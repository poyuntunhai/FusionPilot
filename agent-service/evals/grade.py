"""
Grading for the evaluation cases. Pure functions over a recorded outcome: no I/O, no model.

Why this is split out from the harness: **a grader nobody has seen fail is not a grader.** Keeping
it pure means it can be pointed at deliberately broken runs in the unit tests and observed to
report failures. Every check below has a negative test for exactly that reason.

Three things this module deliberately does *not* do:

* It does not compare prose to prose. Text assertions are substring probes of the platform's own
  vocabulary (`answer_contains`), which is what makes them stable, and they only make sense with the
  scripted model — see ``evals/README.md`` for the boundary of what this suite measures.
* It does not use an LLM judge. A judge would be a second non-deterministic system standing between
  a change and the verdict.
* It does not treat a missing expectation as a pass. An unknown expectation key raises, because a
  typo'd expectation that silently checks nothing is the worst failure mode a suite can have.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .harness import Outcome

# The metric names the Java core can return. Mirrors `AggregateMetrics` plus the per-step names, and
# the prefixes a policy comparison adds. Used to catch a mention of a metric the run never returned.
METRIC_NAMES = (
    "averagePositionError",
    "trackingRate",
    "resourceUtilization",
    "averageWaitingTime",
    "schedulingSwitches",
    "totalSteps",
    "allocatedTargetCount",
    "unservedTargetCount",
)
COMPARISON_PREFIXES = ("roundRobin.", "priority.", "delta.", "priorityMinusRoundRobin.")

DECIMAL = re.compile(r"-?\d+\.\d+")
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")

# A number quoted in prose is allowed to be a rounded restatement of a real value ("3.1" for 3.12),
# so comparisons use a relative tolerance. It is tight enough that a fabricated value ("2.5" when
# the run said 3.12) still fails.
RELATIVE_TOLERANCE = 0.005


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""

    def render(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        return f"  [{mark}] {self.name}" + (f" — {self.detail}" if self.detail else "")


KNOWN_EXPECTATIONS = frozenset(
    {
        "route",
        "no_tools",
        "tools_used",
        "tools_exclude",
        "tool_failed",
        "tool_result_contains",
        "requires_confirmation",
        "runs_executed",
        "plan_steps",
        "grounded",
        "citations_min",
        "no_citations",
        "citation_chunk_ids",
        "answer_contains",
        "answer_excludes",
        "transcript_contains",
        "self_check_issues_contain",
        "self_check_clean",
        "self_correction",
        "status",
        "no_invented_metrics",
        "working_config",
        # multi-agent coordination
        "handoff_to",
        "routing_reason_contains",
        "model_roles",
        "analysis",
    }
)


def grade(case: dict[str, Any], outcome: Outcome) -> list[Check]:
    """Run every applicable check for one case. Always includes the shared invariants."""
    checks: list[Check] = []

    if outcome.error:
        checks.append(Check("case-completed", False, outcome.error))
        return checks
    checks.append(Check("case-completed", True))

    # Runs for every case, whether or not the case asks for it: a transcript with an unanswered tool
    # call is rejected by both providers, so it is a defect no matter what else the case asserts.
    checks.append(_replayable(outcome))

    expect = case.get("expect") or {}
    unknown = sorted(set(expect) - KNOWN_EXPECTATIONS)
    if unknown:
        raise ValueError(
            f"{outcome.case_id}: unknown expectation key(s) {', '.join(unknown)}. "
            f"Known keys: {', '.join(sorted(KNOWN_EXPECTATIONS))}"
        )

    if "route" in expect:
        checks.append(_route(expect["route"], outcome))
    if "no_tools" in expect:
        # Stronger than "nothing ran": no tool call was even *proposed*. A concept answer that
        # reaches for a tool is the failure this guards, and it shows up as a proposed call on the
        # assistant message, not as a tool result.
        proposed = [
            call["name"]
            for message in outcome.messages
            if message["role"] == "assistant"
            for call in message.get("tool_calls") or []
        ]
        ran = outcome.tool_names()
        ok = not proposed and not ran
        checks.append(
            Check("no-tools", ok is expect["no_tools"], f"proposed {proposed}, ran {ran}")
        )
    if "tools_used" in expect:
        names = outcome.tool_names()
        checks.append(Check("tools-used", names == expect["tools_used"], f"got {names}"))
    if "tools_exclude" in expect:
        names = outcome.tool_names()
        present = [name for name in expect["tools_exclude"] if name in names]
        checks.append(Check("tools-exclude", not present, f"unexpected {present}"))
    if "tool_failed" in expect:
        wrong = [
            name
            for name in expect["tool_failed"]
            if (outcome.tool_message(name) or {}).get("tool_ok") is not False
        ]
        checks.append(Check("tool-failed", not wrong, f"not reported as failed: {wrong}"))
    if "tool_result_contains" in expect:
        missing: list[str] = []
        for tool_name, needles in expect["tool_result_contains"].items():
            content = (outcome.tool_message(tool_name) or {}).get("content") or ""
            missing.extend(needle for needle in needles if needle not in content)
        checks.append(Check("tool-result-contains", not missing, f"missing {missing}"))
    if "requires_confirmation" in expect:
        checks.append(_requires_confirmation(expect["requires_confirmation"], outcome))
    if "runs_executed" in expect:
        checks.append(
            Check(
                "runs-executed",
                len(outcome.java_runs) == expect["runs_executed"],
                f"java runs invoked: {len(outcome.java_runs)}",
            )
        )
    if "plan_steps" in expect:
        sequence = outcome.session.get("sequence") or {}
        steps = sequence.get("steps") or []
        checks.append(Check("plan-steps", len(steps) == expect["plan_steps"], f"got {len(steps)}"))
    if "grounded" in expect:
        checks.append(_grounded(expect["grounded"], outcome))
    if "citations_min" in expect:
        rows = (outcome.last_assistant() or {}).get("knowledge") or []
        checks.append(
            Check("citations-min", len(rows) >= expect["citations_min"], f"got {len(rows)}")
        )
    if "no_citations" in expect:
        rows = (outcome.last_assistant() or {}).get("knowledge") or []
        empty = not rows
        checks.append(
            Check("no-citations", empty is expect["no_citations"], f"got {len(rows)} citations")
        )
    if "citation_chunk_ids" in expect:
        rows = (outcome.last_assistant() or {}).get("knowledge") or []
        found = {row.get("chunk_id") for row in rows}
        missing = [chunk for chunk in expect["citation_chunk_ids"] if chunk not in found]
        checks.append(Check("citation-chunk-ids", not missing, f"missing {missing} from {sorted(found)}"))
    if "answer_contains" in expect or "answer_excludes" in expect:
        answer = (outcome.last_assistant() or {}).get("content") or ""
        if "answer_contains" in expect:
            missing = [text for text in expect["answer_contains"] if text not in answer]
            checks.append(Check("answer-contains", not missing, f"missing {missing} in {answer[:80]!r}"))
        if "answer_excludes" in expect:
            present = [text for text in expect["answer_excludes"] if text in answer]
            checks.append(Check("answer-excludes", not present, f"unexpected {present}"))
    if "transcript_contains" in expect:
        # Anywhere in the transcript, unlike `answer_contains` which reads the closing message. Used
        # to assert that something the agent said is *kept* — a wrong claim that a correction
        # superseded must stay visible rather than being quietly replaced.
        whole = "\n".join(message.get("content") or "" for message in outcome.messages)
        missing = [text for text in expect["transcript_contains"] if text not in whole]
        checks.append(Check("transcript-contains", not missing, f"missing {missing}"))
    if "self_check_issues_contain" in expect:
        issues = _last_event_payload(outcome, "self_check").get("issues") or []
        missing = [text for text in expect["self_check_issues_contain"] if not any(text in issue for issue in issues)]
        checks.append(Check("self-check-issues-contain", not missing, f"missing {missing} in {issues}"))
    if "self_check_clean" in expect:
        payload = _last_event_payload(outcome, "self_check")
        if not payload:
            checks.append(Check("self-check-clean", False, "no self_check event was emitted"))
        else:
            issues = payload.get("issues") or []
            clean = not issues
            checks.append(
                Check("self-check-clean", clean is expect["self_check_clean"], f"issues: {issues}")
            )
    if "self_correction" in expect:
        checks.append(_self_correction(expect["self_correction"], outcome))
    if "status" in expect:
        status = outcome.session.get("status")
        checks.append(Check("status", status == expect["status"], f"got {status}"))
    if "no_invented_metrics" in expect and expect["no_invented_metrics"]:
        checks.append(_no_invented_metrics(outcome))
    if "working_config" in expect:
        actual = outcome.session.get("working_config") or {}
        wrong = {
            key: (actual.get(key), value)
            for key, value in expect["working_config"].items()
            if actual.get(key) != value
        }
        checks.append(Check("working-config", not wrong, f"mismatched (actual, expected): {wrong}"))
    if "handoff_to" in expect:
        payload = _last_event_payload(outcome, "intent_classified")
        actual = payload.get("handoff_to")
        checks.append(Check("handoff-to", actual == expect["handoff_to"], f"got {actual}"))
    if "routing_reason_contains" in expect:
        because = _last_event_payload(outcome, "intent_classified").get("because") or ""
        missing = [text for text in expect["routing_reason_contains"] if text not in because]
        checks.append(Check("routing-reason-contains", not missing, f"missing {missing} in {because!r}"))
    if "model_roles" in expect:
        checks.append(_model_roles(expect["model_roles"], outcome))
    if "analysis" in expect:
        checks.extend(_analysis_checks(expect["analysis"], outcome))

    return checks


def _model_roles(expected: dict[str, int], outcome: Outcome) -> Check:
    """
    How many times each role's model call actually happened.

    This is what pins the *coordination* rather than the output: that the analyst ran once for a
    run and not at all for a turn that changed a setting, that the critic ran once, that a concept
    turn never reached the executor. Those are the claims that make this a team rather than one
    model doing five jobs, and none of them is visible in the answer text.
    """
    counts: dict[str, int] = {}
    for call in outcome.model_calls:
        kind = call.get("kind", "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    wrong = {
        role: f"expected {count}, got {counts.get(role, 0)}"
        for role, count in expected.items()
        if counts.get(role, 0) != count
    }
    return Check("model-roles", not wrong, "; ".join(sorted(wrong.values())) or f"call counts {counts}")


def _analysis_checks(spec: dict[str, Any], outcome: Outcome) -> list[Check]:
    """
    The analyst's artifact: present when it should be, and traceable to the run when it is.

    ``evidence_metrics_only_returned`` is the end-to-end proof that the analyst cannot smuggle a
    metric past the reader: the role inherits the filter in ``analyze_with_model``, which drops any
    evidence row naming a metric the run never returned. A case scripts such a row on purpose.
    """
    checks: list[Check] = []
    artifact = outcome.session.get("analysis") or {}
    event = _last_event_payload(outcome, "analysis_ready")
    present = bool(artifact) and bool(event)

    if "present" in spec:
        checks.append(
            Check(
                "analysis-present",
                present is spec["present"],
                f"artifact={bool(artifact)} event={bool(event)}",
            )
        )
    if not present:
        return checks

    if "summary_contains" in spec:
        summary = artifact.get("summary") or ""
        missing = [text for text in spec["summary_contains"] if text not in summary]
        checks.append(Check("analysis-summary-contains", not missing, f"missing {missing} in {summary[:90]!r}"))
    if "limitations_min" in spec:
        rows = artifact.get("limitations") or []
        checks.append(
            Check("analysis-limitations-min", len(rows) >= spec["limitations_min"], f"got {len(rows)}")
        )
    if "produced_by_prefix" in spec:
        produced = artifact.get("produced_by") or ""
        checks.append(
            Check("analysis-produced-by", produced.startswith(spec["produced_by_prefix"]), f"got {produced}")
        )
    if spec.get("evidence_metrics_only_returned"):
        metrics = (outcome.session.get("last_result") or {}).get("metrics") or {}
        allowed = {key.split(".")[-1]: value for key, value in metrics.items()}
        invented = sorted(
            {row.get("metric") for row in (artifact.get("evidence") or [])} - set(allowed)
        )
        drifted = [
            row.get("metric")
            for row in (artifact.get("evidence") or [])
            if row.get("metric") in allowed and row.get("value") != allowed[row["metric"]]
        ]
        checks.append(
            Check(
                "analysis-evidence-returned-metrics",
                not invented and not drifted,
                f"invented {invented}, values not from the run {drifted}",
            )
        )
    return checks


def _replayable(outcome: Outcome) -> Check:
    """
    Every requested tool call has a result — *once the turn has come to rest*.

    A conversation paused on a confirmation is deliberately not in that state: the batch is held
    whole so that approving it can answer every call at once, and flagging that as an orphan would
    make the invariant wrong about the one flow it most needs to permit. The check therefore
    applies whenever the session is not waiting on the user.
    """
    if outcome.session.get("status") == "AWAITING_CONFIRMATION":
        return Check("transcript-replayable", True, "not applicable while awaiting confirmation")

    answered = {message.get("tool_call_id") for message in outcome.messages if message["role"] == "tool"}
    orphaned: list[str] = []
    for message in outcome.messages:
        if message["role"] != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            if call["call_id"] not in answered:
                orphaned.append(f"{call['name']}({call['call_id']})")
    return Check("transcript-replayable", not orphaned, f"unanswered: {orphaned}")


def _route(expected: str, outcome: Outcome) -> Check:
    payload = _last_event_payload(outcome, "intent_classified")
    actual = payload.get("action")
    return Check("route", actual == expected, f"got {actual}")


def _requires_confirmation(expected: bool, outcome: Outcome) -> Check:
    """
    A confirmation was requested, and nothing expensive ran before it.

    The status is deliberately not asserted here. After the user approves, the status is ACTIVE
    again while the ``confirmation_requested`` event stays in the trail — so requiring
    ``AWAITING_CONFIRMATION`` would make this check wrong for exactly the flow it exists to protect.
    Whether the turn is still paused is a separate expectation (``status``).
    """
    if not expected:
        requested = "confirmation_requested" in outcome.event_types()
        return Check("requires-confirmation", not requested, f"requested={requested}")

    marker = next(
        (index for index, event in enumerate(outcome.events) if event["event_type"] == "confirmation_requested"),
        None,
    )
    if marker is None:
        return Check("requires-confirmation", False, "no confirmation_requested event was emitted")

    # Anything executed before the gate is the failure this guards: the run must not have happened
    # until the user said so.
    early = [
        event["payload"].get("tool_name")
        for event in outcome.events[:marker]
        if event["event_type"] == "tool_called"
    ]
    return Check(
        "requires-confirmation",
        not early,
        f"tools called before the gate: {early}" if early else "",
    )


def _grounded(expected: bool, outcome: Outcome) -> Check:
    """
    Whether retrieval grounded this answer — and the absence of the event is not a pass.

    A case that declares ``grounded`` is asserting something about the concept path, so if no
    ``knowledge_retrieved`` event exists, the path never ran and there is nothing to judge. Treating
    "no event" as "not grounded" would let the check pass on a turn where retrieval was never wired
    in, which is the exact false positive this suite exists to prevent.
    """
    payload = _last_event_payload(outcome, "knowledge_retrieved")
    if not payload:
        return Check("grounded", False, "no knowledge_retrieved event was emitted, so nothing was evaluated")
    actual = payload.get("grounded")
    return Check("grounded", actual is expected, f"got {actual}")


def _self_correction(expected: bool, outcome: Outcome) -> Check:
    event_present = "self_correction" in outcome.event_types()
    message_present = any(
        (message.get("produced_by") or "").startswith("reflect:") for message in outcome.messages
    )
    if expected:
        return Check(
            "self-correction",
            event_present and message_present,
            f"event={event_present} message={message_present}",
        )
    return Check("self-correction", not event_present, f"event={event_present}")


def _last_event_payload(outcome: Outcome, event_type: str) -> dict[str, Any]:
    for event in reversed(outcome.events):
        if event["event_type"] == event_type:
            return event.get("payload") or {}
    return {}


def _flatten_numbers(value: Any, sink: set[float]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        sink.add(float(value))
    elif isinstance(value, dict):
        for item in value.values():
            _flatten_numbers(item, sink)
    elif isinstance(value, list):
        for item in value:
            _flatten_numbers(item, sink)
    elif isinstance(value, str):
        for match in NUMBER.findall(value):
            try:
                sink.add(float(match))
            except ValueError:
                continue


def _allowed_numbers(outcome: Outcome) -> set[float]:
    """
    Every number the agent was entitled to quote.

    Metric values, their percentage forms (a tracking rate of 0.98 is legitimately written "98%"),
    the values rounded to one decimal (a summary may round), and the configuration the run used
    (target counts and step counts are quoted in prose all the time).
    """
    raw: set[float] = set()
    _flatten_numbers((outcome.session.get("last_result") or {}).get("metrics") or {}, raw)
    _flatten_numbers(outcome.session.get("working_config") or {}, raw)
    for item in outcome.session.get("last_evidence") or []:
        _flatten_numbers(item.get("value"), raw)

    allowed = set(raw)
    for value in raw:
        allowed.add(round(value, 1))
        if 0.0 <= value <= 1.0:
            allowed.update({value * 100, round(value * 100, 1), round(value * 100)})
    return allowed


def _no_invented_metrics(outcome: Outcome) -> Check:
    """
    The agent may not quote a metric value or a metric name it was never given.

    Only numbers that *look like measurements* are checked: anything with a decimal point, and
    anything written with a percent sign. Bare integers are not, because "target 1" and "3 targets"
    are ordinary prose — so an invented integer is outside this check, which is a real limitation and
    is stated in `evals/README.md` rather than papered over.
    """
    metrics = (outcome.session.get("last_result") or {}).get("metrics") or {}
    if not metrics:
        return Check(
            "no-invented-metrics",
            False,
            "the case declares this check but the run produced no metrics to check against",
        )

    answer = (outcome.last_assistant() or {}).get("content") or ""
    allowed = _allowed_numbers(outcome)

    suspicious: list[str] = []
    candidates = set(DECIMAL.findall(answer)) | set(PERCENT.findall(answer))
    for token in candidates:
        try:
            value = float(token)
        except ValueError:
            continue
        if not any(_close(value, candidate) for candidate in allowed):
            suspicious.append(token)

    returned_bases = {key.split(".")[-1] for key in metrics}
    invented_names = sorted(
        name for name in METRIC_NAMES if name in answer and name not in returned_bases
    )

    detail_parts = []
    if suspicious:
        detail_parts.append(f"unsupported numbers {sorted(suspicious)}")
    if invented_names:
        detail_parts.append(f"metrics not returned by the run {invented_names}")
    return Check("no-invented-metrics", not detail_parts, "; ".join(detail_parts))


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= max(1e-6, abs(right) * RELATIVE_TOLERANCE)
