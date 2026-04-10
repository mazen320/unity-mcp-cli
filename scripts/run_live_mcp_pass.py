from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable


FULL_ADVANCED_AUDIT_CATEGORIES = [
    "memory",
    "graphics",
    "physics",
    "profiler",
    "sceneview",
    "settings",
    "testing",
    "ui",
    "audio",
    "lighting",
    "animation",
    "input",
    "shadergraph",
    "terrain",
    "navmesh",
]


PASS_PROFILES: dict[str, dict[str, Any]] = {
    "core": {
        "advancedCategory": "graphics",
        "toolInfoTool": "unity_scene_stats",
        "toolCallTool": "unity_scene_stats",
        "toolCallParams": {},
        "auditCategories": ["graphics", "physics", "sceneview", "settings"],
    },
    "advanced": {
        "advancedCategory": "graphics",
        "toolInfoTool": "unity_scene_stats",
        "toolCallTool": "unity_scene_stats",
        "toolCallParams": {},
        "auditCategories": list(FULL_ADVANCED_AUDIT_CATEGORIES),
    },
    "graphics": {
        "advancedCategory": "graphics",
        "toolInfoTool": "unity_scene_stats",
        "toolCallTool": "unity_scene_stats",
        "toolCallParams": {},
        "auditCategories": ["graphics", "lighting", "sceneview", "shadergraph", "profiler"],
    },
    "ui": {
        "advancedCategory": "ui",
        "toolInfoTool": "unity_ui_info",
        "toolCallTool": "unity_ui_info",
        "toolCallParams": {},
        "auditCategories": ["ui", "input", "graphics"],
    },
    "lighting": {
        "advancedCategory": "lighting",
        "toolInfoTool": "unity_lighting_info",
        "toolCallTool": "unity_lighting_info",
        "toolCallParams": {},
        "auditCategories": ["lighting", "graphics", "sceneview"],
    },
    "terrain": {
        "advancedCategory": "terrain",
        "toolInfoTool": "unity_terrain_info",
        "toolCallTool": "unity_terrain_info",
        "toolCallParams": {},
        "auditCategories": ["terrain", "lighting", "navmesh"],
    },
    "heavy": {
        "advancedCategory": "terrain",
        "toolInfoTool": "unity_terrain_info",
        "toolCallTool": "unity_terrain_info",
        "toolCallParams": {},
        "auditCategories": list(FULL_ADVANCED_AUDIT_CATEGORIES),
    },
}


def _build_profile_plan(profile: str, include_heavy: bool = False) -> dict[str, Any]:
    if profile not in PASS_PROFILES:
        raise ValueError(f"Unknown profile: {profile}")
    plan = dict(PASS_PROFILES[profile])
    plan["name"] = profile
    if include_heavy:
        expanded = list(dict.fromkeys(list(plan["auditCategories"]) + list(FULL_ADVANCED_AUDIT_CATEGORIES)))
        plan["auditCategories"] = expanded
    return plan


def _default_report_file(runtime_dir: Path, profile: str, timestamp: str | None = None) -> Path:
    stamp = timestamp or time.strftime("%Y%m%d-%H%M%S")
    return runtime_dir / f"live-pass-{profile}-{stamp}.json"


def _compact_text(value: Any, limit: int = 220) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        try:
            value = json.dumps(value, separators=(",", ":"), ensure_ascii=True)
        except TypeError:
            value = str(value)
    text = " ".join(value.strip().split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _truthy_nested_flag(value: Any, flag_name: str) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == flag_name and bool(item):
                return True
            if _truthy_nested_flag(item, flag_name):
                return True
    if isinstance(value, list):
        return any(_truthy_nested_flag(item, flag_name) for item in value)
    return False


def _as_port(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _find_observed_port(value: Any) -> int | None:
    if isinstance(value, dict):
        for key in ("selectedPort", "activePort", "targetPort", "finalPort"):
            port = _as_port(value.get(key))
            if port is not None:
                return port

        for key in ("selectedInstance", "instance", "activeInstance"):
            port = _find_observed_port(value.get(key))
            if port is not None:
                return port

        instances = value.get("instances")
        if isinstance(instances, list):
            for instance in instances:
                if isinstance(instance, dict) and bool(instance.get("isSelected")):
                    port = _as_port(instance.get("port"))
                    if port is not None:
                        return port

        for key in ("summary", "result"):
            port = _find_observed_port(value.get(key))
            if port is not None:
                return port

        port = _as_port(value.get("port"))
        if port is not None:
            return port

    if isinstance(value, list):
        for item in value:
            port = _find_observed_port(item)
            if port is not None:
                return port
    return None


def _step_observed_port(step: dict[str, Any]) -> int | None:
    for key in ("result", "raw"):
        port = _find_observed_port(step.get(key))
        if port is not None:
            return port
    return None


def _step_timed_out(step: dict[str, Any]) -> bool:
    return _truthy_nested_flag(step.get("result"), "timedOut") or _truthy_nested_flag(step.get("raw"), "timedOut")


def _extract_failure_detail(step: dict[str, Any]) -> str:
    result = step.get("result")
    raw = step.get("raw")
    for container in (result, raw):
        if isinstance(container, dict):
            for key in ("error", "message", "detail", "diagnosis"):
                text = _compact_text(container.get(key))
                if text:
                    return text
            content = container.get("content")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        text = _compact_text(item.get("text"))
                        if text:
                            return text
    if _step_timed_out(step):
        return "Timed out."
    return "Step reported failure without a structured error."


def _summarize_console_snapshot(snapshot: dict[str, Any] | None) -> str | None:
    if not snapshot:
        return None
    if snapshot.get("status") == "failed":
        return _compact_text(snapshot.get("error") or "Console snapshot failed.")

    result = snapshot.get("result")
    if not isinstance(result, dict):
        return None
    entries = result.get("entries") or result.get("items") or result.get("messages") or result.get("logs")
    if isinstance(entries, list) and entries:
        first = entries[0]
        if isinstance(first, dict):
            level = _compact_text(first.get("type") or first.get("level") or first.get("logType"), limit=32)
            message = _compact_text(first.get("message") or first.get("text") or first.get("condition"))
            if level and message:
                return f"{level}: {message}"
            if message:
                return message
        return _compact_text(first)
    for key in ("errorCount", "warningCount", "count"):
        if key in result:
            return f"console {key}: {result[key]}"
    return None


def _detect_port_hops(steps: list[dict[str, Any]], initial_port: int | None) -> list[dict[str, Any]]:
    hops: list[dict[str, Any]] = []
    previous = initial_port
    for step in steps:
        observed = _step_observed_port(step)
        if observed is None:
            continue
        if previous is not None and observed != previous:
            hops.append(
                {
                    "step": step.get("name"),
                    "from": previous,
                    "to": observed,
                }
            )
        previous = observed
    return hops


def _port_option(port: int | None) -> str:
    return f" --port {port}" if port is not None else " --port <port>"


def _dedupe_commands(commands: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for command in commands:
        if command in seen:
            continue
        seen.add(command)
        unique.append(command)
    return unique


def _paren_value(step_name: str, prefix: str) -> str | None:
    if not step_name.startswith(prefix) or not step_name.endswith(")"):
        return None
    value = step_name[len(prefix) : -1].strip()
    return value or None


def _recommend_live_pass_commands(step: dict[str, Any], port: int | None) -> list[str]:
    step_name = str(step.get("name") or "")
    port_suffix = _port_option(port)
    commands: list[str] = []

    tool_call_name = _paren_value(step_name, "unity_tool_call(")
    tool_info_name = _paren_value(step_name, "unity_tool_info(")
    advanced_category = _paren_value(step_name, "unity_advanced_tools(")
    if step_name == "unity_inspect":
        commands.append(f"cli-anything-unity-mcp --json workflow inspect{port_suffix}")
    elif step_name == "unity_console":
        commands.append(f"cli-anything-unity-mcp --json console --count 80 --type error{port_suffix}")
    elif step_name == "unity_validate_scene":
        commands.append(f"cli-anything-unity-mcp --json workflow validate-scene --include-hierarchy{port_suffix}")
    elif step_name.startswith("unity_play("):
        commands.append(f"cli-anything-unity-mcp --json play stop{port_suffix}")
    elif step_name == "unity_reset_scene" or step_name.startswith("prepare_scene") or step_name == "prepare_audit_scene":
        commands.append(f"cli-anything-unity-mcp --json workflow reset-scene --discard-unsaved{port_suffix}")
    elif step_name.startswith("unity_audit_advanced"):
        commands.append(f"cli-anything-unity-mcp --json workflow audit-advanced{port_suffix}")
    elif tool_call_name:
        commands.append(f"cli-anything-unity-mcp --json tool-info {tool_call_name}{port_suffix}")
        commands.append(f"cli-anything-unity-mcp --json tool {tool_call_name}{port_suffix}")
    elif tool_info_name:
        commands.append(f"cli-anything-unity-mcp --json tool-info {tool_info_name}{port_suffix}")
    elif advanced_category:
        commands.append(f"cli-anything-unity-mcp --json advanced-tools --category {advanced_category}{port_suffix}")
    elif step_name in {"unity_instances", "unity_select_instance", "tools/list"}:
        commands.append("cli-anything-unity-mcp --json instances")

    commands.extend(
        [
            f"cli-anything-unity-mcp --json debug doctor --recent-commands 8{port_suffix}",
            f"cli-anything-unity-mcp --json debug trace --summary --status error --tail 20{port_suffix}",
            f"cli-anything-unity-mcp --json console --count 80 --type error{port_suffix}",
        ]
    )
    return _dedupe_commands(commands)


def _summarize_live_pass_report(report: dict[str, Any]) -> dict[str, Any]:
    steps = [step for step in report.get("steps", []) if isinstance(step, dict)]
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    failed_steps: list[dict[str, Any]] = []
    timed_out_count = 0
    initial_port = _as_port(summary.get("port"))
    for step in steps:
        timed_out = _step_timed_out(step)
        if timed_out:
            timed_out_count += 1
        if step.get("status") == "failed" or timed_out:
            observed_port = _step_observed_port(step) or initial_port
            failed_step = {
                "name": step.get("name"),
                "status": "timed-out" if timed_out else step.get("status", "failed"),
                "durationMs": step.get("durationMs"),
                "detail": _extract_failure_detail(step),
                "recommendedCommands": _recommend_live_pass_commands(step, observed_port),
            }
            console_summary = _summarize_console_snapshot(step.get("consoleSnapshot"))
            if console_summary:
                failed_step["consoleSummary"] = console_summary
            failed_steps.append(failed_step)

    timed_steps = [
        {"name": step.get("name"), "durationMs": step.get("durationMs")}
        for step in steps
        if _step_timed_out(step)
    ]
    slowest_steps = sorted(
        (
            {
                "name": step.get("name"),
                "status": step.get("status"),
                "durationMs": float(step.get("durationMs") or 0.0),
            }
            for step in steps
            if isinstance(step.get("durationMs"), (int, float))
        ),
        key=lambda item: item["durationMs"],
        reverse=True,
    )[:5]
    recommended_commands = _dedupe_commands(
        [
            command
            for failed_step in failed_steps
            for command in failed_step.get("recommendedCommands", [])
        ]
    )
    return {
        "totalSteps": len(steps),
        "passed": int(summary.get("passed") or sum(1 for step in steps if step.get("status") == "passed")),
        "failed": int(summary.get("failed") or sum(1 for step in steps if step.get("status") == "failed")),
        "timedOut": timed_out_count,
        "profile": summary.get("profile"),
        "port": initial_port,
        "reportFile": summary.get("reportFile"),
        "failedSteps": failed_steps,
        "timedOutSteps": timed_steps,
        "portHops": _detect_port_hops(steps, initial_port),
        "slowestSteps": slowest_steps,
        "recommendedCommands": recommended_commands,
    }


def _format_live_pass_summary(report: dict[str, Any], *, failures_only: bool = False) -> str:
    live_summary = report.get("liveSummary")
    if not isinstance(live_summary, dict):
        live_summary = _summarize_live_pass_report(report)

    profile = live_summary.get("profile") or "unknown"
    port = live_summary.get("port") if live_summary.get("port") is not None else "auto"
    lines = [
        "Unity MCP Live Pass",
        (
            f"Profile: {profile} | port: {port} | steps: {live_summary['totalSteps']} | "
            f"passed: {live_summary['passed']} | failed: {live_summary['failed']} | "
            f"timed out: {live_summary['timedOut']}"
        ),
    ]
    if live_summary.get("reportFile"):
        lines.append(f"Report: {live_summary['reportFile']}")

    lines.extend(["", "Failures And Timeouts"])
    failed_steps = live_summary.get("failedSteps") or []
    if failed_steps:
        for step in failed_steps:
            duration = step.get("durationMs")
            duration_suffix = f" in {duration}ms" if duration is not None else ""
            lines.append(f"- {step.get('name')} [{step.get('status')}]{duration_suffix}: {step.get('detail')}")
            if step.get("consoleSummary"):
                lines.append(f"  console: {step['consoleSummary']}")
            recommended = step.get("recommendedCommands") or []
            if recommended:
                lines.append(f"  next: {recommended[0]}")
    else:
        lines.append("- none")

    lines.extend(["", "Port Hops"])
    port_hops = live_summary.get("portHops") or []
    if port_hops:
        for hop in port_hops:
            lines.append(f"- {hop.get('from')} -> {hop.get('to')} during {hop.get('step')}")
    else:
        lines.append("- none")

    if not failures_only:
        lines.extend(["", "Slowest Steps"])
        slowest_steps = live_summary.get("slowestSteps") or []
        if slowest_steps:
            for step in slowest_steps:
                lines.append(f"- {step.get('name')} [{step.get('status')}] {step.get('durationMs')}ms")
        else:
            lines.append("- none")
        lines.extend(["", "Tip: use --json for the full report or --debug --report-file <path> to save raw MCP payloads."])
    return "\n".join(lines)


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
    parser.add_argument(
        "--profile",
        choices=sorted(PASS_PROFILES.keys()),
        default="core",
        help="Named pass profile to run. Use focused profiles like ui, lighting, or terrain for category-specific validation.",
    )
    parser.add_argument(
        "--include-heavy",
        action="store_true",
        help="Expand the chosen profile to run the broadest advanced-audit category set.",
    )
    parser.add_argument(
        "--prepare-scene",
        choices=("strict", "save", "discard"),
        default="strict",
        help="How to handle a dirty scene before mutating validation steps. `strict` leaves the scene untouched, `save` saves and reloads it, and `discard` reloads without saving.",
    )
    parser.add_argument("--debug", action="store_true", help="Include raw step payloads, timings, and failure console snapshots.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop at the first failing step.")
    parser.add_argument("--console-snapshot-count", type=int, default=20, help="How many Unity console entries to fetch when a step fails.")
    parser.add_argument("--report-file", type=Path, default=None, help="Optional path to write the pass report JSON.")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="In text mode, print only counts, failures/timeouts, and Unity bridge port hops.",
    )
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
    profile_plan = _build_profile_plan(args.profile, args.include_heavy)
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
            f"unity_advanced_tools({profile_plan['advancedCategory']})",
            lambda: client.tool_call(
                "unity_advanced_tools",
                adaptive_tool_args(category=profile_plan["advancedCategory"]),
            ),
        )
        record(
            f"unity_tool_info({profile_plan['toolInfoTool']})",
            lambda: client.tool_call(
                "unity_tool_info",
                adaptive_tool_args(toolName=profile_plan["toolInfoTool"]),
            ),
        )
        record(
            f"unity_tool_call({profile_plan['toolCallTool']})",
            lambda: client.tool_call(
                "unity_tool_call",
                adaptive_tool_args(
                    toolName=profile_plan["toolCallTool"],
                    params=profile_plan["toolCallParams"],
                ),
            ),
        )
        if args.prepare_scene != "strict":
            record(
                f"prepare_scene({args.prepare_scene})",
                lambda: client.tool_call(
                    "unity_reset_scene",
                    adaptive_tool_args(
                        saveIfDirty=args.prepare_scene == "save",
                        discardUnsaved=args.prepare_scene == "discard",
                    ),
                ),
            )
        record(
            "prepare_audit_scene",
            lambda: client.tool_call(
                "unity_reset_scene",
                adaptive_tool_args(saveIfDirty=True),
            ),
        )
        record(
            f"unity_audit_advanced({profile_plan['name']})",
            lambda: client.tool_call(
                "unity_audit_advanced",
                adaptive_tool_args(
                    categories=profile_plan["auditCategories"],
                    saveIfDirtyStart=True,
                ),
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
                "profile": profile_plan["name"],
                "includeHeavy": bool(args.include_heavy),
                "prepareScene": args.prepare_scene,
                "debug": bool(args.debug),
            },
        }
    finally:
        client.close()


def main() -> int:
    args = _parse_args()
    runtime_dir = Path(__file__).resolve().parents[1] / ".cli-anything-unity-mcp"
    report_file = args.report_file or (_default_report_file(runtime_dir, args.profile) if args.debug else None)
    result = _run_pass(args)
    if report_file:
        result["summary"]["reportFile"] = str(report_file)
    result["liveSummary"] = _summarize_live_pass_report(result)
    if report_file:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")
    if args.json:
        print(json.dumps(result, separators=(",", ":"), ensure_ascii=True))
    else:
        print(_format_live_pass_summary(result, failures_only=args.summary_only))
    return 0 if result["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
