# Product Plan

## Vision

CLI Anything Unity MCP is a Unity-native AI copilot for real game development.

The assistant should behave like a capable Unity teammate:

- It can talk normally.
- It can inspect the project before acting.
- It can help create or modify project features when asked.
- It can edit the Unity scene through editor APIs.
- It can verify what changed.
- It should not pretend success when Unity did not actually do the work.

The important distinction: we do not hardcode task-specific recipes in Python. The LLM decides the implementation from context. The backend provides Unity context, valid routes, safety checks, execution, and verification.

## Product Principles

### 1. AI-driven, not recipe-driven

The assistant should not need a Python branch for each kind of Unity task. It should receive context, know the available Unity tools, and produce executable Unity actions.

Python should own:

- context gathering
- route schemas
- plan validation
- approval state
- execution
- verification
- error recovery

The LLM should own:

- interpreting user intent
- deciding the feature design
- choosing which Unity actions to use
- explaining tradeoffs
- revising plans from user feedback

### 2. Context before action

Before significant work, the assistant should read the relevant live state:

- active scene
- hierarchy
- selected or likely target objects
- scripts and components
- compile state
- project settings
- available packages
- recent chat and pending plans

Weak context is a product bug, not a user problem.

### 3. Conversation first

Questions should be answered as conversation. Commands should become plans. The assistant should not turn every message into "I found a plan".

Examples:

- "Can you help set this up?" -> chat about approach.
- "Set this up in a new scene." -> propose executable plan.
- "Show me what you are targeting first." -> explain pending plan, do not execute.
- "Do it in a new scene." -> revise the pending plan, do not apply stale steps.

### 4. Consent before changes

For multi-step or risky work, the assistant proposes first and waits for approval. It should not silently mutate the project.

### 5. Execute through Unity

Scene and inspector changes should go through Unity editor APIs and File IPC routes. Generated scripts are allowed, but they must be created intentionally, compiled, and verified.

### 6. Verify honestly

After action, verify through route results, readback, compile state, console errors, and screenshots where relevant.

The assistant must not say "created" or "saved" unless Unity confirmed the route. If a route returned an error, say exactly what failed and what should happen next.

### 7. Undo-safe by default

Unity-side mutations should use Unity Undo APIs where possible:

- `Undo.RecordObject`
- `Undo.RegisterCreatedObjectUndo`
- `Undo.AddComponent`
- `Undo.DestroyObjectImmediate`
- `Undo.CollapseUndoOperations`

Routes that mutate without Undo coverage are lower trust and should be fixed.

## Current Architecture

```text
Unity EditorWindow
        |
        v
.umcp chat inbox/history/status files
        |
        v
Python ChatBridge
        |
        v
LLM chat/planner + validation
        |
        v
AgentLoop executor
        |
        v
FileIPCClient
        |
        v
Unity FileIPCBridge + StandaloneRouteHandler
```

The CLI exists because it is useful for debugging, automation, and contributors. The product surface is the in-editor copilot.

## What Is Working Now

- Unity EditorWindow chat surface.
- File IPC transport.
- Model-backed chat and planning.
- Approval-required model plans.
- Pending-plan revision for follow-up instructions.
- New-scene route support in model plans.
- Script compile wait before attaching generated MonoBehaviours.
- Live project/game review mode.
- Local project model config through `.umcp/agent-config.json`.
- Project-local provider secrets through `.umcp/agent.env`.
- CI for Python tests.
- Open-source basics: MIT license, contribution docs, issue templates, PR template, security policy.

## Known Gaps Before This Feels Great

- Target resolution needs to inspect names, components, scripts, tags, and scene structure more intelligently.
- Generated code needs diff-first review, compile repair, and rollback.
- Post-action verification needs to be stricter and more visible in the UI.
- Screenshot capture should be part of visual workflows by default.
- Route coverage and Undo coverage need a formal audit.
- Docs and UX should avoid over-promising features that are still roadmap.

## Roadmap

### Milestone 1: Open-source reset

Goal: make the repo honest, installable, testable, and contribution-friendly.

- Align README, PLAN, TODO, AGENTS, and contribution docs.
- Keep public claims limited to what works today.
- Record real demo media from the in-editor chat flow before adding visuals to the README.
- Make local junk ignored.
- Run the full test suite.
- Push a clean branch.

### Milestone 2: Trust loop

Goal: stop "it said it did it but did not".

- Route result summaries that name exact Unity confirmations.
- Compile/console verification after script work.
- Scene readback after object/material/scene changes.
- Screenshot capture after visual changes.
- Failure messages with next action.

### Milestone 3: Context engine

Goal: make the assistant actually understand projects.

- Script index.
- Asset/meta index.
- Scene and prefab graph.
- Project settings and package index.
- Query API for target resolution.
- Live refresh.

### Milestone 4: Safer generation

Goal: let the LLM build real features without hardcoded recipes.

- Diff-first script changes.
- Generated-code convention detection.
- Multi-file atomic edits.
- Compile repair loop.
- Rollback on failure.

### Milestone 5: Better Unity UX

Goal: make the in-editor assistant feel like a product.

- Plan cards instead of plain text.
- Progress cards.
- Evidence cards.
- Inline proof cards with real captures or short GIFs from actual agent runs.
- Visible Undo affordance.
- Model/provider setup that is obvious on first run.

## Decision Rule

When choosing between implementation paths, prefer the one that improves:

1. Real Unity context.
2. Honest execution.
3. Verification.
4. User control.
5. General LLM capability.

Reject the path if it mainly adds hardcoded intent branches, fake success messages, or a larger public surface without better reliability.
