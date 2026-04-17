"""Dataclass + Protocol shapes for specialist skills.

Every skill — built-in or third-party — implements the same five methods:

    audit(context) -> AuditResult
    propose(audit, request) -> list[ProposedAction]
    apply(action, bridge) -> ActionOutcome
    explain(outcome) -> str
    capture_proof(bridge, tag) -> ProofArtifact

All skill-facing data types are frozen dataclasses so results are safe to
pass between chat threads, workflow runs, and the learning ledger without
accidental mutation. The ``Skill`` protocol is structural so a skill does
not need to inherit from it — implementing the five methods is enough.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ProjectContext:
    """Inputs a skill's audit method needs, packaged for easy passing."""

    project_path: str | None
    selected_port: int | None
    inspect_payload: dict[str, Any] | None = None
    systems_summary: dict[str, Any] | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditFinding:
    """One thing a skill noticed."""

    severity: str  # "low" | "medium" | "high"
    title: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditResult:
    """Output of a skill's audit pass. Findings + score + explainability."""

    skill: str
    score: int
    grade: str
    confidence: float
    findings: list[AuditFinding] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProposedAction:
    """One bounded thing a skill can do. Must be reversible."""

    action_id: str
    title: str
    tradeoff: str
    preview: dict[str, Any] = field(default_factory=dict)
    reversible: bool = True


@dataclass(frozen=True)
class ActionOutcome:
    """Result of applying a proposed action."""

    action_id: str
    applied: bool
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    captures: list[str] = field(default_factory=list)
    error: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProofArtifact:
    """Evidence a skill produced. Screenshots, markdown, score deltas."""

    kind: str  # "screenshot-before" | "screenshot-after" | "markdown" | "score-delta"
    path: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Skill(Protocol):
    """Structural protocol every specialist skill implements.

    Skills are plain objects; they do not need to inherit from this class.
    ``isinstance(obj, Skill)`` works because of ``runtime_checkable``.
    """

    name: str
    version: str

    def audit(self, context: ProjectContext) -> AuditResult:
        """Inspect project state. No mutation."""
        ...

    def propose(
        self, audit: AuditResult, request: str
    ) -> list[ProposedAction]:
        """Turn findings + user intent into concrete bounded actions."""
        ...

    def apply(
        self, action: ProposedAction, bridge: Any
    ) -> ActionOutcome:
        """Execute one bounded action. Must be reversible or undoable."""
        ...

    def explain(self, outcome: ActionOutcome) -> str:
        """Plain-English explanation of what changed and why."""
        ...

    def capture_proof(self, bridge: Any, tag: str) -> ProofArtifact:
        """Screenshot / log / measurement that proves before vs after."""
        ...


__all__ = [
    "ActionOutcome",
    "AuditFinding",
    "AuditResult",
    "ProjectContext",
    "ProofArtifact",
    "ProposedAction",
    "Skill",
]
