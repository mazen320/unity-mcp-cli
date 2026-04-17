# Writing A Specialist Skill

This repo treats a specialist skill as a product surface, not a loose prompt wrapper.

Use the physics-feel path as the anchor template:
- [BUILD_PHYSICS_FEEL_SKILL.md](./BUILD_PHYSICS_FEEL_SKILL.md)
- [2026-04-17-phase4-specialist-skills.md](../superpowers/specs/2026-04-17-phase4-specialist-skills.md)
- [2026-04-17-physics-feel-anchor-demo.md](../superpowers/plans/2026-04-17-physics-feel-anchor-demo.md)

## What A Skill Must Do

Every real skill should be able to:
- audit the current state
- propose a few bounded actions with tradeoffs
- apply one bounded action honestly through the bridge
- explain what changed in plain English
- capture proof
- log the outcome for later replay and learning

If a candidate feature cannot do most of that yet, keep it as an expert lens or workflow fix. Do not call it a full skill.

## Standard Files

At minimum, expect to touch:
- `cli_anything/unity_mcp/core/skills/base.py`
- `cli_anything/unity_mcp/core/skills/__init__.py`
- `cli_anything/unity_mcp/core/skills/<skill_name>.py`
- `cli_anything/unity_mcp/core/agent_chat.py`
- `cli_anything/unity_mcp/tests/test_<skill_name>.py`
- `cli_anything/unity_mcp/tests/test_chat_e2e.py`
- `README.md`
- `TODO.md`
- `CHANGELOG.md`

Touch these only if the skill needs them:
- `cli_anything/unity_mcp/core/learning/ledger.py`
- `unity-scripts/Editor/StandaloneRouteHandler.cs`
- `C:\Users\mazen\OneDrive\Desktop\New Unity MCP Replacement\CLI\PLAN.md`

## Commit Shape

Keep the work in small green commits. The physics-feel anchor used this sequence:

1. skill interface scaffolding
2. audit module
3. proposal paths
4. apply + capture
5. chat routing
6. learning ledger
7. docs patch

That sequence is recommended because each stage leaves the repo shippable and testable.

## Build Pattern

### 1. Start From The Skill Contract

Use the shared dataclasses and registry in:
- `cli_anything/unity_mcp/core/skills/base.py`
- `cli_anything/unity_mcp/core/skills/__init__.py`

Your module should expose a small public surface like:

```python
from cli_anything.unity_mcp.core.skills import (
    ActionOutcome,
    AuditResult,
    ProjectContext,
    ProposedAction,
)


def audit_<skill_name>(context: ProjectContext) -> AuditResult:
    ...


def propose_<skill_name>(audit: AuditResult, request: str) -> list[ProposedAction]:
    ...


def apply_<skill_name>(action: ProposedAction, bridge) -> ActionOutcome:
    ...
```

Keep the functions importable and testable without Unity running.

### 2. Audit First

Do not start with chat wiring or bridge mutation.

Audit should:
- work from `ProjectContext`
- produce a meaningful score and findings
- degrade honestly when live context is missing
- record enough summary data for the proposal step

Good audit output answers:
- what is wrong
- how confident we are
- what object or asset is likely affected
- which values or missing pieces drive the result

### 3. Proposals Must Encode Taste

Do not return one generic fix.

Return 2-3 bounded proposals with:
- stable `action_id`
- a title the user can recognize
- a `tradeoff` string in plain English
- a `preview` payload that is rich enough for `apply`

This is where the skill becomes more than API wrapping. Physics-feel worked because the proposals were distinct, taste-aware, and understandable.

### 4. Apply Must Be Honest

Never claim success unless the bridge actually wrote something.

Rules:
- prefer existing public routes first
- if a route gap is real, add the smallest honest route instead of faking the result
- keep the mutation bounded and reversible where possible
- return concrete `before` and `after` payloads
- capture proof before and after

If part of a proposal cannot be applied yet, record that in `notes` or `error`. Do not silently pretend the whole proposal landed.

### 5. Chat Is A Thin Router

`cli_anything/unity_mcp/core/agent_chat.py` should:
- detect the skill intent
- call `audit` + `propose`
- stash pending proposals
- resolve a follow-up like `apply 1`
- call `apply`
- format the outcome

Do not bury the skill logic inside chat formatting. The skill module should stay reusable from CLI, chat, and future MCP surfaces.

### 6. Log Outcomes

If the skill can mutate state, it should usually log outcomes via:
- `cli_anything/unity_mcp/core/learning/ledger.py`

Minimum useful entry:
- `skill`
- `request`
- `chosen_action`
- `before`
- `after`
- `captures`
- `error`

This is the seed for replay, evals, and project-aware memory later.

## Tests You Should Add

Required:
- skill-unit tests in `test_<skill_name>.py`
- chat-routing tests in `test_chat_e2e.py`

Usually needed:
- bridge or file-IPC tests if you add a new route
- ledger tests if you add new logging behavior

Cover these cases:
- no context
- normal success path
- missing required object/component
- apply without pending proposal
- partial apply or bridge failure

## CI Expectation

If you add a committed test module, make sure `.github/workflows/ci.yml` runs it.

Do not leave new tests outside the default green path. Physics-feel initially had that gap, and it had to be fixed after the feature landed.

## Live Verification Checklist

Before calling the skill real:
- run the committed automated test surface
- open a real Unity project
- trigger the skill end to end from the Agent tab
- verify proof artifacts are written
- verify ledger entries are written
- verify the bridge path actually changed the Unity state

If the skill depends on a new standalone route, verify that route live in Unity, not only through Python mocks.

## Common Failure Modes

- putting taste logic in chat instead of the skill module
- using a giant preview payload with no stable ids
- claiming an apply succeeded when only part of it landed
- skipping capture because the mutation was "small"
- forgetting to update CI for new tests
- updating README but not TODO or CHANGELOG
- building a skill that is really just an audit with nicer text

## Good Candidates For The Next Skill

The next strong templates are:
- `animation` if you want impact/readability/polish and controller-state work
- `ui` if you want visible before/after and quick in-editor demos

Pick one. Do not start both at once.

## Definition Of Done

A specialist skill is ready when:
- it has audit, proposal, and apply paths
- chat can route into it cleanly
- it captures proof
- it writes a ledger entry for applies
- docs mention the capability
- CI covers the committed test modules
- a live Unity run confirms the behavior end to end
