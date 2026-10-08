"""
LangGraph orchestration for one agent turn.

Before this module existed, a turn went straight into the tool-calling loop: the model was handed
the tool catalog on the first call and left to decide, every time, whether the user wanted a
concept explanation or an experiment. That made the agent "dumb" in two visible ways:

* a concept question ("what is a Kalman filter?") still spun up tool calls it did not need;
* a vague experiment request ("run something") guessed the missing parameters instead of asking.

The loop is now wrapped in a small state graph that routes first and acts second. The graph is
the *orchestration* layer only; the tool loop itself (``agent_loop.advance``) is unchanged and
remains one node of the graph. Splitting the two means the loop stays a plain, well-tested while
loop, while the routing decisions become a named, drawable, re-playable graph — the same shape
QueryMind (the text-to-SQL reference project) uses, with its SQL-specific nodes swapped for
simulation ones.

Nodes:

* ``supervisor``     — one JSON call that decides which specialist the turn is handed to, and why
* ``responder``      — the librarian's material plus a tool-free answer to a concept question
* ``executor``       — delegate to the existing tool-calling loop
* ``planner``        — design a multi-step experiment for an exploratory goal, then pause for one
  approval of the whole sequence
* ``clarifier``      — ask back for the missing piece instead of guessing
* ``analyst``        — read the run's metrics into a structured, evidence-checked artifact
* ``critic``         — audit the result and the agent's own words before the turn ends

**This is a supervisor with specialists, not one model doing five jobs.** Each specialist has one
responsibility, one prompt, and — where it matters — a different *tool power*: the responder and the
analyst are offered no tool channel at all (the analyst calls ``complete``, which cannot carry
tools), while only the executor may act on the simulation. Splitting them is what makes those
powers structural, instead of a paragraph in a prompt asking the model not to drift. The shared
blackboard is the session itself: every specialist reads and writes the same object, which is
already the durable store, so no third state machine is introduced.

``analyze_turn`` and ``reflect_turn`` are module-level rather than only graph nodes because the turn
after a confirmation approval does not travel through the graph (``resolve_decision`` runs the
approved batch and then continues inside the loop). The decision endpoints therefore invoke both
explicitly, and the graph nodes call the very same functions.

Clarification is deliberately "ask a question and end the turn" rather than a LangGraph
``interrupt`` with checkpoint resume. The session is already the durable source of truth and is
persisted to MySQL after every turn, so the user answering the question next turn *is* the resume.
An ``interrupt`` + ``Command(resume=...)`` would add a second state machine and a checkpoint store
on top of that, for no user-visible gain here. That mechanism earns its keep when the graph must
resume precisely mid-node (e.g. replayed in an evaluation harness), which the evaluation suite
turned out not to need either — see ``evals/README.md``.

The streaming sink (``on_event``) is captured by closure rather than carried in the graph state:
LangGraph's state is a data channel, and a callable is not data. Each turn compiles a fresh graph
with the turn's sink bound in, which costs microseconds and keeps the state clean.
"""

from __future__ import annotations

import json
from typing import Any, NamedTuple, TypedDict

from langgraph.graph import END, START, StateGraph

from .agent_loop import EventSink, advance, emit_into
from .conversation import (
    ToolCallRecord,
    assistant_message,
    context_window,
    last_user_text,
    now_iso,
)
from .domain_tools import CONFIG_SUMMARY_KEYS, PLANNABLE_TOOLS
from .knowledge import citations, render_context, retrieve
from .model_gateway import ModelCredential, ModelGatewayError, complete, stream_call_with_tools
from .model_planner import parse_json_object
from .models import AgentSession, ExperimentSequence, PendingDecision
from .reflection import (
    deterministic_self_check,
    final_narrative,
    merge_issues,
    reflect_on_result,
)
from .result_analysis import analyze_result, analyze_with_model


# The router decides which node handles the user's message. The actions map onto the reference
# project's intent split (there: answer / query / clarify), plus an exploratory route that designs
# a multi-step experiment rather than executing a single action.
CONCEPT_QA = "concept_qa"
EXPERIMENT = "experiment"
EXPLORE = "explore"
CLARIFY = "clarify"

ROUTED_ACTIONS = frozenset({CONCEPT_QA, EXPERIMENT, EXPLORE, CLARIFY})

# Which specialist each route hands the turn to. Named separately from the route because they answer
# different questions: the route is *what the user wants*, the role is *who does the work*. The role
# name travels in the event payload so the coordination is legible in the trail without reading code.
SPECIALISTS = {
    CONCEPT_QA: "responder",
    EXPERIMENT: "executor",
    EXPLORE: "planner",
    CLARIFY: "clarifier",
}

# Why the supervisor routed this way. The model is asked for its own one-line reason; these are the
# fallbacks, used on rule mode, on a failed call, and whenever the model's reason is missing — a
# handoff with no stated reason is worse than a generic one.
ROUTING_FALLBACK = {
    CONCEPT_QA: "问的是概念或方法，不需要运行仿真",
    EXPERIMENT: "要的是一次具体操作",
    EXPLORE: "目标需要多次运行才能回答",
    CLARIFY: "关键信息缺失，先问清楚再动手",
}


# NOTE: the phrase "意图路由" is a wire contract, not decoration. The stub provider used by the
# end-to-end scripts and the tests recognises a supervisor call by it, so it has to stay in this
# prompt; a self-describing phrase would be better than a keyword, but the alternative is a marker
# the prompt never uses at all (which is what the knowledge/analysis block headers do).
CLASSIFY_SYSTEM_PROMPT = """你是 FusionPilot（一体化雷达与电子对抗仿真平台）智能助手的主管（supervisor），负责意图路由与分派。你要判断用户这句话该交给团队里哪位专员处理，只返回 JSON。

四位专员：
1. "concept_qa" → 交给"应答专员"：用户问概念、原理、方法、术语解释，或让你比较/分析算法本身，而不要求跑新的仿真。
   例如"什么是卡尔曼滤波""加权平均和最近邻融合有什么区别""跟踪率是怎么算的"。这类直接回答，不要调用工具。
2. "experiment" → 交给"执行专员"：用户要一次具体的操作——改一个配置、跑一次仿真、读一次结果。
   例如"把目标数改成5""跑一次看看""读一下上次的指标"。
3. "explore" → 交给"规划专员"：用户给的是一个探索性目标，需要跑多个实验才能回答（对比不同算法或参数、找增益、
   做敏感性分析），而不是一次改配置跑一次。
   例如"对比卡尔曼滤波和加权平均在5目标场景的精度""看看资源数从2加到4对等待时间的影响"
   "帮我找出这个场景下最好的融合方法"。这类会先规划一个多步实验序列，让用户一次确认后连续执行。
4. "clarify" → 交给"澄清专员"：用户想做实验，但关键信息缺失、且澄清会显著改变执行，需要先反问。
   注意：会话已有工作配置时，普通一句"跑一下"用当前配置即可，不必澄清；只有当意图本身有歧义
   （比如"帮我优化一下"没说优化哪个指标、"对比一下"没说对比什么策略）时才澄清。

返回 JSON：
{"action": "concept_qa|experiment|explore|clarify", "because": "一句话说明为什么这么分派（中文，20 字以内）", "question": "仅 clarify 时填写，一句简短的反问"}

只返回 JSON，不要任何其他内容。"""


CONCEPT_SYSTEM_PROMPT = """你是 FusionPilot（一体化雷达与电子对抗仿真平台）的仿真助手。用户问的是概念、原理或方法，不需要你运行仿真。

你会拿到一段【知识库】摘录——它是本平台的权威参考材料，由平台代码与领域约定整理而来。回答规则：
- 只依据【知识库】回答。摘录里没有的内容，就说现有资料里没有这一部分，不要用一般性常识补齐。
- 特别注意本平台特有的边界，不要把平台描述得比资料更完备。例如：融合层能直接拿到目标真值状态，
  因此除卡尔曼滤波外上报的速度不是估计量；一次运行的指标只是单个随机种子上的一个样本，不能据此
  给方法排序；卡尔曼滤波的过程噪声是假设值而非标定值。
- 不要编造任何仿真数值，也不要假装你刚跑过实验——你没有调用任何工具，就没有任何结果可引用。
- 引用到具体小节时，可以在句末用「（见《小节标题》）」的形式标出来源。
- 用用户的语言，简洁（2-4 句为主，除非用户明确要详细展开）。
- 不要调用工具。"""


# Recorded on a grounded answer so the transcript shows what the answer was allowed to use. When the
# corpus has nothing for the question the list is empty, which is itself the fact worth showing.
KNOWLEDGE_ABSENT_NOTE = "平台资料中没有与这个问题对应的小节。"

# The headers the retrieved material is injected under. They are contracts, not cosmetics: the mock
# provider and the end-to-end check detect grounding by their presence, and the prompts mention the
# material in prose ("你会拿到一段【知识库】摘录") without ever producing these exact lines. A prose
# mention therefore cannot be mistaken for material that was actually retrieved.
KNOWLEDGE_BLOCK_HEADER = "## 知识库"
REFERENCE_BLOCK_HEADER = "## 参考材料"


PLANNER_SYSTEM_PROMPT = """你是 FusionPilot（雷达与电子对抗仿真平台）的实验规划器。用户给了一个探索性目标，你设计一个多步实验序列来回答它。

可用工具，每一步必须用其中之一：
- update_experiment_config：改配置，arguments 形如 {"patch": {"fusionMethod": "KALMAN_FILTER"}}。
- run_simulation：用当前配置跑一次仿真并返回指标，arguments 形如 {"reason": "这一步要验证什么"}。
- calculate_metrics：读取最近一次运行的指标。
- validate_experiment：只校验不运行，通常不需要。

规划要求：
- 序列要能直接执行：每次 run_simulation 之前，必须已经有一次 update_experiment_config 把它要用的配置设好（沿用当前配置的第一次运行可以省略）。
- 对比类目标：为每个待对比的配置各安排一次 update + 一次 run。
- 步骤精简，通常 3-6 步；不要安排重复或多余的步骤。
- 字段名和枚举值必须与平台一致（见下方参考材料）。例如融合方法是 KALMAN_FILTER 这种大写枚举名，
  不是中文名；每个字段都有合法取值范围，安排一个超出范围的取值会让整步失败。
- 规划时检查对比是否真的能产生差异：可用资源大于等于目标数时，两种调度策略结果相同，这样的对比
  测不出任何东西。
- 不要编造任何指标数值。你只规划步骤，数值由仿真核心给出。

只返回 JSON：
{"goal": "对目标的简短复述", "rationale": "一句话说明这个序列为什么能回答目标", "steps": [{"summary": "这一步做什么（中文）", "tool": "工具名", "arguments": {}}]}

只返回 JSON，不要任何其他内容。"""


async def plan_experiment(
    session: AgentSession,
    credential: ModelCredential | None,
) -> ExperimentSequence | None:
    """
    Ask the model to design a multi-step sequence for an exploratory goal.

    Returns ``None`` when there is no model, the call fails, or every proposed step names an
    unknown tool — the caller then falls back to the ordinary tool loop, so a failed plan degrades
    to "do the obvious single step" rather than to nothing.
    """
    if credential is None:
        return None

    goal = last_user_text(session.messages)
    working = {key: session.working_config.get(key) for key in CONFIG_SUMMARY_KEYS if key in session.working_config}
    system_prompt = PLANNER_SYSTEM_PROMPT
    # The planner is the step that can do the most damage by guessing: a step that names a field
    # value the Java core rejects fails the whole sequence. Handing it the same reference material
    # the concept route uses is what keeps an enum spelling and a valid range from being invented.
    hits = retrieve(goal)
    if hits:
        system_prompt += f"\n\n{REFERENCE_BLOCK_HEADER}（字段取值与方法语义以这里为准）\n" + render_context(hits)
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps({"goal": goal, "working_config": working}, ensure_ascii=False),
        },
    ]
    try:
        content = await complete(messages, credential)
        parsed = parse_json_object(content)
        sequence = ExperimentSequence.model_validate(
            {
                "goal": str(parsed.get("goal") or last_user_text(session.messages))[:500],
                "rationale": str(parsed.get("rationale") or "")[:500],
                "steps": parsed.get("steps") or [],
                "produced_by": f"{credential.provider}:{credential.model}",
            }
        )
    except (ModelGatewayError, json.JSONDecodeError, ValueError):
        return None

    # Only tools that *do* something may appear in a sequence; a plan step that merely reads
    # documentation would sit in the approved batch doing nothing.
    sequence.steps = [step for step in sequence.steps if step.tool in PLANNABLE_TOOLS]
    if not sequence.steps:
        return None
    return sequence


class TurnState(TypedDict, total=False):
    """State passed through the turn graph. ``session`` is the mutable conversation; everything
    else is per-turn routing context. Nothing here is persisted by LangGraph — the session snapshot
    is the only durable store."""

    session: AgentSession
    credential: ModelCredential | None
    authorization: str | None
    intent_action: str
    clarification_question: str | None
    # Set by the executor node: whether this turn produced a fresh result, which is what earns the
    # turn a reading from the analyst.
    produced_result: bool


class SupervisorDecision(NamedTuple):
    """
    Where the supervisor hands the turn, and why.

    A named tuple rather than a bare tuple so the call sites read as ``decision.action`` instead of
    ``parts[0]``, and so adding a field later is a visible change rather than a silent index shift.
    """

    action: str
    question: str | None
    because: str

    @property
    def specialist(self) -> str:
        return SPECIALISTS.get(self.action, "executor")


async def classify_intent(
    session: AgentSession,
    credential: ModelCredential | None,
) -> SupervisorDecision:
    """
    Decide which specialist handles the user's latest message.

    The handoff always carries a reason, because a coordination decision nobody can inspect is the
    part of a multi-agent system that rots first. The model supplies its own one-line reason; a
    per-route fallback covers rule mode, a failed call, and a model that omits it.

    When no model credential is available (rule mode) or the classification call fails, the safe
    handoff is the executor: the tool loop handles it, and a model failure surfaces normally inside
    the loop rather than being masked by a wrong route.
    """
    if credential is None:
        return SupervisorDecision(EXPERIMENT, None, ROUTING_FALLBACK[EXPERIMENT])

    working = {key: session.working_config.get(key) for key in CONFIG_SUMMARY_KEYS if key in session.working_config}
    payload: dict[str, Any] = {"message": last_user_text(session.messages), "working_config": working}
    if session.last_result and session.last_result.get("metrics"):
        payload["last_run_metrics"] = session.last_result["metrics"]

    messages = [
        {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        content = await complete(messages, credential)
        parsed = parse_json_object(content)
    except (ModelGatewayError, json.JSONDecodeError, ValueError):
        return SupervisorDecision(EXPERIMENT, None, ROUTING_FALLBACK[EXPERIMENT])

    action = str(parsed.get("action") or "").strip()
    if action not in ROUTED_ACTIONS:
        return SupervisorDecision(EXPERIMENT, None, ROUTING_FALLBACK[EXPERIMENT])

    because = str(parsed.get("because") or "").strip()[:120] or ROUTING_FALLBACK[action]
    if action == CLARIFY:
        question = str(parsed.get("question") or "").strip()
        if not question:
            return SupervisorDecision(EXPERIMENT, None, ROUTING_FALLBACK[EXPERIMENT])
        return SupervisorDecision(CLARIFY, question, because)
    return SupervisorDecision(action, None, because)


async def reflect_turn(
    session: AgentSession,
    credential: ModelCredential | None,
    on_event: EventSink | None = None,
) -> None:
    """
    Check the turn's own output before it is handed back.

    Skipped when the turn is waiting on a confirmation (there is no result yet) or produced no
    metrics. The deterministic layer always runs and is free; the model layer runs only when the
    agent actually said something about a result, so a turn that merely read the configuration pays
    nothing.

    This lives at module level rather than only inside the graph node because **the turn after a
    confirmation approval does not go through the graph**: ``resolve_decision`` runs the approved
    batch and then continues in the loop, so the ``run_experiment`` node — and its ``reflect`` edge
    — is never re-entered. Keeping the check inside the node meant the one turn that interprets a
    result the user just approved was the one turn nothing audited. An evaluation case caught it;
    reading the graph would not have.
    """
    emit = emit_into(session, on_event)
    if session.pending is not None:
        return
    if not (session.last_result or {}).get("metrics"):
        return

    deterministic = deterministic_self_check(session)
    model_issues: list[str] = []
    narrative = final_narrative(session)
    if credential is not None and narrative:
        try:
            outcome = await reflect_on_result(session, narrative, credential)
        except (ModelGatewayError, json.JSONDecodeError, ValueError):
            # Reflection is best-effort: a failure to audit must not fail the turn. A provider that
            # answers the audit with prose instead of JSON raises a decode error rather than a
            # gateway error, and that is still a failure to audit — not a failure of the turn.
            outcome = None
        if outcome is not None and not outcome.supported:
            if outcome.problem:
                model_issues.append(outcome.problem)
            if outcome.correction:
                correction = assistant_message(outcome.correction, [])
                correction.produced_by = f"reflect:{credential.provider}:{credential.model}"
                session.messages.append(correction)
                emit(
                    "self_correction",
                    {"problem": outcome.problem, "correction": outcome.correction},
                )

    issues = merge_issues(deterministic, model_issues)
    emit("self_check", {"ok": not issues, "issues": issues})


async def analyze_turn(
    session: AgentSession,
    credential: ModelCredential | None,
    produced_result: bool,
    on_event: EventSink | None = None,
) -> None:
    """
    The analyst specialist: read the newest run into a structured artifact.

    Interpreting a result is the step with the strictest fact discipline, and in the single-agent
    version it competed for the model's attention with choosing the next tool, respecting the
    confirmation gate and narrating progress. Promoting it to a role buys three things that were
    otherwise only good intentions:

    * **No tool channel.** This calls ``complete``, which cannot carry tools, so the analyst cannot
      run anything, change anything, or "verify" a claim by acting. That is a structural boundary
      rather than a prompt asking it to behave.
    * **The fact-discipline prompt**, not the general operating prompt.
    * **An artifact, not prose.** ``session.analysis`` is persisted with the snapshot and can be
      asserted on mechanically — prose can only be read.

    ``analyze_with_model`` already drops any evidence row naming a metric the run never returned, so
    the role inherits a real defence against inventing a metric name.

    ``produced_result`` gates the cost: a turn that merely re-read the configuration, or asked about
    a previous run, must not pay for a fresh reading. Falling back to the deterministic reading keeps
    the artifact present when the model is unavailable, and says so in the limitations.
    """
    if not produced_result:
        return
    result = session.last_result or {}
    if not result.get("metrics"):
        return

    emit = emit_into(session, on_event)
    if credential is None:
        analysis = analyze_result(result)
    else:
        try:
            analysis = await analyze_with_model(result, session.plan, credential)
        except (ModelGatewayError, json.JSONDecodeError, ValueError):
            # Best-effort like reflection: a failed reading must not fail the turn, and the
            # deterministic reading is plain but truthful. Unparseable JSON is caught alongside the
            # gateway failure because a provider that answers with prose is a failure of this step,
            # not of the user's turn — the same hole reflection had.
            fallback = analyze_result(result)
            analysis = fallback.model_copy(
                update={
                    "limitations": fallback.limitations
                    + ["解读模型调用失败，这里只有结构化指标的直读结果，没有模型解读。"]
                }
            )

    session.analysis = analysis
    emit(
        "analysis_ready",
        {
            "role": "analyst",
            "produced_by": analysis.produced_by,
            "summary": analysis.summary,
            "evidence": analysis.evidence,
            "limitations": analysis.limitations,
            "metric_count": len(analysis.metrics),
        },
    )


def build_turn_graph(on_event: EventSink | None = None) -> StateGraph:
    """Compile the turn graph with ``on_event`` bound into every node's closure."""

    def _route(state: TurnState) -> str:
        return state["intent_action"]

    async def _supervisor(state: TurnState) -> dict[str, Any]:
        session = state["session"]
        # Transient UI hint only: routing takes one model call, and without this the user watches
        # a blank stage. Not persisted — "the turn started" is not worth a trail entry.
        if on_event is not None:
            on_event("understanding_query", {})
        emit = emit_into(session, on_event)
        decision = await classify_intent(session, state.get("credential"))
        # The role name and the reason ride along with the route, so the coordination decision is
        # readable in the stored trail without re-deriving it from the code.
        emit(
            "intent_classified",
            {
                "action": decision.action,
                "question": decision.question,
                "because": decision.because,
                "handoff_to": decision.specialist,
            },
        )
        return {"intent_action": decision.action, "clarification_question": decision.question}

    async def _answer_concept(state: TurnState) -> dict[str, Any]:
        """
        Answer a concept question from the platform's own reference material.

        The material is retrieved before the call and placed in the system prompt, so the answer is
        grounded in text written from the Java core instead of the model's priors about radar
        simulation. This matters because the platform's *departures* from the textbook (the fusion
        layer sees the ground truth, one seed is one sample) are exactly what a model gets wrong if
        left to itself.
        """
        session = state["session"]
        credential = state["credential"]
        assert credential is not None  # concept_qa only routes when a model is available
        emit = emit_into(session, on_event)

        question = last_user_text(session.messages)
        hits = retrieve(question)
        system_prompt = CONCEPT_SYSTEM_PROMPT
        if hits:
            system_prompt = f"{system_prompt}\n\n{KNOWLEDGE_BLOCK_HEADER}\n{render_context(hits)}"
        emit(
            "knowledge_retrieved",
            {
                "query": question[:200],
                "matches": citations(hits),
                "grounded": bool(hits),
            },
        )

        kept, _digest = context_window(session.messages)
        text_parts: list[str] = []
        async for event in stream_call_with_tools(system_prompt, kept, [], credential):
            if event.kind == "text":
                text_parts.append(event.text)
                emit("token", {"text": event.text})

        message = assistant_message("".join(text_parts), [])
        message.produced_by = f"{credential.provider}:{credential.model}"
        message.knowledge = citations(hits)
        session.messages.append(message)
        session.status = "ACTIVE"
        emit(
            "assistant_message",
            {
                "has_text": True,
                "tool_names": [],
                "step": 1,
                "route": CONCEPT_QA,
                "knowledge_count": len(hits),
            },
        )
        emit("turn_completed", {"steps": 1, "route": CONCEPT_QA})
        return {}

    async def _run_experiment(state: TurnState) -> dict[str, Any]:
        """
        Hand the turn to the executor and report whether it produced a new result.

        The flag is what keeps the analyst from being paid for on a turn that only read the
        configuration or asked about a previous run. It is measured rather than inferred: any run or
        comparison increments the tool-call count, and metrics only exist once something ran.
        """
        session = state["session"]
        calls_before = session.tool_call_count
        await advance(
            session,
            state.get("credential"),
            state.get("authorization"),
            on_event=on_event,
        )
        produced = session.tool_call_count > calls_before and bool((session.last_result or {}).get("metrics"))
        return {"produced_result": produced}

    async def _plan_experiment(state: TurnState) -> dict[str, Any]:
        """
        Design a multi-step experiment for an exploratory goal, then pause for one approval.

        The whole sequence is held as a single pending batch: approving it runs every step in order
        under one confirmation, so a three-config comparison is one approval rather than three.
        """
        session = state["session"]
        credential = state.get("credential")
        emit = emit_into(session, on_event)

        sequence = await plan_experiment(session, credential)
        if sequence is None:
            # No usable plan; fall back to the ordinary loop rather than stalling the turn.
            await advance(session, credential, state.get("authorization"), on_event=on_event)
            return {}

        session.sequence = sequence
        calls = [
            ToolCallRecord(call_id=f"plan_{index}", name=step.tool, arguments=step.arguments)
            for index, step in enumerate(sequence.steps)
        ]
        prompt = sequence.goal + (f"：{sequence.rationale}" if sequence.rationale else "")
        session.pending = PendingDecision(tool_calls=calls, prompt=prompt, created_at=now_iso())
        session.status = "AWAITING_CONFIRMATION"
        emit(
            "plan_created",
            {
                "goal": sequence.goal,
                "rationale": sequence.rationale,
                "steps": [step.model_dump() for step in sequence.steps],
                "produced_by": sequence.produced_by,
            },
        )
        emit(
            "confirmation_requested",
            {"tool_names": [call.name for call in calls], "prompt": prompt, "is_plan": True},
        )
        return {}

    async def _analysis(state: TurnState) -> dict[str, Any]:
        """The analyst's graph entry point; see ``analyze_turn`` for the rules."""
        await analyze_turn(
            state["session"],
            state.get("credential"),
            bool(state.get("produced_result")),
            on_event,
        )
        return {}

    async def _reflect(state: TurnState) -> dict[str, Any]:
        """The graph's own invocation of ``reflect_turn``; see that function for the rules."""
        await reflect_turn(state["session"], state.get("credential"), on_event)
        return {}

    async def _ask_clarify(state: TurnState) -> dict[str, Any]:
        session = state["session"]
        credential = state.get("credential")
        question = state.get("clarification_question") or "能再具体一点吗？"
        emit = emit_into(session, on_event)

        message = assistant_message(question, [])
        message.produced_by = f"{credential.provider}:{credential.model}" if credential else "rule"
        session.messages.append(message)
        session.status = "ACTIVE"
        emit("clarification_requested", {"question": question})
        emit("assistant_message", {"has_text": True, "tool_names": [], "step": 1, "route": CLARIFY})
        emit("turn_completed", {"steps": 1, "route": CLARIFY})
        return {}

    def _after_executor(state: TurnState) -> str:
        """Only a turn that actually produced a result is worth a reading."""
        return "analyst" if state.get("produced_result") else "critic"

    builder = StateGraph(TurnState)
    # Node names are the specialists, not the routes: the graph should read as the team's
    # coordination, so a reader can see who does what without decoding the route vocabulary.
    builder.add_node("supervisor", _supervisor)
    builder.add_node("responder", _answer_concept)
    builder.add_node("executor", _run_experiment)
    builder.add_node("planner", _plan_experiment)
    builder.add_node("clarifier", _ask_clarify)
    builder.add_node("analyst", _analysis)
    builder.add_node("critic", _reflect)
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        _route,
        {
            CONCEPT_QA: "responder",
            EXPERIMENT: "executor",
            EXPLORE: "planner",
            CLARIFY: "clarifier",
        },
    )
    builder.add_edge("responder", END)
    # executor -> analyst (only when a result exists) -> critic. The critic audits the closing prose
    # against the facts; the analyst supplies the structured reading the prose can be compared with.
    builder.add_conditional_edges(
        "executor",
        _after_executor,
        {"analyst": "analyst", "critic": "critic"},
    )
    builder.add_edge("analyst", "critic")
    builder.add_edge("critic", END)
    # A plan pauses for one approval; the decision endpoint executes the batch and the loop then
    # returns to interpret the results, so this node ends the turn rather than continuing.
    builder.add_edge("planner", END)
    builder.add_edge("clarifier", END)
    return builder.compile()


async def run_turn(
    session: AgentSession,
    credential: ModelCredential | None,
    authorization: str | None,
    on_event: EventSink | None = None,
) -> None:
    """
    Run one turn through the routed graph.

    This is the entry the HTTP layer calls in place of the raw loop. ``on_event`` is the streaming
    sink; when it is present every node forwards its progress live, exactly as the loop did.
    """
    graph = build_turn_graph(on_event)
    await graph.ainvoke(
        {
            "session": session,
            "credential": credential,
            "authorization": authorization,
        }
    )
