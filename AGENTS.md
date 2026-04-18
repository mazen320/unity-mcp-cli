# AGENTS

This repo builds a Unity AI copilot for real Unity game development.

Treat that as the source of truth when making decisions:

- collaborator, not generator
- context-aware before action
- in-editor first
- Undo-safe mutations
- consent before risky or multi-step changes
- verification before claiming success

## Product stance

- The product surface is the Unity `Agent` tab in `Window > CLI Anything`.
- The CLI is the debugging and power-user surface behind it.
- The copilot should help users build their existing game, not invent a new one for them.
- Real projects matter more than fixture scenes. Fixtures exist for smoke tests and regressions.

## Default operating loop

When working on product behavior, use this order:

1. Read real project context first.
2. Diagnose before acting.
3. Offer tradeoffs when there is more than one reasonable path.
4. Get consent before destructive or multi-step work.
5. Apply through Unity editor APIs / bridge routes where possible.
6. Keep mutations Undo-safe.
7. Verify with compile state, logs, captures, or explicit route readback.
8. Report what actually changed.

## Current priorities

Milestone 1 is a reset away from the old CLI-first public story.

That means:

- remove user-facing `workflow *` product chrome
- internalize expert lenses instead of marketing them directly
- keep the suite green while the surface is simplified

After that, the next build order is:

1. context engine
2. skill base and routing
3. consent/Undo UX
4. first cloned specialist skills

Use [../../PLAN.md](../../PLAN.md), [TODO.md](TODO.md), and [TASKS.md](TASKS.md) together. They are the current hierarchy.

## Do not build the wrong product

Do not optimize for:

- tool count
- public score dashboards
- benchmark marketing
- batch cleanup sweeps without consent
- fake “LLM” behavior when no provider is configured

Do optimize for:

- good project context
- high-confidence, bounded edits
- strong verification
- real Unity ergonomics
- trustworthy assistant behavior

## Provider and bridge rules

- Project-local model settings belong in `.umcp/agent-config.json`.
- Project-local secrets belong in `.umcp/agent.env`.
- Process environment still overrides `.umcp/agent.env`.
- Do not build around fake OAuth/session reuse as the main auth path.
- If no provider is configured, the assistant must say so plainly.

## Skills

The intended product architecture is skill-first.

Each skill should follow:

`notice -> diagnose -> propose -> consent -> apply -> verify -> ledger`

Current anchor skill:

- `physics_feel`

When adding or refactoring a skill:

- use [docs/skills/WRITING_A_SKILL.md](docs/skills/WRITING_A_SKILL.md)
- keep it bounded
- keep it Undo-safe
- test the real flow, not only helpers

## Code-change rules

- Scene and inspector changes should use Unity editor APIs first.
- Script changes should be minimal diffs against existing code, not blind rewrites.
- Compile verification matters for any script change.
- If a mutation route lacks Undo coverage, fix that before expanding usage.
- If docs or product direction change, update [README.md](README.md), [TODO.md](TODO.md), [TASKS.md](TASKS.md), [CHANGELOG.md](CHANGELOG.md), and when relevant [../../PLAN.md](../../PLAN.md).

## Validation rules

- A feature is not “working” because a unit test passed.
- Prefer live verification on a real Unity project when the feature is user-facing.
- If visuals matter, capture before/after proof.
- If bridge state matters, verify through a real route readback.
- If the assistant context is weak or stale, treat that as a product bug, not user error.
