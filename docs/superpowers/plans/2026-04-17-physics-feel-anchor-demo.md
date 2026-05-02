# Plan — Physics "Feel" Anchor Demo

**Date:** 2026-04-17
**Status:** Draft — awaiting approval
**Related spec:** [2026-04-17-phase4-specialist-skills.md](../specs/2026-04-17-phase4-specialist-skills.md)
**Branch:** `main` (commit-only, never push)
**Subagent-ready:** yes (tasks are parallelizable where noted)

---

## Context

The Phase 4 spec proposes "my player feels floaty" as the anchor demo that proves the specialist-skills architecture. This plan breaks that demo into concrete buildable tasks.

Relevant existing code:
- `core/expert_rules/physics.py` — 132 lines. Structural audit only (colliders, rigidbodies, CharacterController). No tuning awareness yet.
- `core/expert_fixes.py` — 489 lines. Has `player-character-controller` fix. No tuning fixes yet.
- `core/agent_chat.py` — 2117 lines. `_OfflineUnityAssistant` at L64 handles offline intents. `ChatBridge` at L1745 handles LLM-first and offline routing. Track 2A added capture helpers, player prototype, autonomous stubs.
- `commands/workflows/fix.py` — 218 lines. CLI entry point for quality-fix.
- `core/memory.py` — exists. Need to check whether a run ledger surface already exists or whether this plan adds one.

---

## Goal

Ship the anchor demo end-to-end:

> User types "my player feels floaty" in Unity Agent chat → within 6 seconds → diagnosis + 3 tuning paths with tradeoffs + one-click apply + before/after Game View capture + score delta + ledger entry.

Secondary: produce the reusable skill interface so the next specialist skill clones this shape.

---

## Task breakdown

Seven tasks. Tasks 1-3 can run in parallel. Tasks 4-7 serialize on top.

### Task 1 — Skill interface scaffolding

**Files to create:**
- `cli_anything/unity_mcp/core/skills/__init__.py` — exports `Skill` protocol, `SKILLS` registry list, `ProjectContext`, `AuditResult`, `ProposedAction`, `ActionOutcome`, `ProofArtifact` dataclasses.
- `cli_anything/unity_mcp/core/skills/base.py` — Protocol + dataclass definitions per the spec's skill interface contract.

**Shape (mirror spec, enforce via Protocol + dataclasses):**

```python
from dataclasses import dataclass, field
from typing import Protocol, Any

@dataclass(frozen=True)
class ProjectContext:
    project_path: str | None
    selected_port: int | None
    inspect_payload: dict[str, Any] | None
    systems_summary: dict[str, Any] | None

@dataclass(frozen=True)
class AuditFinding:
    severity: str        # "low" | "medium" | "high"
    title: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class AuditResult:
    skill: str
    score: int
    grade: str
    confidence: float
    findings: list[AuditFinding]
    summary: dict[str, Any]

@dataclass(frozen=True)
class ProposedAction:
    action_id: str       # stable id, used for apply
    title: str
    tradeoff: str
    preview: dict[str, Any]  # before/after values the agent will write
    reversible: bool

@dataclass(frozen=True)
class ActionOutcome:
    action_id: str
    applied: bool
    before: dict[str, Any]
    after: dict[str, Any]
    captures: list[str]  # file paths
    error: str | None

@dataclass(frozen=True)
class ProofArtifact:
    kind: str            # "screenshot-before" | "screenshot-after" | "markdown" | "score-delta"
    path: str | None
    data: dict[str, Any]

class Skill(Protocol):
    name: str
    version: str
    def audit(self, context: ProjectContext) -> AuditResult: ...
    def propose(self, audit: AuditResult, request: str) -> list[ProposedAction]: ...
    def apply(self, action: ProposedAction, bridge) -> ActionOutcome: ...
    def explain(self, outcome: ActionOutcome) -> str: ...
    def capture_proof(self, bridge, tag: str) -> ProofArtifact: ...
```

**Also in `__init__.py`:**
```python
SKILLS: list[Skill] = []  # populated by skill modules at import time

def register_skill(skill: Skill) -> None:
    SKILLS.append(skill)

def find_skill(name: str) -> Skill | None:
    for s in SKILLS:
        if s.name == name:
            return s
    return None
```

**Tests:** `tests/test_skills_base.py` — verify dataclasses roundtrip, Protocol structural check with a dummy skill, `register_skill` / `find_skill` behavior. ~50 lines.

---

### Task 2 — Physics-feel audit module

**File to create:** `cli_anything/unity_mcp/core/skills/physics_feel.py`

Extends the current structural `physics.py` lens with tuning awareness. Do NOT replace the existing structural lens — this is an additive skill that sits alongside it and reuses its findings.

**Core function signature:**
```python
def audit_physics_feel(context: ProjectContext) -> AuditResult:
    """Audit physics from a FEEL perspective.

    Pulls gravity from Physics settings, finds likely player GO, reads its
    Rigidbody or CharacterController, computes floatiness signal.
    """
```

**Signal computation (the "discipline" layer):**

- **Gravity magnitude:** `Physics.gravity.y`. Anything weaker than -9.8 can feel light for punchy movement.
- **Player jump estimate:** if we can find a jump script, parse `jumpPower` / `jumpForce` constants; else heuristic from Rigidbody.mass + inferred impulse.
- **Airtime estimate:** `t_air = 2 * jumpPower / |gravity|` (simple kinematic approximation).
- **Drag:** Rigidbody.drag, Rigidbody.angularDrag.
- **CharacterController slopeLimit, stepOffset** — stiffness signals.

**Floatiness score (0–100, higher = floatier):**
```
floatiness = clamp(
    40 * (airtime_s / 0.8) +          # 0.4s feels snappy, 1.2s feels floaty
    25 * (1.0 - min(drag, 3.0)/3.0) + # low drag contributes to floatiness
    15 * (1.0 - min(|gravity|/20, 1)),# weak gravity contributes
    0, 100
)
```

**Tuning paths (generated in `propose`):**

Three paths, chosen based on current project vibe:
1. **Snappy movement:** gravity=-20, jump scaled so peak height stays same, drag unchanged.
2. **Controlled air:** drag=2, gravity unchanged, jump power reduced by ~30%.
3. **Arcade / stylized:** per-player gravity override via `Physics.gravity` scaled body or a `customGravity` field if the movement script supports it, else fallback to option 1.

Each path carries `tradeoff` text in plain English.

**Tests:** `tests/test_physics_feel.py` — mock contexts for (a) no player, (b) floaty player, (c) snappy player, (d) missing rigidbody. Verify score, findings, propose output. ~120 lines.

---

### Task 3 — Physics-feel apply + capture

**File to extend:** `cli_anything/unity_mcp/core/skills/physics_feel.py`

**Apply function:**
```python
def apply_physics_feel(action: ProposedAction, bridge) -> ActionOutcome:
    """Apply one tuning path via bridge routes. Registers undo group."""
```

**Routes used:**
- `gameobject/get-components` — read current values before mutation
- `physics/set-gravity` (or equivalent in routes.py — verify exists; if not, add a bounded route to `unity-scripts/Editor/StandaloneRouteHandler.cs`)
- `component/set-field` — write rigidbody.drag, rigidbody.mass
- `script/patch` — only if the chosen path needs to edit a jump script constant; defer this to a follow-up task if routes don't support it cleanly. For the MVP, if the player has no accessible jump constant, skip the jump-power edit and adjust only gravity + drag. Mark in outcome.

**Capture:**
```python
def capture_proof(bridge, tag: str) -> ProofArtifact:
    """debug/capture kind=scene, timestamped filename, returns artifact path."""
```

Uses existing `debug capture` path. Writes to `.umcp/captures/physics-feel/{timestamp}-{tag}.png`.

**Undo:** wrap apply in a Unity undo group via existing `undo/begin-group` / `undo/end-group` routes if present; verify in `routes.py`.

**Tests:** extend `test_physics_feel.py` with mock-bridge apply path. Verify before/after dict, capture path format, undo group registered. ~60 lines.

---

### Task 4 — Chat intent routing

**Files to edit:** `cli_anything/unity_mcp/core/agent_chat.py`

**Two paths to wire:**

**A. Offline assistant path (`_OfflineUnityAssistant._dispatch`):**
Add regex for physics-feel intents:
```python
_PHYSICS_FEEL_RE = re.compile(
    r"\b(floaty|floats|weighty|heavy|slippery|snappy|stiff|sluggish|sloppy|jumps?\s+feel|movement\s+feel|feels?\s+off)\b",
    re.IGNORECASE,
)
```

Add handler `_build_physics_feel_reply` that:
1. Calls `physics_feel.audit(context)`.
2. Calls `physics_feel.propose(audit, user_text)` to get 3 paths.
3. Formats reply as: diagnosis paragraph + 3 numbered paths with tradeoffs + "Reply '1', '2', or '3' to apply, or 'apply snappier' / 'apply controlled' / 'apply arcade'."
4. Stashes pending proposals on the assistant instance (similar pattern to autonomous `_execute_pending_autonomous_plan` from Track 2A).

Add follow-up handler that detects "apply 1", "apply snappier", etc., pulls the stashed proposal, calls `apply`, runs before + after capture, computes score delta via existing `expert-audit --lens physics`, builds a reply with:
- "Applied: {path title}"
- "Before: {before values}"
- "After: {after values}"
- "Capture: before.png, after.png"
- "Physics-feel score: {before} → {after}"

**B. LLM-first path (`ChatBridge`):**
When LLM provider is active, expose the physics-feel skill as a tool the model can call (consistent with how other workflows are exposed today — verify the current tool exposure mechanism). The LLM routes; the skill executes. No bespoke LLM logic in the skill.

**Tests:** extend `tests/test_chat_e2e.py` with:
- "my player feels floaty" offline → proposal reply with 3 paths
- "apply 1" follow-up → outcome reply with before/after
- no-player scenario → graceful fallback reply

~80 lines added.

---

### Task 5 — Learning ledger seed

**Files:** check `core/memory.py` first. If a run ledger surface exists, use it. If not, add a minimal append-only ledger:

- `cli_anything/unity_mcp/core/learning/ledger.py` — `append_run(entry: dict)`, `read_runs(limit: int | None = None)`. Writes to `.umcp/ledger/runs.json` (JSON lines or array, pick simplest).

**Ledger entry shape for physics-feel:**
```json
{
  "timestamp": "2026-04-17T14:32:00Z",
  "skill": "physics_feel",
  "request": "my player feels floaty",
  "audit_score_before": 42,
  "audit_score_after": 78,
  "chosen_action": "snappy",
  "proposed_actions": ["snappy", "controlled", "arcade"],
  "before": {"gravity": -9.8, "drag": 0.0, "jumpPower": 10.0},
  "after": {"gravity": -20.0, "drag": 0.0, "jumpPower": 10.0},
  "capture_before": "path/to/before.png",
  "capture_after": "path/to/after.png",
  "user_accepted": true,
  "duration_ms": 4200
}
```

Ledger writes happen at `apply` time. Failures also get logged (with `applied: false` and `error`).

**Tests:** `tests/test_learning_ledger.py` — append, read, roundtrip, limit. ~40 lines.

---

### Task 6 — Contributor doc

**File to create:** `docs/skills/WRITING_A_SKILL.md`

Short (under 300 lines). Sections:
1. What a skill is (1 paragraph, link to spec)
2. The five methods (audit / propose / apply / explain / capture_proof) with minimal example each
3. How physics_feel is organized (file reference, line anchors)
4. How to add your own skill (copy `physics_feel.py`, rename, implement the 5 methods, register in `SKILLS`)
5. Testing pattern (mock bridge, mock context)
6. What NOT to do (no direct Unity API calls outside `bridge`, no unbounded mutations, must be reversible)

---

### Task 7 — PLAN.md patch + commit

After tasks 1-6 ship and tests pass:

1. Apply the PLAN.md patch from the spec (Phase 4 rewrite + Three Modes insert + Strategic Priority update).
2. Update `README.md` "Hero Workflows" or equivalent section to mention the physics-feel demo.
3. Add a short CHANGELOG/TODO entry.
4. Commit. Do not push.

---

## Test plan

**Unit:**
- `test_skills_base.py` — Protocol + dataclasses
- `test_physics_feel.py` — audit, propose, apply (mock bridge)
- `test_learning_ledger.py` — append/read

**E2E (mock bridge):**
- `test_chat_e2e.py` extensions — full "my player feels floaty" → propose → apply → outcome flow
- Verify capture paths recorded
- Verify ledger entry written

**Manual / live (optional, runs after code ships):**
- Against a real Unity project with a floaty player, run the demo from the Agent tab chat.
- Verify under-6-second response.
- Verify captures look right.

**Regression:**
- Run full test suite. Track 2A added 8 chat tests — must still pass. Track 1 split modules — must still pass.

---

## Exit criteria

1. All seven tasks complete.
2. Test suite green.
3. Physics-feel demo runs end-to-end on mock bridge in under 2s (real Unity target: under 6s cold).
4. PLAN.md patched. README mentions the demo.
5. `docs/skills/WRITING_A_SKILL.md` exists and is followable.
6. One commit per task (or logical grouping). Nothing pushed.

---

## Risks + mitigations

- **Route gaps:** `physics/set-gravity` or `component/set-field` for specific Rigidbody fields may not exist in the standalone File IPC bridge today. Mitigation: task 3 verifies routes first; if missing, add minimal bounded routes to `StandaloneRouteHandler.cs` as part of task 3, not a separate task.
- **Jump-power script editing is hard:** if the player's jump constant is buried in a custom script, automatic editing is risky. Mitigation: MVP skips jump-power edits when no accessible surface exists; outcome notes the skip; user can edit manually. Explicit limitation, not a bug.
- **LLM-first path may need new tool registration:** depending on how chat exposes workflows to the provider, task 4B may require touching the tool registration surface. Mitigation: keep offline path functional first (task 4A), treat LLM path as a second commit if scope grows.
- **Subagent scope:** if this is dispatched as one big subagent, context pressure could cause dropped tasks. Mitigation: dispatch as two subagents — (1) tasks 1+2+3 (skill infra + physics-feel core), (2) tasks 4+5 (chat wire-up + ledger). Tasks 6+7 run locally after both return.

---

## Dispatch recipe (when approved)

```
Subagent A — in worktree
Prompt: "Execute tasks 1, 2, 3 of
 docs/superpowers/plans/2026-04-17-physics-feel-anchor-demo.md.
 Commit each task as its own commit. Do not push. Return test output."

Subagent B — in worktree (after A returns green)
Prompt: "Execute tasks 4, 5 of the same plan. Use the skill interface
 shipped in A. Commit per task. Do not push."

Local — after B returns
- Task 6 (contributor doc)
- Task 7 (PLAN.md + README patches + final commit)
```
