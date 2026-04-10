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
2. Inspect the current state — this also caches project structure into memory automatically.
3. Check memory for what the CLI already knows about this project.
4. Debug before guessing.
5. Make the smallest useful change.
6. Verify with logs, trace, and captures.
7. Run `debug doctor` again after a fix — if the issue is gone, the CLI auto-learns the fix.

Use these commands first:

```powershell
cli-anything-unity-mcp instances
cli-anything-unity-mcp select <port>
cli-anything-unity-mcp --json workflow inspect --port <port>
cli-anything-unity-mcp --json memory recall
cli-anything-unity-mcp --json memory stats
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

## Project Memory System

The CLI has a persistent memory store that learns about each Unity project over time. Memory is keyed per project (by project path) and survives across sessions.

### How it gets populated automatically

- **`workflow inspect`** — caches render pipeline, Unity version, project name, installed packages, script directories, and last active scene every time it runs. No extra flags needed.
- **`debug doctor` fix loops** — when an issue disappears between two doctor runs, the CLI credits the intervening commands and saves them as fixes automatically. The next doctor run that sees the same issue will show `pastFix.fixCommand`.

### When to use memory explicitly

Check memory early in a session, especially for a project you've worked on before:

```powershell
cli-anything-unity-mcp --json memory stats
cli-anything-unity-mcp --json memory recall
cli-anything-unity-mcp --json memory recall --category fix
cli-anything-unity-mcp --json memory recall --category structure
cli-anything-unity-mcp --json memory recall --search "CS0246"
```

Save a fix manually when you know what worked:

```powershell
cli-anything-unity-mcp memory remember-fix "CS0246" "cli-anything-unity-mcp script-update Assets/Foo.cs" --context "was a missing asmdef"
cli-anything-unity-mcp memory remember structure render_pipeline URP
cli-anything-unity-mcp memory remember pattern addressables "Project uses Addressables not Resources.Load"
```

### What `debug doctor` does with memory

When memory exists for the active project, `debug doctor`:

1. **Annotates findings** with `pastFix` — if a finding matches a known error pattern, the report includes the command that fixed it before.
2. **Detects structure drift** — compares current snapshot against cached structure and flags changes: pipeline switch, Unity version change, missing packages referenced in code.
3. **Auto-learns fixes** — after each run, saves the current finding set. If a problem disappears on the next run, credits the intervening CLI commands as fixes.

### Memory categories

| Category | What it stores | Example key |
|----------|---------------|-------------|
| `fix` | error pattern → fix command | `"Compilation Issues"` |
| `structure` | project layout facts | `"render_pipeline"`, `"packages"`, `"unity_version"` |
| `pattern` | recurring project behaviour | `"addressables"`, `"custom_shader_workflow"` |
| `preference` | agent/user preferences for this project | `"preferred_scene_depth"` |

### What NOT to store in memory

- Transient runtime state (console messages, play mode status) — these change constantly
- Full snapshots or hierarchy dumps — too large and go stale immediately
- Things already visible in git or the project files

## What Not To Do

- Do not present temporary probes or validation helpers as the main value of the project.
- Do not skip logs and screenshots when debugging Unity visuals.
- Do not jump straight to low-level route calls if a workflow or debug command already covers the job.
- Do not push mixed CLI work and experimental fixture work together unless the user explicitly wants that.
- Do not skip `memory recall` at the start of a session on a known project — past fixes and structure facts save bridge round-trips.
- Do not manually save things to memory that `workflow inspect` already caches automatically (render pipeline, Unity version, packages).
- Do not trust cached structure as ground truth without verifying against the current bridge state when something looks wrong.
