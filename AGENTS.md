# AGENTS

This repo is a CLI-first Unity assistant.

If you are a coding agent working in this repository, treat the CLI layer as the product.

## Product Focus

- Prioritize the Unity CLI, debugging surface, tool coverage, and bridge reliability.
- Do not add or push sample or fixture work unless the user explicitly asks for it.
- Use temporary probes, captures, and debug commands to validate changes instead of building demo content.

## Default Unity Workflow

When helping a user with a Unity task, prefer this order:

1. Discover and target the right Unity editor.
2. Inspect the current state.
3. Debug before guessing.
4. Make the smallest useful change.
5. Verify with logs, trace, and captures.

Use these commands first:

```powershell
cli-anything-unity-mcp instances
cli-anything-unity-mcp select <port>
cli-anything-unity-mcp --json workflow inspect --port <port>
cli-anything-unity-mcp --json debug doctor --port <port>
cli-anything-unity-mcp --json debug trace --tail 20
cli-anything-unity-mcp --json debug snapshot --console-count 100 --include-hierarchy --port <port>
cli-anything-unity-mcp --json debug editor-log --tail 120 --ab-umcp-only
cli-anything-unity-mcp --json debug capture --kind both --port <port>
```

## Command Selection Rules

- Prefer `--json` for anything another agent or tool will read.
- Prefer `--port <port>` when the target editor is known.
- Prefer `workflow` commands before dropping to `tool` or `route`.
- Use `tool-info`, `tools`, and `tool-coverage` to discover capability instead of guessing command shapes.
- Use `agent save`, `agent use`, and `--agent-id` when you want stable trace/debug attribution.

## Required Debugging Behavior

If the user says something is broken, bugged, missing, invisible, not working, or confusing:

1. Run `debug doctor`.
2. Run `debug trace`.
3. Check `debug editor-log`.
4. If visuals matter, run `debug capture --kind both`.
5. Only then propose or apply a fix.

Useful commands:

```powershell
cli-anything-unity-mcp --json debug doctor --recent-commands 8 --port <port>
cli-anything-unity-mcp --json debug trace --tail 20
cli-anything-unity-mcp --json debug trace --tail 20 --agent-id <agent-id>
cli-anything-unity-mcp --json debug editor-log --tail 120 --ab-umcp-only
cli-anything-unity-mcp debug editor-log --tail 40 --contains "CLI-TRACE" --follow
cli-anything-unity-mcp --json debug capture --kind both --port <port>
```

## Automatic Trace Expectations

Normal CLI commands now emit visible Unity-side `[CLI-TRACE]` breadcrumbs.

Expect to see lines like:

- `locke-debug: Inspecting scene info`
- `locke-debug: Finished inspecting scene info`
- `locke-debug: Checking project info`
- `locke-debug: Checking editor state`

Use a stable agent id if you want cleaner logs:

```powershell
cli-anything-unity-mcp --json agent save locke --agent-id locke-debug --select
cli-anything-unity-mcp --json scene-info --port <port>
cli-anything-unity-mcp --json debug trace --tail 20 --agent-id locke-debug
cli-anything-unity-mcp debug editor-log --contains "CLI-TRACE" --follow
```

## Visual Verification Rules

- For scene, lighting, camera, UI, renderer, material, or gameplay presentation changes, capture both Game View and Scene View.
- Do not assume a fix is good without looking at the captures.
- If a camera is wrong, inspect renderer/clear flags and not just transform values.

## Repo Boundaries

- The CLI is the main public product.
- The Unity plugin is still the runtime backend today.
- Keep attribution honest.
- Improve the CLI/debugging/tooling surface first.

## What Not To Do

- Do not present temporary probes or validation helpers as the main value of the project.
- Do not skip logs and screenshots when debugging Unity visuals.
- Do not jump straight to low-level route calls if a workflow or debug command already covers the job.
- Do not push mixed CLI work and experimental fixture work together unless the user explicitly wants that.
