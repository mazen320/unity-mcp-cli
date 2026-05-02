"""Tests for the skill interface scaffolding."""
from __future__ import annotations

import dataclasses
from contextlib import contextmanager

from cli_anything.unity_mcp.core.skills import (
    ActionOutcome,
    AuditFinding,
    AuditResult,
    ProjectContext,
    ProofArtifact,
    ProposedAction,
    Skill,
    SKILLS,
    clear_skills,
    find_skill,
    register_skill,
)


@contextmanager
def _raises(expected_exception):
    try:
        yield
    except expected_exception:
        return
    raise AssertionError(f"Expected {expected_exception.__name__} to be raised")


class _DummySkill:
    """Minimal skill used to exercise the Protocol + registry."""

    name = "dummy"
    version = "0.1.0"

    def audit(self, context: ProjectContext) -> AuditResult:
        return AuditResult(
            skill=self.name,
            score=80,
            grade="strong",
            confidence=0.9,
            findings=[AuditFinding(severity="low", title="ok", detail="nothing wrong")],
            summary={"context_path": context.project_path},
        )

    def propose(self, audit: AuditResult, request: str) -> list[ProposedAction]:
        return [
            ProposedAction(
                action_id="dummy/noop",
                title="Do nothing",
                tradeoff="Literally nothing changes.",
                preview={"noop": True},
            )
        ]

    def apply(self, action: ProposedAction, bridge) -> ActionOutcome:
        return ActionOutcome(
            action_id=action.action_id,
            applied=True,
            before={},
            after={},
            captures=[],
            error=None,
        )

    def explain(self, outcome: ActionOutcome) -> str:
        return f"Applied {outcome.action_id}"

    def capture_proof(self, bridge, tag: str) -> ProofArtifact:
        return ProofArtifact(kind="markdown", path=None, data={"tag": tag})

def test_protocol_structural_check() -> None:
    skill = _DummySkill()
    assert isinstance(skill, Skill)


def test_register_and_find() -> None:
    skill = _DummySkill()
    register_skill(skill)
    assert SKILLS == [skill]
    assert find_skill("dummy") is skill
    assert find_skill("DUMMY") is skill  # case-insensitive lookup
    assert find_skill("does-not-exist") is None


def test_register_idempotent() -> None:
    skill = _DummySkill()
    register_skill(skill)
    register_skill(skill)
    register_skill(_DummySkill())  # same name, different instance
    assert len(SKILLS) == 1


def test_clear_skills() -> None:
    register_skill(_DummySkill())
    assert SKILLS
    clear_skills()
    assert SKILLS == []


def test_dataclasses_are_frozen() -> None:
    finding = AuditFinding(severity="high", title="t", detail="d")
    with _raises(dataclasses.FrozenInstanceError):
        finding.severity = "low"  # type: ignore[misc]

    result = AuditResult(
        skill="x",
        score=50,
        grade="weak",
        confidence=0.5,
    )
    with _raises(dataclasses.FrozenInstanceError):
        result.score = 99  # type: ignore[misc]

    action = ProposedAction(action_id="a", title="t", tradeoff="t")
    with _raises(dataclasses.FrozenInstanceError):
        action.title = "new"  # type: ignore[misc]

    outcome = ActionOutcome(action_id="a", applied=True)
    with _raises(dataclasses.FrozenInstanceError):
        outcome.applied = False  # type: ignore[misc]

    artifact = ProofArtifact(kind="markdown")
    with _raises(dataclasses.FrozenInstanceError):
        artifact.kind = "other"  # type: ignore[misc]


def test_audit_result_roundtrip_through_skill() -> None:
    skill = _DummySkill()
    context = ProjectContext(project_path="/tmp/demo", selected_port=None)
    result = skill.audit(context)

    assert result.skill == "dummy"
    assert result.score == 80
    assert result.grade == "strong"
    assert len(result.findings) == 1
    assert result.findings[0].severity == "low"
    assert result.summary == {"context_path": "/tmp/demo"}


def test_full_skill_lifecycle_roundtrip() -> None:
    skill = _DummySkill()
    context = ProjectContext(project_path=None, selected_port=None)
    audit = skill.audit(context)
    proposals = skill.propose(audit, "go")
    assert len(proposals) == 1
    outcome = skill.apply(proposals[0], bridge=object())
    assert outcome.applied is True
    explanation = skill.explain(outcome)
    assert "dummy/noop" in explanation
    proof = skill.capture_proof(bridge=object(), tag="after")
    assert proof.kind == "markdown"
    assert proof.data["tag"] == "after"


def test_project_context_defaults() -> None:
    context = ProjectContext(project_path=None, selected_port=None)
    assert context.inspect_payload is None
    assert context.systems_summary is None
    assert context.extras == {}
