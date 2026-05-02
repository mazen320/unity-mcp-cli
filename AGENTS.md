# AGENTS

Operating rules for AI agents working in this repository.

This project is a Unity-native AI copilot. The product goal is not "hardcode workflows in Python"; the goal is to let an LLM understand a Unity project, choose valid Unity actions, execute through editor APIs, and verify the result.

Read [PLAN.md](PLAN.md) before major changes.

## Product Direction

Build toward:

- AI-driven Unity control.
- Conversation first, plans only for clear edit/build requests.
- Real project context before action.
- In-editor execution through File IPC and Unity editor APIs.
- Approval before multi-step changes.
- Honest verification after execution.
- Local-first memory and logs.

Avoid:

- Task-specific Python recipes that bypass the LLM.
- Fake success messages.
- Batch "fix everything" behavior without consent.
- Public score/grade/benchmark framing.
- CLI-first product design.
- Blind code writes that skip Unity compile verification.

## Correct Agent Loop

For Unity-facing work:

1. Read live state first: editor state, active scene, hierarchy, selected/likely target objects, scripts, compile state, and recent chat.
2. If the user is asking a question, answer conversationally.
3. If the user asks for a concrete edit/build, propose an executable plan and wait for approval.
4. If the user revises a pending plan, replace the pending plan. Do not apply stale steps.
5. Execute through File IPC routes.
6. Wait for Unity compilation after script creation or updates before attaching components.
7. Verify with route readback, console/compile state, and screenshots for visual changes.
8. Report exactly what Unity confirmed and exactly what failed.

## LLM vs Backend Ownership

The LLM owns:

- interpreting intent
- designing a project feature or edit
- choosing Unity actions from available routes
- explaining tradeoffs
- revising plans from feedback

The backend owns:

- project context
- route schemas
- plan validation
- pending-plan state
- approval gate
- execution
- compile waits
- verification
- error reporting

Do not move domain decisions into Python conditionals. Python can reject invalid plans, but it should not contain task-specific implementation instructions.

## Consent Rules

- Multi-step work requires approval.
- Destructive work requires explicit approval.
- "Yes", "go", "do it", and similar replies apply the current pending plan only.
- "Do it in a new scene", "use another object", "before changing", and similar follow-ups revise or explain the pending plan instead of applying it.
- If the pending plan no longer matches user intent, keep it paused and ask for revision.

## Unity Execution Rules

Prefer File IPC. It writes commands under `.umcp/inbox/`, reads responses from `.umcp/outbox/`, and uses `.umcp/ping.json` for heartbeat.

For script work:

1. Create or update the script.
2. Poll `editor/state` until Unity is done compiling/domain reload.
3. Check console or compilation errors when available.
4. Attach the component only after compile settles.

For scene work:

- Use `scene/new` when the user asks for a new or separate scene.
- Use `scene/save` only after Unity has confirmed the scene exists and object/script steps succeeded.
- Do not claim a scene was created just because the plan text said so.

For visual work:

- Capture Game View or Scene View when practical.
- If capture fails, say so.

## Undo Rules

Unity-side mutation routes should be Undo-safe. Use:

- `Undo.RecordObject`
- `Undo.RegisterCreatedObjectUndo`
- `Undo.AddComponent`
- `Undo.DestroyObjectImmediate`
- `Undo.CollapseUndoOperations`

If a route mutates state without Undo coverage, either fix the route or clearly mark the limitation.

## Debug Commands

Use JSON output when another tool or agent will read the result:

```powershell
cli-anything-unity-mcp --transport file --file-ipc-path <project> --json debug doctor
cli-anything-unity-mcp --transport file --file-ipc-path <project> --json debug trace --tail 20
cli-anything-unity-mcp --transport file --file-ipc-path <project> --json agent sessions
cli-anything-unity-mcp --transport file --file-ipc-path <project> --json scene-info
cli-anything-unity-mcp --transport file --file-ipc-path <project> --json console --type error --count 20
```

## Code Change Rules

- Keep changes bounded.
- Add tests for routing, planning, execution, or route behavior changes.
- Update docs when product behavior changes.
- Do not revert unrelated user or agent changes.
- Do not add dependencies unless clearly justified.
- Keep open-source docs honest about what works now vs roadmap.

## Documentation Rule

If user-facing behavior changes, update:

- [README.md](README.md)
- [PLAN.md](PLAN.md) if direction changes
- [TODO.md](TODO.md) if priority changes
- [CHANGELOG.md](CHANGELOG.md)

## Current Priority

Open-source readiness and trust:

1. Public docs must match actual behavior.
2. Worktree must be clean except intentional changes.
3. Tests must pass.
4. Assistant must stop claiming success without Unity confirmation.
5. Next engineering focus is verification, target resolution, and generated-code repair/rollback.
