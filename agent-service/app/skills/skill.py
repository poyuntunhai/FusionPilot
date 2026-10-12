"""
A skill is one specialist the supervisor can hand a turn to.

Before this module, "which specialists exist, what each may do, and what each is told" lived in
three places: the ``SPECIALISTS`` route map, four system-prompt constants, and
``EXECUTOR_TOOL_NAMES``. Adding a specialist meant editing all three, then remembering to add a
graph node — miss one and the graph still draws, it just cannot route to the new role.

A ``Skill`` puts those on one object, so the four facts that must stay consistent are defined
once:

* the route ``action`` that triggers it (also what the supervisor's routing prompt is built from),
* its ``name`` (the graph node it becomes),
* its ``system_prompt``,
* the ``tool_names`` it may call — an **empty set is a structural absence of a tool channel**, not
  a sentence in a prompt asking the model to hold back.

Prompt text is data here, but it is *load-bearing* data: the stub provider used by the end-to-end
scripts and the tests recognises a call by phrases inside the prompt (see
``tests/mock_model_server.py``). Editing a skill's wording can therefore change what the test
double answers, which is why the phrases are kept verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The four routes. These are the vocabulary the supervisor classifies into and the keys of the
# registry; ``agent_graph`` re-exports them so the existing import sites keep working.
CONCEPT_QA = "concept_qa"
EXPERIMENT = "experiment"
EXPLORE = "explore"
CLARIFY = "clarify"

ROUTED_ACTIONS = frozenset({CONCEPT_QA, EXPERIMENT, EXPLORE, CLARIFY})


@dataclass(frozen=True)
class Skill:
    """One specialist: how it is routed to, what it is told, and what it may touch."""

    action: str
    name: str
    title: str
    duty: str
    examples: tuple[str, ...] = ()
    note: str = ""
    system_prompt: str = ""
    tool_names: frozenset[str] = field(default_factory=frozenset)

    @property
    def tool_free(self) -> bool:
        """True when this role cannot act at all — enforced by an empty tool surface."""
        return not self.tool_names


class SkillRegistry:
    """
    The set of skills the graph routes into.

    Registration is the extension point: ``routing_prompt`` is generated from whatever is
    registered, so a newly registered skill shows up in the supervisor's instructions without
    anyone editing that prompt by hand.
    """

    def __init__(self, skills: tuple[Skill, ...] = ()) -> None:
        self._by_action: dict[str, Skill] = {}
        for skill in skills:
            self.register(skill)

    def register(self, skill: Skill) -> None:
        if skill.action not in ROUTED_ACTIONS:
            raise ValueError(f"skill action must be one of {sorted(ROUTED_ACTIONS)}: {skill.action}")
        if skill.action in self._by_action:
            raise ValueError(f"a skill is already registered for action: {skill.action}")
        self._by_action[skill.action] = skill

    def get(self, action: str) -> Skill | None:
        return self._by_action.get(action)

    def all(self) -> tuple[Skill, ...]:
        return tuple(self._by_action.values())

    def routes(self) -> dict[str, str]:
        """action -> role name. This is the old ``SPECIALISTS`` map, derived rather than typed."""
        return {skill.action: skill.name for skill in self._by_action.values()}

    def tool_names(self) -> frozenset[str]:
        """Every tool any skill may call. The union, so a capability is visible in one place."""
        return frozenset().union(*(skill.tool_names for skill in self._by_action.values()))

    def routing_prompt(self) -> str:
        """
        Build the supervisor's routing instructions from the registered skills.

        The phrase "意图路由" is a wire contract, not decoration: the stub provider recognises a
        supervisor call by it, so it has to survive this generation. The per-route note and the
        JSON shape come from the skills and from the fixed tail below.
        """
        entries: list[str] = []
        for index, skill in enumerate(self._by_action.values(), start=1):
            entry = f'{index}. "{skill.action}" → 交给"{skill.title}"：{skill.duty}'
            if skill.examples:
                entry += "\n   例如" + "、".join(skill.examples)
            if skill.note:
                entry += "\n   " + skill.note
            entries.append(entry)
        count = {2: "两", 3: "三", 4: "四", 5: "五"}.get(len(entries), str(len(entries)))
        return (
            "你是 FusionPilot（一体化雷达与电子对抗仿真平台）智能助手的主管（supervisor），"
            f"负责意图路由与分派。你要判断用户这句话该交给团队里哪位专员处理，只返回 JSON。\n\n"
            f"{count}位专员：\n"
            + "\n".join(entries)
            + "\n\n返回 JSON：\n"
            '{"action": "'
            + "|".join(self._by_action)
            + '", "because": "一句话说明为什么这么分派（中文，20 字以内）", '
            '"question": "仅 clarify 时填写，一句简短的反问"}\n\n'
            "只返回 JSON，不要任何其他内容。"
        )
