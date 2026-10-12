"""
The skill registry and what it is for.

The point of a registry is not that constants moved house — it is that the routing instructions and
the graph's routed nodes are *derived* from what is registered. So these tests assert the derivation
itself: a registry built from different skills must produce different routing text, and the graph
must route into exactly the registered specialists. If either were still hard-coded underneath,
"add a specialist" would go back to meaning "edit four places".

Two things are pinned because they are wire contracts rather than cosmetics: the phrase ``意图路由``
that the stub provider uses to recognise a supervisor call, and which roles have no tool channel at
all. Both are the kind of fact that a green suite would otherwise not notice changing.
"""

from __future__ import annotations

import pytest

from app.domain_tools import EXECUTOR_TOOL_NAMES, PLANNABLE_TOOLS
from app.skills import (
    CLARIFY,
    CONCEPT_QA,
    EXPERIMENT,
    EXPLORE,
    SKILLS,
    Skill,
    SkillRegistry,
)


def _skill(action: str, name: str, title: str, duty: str) -> Skill:
    return Skill(action=action, name=name, title=title, duty=duty)


def test_the_routing_prompt_is_built_from_the_registered_skills():
    """A registry of different skills must read back as those skills — not as the built-ins."""
    custom = SkillRegistry((
        _skill(CONCEPT_QA, "reader", "阅读专员", "只朗读平台文档，不做任何其他判断。"),
    ))

    prompt = custom.routing_prompt()

    assert "阅读专员" in prompt
    assert "只朗读平台文档" in prompt
    assert "应答专员" not in prompt


def test_the_wire_contract_phrase_survives_generation():
    """The stub provider recognises a supervisor call by this phrase; generating must keep it."""
    custom = SkillRegistry((
        _skill(EXPERIMENT, "doer", "执行专员", "做一次操作。"),
    ))

    assert "意图路由" in SKILLS.routing_prompt()
    assert "意图路由" in custom.routing_prompt()


def test_the_supervisor_routes_into_exactly_the_registered_specialists():
    """The graph's routing edges come from the registry, so the two cannot drift apart."""
    from app.agent_graph import SPECIALISTS, build_turn_graph

    assert SPECIALISTS == SKILLS.routes()
    nodes = set(build_turn_graph().get_graph().nodes)
    assert {skill.name for skill in SKILLS.all()} <= nodes


def test_registering_the_same_action_twice_is_rejected():
    """Two skills for one route would make the handoff ambiguous; refuse it at registration."""
    registry = SkillRegistry((_skill(CONCEPT_QA, "a", "A", "x"),))

    with pytest.raises(ValueError):
        registry.register(_skill(CONCEPT_QA, "b", "B", "y"))


def test_an_action_outside_the_route_vocabulary_is_rejected():
    """The supervisor only ever emits the four known actions; a skill for anything else is dead."""
    with pytest.raises(ValueError):
        SkillRegistry((_skill("nonsense", "x", "X", "y"),))


def test_tool_power_is_declared_on_the_skill_and_matches_the_tool_catalog():
    """
    Tool access is a property of the role, stated once, not discovered by reading a prompt.

    This is the same contract ``test_roles`` defends from the other side (the executor's surface is
    exactly what was enumerated), restated where the surface is now declared.
    """
    by_action = {skill.action: skill for skill in SKILLS.all()}

    assert by_action[CONCEPT_QA].tool_free is True
    assert by_action[CLARIFY].tool_free is True
    assert by_action[EXPERIMENT].tool_names == frozenset(EXECUTOR_TOOL_NAMES)
    assert by_action[EXPLORE].tool_names == frozenset(PLANNABLE_TOOLS)


def test_the_executor_has_more_power_than_the_planner():
    """
    Both name ``run_simulation`` — the planner schedules it — but only the executor can run a
    comparison, re-read metrics, or look the reference material up directly. If the planner ever
    gained those it could act outside the single confirmation the user approves.
    """
    by_action = {skill.action: skill for skill in SKILLS.all()}
    executor_extra = by_action[EXPERIMENT].tool_names - by_action[EXPLORE].tool_names

    assert executor_extra == {"compare_scheduling_policies", "calculate_metrics", "search_knowledge"}
    assert "compare_scheduling_policies" not in by_action[EXPLORE].tool_names
