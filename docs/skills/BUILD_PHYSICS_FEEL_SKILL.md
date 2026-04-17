# Build Guide — Physics "Feel" Skill (Anchor Demo)

**For:** the human actually building this
**Spec:** [../superpowers/specs/2026-04-17-phase4-specialist-skills.md](../superpowers/specs/2026-04-17-phase4-specialist-skills.md)
**Plan (agent-oriented):** [../superpowers/plans/2026-04-17-physics-feel-anchor-demo.md](../superpowers/plans/2026-04-17-physics-feel-anchor-demo.md)
**Goal:** ship "my player feels floaty" as an end-to-end anchor demo in ~2 days of focused work

---

## What you're building

A user types `my player feels floaty` in Unity Agent chat. Within ~6 seconds they get:

1. A diagnosis in plain English
2. Three tuning paths with real tradeoffs
3. One-click apply for whichever they pick
4. Before/after Game View screenshots
5. A physics-feel score delta (42 → 78)
6. An entry in the local learning ledger so the skill remembers what worked for this project

That's it. One sentence in, taste-encoded physics advice out. The whole thing becomes the template for every other specialist skill (UI, animation, TDD, etc.) later.

---

## Before you start

Open these in your editor so you can jump between them:

```
cli_anything/unity_mcp/core/agent_chat.py           # 2117 lines, chat routing
cli_anything/unity_mcp/core/expert_rules/physics.py # 132 lines, current structural audit
cli_anything/unity_mcp/core/expert_fixes.py         # 489 lines, current fixes
cli_anything/unity_mcp/core/routes.py               # route registry
cli_anything/unity_mcp/commands/debug.py            # capture command at L1375
unity-scripts/Editor/StandaloneRouteHandler.cs      # File IPC route handlers
```

Have running:
- Unity editor with a test project open (one with a floaty player — easy to make: Cube + Rigidbody, gravity −9.8, no drag, script that adds upward force)
- A terminal in `agent-harness/` for `pytest` and CLI calls

---

## Step 1 — Scaffold the skill interface

**Why first:** every later step imports from here. Get it right, the rest falls into place.

**Create:** `cli_anything/unity_mcp/core/skills/__init__.py`

```python
"""Specialist skills — each Unity domain gets one.

A Skill owns its domain end-to-end: audit, propose, apply, explain, prove.
Skills are registered in the SKILLS list. Third-party skills (DoTween,
Rewired, etc.) will plug in through the same shape later.
"""
from .base import (
    Skill,
    ProjectContext,
    AuditFinding,
    AuditResult,
    ProposedAction,
    ActionOutcome,
    ProofArtifact,
)

SKILLS: list[Skill] = []


def register_skill(skill: Skill) -> None:
    if not any(s.name == skill.name for s in SKILLS):
        SKILLS.append(skill)


def find_skill(name: str) -> Skill | None:
    for s in SKILLS:
        if s.name == name:
            return s
    return None


__all__ = [
    "Skill", "ProjectContext", "AuditFinding", "AuditResult",
    "ProposedAction", "ActionOutcome", "ProofArtifact",
    "SKILLS", "register_skill", "find_skill",
]
```

**Create:** `cli_anything/unity_mcp/core/skills/base.py`

Full dataclasses + Protocol as defined in the plan's Task 1 (copy the snippet from there — `dataclass(frozen=True)` for all five data types, `Protocol` for `Skill`).

**Test:** `cli_anything/unity_mcp/tests/test_skills_base.py`

- Build a `DummySkill` that implements the Protocol with no-op methods
- Register it, find it by name, assert dataclass roundtrip
- ~50 lines

**Run:**
```powershell
python -m pytest cli_anything/unity_mcp/tests/test_skills_base.py -v
```

**Commit:**
```
feat(skills): add skill interface scaffolding
```

---

## Step 2 — Physics-feel audit

**Why:** this is the taste layer. The thing Bezi can't copy.

**Create:** `cli_anything/unity_mcp/core/skills/physics_feel.py`

Start with just the audit half. Skip propose/apply for now.

### 2a. Gather inputs

Read from `ProjectContext.inspect_payload`:
- Unity `Physics.gravity.y` (inspect should surface this — check by running `workflow inspect --json` on your test project and grep for `gravity`)
- Hierarchy nodes → find the likely player (reuse `_PLAYER_TOKENS` pattern from `expert_rules/physics.py`)
- On the player: Rigidbody `mass`, `drag`, `angularDrag`, `useGravity`; or CharacterController `slopeLimit`, `stepOffset`

If any of those aren't in `inspect` output today, that's your first integration gap. Note it and fall back to defaults — don't block the whole skill on one missing field.

### 2b. Compute the floatiness signal

```python
def _airtime_estimate(jump_power: float, gravity_y: float) -> float:
    """Kinematic estimate: t = 2v/|g| for a simple impulse jump."""
    g = abs(gravity_y) or 9.8
    return (2.0 * jump_power) / g

def _floatiness_score(airtime: float, drag: float, gravity_y: float) -> int:
    """0-100, higher = floatier."""
    airtime_penalty = min(airtime / 0.8, 2.0) * 40   # 0.4s snappy, 0.8s baseline, 1.6s+ floaty
    drag_penalty = (1.0 - min(drag, 3.0) / 3.0) * 25
    gravity_penalty = (1.0 - min(abs(gravity_y) / 20.0, 1.0)) * 15
    raw = airtime_penalty + drag_penalty + gravity_penalty
    return max(0, min(100, int(raw)))
```

### 2c. Build findings

For each floatiness factor above threshold, add an `AuditFinding` with a **plain English detail string**. Not "Rigidbody.drag < threshold." Say "Your drag is 0, which means the player never slows down in air. That reads as floaty."

### 2d. Return AuditResult

```python
def audit_physics_feel(context: ProjectContext) -> AuditResult:
    # ... gather, compute, build findings ...
    return AuditResult(
        skill="physics_feel",
        score=100 - floatiness,   # invert so higher = better feel
        grade=grade_score(100 - floatiness),
        confidence=0.8 if found_player else 0.5,
        findings=findings,
        summary={"floatiness": floatiness, "airtime_s": airtime, ...},
    )
```

**Test:** `tests/test_physics_feel.py` with four mock contexts:
1. No player found → low confidence, "couldn't find player" finding
2. Floaty player (gravity −9.8, drag 0, jump 10) → high floatiness, 3+ findings
3. Snappy player (gravity −25, drag 1.5, jump 8) → low floatiness
4. Missing rigidbody → graceful fallback

**Run + commit:**
```
feat(skills): add physics-feel audit with floatiness signal
```

---

## Step 3 — Three tuning paths (propose)

**In the same file.** Add a `propose` function that takes the audit + user request text and returns three `ProposedAction` objects.

```python
def propose_physics_feel_tuning(
    audit: AuditResult, request: str
) -> list[ProposedAction]:
    current = audit.summary
    paths = []

    # Path 1: Snappy platformer
    paths.append(ProposedAction(
        action_id="physics_feel/snappy",
        title="Snappier jump (Celeste-style)",
        tradeoff=(
            "Gravity jumps from {} to -25, jump power stays. "
            "Player hits peak faster and falls quicker. "
            "Feels responsive. Tradeoff: less hangtime for precise air control."
        ).format(current["gravity_y"]),
        preview={"gravity_y": -25.0, "drag": current["drag"]},
        reversible=True,
    ))

    # Path 2: Controlled air
    paths.append(ProposedAction(
        action_id="physics_feel/controlled",
        title="More air control (Hollow Knight-style)",
        tradeoff=(
            "Drag rises from {} to 2.0, gravity unchanged. "
            "Player slows in air, reads as heavier without losing hangtime. "
            "Tradeoff: horizontal air moves feel lower-energy."
        ).format(current["drag"]),
        preview={"gravity_y": current["gravity_y"], "drag": 2.0},
        reversible=True,
    ))

    # Path 3: Arcade / stylized
    paths.append(ProposedAction(
        action_id="physics_feel/arcade",
        title="Arcade bounce (Mario 64-style)",
        tradeoff=(
            "Gravity to -30 but jump power raised to match peak height. "
            "Extremely punchy, feels weighty on landings. "
            "Tradeoff: physics objects in the scene will also fall faster unless you use a per-player gravity override."
        ),
        preview={"gravity_y": -30.0, "drag": current["drag"], "jump_power_mult": 1.4},
        reversible=True,
    ))

    return paths
```

The `tradeoff` strings are the skill's value. Spend time writing them like a senior Unity dev would explain to a junior. Reference real games. Name what the user gains and loses. This is what makes it not-Bezi.

**Test:** extend `test_physics_feel.py` with propose assertions — 3 paths, stable action_ids, each has non-empty tradeoff string.

**Commit:**
```
feat(skills): add physics-feel tuning proposals with tradeoffs
```

---

## Step 4 — Apply + capture

This is where route gaps bite. Check before writing:

```powershell
cli-anything-unity-mcp --json tools --search physics
cli-anything-unity-mcp --json tools --search component
cli-anything-unity-mcp --json tool-info unity_set_physics_gravity
```

**What you'll probably find:**
- Plugin HTTP path: has `MCPPhysicsCommands.cs` and `MCPComponentCommands.cs` — set-gravity and set-field routes exist
- Standalone File IPC path: `StandaloneRouteHandler.cs` does NOT have these yet

**Two options:**

**Option A (fastest):** target plugin HTTP only for MVP. Skill errors cleanly on File IPC with "This tuning needs the AnkleBreaker plugin for now." Ship the demo, file a follow-up to port to File IPC.

**Option B (better long-term):** add bounded `physics/set-gravity` and `component/set-rigidbody-field` routes to `StandaloneRouteHandler.cs`. ~80 lines of C#. The read-existing-Rigidbody-field path is already solved by `gameobject/inspect` routes, so you're mostly adding the write side. Gravity write is a one-liner: `Physics.gravity = new Vector3(0, value, 0);`.

**Recommendation: Option A first.** Get the demo end-to-end on one transport, prove the loop works, then port to File IPC as its own commit. Don't let route-porting block the anchor.

### Apply function

```python
def apply_physics_feel(action: ProposedAction, bridge) -> ActionOutcome:
    before = _read_current_values(bridge)  # read via gameobject/inspect

    try:
        # Undo group
        bridge.call("undo/begin-group", {"name": f"physics-feel:{action.action_id}"})

        # Write gravity
        if "gravity_y" in action.preview:
            bridge.call("physics/set-gravity", {
                "y": action.preview["gravity_y"]
            })

        # Write rigidbody drag on player
        if "drag" in action.preview:
            bridge.call("component/set-rigidbody-field", {
                "target": _player_path(bridge),
                "field": "drag",
                "value": action.preview["drag"],
            })

        bridge.call("undo/end-group", {})
    except Exception as e:
        return ActionOutcome(
            action_id=action.action_id,
            applied=False, before=before, after=before,
            captures=[], error=str(e),
        )

    after = _read_current_values(bridge)
    captures = _capture_before_after(bridge, action.action_id)

    return ActionOutcome(
        action_id=action.action_id, applied=True,
        before=before, after=after,
        captures=captures, error=None,
    )
```

### Capture

Reuse `graphics/game-capture` route (see `commands/debug.py` L1375 for the pattern). Pre-apply capture + post-apply capture, named `{timestamp}-before.png` and `{timestamp}-after.png` under `.umcp/captures/physics-feel/`.

**Important:** for the MVP, run captures in edit mode — not play mode. Play-mode captures need Unity to be in play mode already, which adds a huge UX tax on the demo. Edit-mode scene capture is good enough to show the player GO position before and after settings changes. Real feel requires play mode, but that's a v2 concern.

**Test:** extend `test_physics_feel.py` with a mock-bridge apply path. Verify before/after dicts differ, captures list has 2 entries, error is None on happy path.

**Commit:**
```
feat(skills): apply physics-feel tuning with before/after capture
```

---

## Step 5 — Wire into chat

**File:** `cli_anything/unity_mcp/core/agent_chat.py`

### 5a. Intent detection in `_OfflineUnityAssistant`

Find `_OfflineUnityAssistant` at L64. Find the pattern table near the top of the class (where `_CREATE_PRIMITIVE_RE`, `_GREETING_RE`, `_PLAYER_TOKENS` live). Add:

```python
_PHYSICS_FEEL_RE = re.compile(
    r"\b(floaty|floats?|weighty|heavy|slippery|snappy|stiff|sluggish|"
    r"sloppy|jumps?\s+feel|movement\s+feel|feels?\s+off|feels?\s+wrong|"
    r"doesn't\s+feel\s+right)\b",
    re.IGNORECASE,
)
```

In `_dispatch` (L77), add a branch:

```python
if self._PHYSICS_FEEL_RE.search(text):
    return self._build_physics_feel_reply(text)
```

### 5b. Build the proposal reply

```python
def _build_physics_feel_reply(self, text: str) -> str:
    from ..skills.physics_feel import audit_physics_feel, propose_physics_feel_tuning

    context = self._project_context()  # exists on _OfflineUnityAssistant
    audit = audit_physics_feel(context)
    proposals = propose_physics_feel_tuning(audit, text)

    # Stash for follow-up apply
    self._pending_physics_proposals = {p.action_id: p for p in proposals}

    lines = [
        f"**Physics feel check:** score {audit.score}/100",
        "",
        "**Diagnosis:**",
    ]
    for f in audit.findings[:3]:
        lines.append(f"- {f.detail}")
    lines.append("")
    lines.append("**Three tuning paths:**")
    for i, p in enumerate(proposals, 1):
        lines.append(f"\n**{i}. {p.title}**")
        lines.append(f"   {p.tradeoff}")
    lines.append("")
    lines.append("Reply `apply 1`, `apply 2`, or `apply 3` to try one. I'll capture before/after.")
    return "\n".join(lines)
```

### 5c. Handle the follow-up

Add another regex + dispatch branch for `^apply\s+([123]|snappy|controlled|arcade)`. Pull the stashed proposal, call `apply_physics_feel`, format the outcome reply with before/after values and capture paths.

**Test:** extend `tests/test_chat_e2e.py`:
- "my player feels floaty" → proposal reply contains "three tuning paths"
- follow-up "apply 1" → outcome reply contains "before" and "after"
- follow-up without prior proposal → graceful "no pending proposal" message

**Commit:**
```
feat(chat): route physics-feel intent to specialist skill
```

---

## Step 6 — Learning ledger

**Check first:** `grep -r "ledger" cli_anything/unity_mcp/core/` — if a ledger surface already exists, use it. If not:

**Create:** `cli_anything/unity_mcp/core/learning/ledger.py`

```python
"""Append-only run ledger. Every skill outcome gets one line.

Used later for eval/replay, project-aware memory, and outcome-driven
learning. Never deletes entries. Safe to tail.
"""
from __future__ import annotations
from pathlib import Path
import json
from datetime import datetime, UTC
from typing import Any


def _ledger_path(project_root: Path) -> Path:
    d = project_root / ".umcp" / "ledger"
    d.mkdir(parents=True, exist_ok=True)
    return d / "runs.jsonl"


def append_run(project_root: Path, entry: dict[str, Any]) -> None:
    entry = dict(entry)
    entry.setdefault("timestamp", datetime.now(UTC).isoformat())
    with _ledger_path(project_root).open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def read_runs(project_root: Path, limit: int | None = None) -> list[dict[str, Any]]:
    p = _ledger_path(project_root)
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    if limit is not None:
        lines = lines[-limit:]
    return [json.loads(line) for line in lines if line.strip()]
```

Call `append_run` at the end of `apply_physics_feel` with the full outcome dict.

**Test:** `tests/test_learning_ledger.py` — append, read, limit, roundtrip.

**Commit:**
```
feat(learning): add append-only run ledger for skill outcomes
```

---

## Step 7 — Patch PLAN.md + README

Open `../../PLAN.md`. Find `### Phase 4 — Expert Unity Developer Layer`. Replace with the patch block from the end of the spec doc (`docs/superpowers/specs/2026-04-17-phase4-specialist-skills.md` → "PLAN.md patch (ready to apply on approval)" section).

Also:
- Add the "Three Modes" block under Product Thesis per the spec
- Update "Current Strategic Priority" with the specialist-skills item

In `README.md`, find the "In-Editor Agent" section. Add one line after the current bullets:

> - **Physics "feel" skill:** type *"my player feels floaty"* and get diagnosis, three tuning paths with tradeoffs, one-click apply, and before/after capture — powered by the specialist physics skill, not a generic LLM wrapper

**Commit:**
```
docs: land phase 4 specialist-skills identity + physics-feel demo
```

---

## Definition of done

- [ ] Skill interface shipped, tests green
- [ ] `audit_physics_feel` returns meaningful findings on a real floaty-player project
- [ ] `propose_physics_feel_tuning` returns 3 paths with distinct tradeoff strings
- [ ] `apply_physics_feel` writes values via bridge, captures before/after, returns ActionOutcome
- [ ] Chat flow: "my player feels floaty" → proposal → "apply 1" → outcome, all in under 6s on real Unity
- [ ] Ledger entry written per apply, readable via `read_runs`
- [ ] PLAN.md reflects Phase 4 identity
- [ ] README mentions the demo
- [ ] Full test suite green (track1/2A tests must still pass)
- [ ] Nothing pushed. Commits only.

---

## When to ping me back

- Route gaps in standalone File IPC are worse than expected → might need a design call on Option A vs B
- `inspect` payload doesn't surface Physics.gravity or Rigidbody fields → integration doc update needed
- LLM-first path wiring is unclear → pair on the tool-registration surface for `ChatBridge`
- Test is flaky, score calculation feels off → tune the `_floatiness_score` weights together
- Done and you want a review pass before merging to main

---

## Why these steps are in this order

1. Interface first → every step imports from it. Change costs compound later.
2. Audit before propose → can't propose without a signal.
3. Propose before apply → paths drive what apply writes.
4. Apply before chat → chat wires a working skill, not stubs.
5. Ledger after apply → you already have outcome data to log; bolting it on last is cheaper than weaving it through.
6. Docs last → they describe what actually shipped, not what we hoped would ship.

Each commit leaves `main` green. If you run out of time halfway, the repo stays shippable.
