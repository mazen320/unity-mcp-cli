# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Added

- **standalone-first File IPC core expansion** — the Unity-side standalone bridge now owns more of the direct no-plugin core path before plugin reflection is tried: `context`, `search/scene-stats`, `search/missing-references`, `debug/breadcrumb`, `graphics/game-capture`, `graphics/scene-capture`, and `undo/redo` are now part of the standalone-first route set.
- **direct File IPC breadcrumb route** — `debug/breadcrumb` now works through the standalone Unity bridge, so CLI activity can be written into the Unity Console and read back through `console/log` without relying on `editor/execute-code`.
- **file-transport context fix** — `UnityMCPBackend.get_context()` now uses the selected File IPC client directly instead of incorrectly falling through to `127.0.0.1:0` style port resolution.
- **`scripts/run_file_ipc_smoke.py`** — one-command standalone verification pass for a live Unity project. It checks instances, state, context, scene info, scene stats, missing references, agent visibility, breadcrumb write/readback, and optional captures, then writes a structured JSON report.
- **project insight pass in `workflow inspect`** — inspect now reads local guidance files (`AGENTS.md`, `README.md`, `Assets/MCP/Context`), scans the Unity project asset structure, and returns concrete improvement suggestions for documentation, tests, sandbox scenes, materials, prefabization, and animation/rig pipeline gaps.
- **file-transport auto-selection fixes** — a single discovered File IPC project now auto-selects for `ping`, `workflow inspect`, and CLI progress breadcrumbs, so the direct path does not require a separate manual selection step before higher-level workflows run.
- **live standalone verification update** — the no-AnkleBreaker path was live-verified in `OutsideTheBox` for `context`, `search/scene-stats`, `search/missing-references`, `debug breadcrumb`, `console/log` breadcrumb readback, and `debug capture --kind both`.
- **project memory system** — persistent per-project learning store in `core/memory.py`. Keyed by SHA256 hash of the project path. Survives across sessions. Storage at `%LOCALAPPDATA%/CLIAnything/memory/` on Windows with workspace fallback.
- **four memory categories** — `fix` (error pattern → fix command), `structure` (render pipeline, packages, Unity version, script dirs, active scene), `pattern` (recurring project behaviour), `preference` (per-project agent preferences)
- **`memory` command group** — `memory recall`, `memory remember-fix`, `memory remember`, `memory forget`, `memory stats` for manual memory management
- **auto-learn from `workflow inspect`** — every inspect call silently caches render pipeline, Unity version, project name, installed packages, script directories, and active scene. No extra flags needed.
- **auto-learn from fix loops** — when `debug doctor` finds an issue, then the issue is gone on the next doctor run, the CLI automatically credits the commands that ran in between and saves them as fixes. Reported in `report["autoLearnedFixes"]`.
- **`debug doctor` past-fix annotations** — findings now include `pastFix.fixCommand` when a matching fix is in memory, with a note that it worked before
- **`debug doctor` structure-drift detection** — three new findings powered by cached structure: `Render Pipeline Changed` (pipeline switch detected), `Unity Version Changed` (editor version differs from last inspect), `TextMeshPro Not Installed` (TMPro compilation error but package not in cached list)
- **`debug doctor` compiler/runtime heuristics** — C# compiler codes and Unity console patterns now get targeted findings, evidence, and suggested CLI follow-up commands.
- **`ProjectMemory` typed helpers** — `remember_fix()`, `remember_structure()`, `remember_pattern()`, `suggest_fix()`, `get_structure()`, `get_all_structure()`, `save_doctor_state()`, `get_last_doctor_state()`
- **recurring missing-reference memory helpers** — project memory can now track new, recurring, and resolved missing-reference issues for future validation workflows.
- **`workflow validate-scene` missing-reference tracking** — scene validation now stores new, recurring, and resolved missing references in project memory.
- **project memory surfacing on `select`** — selecting a known Unity instance now returns compact cached structure, known fixes, and recurring missing-reference context when available.
- **focused mock-only coverage batch** — the first broad pass gave 161 routes across 23 advanced categories subprocess mock-bridge coverage, reducing deferred tools from 260 to 99 at that checkpoint.
- **extended mock-only coverage (2026-04-10 continued)** — 62 additional routes across 12 categories promoted from `deferred` to `mock-only` with full mock bridge handlers and test assertions: `search` (6), `shader/shadergraph` (13), `selection` (4), `scriptableobject` (4), `settings` (7), `taglayer` (5), `texture` (5), `navmesh` (5), `physics` (5), `graphics` (3), `packages` (5). This checkpoint reached 161 mock-only, 99 deferred, and 68% coverage.
- **terrain + animation mock coverage** — all 25 deferred terrain tools and 12 deferred animation tools promoted to `mock-only` with full mock bridge handlers. `ProjectMemory.summarize_for_selection()` method added for compact selection-time context.
- **prefab + asmdef + particle + lod + constraint mock coverage** — 36 more tools promoted: `prefab` (18), `asmdef` (8), `particle` (6), `lod` (2), `constraint` (2). Each has mock bridge handler + test assertion in `test_mock_only_advanced_routes_work_against_mock_bridge`.
- **final deferred promotion batch** — remaining non-package-dependent tools promoted: `profiler` (4), `debugger` (3), `editorprefs` (3), `audio` (2), `console/clear` (1), `screenshot` (2), `testing/run-tests + get-job` (2), `undo` (3), `vfx` (2), `component` (3), `gameobject` (3 extra routes: duplicate/reparent/set-active/set-object-reference), `agents/log`, `asset/import`, `asset/create-material`, `build/start`, `ping`, `editor/execute-menu-item`, `renderer/set-material`, `scene/new`, `sceneview/set-camera`, `context`. Each has a mock bridge handler + test assertion.
- **coverage matrix at 86.6%** — 32 live-tested, 37 covered, 215 mock-only, 38 deferred (Amplify=23, UMA=15, both package-dependent), 6 unsupported. 96/96 tests passing.
- **package fixture plans for deferred tools** — `tool-coverage --fixture-plan` now returns category-level live-audit handoff plans for Amplify and UMA with package requirements, fixture roots, preflight commands, risk-ordered tool groups, cleanup guidance, and contributor-ready recommended commands.
- **unsupported support plans** — `tool-coverage --support-plan` now returns an explicit Unity Hub implementation plan so unsupported tools are tracked as a separate backend integration, not ignored.
- **cross-track coverage handoff** — `tool-coverage --handoff-plan` now summarizes the remaining 44 tools into the optional-package live-audit track and Unity Hub backend track with recommended next commands.
- **file-based IPC transport** — zero-config alternative to the HTTP bridge. Commands exchanged as JSON files through `ProjectRoot/.umcp/inbox/` and `.umcp/outbox/`. Unity polls on the main thread via `EditorApplication.update` — no threading issues, no port config, survives play-mode and domain reloads.
- **`core/file_ipc.py`** — `FileIPCClient` with atomic writes, heartbeat-based ping, response polling, stale cleanup, and `discover_file_ipc_instances()` for project-path-based discovery.
- **Unity C# scripts** — `unity-scripts/Editor/FileIPCBridge.cs` (polls inbox, dispatches to existing MCP plugin or standalone fallback, writes responses and heartbeat) and `StandaloneRouteHandler.cs` (~25 core routes without the full plugin: scene, project, editor, gameobject, component, asset, script, undo, screenshot).
- **File IPC agent registry** — `FileIPCBridge.cs` now tracks lightweight Unity-side agent sessions and action logs for File IPC commands. It supports `queue/info`, `agents/list`, and `agents/log` without the AnkleBreaker HTTP queue.
- **native Unity panel** — `unity-scripts/Editor/CliAnythingWindow.cs` adds an optional `Window > CLI Anything` EditorWindow with a cached hierarchy, inspector, and common actions. It uses direct Unity editor APIs only, no polling bridge.
- **`--transport auto|http|file`** CLI option — controls transport mode. `auto` (default) tries HTTP first, falls back to file IPC. `http` skips file IPC entirely. `file` skips HTTP port scanning entirely.
- **`--file-ipc-path`** CLI option — specify Unity project roots to check for `.umcp` file IPC bridges. Repeatable for multiple projects.
- **backend integration** — `UnityMCPBackend` discovers file IPC instances alongside HTTP instances, deduplicates by project path (preferring HTTP when both are available), and delegates `call_route` to the right transport based on the selected instance's transport type.
- **12 file IPC unit tests** — ping, stale heartbeat rejection, roundtrip command/response, timeout cleanup, discovery, backend integration, File IPC queue-info registry delegation, file-transport breadcrumb routing, and file-transport context routing.
- **`memory_for_session()` factory** — creates a `ProjectMemory` from the active session's selected instance without extra bridge calls

### Improved

- `debug doctor` now accepts a `memory` parameter and is smarter when project memory exists
- `debug doctor` now includes a compact `compilationSummary` block for quick agent scanning.
- Project memory selection summaries are generated in `ProjectMemory` so command output stays compact and side-effect free.
- Explicit/env-configured memory roots no longer read from the workspace fallback, which keeps tests and isolated agent runs from inheriting stale local memory.
- `workflow inspect` now has a side effect: structure facts are silently cached after every successful run
- local upstream tool-catalog snapshot and schema-aware discovery commands
- generated tool coverage matrix JSON and a `tool-coverage` command for tracking live-tested, covered, mock-only, unsupported, and deferred upstream tools
- saved optional sidecar agent profiles plus CLI commands for `agent current`, `agent list`, `agent save`, `agent use`, `agent clear`, and `agent remove`
- live agent inspection commands for `agent sessions`, `agent log`, and `agent queue`
- MCP-style meta-tool support for advanced-tool browsing and project-context access
- optional thin MCP adapter entry point, `cli-anything-unity-mcp-mcp`
- curated MCP tool registry that delegates into the existing CLI/core
- live MCP pass runner script for repeatable checks against a real Unity editor
- named live-pass profiles for focused validation runs such as `ui`, `lighting`, `terrain`, `graphics`, `advanced`, and `heavy`
- `workflow audit-advanced` for repeatable validation of safe advanced-tool categories and disposable probe-backed graphics/physics checks
- Unity debug snapshot/template commands for bundling console, compilation, scene, hierarchy, and queue state into a reusable CLI-first debug flow
- `debug watch` for repeatedly sampling Unity console/editor/queue state over time without rerunning snapshot by hand
- `agent watch` for sampling queue, sessions, logs, and debug snapshot summaries over time
- explicit CLI progress trace entries so multi-step workflows can write substeps into both `debug trace` and the Unity Console
- persisted `debug settings` for Unity Console breadcrumb control and dashboard defaults
- `debug dashboard`, a local browser UI for live doctor findings, trace entries, bridge diagnostics, Unity console state, and Editor.log context

### Improved

- route resolution for plugin variants such as `unity_scene_stats`
- graphics advanced tools now normalize `objectPath` to `gameObjectPath` for plugin compatibility
- mock bridge coverage for transforms, parenting, prefab instantiation, and recursive scene cleanup
- MCP adapter coverage for initialize, tools/list, and real tools/call flows against the mock Unity bridge
- curated MCP matrix coverage now exercises most of the high-level tool surface in one pass
- the live MCP pass runner can now emit debug reports, capture failure console snapshots, and follow Unity editor port rebinds during play-mode transitions
- the live MCP pass runner can now prepare a dirty scene explicitly with `--prepare-scene save|discard` before mutating validation steps
- `workflow audit-advanced` now probes UI, audio, lighting, animation, input, shadergraph, terrain, and navmesh in addition to the earlier core categories, with built-in asset cleanup
- docs and test plan coverage for CLI-first validation, debugging, and advanced-tool auditing
- public contribution flow with a lightweight CLA policy, commit sign-off guidance, and PR checklist updates
- tool coverage entries now include blocker labels so deferred tools are grouped as live-audit work, package-dependent work, environment-sensitive work, or true Hub integration gaps
- Unity console summaries now normalize common plugin log types like `log` into useful snapshot severity output
- automatic Unity breadcrumbs now use more specific workflow wording, including substeps like `Checking project info`, `Checking editor state`, and `Listing assets in Assets/...`
- `debug editor-log` now supports context windows around matches so bridge lines can be inspected with the surrounding reload/import activity
- `unity_get_project_context` now avoids the plugin's direct `/api/context` path unless it is the last legacy fallback. The CLI tries queued `context` first, then a queued `editor/execute-code` context shim, so settings-backed context reads stay on Unity's main thread and avoid `EditorPrefs.GetBool`/`GetBool can only be called from the main thread` failures.
- File IPC route params are now serialized as raw JSON strings so Unity's `JsonUtility` can pass them to the standalone handler instead of dropping them as empty payloads.
- File IPC plugin dispatch now falls back to `StandaloneRouteHandler` when the full plugin returns an unknown-route response.
- File IPC `agent queue` now asks the Unity-side File IPC registry for live queue/session state before falling back to a static direct-execution message.
- Standalone File IPC now supports `editor/execute-menu-item` and `gameobject/set-active`, and GameObject lookup can find inactive scene objects by hierarchy path.
- `MiniJson.Serialize` now serializes public fields/properties, so standalone error results come back as structured JSON instead of `StandaloneRouteHandler+ErrorResult`.

### Changed

- removed deprecated sample/scaffold workflows from the public CLI and MCP surface so the repo stays focused on the CLI/debugging/tooling layer

## 0.1.0 - 2026-04-08

Initial public-ready release of the CLI harness.

### Added

- direct CLI access to the Unity plugin bridge without MCP transport overhead
- REPL-first command flow with `--json` output
- instance discovery, selection, history, and session persistence
- route and tool passthrough commands for bridge coverage
- high-level workflows for inspect, behavior creation, scene reset, reference wiring, prefab creation, and scene validation
- play-mode recovery support for temporary bridge rebinds
- beginner-friendly docs and contributor docs
- issue templates, PR template, security policy, and repository hygiene files

### Verified

- editable install via `python -m pip install -e .`
- unit and end-to-end test coverage through `unittest`
- live authoring flows against a real Unity project
