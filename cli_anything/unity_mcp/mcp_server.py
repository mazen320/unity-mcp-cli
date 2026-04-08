from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .core.embedded_cli import EmbeddedCLIOptions
from .core.mcp_tools import execute_mcp_tool, iter_mcp_tools


DEFAULT_PROTOCOL_VERSION = "2025-06-18"


@dataclass
class JSONRPCError(Exception):
    code: int
    message: str
    data: Any | None = None


class StdioMessageStream:
    def __init__(self) -> None:
        self.input_mode = "newline"

    def read_message(self) -> dict[str, Any] | None:
        first_line = sys.stdin.buffer.readline()
        if not first_line:
            return None
        if not first_line.strip():
            return self.read_message()

        if first_line.lower().startswith(b"content-length:"):
            self.input_mode = "content-length"
            content_length = self._parse_content_length(first_line)
            while True:
                header_line = sys.stdin.buffer.readline()
                if not header_line:
                    raise JSONRPCError(-32700, "Unexpected end of stream while reading headers.")
                if header_line in {b"\n", b"\r\n"}:
                    break
            raw = sys.stdin.buffer.read(content_length)
        else:
            self.input_mode = "newline"
            raw = first_line.strip()

        try:
            message = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive parsing guard
            raise JSONRPCError(-32700, "Invalid JSON payload.", data=str(exc)) from exc
        if not isinstance(message, dict):
            raise JSONRPCError(-32600, "MCP requests must be JSON-RPC objects.")
        return message

    def write_message(self, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if self.input_mode == "content-length":
            sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii"))
            sys.stdout.buffer.write(raw)
        else:
            sys.stdout.buffer.write(raw + b"\n")
        sys.stdout.buffer.flush()

    @staticmethod
    def _parse_content_length(header_line: bytes) -> int:
        try:
            return int(header_line.decode("ascii").split(":", 1)[1].strip())
        except (IndexError, ValueError) as exc:  # pragma: no cover - defensive parsing guard
            raise JSONRPCError(-32600, "Malformed Content-Length header.") from exc


class UnityThinMCPServer:
    def __init__(self, options: EmbeddedCLIOptions) -> None:
        self.options = options
        self.stream = StdioMessageStream()

    def serve_forever(self) -> None:
        while True:
            request: dict[str, Any] | None = None
            try:
                request = self.stream.read_message()
                if request is None:
                    return
                response = self._handle_request(request)
            except JSONRPCError as exc:
                request_id = request.get("id") if isinstance(request, dict) else None
                if request_id is not None:
                    self.stream.write_message(
                        self._error_response(request_id, exc.code, exc.message, exc.data)
                    )
                continue
            except Exception as exc:  # pragma: no cover - defensive server guard
                request_id = request.get("id") if isinstance(request, dict) else None
                if request_id is not None:
                    self.stream.write_message(
                        self._error_response(request_id, -32603, "Internal server error.", str(exc))
                    )
                continue

            if response is not None:
                self.stream.write_message(response)

    def _handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if request.get("jsonrpc") != "2.0":
            raise JSONRPCError(-32600, "Expected `jsonrpc` to be `2.0`.")
        method = request.get("method")
        if not isinstance(method, str):
            raise JSONRPCError(-32600, "Missing JSON-RPC method name.")
        params = request.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise JSONRPCError(-32602, "`params` must be a JSON object.")

        if method == "notifications/initialized":
            return None

        result = self._dispatch(method, params)
        if "id" not in request:
            return None
        return {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": result,
        }

    def _dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            requested_version = params.get("protocolVersion")
            return {
                "protocolVersion": str(requested_version or DEFAULT_PROTOCOL_VERSION),
                "capabilities": {
                    "tools": {
                        "listChanged": False,
                    }
                },
                "serverInfo": {
                    "name": "unity-mcp-cli-thin",
                    "version": __version__,
                },
                "instructions": (
                    "Thin MCP adapter for unity-mcp-cli. It exposes a curated high-level tool set "
                    "plus a generic unity_tool_call escape hatch instead of mirroring hundreds of tools."
                ),
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": iter_mcp_tools()}
        if method == "tools/call":
            tool_name = params.get("name")
            if not isinstance(tool_name, str) or not tool_name.strip():
                raise JSONRPCError(-32602, "`tools/call` requires a string `name`.")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise JSONRPCError(-32602, "`arguments` must be a JSON object.")
            try:
                result = execute_mcp_tool(tool_name.strip(), arguments, self.options)
            except Exception as exc:
                return {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                    "structuredContent": {"error": str(exc)},
                }
            return {
                "content": [{"type": "text", "text": self._stringify_result(result)}],
                "isError": False,
                "structuredContent": self._normalize_structured_content(result),
            }
        if method == "resources/list":
            return {"resources": []}
        if method == "prompts/list":
            return {"prompts": []}
        raise JSONRPCError(-32601, f"Unsupported MCP method `{method}`.")

    @staticmethod
    def _normalize_structured_content(result: Any) -> dict[str, Any]:
        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            return {"items": result}
        return {"value": result}

    @staticmethod
    def _stringify_result(result: Any) -> str:
        if isinstance(result, str):
            return result
        return json.dumps(result, indent=2, ensure_ascii=True)

    @staticmethod
    def _error_response(request_id: Any, code: int, message: str, data: Any | None = None) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }
        if data is not None:
            payload["error"]["data"] = data
        return payload


def parse_args(argv: list[str] | None = None) -> EmbeddedCLIOptions:
    parser = argparse.ArgumentParser(
        prog="cli-anything-unity-mcp-mcp",
        description="Thin MCP adapter for unity-mcp-cli with a curated Unity tool surface.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Unity bridge host.")
    parser.add_argument("--default-port", type=int, default=7890, help="Fallback Unity bridge port.")
    parser.add_argument("--registry-path", type=Path, default=None, help="Override the Unity instance registry path.")
    parser.add_argument("--session-path", type=Path, default=None, help="Override the CLI session state path.")
    parser.add_argument("--port-range-start", type=int, default=7890, help="First port to scan when discovering Unity instances.")
    parser.add_argument("--port-range-end", type=int, default=7899, help="Last port to scan when discovering Unity instances.")
    parser.add_argument("--agent-id", default="cli-anything-unity-mcp-mcp", help="Agent identifier used in queue headers.")
    parser.add_argument("--legacy", action="store_true", help="Bypass queue mode and use legacy direct POST requests.")
    ns = parser.parse_args(argv)
    return EmbeddedCLIOptions(
        host=ns.host,
        default_port=ns.default_port,
        registry_path=ns.registry_path,
        session_path=ns.session_path,
        port_range_start=ns.port_range_start,
        port_range_end=ns.port_range_end,
        agent_id=ns.agent_id,
        legacy=ns.legacy,
    )


def main(argv: list[str] | None = None) -> int:
    options = parse_args(argv)
    server = UnityThinMCPServer(options)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
