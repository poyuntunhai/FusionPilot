"""
Skills: the specialists the turn graph can route into.

``SKILLS`` is the registry the application uses. ``agent_graph`` reads its route map and its
prompts from here, so "which specialists exist" is answered in one place and a new skill is a
registration rather than an edit across three files plus a graph node.
"""

from __future__ import annotations

from .builtin import (
    BUILTIN_SKILLS,
    CONCEPT_SYSTEM_PROMPT,
    PLANNER_SYSTEM_PROMPT,
    build_registry,
)
from .skill import (
    CLARIFY,
    CONCEPT_QA,
    EXPERIMENT,
    EXPLORE,
    ROUTED_ACTIONS,
    Skill,
    SkillRegistry,
)

# The registry the running agent uses. Rebuilt per import is fine: it is four dataclasses.
SKILLS = build_registry()

__all__ = [
    "CLARIFY",
    "CONCEPT_QA",
    "EXPERIMENT",
    "EXPLORE",
    "ROUTED_ACTIONS",
    "SKILLS",
    "BUILTIN_SKILLS",
    "CONCEPT_SYSTEM_PROMPT",
    "PLANNER_SYSTEM_PROMPT",
    "Skill",
    "SkillRegistry",
    "build_registry",
]
