# Test Plan

Unit coverage:
- Route mapping for generic `tool` calls and irregular override cases.
- Session persistence and command history trimming.
- Instance discovery behavior for single-instance auto-select and multi-instance selection requirements.
- Selected-project recovery when the Unity bridge disappears and comes back on a new port.

End-to-end coverage:
- Run the installed `cli-anything-unity-mcp` entry point in subprocess mode.
- Exercise `instances`, `select`, `scene-info`, `tool unity_execute_code`, and REPL-default behavior against a mock Unity bridge server.
- Exercise the higher-level workflow layer:
  - `workflow inspect`
  - `workflow build-sample`
  - `workflow build-fps-sample`
  - `workflow audit-advanced`
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
python .\scripts\run_live_mcp_pass.py --port 7891
```
