# Test Plan

Unit coverage:
- Route mapping for generic `tool` calls and irregular override cases.
- Session persistence and command history trimming.
- Instance discovery behavior for single-instance auto-select and multi-instance selection requirements.
- Selected-project recovery when the Unity bridge disappears and comes back on a new port.

End-to-end coverage:
- Run the installed `cli-anything-unity-mcp` entry point in subprocess mode.
- Exercise `instances`, `select`, `scene-info`, `tool unity_execute_code`, and REPL-default behavior against a mock Unity bridge server.
- Exercise `agent save`, `agent list`, `agent current`, `agent sessions`, and `agent log` against the CLI plus mock bridge routes.
- Exercise `agent watch` so queue/session/log activity can be sampled over repeated debug snapshots.
- Exercise `tool-coverage` summary and category filtering against the generated upstream coverage matrix.
- Exercise the higher-level workflow layer:
  - `workflow inspect`
  - `workflow build-sample`
  - `workflow build-fps-sample`
  - `workflow audit-advanced` across memory, graphics, physics, profiler, sceneview, settings, testing, ui, audio, lighting, animation, input, shadergraph, terrain, and navmesh
  - `workflow create-behaviour`
  - `workflow wire-reference`
  - `workflow create-prefab`
  - `workflow validate-scene`
  - `workflow smoke-test`
- Exercise the thin MCP adapter against the mock bridge:
  - `initialize`
  - `tools/list`
  - curated `tools/call` coverage for inspect, validate, create-behaviour, wire-reference, create-prefab, build-sample, build-fps-sample, audit-advanced, play, reset-scene, and the generic `unity_tool_call`
- Validate queue-mode request flow through `/api/queue/submit` and `/api/queue/status`.

Validation commands:
```powershell
python -m pip install -e .
python -m unittest cli_anything.unity_mcp.tests.test_core cli_anything.unity_mcp.tests.test_full_e2e -v
cli-anything-unity-mcp --help
cli-anything-unity-mcp --json tool-coverage --summary
cli-anything-unity-mcp --json tool-coverage --status unsupported
cli-anything-unity-mcp --json workflow scaffold-test-project --project-path "C:\Temp\UnityMcpCliSmokeProject" --force
cli-anything-unity-mcp --json agent watch --iterations 2 --interval 0 --port 7891
cli-anything-unity-mcp --json debug snapshot --console-count 100 --include-hierarchy --port 7891
python .\scripts\run_live_mcp_pass.py --port 7891
python .\scripts\run_live_mcp_pass.py --port 7891 --profile ui --prepare-scene discard --debug --report-file .\.cli-anything-unity-mcp\live-pass-ui-debug.json
python .\scripts\run_live_mcp_pass.py --port 7891 --include-heavy --debug --report-file .\.cli-anything-unity-mcp\live-pass-heavy-debug.json
```

Live pass notes:
- The live pass runner now follows Unity bridge rebinds across the configured scan range instead of assuming the editor stays on a single port.
- The live pass runner now supports named profiles such as `core`, `advanced`, `graphics`, `ui`, `lighting`, `terrain`, and `heavy`.
- `--prepare-scene save|discard` lets mutating validation steps start from a clean scene on purpose instead of failing halfway through a run.
- `--debug` records per-step timings, raw MCP payloads, and Unity console snapshots for failed steps.
- `--report-file` writes the full run report to disk for later inspection.
- `workflow audit-advanced` now performs disposable scene and asset probes for broader advanced-category coverage, then resets the scene and deletes generated assets.
