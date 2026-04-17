# Plan — Animation Locomotion Specialist Skill

**Date:** 2026-04-18
**Status:** Draft — ready for execution
**Why this plan exists:** live Unity verification for the physics-feel anchor is blocked until a real editor session is reopened. This plan picks the next specialist-skill template so implementation does not drift.

## Why animation is next

Choose `animation` before `ui`.

Reason:
- the repo already has real standalone routes for controller creation and graph editing
- the current animation lens already audits clips, controllers, and live `Animator` presence
- the current animation fixes already scaffold and wire controllers
- the skill can prove results through controller-info and bounded state-machine changes even before a polished live visual loop

UI is still a good future skill, but the current UI surface is mostly hygiene repair. Animation has a better path to a real specialist behavior now.

## Existing capability base

Already in the repo:
- `core/expert_rules/animation.py`
- `core/expert_fixes.py`
- `workflow quality-fix --lens animation --fix controller-scaffold --apply`
- `workflow quality-fix --lens animation --fix controller-wireup --apply`

Standalone File IPC already supports:
- `animation/create-controller`
- `animation/assign-controller`
- `animation/create-clip`
- `animation/clip-info`
- `animation/controller-info`
- `animation/add-parameter`
- `animation/add-state`
- `animation/add-transition`
- `animation/set-default-state`
- `graphics/game-capture`

That is enough to build a bounded locomotion/setup skill without inventing a fresh bridge layer.

## Goal

Ship a second specialist skill that proves the pattern transfers:

> User types "my animations aren't hooked up" or "wire up my animator" in the Unity Agent chat -> diagnosis + three bounded controller paths with tradeoffs -> apply one path -> controller asset + graph + assignment + proof + ledger entry.

## Anchor experience

Expected flow:

1. User asks for animation help in plain language.
2. Agent audits:
   - whether clips exist
   - whether controllers exist
   - whether a live `Animator` exists
   - whether the scene has a controller already assigned
3. Agent proposes three bounded paths:
   - **Preview path**: one generated controller, one default state, fastest proof, lowest coverage
   - **Locomotion starter**: `Speed` parameter + `Idle` / `Walk` states + transitions, better gameplay base
   - **Clip sandbox**: generated controller with detected clips as preview states, best for exploration, less game-ready
4. User replies `apply 1/2/3`.
5. Agent applies the chosen path through the standalone routes.
6. Agent returns:
   - what was created
   - what object was wired
   - controller path
   - before/after controller summary
   - capture path when available
7. Outcome is logged to the local ledger.

## Proposed module

Create:
- `cli_anything/unity_mcp/core/skills/animation_locomotion.py`

Expected public functions:

```python
def audit_animation_locomotion(context: ProjectContext) -> AuditResult: ...
def propose_animation_locomotion(audit: AuditResult, request: str) -> list[ProposedAction]: ...
def apply_animation_locomotion(action: ProposedAction, bridge) -> ActionOutcome: ...
```

The skill should reuse the shared skill contract and registry from:
- `core/skills/base.py`
- `core/skills/__init__.py`

## Task breakdown

### Task 1 — Audit module

Create the skill module and implement audit.

Audit should answer:
- are clips present
- is a controller present
- is a live `Animator` present
- is a controller already assigned
- which object is the best target
- which clip names are available

Minimum summary data:
- `animatorPath`
- `controllerPath`
- `clipNames`
- `controllerPresent`
- `animatorPresent`
- `contextAvailable`

### Task 2 — Proposal paths

Add three bounded proposals.

Recommended proposal ids:
- `animation_locomotion/preview`
- `animation_locomotion/locomotion`
- `animation_locomotion/sandbox`

Recommended tradeoffs:
- `preview`: fastest proof, minimal graph, not yet gameplay-ready
- `locomotion`: strongest starting point for actual gameplay, assumes clip names can be mapped sanely
- `sandbox`: safest for exploring clips, but more manual cleanup later

Each proposal preview should carry:
- target animator path
- controller path
- parameter names
- state names
- default state
- clip mapping

### Task 3 — Apply path

Apply should use existing standalone routes only unless a small honest gap appears.

Expected route usage:
- `animation/create-controller`
- `animation/add-parameter`
- `animation/add-state`
- `animation/set-default-state`
- `animation/add-transition`
- `animation/assign-controller`
- `animation/controller-info`
- `graphics/game-capture` when live capture is available

The apply path must return:
- `before`
- `after`
- `captures`
- `error`

Do not fake clip assignment or blend trees if the route surface does not support them cleanly yet.

### Task 4 — Chat routing

Extend `core/agent_chat.py`.

Add intent routing for phrases like:
- `my animations aren't hooked up`
- `wire up my animator`
- `set up animation controller`
- `hook up these clips`

Chat flow should mirror physics-feel:
- audit
- propose three numbered paths
- stash pending proposals
- handle `apply 1/2/3`

### Task 5 — Ledger + proof

Use `core/learning/ledger.py`.

Minimum ledger entry:
- `skill`
- `request`
- `chosen_action`
- `before`
- `after`
- `controllerPath`
- `targetGameObjectPath`
- `captures`
- `error`

Proof priority:
1. controller-info before/after
2. Game-view capture if live
3. markdown/plain-text summary

### Task 6 — Docs + tests

Add:
- `tests/test_animation_locomotion.py`
- `test_chat_e2e.py` coverage for the new route

Update:
- `README.md`
- `TODO.md`
- `CHANGELOG.md`

If a new committed test module is added, CI must run it.

## Test plan

Required automated coverage:
- audit with no context
- audit with clips but no controller
- audit with controller but no animator
- propose returns three stable paths
- apply preview path creates and wires controller graph through the mock bridge
- chat route: request -> proposals -> apply follow-up
- ledger entry written on apply

Optional live checks after Unity is reopened:
- run the chat flow against a real project
- confirm controller asset exists
- confirm target `Animator` now points at the generated controller
- confirm capture file exists when a camera is available

## Exit criteria

This skill slice is done when:
- animation specialist skill exists under `core/skills/`
- the Agent chat can route into it
- one bounded controller path applies end to end
- ledger writes happen on apply
- docs reflect the new specialist path
- automated tests are green

## Risks

- clip naming in real projects may be inconsistent
- clip-to-state mapping may need heuristics that are too broad for the first pass
- blend-tree support is not the right first target if route coverage is unclear

Mitigation:
- keep the first version state-machine based
- avoid blend trees in v1
- prefer honest limited behavior over fake “smart” animation wiring

## Recommended execution order

1. audit module
2. proposal paths
3. apply preview path
4. chat route
5. ledger + proof
6. docs + CI

## Recommendation

When live Unity is available again:
- finish the delayed physics-feel live verification first
- then execute this animation plan

If live Unity is still unavailable but work must continue:
- implement Tasks 1-3 from this plan first
- defer live proof validation until the editor is reopened
