"""
Tests for domain knowledge retrieval.

Three things are worth pinning, and they fail in different ways:

* **Tokenisation.** If the CJK lexicon or the ``snake_case`` handling breaks, retrieval does not
  error — it quietly returns the wrong section, and the agent then answers confidently from the
  wrong material. Silent, so it needs a test.
* **Ranking.** The same failure again: a plausible-looking but wrong top hit. The cases below are
  the questions the agent is actually asked.
* **The graph wiring.** Retrieval can be perfect and still not be used, because a node forgot to
  pass the material into the prompt. That is asserted by inspecting the prompt the node sends.

The ordering assertions run against the bundled corpus, so they double as a check that the corpus
still covers what the prompts promise. A synthetic corpus is used for the scoring mechanics, where
the point is the arithmetic rather than the content.
"""

import asyncio
import json

import pytest

from app.agent_graph import CONCEPT_QA, SupervisorDecision, run_turn
from app.conversation import AgentMessage
from app.domain_tools import (
    PLANNABLE_TOOLS,
    ToolContext,
    execute_tool,
    needs_confirmation,
)
from app.knowledge import (
    KnowledgeChunk,
    KnowledgeIndex,
    citations,
    cjk_tokens,
    corpus_directory,
    get_index,
    load_corpus,
    parse_document,
    render_context,
    retrieve,
    tokenize,
)
from app.model_gateway import ModelStreamEvent, resolve_credential
from app.session_store import session_store


OWNER = 6161


def default_config() -> dict:
    return {
        "scenarioName": "multi-target-demo",
        "targetCount": 3,
        "simulationSteps": 12,
        "timeStepSeconds": 1.0,
        "availableResources": 2,
        "fusionMethod": "WEIGHTED_AVERAGE",
        "schedulingPolicy": "ROUND_ROBIN",
        "randomSeed": 20260928,
        "observationSources": [],
    }


def credential():
    return resolve_credential("openai", "gpt-4o-mini", "user-token")


def new_session(prompt: str = "什么是卡尔曼滤波"):
    session_store.drop_for_user(OWNER)
    session = session_store.create(
        owner_user_id=OWNER,
        default_config=default_config(),
        provider="openai",
        model="gpt-4o-mini",
    )
    session.messages.append(AgentMessage(role="user", content=prompt))
    return session


def top_label(query: str) -> str:
    hits = retrieve(query)
    assert hits, f"expected a match for {query!r}"
    return hits[0].chunk.label


# --------------------------------------------------------------------------- tokenisation


def test_snake_case_enum_names_stay_whole_and_also_split():
    tokens = tokenize("set fusionMethod to WEIGHTED_AVERAGE")
    assert "weighted_average" in tokens
    # The parts matter too: a question about "average position error" contains neither the enum
    # name nor a phrase the corpus lists verbatim.
    assert "weighted" in tokens
    assert "average" in tokens
    assert "fusionmethod" in tokens


def test_cjk_lexicon_terms_are_recognised():
    tokens = tokenize("卡尔曼滤波和加权平均的区别")
    assert "卡尔曼滤波" in tokens
    assert "加权平均" in tokens


def test_cjk_bigrams_cover_words_outside_the_lexicon():
    # "性能" is not in the lexicon, so only the bigram can match it.
    assert "性能" in cjk_tokens("平台性能如何")


def test_function_words_are_dropped_but_entities_kept():
    tokens = tokenize("请问这个卡尔曼滤波是怎么回事")
    assert "卡尔曼滤波" in tokens
    assert "什么" not in tokens
    assert "请问" not in tokens
    assert "这个" not in tokens


# --------------------------------------------------------------------------- document parsing


SAMPLE = """---
doc: sample-doc
title: 样例标题
tags: 标签一, sample
---

## 卡尔曼滤波 KALMAN_FILTER kalman filter

卡尔曼滤波的正文。

## 指标总览 五个聚合指标

指标正文。
"""


def test_front_matter_supplies_the_document_key_and_tags():
    chunks = parse_document(SAMPLE, fallback_doc="ignored")
    assert {chunk.doc for chunk in chunks} == {"sample-doc"}
    assert all(chunk.tags == ("标签一", "sample") for chunk in chunks)


def test_each_section_becomes_its_own_chunk():
    chunks = parse_document(SAMPLE, fallback_doc="ignored")
    assert len(chunks) == 2
    assert chunks[0].text == "卡尔曼滤波的正文。"
    # The heading keeps its latin aliases (they are retrieval signal) …
    assert chunks[0].title == "卡尔曼滤波 KALMAN_FILTER kalman filter"
    # … while the display label drops them.
    assert chunks[0].label == "卡尔曼滤波"


def test_section_ids_are_readable_and_unique():
    chunks = parse_document(SAMPLE, fallback_doc="ignored")
    ids = [chunk.chunk_id for chunk in chunks]
    assert ids[0] == "sample-doc#kalman_filter"
    assert len(set(ids)) == len(ids)


def test_a_section_without_a_heading_is_not_indexed():
    assert parse_document("---\ndoc: x\n---\n\n正文但没有小节标题。\n", fallback_doc="x") == []


def test_a_missing_corpus_directory_yields_no_chunks(tmp_path):
    assert load_corpus(tmp_path / "does-not-exist") == []


# --------------------------------------------------------------------------- the bundled corpus


def test_the_bundled_corpus_is_present_and_parsed():
    # A parse failure would silently disable grounding rather than raise, so this asserts the
    # corpus is actually there. It is the corpus promised by the concept prompt.
    index = get_index()
    assert len(index) >= 25
    assert all(chunk.text.strip() for chunk in index.chunks)
    assert corpus_directory().name == "knowledge"


# --------------------------------------------------------------------------- ranking


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("什么是卡尔曼滤波", "卡尔曼滤波"),
        ("卡尔曼滤波和加权平均有什么区别", "卡尔曼滤波"),
        ("跟踪率是怎么算的", "跟踪率"),
        ("定位精度这个指标怎么理解", "平均位置误差"),
        ("为什么两次跑结果一模一样，是不是缓存了", "确定性复现"),
        ("资源利用率一直是1说明什么", "资源利用率"),
        ("轮询和优先级有什么不同", "优先级"),
        ("平均等待时间的单位是什么", "平均等待时间"),
        ("观测源的时延是怎么影响结果的", "观测时延"),
        ("调度切换次数是什么", "调度切换次数"),
        ("融合层上报的速度是估计值吗", "融合层的真值输入"),
    ],
)
def test_the_intended_section_ranks_first(query, expected):
    assert top_label(query) == expected


@pytest.mark.parametrize(
    ("query", "fact"),
    [
        # The point of retrieval is not a title match, it is that the material handed to the model
        # contains the fact the answer needs. These three are the platform's known departures from
        # the textbook — exactly where a model left to itself answers plausibly and wrongly.
        ("可用资源设成多少才能让两种调度策略不一样", "相同的指标"),
        ("为什么两次跑结果一模一样，是不是缓存了", "被缓存"),
        ("融合层上报的速度是估计值吗", "不是估计量"),
        ("卡尔曼滤波的过程噪声是怎么定的", "过程噪声取一个固定值"),
    ],
)
def test_the_retrieved_material_contains_the_fact_needed_to_answer(query, fact):
    assert fact in render_context(retrieve(query))


def test_an_english_query_reaches_the_same_section():
    assert top_label("What does KALMAN_FILTER estimate?") == "卡尔曼滤波"


def test_a_question_outside_the_domain_matches_nothing():
    # The agent relies on this: an empty result is what tells it to say it has no material instead
    # of answering from general knowledge.
    assert retrieve("今天天气怎么样") == []
    assert retrieve("写一首关于春天的诗") == []


def test_results_are_capped_by_the_limit():
    assert len(retrieve("卡尔曼滤波和加权平均有什么区别", limit=1)) == 1


def test_citations_carry_the_source_and_a_score():
    hits = retrieve("什么是卡尔曼滤波")
    rows = citations(hits)
    assert rows
    assert set(rows[0]) == {"chunk_id", "doc", "title", "score"}
    assert rows[0]["title"] == "卡尔曼滤波"
    assert rows[0]["score"] > 0


def test_render_context_numbers_and_labels_every_section():
    rendered = render_context(retrieve("什么是卡尔曼滤波"))
    assert rendered.startswith("[1] 《")
    assert "卡尔曼滤波" in rendered


def test_render_context_of_nothing_is_empty():
    assert render_context([]) == ""


# --------------------------------------------------------------------------- scoring mechanics


def synthetic_index() -> KnowledgeIndex:
    return KnowledgeIndex(
        [
            KnowledgeChunk(
                chunk_id="a#one",
                doc="a",
                title="阿尔法 alpha",
                label="阿尔法",
                tags=("先验",),
                text="阿尔法的正文。",
            ),
            KnowledgeChunk(
                chunk_id="b#two",
                doc="b",
                title="贝塔 beta",
                label="贝塔",
                tags=(),
                text="贝塔的正文，正文里也提到一次阿尔法。",
            ),
        ]
    )


def test_a_title_match_wins_over_a_body_only_match():
    """
    The section *about* a term must beat a section that merely mentions it.

    The body-only section is not merely ranked lower, it is dropped: the heading boost pushes it
    below ``RELATIVE_FLOOR``. That is the intended behaviour — this is the mechanism that keeps a
    generic "how to read the metrics" section out of an answer about one specific metric.
    """
    hits = synthetic_index().search("阿尔法")
    assert [hit.chunk.chunk_id for hit in hits] == ["a#one"]


def test_similarly_relevant_sections_are_both_returned():
    """The floor trims the tail, it does not reduce every query to a single hit."""
    index = KnowledgeIndex(
        [
            KnowledgeChunk(
                chunk_id="a#one",
                doc="a",
                title="阿尔法 alpha",
                label="阿尔法",
                tags=(),
                text="阿尔法的正文。",
            ),
            KnowledgeChunk(
                chunk_id="b#two",
                doc="b",
                title="阿尔法贝塔 alpha beta",
                label="阿尔法贝塔",
                tags=(),
                text="阿尔法贝塔的正文。",
            ),
        ]
    )
    hits = index.search("阿尔法")
    assert {hit.chunk.chunk_id for hit in hits} == {"a#one", "b#two"}


def test_a_term_absent_from_the_corpus_matches_nothing():
    assert synthetic_index().search("伽马") == []


def test_an_empty_query_matches_nothing():
    assert synthetic_index().search("") == []
    assert synthetic_index().search("   ") == []


def test_an_empty_index_is_safe():
    assert KnowledgeIndex([]).search("阿尔法") == []


# --------------------------------------------------------------------------- the tool surface


def test_search_knowledge_is_available_and_never_needs_confirmation():
    assert needs_confirmation("search_knowledge") is False


def test_the_planner_may_not_spend_a_step_on_a_lookup():
    # A plan step that only reads documentation would sit in the approved batch doing nothing.
    assert "search_knowledge" not in PLANNABLE_TOOLS
    assert "run_simulation" in PLANNABLE_TOOLS


def test_the_search_tool_returns_an_excerpt_and_matches():
    context = ToolContext(working_config=default_config())
    outcome = asyncio.run(execute_tool("search_knowledge", {"query": "卡尔曼滤波"}, context, None))
    assert outcome.ok is True
    assert outcome.summary["matches"][0]["title"] == "卡尔曼滤波"
    assert "卡尔曼滤波" in outcome.summary["excerpt"]


def test_the_search_tool_reports_an_empty_lookup_as_success():
    context = ToolContext(working_config=default_config())
    outcome = asyncio.run(execute_tool("search_knowledge", {"query": "今天天气怎么样"}, context, None))
    # Reported as ok so the model reads it as "no material", not as "the tool is broken, retry".
    assert outcome.ok is True
    assert outcome.summary["matches"] == []
    assert "no material" in outcome.summary["note"]


def test_the_search_tool_rejects_an_empty_query():
    context = ToolContext(working_config=default_config())
    outcome = asyncio.run(execute_tool("search_knowledge", {"query": "  "}, context, None))
    assert outcome.ok is False
    assert "query" in outcome.error


# --------------------------------------------------------------------------- graph wiring


def test_a_concept_answer_is_grounded_in_the_corpus(monkeypatch):
    seen: dict = {}

    async def fake_classify(session, cred):
        return SupervisorDecision(CONCEPT_QA, None, "test route")

    async def fake_stream(system_prompt, messages, tools, cred):
        seen["system_prompt"] = system_prompt
        yield ModelStreamEvent("text", text="卡尔曼滤波是唯一估计速度的方法。")

    monkeypatch.setattr("app.agent_graph.classify_intent", fake_classify)
    monkeypatch.setattr("app.agent_graph.stream_call_with_tools", fake_stream)

    session = new_session("什么是卡尔曼滤波")
    asyncio.run(run_turn(session, credential(), "Bearer test"))

    # The material reached the prompt, not just the event stream.
    assert "## 知识库" in seen["system_prompt"]
    assert "唯一真正估计速度" in seen["system_prompt"]

    assistant = [message for message in session.messages if message.role == "assistant"]
    assert len(assistant) == 1
    # Sources are kept on the message so a reloaded transcript still shows them.
    assert assistant[0].knowledge
    assert assistant[0].knowledge[0]["title"] == "卡尔曼滤波"

    events = [event.event_type for event in session.events]
    assert "knowledge_retrieved" in events
    retrieved = next(event for event in session.events if event.event_type == "knowledge_retrieved")
    assert retrieved.payload["grounded"] is True
    assert retrieved.payload["matches"][0]["chunk_id"].startswith("fusion-methods#")


def test_an_unanswerable_concept_question_is_not_grounded(monkeypatch):
    async def fake_classify(session, cred):
        return SupervisorDecision(CONCEPT_QA, None, "test route")

    async def fake_stream(system_prompt, messages, tools, cred):
        yield ModelStreamEvent("text", text="平台资料里没有这一部分。")

    monkeypatch.setattr("app.agent_graph.classify_intent", fake_classify)
    monkeypatch.setattr("app.agent_graph.stream_call_with_tools", fake_stream)

    session = new_session("今天天气怎么样")
    asyncio.run(run_turn(session, credential(), "Bearer test"))

    event = next(event for event in session.events if event.event_type == "knowledge_retrieved")
    assert event.payload["grounded"] is False
    assert event.payload["matches"] == []
    assistant = [message for message in session.messages if message.role == "assistant"]
    assert assistant[0].knowledge == []


def test_the_planner_receives_the_reference_material(monkeypatch):
    from app.agent_graph import plan_experiment

    captured: dict = {}

    async def capture_complete(messages, cred):
        captured["messages"] = messages
        return json.dumps(
            {
                "goal": "对比两种融合方法",
                "rationale": "各跑一次比较位置误差",
                "steps": [
                    {
                        "summary": "设为卡尔曼滤波",
                        "tool": "update_experiment_config",
                        "arguments": {"patch": {"fusionMethod": "KALMAN_FILTER"}},
                    },
                    {"summary": "跑一次", "tool": "run_simulation", "arguments": {"reason": "对比"}},
                ],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("app.agent_graph.complete", capture_complete)

    session = new_session("对比卡尔曼滤波和加权平均在5目标场景的精度")
    sequence = asyncio.run(plan_experiment(session, credential()))

    assert sequence is not None
    system_prompt = captured["messages"][0]["content"]
    # The valid enum value is in front of the planner, which is what stops it inventing one.
    assert "KALMAN_FILTER" in system_prompt
    assert "## 参考材料" in system_prompt


def test_a_plan_step_naming_a_lookup_tool_is_dropped(monkeypatch):
    from app.agent_graph import plan_experiment

    async def capture_complete(messages, cred):
        return json.dumps(
            {
                "goal": "g",
                "rationale": "r",
                "steps": [
                    {"summary": "查资料", "tool": "search_knowledge", "arguments": {"query": "x"}},
                    {"summary": "跑一次", "tool": "run_simulation", "arguments": {"reason": "r"}},
                ],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("app.agent_graph.complete", capture_complete)

    sequence = asyncio.run(plan_experiment(new_session("对比一下"), credential()))
    assert sequence is not None
    assert [step.tool for step in sequence.steps] == ["run_simulation"]
