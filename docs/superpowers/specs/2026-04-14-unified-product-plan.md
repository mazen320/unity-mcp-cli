# Unified Product Plan
**Date:** 2026-04-14
**Status:** Approved
**Author:** Mazen + Claude

---

## Product Identity

### What This Is

A deep-specialist AI agent that lives in your Unity editor.

It understands your project, learns from every session, sees what is happening visually, and can build things with you — scripts, GameObjects, components, prefabs, scenes. Ask it to prototype fast, fix a system, design a HUD, write tests, or polish the feel of your combat. Each skill is real expertise, not generic advice.

It is not just a chatbox. It is a developer that works with you at whatever level you need.

### Three Modes

**Reactive** — you ask, it answers and acts.
> "My player feels floaty" → diagnoses the physics, explains why, proposes a fix, applies it, shows you the result.

**Watchdog** — it observes your project, surfaces things proactively.
> "Your rigidbody has no drag — that is why movement feels off." No prompt needed.

**Autonomous** — give it a goal, it plans and executes, checks in at decision points.
> "Polish the combat feel" → runs audit → proposes plan → executes step by step → before/after proof.

### Chat Interface

The Unity panel chat should feel like talking to Claude in Cowork — clean, focused, natural. Not a dev tool UI. A conversation with a capable collaborator that happens to live inside Unity.

---

## Specialist Skills

Each domain has a real skill — not a general-knowledge wrapper. Each skill covers the full development lifecycle:

**Build it → Iterate on it → Polish it**

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

Each skill:
- Audits the current state (what is wrong, what is missing, what could be better)
- Builds and edits (creates, repairs, polishes — not just reports)
- Explains its reasoning (why this matters, what the tradeoff is)
- Learns from outcomes (what worked for this project gets remembered)

Skills compose. "Build a HUD and write tests for it" uses UI + TDD together.

### Future Skills (soft priority)
- **ProBuilder** — sculpt and edit geometry directly from chat
- **Self-improving skills** — agents that reflect on failures, improve their own patterns
- **Multi-agent orchestration** — specialist agents collaborating on a goal

---

## Roadmap

### Track 1 — Housekeeping
*Do once. Unblocks contributors. Runs parallel with Track 2.*

1. Merge `codex/unity-mastery-pack-phase-1` → main
2. Delete merged branches (`claude/gracious-meninsky`)
3. Split `workflow.py` (4.8k lines) → `inspect.py`, `audit.py`, `fix.py`, `benchmark.py`, `improve.py`
4. Split `test_core.py` (5.5k lines) and `test_full_e2e.py` (5.7k lines) by domain
5. Compress `TODO.md`, `README.md`, `AGENTS.md` — trim to fast-comprehension length
6. Update `PLAN.md` to reflect current phase completion and this new vision

**Exit gate:** any contributor can find and understand any workflow in under 2 minutes.

---

### Track 2A — Chat → Action Pipeline
*Immediate. The core product loop.*

The agent can handle all three modes (reactive, watchdog, autonomous) end-to-end:

- Chat input → intent understanding → plan → execute → visual proof (screenshot)
- Every action shows what changed and why
- One clean prototype flow: "add a player that can walk" → GO + CharacterController + movement script + screenshot

**Exit gate:** agent builds a basic player controller from a single chat message with visual before/after proof.

---

### Track 2B — Specialist Skills Grow
*After 2A gate. The product deepens.*

Flip existing expert lenses from audit-only → full lifecycle (build + polish + explain + learn):

- UI skill: build HUD, tighten spacing, add transitions, fix scaling
- Physics skill: deep understanding of feel — tunes drag, mass, collision, not just adds components
- TDD skill: writes tests first, scaffolds coverage, teaches the pattern
- Animation skill: creates controllers, wires states, authors transitions
- Level design skill: audits composition, suggests and applies bounded edits

**Learning system MVP runs parallel here:**
- Run ledger: every skill action logged with outcome
- Structured memory: what worked per project, per domain
- Basic eval/replay: rerun past flows, compare outcomes
- Foundation for self-improving skills later

**Exit gate:** each skill can audit + build + explain in its domain. Learning system captures outcomes.

---

### Track 3 — Polish + Proof
*After Track 2A. Runs alongside 2B.*

- Unity panel UX: clean chat interface (Cowork-style), score deltas, applied/skipped visible, export actions
- Benchmark artifacts and GitHub-ready evidence per major capability
- Contributing guide — open source onboarding for new contributors
- External validation on real Unity projects (not just internal benchmarks)

---

### Future Track
*No timeline. Soft priority.*

- ProBuilder sculpting via chat
- Self-improving skill agents (Voyager-style skill library from experience)
- Ambient watchdog deepened (persistent background project awareness)
- Teams / multi-user / hosted sync (opt-in, redacted, explainable)
- Model-backed multi-step orchestration

---

## Open Source + Monetization

**Default:** MIT, free, open source. Community contribution is the growth path.

**Monetization door stays open** — nothing designed for it yet, nothing closed off. Candidates if the product gets there: polished pro panel, curated workflow packs, hosted learning sync. Decision deferred until the product earns it.

---

## What "Best Move" Means

When choosing between tasks, prefer the one that does the most across:

1. Makes the agent smarter or more capable in a specialist domain
2. Makes results visible and provable to the user
3. Reduces drift between CLI, chat, and Unity panel
4. Improves the learning loop without hiding behavior
5. Unblocks contributors

If a task only hits one of those, it usually loses to something more balanced.

---

## Project Rules (unchanged from PLAN.md)

1. **No hidden capability** — if it is built, it must become user-visible quickly
2. **No assistant-only logic when a workflow can own it** — delegate to reusable workflows
3. **Standalone-first** — keep reducing plugin dependence
4. **Safe by default** — audits broad, fixes bounded and explainable
5. **Evidence over claims** — every major capability benchmarkable and exportable
6. **Magic must stay concrete** — user can always see what the agent understood, did, changed, and recommends next
7. **Learning must be structured** — run ledgers, memory, eval/replay, opt-in sync. Not telemetry.
