from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a repeatable live pass against the thin unity-mcp-cli MCP adapter.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Unity bridge host.")
    parser.add_argument("--port", type=int, default=7891, help="Unity bridge port to target.")
    parser.add_argument(
        "--port-range-start",
        type=int,
        default=7890,
        help="Start of the Unity bridge discovery range used by the embedded MCP server.",
    )
    parser.add_argument(
        "--port-range-end",
        type=int,
        default=7899,
        help="End of the Unity bridge discovery range used by the embedded MCP server.",
    )
    parser.add_argument("--registry-path", type=Path, default=None, help="Optional Unity instance registry path.")
    parser.add_argument("--session-path", type=Path, default=None, help="Optional session path for the pass.")
    parser.add_argument("--include-heavy", action="store_true", help="Include the heavier FPS-scene generation pass.")
    parser.add_argument("--debug", action="store_true", help="Include raw step payloads, timings, and failure console snapshots.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop at the first failing step.")
    parser.add_argument("--console-snapshot-count", type=int, default=20, help="How many Unity console entries to fetch when a step fails.")
    parser.add_argument("--report-file", type=Path, default=None, help="Optional path to write the pass report JSON.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    return parser.parse_args()


class MCPClientProcess:
    def __init__(self, command: list[str]) -> None:
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        self._next_id = 1

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params or {},
        }
        self._next_id += 1
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"MCP server did not respond.\nSTDERR:\n{stderr}")
        response = json.loads(line)
        if "error" in response:
            raise RuntimeError(f"MCP error: {response['error']}")
        return response["result"]

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        assert self.process.stdin is not None
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()

    def tool_call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.call("tools/call", {"name": name, "arguments": arguments or {}})


def _run_pass(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    runtime_dir = repo_root / ".cli-anything-unity-mcp"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    session_path = args.session_path or (runtime_dir / "live-pass-session.json")
    command = [
        sys.executable,
        "-m",
        "cli_anything.unity_mcp.mcp_server",
        "--host",
        args.host,
        "--default-port",
        str(args.port),
        "--port-range-start",
        str(args.port_range_start),
        "--port-range-end",
        str(args.port_range_end),
        "--session-path",
        str(session_path),
    ]
    if args.registry_path:
        command.extend(["--registry-path", str(args.registry_path)])

    client = MCPClientProcess(command)
    try:
        initialize = client.call(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "live-pass", "version": "1.0"},
            },
        )
        client.notify("notifications/initialized", {})

        steps: list[dict[str, Any]] = []

        def tool_args(**values: Any) -> dict[str, Any]:
            return {key: value for key, value in values.items() if value is not None}

        def adaptive_tool_args(**values: Any) -> dict[str, Any]:
            payload = tool_args(**values)
            payload.pop("port", None)
            return payload

        def step_failed(call: dict[str, Any], structured: dict[str, Any]) -> bool:
            if bool(call.get("isError")):
                return True
            return bool(structured.get("timedOut"))

        def fetch_console_snapshot() -> dict[str, Any] | None:
            try:
                result = client.tool_call(
                    "unity_console",
                    adaptive_tool_args(count=args.console_snapshot_count),
                )
            except Exception as exc:  # pragma: no cover - defensive live debug helper
                return {"status": "failed", "error": str(exc)}
            return {
                "status": "passed" if not result.get("isError") else "failed",
                "result": result.get("structuredContent", {}),
            }

        def record(name: str, action: Callable[[], dict[str, Any]]) -> None:
            started = time.perf_counter()
            try:
                call = action()
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                structured = call.get("structuredContent", {})
                is_error = step_failed(call, structured)
                step = {
                    "name": name,
                    "status": "failed" if is_error else "passed",
                    "durationMs": duration_ms,
                    "result": structured,
                }
                if args.debug:
                    step["raw"] = call
                if is_error and name != "unity_console":
                    step["consoleSnapshot"] = fetch_console_snapshot()
                steps.append(step)
                if is_error and args.fail_fast:
                    raise RuntimeError(f"Step `{name}` failed.")
            except Exception as exc:
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                step = {
                    "name": name,
                    "status": "failed",
                    "durationMs": duration_ms,
                    "result": {"error": str(exc)},
                }
                if name != "unity_console":
                    step["consoleSnapshot"] = fetch_console_snapshot()
                steps.append(step)
                if args.fail_fast:
                    raise

        tools = client.call("tools/list")
        steps.append(
            {
                "name": "tools/list",
                "status": "passed",
                "toolCount": len(tools.get("tools", [])),
                "durationMs": 0.0,
            }
        )

        record("unity_instances", lambda: client.tool_call("unity_instances"))
        record("unity_select_instance", lambda: client.tool_call("unity_select_instance", tool_args(port=args.port)))
        record("unity_inspect", lambda: client.tool_call("unity_inspect", adaptive_tool_args(assetLimit=3)))
        record("unity_console", lambda: client.tool_call("unity_console", adaptive_tool_args(count=10)))
        record("unity_validate_scene", lambda: client.tool_call("unity_validate_scene", adaptive_tool_args()))
        record(
            "unity_advanced_tools",
            lambda: client.tool_call("unity_advanced_tools", adaptive_tool_args(category="graphics")),
        )
        record(
            "unity_tool_info",
            lambda: client.tool_call("unity_tool_info", adaptive_tool_args(toolName="unity_scene_stats")),
        )
        record(
            "unity_tool_call",
            lambda: client.tool_call(
                "unity_tool_call",
                adaptive_tool_args(toolName="unity_scene_stats", params={}),
            ),
        )
        record(
            "unity_build_sample",
            lambda: client.tool_call(
                "unity_build_sample",
                adaptive_tool_args(
                    name="McpLivePassArena",
                    cleanup=True,
                    capture="none",
                    playCheck=False,
                ),
            ),
        )
        record(
            "unity_audit_advanced",
            lambda: client.tool_call(
                "unity_audit_advanced",
                adaptive_tool_args(categories=["graphics", "physics", "sceneview", "settings"]),
            ),
        )
        record(
            "unity_play(play)",
            lambda: client.tool_call("unity_play", adaptive_tool_args(action="play", wait=True)),
        )
        record(
            "unity_play(stop)",
            lambda: client.tool_call("unity_play", adaptive_tool_args(action="stop", wait=True)),
        )
        record(
            "unity_reset_scene",
            lambda: client.tool_call("unity_reset_scene", adaptive_tool_args(discardUnsaved=True)),
        )

        if args.include_heavy:
            record(
                "unity_build_fps_sample",
                lambda: client.tool_call(
                    "unity_build_fps_sample",
                    adaptive_tool_args(
                        name="McpLiveFpsPass",
                        scenePath="Assets/Scenes/McpLiveFpsPass.unity",
                        folder="Assets/CodexSamples/McpLiveFpsPass",
                        replace=True,
                        verifyLevel="quick",
                        playCheck=False,
                        capture="none",
                    ),
                ),
            )

        passed = sum(1 for step in steps if step["status"] == "passed")
        failed = sum(1 for step in steps if step["status"] == "failed")
        return {
            "initialize": initialize,
            "steps": steps,
            "summary": {
                "repoRoot": str(repo_root),
                "port": args.port,
                "portRangeStart": args.port_range_start,
                "portRangeEnd": args.port_range_end,
                "sessionPath": str(session_path),
                "passed": passed,
                "failed": failed,
                "includeHeavy": bool(args.include_heavy),
                "debug": bool(args.debug),
            },
        }
    finally:
        client.close()


def main() -> int:
    args = _parse_args()
    result = _run_pass(args)
    if args.report_file:
        args.report_file.parent.mkdir(parents=True, exist_ok=True)
        args.report_file.write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")
    if args.json:
        print(json.dumps(result, separators=(",", ":"), ensure_ascii=True))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
