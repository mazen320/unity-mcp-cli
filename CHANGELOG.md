# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Added

- **docs alignment for the File IPC agent chat stack** — updated `PLAN.md` and `FILE_IPC.md` so they reflect the already-implemented Python `ChatBridge`, `AgentLoop`, Unity Agent tab, `.umcp/chat/user-inbox/`, `.umcp/chat/history.json`, `.umcp/agent-status.json`, and the in-editor bridge launch flow, instead of describing that architecture as entirely future work.
- **offline Agent tab assistant** — `core/agent_chat.py` now routes Unity Agent-tab messages through a project-aware offline assistant instead of the old placeholder switch. It can greet/help, summarize context, run project audits, quality scores, benchmark reports, scaffold guidance/tests, create sandbox scenes, save scenes, read compilation state, and create simple primitives without requiring external model APIs.
- **safer `improve project` chat pass** — the offline Agent assistant now scopes test detection to files inside the Unity `Assets` tree instead of matching outer temp-folder names, so the safe improvement bundle no longer skips test scaffolding just because the workspace sits under `.tmp-tests`. The reply also reports a before/after quality-score delta instead of only the final score, and sandbox creation now skips immediately with a clear “no live Unity session” reason instead of burning through a File IPC timeout when the assistant is only operating on a project path.
- **direct systems repair in the offline assistant** — when a live Unity scene is attached, the `improve project` chat flow can now inspect the scene hierarchy and repair a missing `EventSystem` directly through the File IPC client. It creates or reuses the `EventSystem` object and adds either `InputSystemUIInputModule` or `StandaloneInputModule` based on installed packages, without detouring through the broader workflow layer.
- **incomplete EventSystem repair in the offline assistant** — the same live `improve project` flow now also repairs existing `EventSystem` objects that are missing the expected UI input module, instead of treating any object with an `EventSystem` component as already correct.
- **duplicate EventSystem cleanup in the offline assistant** — the same live `improve project` flow now also strips duplicate `EventSystem` and UI input-module components from extra scene objects, keeping one primary `EventSystem` instead of leaving competing scene-control objects active.
- **primary EventSystem normalization in the offline assistant** — the same live `improve project` flow now also removes the wrong extra UI input module from the primary `EventSystem` object when both legacy and Input System modules are present together.
- **duplicate AudioListener cleanup in the offline assistant** — the same live `improve project` flow can now detect multiple `AudioListener` components in the active scene, keep the best camera candidate, and remove the extra listeners directly through the existing File IPC component-removal route.
- **missing AudioListener repair in the offline assistant** — the same live `improve project` flow can now also detect scenes with cameras but no `AudioListener`, choose the best camera candidate, and add the component directly through File IPC instead of only treating duplicate listeners as fixable.
- **disposable probe cleanup in the offline assistant** — when a live Unity scene is attached, `improve project` can now remove obvious temporary probe/demo objects like `StandaloneProbe` or other path matches containing `probe`, `fixture`, `temp`, `debug`, or `standalone` by using the existing File IPC `gameobject/delete` route.
- **CanvasScaler repair in the offline assistant** — the same live `improve project` flow can now detect Canvas objects missing `CanvasScaler` and add the component directly through File IPC, so basic UI scaling hygiene is repaired in the same bounded scene-fix pass as EventSystem and AudioListener cleanup.
- **GraphicRaycaster repair in the offline assistant** — the same live `improve project` flow can now detect Canvas objects missing `GraphicRaycaster` and add the component directly through File IPC, so UI canvases are normalized for interaction in the same bounded scene-fix pass as EventSystem and CanvasScaler repair.
- **first-class CLI developer profiles** — the harness now has a dedicated developer-profile layer with built-in `normal`, `builder`, `review`, and `caveman` modes, plus persistent selection through `developer list`, `developer current`, `developer use`, `developer clear`, `--developer-profile`, and `--developer-profiles-path`.
- **Unity Mastery Pack foundations** — added expert lens foundations in `core/expert_lenses.py` and `core/expert_context.py`, plus specialist developer profiles for `director`, `animator`, `tech-artist`, `ui-designer`, and `level-designer`.
- **broad Unity systems lens** — added a new `systems` expert lens plus a matching `systems` developer profile. It audits scene architecture, runtime hygiene, sandbox coverage, prefab coverage, duplicate `AudioListener` usage, missing `EventSystem` setup, movement-foundation gaps, collider gaps, and disposable probe/demo objects without overfitting to a specific genre or demo scene.
- **specialist expert rules** — new `core/expert_rules/` modules now audit direction/guidance gaps, animation-readiness, tech-art importer mismatches, UI canvas-scaler coverage, and level-art scene density/readability.
- **benchmark report workflow** — added `workflow benchmark-report`, which packages expert-lens scoring into a stable JSON snapshot with overall grade, weakest lenses, severity breakdown, top findings, and project summary metadata for GitHub or local regression tracking.
- **benchmark diagnostics memory** — `workflow benchmark-report` now also includes bounded recurring diagnostics memory, so saved benchmark artifacts carry forward recurring compilation errors and recurring operational signals instead of only the current lens scores.
- **queue-health benchmark summaries** — `workflow benchmark-report` now emits a dedicated `queueDiagnostics` block with status, recurring queue signal keys, and a compact summary, so saved benchmark JSON can show queue pressure separately from the broader recurring-operational-signal list.
- **queue history snapshots** — `debug doctor` now records bounded queue samples in project memory and returns a `queueTrend` block, so the CLI can distinguish intermittent backlog from persistent or stalled queue pressure.
- **queue-trend benchmark export** — `workflow benchmark-report` now includes `queueTrend`, which carries sample count, peak queue depth, peak active agents, consecutive backlog runs, and a compact trend summary for GitHub evidence artifacts.
- **queue-trend benchmark deltas** — `workflow benchmark-compare` now also diffs `queueTrend`, so Markdown summaries can show whether queue backlog, consecutive stuck runs, and peak queue depth improved or regressed between two benchmark snapshots.
- **benchmark comparison workflow** — added `workflow benchmark-compare`, which diffs two saved benchmark-report JSON files into overall score deltas, per-lens deltas, finding churn, and recurring-diagnostics churn without needing a live Unity session.
- **queue-health benchmark deltas** — `workflow benchmark-compare` now also reports `queueDiagnosticsDelta` and renders a `Queue health` section in Markdown so regressions or fixes in queue pressure are visible in GitHub evidence.
- **benchmark markdown export** — `workflow benchmark-compare` can now emit a compact Markdown summary and write it through `--markdown-file`, so benchmark diffs can be pasted straight into GitHub issues, PRs, or release notes.
- **actionable route-failure hints** — CLI command failures now reuse the last recorded backend error history entry to surface the failing route, derived tool name, transport, port, and a concrete retry command instead of only returning the raw bridge exception text.
- **recovery-timeout context** — route recovery timeouts now report which route was being recovered, which selected project/port the backend was waiting on, and the last blocking transport error, so stale-port failures do not collapse back to bare connection exceptions.
- **queue-specific failure guidance** — queue-backed route failures now point directly at `agent queue` and `agent sessions` in addition to `debug doctor`, so contention and stuck worker state can be triaged from the failure text itself.
- **split queue diagnostics in `debug doctor`** — queue backlog and active worker churn now produce separate findings (`Queued Requests Pending` vs `Active Unity Agents Running`) instead of one generic queue warning, so reports and benchmark artifacts carry the real operational state.
- **doctor queue summary block** — `debug doctor` now returns a compact `queueDiagnostics` block with current backlog/active-worker state plus recurring queue-pressure context when memory exists, so agent tooling does not have to reconstruct queue health from raw findings.
- **expert quality workflows** — added `workflow expert-audit`, `workflow scene-critique`, `workflow quality-score`, and `workflow quality-fix` so the CLI can score a project through specialist Unity lenses and plan safe next actions like guidance scaffolding, sandbox-scene creation, generated animation-controller scaffolding, or live controller wireup.
- **bounded expert-fix apply support** — `workflow quality-fix --apply` can now execute the safest expert fixes directly: writing generated guidance files for `guidance`, running the sandbox-scene workflow for `sandbox-scene`, adding missing `CanvasScaler` components for the `ui-canvas-scaler` fix, repairing likely normal-map / sprite importer mismatches for the `texture-imports` fix, creating a generated Animator Controller asset for the `controller-scaffold` fix, and wiring that controller to a live Animator for the `controller-wireup` fix, while leaving riskier/manual fixes in planner mode.
- **bounded UI GraphicRaycaster fix** — `workflow quality-fix --lens ui --fix ui-graphic-raycaster --apply` now adds missing `GraphicRaycaster` components to Canvas objects through the same bounded workflow path used for `ui-canvas-scaler`, so the reusable CLI can repair UI interaction setup without relying on the chat assistant path.
- **UI lens GraphicRaycaster finding** — the UI expert audit now flags `Canvas without GraphicRaycaster`, so the new bounded fix is surfaced directly in audit output instead of only existing as a manual fix name.
- **bounded systems AudioListener fix** — `workflow quality-fix --lens systems --fix audio-listener --apply` now normalizes the scene to one `AudioListener` by adding it to the primary camera candidate when missing or removing duplicates from extra cameras, and the systems audit now also flags `No AudioListener in scene` when cameras exist without any listener.
- **bounded systems EventSystem repair parity** — `workflow quality-fix --lens systems --fix event-system --apply` now repairs incomplete existing `EventSystem` objects by adding the expected UI input module instead of only creating a missing EventSystem object.
- **bounded systems EventSystem normalization parity** — the same workflow `event-system` fix now also removes duplicate `EventSystem`/input-module components from extra scene objects and strips the wrong extra module from the primary EventSystem object, matching the assistant-side normalization behavior instead of stopping at “object exists”.
- **systems lens EventSystem findings** — the systems audit now flags `Multiple EventSystems in scene` and `EventSystem missing UI input module`, so the new normalization work is visible directly from audit output.
- **bounded systems EventSystem fix** — `workflow quality-fix --lens systems --fix event-system --apply` now creates or repairs a live `EventSystem` object when Canvas UI exists without one, choosing `InputSystemUIInputModule` for Input System projects and `StandaloneInputModule` otherwise.
- **bounded test scaffold fix** — `workflow quality-fix --lens director --fix test-scaffold --apply` now writes a minimal EditMode smoke test and test assembly scaffold under `Assets/Tests/EditMode/`, but only when `com.unity.test-framework` is already present.
- **live-context-aware expert lenses** — scene-dependent lenses now declare when they need a live selected Unity editor. `ui` and `level-art` return explicit `requiresLiveUnity` / `contextAvailable` metadata and a “live scene context unavailable” finding when run against a bare project path.
- **richer animation lens** — the `animation` expert lens now catches three distinct states: models with no animation evidence, clips without Animator Controller coverage, and scenes with no `Animator` components even when animation assets exist.
- **bounded animation scaffold fix** — the `animation` lens now advertises `controller-scaffold`, which plans and can apply a generated Animator Controller asset under `Assets/Animations/Generated/` through the existing Unity animation route.
- **standalone animation wireup** — Standalone File IPC now supports `animation/assign-controller`, and the animation quality-fix workflow can create or reuse the generated controller and assign it to a live `Animator` without needing the plugin bridge.
- **standalone animation inspection** — Standalone File IPC now supports `animation/create-clip`, `animation/clip-info`, and `animation/controller-info`, so the CLI can create a lightweight probe clip and inspect clip/controller state directly through the no-plugin path.
- **standalone animation authoring** — Standalone File IPC now supports `animation/add-parameter`, `animation/add-state`, and `animation/add-transition`, so the CLI can build a minimal Animator Controller graph directly against live Unity without the plugin bridge.
- **default-state semantics fixed** — `animation/controller-info` now reports default-state, entry-transition, any-state, and per-state transition details, and Standalone File IPC now supports `animation/set-default-state` so the CLI can change the Animator layer default state directly instead of faking it with a self-transition.
- **goal assistant inside the native Unity panel** — `unity-scripts/Editor/CliAnythingWindow.cs` now includes a local `Assistant` tab with goal input, project/scene scan summaries, ranked recommendations, safe one-click follow-up actions, generated CLI command suggestions tied to the current project path and selection, and a copyable brief for handing context to the CLI agent without background polling.
- **real Codex login path in the native Unity panel** — `unity-scripts/Editor/CliAnythingWindow.cs` now detects the local Codex session plus `~/.codex/.sandbox-bin/codex.exe`, exposes a `Codex` provider button, and routes in-editor chat through the local Codex CLI instead of treating ChatGPT session tokens like an OpenAI API key.
- **Unity Agent tab bridge connect flow** — `unity-scripts/Editor/CliAnythingWindow.cs` now has a real `Connect` path plus saved harness-root / Python-launcher settings, and can auto-start the Python chat bridge on send using `PYTHONPATH=<agent-harness>` instead of assuming the global shell already has `cli_anything.unity_mcp` installed.
- **CLI-side importer heuristics in `workflow inspect`** — `core/project_insights.py` now reads adjacent model and texture `.meta` files during project scans so the shell-side workflow can flag disabled model material import, likely normal-map mismatches, and likely sprite-import mismatches using the same broad heuristics as the native Unity assistant.
- **`workflow asset-audit`** — dedicated CLI workflow for project-side asset audits. It can work from a selected Unity editor or a direct project path and returns a tighter summary of guidance coverage, asset counts, importer-hint counts, priority buckets, focus areas, and top recommendations.
- **`workflow bootstrap-guidance`** — preview-first CLI workflow that turns the current project audit into a starter `AGENTS.md` and optional `Assets/MCP/Context/ProjectSummary.md`, with `--write` support when you want the files created in place.
- **`workflow create-sandbox-scene`** — new CLI workflow that creates or reopens a saved sandbox scene under `Assets/Scenes` by default, supports custom names/folders, restores the original scene unless `--open` is passed, and works on the standalone File IPC path.
- **standalone search + selection expansion** — the no-plugin File IPC bridge now supports `search/by-component`, `selection/get`, `selection/set`, and `selection/focus-scene-view`, and those routes were live-verified in `OutsideTheBox`.
- **standalone public prefab/material/renderer parity** — the no-plugin File IPC bridge now owns the public route surface for `asset/create-material`, `asset/create-prefab`, `asset/instantiate-prefab`, `renderer/set-material`, `graphics/material-info`, `graphics/renderer-info`, and widened `prefab/info`. These were live-verified in `OutsideTheBox`, including prefab asset + scene-instance inspection through the same public route.
- **File IPC smoke expansion** — `scripts/run_file_ipc_smoke.py` now checks live component search, selection readback, selection set, and Scene view focus so the standalone pass validates more than just read-only status routes.
- **dispatch hardening** — standalone Unity dispatch now trims incoming route names before matching, which fixes invisible route-string whitespace issues in the file transport path.
- **Unity 6 model-importer compatibility** — the native Unity panel's importer audit now uses `materialImportMode` instead of the removed `importMaterials` property, so the assistant keeps compiling on newer Unity versions while checking model material ownership.
- **Unity 6 object-query cleanup** — the native Unity panel now uses the newer `FindObjectsByType<T>(FindObjectsInactive.Exclude)` overloads instead of deprecated `FindObjectsSortMode` variants, which keeps the assistant quieter on newer Unity editors.
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
- **coverage matrix at 86.6%** — 32 live-tested, 37 covered, 215 mock-only, 38 deferred (Amplify=23, UMA=15, both package-dependent), 6 unsupported. 102/102 tests passing.
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

- CLI status and runtime history now surface the resolved developer profile, so command sessions can explain not just which agent ran a command, but which working mode the CLI was in.
- workflow trace wording now includes `expert-audit`, `scene-critique`, `quality-score`, and `quality-fix`, so Unity-side breadcrumbs and `debug trace` summaries stay readable during expert passes.
- `debug doctor` now accepts a `memory` parameter and is smarter when project memory exists
- `debug doctor` now includes a compact `compilationSummary` block for quick agent scanning.
- direct-path `workflow asset-audit` and `workflow bootstrap-guidance` runs now stay offline-local and skip Unity Console breadcrumbs, so previewing or scaffolding guidance for a project path does not write trace noise into an unrelated selected editor
- workflow trace wording now includes `create-sandbox-scene`, so Unity-side breadcrumbs and `debug trace` summaries describe sandbox creation clearly instead of falling back to a generic workflow label
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
