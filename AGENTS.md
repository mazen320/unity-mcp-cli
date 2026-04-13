# AGENTS

This repo is a CLI-first Unity assistant.

If you are a coding agent working in this repository, treat the CLI layer as the product.

## Product Focus

- Prioritize the Unity CLI, debugging surface, tool coverage, and bridge reliability.
- Do not add or push sample or fixture work unless the user explicitly asks for it.
- Use temporary probes, captures, and debug commands to validate changes instead of building demo content.
- For the Bezi-like assistant, agent loop, chat UI, and File IPC work, treat [PLAN.md](C:/Users/mazen/OneDrive/Desktop/New%20Unity%20MCP%20Replacement/CLI/PLAN.md) as the source of truth.
- Keep implementation aligned to the phase order in `PLAN.md` unless the user explicitly asks to override it.
- When a protocol detail changes in code, update `PLAN.md` in the same pass so future agents do not drift.
- For Agent-tab chat work, do not assume a correctly prepared external shell. The Unity panel should own bridge startup or surface an explicit in-editor connect flow.

## Default Unity Workflow

When helping a user with a Unity task, prefer this order:

1. Discover and target the right Unity editor.
2. Inspect the current state — this also caches project structure into memory automatically.
   `workflow inspect` now also reads nearby asset `.meta` files, so use it before guessing about material import, normal maps, sprite imports, or early rig/setup gaps.
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
cli-anything-unity-mcp --json workflow asset-audit --port <port>
cli-anything-unity-mcp --json workflow bootstrap-guidance --port <port>
cli-anything-unity-mcp --json workflow create-sandbox-scene --port <port>
cli-anything-unity-mcp --json workflow expert-audit --lens director --port <port>
cli-anything-unity-mcp --json workflow expert-audit --lens systems --port <port>
cli-anything-unity-mcp --json workflow scene-critique --port <port>
cli-anything-unity-mcp --json workflow quality-score --port <port>
cli-anything-unity-mcp --json workflow benchmark-report --port <port>
cli-anything-unity-mcp --json workflow quality-fix --lens director --fix guidance --port <port>
cli-anything-unity-mcp --json workflow quality-fix --lens director --fix guidance --apply C:/Projects/MyUnityProject
cli-anything-unity-mcp --json workflow quality-fix --lens director --fix test-scaffold --apply C:/Projects/MyUnityProject
cli-anything-unity-mcp --json workflow quality-fix --lens director --fix sandbox-scene --apply --port <port>
cli-anything-unity-mcp --json workflow quality-fix --lens systems --fix event-system --apply --port <port>
cli-anything-unity-mcp --json workflow quality-fix --lens animation --fix controller-scaffold --apply --port <port>
cli-anything-unity-mcp --json workflow quality-fix --lens animation --fix controller-wireup --apply --port <port>
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
- Use `developer current`, `developer list`, `developer use`, and `--developer-profile` when you want the CLI itself to stay in a more action-first, review-first, or token-saving mode for the current project.
- On File IPC, use `agent queue`, `agent sessions`, `agent log <agent-id>`, and `agent watch --iterations 1` for agent visibility. The bridge records agent activity only when commands arrive, so do not add Unity-side polling loops for this.
- On standalone File IPC, prefer `search/by-component` plus `selection/get`, `selection/set`, and `selection/focus-scene-view` when you need a fast no-plugin way to find a live object, select it, and jump the Scene view before making edits.
- Use `workflow asset-audit` when the user is asking about asset quality, importer setup, materials, textures, animation-readiness, or likely project clean-up work. It can audit by selected Unity editor or a direct project path.
- Use `workflow bootstrap-guidance` when the project needs a starter `AGENTS.md` or `Assets/MCP/Context/ProjectSummary.md` generated from the current audit findings. It previews by default and can write the files with `--write`.
- Use `workflow create-sandbox-scene` when the audit flags a missing sandbox scene or when you want a safe disposable scene before doing bigger gameplay or tooling passes. By default it restores the original scene after creation; pass `--open` if you want to land in the sandbox immediately.
- Use `workflow expert-audit --lens <director|systems|animation|tech-art|ui|level-art>` when the user wants content-direction review, Unity systems/runtime hygiene feedback, animation/rig hints, tech-art checks, HUD critique, or level readability feedback from a single specialist lens.
- Prefer `workflow expert-audit --lens systems` when the user wants a broad Unity-developer read instead of genre-specific advice. That lens is for scene architecture, playability hooks, runtime hygiene, prefab coverage, and benchmark cleanliness.
- Remember that `ui` and `level-art` need live scene data. If you only have a direct project path and no selected editor, expect those lenses to report missing live context instead of returning a confident scene score.
- The `animation` lens can use live hierarchy data when it is available, so prefer running it against a selected editor when you want scene-side Animator wiring feedback and not just asset-pipeline feedback.
- Use `workflow scene-critique` when you want the fast combined read from the scene-facing expert lenses without manually chaining them.
- Use `workflow quality-score` when the user wants a broad “how healthy is this project?” checkpoint across all expert lenses.
- Use `workflow benchmark-report` when the user wants a stable scorecard or evidence artifact for GitHub, release notes, or regression tracking. Prefer writing the report to a file instead of copy-pasting huge CLI output blobs. The saved JSON now also carries `queueDiagnostics` for recurring queue pressure and `queueTrend` for longer-horizon queue history.
- The Unity Agent tab now has a real offline assistant layer. For quick in-editor support, it can already handle project inspection, quality scoring, benchmarks, guidance scaffolding, test scaffolding, sandbox scenes, compilation checks, basic primitive creation, and a small set of bounded live-scene hygiene fixes without external API keys.
- The bounded live-scene cleanup set currently includes: repairing a missing `EventSystem`, adding missing `CanvasScaler` components, removing duplicate `AudioListener` components, and deleting obvious disposable probe/demo objects during `improve project`. Keep new assistant-side scene edits in that same low-risk category.
- If a route call fails from the normal CLI path, read the enriched error text before retrying. It now includes the failing route, derived tool, transport, port, and a suggested next debug command from recent backend history.
- Use `workflow quality-fix` when a finding maps to a safe next step like guidance scaffolding, EditMode test scaffolding, sandbox-scene creation, adding a missing `EventSystem`, adding missing `CanvasScaler` components, scaffolding or wiring an Animator Controller, or repairing importer mismatches. By default it plans the next move; add `--apply` only for the bounded fixes that are explicitly supported.
- If `workflow asset-audit` or `workflow bootstrap-guidance` is pointed at a direct project path, keep that run local. Do not expect or require Unity Console breadcrumbs for those offline scans.

## Required Debugging Behavior

If the user says something is broken, bugged, missing, invisible, not working, or confusing:

1. Run `debug doctor`.
2. Run `debug trace`.
3. Check `debug editor-log`.
4. If visuals matter, run `debug capture --kind both`.
5. Only then propose or apply a fix.
6. If a recovery poll timed out, read the full CLI error first — it should now tell you which route was being recovered, which project/port was targeted, and which last transport error blocked recovery.
7. If the failing transport is `queue`, run `agent queue` and `agent sessions` immediately after `debug doctor` so you can rule out contention before changing code.
8. In `debug doctor`, read queue findings literally: `Queued Requests Pending` means backlog, `Active Unity Agents Running` means live worker churn. They look similar but imply different next checks.
9. When you need GitHub evidence for queue stability, use `workflow benchmark-compare` and read the `Queue health` plus `Queue trend` sections in the Markdown summary instead of inferring queue changes from the generic recurring-diagnostics counts.
10. If queue behavior feels flaky over time rather than just in one snapshot, inspect `queueTrend` from `debug doctor` or `workflow benchmark-report` before changing code. That tells you whether pressure is intermittent, persistent, or likely stalled.

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

If you want the CLI's own working style to change, set a developer profile too:

```powershell
cli-anything-unity-mcp --json developer list
cli-anything-unity-mcp --json developer use builder
cli-anything-unity-mcp --json developer use review
cli-anything-unity-mcp --json --developer-profile caveman debug doctor --port <port>
```

Built-in developer profiles:

- `normal` — balanced default
- `builder` — action-first implementation mode
- `review` — risk-first reviewer mode
- `caveman` — terse low-token mode
- `director` — content-direction and project-readability bias
- `systems` — Unity systems, runtime hygiene, and testability bias
- `animator` — rig, clip, and controller bias
- `tech-artist` — material, shader, texture, and render-pipeline bias
- `ui-designer` — canvas, HUD, scaling, and clarity bias
- `level-designer` — scene readability and composition bias

On the File IPC transport, Unity also keeps a lightweight in-memory agent registry:

```powershell
cli-anything-unity-mcp --transport file --file-ipc-path C:/Projects/MyUnityProject --agent-id locke-debug --json agent queue
cli-anything-unity-mcp --transport file --file-ipc-path C:/Projects/MyUnityProject --agent-id locke-debug --json agent sessions
cli-anything-unity-mcp --transport file --file-ipc-path C:/Projects/MyUnityProject --agent-id locke-debug --json agent log locke-debug
cli-anything-unity-mcp --transport file --file-ipc-path C:/Projects/MyUnityProject --agent-id locke-debug --json agent watch --iterations 1 --interval 0
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

## Tool Coverage System

Tool coverage is tracked in `core/tool_coverage.py` via `LIVE_TESTED_ROUTE_NOTES`, `COVERED_ROUTE_NOTES`, `COVERED_TOOL_NOTES`, `MOCK_ONLY_ROUTE_NOTES`, plus computed `deferred`/`unsupported` statuses.

**Current state (2026-04-10):** 32 live-tested, 37 covered, 215 mock-only, 38 deferred, 6 unsupported (86.6% coverage).

### How to promote a tool from `deferred` to `mock-only`

Three things must happen together — never do one without the others:

1. **Add the route** to `MOCK_ONLY_ROUTE_NOTES` in `core/tool_coverage.py`.
2. **Add a mock bridge handler** in `test_full_e2e.py` inside `MockUnityBridge._handle_route()`. Existing state dicts to reuse: `self.gameobjects`, `self.scripts`, `self.prefabs`, `self.terrains`, `self.animation_clips`, `self.animation_controllers`, `self._shadergraphs`, `self._selection`, `self._scriptable_objects`, `self._editorprefs`.
3. **Add test assertions** in `test_mock_only_advanced_routes_work_against_mock_bridge`.

Keep `amplify` and `uma` deferred until optional-package fixtures exist. `spriteatlas` and MPPM/scenario routes are already mock-only covered.

Before assigning Amplify or UMA live-audit work, run:

```powershell
cli-anything-unity-mcp --json tool-coverage --status deferred --summary --fixture-plan
```

Use the returned package requirement, fixture root, preflight list, risk-ordered tool groups, and cleanup guidance as the handoff packet for contributors or sidecar agents.

Before assigning Unity Hub work, run:

```powershell
cli-anything-unity-mcp --json tool-coverage --status unsupported --summary --support-plan
```

Use that output to keep Hub work separate from the Unity Editor bridge. Start with read-only Hub discovery, then install-path state changes, and leave editor/module install commands for last because they are long-running and machine-stateful.

For one compact "what is left?" handoff, run:

```powershell
cli-anything-unity-mcp --json tool-coverage --summary --handoff-plan
```

That output should be the first thing shared with contributors before splitting optional-package audit work from Unity Hub backend work.

### Remaining deferred categories

Package-dependent live fixture work only:
`amplify` (23), `uma` (15).

## File-Based IPC Transport

The CLI supports a zero-config file-based IPC transport as an alternative to HTTP. This is useful when:
- The full Unity MCP HTTP plugin is not installed
- Ports are blocked or unreliable
- You need main-thread execution without queue contention
- Play-mode or domain reloads break the HTTP bridge

### How it works

1. Drop `unity-scripts/Editor/FileIPCBridge.cs` and `StandaloneRouteHandler.cs` into `Assets/Editor/` in your Unity project. Optionally drop in `CliAnythingWindow.cs` too for the native `Window > CLI Anything` panel, including its local `Goal Assistant` tab and copyable agent brief.
2. Unity auto-initializes the bridge on domain reload — creates `.umcp/inbox/`, `.umcp/outbox/`, and refreshes `.umcp/ping.json` every 2 seconds.
3. The CLI writes command JSON files to `.umcp/inbox/`, polls `.umcp/outbox/` for responses.
4. Everything runs on Unity's main thread automatically — no threading issues.

### CLI usage

```powershell
# Auto-detect (tries HTTP first, falls back to file IPC)
cli-anything-unity-mcp --transport auto --file-ipc-path C:/Projects/MyUnityProject instances

# File IPC only (skip HTTP port scanning)
cli-anything-unity-mcp --transport file --file-ipc-path C:/Projects/MyUnityProject scene-info

# Multiple projects
cli-anything-unity-mcp --transport file --file-ipc-path C:/Projects/Game1 --file-ipc-path C:/Projects/Game2 instances
```

### Architecture

- **`core/file_ipc.py`** — `FileIPCClient` (command write, response poll, heartbeat ping, stale cleanup) and `discover_file_ipc_instances()`.
- **`FileIPCBridge.cs`** — Polls inbox on `EditorApplication.update`, tries the full MCP plugin via reflection first, falls back to `StandaloneRouteHandler` when the plugin reports an unknown route.
- **`FileIPCBridge.cs` agent registry** — Handles `queue/info`, `agents/list`, and `agents/log` directly for File IPC. It records `agentId`, route, status, timestamp, and error string without a background polling UI.
- **`StandaloneRouteHandler.cs`** — ~27 core routes (scene, project, editor, gameobject, component, asset, script, undo, screenshot) with a `MiniJson` parser. Add new routes to its `switch` statement.
- **`CliAnythingWindow.cs`** — Optional native Unity panel with a local `Goal Assistant` tab, cached hierarchy/search/stats, common inspector/actions UI, bridge tools, generated CLI handoff commands, lightweight importer audit checks for model/material/texture hygiene, and a real local `Codex` provider path through `~/.codex/.sandbox-bin/codex.exe`. Keep it event-driven; do not add polling.
- **Backend** — `UnityMCPBackend` caches `FileIPCClient` instances in `_file_ipc_clients`, keyed by project path. `discover_instances()` merges HTTP and file IPC results, deduplicating by project path (HTTP preferred). `call_route()` delegates to the right transport based on the selected instance.

File IPC command params must stay as a raw JSON string in the command file. Unity's `JsonUtility` drops arbitrary object fields, so writing `params` as an object makes every route receive `{}`.

### When NOT to use file IPC

- For high-throughput operations (HTTP is ~10x faster per request)
- When the full Unity MCP plugin is installed and working (HTTP gives more routes)
- File IPC doesn't support the queue system — it's always main-thread direct

## Documentation Update Rule

**Every time you make code changes, you must also update:**
- `CHANGELOG.md` — what was added or changed under `## Unreleased`
- `TODO.md` — update "What Was Built", "What NOT to duplicate", priorities, and coverage table
- `AGENTS.md` — if new commands, patterns, state dicts, or agent-facing rules were added

This is not optional. Other agents read these files first before touching any code.

## What Not To Do

- Do not present temporary probes or validation helpers as the main value of the project.
- Do not skip logs and screenshots when debugging Unity visuals.
- Do not jump straight to low-level route calls if a workflow or debug command already covers the job.
- Do not push mixed CLI work and experimental fixture work together unless the user explicitly wants that.
- Do not skip `memory recall` at the start of a session on a known project — past fixes and structure facts save bridge round-trips.
- Do not manually save things to memory that `workflow inspect` already caches automatically (render pipeline, Unity version, packages).
- Do not trust cached structure as ground truth without verifying against the current bridge state when something looks wrong.
- Do not promote a route to `mock-only` without all three steps: coverage dict entry + mock handler + test assertion.
- Do not call direct `/api/context` for normal project-context reads; use `UnityMCPBackend.get_context()` so Unity settings/context work stays on the queued main-thread-safe path.
- Do not make code changes without updating `CHANGELOG.md`, `TODO.md`, and `AGENTS.md`.
- Do not create a second file IPC client — `core/file_ipc.py` already has `FileIPCClient`. The backend caches them in `_file_ipc_clients`.
- Do not add routes to `StandaloneRouteHandler.cs` without reading the existing switch statement — just add a new case.
- Do not add polling to `CliAnythingWindow.cs`; refresh caches from Unity events or explicit user actions.
- Keep `CliAnythingWindow.cs` aligned with current Unity editor APIs when adding audits or counters; prefer non-deprecated importer and object-query APIs on Unity 6.
