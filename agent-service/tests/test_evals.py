"""
Tests for the evaluation suite itself.

Two jobs, and the second one is the point:

1. **The bundled cases pass.** A case that has quietly rotted is caught here rather than being
   discovered the next time somebody reads the report and wonders.
2. **The grader fails when it should.** A check nobody has seen fail is not a check. Every
   expectation in the vocabulary gets a deliberately broken run here and is required to report a
   failure — otherwise the whole suite could be passing because it grades nothing.

The grading tests build `Outcome` objects by hand: no HTTP, no model, no Java. That is why the
grader is a pure function.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import evals.harness as harness
from evals.grade import KNOWN_EXPECTATIONS, LIVE_SIGNIFICANT, Check, grade
from evals.harness import DEFAULT_METRICS, LiveModel, Outcome, load_cases, run_case

CASES = load_cases()
CASES_BY_ID = {case["id"]: case for case in CASES}


# --------------------------------------------------------------------------- the bundled cases


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_bundled_case_passes(case):
    outcome = run_case(case)
    checks = grade(case, outcome)
    failures = [check.render().strip() for check in checks if not check.passed]
    assert not failures, "\n".join(failures)


def test_every_expectation_is_exercised_by_a_case():
    """
    No dead checks.

    An expectation key that no case uses is either untested glue or a case someone forgot to write.
    Failing here keeps the vocabulary honest instead of letting it accumulate speculative options.
    """
    used = {key for case in CASES for key in (case.get("expect") or {})}
    assert used == set(KNOWN_EXPECTATIONS), (
        f"unused: {sorted(set(KNOWN_EXPECTATIONS) - used)}; "
        f"unknown: {sorted(used - set(KNOWN_EXPECTATIONS))}"
    )


def test_cases_are_uniquely_named_and_grouped():
    ids = [case["id"] for case in CASES]
    assert len(ids) == len(set(ids))
    for case in CASES:
        assert case.get("group"), f"{case['id']} has no group"
        assert case.get("description"), f"{case['id']} has no description"


def test_the_suite_needs_no_network():
    """
    The harness must not reach the internet.

    It did, until the patch list covered every module holding its own reference to `complete`:
    reflection, memory distillation and result analysis each kept one, so a "scripted" run still
    called a real provider and the suite took twenty seconds instead of a third of a second. The
    runtime is the assertion here because it is the observable consequence.
    """
    import time

    started = time.time()
    outcome = run_case(CASES_BY_ID["concept-grounded-answer-cites-sources"])
    assert outcome.error is None
    assert time.time() - started < 2.0


def test_a_case_that_cannot_run_reports_the_reason_instead_of_raising():
    broken = {"id": "no-route", "group": "x", "description": "d", "message": "hi", "model": {}}
    outcome = run_case(broken)
    assert outcome.error is not None and "route" in outcome.error
    checks = grade(broken, outcome)
    assert [check.name for check in checks] == ["case-completed"]
    assert checks[0].passed is False


def test_case_file_loader_rejects_a_bad_line(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text('{"id": "ok"}\n{not json}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_cases(path)


def test_case_file_loader_rejects_a_case_without_an_id(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text('{"message": "no id"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="no id"):
        load_cases(path)


# --------------------------------------------------------------------------- a builder for broken runs


def outcome_with(**overrides) -> Outcome:
    """
    A synthetic outcome carrying every state the checks read, in one object.

    It is deliberately *not* a plausible single turn — it holds a concept-turn retrieval event next
    to experiment-turn java runs, which no real turn does. The point is to show that each check can
    pass, so the fixture is the union of the states rather than a conversation. Each test below
    breaks exactly one thing about it.
    """
    base = {
        "case_id": "synthetic",
        "session": {
            "status": "ACTIVE",
            "working_config": {"targetCount": 5, "simulationSteps": 12},
            "sequence": {"steps": [{"tool": "run_simulation"}]},
            "last_result": {"metrics": dict(DEFAULT_METRICS)},
            "last_evidence": [{"metric": "trackingRate", "value": 0.98}],
            "analysis": {
                "summary": "本次运行跟踪率 0.98。",
                "metrics": dict(DEFAULT_METRICS),
                "evidence": [{"metric": "trackingRate", "value": 0.98, "note": "主指标"}],
                "limitations": ["单个随机种子"],
                "produced_by": "openai:eval-model",
            },
        },
        "messages": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "The run reported 3.12 and 98%.", "tool_calls": [], "knowledge": []},
        ],
        "events": [
            {
                "event_type": "intent_classified",
                "payload": {"action": "experiment", "because": "脚本化的路由理由", "handoff_to": "executor"},
            },
            {"event_type": "knowledge_retrieved", "payload": {"grounded": False}},
            {"event_type": "analysis_ready", "payload": {"summary": "本次运行跟踪率 0.98。"}},
            {"event_type": "self_check", "payload": {"ok": True, "issues": []}},
        ],
        "model_calls": [{"kind": "analysis"}, {"kind": "reflect"}],
        "java_runs": [{"config": {}}],
    }
    base.update(overrides)
    return Outcome(**base)


def checks_for(expect: dict, outcome: Outcome) -> dict[str, Check]:
    case = {"id": "synthetic", "group": "x", "description": "d", "message": "m", "expect": expect}
    return {check.name: check for check in grade(case, outcome)}


def passes(expect: dict, outcome: Outcome | None = None) -> bool:
    return all(check.passed for check in grade(
        {"id": "synthetic", "group": "x", "description": "d", "message": "m", "expect": expect},
        outcome if outcome is not None else outcome_with(),
    ))


# --------------------------------------------------------------------------- the grader can fail


def test_a_healthy_run_passes_every_declared_check():
    healthy = {
        "route": "experiment",
        "no_tools": True,
        "tools_used": [],
        "tools_exclude": ["run_simulation"],
        "runs_executed": 1,
        "plan_steps": 1,
        "grounded": False,
        "citations_min": 0,
        "no_citations": True,
        "citation_chunk_ids": [],
        "answer_contains": ["3.12"],
        "answer_excludes": ["缓存"],
        "transcript_contains": ["hello"],
        "self_check_clean": True,
        "self_check_issues_contain": [],
        "self_correction": False,
        "status": "ACTIVE",
        "no_invented_metrics": True,
        "working_config": {"targetCount": 5},
        # multi-agent coordination
        "handoff_to": "executor",
        "routing_reason_contains": ["路由理由"],
        "model_roles": {"analysis": 1, "reflect": 1},
        "analysis": {
            "present": True,
            "summary_contains": ["0.98"],
            "evidence_metrics_only_returned": True,
            "limitations_min": 1,
            "produced_by_prefix": "openai",
        },
    }
    assert passes(healthy)


@pytest.mark.parametrize(
    ("expect", "overrides"),
    [
        # routing
        ({"route": "concept_qa"}, {}),
        # no_tools must catch a *proposed* call, not just an executed one
        (
            {"no_tools": True},
            {"messages": [{"role": "assistant", "content": "x", "tool_calls": [{"call_id": "c1", "name": "run_simulation"}], "knowledge": []}]},
        ),
        ({"tools_used": ["run_simulation"]}, {}),
        ({"tools_exclude": ["run_simulation"]}, {"messages": [{"role": "tool", "tool_name": "run_simulation", "tool_ok": True, "content": "{}"}]}),
        # gate
        ({"requires_confirmation": True}, {}),
        (
            {"requires_confirmation": True},
            {
                "events": [
                    {"event_type": "tool_called", "payload": {"tool_name": "run_simulation"}},
                    {"event_type": "confirmation_requested", "payload": {}},
                ]
            },
        ),
        ({"requires_confirmation": False}, {"events": [{"event_type": "confirmation_requested", "payload": {}}]}),
        # runs and plans
        ({"runs_executed": 2}, {}),
        ({"plan_steps": 4}, {}),
        # grounding
        ({"grounded": True}, {}),
        (
            {"grounded": False},
            {"events": [{"event_type": "knowledge_retrieved", "payload": {"grounded": True}}]},
        ),
        (
            {"grounded": True},
            {"events": [{"event_type": "knowledge_retrieved", "payload": {"grounded": False}}]},
        ),
        (
            {"citations_min": 1},
            {},
        ),
        (
            {"no_citations": True},
            {"messages": [{"role": "assistant", "content": "x", "tool_calls": [], "knowledge": [{"chunk_id": "a"}]}]},
        ),
        ({"citation_chunk_ids": ["fusion-methods#kalman_filter"]}, {}),
        # prose
        ({"answer_contains": ["估计速度"]}, {}),
        ({"answer_excludes": ["3.12"]}, {}),
        ({"transcript_contains": ["never said this"]}, {}),
        # self-check
        ({"self_check_clean": True}, {"events": [{"event_type": "self_check", "payload": {"ok": False, "issues": ["boom"]}}]}),
        ({"self_check_clean": False}, {}),
        ({"self_check_issues_contain": ["超出 [0, 1]"]}, {}),
        ({"self_correction": True}, {}),
        # state
        ({"status": "AWAITING_CONFIRMATION"}, {}),
        ({"working_config": {"targetCount": 99}}, {}),
        # multi-agent coordination
        ({"handoff_to": "responder"}, {}),
        ({"routing_reason_contains": ["用户问了原理"]}, {}),
        ({"model_roles": {"analysis": 2}}, {}),
        # A role that never ran counts as zero rather than being skipped.
        ({"model_roles": {"planner": 1}}, {}),
        ({"analysis": {"present": False}}, {}),
        (
            {"analysis": {"present": True}},
            {"session": {"status": "ACTIVE", "working_config": {}, "last_result": {"metrics": dict(DEFAULT_METRICS)}}},
        ),
        ({"analysis": {"summary_contains": ["不存在的结论"]}}, {}),
        ({"analysis": {"limitations_min": 5}}, {}),
        ({"analysis": {"produced_by_prefix": "rule"}}, {}),
        (
            {"analysis": {"evidence_metrics_only_returned": True}},
            {
                "session": {
                    "status": "ACTIVE",
                    "working_config": {},
                    "last_result": {"metrics": dict(DEFAULT_METRICS)},
                    "analysis": {
                        "summary": "s",
                        "evidence": [{"metric": "hallucinatedMetric", "value": 1}],
                        "limitations": [],
                        "produced_by": "openai:eval-model",
                    },
                }
            },
        ),
        (
            {"analysis": {"evidence_metrics_only_returned": True}},
            {
                "session": {
                    "status": "ACTIVE",
                    "working_config": {},
                    "last_result": {"metrics": dict(DEFAULT_METRICS)},
                    "analysis": {
                        "summary": "s",
                        # The metric exists in the run but the quoted value does not: a drifted
                        # restatement is the same defect as an invented metric.
                        "evidence": [{"metric": "trackingRate", "value": 0.5}],
                        "limitations": [],
                        "produced_by": "openai:eval-model",
                    },
                }
            },
        ),
    ],
)
def test_the_grader_reports_a_failure(expect, overrides):
    assert not passes(expect, outcome_with(**overrides)), f"{expect} passed on a broken run"


def test_the_replayability_invariant_fails_on_an_orphaned_call_but_allows_a_paused_turn():
    orphaned = [{"role": "assistant", "content": "x", "tool_calls": [{"call_id": "c1", "name": "run_simulation"}], "knowledge": []}]
    assert not passes({}, outcome_with(messages=orphaned))
    # The same transcript is correct while the user is being asked to approve the batch.
    paused = outcome_with(messages=orphaned, session={"status": "AWAITING_CONFIRMATION", "working_config": {}})
    assert passes({}, paused)


def test_the_replayability_invariant_allows_a_closed_out_call():
    answered = [
        {"role": "assistant", "content": "x", "tool_calls": [{"call_id": "c1", "name": "run_simulation"}], "knowledge": []},
        {"role": "tool", "tool_name": "run_simulation", "tool_call_id": "c1", "tool_ok": False, "content": "{}"},
    ]
    assert passes({}, outcome_with(messages=answered))


def test_declaring_grounded_requires_the_event_even_when_the_answer_is_false():
    """
    A missing ``knowledge_retrieved`` event is a failure, not a quiet "false".

    Otherwise a turn on which retrieval was never wired in would satisfy ``grounded: false`` — the
    same false positive that a mock once produced by keying on a phrase the prompt itself contains.
    """
    without_event = outcome_with(events=[{"event_type": "self_check", "payload": {"ok": True, "issues": []}}])
    assert not passes({"grounded": False}, without_event)
    assert not passes({"grounded": True}, without_event)


def test_tool_failed_and_result_checks_read_the_tool_message():
    messages = [{"role": "tool", "tool_name": "run_simulation", "tool_call_id": "c1", "tool_ok": False, "content": '{"result": {"excerpt": "唯一真正估计速度"}}'}]
    assert passes({"tool_failed": ["run_simulation"]}, outcome_with(messages=messages))
    assert not passes({"tool_failed": ["search_knowledge"]}, outcome_with(messages=messages))
    assert passes({"tool_result_contains": {"run_simulation": ["唯一真正估计速度"]}}, outcome_with(messages=messages))
    assert not passes({"tool_result_contains": {"run_simulation": ["not in there"]}}, outcome_with(messages=messages))


# --------------------------------------------------------------------------- the hallucination check


def test_a_fabricated_decimal_is_caught():
    claim = [{"role": "assistant", "content": "平均位置误差是 2.5。", "tool_calls": [], "knowledge": []}]
    assert not passes({"no_invented_metrics": True}, outcome_with(messages=claim))


def test_a_percentage_restatement_is_allowed():
    # A tracking rate of 0.98 is legitimately written "98%".
    claim = [{"role": "assistant", "content": "跟踪率 98%。", "tool_calls": [], "knowledge": []}]
    assert passes({"no_invented_metrics": True}, outcome_with(messages=claim))


def test_a_rounded_restatement_is_allowed():
    claim = [{"role": "assistant", "content": "误差约 3.1。", "tool_calls": [], "knowledge": []}]
    assert passes({"no_invented_metrics": True}, outcome_with(messages=claim))


def test_a_config_value_may_be_quoted():
    claim = [{"role": "assistant", "content": "当前配置是 5 个目标、12 步。", "tool_calls": [], "knowledge": []}]
    assert passes({"no_invented_metrics": True}, outcome_with(messages=claim))


def test_a_metric_the_run_never_returned_is_caught():
    claim = [{"role": "assistant", "content": "schedulingSwitches 是本次关键指标。", "tool_calls": [], "knowledge": []}]
    thin = outcome_with(
        session={"status": "ACTIVE", "working_config": {}, "last_result": {"metrics": {"trackingRate": 0.98}}}
    )
    # DEFAULT_METRICS includes schedulingSwitches, so on the healthy outcome this passes; on a run
    # that did not return it, the mention is a fabrication.
    assert passes({"no_invented_metrics": True}, outcome_with(messages=claim))
    assert not passes({"no_invented_metrics": True}, thin)


def test_the_hallucination_check_refuses_to_pass_without_metrics():
    # Declaring the check on a case that produced no metrics is a case-authoring error, and it must
    # be loud rather than a silent pass.
    empty = outcome_with(session={"status": "ACTIVE", "working_config": {}, "last_result": {"metrics": {}}})
    assert not passes({"no_invented_metrics": True}, empty)


# --------------------------------------------------------------------------- authoring guards


def test_an_unknown_expectation_key_raises_rather_than_being_ignored():
    with pytest.raises(ValueError, match="unknown expectation key"):
        passes({"answer_contians": ["typo"]})


def test_the_case_file_is_valid_jsonl_with_readable_text():
    raw = Path(__file__).resolve().parent.parent / "evals" / "cases.jsonl"
    for line in raw.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("//"):
            json.loads(line)


# --------------------------------------------------------------------------- live provider mode


def test_live_mode_puts_the_scripted_model_aside():
    """
    Live mode exists to measure the model, so the one thing it has to guarantee is that the case's
    scripted answers are out of the picture. An unusable provider therefore has to make the case
    fail, because a scripted run would have answered from the case and passed.

    The base URL is malformed rather than merely unreachable. A refused connection produces the same
    failure but costs about eleven seconds of gateway retries, and a suite that slow stops being
    run; this fails in about one.
    """
    case = CASES_BY_ID["concept-grounded-answer-cites-sources"]
    patched: list[str] = []
    real_patch = harness.patch

    def spy(target, replacement):
        patched.append(target)
        return real_patch(target, replacement)

    with patch.object(harness, "patch", spy):
        outcome = run_case(
            case, LiveModel(provider="openai", model="m", api_key="k", api_base="not-a-url")
        )

    # The provider path was reached, so the scripted answers were not.
    assert outcome.error is not None, "a live run must not be answerable from the case"
    assert outcome.event_types() == []
    checks = grade(case, outcome)
    assert [check.name for check in checks] == ["case-completed"]
    assert checks[0].passed is False

    # And this is the mechanism, asserted directly so a future edit cannot quietly reinstall the
    # substitutions "for safety": neither the classifier stub nor any model entry point is patched.
    assert "app.agent_graph.classify_intent" not in patched
    assert not [target for target in patched if "stream_call_with_tools" in target]
    assert not [target for target in patched if target.endswith(".complete")]
    # The Java core is still stubbed. Comparing two providers should not need a database, and a
    # stubbed simulation is what makes the two runs comparable at all.
    assert "app.domain_tools.run_simulation" in patched


def test_every_live_significant_name_is_a_check_the_grader_emits():
    """
    A typo in LIVE_SIGNIFICANT would silently stop counting a check in live mode: the run would
    still print a number, and that number would just be measuring less than it claims. Comparing
    the set against the names the grader actually produces catches the typo and the later rename.
    """
    emitted = {
        check.name
        for case in CASES
        for check in grade(case, Outcome(case_id=case["id"]))
    }
    assert LIVE_SIGNIFICANT <= emitted, f"not emitted by the grader: {LIVE_SIGNIFICANT - emitted}"
