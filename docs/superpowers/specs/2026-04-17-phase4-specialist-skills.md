# Phase 4 — Specialist Skills (with anchor demo)

**Date:** 2026-04-17
**Status:** Draft — awaiting approval to patch `PLAN.md`
**Author:** Mazen + Claude
**Supersedes:** the current Phase 4 section of `PLAN.md` ("Expert Unity Developer Layer")

---

## Why this spec exists

The current `PLAN.md` Phase 4 says "deepen specialist lenses." That framing is too generic. It describes what Bezi already ships. It does not name what makes this product structurally different.

The approved unified product plan (`docs/superpowers/specs/2026-04-14-unified-product-plan.md`) already defined:
- specialist skills per Unity domain (UI, Physics, Animation, TDD, Level Design, Tech Art, Systems, Prototyping)
- three agent modes (Reactive, Watchdog, Autonomous)
- full lifecycle per skill (Build → Iterate → Polish)

That identity never landed in `PLAN.md`. This spec folds it in, grounds it in a concrete anchor demo, and leaves the architectural door open for third-party skills (DoTween, Rewired, FMOD, Timeline, Shader Graph, addressables, netcode, etc.) without building the plugin registry yet.

---

## Product identity (for Phase 4)

> A deep-specialist AI developer that lives in your Unity editor, understands your project, learns from every session, sees it visually, and can build, iterate, and polish with you at whatever level you need.

Each domain gets a **real skill** — not a generalist chat wrapper with keywords. Each skill covers the full lifecycle:

**Build it → Iterate on it → Polish it**

Skills compose. "Build a HUD and write tests for it" uses UI + TDD together. "My combat feels weak" uses Physics + Animation + Tech Art together.

---

## Three modes

Every skill works in three modes. The mode is chosen by the router/planner from the user request.

| Mode | Trigger | Example |
|---|---|---|
| **Reactive** | User asks, agent answers and acts | "My player feels floaty" → diagnose → propose → apply → capture before/after |
| **Watchdog** | Agent observes project, surfaces proactively | "Your rigidbody has no drag — that's why movement feels off." No prompt needed. |
| **Autonomous** | User gives goal, agent plans and executes, checks in at decision points | "Polish the combat feel" → audit → propose plan → execute step by step → before/after proof |

---

## Skills matrix

| Skill | Covers |
|---|---|
| **UI / UX** | Canvas setup, HUD layout, scaling, transitions, accessibility, spacing, feel |
| **Physics** | Forces, friction, drag, mass, collision response, CharacterController, rigidbody tuning, movement feel — the discipline, not just the API |
| **Animation** | Animator controllers, blend trees, state machines, root motion, transitions, clip authoring |
| **TDD** | Test-driven workflow, EditMode + PlayMode test scaffolding, coverage, red-green-refactor |
| **Level Design** | Scene composition, readability, visual anchors, density, lighting, player guidance |
| **Tech Art** | Materials, shaders, texture import settings, VFX, post-processing, render pipeline hygiene |
| **Systems** | Scene architecture, runtime hygiene, prefab coverage, event systems, audio, performance |
| **Prototyping** | Rapid scaffold: GO + component + script + verify in one flow |

Each skill must be able to:

1. **Audit** the current state (what is wrong, what is missing, what could be better)
2. **Build / edit** (create, repair, polish — not just report)
3. **Explain reasoning** (why this matters, what the tradeoff is, in plain English)
4. **Learn outcomes** (log result to the local run ledger; remember project preferences across runs)

---

## Skill interface contract

Every skill — current or future — implements the same shape. This is the contract. It is deliberately minimal so third-party contributors can add skills (DoTween, Rewired, FMOD, Timeline, Shader Graph, addressables, netcode, Cinemachine, custom studio tooling) without needing to modify the core.

```python
class Skill(Protocol):
    name: str                       # "physics", "ui", "dotween", ...
    version: str

    def audit(self, context: ProjectContext) -> AuditResult:
        """Return findings, score, summary. No mutation."""

    def propose(self, audit: AuditResult, request: UserRequest) -> list[ProposedAction]:
        """Turn findings + user intent into concrete bounded actions with tradeoffs."""

    def apply(self, action: ProposedAction, bridge: UnityBridge) -> ActionOutcome:
        """Execute one bounded action. Must be reversible or undoable."""

    def explain(self, outcome: ActionOutcome) -> str:
        """Plain-English explanation of what changed and why."""

    def capture_proof(self, bridge: UnityBridge) -> ProofArtifact:
        """Screenshot / log / measurement that proves before vs after."""
```

**Non-goals for this phase:**
- We are NOT building a dynamic plugin registry, dependency resolution, or a marketplace.
- We are NOT shipping a Skill SDK package.
- We are NOT adding runtime skill discovery.

Skills are registered in code via a central list for now. The interface is stable; the loader is not. When a second third-party contributor actually wants to ship a skill, we build the loader. Until then, premature.

---

## Skill lifecycle stages

Each skill ships in three stages. A skill is not "done" until stage 3.

### Stage 1 — Audit-only (current state of most lenses)
Reports findings and a score. No mutation. Example today: `workflow expert-audit --lens physics`.

### Stage 2 — Bounded build / fix
Adds bounded mutations tied to specific findings. Reversible. Example today: `workflow quality-fix --lens physics --fix player-character-controller --apply`.

### Stage 3 — Full lifecycle (Build → Iterate → Polish)
- Understands taste/feel in the domain (e.g. "floaty" vs "snappy" for physics).
- Proposes multiple tuning paths with tradeoffs.
- Applies bounded edits with undo.
- Captures before/after proof.
- Logs outcome to learning ledger.
- Ties into chat (Reactive), watchdog (proactive surfacing), and autonomous mode (goal decomposition).

**Today:** Physics skill is at Stage 2. Most other lenses are at Stage 1.
**Phase 4 exit criteria:** at least one skill at Stage 3, and a clear template so the rest can follow.

---

## Anchor demo: "my player feels floaty"

Phase 4 ships behind one concrete demo that exercises the full stack. If the demo works end-to-end and the skill interface survives contact with it, the spec is validated. Other skills get built from the same template.

### The experience

**User (in Unity Agent chat):** "my player feels floaty"

**Agent (within ~4 seconds):**

1. Detects physics-feel intent → routes to Physics skill in Reactive mode.
2. Runs targeted audit: inspects the likely player GameObject (Rigidbody or CharacterController), pulls drag, mass, gravity scale, jump power heuristics, air control, slopeLimit.
3. Computes a "floatiness signal": gravity weakness, low drag, high jump power relative to mass, long airtime estimate.
4. Replies with:
   - **Diagnosis:** "Your player feels floaty because gravity is −9.8, drag is 0, jump power is 10 → estimated airtime 1.2s. That reads as floaty."
   - **Three tuning paths with tradeoffs:**
     - **Snappier jump:** raise gravity to −20, reduce jump power to 8 (tradeoff: feels heavier, reaches same height faster)
     - **More control:** add drag 2, keep gravity, reduce jump power to 7 (tradeoff: air control improves, terminal velocity lower)
     - **Arcade feel:** custom gravity override on player, jump power 12, gravity −30 (tradeoff: only the player feels heavier; physics objects unchanged)
   - **One-click apply** for any of the three, or "apply snappier and show me."
5. On apply: bounded edit via bridge, undo group registered. Before/after Game View capture. Score delta: Physics-feel 58 → 81.
6. Logs outcome to `.umcp/ledger/runs.json` with: request, chosen path, before/after values, user acceptance, capture paths.
7. Next time the user asks about physics in this project, the skill remembers the chosen path preference.

### Why this demo is the right anchor

- **User efficiency:** one sentence, ~4 second response, one click to apply. Not a 30-step wizard.
- **Exercises five phases at once:** Phase 3 (visible magic in panel), Phase 4 (specialist skill), Phase 5 (LLM-first routing), Phase 6 (capture + markdown export), Phase 7 (learning ledger seed).
- **Structurally hard for competitors to copy:** Bezi does Actions but one generalist agent. Muse does generators. Nobody ships "physics as discipline" with local learning.
- **Template value:** once this works, the same shape clones to Animation ("my attack doesn't feel impactful"), UI ("my HUD feels cluttered"), Level Design ("this room feels empty"). Same interface, different expertise.
- **Visible before/after:** jump arc capture is an obvious demo GIF for GitHub.

### Taste vs API

The key difference from Bezi/Coplay: they wrap the Unity API. This skill encodes **taste**. A generalist LLM can tell you what `Rigidbody.drag` does. A physics skill knows that drag=2 + gravity=−15 + jump=8 feels like Hollow Knight, and drag=0 + gravity=−25 + jump=14 feels like Celeste. That's the discipline. That's what users pay for (or in our case, what wins users over vs a paid closed tool).

---

## Out of scope for this spec (deliberately)

- The dynamic plugin loader / Skill SDK package (wait for second contributor)
- Third-party skill packages like DoTween, Rewired, FMOD, Cinemachine, netcode (the interface will support them; the skills themselves come later)
- Autonomous mode full implementation beyond the stubs Track 2A already landed
- Watchdog depth beyond the 60s-poll stub Track 2A already landed
- The polish tier of non-physics skills (UI / animation / TDD stage 3) — they get scheduled after physics anchor ships and the template is proven

---

## Exit criteria

Phase 4 is done when:

1. **Skill interface is stable.** Physics skill implements it. The interface file (`core/skills/base.py`) has docstring and type signatures frozen.
2. **Physics skill at Stage 3.** Full Build → Iterate → Polish lifecycle works in chat and CLI.
3. **Anchor demo works end-to-end.** "my player feels floaty" in the Unity Agent chat produces diagnosis, 3 tuning paths, one-click apply, before/after capture, score delta, ledger entry. Under 6 seconds cold.
4. **Template documented.** A contributor can read `docs/skills/WRITING_A_SKILL.md` and understand how to clone the physics skill shape for a new domain.
5. **At least one other skill (Animation OR UI) moved from Stage 1 to Stage 2** using the template, proving it transfers.

---

## PLAN.md patch (ready to apply on approval)

Replace the current `### Phase 4 — Expert Unity Developer Layer` section with:

```markdown
### Phase 4 — Specialist Skills

Focus:
- move from generic "expert lenses" to real specialist skills per Unity domain
- each skill covers the full lifecycle: Build → Iterate → Polish
- each skill encodes taste/discipline, not just API wrapping
- three modes work on every skill: Reactive (user asks), Watchdog (agent surfaces), Autonomous (goal decomposition)
- skill interface designed so future domain and third-party skills plug in through the same shape

Current skill roster:
- UI / UX, Physics, Animation, TDD, Level Design, Tech Art, Systems, Prototyping

Anchor demo:
- "my player feels floaty" → Physics skill in Reactive mode diagnoses, proposes three tuning paths with tradeoffs, one-click applies, captures before/after, logs outcome. Exercises Phase 3, 4, 5, 6, 7 in a single flow.

Visible unlocks:
- the assistant behaves like a specialist, not a wrapper
- users feel domain taste in the suggestions, not generic Unity advice
- skills compose (UI + TDD, Physics + Animation)
- before/after evidence is the norm for applied changes

Exit criteria:
- Physics skill at full Build → Iterate → Polish lifecycle
- Skill interface stable and documented for contributors
- At least one other skill moved from audit-only to bounded-fix using the same template
- The anchor demo runs end-to-end under 6 seconds from Unity Agent chat
```

Also add to the "Product Thesis" section, under the four layers, a new short block:

```markdown
### Three Modes

Every specialist skill works across three modes:
- **Reactive** — user asks, agent answers and acts
- **Watchdog** — agent observes, surfaces findings without prompting
- **Autonomous** — user gives a goal, agent plans and executes with decision-point check-ins

The router/planner chooses the mode from the request. The workflow executor runs the skill. The verifier captures proof. Same stack for all three modes.
```

Also update the "Current Strategic Priority" list to add after item 3:

```markdown
4. turn the existing expert lenses into real specialist skills (Build → Iterate → Polish), starting with Physics as the anchor
```

(renumber subsequent items).

---

## Open questions

- **Skill registration location.** Propose `cli_anything/unity_mcp/core/skills/__init__.py` with a flat `SKILLS` list. Simple. Defer registry pattern until needed.
- **Chat-intent routing.** Anchor demo needs intent detection for "feels floaty / weighty / heavy / slippery / snappy / stiff" → Physics skill. Either extend existing `_OfflineUnityAssistant._dispatch` regex patterns, or add a thin intent classifier that the LLM-first chat path can also use. Plan doc proposes the latter for consistency.
- **Capture timing.** For anchor demo, before/after Game View capture requires either stepping Unity briefly or using edit-mode snapshot. Plan doc proposes edit-mode snapshots pre- and post-apply; play-mode captures are deferred.

---

## Next step

If approved: execute `docs/superpowers/plans/2026-04-17-physics-feel-anchor-demo.md` to ship the anchor demo. PLAN.md patch applies as part of that plan's final task.
