# Test Plan

Unit coverage:
- Route mapping for generic `tool` calls and irregular override cases.
- Session persistence and command history trimming.
- Project memory for recurring and resolved missing-reference tracking.
- Project memory isolation when explicit or env-configured memory roots are used.
- Project memory selection summaries for compact public context.
- Tool coverage matrix promotion for focused `mock-only` routes.
- Instance discovery behavior for single-instance auto-select and multi-instance selection requirements.
- Selected-project recovery when the Unity bridge disappears and comes back on a new port.
- Main-thread-safe project-context retrieval: queued `context`, queued `editor/execute-code` shim when the route is missing, and direct GET only for legacy fallback.

End-to-end coverage:
- Run the installed `cli-anything-unity-mcp` entry point in subprocess mode.
- Exercise `instances`, `select`, select-time project memory surfacing, `scene-info`, `tool unity_execute_code`, and REPL-default behavior against a mock Unity bridge server.
- Exercise `agent save`, `agent list`, `agent current`, `agent sessions`, and `agent log` against the CLI plus mock bridge routes.
- Exercise `agent watch` so queue/session/log activity can be sampled over repeated debug snapshots.
- Exercise `tool-coverage` summary and category filtering against the generated upstream coverage matrix.
- Exercise focused mock-only advanced routes across the broad advanced-tool surface through the subprocess CLI plus mock Unity bridge.
- Exercise `debug bridge` so registry/discovery/selected-port health can be checked independently of scene logic.
- Exercise `debug doctor` so the CLI can summarize likely Unity issues and recommend the next commands to run.
- Exercise `debug doctor` compiler/runtime heuristics so CS error codes and Unity exception patterns become actionable findings.
- Exercise `workflow validate-scene` recurring missing-reference memory integration.
- Exercise `debug trace` so recent CLI route/tool attempts can be inspected with status and duration.
- Exercise `debug editor-log` so the real Unity Editor.log can be tailed and filtered independently of bridge console output.
- Exercise `debug editor-log --context` so bridge lines can be inspected together with surrounding reload/import context.
- Exercise `debug editor-log --follow` so the Editor.log can be streamed live in a plain terminal session.
- Exercise `debug breadcrumb` so visible [CLI-TRACE] markers can be written into the Unity Console and Editor.log.
- Exercise `debug settings` so Unity Console breadcrumbs and dashboard defaults can be persisted safely.
- Exercise `debug dashboard` so a local browser UI can inspect doctor findings, trace, bridge state, console output, and Editor.log together.
- Exercise `debug capture` so paired Scene/Game screenshots can be saved independently of any higher-level workflow.
- Exercise `tool-coverage --fixture-plan` so remaining package-dependent deferred work has agent-ready setup, preflight, risk ordering, and cleanup guidance.
- Exercise `tool-coverage --support-plan` so unsupported Unity Hub work has an explicit implementation track and guardrails.
- Exercise `tool-coverage --handoff-plan` so remaining deferred and unsupported work has one cross-track contributor handoff.
- Exercise File IPC route params so the Python client writes Unity-readable raw JSON strings instead of objects that `JsonUtility` drops.
- Exercise File IPC agent registry routes so `agent queue`, `agent sessions`, `agent log`, and `agent watch` work without the optional HTTP queue.
- Exercise the higher-level workflow layer:
  - `workflow inspect`
  - `workflow audit-advanced` across memory, graphics, physics, profiler, sceneview, settings, testing, ui, audio, lighting, animation, input, shadergraph, terrain, and navmesh
  - `workflow create-behaviour`
  - `workflow wire-reference`
  - `workflow create-prefab`
  - `workflow validate-scene`
- Exercise the thin MCP adapter against the mock bridge:
  - `initialize`
  - `tools/list`
  - curated `tools/call` coverage for inspect, validate, create-behaviour, wire-reference, create-prefab, audit-advanced, play, reset-scene, and the generic `unity_tool_call`
- Validate queue-mode request flow through `/api/queue/submit` and `/api/queue/status`.

Validation commands:
```powershell
python -m pip install -e .
python -m unittest cli_anything.unity_mcp.tests.test_core cli_anything.unity_mcp.tests.test_full_e2e -v
cli-anything-unity-mcp --help
cli-anything-unity-mcp --json tool-coverage --summary
cli-anything-unity-mcp --json tool-coverage --category amplify --status deferred --summary --next-batch 5
cli-anything-unity-mcp --json tool-coverage --status deferred --summary --fixture-plan
cli-anything-unity-mcp --json tool-coverage --status unsupported --summary --support-plan
cli-anything-unity-mcp --json tool-coverage --summary --handoff-plan
cli-anything-unity-mcp --json tool-coverage --status unsupported
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json instances
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json state
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json route --params '{"menuItem":"Window/CLI Anything"}' editor/execute-menu-item
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --agent-id file-test-agent --json agent queue
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --agent-id file-test-agent --json agent sessions
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --agent-id file-test-agent --json agent log file-test-agent
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --agent-id file-test-agent --json agent watch --iterations 1 --interval 0
cli-anything-unity-mcp --json tool unity_get_project_context --port 7891
cli-anything-unity-mcp --json debug bridge --port 7891
cli-anything-unity-mcp --json debug doctor --recent-commands 8 --port 7891
cli-anything-unity-mcp --json debug trace --tail 20
cli-anything-unity-mcp --json debug settings
cli-anything-unity-mcp --json debug settings --no-unity-console-breadcrumbs
cli-anything-unity-mcp --json debug settings --unity-console-breadcrumbs
cli-anything-unity-mcp --json debug editor-log --tail 120 --ab-umcp-only
cli-anything-unity-mcp --json debug editor-log --tail 80 --ab-umcp-only --context 50
cli-anything-unity-mcp debug editor-log --tail 40 --ab-umcp-only --follow
cli-anything-unity-mcp debug dashboard --port 7891 --no-open-browser
cli-anything-unity-mcp --json debug breadcrumb "Trying skybox lighting tweak" --level info --port 7891
cli-anything-unity-mcp --json debug capture --kind both --port 7891
cli-anything-unity-mcp --json agent watch --iterations 2 --interval 0 --port 7891
cli-anything-unity-mcp --json debug snapshot --console-count 100 --include-hierarchy --port 7891
cli-anything-unity-mcp --json debug watch --iterations 2 --interval 0 --console-count 20 --port 7891
python .\scripts\run_live_mcp_pass.py --port 7891
python .\scripts\run_live_mcp_pass.py --port 7891 --summary-only
python .\scripts\run_live_mcp_pass.py --port 7891 --profile ui --prepare-scene discard --debug --report-file .\.cli-anything-unity-mcp\live-pass-ui-debug.json
python .\scripts\run_live_mcp_pass.py --port 7891 --include-heavy --debug --report-file .\.cli-anything-unity-mcp\live-pass-heavy-debug.json
```

Live pass notes:
- The live pass runner now follows Unity bridge rebinds across the configured scan range instead of assuming the editor stays on a single port.
- The live pass runner now supports named profiles such as `core`, `advanced`, `graphics`, `ui`, `lighting`, `terrain`, and `heavy`.
- `--prepare-scene save|discard` lets mutating validation steps start from a clean scene on purpose instead of failing halfway through a run.
- `--debug` records per-step timings, raw MCP payloads, and Unity console snapshots for failed steps.
- `--report-file` writes the full run report to disk for later inspection.
- Text mode now prints a scan-friendly live-pass summary with first next commands for failed steps. Add `--summary-only` to limit it to counts, failures/timeouts, and Unity bridge port hops.
- `workflow audit-advanced` now performs disposable scene and asset probes for broader advanced-category coverage, then resets the scene and deletes generated assets.
