"""
Self-reflection for the agent: check its own conclusion before the turn ends.

The failure this addresses is the one that actually happened. The agent looked at two runs with
identical numbers and concluded the results had been "cached" or that the configuration had been
ignored — reasoning that was wrong (a fixed seed makes identical numbers the expected outcome) and
that it had no way to notice, because nothing ever asked it to check its own claim against the
evidence it had.

Reflection runs in two layers, and the split is deliberate:

* ``deterministic_self_check`` — pure code, no model call. Physical range checks on the metrics and
  a consistency check that the evidence cards match the metrics they came from. Free, always runs,
  and catches the mechanical failures.
* ``reflect_on_result`` — one model call, only when a turn actually produced a result *and* the
  agent said something about it. It audits the agent's own prose against the facts the tools
  returned and, if the prose outruns the evidence, produces a correction.

The model layer is deliberately not run on every turn: a turn that only read the configuration has
no claim to audit, and paying a model call to confirm nothing is waste. The deterministic layer is
free, so it is never worth skipping.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from .domain_tools import CONFIG_SUMMARY_KEYS
from .model_gateway import ModelCredential, complete
from .model_planner import parse_json_object
from .models import AgentSession


# Metrics that are probabilities or ratios. Anything outside [0, 1] is not a judgement call.
UNIT_INTERVAL_METRICS = frozenset({"trackingRate", "resourceUtilization"})
NON_NEGATIVE_METRICS = frozenset(
    {"averagePositionError", "averageWaitingTime", "allocatedTargetCount", "unservedTargetCount"}
)
# A comparison run nests two results, so metric names arrive prefixed.
METRIC_PREFIXES = ("roundRobin.", "priority.", "delta.")


REFLECT_SYSTEM_PROMPT = """你是 FusionPilot 仿真助手的自检模块。刚才助手对用户说了一段话，你的任务是严格审查这段话是否被工具返回的数据支持，找出任何编造、夸大、无证据的因果、或与数值矛盾的表述。

严格检查：
1. 这段话里提到的每个数值，是否能在这份事实里找到？找不到的就是编造。
2. 这段话里的比较或因果结论（例如"A 比 B 好""配置已生效""结果被缓存/复用了"）是否有数据支持？
3. 特别警惕：把"确定性复现"（同一配置、同一种子必然得到相同结果）误判成"缓存"或"配置没生效"。判断配置是否生效，要看 run 自己的 config 摘要里字段是否是新值，不能只看数值相同就下结论。

已知事实全部来自 Java 仿真核心，是唯一真相源，以 JSON 形式在用户消息的 facts 字段里给出；助手的原话在 narrative 字段里。

只返回 JSON：
{"supported": true 或 false, "problem": "有问题时简述问题，无问题留空字符串", "correction": "如果需要纠正，给出一句正确、被证据支持的表述；否则留空字符串"}

只找问题，不要客套。没问题就 supported=true、problem 和 correction 都留空。"""


class ReflectionOutcome(BaseModel):
    supported: bool = True
    problem: str = ""
    correction: str = ""


def _base_metric(name: str) -> str:
    for prefix in METRIC_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


def deterministic_self_check(session: AgentSession) -> list[str]:
    """
    Mechanical checks on the last run's numbers. No model, no cost.

    Catches impossible values (a tracking rate above 1, a negative error) and any drift between
    the evidence cards and the metrics they were built from.
    """
    issues: list[str] = []
    metrics = (session.last_result or {}).get("metrics") or {}
    if not metrics:
        return issues

    for name, value in metrics.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        stem = _base_metric(name)
        if stem in UNIT_INTERVAL_METRICS and not (0.0 <= value <= 1.0):
            issues.append(f"{name} = {value} 超出 [0, 1] 的正常范围")
        if stem in NON_NEGATIVE_METRICS and value < 0:
            issues.append(f"{name} = {value} 为负值，不符合物理含义")

    for item in session.last_evidence:
        name = item.get("metric")
        if name in metrics and metrics[name] != item.get("value"):
            issues.append(f"证据卡 {name} = {item.get('value')} 与本次指标 {metrics[name]} 不一致")

    return issues


async def reflect_on_result(
    session: AgentSession,
    narrative: str,
    credential: ModelCredential,
) -> ReflectionOutcome | None:
    """
    Audit the agent's own prose against the facts the tools returned.

    Returns ``None`` when there is nothing to audit (no metrics, or the agent said nothing). A
    gateway failure is the caller's to decide on; this function lets it propagate.
    """
    metrics = (session.last_result or {}).get("metrics") or {}
    if not metrics or not narrative.strip():
        return None

    config = {key: session.working_config.get(key) for key in CONFIG_SUMMARY_KEYS if key in session.working_config}
    facts = {
        "metrics": metrics,
        "run_id": session.last_run_id,
        "config_used_by_this_run": config,
        "evidence": session.last_evidence,
        "determinism_rule": (
            "The simulation is deterministic for a fixed random seed: identical configuration and "
            "seed reproduce bit-identical metrics. Equal numbers therefore mean reproducibility, "
            "not a cached result."
        ),
    }
    messages = [
        {"role": "system", "content": REFLECT_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps({"facts": facts, "narrative": narrative}, ensure_ascii=False)},
    ]
    content = await complete(messages, credential)
    parsed = parse_json_object(content)
    return ReflectionOutcome(
        supported=bool(parsed.get("supported", True)),
        problem=str(parsed.get("problem") or "").strip(),
        correction=str(parsed.get("correction") or "").strip(),
    )


def final_narrative(session: AgentSession) -> str:
    """The agent's last substantive reply, which is what reflection audits."""
    for message in reversed(session.messages):
        if message.role == "assistant" and message.content.strip():
            return message.content
    return ""


def merge_issues(*groups: list[str]) -> list[str]:
    """De-duplicate issues from both layers while preserving order."""
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for item in group:
            if item not in seen:
                seen.add(item)
                merged.append(item)
    return merged
