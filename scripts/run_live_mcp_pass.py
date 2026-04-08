from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a repeatable live pass against the thin unity-mcp-cli MCP adapter.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Unity bridge host.")
    parser.add_argument("--port", type=int, default=7891, help="Unity bridge port to target.")
    parser.add_argument("--registry-path", type=Path, default=None, help="Optional Unity instance registry path.")
    parser.add_argument("--session-path", type=Path, default=None, help="Optional session path for the pass.")
    parser.add_argument("--include-heavy", action="store_true", help="Include the heavier FPS-scene generation pass.")
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
        str(args.port),
        "--port-range-end",
        str(args.port),
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

        def record(name: str, call: dict[str, Any]) -> None:
            is_error = bool(call.get("isError"))
            structured = call.get("structuredContent", {})
            steps.append(
                {
                    "name": name,
                    "status": "failed" if is_error else "passed",
                    "result": structured,
                }
            )

        tools = client.call("tools/list")
        steps.append(
            {
                "name": "tools/list",
                "status": "passed",
                "toolCount": len(tools.get("tools", [])),
            }
        )

        record("unity_instances", client.tool_call("unity_instances"))
        record("unity_select_instance", client.tool_call("unity_select_instance", {"port": args.port}))
        record("unity_inspect", client.tool_call("unity_inspect", {"port": args.port, "assetLimit": 3}))
        record("unity_console", client.tool_call("unity_console", {"port": args.port, "count": 10}))
        record("unity_validate_scene", client.tool_call("unity_validate_scene", {"port": args.port}))
        record(
            "unity_advanced_tools",
            client.tool_call("unity_advanced_tools", {"port": args.port, "category": "graphics"}),
        )
        record(
            "unity_tool_info",
            client.tool_call("unity_tool_info", {"port": args.port, "toolName": "unity_scene_stats"}),
        )
        record(
            "unity_tool_call",
            client.tool_call(
                "unity_tool_call",
                {"port": args.port, "toolName": "unity_scene_stats", "params": {}},
            ),
        )
        record(
            "unity_build_sample",
            client.tool_call(
                "unity_build_sample",
                {
                    "port": args.port,
                    "name": "McpLivePassArena",
                    "cleanup": True,
                    "capture": "none",
                    "playCheck": False,
                },
            ),
        )
        record(
            "unity_audit_advanced",
            client.tool_call(
                "unity_audit_advanced",
                {
                    "port": args.port,
                    "categories": ["graphics", "physics", "sceneview", "settings"],
                },
            ),
        )
        record("unity_play(play)", client.tool_call("unity_play", {"port": args.port, "action": "play", "wait": True}))
        record("unity_play(stop)", client.tool_call("unity_play", {"port": args.port, "action": "stop", "wait": True}))
        record(
            "unity_reset_scene",
            client.tool_call("unity_reset_scene", {"port": args.port, "discardUnsaved": True}),
        )

        if args.include_heavy:
            record(
                "unity_build_fps_sample",
                client.tool_call(
                    "unity_build_fps_sample",
                    {
                        "port": args.port,
                        "name": "McpLiveFpsPass",
                        "scenePath": "Assets/Scenes/McpLiveFpsPass.unity",
                        "folder": "Assets/CodexSamples/McpLiveFpsPass",
                        "replace": True,
                        "verifyLevel": "quick",
                        "playCheck": False,
                        "capture": "none",
                    },
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
                "sessionPath": str(session_path),
                "passed": passed,
                "failed": failed,
                "includeHeavy": bool(args.include_heavy),
            },
        }
    finally:
        client.close()


def main() -> int:
    args = _parse_args()
    result = _run_pass(args)
    if args.json:
        print(json.dumps(result, separators=(",", ":"), ensure_ascii=True))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
