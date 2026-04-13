# TODO

This file is the working roadmap for taking `unity-mcp-cli` from "good CLI wrapper" to "serious Unity agent layer".

It focuses on three outcomes:

- full practical tool coverage and parity
- proof through repeatable live testing
- a CLI-first Unity assistant that is easier to debug, trust, and extend than the current alternatives

## Current Baseline

As of 2026-04-12:

- `162/162` automated tests passing
- heavy live MCP pass passing `15/15`
- tool coverage: `40` live-tested, `37` covered, `207` mock-only, `38` deferred, `6` unsupported
- `unsupported` currently maps to the Unity Hub surface only
- deferred tools carry blocker labels like `stateful-live-audit`, `package-dependent-live-audit`, `unity-hub-integration`
- thin MCP adapter is working
- upstream coverage matrix exists in code and JSON form
- live debug reports via `scripts/run_live_mcp_pass.py --debug --report-file ...`

## Latest CLI Layer Pass

- Added a first-class developer-profile layer to the CLI itself, not just the Unity panel.
- New built-in profiles: `normal`, `builder`, `review`, `caveman`.
- New CLI commands: `developer list`, `developer current`, `developer use`, `developer clear`.
- New top-level flags: `--developer-profile` and `--developer-profiles-path`.
- Status output now reports the resolved developer profile alongside the agent identity.
- Runtime command history now records `developerProfile` so future trace/debug tooling can reason about which mode produced a command.
- Non-default developer profiles now influence Unity-side breadcrumb labels without breaking agent-first trace filtering.

## Latest Unity Mastery Pass

- Added expert lens foundations in `core/expert_lenses.py` and `core/expert_context.py`.
- Added built-in expert lenses: `director`, `animation`, `tech-art`, `ui`, `level-art`.
- Added a broader `systems` expert lens for Unity-wide scene architecture, runtime hygiene, and playability-hook audits.
- Added specialist rule modules in `core/expert_rules/` for direction, animation-readiness, tech-art importer hints, UI canvas scaling, and level-art density/readability.
- Added benchmark output via `workflow benchmark-report` so expert scoring can be saved as a stable JSON snapshot for GitHub or regression tracking.
- `workflow benchmark-report` now also carries bounded recurring diagnostics memory so saved benchmark JSON can show recurring compiler failures and recurring queue/bridge instability, not just current lens scores.
- `workflow benchmark-report` now also emits a dedicated `queueDiagnostics` summary so queue pressure can be tracked separately from the broader recurring-operational-signal list.
- `workflow benchmark-report` now also emits `queueTrend`, a longer-horizon queue history summary with sample count, peak backlog, peak active agents, and consecutive backlog runs.
- Added `workflow benchmark-compare` so two saved benchmark JSON snapshots can be diffed into score deltas, lens deltas, finding churn, and recurring-diagnostics churn without re-running Unity.
- `workflow benchmark-compare` now also emits a compact Markdown summary and can write it to `--markdown-file` for GitHub comments, PR descriptions, or release notes.
- `workflow benchmark-compare` now includes `queueDiagnosticsDelta` and `queueTrendDelta`, so recurring queue-pressure regressions, stuck-backlog runs, and peak queue depth changes can be shown directly in GitHub-friendly evidence.
- The Python `ChatBridge` now has a real offline assistant layer instead of the old placeholder command switch. The Unity Agent tab can inspect the project, score quality, run benchmarks, scaffold guidance/tests, create sandbox scenes, save scenes, read compilation state, and create basic primitives without requiring external API keys.
- The safe `improve project` chat path now avoids false-positive test detection from parent temp-folder names, skips sandbox creation immediately when no live Unity session is attached, and reports a before/after quality-score delta so the in-editor assistant shows measurable progress instead of only a final score.
- The offline assistant can now repair a missing live-scene `EventSystem` directly during `improve project`, using the active File IPC client and the project’s installed input package to choose the right UI input module.
- The same live `improve project` path now also repairs incomplete `EventSystem` objects that already exist but are missing the expected UI input module, instead of incorrectly treating them as already healthy.
- The same live `improve project` path can now clean up duplicate `AudioListener` components directly in-scene, keeping the best camera candidate instead of only reporting the problem.
- The same live `improve project` path can now also add a missing `AudioListener` to the best live camera candidate when a scene has cameras but no listener at all, so the assistant repairs both missing and duplicate listener states.
- The same live `improve project` path can now also delete obvious disposable probe/demo objects directly in-scene, so benchmark and demo leftovers are treated as a bounded cleanup step instead of only a systems finding.
- The same live `improve project` path can now also add a missing `CanvasScaler` to live Canvas objects directly in-scene, so basic UI scaling hygiene is repaired alongside the existing EventSystem and AudioListener cleanup.
- CLI route failures now use recent backend history to explain which route failed, on which transport/port, and which retry/debug command to run next.
- Added safe next-step planning in `core/expert_fixes.py` for `guidance`, `sandbox-scene`, `ui-canvas-scaler`, `controller-scaffold`, and `controller-wireup`.
- Added new workflows: `workflow expert-audit`, `workflow scene-critique`, `workflow quality-score`, `workflow benchmark-report`, and `workflow quality-fix`.
- Added a `systems` developer profile so the CLI can bias toward runtime hygiene, scene architecture, and testability instead of genre-specific advice.
- `workflow quality-fix` can now apply the bounded `guidance`, `test-scaffold`, `sandbox-scene`, `event-system`, `ui-canvas-scaler`, `texture-imports`, `controller-scaffold`, and `controller-wireup` fixes directly with `--apply`, while keeping the riskier/manual fixes planner-only.
- Scene-dependent expert lenses now report missing live context honestly instead of returning optimistic scores from project-path-only runs.
- The `animation` lens now looks for both asset-side pipeline gaps and scene-side `Animator` coverage when live hierarchy data is available.
- The `animation` fix path can now scaffold a generated Animator Controller asset through Unity when audit findings show controller-coverage gaps.
- Added specialist developer profiles: `director`, `animator`, `tech-artist`, `ui-designer`, `level-designer`.
- Added workflow trace wording for the new expert commands so breadcrumbs stay readable in Unity and `debug trace`.

## Latest Standalone-First File IPC Pass

- Docs/plan alignment pass: `PLAN.md` and `FILE_IPC.md` now explicitly describe the current File IPC agent-chat stack, including the Python `ChatBridge`, `AgentLoop`, Unity Agent tab, `.umcp/chat/user-inbox/`, `.umcp/chat/history.json`, `.umcp/agent-status.json`, and in-editor bridge startup flow.
- This means future work should treat the base chat/file architecture as existing, and focus on smarter intent handling, better plan generation, and richer execution UX instead of rebuilding the transport/UI skeleton.

- `FileIPCBridge.cs` now prefers the standalone handler first for the direct core route set instead of only using it as a weak last fallback.
- `StandaloneRouteHandler.cs` now covers `context`, `search/scene-stats`, `search/missing-references`, `debug/breadcrumb`, `graphics/game-capture`, `graphics/scene-capture`, and `undo/redo` in the no-plugin path.
- `StandaloneRouteHandler.cs` now also covers `search/by-component`, `selection/get`, `selection/set`, and `selection/focus-scene-view` on the standalone File IPC path, so agents can search the live scene and drive selection without the plugin.
- `UnityMCPBackend.get_context()` no longer falls through to `127.0.0.1:0` when the selected transport is file IPC.
- `emit_unity_breadcrumb()` now uses the standalone File IPC route directly when the selected instance is file transport.
- `scripts/run_file_ipc_smoke.py` now gives us a reusable no-plugin smoke pass instead of ad-hoc manual testing, including live component search plus selection/set/focus validation.
- Standalone Unity dispatch now trims incoming route names before matching, which makes the file route path more resilient to invisible whitespace in command payloads.
- `workflow inspect` now includes local project guidance + asset structure analysis and returns improvement suggestions for docs, scenes, tests, materials, prefabization, and animation pipeline gaps.
- Standalone File IPC now supports `animation/assign-controller`, and the animation quality-fix workflow can create a generated Animator Controller and assign it to a live Animator without using the plugin path.
- Standalone File IPC now also supports `animation/create-clip`, `animation/clip-info`, and `animation/controller-info`, so the CLI can inspect lightweight animation assets without leaving the no-plugin path.
- Standalone File IPC now also supports `animation/add-parameter`, `animation/add-state`, and `animation/add-transition`, so the CLI can author a minimal Animator Controller graph directly in live Unity without the plugin path.
- Standalone File IPC now also supports `animation/set-default-state`, and `animation/controller-info` reports default-state, entry-transition, any-state, and per-state transition details so the CLI can reason about Animator state-machine semantics directly.
- `workflow inspect` now also audits adjacent model/texture `.meta` files, so the CLI-side scan can flag disabled model material import plus likely normal-map and sprite-import mismatches without needing the native Unity panel first.
- `workflow asset-audit` now exposes that project scan as a dedicated CLI workflow, with a tighter summary, priority buckets, focus areas, and top recommendations. It works from a live Unity selection or a direct project path.
- `workflow bootstrap-guidance` now turns the audit output into a preview-first `AGENTS.md` and optional `Assets/MCP/Context/ProjectSummary.md` scaffold, so the CLI can fix the common "missing project guidance" recommendation itself.
- `workflow create-sandbox-scene` now turns another common audit recommendation into a real CLI action: it creates or reopens a saved sandbox scene, works on the standalone File IPC path, and restores the original scene by default unless `--open` is requested.
- `CliAnythingWindow.cs` now owns Agent-tab bridge startup too: it has a `Connect` action, persistent harness-root / Python-launcher settings, and an auto-start-on-send path that launches the chat bridge from source with `PYTHONPATH=<agent-harness>` instead of relying on a preinstalled global module.
- direct-path `workflow asset-audit` and `workflow bootstrap-guidance` runs now stay local and skip Unity Console breadcrumbs instead of touching whichever editor happens to be selected.
- single discovered File IPC projects now auto-select for higher-level workflows, so `workflow inspect` works directly with `--transport file --file-ipc-path ...` without a separate select step.
- Live-tested in `OutsideTheBox`: `state`, `context`, `search/scene-stats`, `search/missing-references`, `debug breadcrumb`, `console/log` breadcrumb readback, and `debug capture --kind both`.
- Saved capture proof:
  - `.cli-anything-unity-mcp/captures/standalone-v3-live-game.png`
  - `.cli-anything-unity-mcp/captures/standalone-v3-live-scene.png`

## What Was Just Built (2026-04-10 session)

These features were built in this working tree. Other agents working on this repo should know about them:

### Project Memory System (`core/memory.py`)
- Persistent per-project learning store keyed by SHA256 of project path
- Four categories: `fix`, `structure`, `pattern`, `preference`
- Auto-populated: `workflow inspect` silently caches render pipeline, Unity version, packages, script dirs, active scene
- Auto-learns fixes: `debug doctor` tracks findings between runs — when an issue disappears, credits the intervening CLI commands and saves them as fixes
- CLI commands: `memory recall`, `memory remember-fix`, `memory remember`, `memory forget`, `memory stats`
- Storage: `%LOCALAPPDATA%/CLIAnything/memory/<project_id>.json` with workspace fallback
- Factory: `memory_for_session(session_state)` returns a `ProjectMemory` for the active project
- Recurring missing-reference tracker has direct unit coverage for new, recurring, and resolved issues
- `select` surfaces compact memory summaries for known projects: cached public structure, known fixes, and recurring missing references

### Error Heuristics Engine (`core/error_heuristics.py`)
- 25 known C# compiler error codes (CS0246, CS0103, CS1061, etc.) with causes, fix hints, and CLI commands
- 19 Unity runtime/editor patterns (NullRef, MissingRef, shader failure, prefab issues, asset import failures, etc.)
- Integrated into `debug doctor`: compilation findings now show per-code breakdowns instead of raw messages
- `compilationSummary` block in doctor reports for quick agent scanning
- Pipeline normalization: URP/UniversalRP/Universal Render Pipeline all resolve to same canonical name
- `workflow validate-scene` now records new, recurring, and resolved missing references into project memory
- coverage matrix reduced `deferred` from `260` to `50` by promoting 210 focused routes across advanced categories to `mock-only` with subprocess bridge tests

### CLI Modular Split (`commands/`)
- `unity_mcp_cli.py` reduced from 4,621 → 250 lines (thin entrypoint only)
- 8 command modules plus package init: `_shared.py`, `instances.py`, `agent.py`, `debug.py`, `scene.py`, `tools.py`, `workflow.py`, `memory.py`
- All shared helpers in `commands/_shared.py`: `CLIContext`, `_emit`, `_run_and_emit`, `_record_progress_step`, etc.
- Adding new commands now touches one focused module, not a monolith

### Debug Doctor Improvements
- Past-fix annotations: findings show `pastFix.fixCommand` when a matching fix exists in memory
- Structure drift detection: pipeline change, Unity version change, missing package (e.g. TMPro) detected automatically
- Compiler/runtime heuristics now have direct unit coverage for CS0246, CS0103, and NullReferenceException patterns
- Fix-loop auto-learning: `_detect_and_learn_fixes()` runs after every doctor call
- Doctor state saved to memory so diffs work across sessions

## Agent-to-Agent Notes

If you are an AI agent picking up work on this repo, read these first:

1. **`AGENTS.md`** has the full operating manual: workflow, command selection, debugging rules, memory system guide.
2. **Run `memory recall` early** — if the project has been inspected before, memory has structure facts that save bridge round-trips.
3. **The memory system auto-learns** — you don't need to manually save most things. `workflow inspect` caches structure, `debug doctor` learns fixes.
4. **Use `--json` for everything** so other agents and tools can parse your output.
5. **The split happened** — commands are in `commands/`. Don't add new commands to `unity_mcp_cli.py`, add them to the right module.
6. **Test with `py -3.12`** — the project requires Python 3.11+ (`datetime.UTC` is used). Python 3.8 will fail on import.

### What Was Built After Initial Session (2026-04-10 continued)

#### Memory-Powered Recurring Missing Refs in `workflow validate-scene`
- `ProjectMemory.record_missing_references(results, scene_name)` tracks every missing ref by GameObject path + component + issue text
- Issues that appear across multiple validate-scene runs get `seen_count` incremented and flagged as `recurring`
- Issues that were present last time but gone now are returned as `resolvedIssues`
- `ProjectMemory.get_recurring_missing_refs(min_seen=2)` returns repeat offenders sorted by frequency
- `workflow validate-scene` now outputs `missingRefTracking` (new/recurring/resolved counts) and `recurringMissingRefs` (repeat offender list) in its payload
- Repeat offenders surface as warnings in the payload so agents can prioritize fixing them
- Tracker is stored under `pattern:_missing_refs_tracker` in memory — survives across sessions
- All best-effort: memory failures never break the validation workflow

#### Auto-Show Memory on `select`
- `select <port>` now surfaces cached memory when selecting a known project
- Output includes: `memory.structure` (pipeline, version, packages, etc.), `memory.knownFixes` (up to 5), `memory.recurringMissingRefs`
- Only shown when memory has entries — new projects show no extra output
- Best-effort: memory errors never break instance selection

#### Expanded Error Heuristics (`core/error_heuristics.py`)
- **CS codes added (7 new, total 25):** CS0619 (obsolete/required), CS0618 (obsolete/deprecated), CS0649 (uninitialized field), CS0535 (missing interface impl), CS0433 (duplicate type across assemblies), CS0101 (duplicate type in namespace)
- **Unity patterns added (11 new, total 19):**
  - Serialization: `SerializationException`, type not serializable, layout changed
  - Prefab: missing/broken prefab, disconnected instance, nested/variant errors
  - Asset import: generic import failure, missing .meta, model import, texture import, script import
  - Runtime: StackOverflow, OutOfMemory, Addressables errors

#### Massive Mock Coverage Push (2026-04-10 continued)
Coverage moved from `47.9%` → `86.6%` (215 mock-only, 38 deferred, out of 328 total):

**Batch 1 — terrain (25) + animation (12) = 37 tools**
- All terrain mutation routes now have mock bridge handlers + test assertions
- All animation remove/assign/blend-tree routes now covered
- `ProjectMemory.summarize_for_selection(max_fixes, max_recurring)` added — called by `select` command

**Batch 2 — prefab (18) + asmdef (8) + particle (6) + lod (2) + constraint (2) = 36 tools**
- Prefab: full asset-editing surface (hierarchy, get/set-property, add/remove component, create-variant, compare, transfer overrides, unpack)
- Asmdef: full assembly definition lifecycle (create, create-ref, add/remove references, set-platforms, update-settings)
- Particle, LOD, Constraint: all routes covered

**Batch 3 — search (6) + shader/shadergraph (13) + selection (4) + scriptableobject (4) + settings (7) + taglayer (5) + texture (5) + navmesh (5) + physics (5) + graphics (3) + packages (5) = 62 tools**
- Mock bridge state added: `_shadergraphs`, `_selection`, `_scriptable_objects` dicts
- All routes have assertions in `test_mock_only_advanced_routes_work_against_mock_bridge`
- Tests: 94/94 passing after the context main-thread regression coverage, fixture-plan coverage, support-plan coverage, handoff-plan coverage, and file-IPC coverage were added

**Batch 4 — profiler (4) + debugger (3) + editorprefs (3) + audio (2) + console/clear (1) + screenshot (2) + testing/run+get-job (2) + undo (3) + vfx (2) + component (3) + gameobject extra (4) + agents/log + asset/import + asset/create-material + build/start + ping + editor/execute-menu-item + renderer/set-material + scene/new + sceneview/set-camera + context = ~40 tools**
- Mock server gained `self._editorprefs: dict` state — reuse it, don't recreate
- Duplicate handlers for `scene/new` and `agents/log` removed; originals updated to return correct fields
- 94/94 tests passing after fixes, the context main-thread regression coverage, fixture-plan coverage, support-plan coverage, handoff-plan coverage, and file-IPC coverage

**Latest cleanup — SpriteAtlas, MPPM, CLI meta wrappers, and broad advanced-tool tail**
- Current matrix now reports `32` live-tested, `37` covered, `215` mock-only, and `38` deferred.
- SpriteAtlas is mock-only covered; do not list it as a package-dependent skip anymore.
- CLI meta wrappers (`unity_advanced_tool`, `unity_list_advanced_tools`, `unity_list_instances`, `unity_select_instance`) and route wrappers (`agents/list`, `console/log`) are now covered.
- MPPM/scenario route overrides (`scenario/info`, `scenario/list`, `scenario/status`, `scenario/activate`, `scenario/start`, `scenario/stop`) are now mock-only covered.
- Remaining deferred work is `amplify` and `uma` optional-package live fixture validation.
- `unity_get_project_context` now avoids the plugin's direct context endpoint during normal use. It tries queued `context`, then a queued `editor/execute-code` shim that calls `MCPContextManager.GetContextResponse(...)` on Unity's main thread, and only falls back to direct GET for legacy bridges.
- `tool-coverage --fixture-plan` now generates package-level handoff plans for the remaining Amplify and UMA deferred tools, including fixture roots, preflight commands, safe ordering, cleanup, and recommended contributor commands.
- `tool-coverage --support-plan` now generates an explicit Unity Hub backend plan for the 6 unsupported tools, including safe implementation order and guardrails.
- `tool-coverage --handoff-plan` now gives one cross-track "what is left" handoff: 38 optional-package live-audit tools and 6 Unity Hub backend tools.

#### File-Based IPC Transport (2026-04-10)
- **`core/file_ipc.py`** — `FileIPCClient` with atomic JSON writes, heartbeat-based ping, response polling, stale file cleanup, and `discover_file_ipc_instances()`.
- **`unity-scripts/Editor/FileIPCBridge.cs`** — Unity `[InitializeOnLoad]` script that polls `.umcp/inbox/` on the main thread, dispatches to the existing MCP plugin (via reflection) or falls back to `StandaloneRouteHandler`, writes responses to `.umcp/outbox/`, and refreshes `.umcp/ping.json` heartbeat every 2 seconds.
- **`unity-scripts/Editor/StandaloneRouteHandler.cs`** — ~27 core routes without the full plugin: `ping`, `scene/info`, `scene/hierarchy`, `scene/save`, `scene/new`, `scene/stats`, `project/info`, `editor/state`, `editor/play-mode`, `editor/execute-menu-item`, `compilation/errors`, `console/log`, `console/clear`, `gameobject/create|delete|info|set-active|set-transform`, `component/add|get-properties`, `asset/list`, `script/create|read`, `undo/perform`, `redo/perform`, `screenshot/game`. Includes a `MiniJson` parser for dictionaries and simple public-field result objects.
- **`unity-scripts/Editor/CliAnythingWindow.cs`** — optional native Unity panel at `Window > CLI Anything`; now includes a local `Goal Assistant` tab, copyable agent brief, suggested CLI command handoff, a real local `Codex` provider path through the installed Codex CLI session, lightweight importer audit for models/materials/textures, Unity 6-safe object-query/importer API usage, cached hierarchy/search/stats, inspector editing with Undo, bridge tools, and common scene actions without bridge polling.
- **Backend integration** — `UnityMCPBackend` gained `transport` (`auto|http|file`), `file_ipc_paths`, `_file_ipc_clients` cache. `discover_instances()` merges HTTP and file IPC results (deduplicates by project path, prefers HTTP). `call_route()` checks `_resolve_file_ipc_client()` first and delegates to `FileIPCClient.call_route()` for file IPC instances.
- **File IPC params fix** — Python now writes route params as a raw JSON string so Unity's `JsonUtility` does not drop params as an empty object.
- **Fallback fix** — `FileIPCBridge` now falls back to standalone routes when the full plugin returns an unknown-route result.
- **Agent registry v2** — `FileIPCBridge` now handles `queue/info`, `agents/list`, and `agents/log` directly for File IPC. The Unity-side registry records `agentId`, route, status, timestamp, and error string without adding a polling UI loop.
- **CLI options** — `--transport auto|http|file` and `--file-ipc-path <dir>` (repeatable).
- **10 file IPC unit tests** — ping, stale rejection, roundtrip, timeout, discovery, cleanup, backend integration, and File IPC queue info registry delegation. 94/94 tests passing after this batch.
- **Zero-config fallback** — drop the two C# files into `Assets/Editor/`, run the CLI with `--file-ipc-path <project_root>`, done. No ports, no HTTP server, no threading issues.
- **Live-tested in `OutsideTheBox`** — `instances`, `state`, `scene-info`, compact `hierarchy`, `compilation/errors`, `editor/execute-menu-item`, inactive-object `gameobject/info`, `gameobject/set-active`, `queue/info`, `agent queue`, `agent sessions`, `agent log`, and `agent watch --iterations 1` were verified through File IPC.

#### Rule: Always Update Docs
From this point forward, every batch of changes must update:
- `CHANGELOG.md` — what was added/changed
- `TODO.md` — what was built, what NOT to duplicate, updated priorities
- `AGENTS.md` — if new commands, patterns, or agent-facing rules were added

### What NOT to duplicate
- Don't re-implement the File IPC chat skeleton as if it does not exist. `core/agent_chat.py`, `core/agent_loop.py`, and the Agent tab in `unity-scripts/Editor/CliAnythingWindow.cs` already cover the basic inbox/history/status loop.
- Don't rebuild memory from scratch — `core/memory.py` already handles it
- Don't add error code heuristics inline in doctor — use `core/error_heuristics.py`
- Don't put new commands in the entrypoint — use the `commands/` modules
- Don't add one-off behavior flags when a mode belongs in the developer-profile layer. Use the built-in developer profiles or extend that system cleanly.
- Don't reimplement missing-ref tracking — `record_missing_references()` and `get_recurring_missing_refs()` already exist in `core/memory.py`
- Don't add mock bridge handlers without also adding them to `MOCK_ONLY_ROUTE_NOTES` in `tool_coverage.py` AND adding test assertions in `test_mock_only_advanced_routes_work_against_mock_bridge`
- Don't promote a route to `mock-only` without a corresponding mock bridge handler in `test_full_e2e.py`
- The `_shadergraphs`, `_selection`, `_scriptable_objects`, `_editorprefs` state dicts are already in the mock server — use them, don't recreate
- `amplify` and `uma` are package-dependent — keep them `deferred` until optional-package fixtures exist
- Don't call direct `/api/context` in new context code. Use `UnityMCPBackend.get_context()` so the queue/execute-code main-thread fallback stays intact.
- Don't create a second file IPC client class — `core/file_ipc.py` already has `FileIPCClient` and `discover_file_ipc_instances()`. The backend caches clients in `_file_ipc_clients`.
- Don't add routes to `StandaloneRouteHandler.cs` without also handling them in `FileIPCBridge.cs` dispatch — the bridge delegates to the standalone handler automatically, so just add to the standalone handler's switch.
- Don't write File IPC command params as a JSON object; Unity's `JsonUtility` cannot deserialize that into `CommandData.params`. Keep params as a raw JSON string.
- Don't add a heavy Unity-side polling dashboard for agent visibility. File IPC agent visibility is command-driven via `agent queue`, `agent sessions`, `agent log`, and `agent watch`.

## Definition Of Done

We should consider the tool layer "done enough" when all of these are true:

- every curated MCP tool has automated coverage
- every important upstream advanced-tool category has at least one live validation path
- failure cases produce useful debug output instead of silent breakage
- the CLI can explain likely Unity failures in one pass instead of forcing manual detective work
- contributors can see what is implemented, what is partially supported, and what is intentionally deferred

## Track 1: MCP And Tool Coverage

### P0

- Expand the coverage matrix so fewer tools remain in `deferred`.
- Keep each tool tagged as one of:
  - `covered`
  - `live-tested`
  - `mock-only`
  - `unsupported`
  - `deferred`
- Keep blocker labels actionable so `deferred` never means "ignored forever."
- Refresh the machine-readable coverage file whenever status changes.
- Keep the `tool-coverage` command aligned with the checked-in matrix.

### P1

- Expand live validation beyond the current safe categories:
  - `ui`
  - `audio`
  - `lighting`
  - `animation`
  - `terrain`
  - `navmesh`
  - `shadergraph`
- Add category-specific probe builders so these tools can be exercised safely in disposable scenes.
- Normalize more parameter mismatches between catalog expectations and live plugin routes.

### P2

- Add support notes for package-dependent tools.
- Make unsupported tools fail clearly with actionable explanations.
- Add a generated report that lists dynamic routes missing from the catalog snapshot.

## Track 2: Testing And Debugging

### P0

- Keep `scripts/run_live_mcp_pass.py` as the source of truth for live validation.
- Expand and tune the named pass profiles:
  - `core`
  - `advanced`
  - `heavy`
  - `graphics`
  - `ui`
  - `terrain`
- Save each run to a timestamped report file by default when `--debug` is enabled.
- Keep the live-pass summary mode focused on failures, timeouts, and bridge port hops.
- Keep improving the failure-first text rendering for `debug trace --summary` so the plain CLI view stays easy to scan mid-conversation.

### P1

- Capture Unity console before and after every heavy workflow.
- Capture Scene view and Game view automatically for visual workflows.
- Add detection for:
  - play-mode timeout
  - compilation error
  - bridge rebind
  - scene-dirty prompt risk
  - missing renderer/material output
- Add regression tests for previously fixed issues:
  - Input System mismatch
  - double HUD/canvas overlays
  - port rebind after play mode
  - dirty-scene reset prompts

### P2

- Add CI jobs for unit tests plus a report-only dry run of live-pass formatting logic.
- Add a "known flaky" section if any Unity-side plugin behaviors remain inconsistent.

## Track 3: Unity Assistant Quality

### P0

- ~~Keep improving `debug snapshot`, `debug doctor`, `debug watch`, and `debug capture` so the CLI feels like an actual Unity assistant.~~ **Done** — doctor now has memory, error heuristics, structure drift, fix-loop learning.
- ~~Include the most recent CLI command history in failure triage.~~ **Done** — doctor includes `recentCommands`.
- ~~Explain likely causes for compilation failures.~~ **Done** — `error_heuristics.py` maps 25 CS codes + 19 Unity patterns.
- ~~Explain likely causes for missing scripts or references.~~ **Done** — doctor detects these.
- Explain likely causes for:
  - queue contention (partially done — doctor detects queue backlog)
  - bridge restarts or timeouts
  - play-mode state leaks
- ~~Prefer commands that recommend the next useful CLI action instead of dumping raw state only.~~ **Done** — `recommendedCommands` in every doctor report.

### P1

- Better route-level timeouts and bridge recovery hints now report the route being recovered, the selected project/port, and the last blocking transport error. Queue-backed failures now also point at `agent queue` and `agent sessions`; deeper queue diagnostics still need expansion.
- `debug doctor` now distinguishes queued backlog from active Unity workers instead of collapsing both into one generic queue warning, returns a compact `queueDiagnostics` block, and records queue history into a `queueTrend` summary. Next queue work should focus on richer stalled-queue heuristics and benchmark comparisons that reason more deeply about queue trends, not just deltas.
- Expand issue-specific helper commands for common Unity failures.
- Make tool errors more actionable by surfacing route, category, likely blocker, and suggested retry path.
- Continue expanding `core/error_heuristics.py` with edge-case Unity failures as they appear in real projects.
- Expand memory-backed validation beyond missing references, starting with recurring compiler errors and queue contention.

### P2

- Start separating "CLI layer" work from "future custom Unity backend" work so backend independence becomes a real track, not just an idea.

## Track 4: Validation Probes

### P0

- Keep validation centered on temporary probe creation, scene checks, and screenshot review instead of demo/sample content.
- Make probe-driven validation stable enough to test:
  - script sync
  - play-mode transitions
  - screenshot capture
  - material/visibility sanity
  - advanced-category route safety

### P1

- Add a lightweight capture review command that summarizes obvious visual problems from the last run.
- Store capture metadata in the debug report so visual regressions can be tracked over time.

## Track 5: Visual Verification

### P0

- Make screenshot capture part of every visually meaningful workflow.
- Save paired Scene/Game captures into the runtime capture folder with predictable names.
- Add simple visual heuristics:
  - too bright
  - too dark
  - empty frame
  - HUD overlap
  - missing crosshair

### P1

- Add comparison support so two validation runs can be reviewed side by side.
- Flag when the Game view is clearly blocked by first-person meshes or bad camera placement.

## Track 6: Contributor Clarity

### P0

- Publish the tool coverage matrix in the repo.
- Link this file from the README.
- Add a "good first issue" bucket:
  - tool alias fixes
  - category probe builders
  - new live-pass profiles
  - new high-level workflows

### P1

- Open GitHub issues for each major category instead of keeping all planning in one file.
- Tag issues by:
  - `tool-coverage`
  - `live-testing`
  - `visual-quality`
  - `workflow`
  - `docs`

## Coverage State (as of 2026-04-10 continued session)

| Status | Count |
|---|---|
| `live-tested` | 32 |
| `covered` | 37 |
| `mock-only` | 215 |
| `unsupported` | 6 |
| `deferred` | 38 |
| **Total** | **328** |
| **Coverage %** | **86.6%** |

Remaining deferred breakdown:
`amplify` (23), `uma` (15).

## Immediate Next Priorities

These are the best moves right now, in order:

1. **Run optional-package live fixture audits** — `amplify` and `uma` now represent the remaining deferred surface; use `tool-coverage --fixture-plan` before assigning work.
2. ~~**Add more error heuristics** — serialization errors, prefab issues, asset import failures.~~ **Done** — 25 CS codes + 19 Unity patterns now covered.
3. **Expand memory-backed validation** — recurring compiler errors, queue contention, and bridge restarts.
4. **Add automatic Scene/Game capture review** to heavy workflows (opt-in, lightweight).
5. **Turn highest-value roadmap items into GitHub issues.**
6. **Prototype Unity Hub discovery** — use `tool-coverage --support-plan` first so Hub work stays separate from editor-bridge work.

## Short Todo List

- `P0` Use `tool-coverage --fixture-plan` to package the Amplify Shader Editor and UMA audits before assigning optional-package work.
- `P0` Use `tool-coverage --next-batch` to assign safe live-audit slices to parallel contributors after the fixture plan is understood.
- `P0` Use `tool-coverage --support-plan` before starting Unity Hub work so unsupported tools stay tracked as a separate backend integration.
- `P0` Keep bridge discovery/rebind reliable so stale selected ports do not confuse day-to-day use.
- `P0` **Always update `CHANGELOG.md`, `TODO.md`, and `AGENTS.md` when making changes** — this is now a hard rule.
- `P1` Add category-level live-pass presets that contributors can run without knowing the whole harness.
- `P1` Route failures now mention route, tool, transport, and suggested next command. Next improvement is better queue/timeout-specific triage beyond the current recovery message.
- ~~`P1` Add more Unity-specific heuristics to `error_heuristics.py` (serialization, prefab, asset import).~~ **Done** — 25 CS codes, 19 Unity patterns.
- `P2` Start separating future custom-backend work from current CLI-layer work in issues and docs.

## Notes

- The CLI remains the primary product.
- The thin MCP adapter should stay curated and efficient, not balloon into hundreds of noisy top-level tools.
- Commands belong in `commands/`, not in the entrypoint `unity_mcp_cli.py`.
- Memory is auto-populated — don't manually save things that `workflow inspect` already caches.
- If we later build a clean-room Unity backend, this roadmap should split into "CLI/MCP layer" and "Unity runtime/backend layer".
