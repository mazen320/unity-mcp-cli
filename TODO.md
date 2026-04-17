# TODO

This file is the working roadmap for taking `unity-mcp-cli` from "good CLI wrapper" to "serious Unity agent layer".

It focuses on three outcomes:

- full practical tool coverage and parity
- proof through repeatable live testing
- a CLI-first Unity assistant that is easier to debug, trust, and extend than the current alternatives

## Current Baseline

As of 2026-04-14:

- `162/162` automated tests passing
- heavy live MCP pass passing `15/15`
- tool coverage snapshot: `46` live-verified, `35` automated-covered, `204` mock-only, `38` deferred, `6` unsupported
- `unsupported` currently maps to the Unity Hub surface only
- deferred tools carry blocker labels like `stateful-live-audit`, `package-dependent-live-audit`, `unity-hub-integration`
- thin MCP adapter is working
- upstream coverage matrix exists in code and JSON form
- live debug reports via `scripts/run_live_mcp_pass.py --debug --report-file ...`

## Latest Agent Runtime Pass

- Freeform Agent-tab chat is now LLM-first when a provider is configured, and explicitly says so when no provider is configured instead of pretending to be a full assistant.
- The model-planning path now receives fresh full Unity context, project guidance, and recent chat history before building an agent loop plan.
- The Agent bridge now reports `llmAvailable`, `llmProvider`, `llmModel`, and `llmConfigSource` in `.umcp/agent-status.json`.
- Project-local bridge preferences now live in `.umcp/agent-config.json` via `preferredProvider` and `preferredModel`.
- Project-local bridge secrets can now live in `.umcp/agent.env`, with process environment variables still taking precedence.
- The Unity Agent settings now expose provider/model selection and write the project-local bridge config directly.
- Immediate next live-validation task: reopen a real Unity project and verify the full in-editor provider/model flow end to end, including `.umcp/agent.env` pickup and selected-model reporting.

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
- Added a dedicated `physics` expert lens for collider coverage, rigidbody hygiene, and movement-body setup checks, plus a matching `physics` developer profile.
- Added a bounded `physics` workflow fix, `player-character-controller`, which can add a `CharacterController` to the single clear likely player object in a live scene and refuses to guess when multiple candidates exist.
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
- The same live `improve project` path now also strips duplicate `EventSystem` and UI input-module components from extra scene objects, keeping one primary `EventSystem` instead of only repairing missing pieces.
- The same live `improve project` path now also normalizes the primary `EventSystem` object itself by removing the wrong extra UI input module when both legacy and Input System modules are present together.
- The same live `improve project` path can now clean up duplicate `AudioListener` components directly in-scene, keeping the best camera candidate instead of only reporting the problem.
- The same live `improve project` path can now also add a missing `AudioListener` to the best live camera candidate when a scene has cameras but no listener at all, so the assistant repairs both missing and duplicate listener states.
- The same live `improve project` path can now also delete obvious disposable probe/demo objects directly in-scene, so benchmark and demo leftovers are treated as a bounded cleanup step instead of only a systems finding.
- The same live `improve project` path can now also add a missing `CanvasScaler` to live Canvas objects directly in-scene, so basic UI scaling hygiene is repaired alongside the existing EventSystem and AudioListener cleanup.
- The same live `improve project` path can now also add a missing `GraphicRaycaster` to live Canvas objects directly in-scene, so UI canvases are normalized for interaction along with the existing EventSystem and CanvasScaler repair.
- The same live `improve project` path can now also add a bounded `CharacterController` to one clear likely player object when the scene has an obvious movement-body gap, while still refusing to guess across multiple player-like objects.
- Added a first-class CLI `workflow improve-project` command so the same bounded improvement pass is no longer trapped inside the Unity Agent tab. Offline it writes guidance and EditMode smoke-test scaffolding; with `--port` it also runs the bounded live-scene hygiene bundle and reports `baselineScore`, `finalScore`, `scoreDelta`, and explicit `applied` / `skipped` fix lists for demos or GitHub evidence.
- The Agent chat and the CLI now share the same `workflow improve-project` engine. `workflow agent-chat <PROJECT_ROOT>` seeds that File IPC project into session state, and `workflow improve-project` can now automatically reuse a matching selected live Unity editor even without `--port`, so the in-editor assistant and shell command produce the same bounded fix bundle and score delta.
- `workflow improve-project` can now also emit a markdown artifact through `--markdown-file`, so the same run that repairs the project can generate a GitHub-friendly summary of score delta plus applied/skipped fixes without a separate hand-written status report.
- CLI route failures now use recent backend history to explain which route failed, on which transport/port, and which retry/debug command to run next.
- Added safe next-step planning in `core/expert_fixes.py` for `guidance`, `sandbox-scene`, `ui-canvas-scaler`, `controller-scaffold`, and `controller-wireup`.
- Added safe next-step planning and bounded apply support for `ui-graphic-raycaster`, so the reusable workflow layer can normalize Canvas interaction setup the same way the in-editor assistant now does.
- The UI expert lens now also flags `Canvas without GraphicRaycaster`, so the new bounded workflow and assistant repair path is discoverable from audits instead of only by knowing the fix name.
- The systems expert lens now also flags `No AudioListener in scene`, and the reusable workflow layer now has a bounded `audio-listener` fix so systems audits can directly drive the same audio hygiene repair path the assistant already uses.
- The reusable `workflow quality-fix --lens systems --fix event-system --apply` path now also repairs incomplete existing `EventSystem` objects by adding the expected UI input module instead of only creating brand-new EventSystem objects.
- The reusable `workflow quality-fix --lens systems --fix event-system --apply` path now also removes duplicate EventSystem/input-module components from extra scene objects and strips the wrong extra input module from the primary EventSystem object, so the workflow path finally matches the assistant-side normalization behavior.
- The reusable `workflow quality-fix --lens systems --fix disposable-cleanup --apply` path can now delete obvious probe/demo objects directly from the live scene, so the workflow layer has parity with the assistant-side bounded cleanup for benchmark and fixture leftovers.
- The systems expert lens now also flags `Multiple EventSystems in scene` and `EventSystem missing UI input module`, so the event-system normalization work is surfaced directly in audits instead of only discovered when a fix is attempted.
- The systems expert lens now also surfaces duplicate EventSystem object names in the finding detail and flags `EventSystem has conflicting UI input modules` when both legacy and Input System modules are active on the same object, so benchmark output is more actionable.
- The systems expert lens now also surfaces duplicate `AudioListener` object names and the likely keep target, and missing-listener findings now name the likely camera target, so systems benchmarks explain the audio repair path instead of only reporting counts.
- The subprocess E2E harness no longer hides a huge mock-route coverage block inside the self-transition regression, and the heaviest mock-route and `workflow audit-advanced` tests now use in-process Click invocation where appropriate so the full `test_full_e2e` suite finishes reliably on slower local machines.
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
Historical blended route-status snapshot moved from `47.9%` → `86.6%` at that checkpoint. Treat that as a status milestone, not a single confidence metric:

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
- Current matrix now reports `46` live-verified, `35` automated-covered, `204` mock-only, `38` deferred, and `6` unsupported.
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

We should consider the product "done enough" when all of these are true:

- the engine is reliable enough for day-to-day Unity work
- the visible Unity surface makes the intelligence obvious and satisfying
- major capabilities are benchmarkable and exportable
- assistant behavior is mostly powered by reusable workflows instead of special-case chat logic
- contributors can tell which work belongs to the engine, the visible product, or the proof layer

## Execution Tracks

This file follows the same hierarchy as the main roadmap:

- `PLAN.md` explains how the product gets built
- `README.md` explains what the product is becoming
- this file explains what happens next

The execution backlog is organized into three tracks:

1. **Engine Track**
Build the reusable system.

2. **Magic Track**
Make the system visible and satisfying inside Unity.

3. **Proof Track**
Make progress measurable and GitHub-ready.

4. **Learning Track**
Make the assistant improve from structured outcomes, memory, and evals.

## Engine Track

### P0

- Keep converting assistant-only behavior into top-level reusable workflows.
- Keep expanding standalone-first ownership in high-value Unity categories:
  - prefab
  - material / renderer
  - physics
  - animation
- Keep bridge/session/recovery behavior reliable so selected targets do not drift or silently degrade.
- Keep route failures actionable with route, transport, target, and next-command context.
- Expand memory-backed validation beyond missing references:
  - recurring compiler failures
  - queue contention
  - bridge restart patterns

### P1

- Expand live validation beyond current safe categories:
  - UI
  - audio
  - lighting
  - terrain
  - navmesh
  - shadergraph
- Normalize more parameter mismatches between the catalog and live routes.
- Keep unsupported surfaces explicit and actionable instead of vaguely deferred.
- Start separating current CLI-layer work from future custom Unity-backend work.

### P2

- Add deeper package-aware route notes and support guidance.
- Add generated reports for dynamic route/catalog drift.
- Keep reducing plugin-only dependence where standalone ownership is realistic.

## Magic Track

### P0

- Keep the Unity Agent tab’s `improve-project` card aligned with the shared workflow payload and markdown export format.
- Expand the same visible report treatment to benchmark, compare, and expert-audit results.
- Keep making the Agent tab feel like a real assistant surface, not a transport log.
- Keep one-click improvement flows aligned with the reusable workflow engine.

### P1

- Surface expert-lens audits clearly in Unity:
  - score
  - grade
  - findings
  - supported fixes
  - confidence/context availability
- Add visible before/after summaries for major repair flows.
- Improve Unity-side presentation of:
  - benchmarks
  - compare reports
  - captures
  - fix reports

### P2

- Move toward richer model-backed orchestration on top of the workflow layer.
- Keep “magic” concrete: users should always see what changed, why, and what comes next.

## Proof Track

### P0

- Keep `scripts/run_live_mcp_pass.py` as the source of truth for live validation.
- Keep `workflow benchmark-report`, `benchmark-compare`, and `improve-project --markdown-file` as first-class evidence outputs.
- Save timestamped report artifacts for heavy/debug runs.
- Keep benchmark and markdown artifacts easy to drop into GitHub issues, PRs, and devlogs.

### P1

- Add more named benchmark fixtures and repeatable scene scenarios.
- Capture Scene/Game evidence for visually meaningful workflows.
- Add lightweight visual-review heuristics where they materially improve proof quality.
- Make side-by-side before/after comparisons easier for benchmark and capture outputs.

### P2

- Add CI coverage for report formatting and artifact generation.
- Promote the strongest benchmark scenarios into public-facing proof for the repo.

## Learning Track

### P0

- Turn the written local-first learning-system spec into an implementation plan:
  - `docs/superpowers/specs/2026-04-14-learning-system-design.md`
  - start with Phase L1 run ledger only
- Define the minimum useful event schema for workflow runs:
  - intent
  - workflow chosen
  - routes called
  - latency
  - errors
  - score delta
  - applied/skipped fixes
  - accepted or reverted outcome when known
- Start turning real improvement, benchmark, and repair runs into replayable eval fixtures instead of only one-off debug evidence.

### P1

- Add bounded local persistence for project memory, user preferences, and recurring system patterns.
- Add opt-in redacted sync for run outcomes and artifacts instead of assuming a hosted backend by default.
- Rank workflows, prompts, and fix paths by real outcome quality once enough structured runs exist.

### P2

- Add retrieval-based experience memory on top of the run/eval store.
- Only evaluate fine-tuning or distillation after the traces are clean, labeled, and demonstrably useful.

## Current Coverage State

Keep tracking tool coverage, but do it as support for the engine track rather than the whole roadmap.

Current status snapshot:

| Status | Count |
|---|---|
| `live-tested` | 46 |
| `covered` | 35 |
| `mock-only` | 204 |
| `unsupported` | 6 |
| `deferred` | 38 |
| **Total** | **329** |

Remaining deferred breakdown:
`amplify` (23), `uma` (15)

Reporting rule:
- Do not blend `live-tested`, `covered`, and `mock-only` into one confidence percentage. Use `summary.evidenceSummary` instead.

## Immediate Next Priorities

These are the best moves right now, in order:

1. **Magic:** extend the new Agent-tab report surface beyond `improve-project` into benchmarks, audit results, and before/after summaries.
2. **Engine:** keep moving assistant-only actions into reusable workflows.
3. **Engine:** keep expanding standalone-first depth in prefab, material/renderer, physics, and animation.
4. **Proof:** strengthen benchmark/evidence exports so every major fix can be shown clearly on GitHub.
5. **Learning:** write the local-first learning-system spec and event schema so the product can improve from real runs.
6. **Engine/Proof:** continue optional-package fixture audits (`amplify`, `uma`) through the existing coverage planning commands.

## Short Todo List

- `P0` Extend the new Agent-tab report card pattern to benchmark, compare, and audit outputs.
- `P0` Keep using `tool-coverage --fixture-plan` to package Amplify Shader Editor and UMA audits before assigning optional-package work.
- `P0` Keep bridge discovery/rebind reliable so stale selected ports do not confuse day-to-day use.
- `P0` Keep route failures and queue/recovery diagnostics actionable.
- `P0` **Always update `CHANGELOG.md`, `TODO.md`, and `AGENTS.md` when making changes.**
- `P1` Write the local-first learning-system spec and event schema.
- `P1` Add more category-level live-pass presets contributors can run without knowing the whole harness.
- `P1` Add more benchmark fixtures and proof-oriented markdown/report examples.
- `P1` Keep separating future custom-backend work from current CLI-layer work in docs and issues.

## Notes

- The CLI remains the main reusable engine.
- The Unity Agent tab is the main visible product layer on top of that engine.
- The thin MCP adapter should stay curated and efficient.
- Commands belong in `commands/`, not in the entrypoint `unity_mcp_cli.py`.
- Memory is auto-populated; don’t manually save things `workflow inspect` already caches.
- If we later build a clean-room Unity backend, the engine track should split into:
  - CLI/workflow layer
  - Unity runtime/backend layer
