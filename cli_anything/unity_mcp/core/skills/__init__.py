"""Specialist skills — each Unity domain gets one.

A Skill owns its domain end-to-end: audit, propose, apply, explain, prove.
Skills are registered in the ``SKILLS`` list. Third-party skills (DoTween,
Rewired, FMOD, Cinemachine, netcode, etc.) plug in through the same shape
later without modifying core — the registry today is a flat list; a dynamic
loader is deferred until a second contributor actually needs one.

See also:
- ``docs/superpowers/specs/2026-04-17-phase4-specialist-skills.md`` (spec)
- ``docs/skills/BUILD_PHYSICS_FEEL_SKILL.md`` (implementer walkthrough)
"""
from __future__ import annotations

from .base import (
    ActionOutcome,
    AuditFinding,
    AuditResult,
    ProjectContext,
    ProofArtifact,
    ProposedAction,
    Skill,
)

SKILLS: list[Skill] = []


def register_skill(skill: Skill) -> None:
    """Register a skill. Idempotent by ``skill.name``."""
    if not any(existing.name == skill.name for existing in SKILLS):
        SKILLS.append(skill)


def find_skill(name: str) -> Skill | None:
    """Look up a registered skill by name. Returns ``None`` if missing."""
    normalized = str(name or "").strip().lower()
    for skill in SKILLS:
        if skill.name == normalized:
            return skill
    return None


def clear_skills() -> None:
    """Test helper. Drops every registered skill. Do not use in production code."""
    SKILLS.clear()


__all__ = [
    "ActionOutcome",
    "AuditFinding",
    "AuditResult",
    "ProjectContext",
    "ProofArtifact",
    "ProposedAction",
    "Skill",
    "SKILLS",
    "clear_skills",
    "find_skill",
    "register_skill",
]
