# TODO

The full backlog lives in [TASKS.md](TASKS.md). This file is the short current-focus view.

## Current focus

The repo is in **Milestone 1: Reset**.

The job right now is to remove drift from the old CLI-first product story and align the codebase to the new Unity-copilot direction:

- collaborator, not generator
- in-editor first
- consent and Undo
- specialist skills
- CLI as a debugging and power-user layer, not the product

## Just completed

- **E1-T4** Replace `PLAN.md` with the new vision
- **E1-T5** Rewrite `README.md` around the Agent tab and Unity-copilot framing
- **E1-T6** Rewrite this file into the short current-focus view
- **E1-T7** Rewrite `AGENTS.md` around consent, Undo, and chat
- **E1-T2** Delete the public CLI developer-profile layer
- **E1-T3** Delete the Agent-tab improve-project report card
- **TASKS sync** Import the CSV backlog into tracked `TASKS.md`

## Active now

- **E1-T1** Delete CLI `workflow *` user-facing commands
- **E1-T8** Internalize expert lenses instead of emitting them as the public product surface
- **E11-T1** Cut failing tests per deletion commit
- **E11-T10** Documentation accuracy sweep after the reset

## Next up after M1

Priority order:

1. **E2-T1** Index schema design
2. **E3-T1** Skill base class and shared plumbing
3. **E8-T2** Per-change consent prompt pattern
4. **E2-T2 / E2-T3 / E2-T4 / E2-T8 / E2-T15** Core context indexers and query API
5. **E3-T3** `collision_setup` as the first clone of `physics_feel`
6. **E3-T4** `event_wiring`
7. **E5-T1** Diff-first code change protocol
8. **E8-T3** Visible Undo affordance

## What we are not doing right now

- Public score / grade / benchmark marketing
- `improve-project` as the headline product loop
- CLI developer profiles as part of the public story
- Tool coverage percentages as the main credibility metric
- New generation features before the context engine exists

Supporting infrastructure can remain in the repo while the product surface is reset. The reset is about what the product is for, not pretending the old code never existed.

## Doc hierarchy

- [../../PLAN.md](../../PLAN.md) — vision and principles
- [README.md](README.md) — what the product is
- [TODO.md](TODO.md) — this file, short current-focus view
- [TASKS.md](TASKS.md) — full backlog
- [AGENTS.md](AGENTS.md) — operating rules for AI agents in this repo
- [docs/skills/WRITING_A_SKILL.md](docs/skills/WRITING_A_SKILL.md) — skill implementation template

## Rule

Every code change updates [CHANGELOG.md](CHANGELOG.md).

Every completed task updates either:

- [TODO.md](TODO.md) if it changes current priorities, or
- [TASKS.md](TASKS.md) if it changes tracked task state.
