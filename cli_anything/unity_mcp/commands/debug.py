from __future__ import annotations

import base64
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
from click.core import ParameterSource

from ._shared import (
    BackendSelectionError,
    DashboardConfig,
    UnityMCPClientError,
    _describe_cli_activity,
    _detect_and_learn_fixes,
    _normalized_command_path,
    _run_and_emit,
    _serialize_agent_profile,
    format_output,
    memory_for_session,
    route_to_tool_name,
    serve_debug_dashboard,
    build_debug_doctor_report,
)


# ─── Trace helper functions ────────────────────────────────────────────────────

def _filter_history_entries(
    history: list[dict[str, Any]],
    *,
    tail: int | None = None,
    status: str | None = None,
    command_contains: str | None = None,
    agent_id: str | None = None,
) -> list[dict[str, Any]]:
    filtered = list(history)
    if status:
        filtered = [entry for entry in filtered if str(entry.get("status") or "ok").lower() == status.lower()]
    if command_contains:
        needle = command_contains.lower()
        filtered = [entry for entry in filtered if needle in str(entry.get("command") or "").lower()]
    if agent_id:
        needle = agent_id.lower()
        filtered = [entry for entry in filtered if needle in str(entry.get("agentId") or "").lower()]
    if tail is not None and tail > 0:
        filtered = filtered[-tail:]
    return filtered


def _filter_rendered_trace_entries(
    entries: list[dict[str, Any]],
    *,
    category: str | None = None,
    route_name: str | None = None,
    tool_name: str | None = None,
) -> list[dict[str, Any]]:
    filtered = list(entries)
    if category:
        needle = category.strip().lower()
        filtered = [
            entry for entry in filtered if needle in str(entry.get("category") or "").strip().lower()
        ]
    if route_name:
        needle = route_name.strip().lower()
        filtered = [
            entry for entry in filtered if needle in str(entry.get("routeName") or "").strip().lower()
        ]
    if tool_name:
        needle = tool_name.strip().lower()
        filtered = [
            entry for entry in filtered if needle in str(entry.get("toolName") or "").strip().lower()
        ]
    return filtered


def _basenameish(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").rstrip("/")
    if not normalized:
        return ""
    return normalized.rsplit("/", 1)[-1]


def _trace_target_from_args(command: str, args: dict[str, Any]) -> str | None:
    if not isinstance(args, dict):
        return None

    for key in (
        "path",
        "scenePath",
        "assetPath",
        "prefabPath",
        "gameObjectPath",
        "objectPath",
        "folder",
        "directory",
        "name",
        "menuItem",
        "tool",
        "category",
    ):
        value = args.get(key)
        if value in (None, ""):
            continue
        if key in {"path", "scenePath", "assetPath", "prefabPath", "folder", "directory"}:
            return _basenameish(str(value))
        return str(value)

    if command == "editor/play-mode":
        action = str(args.get("action") or "").strip().lower()
        if action:
            return action
    return None


def _trace_amount_from_args(args: dict[str, Any]) -> str | None:
    if not isinstance(args, dict):
        return None
    width = args.get("width")
    height = args.get("height")
    if width is not None and height is not None:
        return f"{width}x{height}"
    count = args.get("count")
    if count is not None:
        return f"{count} items"
    limit = args.get("limit")
    if limit is not None:
        return f"limit {limit}"
    max_nodes = args.get("maxNodes")
    max_depth = args.get("maxDepth")
    if max_nodes is not None and max_depth is not None:
        return f"depth {max_depth}, max {max_nodes} nodes"
    if max_nodes is not None:
        return f"max {max_nodes} nodes"
    if max_depth is not None:
        return f"depth {max_depth}"
    return None


def _trace_phase_and_base_label(command: str, args: dict[str, Any], note: str | None) -> tuple[str, str]:
    normalized = str(command or "").strip().lower()
    action = str((args or {}).get("action") or "").strip().lower()

    if normalized == "debug/breadcrumb":
        return ("log", "Logging Unity breadcrumb")
    if normalized == "ping":
        return ("check", "Checking Unity bridge")
    if normalized == "queue/info":
        return ("check", "Checking Unity queue")
    if normalized == "_meta/routes":
        return ("inspect", "Inspecting bridge routes")
    if normalized == "context":
        return ("inspect", "Inspecting project context")
    if normalized == "editor/state":
        return ("check", "Checking editor state")
    if normalized == "project/info":
        return ("inspect", "Inspecting project info")
    if normalized == "scene/info":
        return ("inspect", "Inspecting scene info")
    if normalized == "scene/hierarchy":
        return ("inspect", "Inspecting scene hierarchy")
    if normalized == "console/log":
        return ("inspect", "Inspecting Unity console")
    if normalized == "compilation/errors":
        return ("check", "Checking compilation errors")
    if normalized == "search/missing-references":
        return ("check", "Checking missing references")
    if normalized == "search/scene-stats":
        return ("inspect", "Inspecting scene stats")
    if normalized == "graphics/game-capture":
        return ("capture", "Capturing Game view")
    if normalized == "graphics/scene-capture":
        return ("capture", "Capturing Scene view")
    if normalized == "scene/save":
        return ("save", "Saving scene")
    if normalized == "scene/open":
        return ("open", "Opening scene")
    if normalized == "editor/play-mode":
        if action == "play":
            return ("play", "Entering play mode")
        if action == "stop":
            return ("play", "Exiting play mode")
        return ("play", "Changing play mode")
    if normalized == "editor/execute-code":
        return ("run", "Running Unity editor code")
    if normalized == "script/read":
        return ("inspect", "Inspecting script")
    if normalized == "script/update":
        return ("edit", "Editing script")
    if normalized == "script/create":
        return ("create", "Creating script")
    if normalized == "script/delete":
        return ("delete", "Deleting script")
    if normalized == "gameobject/info":
        return ("inspect", "Inspecting GameObject")
    if normalized == "gameobject/create":
        return ("create", "Creating GameObject")
    if normalized == "gameobject/update":
        return ("edit", "Editing GameObject")
    if normalized == "gameobject/delete":
        return ("delete", "Deleting GameObject")
    if normalized.startswith("prefab/"):
        if normalized == "prefab/set-object-reference":
            return ("wire", "Wiring object reference")
        if normalized.endswith("/create"):
            return ("create", "Creating prefab")
        if normalized.endswith("/update"):
            return ("edit", "Editing prefab")
        return ("inspect", "Inspecting prefab")
    if normalized.startswith("selection/"):
        return ("inspect", "Inspecting selection")
    if normalized.startswith("build/"):
        return ("build", "Starting build")
    if normalized.startswith("undo/"):
        return ("edit", "Applying undo history change")

    if note:
        return ("run", note)

    category, _, tail = normalized.partition("/")
    if tail.startswith("list") or tail.endswith("info") or tail.endswith("status"):
        return ("inspect", f"Inspecting {normalized}")
    if tail.startswith("create"):
        return ("create", f"Creating {category}")
    if tail.startswith("update") or tail.startswith("set"):
        return ("edit", f"Editing {category}")
    if tail.startswith("delete") or tail.startswith("remove"):
        return ("delete", f"Deleting {category}")
    return ("run", f"Running {normalized}")


def _history_route_name(command: str) -> str | None:
    normalized = str(command or "").strip()
    if not normalized or "/" not in normalized:
        return None
    if normalized in {"cli/progress", "debug/breadcrumb"} or normalized.startswith("_meta/"):
        return None
    return normalized


def _history_tool_name(route_name: str | None) -> str | None:
    if not route_name:
        return None
    try:
        return route_to_tool_name(route_name)
    except ValueError:
        return None


def _history_category_name(route_name: str | None, tool_name: str | None) -> str | None:
    if route_name:
        category, _, _ = route_name.partition("/")
        normalized = category.strip().lower()
        return normalized or None
    if tool_name and tool_name.startswith("unity_"):
        remainder = tool_name[len("unity_"):]
        category, _, _ = remainder.partition("_")
        normalized = category.strip().lower()
        return normalized or None
    return None


def _humanize_history_entry(entry: dict[str, Any]) -> dict[str, Any]:
    payload = dict(entry)
    command = str(payload.get("command") or "")
    args = payload.get("args")
    args = dict(args) if isinstance(args, dict) else {}
    note = str(payload.get("note") or "").strip() or None

    phase, base_label = _trace_phase_and_base_label(command, args, note)
    target = _trace_target_from_args(command, args)
    amount = _trace_amount_from_args(args)
    summary = base_label

    if command == "cli/progress":
        summary = str(args.get("message") or base_label).strip() or base_label
        payload["phase"] = str(args.get("phase") or "run")
        payload["summary"] = summary
        payload["target"] = None
        payload["actor"] = payload.get("agentProfile") or payload.get("agentId") or payload.get("developerProfile")
        payload["amount"] = None
        payload["commandKind"] = "progress"
        return payload

    if command in {"script/update", "script/create", "script/read", "script/delete"} and target:
        summary = f"{base_label} {target}"
    elif command == "scene/open" and target:
        summary = f"{base_label} {target}"
    elif command == "gameobject/info" and target:
        summary = f"{base_label} {target}"
    elif command == "prefab/set-object-reference" and target:
        summary = f"{base_label} {target}"
    elif command == "editor/play-mode" and target in {"play", "stop"}:
        summary = base_label
    elif target and base_label.startswith("Running "):
        summary = f"{base_label} for {target}"

    if amount and amount not in summary:
        summary = f"{summary} ({amount})"

    route_name = _history_route_name(command)
    tool_name = _history_tool_name(route_name)
    category_name = _history_category_name(route_name, tool_name)
    payload["phase"] = phase
    payload["summary"] = summary
    payload["target"] = target
    payload["actor"] = payload.get("agentProfile") or payload.get("agentId") or payload.get("developerProfile")
    payload["commandKind"] = "route" if route_name else "command"
    if route_name:
        payload["routeName"] = route_name
    if tool_name:
        payload["toolName"] = tool_name
    if category_name:
        payload["category"] = category_name
    if amount:
        payload["amount"] = amount
    return payload


def _history_entry_identity(entry: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(entry.get("timestamp") or ""),
        str(entry.get("command") or ""),
        str(entry.get("status") or ""),
        str(entry.get("transport") or ""),
        str(entry.get("durationMs") or ""),
        str(entry.get("error") or ""),
        str(entry.get("note") or ""),
        str(entry.get("args") or ""),
    )


def _format_trace_watch_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "--:--:--"
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed.astimezone().strftime("%H:%M:%S")
    except ValueError:
        return text[-8:] if len(text) >= 8 else text


def _format_trace_watch_line(entry: dict[str, Any]) -> str:
    timestamp = _format_trace_watch_timestamp(entry.get("timestamp"))
    summary = str(entry.get("summary") or entry.get("command") or "CLI activity").strip()
    status = str(entry.get("status") or "ok").strip().lower()
    phase = str(entry.get("phase") or "run").strip().lower()
    command = str(entry.get("command") or "").strip()
    transport = str(entry.get("transport") or "").strip()
    actor = str(entry.get("actor") or entry.get("agentProfile") or entry.get("agentId") or entry.get("developerProfile") or "").strip()
    category = str(entry.get("category") or "").strip()
    route_name = str(entry.get("routeName") or "").strip()
    tool_name = str(entry.get("toolName") or "").strip()
    error = str(entry.get("error") or "").strip()

    details: list[str] = [phase]
    if actor:
        details.append(actor)
    if category:
        details.append(f"category {category}")
    if route_name:
        details.append(f"route {route_name}")
    elif command and command != "cli/progress":
        details.append(f"command {command}")
    if tool_name:
        details.append(f"tool {tool_name}")
    if transport:
        details.append(f"via {transport}")
    if status != "ok":
        details.append(f"status {status}")

    line = f"[{timestamp}] {summary}"
    if details:
        line += " | " + " | ".join(details)
    if error:
        line += f" | error {error}"
    return line


def _trace_port_suffix(port: int | None) -> str:
    return f" --port {port}" if isinstance(port, int) else " --port <port>"


def _recommend_trace_commands(
    *,
    command_kind: str,
    category: str | None,
    route_name: str | None,
    tool_name: str | None,
    selected_port: int | None,
) -> list[str]:
    commands: list[str] = []
    port_suffix = _trace_port_suffix(selected_port)
    normalized_category = (category or "").strip().lower()
    normalized_route = (route_name or "").strip()
    normalized_tool = (tool_name or "").strip()
    normalized_command_kind = (command_kind or "").strip().lower()

    if normalized_route:
        commands.append(f"cli-anything-unity-mcp --json debug trace --route {normalized_route}")
    elif normalized_category:
        commands.append(f"cli-anything-unity-mcp --json debug trace --category {normalized_category}")

    if normalized_route.startswith(("scene/", "gameobject/", "component/", "asset/", "script/")) or normalized_category in {
        "scene",
        "gameobject",
        "component",
        "asset",
        "script",
        "prefab",
    }:
        commands.append(f"cli-anything-unity-mcp --json workflow inspect{port_suffix}")
        commands.append(f"cli-anything-unity-mcp --json debug doctor --recent-commands 8{port_suffix}")
    elif normalized_route in {"compilation/errors", "search/missing-references"} or normalized_route.startswith("console/"):
        commands.append(f"cli-anything-unity-mcp --json debug snapshot --console-count 100 --include-hierarchy{port_suffix}")
        commands.append("cli-anything-unity-mcp --json debug editor-log --tail 120 --ab-umcp-only")
    elif normalized_route.startswith(("graphics/", "sceneview/")) or normalized_category in {
        "graphics",
        "sceneview",
        "lighting",
        "ui",
    }:
        commands.append(f"cli-anything-unity-mcp --json debug capture --kind both{port_suffix}")
        commands.append(f"cli-anything-unity-mcp --json debug snapshot --console-count 80{port_suffix}")
    elif normalized_route.startswith("play/") or normalized_category in {"play", "testing"}:
        commands.append(f"cli-anything-unity-mcp --json debug bridge{port_suffix}")
        commands.append(f"cli-anything-unity-mcp --json status{port_suffix}")
    elif normalized_command_kind == "tool" and normalized_tool:
        commands.append(f"cli-anything-unity-mcp --json debug doctor --recent-commands 8{port_suffix}")
        commands.append(f"cli-anything-unity-mcp --json debug bridge{port_suffix}")
    else:
        commands.append(f"cli-anything-unity-mcp --json debug doctor --recent-commands 8{port_suffix}")
        commands.append(f"cli-anything-unity-mcp --json debug bridge{port_suffix}")

    if normalized_tool:
        commands.append(f"cli-anything-unity-mcp --json tool-info {normalized_tool}")

    deduped: list[str] = []
    seen: set[str] = set()
    for command in commands:
        normalized = command.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped[:3]


def _diagnose_trace_group(
    *,
    command_kind: str,
    category: str | None,
    route_name: str | None,
    tool_name: str | None,
    last_status: str | None,
) -> str | None:
    if str(last_status or "").strip().lower() != "error":
        return None
    normalized_category = (category or "").strip().lower()
    normalized_route = (route_name or "").strip().lower()
    normalized_tool = (tool_name or "").strip()
    normalized_command_kind = (command_kind or "").strip().lower()

    if normalized_route.startswith("scene/") or normalized_category == "scene":
        return "Scene inspection or mutation failed recently."
    if normalized_route in {"compilation/errors", "search/missing-references"} or normalized_route.startswith("console/"):
        return "Unity diagnostics reported a recent editor-side problem."
    if normalized_route.startswith(("graphics/", "sceneview/")) or normalized_category in {"graphics", "sceneview", "lighting", "ui"}:
        return "A visual or rendering-related CLI check failed recently."
    if normalized_route.startswith("play/") or normalized_category in {"play", "testing"}:
        return "Play-mode or testing control failed recently."
    if normalized_command_kind == "tool" and normalized_tool:
        return f"Unity tool {normalized_tool} failed recently."
    if normalized_route:
        return f"CLI route {normalized_route} failed recently."
    return "Recent CLI activity included failures."


def _summarize_trace_entries(
    entries: list[dict[str, Any]],
    *,
    selected_port: int | None = None,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    order = 0
    for entry in entries:
        command_name = str(entry.get("command") or "").strip().lower()
        if command_name in {"debug/breadcrumb", "cli/progress"}:
            continue
        command_kind = str(entry.get("commandKind") or "command").strip().lower()
        category = str(entry.get("category") or "").strip()
        route_name = str(entry.get("routeName") or "").strip()
        tool_name = str(entry.get("toolName") or "").strip()
        summary = str(entry.get("summary") or entry.get("command") or "CLI activity").strip()
        status = str(entry.get("status") or "ok").strip().lower()
        duration = entry.get("durationMs")
        error = str(entry.get("error") or "").strip() or None
        timestamp = str(entry.get("timestamp") or "").strip()

        key = (command_kind, category, route_name, tool_name)
        group = groups.get(key)
        if group is None:
            order += 1
            group = {
                "commandKind": command_kind,
                "category": category or None,
                "routeName": route_name or None,
                "toolName": tool_name or None,
                "label": summary,
                "count": 0,
                "okCount": 0,
                "errorCount": 0,
                "lastStatus": status,
                "lastTimestamp": timestamp or None,
                "lastError": error,
                "diagnosis": None,
                "suggestedNextCommands": [],
                "averageDurationMs": None,
                "maxDurationMs": None,
                "_durationTotal": 0.0,
                "_durationCount": 0,
                "_sortIndex": order,
            }
            groups[key] = group

        group["count"] += 1
        if status == "ok":
            group["okCount"] += 1
        else:
            group["errorCount"] += 1

        if timestamp and (not group["lastTimestamp"] or timestamp >= str(group["lastTimestamp"])):
            group["lastTimestamp"] = timestamp
            group["lastStatus"] = status
            group["lastError"] = error
            if summary:
                group["label"] = summary

        if isinstance(duration, (int, float)):
            group["_durationTotal"] += float(duration)
            group["_durationCount"] += 1
            current_max = group["maxDurationMs"]
            group["maxDurationMs"] = float(duration) if current_max is None else max(float(current_max), float(duration))

    summary_groups = list(groups.values())
    for group in summary_groups:
        duration_count = int(group.pop("_durationCount"))
        duration_total = float(group.pop("_durationTotal"))
        group.pop("_sortIndex", None)
        if duration_count > 0:
            group["averageDurationMs"] = round(duration_total / duration_count, 3)
            if group["maxDurationMs"] is not None:
                group["maxDurationMs"] = round(float(group["maxDurationMs"]), 3)
        group["diagnosis"] = _diagnose_trace_group(
            command_kind=str(group.get("commandKind") or ""),
            category=str(group.get("category") or ""),
            route_name=str(group.get("routeName") or ""),
            tool_name=str(group.get("toolName") or ""),
            last_status=str(group.get("lastStatus") or ""),
        )
        group["suggestedNextCommands"] = _recommend_trace_commands(
            command_kind=str(group.get("commandKind") or ""),
            category=str(group.get("category") or ""),
            route_name=str(group.get("routeName") or ""),
            tool_name=str(group.get("toolName") or ""),
            selected_port=selected_port,
        )

    summary_groups.sort(
        key=lambda item: (
            1 if str(item.get("lastStatus") or "").strip().lower() == "error" else 0,
            str(item.get("lastTimestamp") or ""),
            int(item.get("count") or 0),
        ),
        reverse=True,
    )
    return summary_groups


def _format_trace_summary_text(payload: dict[str, Any]) -> str:
    groups = list(payload.get("groups") or [])
    problem_groups = list(payload.get("problemGroups") or [])
    filters = dict(payload.get("filters") or {})
    lines: list[str] = ["Unity CLI Trace Summary"]

    group_count = int(payload.get("groupCount") or len(groups))
    lines.append(f"Groups: {group_count}")
    if filters.get("agentId"):
        lines.append(f"Agent: {filters['agentId']}")

    filter_bits: list[str] = []
    if filters.get("status"):
        filter_bits.append(f"status={filters['status']}")
    if filters.get("category"):
        filter_bits.append(f"category={filters['category']}")
    if filters.get("route"):
        filter_bits.append(f"route={filters['route']}")
    if filters.get("tool"):
        filter_bits.append(f"tool={filters['tool']}")
    if filters.get("commandContains"):
        filter_bits.append(f"contains={filters['commandContains']}")
    if filter_bits:
        lines.append("Filters: " + ", ".join(filter_bits))

    if problem_groups:
        lines.append("")
        lines.append("Current Problems")
        for group in problem_groups:
            label = str(group.get("label") or "CLI activity").strip()
            route_name = str(group.get("routeName") or "").strip()
            tool_name = str(group.get("toolName") or "").strip()
            diagnosis = str(group.get("diagnosis") or "").strip()
            last_error = str(group.get("lastError") or "").strip()
            lines.append(f"- {label}")
            if route_name:
                lines.append(f"  route: {route_name}")
            if tool_name:
                lines.append(f"  tool: {tool_name}")
            if diagnosis:
                lines.append(f"  why: {diagnosis}")
            if last_error:
                lines.append(f"  error: {last_error}")
            suggested = list(group.get("suggestedNextCommands") or [])
            if suggested:
                lines.append("  next:")
                for command in suggested:
                    lines.append(f"    {command}")
    else:
        lines.append("")
        lines.append("No current failing groups.")

    if groups:
        lines.append("")
        lines.append("Recent Groups")
        for group in groups[:8]:
            label = str(group.get("label") or "CLI activity").strip()
            category = str(group.get("category") or "").strip()
            route_name = str(group.get("routeName") or "").strip()
            tool_name = str(group.get("toolName") or "").strip()
            last_status = str(group.get("lastStatus") or "ok").strip().lower()
            count = int(group.get("count") or 0)
            ok_count = int(group.get("okCount") or 0)
            error_count = int(group.get("errorCount") or 0)
            average_duration = group.get("averageDurationMs")
            meta_bits: list[str] = [f"count {count}", f"ok {ok_count}", f"errors {error_count}", f"last {last_status}"]
            if category:
                meta_bits.append(f"category {category}")
            if route_name:
                meta_bits.append(f"route {route_name}")
            if tool_name:
                meta_bits.append(f"tool {tool_name}")
            if isinstance(average_duration, (int, float)):
                meta_bits.append(f"avg {round(float(average_duration), 3)}ms")
            lines.append(f"- {label} ({'; '.join(meta_bits)})")

    recommended_commands = list(payload.get("recommendedCommands") or [])
    if recommended_commands:
        lines.append("")
        lines.append("Suggested Next Commands")
        for command in recommended_commands:
            lines.append(f"- {command}")

    return "\n".join(lines)


# ─── Debug group ───────────────────────────────────────────────────────────────

@click.group("debug")
def debug_group() -> None:
    """Collect richer Unity debugging snapshots and ready-made debug command templates."""


@debug_group.command("snapshot")
@click.option("--console-count", type=int, default=50, show_default=True, help="How many Unity console entries to fetch.")
@click.option(
    "--type",
    "message_type",
    type=click.Choice(["all", "info", "warning", "error"], case_sensitive=False),
    default="all",
    show_default=True,
    help="Console severity filter.",
)
@click.option("--issue-limit", type=int, default=20, show_default=True, help="How many compilation or missing-reference issues to include.")
@click.option("--include-hierarchy", is_flag=True, help="Include a shallow hierarchy snapshot.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def debug_snapshot_command(
    ctx: click.Context,
    console_count: int,
    message_type: str,
    issue_limit: int,
    include_hierarchy: bool,
    port: int | None,
) -> None:
    """Collect a high-signal Unity debug bundle with console, compilation, scene, and queue state."""

    def _callback() -> dict[str, Any]:
        payload = ctx.obj.backend.get_debug_snapshot(
            port=port,
            console_count=console_count,
            message_type=message_type,
            issue_limit=issue_limit,
            include_hierarchy=include_hierarchy,
        )
        payload["agent"] = {
            "agentId": ctx.obj.agent_id,
            "profile": _serialize_agent_profile(ctx.obj.agent_profile),
            "source": ctx.obj.agent_source,
            "legacy": ctx.obj.legacy_mode,
        }
        return payload

    _run_and_emit(ctx, _callback)


@debug_group.command("template")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def debug_template_command(ctx: click.Context, port: int | None) -> None:
    """Show a reusable CLI-first debug checklist and command template."""

    def _callback() -> dict[str, Any]:
        selected_port = port
        if selected_port is None:
            session = ctx.obj.backend.session_store.load()
            selected_port = session.selected_port
        active_port = selected_port if selected_port is not None else "<port>"
        return {
            "title": "Unity CLI Debug Template",
            "agent": {
                "agentId": ctx.obj.agent_id,
                "profile": _serialize_agent_profile(ctx.obj.agent_profile),
                "source": ctx.obj.agent_source,
                "legacy": ctx.obj.legacy_mode,
            },
            "selectedPort": selected_port,
            "recommendedCommands": [
                f"cli-anything-unity-mcp --json status{' --port ' + str(active_port) if selected_port is not None else ' --port <port>'}",
                f"cli-anything-unity-mcp --json debug bridge{' --port ' + str(active_port) if selected_port is not None else ' --port <port>'}",
                "cli-anything-unity-mcp --json debug trace --tail 20",
                f"cli-anything-unity-mcp --json debug snapshot --console-count 100 --include-hierarchy{' --port ' + str(active_port) if selected_port is not None else ' --port <port>'}",
                "cli-anything-unity-mcp --json debug editor-log --tail 120 --ab-umcp-only",
                f"cli-anything-unity-mcp --json debug breadcrumb \"Trying manual debug step\" --level info{' --port ' + str(active_port) if selected_port is not None else ' --port <port>'}",
                f"cli-anything-unity-mcp --json debug capture --kind both{' --port ' + str(active_port) if selected_port is not None else ' --port <port>'}",
                f"cli-anything-unity-mcp --json console --count 50 --type error{' --port ' + str(active_port) if selected_port is not None else ' --port <port>'}",
                f"cli-anything-unity-mcp --json workflow validate-scene --include-hierarchy{' --port ' + str(active_port) if selected_port is not None else ' --port <port>'}",
                f"cli-anything-unity-mcp --json agent queue{' --port ' + str(active_port) if selected_port is not None else ' --port <port>'}",
            ],
            "checklist": [
                "Inspect the recent CLI trace first so you can see which route/tool attempts succeeded, failed, or took too long.",
                "Capture the current editor, scene, console, compilation, and queue state with `debug snapshot`.",
                "Read the real Unity Editor.log with `debug editor-log` when you need startup, asset import, package, or bridge-level context that is not surfaced through the bridge console route.",
                "Emit a `debug breadcrumb` marker before a manual repro if you want a visible [CLI-TRACE] line in the Unity Console and Editor.log.",
                "Save paired Game View and Scene View screenshots with `debug capture --kind both` before and after visually meaningful edits.",
                "Look at `consoleSummary.highestSeverity` first, then read the newest error messages and stack traces.",
                "Check `compilation.count` before trusting any runtime behavior.",
                "Check `missingReferences.totalFound` before debugging scene logic.",
                "If multiple agents are active, inspect `agent queue` and `agent sessions` to rule out queue contention.",
            ],
            "reportTemplate": {
                "issueSummary": "",
                "reproSteps": [
                    "1. ...",
                    "2. ...",
                    "3. ...",
                ],
                "expected": "",
                "actual": "",
                "snapshotCommand": f"cli-anything-unity-mcp --json debug snapshot --console-count 100 --include-hierarchy{' --port ' + str(active_port) if selected_port is not None else ' --port <port>'}",
            },
        }

    _run_and_emit(ctx, _callback)


@debug_group.command("settings")
@click.option(
    "--unity-console-breadcrumbs/--no-unity-console-breadcrumbs",
    default=None,
    help="Enable or disable automatic CLI breadcrumbs in the Unity Console and Editor.log.",
)
@click.option(
    "--dashboard-auto-refresh/--no-dashboard-auto-refresh",
    default=None,
    help="Persist whether the live debug dashboard should refresh automatically.",
)
@click.option("--dashboard-refresh-seconds", type=float, default=None, help="Persist the default dashboard refresh interval.")
@click.option("--dashboard-console-count", type=int, default=None, help="Persist the default Unity console count for the dashboard.")
@click.option("--dashboard-issue-limit", type=int, default=None, help="Persist the default compilation/missing-reference issue limit.")
@click.option(
    "--dashboard-include-hierarchy/--no-dashboard-include-hierarchy",
    default=None,
    help="Persist whether the dashboard should include hierarchy snapshots by default.",
)
@click.option("--dashboard-editor-log-tail", type=int, default=None, help="Persist the default Editor.log tail length.")
@click.option(
    "--dashboard-ab-umcp-only/--no-dashboard-ab-umcp-only",
    default=None,
    help="Persist whether the dashboard should filter Editor.log to [AB-UMCP] lines by default.",
)
@click.pass_context
def debug_settings_command(
    ctx: click.Context,
    unity_console_breadcrumbs: bool | None,
    dashboard_auto_refresh: bool | None,
    dashboard_refresh_seconds: float | None,
    dashboard_console_count: int | None,
    dashboard_issue_limit: int | None,
    dashboard_include_hierarchy: bool | None,
    dashboard_editor_log_tail: int | None,
    dashboard_ab_umcp_only: bool | None,
) -> None:
    """Inspect or persist CLI debug preferences such as Unity Console breadcrumbs."""

    def _callback() -> dict[str, Any]:
        updates: dict[str, Any] = {}
        if ctx.get_parameter_source("unity_console_breadcrumbs") != ParameterSource.DEFAULT:
            updates["unityConsoleBreadcrumbs"] = unity_console_breadcrumbs
        if ctx.get_parameter_source("dashboard_auto_refresh") != ParameterSource.DEFAULT:
            updates["dashboardAutoRefresh"] = dashboard_auto_refresh
        if ctx.get_parameter_source("dashboard_refresh_seconds") != ParameterSource.DEFAULT:
            updates["dashboardRefreshSeconds"] = dashboard_refresh_seconds
        if ctx.get_parameter_source("dashboard_console_count") != ParameterSource.DEFAULT:
            updates["dashboardConsoleCount"] = dashboard_console_count
        if ctx.get_parameter_source("dashboard_issue_limit") != ParameterSource.DEFAULT:
            updates["dashboardIssueLimit"] = dashboard_issue_limit
        if ctx.get_parameter_source("dashboard_include_hierarchy") != ParameterSource.DEFAULT:
            updates["dashboardIncludeHierarchy"] = dashboard_include_hierarchy
        if ctx.get_parameter_source("dashboard_editor_log_tail") != ParameterSource.DEFAULT:
            updates["dashboardEditorLogTail"] = dashboard_editor_log_tail
        if ctx.get_parameter_source("dashboard_ab_umcp_only") != ParameterSource.DEFAULT:
            updates["dashboardAbUmcpOnly"] = dashboard_ab_umcp_only

        preferences = (
            ctx.obj.backend.update_debug_preferences(**updates)
            if updates
            else ctx.obj.backend.get_debug_preferences()
        )
        return {
            "title": "Unity Debug Settings",
            "updated": sorted(updates.keys()),
            "preferences": preferences,
            "agent": {
                "agentId": ctx.obj.agent_id,
                "profile": _serialize_agent_profile(ctx.obj.agent_profile),
                "source": ctx.obj.agent_source,
                "legacy": ctx.obj.legacy_mode,
            },
        }

    _run_and_emit(ctx, _callback)


@debug_group.command("dashboard")
@click.option("--host", type=str, default="127.0.0.1", show_default=True, help="Host interface for the local dashboard server.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.option(
    "--listen-port",
    type=int,
    default=0,
    show_default=True,
    help="Local dashboard port. Use 0 to auto-pick an open port.",
)
@click.option("--open-browser/--no-open-browser", default=True, show_default=True, help="Open the dashboard in your browser automatically.")
@click.option("--console-count", type=int, default=None, help="Initial Unity console count. Defaults to saved debug settings.")
@click.option("--issue-limit", type=int, default=None, help="Initial issue limit. Defaults to saved debug settings.")
@click.option(
    "--include-hierarchy/--no-include-hierarchy",
    default=None,
    help="Start with hierarchy snapshots enabled or disabled. Defaults to saved debug settings.",
)
@click.option("--editor-log-tail", type=int, default=None, help="Initial Editor.log tail. Defaults to saved debug settings.")
@click.option(
    "--ab-umcp-only/--no-ab-umcp-only",
    default=None,
    help="Start with Editor.log filtered to [AB-UMCP] lines or unfiltered. Defaults to saved debug settings.",
)
@click.option("--trace-tail", type=int, default=20, show_default=True, help="How many recent trace entries to show in the dashboard.")
@click.option(
    "--type",
    "message_type",
    type=click.Choice(["all", "info", "warning", "error"], case_sensitive=False),
    default="all",
    show_default=True,
    help="Initial console severity filter.",
)
@click.pass_context
def debug_dashboard_command(
    ctx: click.Context,
    host: str,
    port: int | None,
    listen_port: int,
    open_browser: bool,
    console_count: int | None,
    issue_limit: int | None,
    include_hierarchy: bool | None,
    editor_log_tail: int | None,
    ab_umcp_only: bool | None,
    trace_tail: int,
    message_type: str,
) -> None:
    """Launch a live browser dashboard for Unity debug state, trace, and logs."""

    preferences = ctx.obj.backend.get_debug_preferences()
    config = DashboardConfig(
        host=host,
        port=listen_port,
        unity_port=port,
        open_browser=open_browser,
        console_count=int(console_count or preferences.get("dashboardConsoleCount", 40)),
        issue_limit=int(issue_limit or preferences.get("dashboardIssueLimit", 20)),
        include_hierarchy=(
            include_hierarchy
            if include_hierarchy is not None
            else bool(preferences.get("dashboardIncludeHierarchy", False))
        ),
        editor_log_tail=int(editor_log_tail or preferences.get("dashboardEditorLogTail", 80)),
        ab_umcp_only=(
            ab_umcp_only
            if ab_umcp_only is not None
            else bool(preferences.get("dashboardAbUmcpOnly", False))
        ),
        trace_tail=trace_tail,
        message_type=message_type,
    )
    ctx.obj.backend.set_runtime_context(
        agent_id=ctx.obj.agent_id,
        agent_profile=ctx.obj.agent_profile.name if ctx.obj.agent_profile else None,
        command_path=_normalized_command_path(ctx),
        activity=_describe_cli_activity(ctx),
    )
    handle = serve_debug_dashboard(
        backend=ctx.obj.backend,
        config=config,
        history_formatter=_humanize_history_entry,
    )
    payload = {
        "title": "Unity Debug Dashboard",
        **handle.to_payload(),
        "unityPort": port,
        "preferences": ctx.obj.backend.get_debug_preferences(),
        "agent": {
            "agentId": ctx.obj.agent_id,
            "profile": _serialize_agent_profile(ctx.obj.agent_profile),
            "source": ctx.obj.agent_source,
            "legacy": ctx.obj.legacy_mode,
        },
    }
    click.echo(format_output(payload, ctx.obj.json_output))
    if not ctx.obj.json_output:
        click.echo("Press Ctrl+C to stop the dashboard server.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        handle.close()


@debug_group.command("trace")
@click.option("--tail", type=int, default=20, show_default=True, help="How many recent CLI trace entries to return.")
@click.option(
    "--status",
    type=click.Choice(["ok", "error"], case_sensitive=False),
    default=None,
    help="Optional status filter.",
)
@click.option("--summary", "summary_mode", is_flag=True, help="Group recent trace entries by category/route/tool.")
@click.option("--command-contains", type=str, default=None, help="Only include entries whose command contains this text.")
@click.option("--category", type=str, default=None, help="Only include entries for a matching Unity category like scene or graphics.")
@click.option("--route", "route_name", type=str, default=None, help="Only include entries for a matching Unity route.")
@click.option("--tool", "tool_name", type=str, default=None, help="Only include entries for a matching Unity tool name.")
@click.option("--agent-id", "filter_agent_id", type=str, default=None, help="Only include entries recorded for this agent ID.")
@click.option("--follow", is_flag=True, help="Keep watching new CLI trace entries. Plain-text mode only.")
@click.option("--history/--new-only", "show_history", default=False, show_default=True, help="In follow mode, print matching existing entries before watching for new ones.")
@click.option("--interval", type=float, default=0.5, show_default=True, help="Seconds between local trace polls in follow mode.")
@click.option("--duration", type=float, default=None, help="Optional number of seconds to follow before exiting.")
@click.option("--clear", "clear_history", is_flag=True, help="Clear the stored CLI trace after printing.")
@click.pass_context
def debug_trace_command(
    ctx: click.Context,
    tail: int,
    status: str | None,
    summary_mode: bool,
    command_contains: str | None,
    category: str | None,
    route_name: str | None,
    tool_name: str | None,
    filter_agent_id: str | None,
    follow: bool,
    show_history: bool,
    interval: float,
    duration: float | None,
    clear_history: bool,
) -> None:
    """Show recent CLI route/tool attempts with status, timing, and errors."""

    def _load_rendered_entries() -> list[dict[str, Any]]:
        history = ctx.obj.backend.get_history()
        entries = _filter_history_entries(
            history,
            tail=tail,
            status=status,
            command_contains=command_contains,
            agent_id=filter_agent_id,
        )
        rendered_entries = [_humanize_history_entry(entry) for entry in entries]
        return _filter_rendered_trace_entries(
            rendered_entries,
            category=category,
            route_name=route_name,
            tool_name=tool_name,
        )

    if follow:
        if ctx.obj.json_output:
            raise click.UsageError("--follow is only supported without --json.")
        if clear_history:
            raise click.UsageError("--clear cannot be combined with --follow.")
        if summary_mode:
            raise click.UsageError("--summary cannot be combined with --follow.")

        rendered_entries = _load_rendered_entries()
        seen = {_history_entry_identity(entry) for entry in rendered_entries}

        click.echo("Watching Unity CLI trace. Press Ctrl+C to stop.")
        if show_history:
            for entry in rendered_entries:
                click.echo(_format_trace_watch_line(entry))

        started = time.monotonic()
        poll_interval = max(0.1, float(interval))
        try:
            while True:
                if duration is not None and (time.monotonic() - started) >= max(0.0, duration):
                    break
                time.sleep(poll_interval)
                for entry in _load_rendered_entries():
                    key = _history_entry_identity(entry)
                    if key in seen:
                        continue
                    seen.add(key)
                    click.echo(_format_trace_watch_line(entry))
        except KeyboardInterrupt:
            click.echo("Stopped watching Unity CLI trace.")
        return

    def _callback() -> dict[str, Any]:
        rendered_entries = _load_rendered_entries()
        selected_port = ctx.obj.backend.session_store.load().selected_port
        summary_groups = (
            _summarize_trace_entries(rendered_entries, selected_port=selected_port)
            if summary_mode
            else None
        )
        problem_groups = [
            group
            for group in (summary_groups or [])
            if str(group.get("lastStatus") or "").strip().lower() == "error"
        ]
        recommended_commands: list[str] = []
        if summary_mode:
            for group in problem_groups:
                for command in group.get("suggestedNextCommands") or []:
                    normalized = str(command).strip()
                    if normalized and normalized not in recommended_commands:
                        recommended_commands.append(normalized)
        payload = {
            "title": "Unity CLI Trace Summary" if summary_mode else "Unity CLI Trace",
            "count": len(rendered_entries),
            "tail": tail,
            "filters": {
                "status": status,
                "summary": summary_mode,
                "commandContains": command_contains,
                "category": category,
                "route": route_name,
                "tool": tool_name,
                "agentId": filter_agent_id,
                "follow": False,
            },
            "agent": {
                "agentId": ctx.obj.agent_id,
                "profile": _serialize_agent_profile(ctx.obj.agent_profile),
                "source": ctx.obj.agent_source,
                "legacy": ctx.obj.legacy_mode,
            },
        }
        if summary_mode:
            payload["groups"] = summary_groups or []
            payload["groupCount"] = len(summary_groups or [])
            payload["problemGroups"] = problem_groups
            payload["problemCount"] = len(problem_groups)
            payload["recommendedCommands"] = recommended_commands[:6]
        else:
            payload["entries"] = rendered_entries
        if clear_history:
            ctx.obj.backend.clear_history()
            payload["cleared"] = True
        return payload

    if summary_mode and not ctx.obj.json_output:
        _run_and_emit(ctx, lambda: _format_trace_summary_text(_callback()))
        return

    _run_and_emit(ctx, _callback)


@debug_group.command("breadcrumb")
@click.argument("message")
@click.option(
    "--level",
    type=click.Choice(["info", "warning", "error"], case_sensitive=False),
    default="info",
    show_default=True,
    help="Unity console log level to emit.",
)
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def debug_breadcrumb_command(
    ctx: click.Context,
    message: str,
    level: str,
    port: int | None,
) -> None:
    """Write a visible [CLI-TRACE] marker into the Unity console and Editor.log."""

    def _callback() -> dict[str, Any]:
        payload = ctx.obj.backend.emit_unity_breadcrumb(
            message=message,
            port=port,
            level=level,
            force=True,
        )
        return {
            "title": "Unity CLI Breadcrumb",
            "message": message,
            "level": level,
            "port": port,
            "result": payload,
            "agent": {
                "agentId": ctx.obj.agent_id,
                "profile": _serialize_agent_profile(ctx.obj.agent_profile),
                "source": ctx.obj.agent_source,
                "legacy": ctx.obj.legacy_mode,
            },
        }

    _run_and_emit(ctx, _callback)


@debug_group.command("bridge")
@click.option("--ping-timeout", type=float, default=0.75, show_default=True, help="Seconds to wait for each bridge ping probe.")
@click.option("--port", type=int, default=None, help="Include and focus an additional explicit port in the bridge diagnostics.")
@click.pass_context
def debug_bridge_command(
    ctx: click.Context,
    ping_timeout: float,
    port: int | None,
) -> None:
    """Inspect bridge discovery, registry, selected port state, and per-port ping health."""

    def _callback() -> dict[str, Any]:
        payload = ctx.obj.backend.get_bridge_diagnostics(port=port, ping_timeout=ping_timeout)
        payload["agent"] = {
            "agentId": ctx.obj.agent_id,
            "profile": _serialize_agent_profile(ctx.obj.agent_profile),
            "source": ctx.obj.agent_source,
            "legacy": ctx.obj.legacy_mode,
        }
        payload["recentCommands"] = ctx.obj.backend.get_history()[-8:]
        return payload

    _run_and_emit(ctx, _callback)


@debug_group.command("doctor")
@click.option("--console-count", type=int, default=80, show_default=True, help="How many Unity console entries to inspect.")
@click.option("--issue-limit", type=int, default=20, show_default=True, help="How many compilation or missing-reference issues to inspect.")
@click.option("--recent-commands", type=int, default=8, show_default=True, help="How many recent CLI commands to include for context.")
@click.option("--include-hierarchy", is_flag=True, help="Include a shallow hierarchy snapshot in the attached debug payload.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def debug_doctor_command(
    ctx: click.Context,
    console_count: int,
    issue_limit: int,
    recent_commands: int,
    include_hierarchy: bool,
    port: int | None,
) -> None:
    """Explain the most likely Unity problems right now and suggest the next CLI checks to run."""

    def _callback() -> dict[str, Any]:
        history_before = list(ctx.obj.backend.session_store.load().history)
        payload = ctx.obj.backend.get_debug_snapshot(
            port=port,
            console_count=console_count,
            message_type="all",
            issue_limit=issue_limit,
            include_hierarchy=include_hierarchy,
        )
        selected_port = port
        if selected_port is None:
            selected_port = int((payload.get("summary") or {}).get("port")) if (payload.get("summary") or {}).get("port") is not None else None
        mem = memory_for_session(ctx.obj.backend.session_store.load())
        report = build_debug_doctor_report(
            payload,
            history_before[-max(0, recent_commands):] if recent_commands > 0 else [],
            selected_port,
            memory=mem,
        )

        # ── Fix-loop auto-learning ─────────────────────────────────────────
        # If issues from the last doctor run are now resolved, credit the
        # commands that ran in between and auto-save them as fixes.
        auto_learned: list[dict[str, Any]] = []
        if mem is not None:
            auto_learned = _detect_and_learn_fixes(mem, report, history_before)
            if auto_learned:
                report["autoLearnedFixes"] = auto_learned

        report["agent"] = {
            "agentId": ctx.obj.agent_id,
            "profile": _serialize_agent_profile(ctx.obj.agent_profile),
            "source": ctx.obj.agent_source,
            "legacy": ctx.obj.legacy_mode,
        }
        return report

    _run_and_emit(ctx, _callback)


@debug_group.command("editor-log")
@click.option("--tail", type=int, default=120, show_default=True, help="How many log lines to return.")
@click.option("--contains", type=str, default=None, help="Only include lines containing this text.")
@click.option("--ab-umcp-only", is_flag=True, help="Only include lines containing [AB-UMCP].")
@click.option("--context", type=int, default=0, show_default=True, help="Include this many surrounding lines around each match. Applies when filters are used.")
@click.option("--follow", is_flag=True, help="Stream the Editor.log in real time after printing the current tail. Plain-text mode only.")
@click.option("--duration", type=float, default=None, help="Optional number of seconds to stream before exiting.")
@click.option("--poll-interval", type=float, default=0.5, show_default=True, help="Seconds between file polls while following.")
@click.option(
    "--path",
    type=click.Path(dir_okay=False, file_okay=True, path_type=Path),
    default=None,
    help="Override the Unity Editor.log path.",
)
@click.pass_context
def debug_editor_log_command(
    ctx: click.Context,
    tail: int,
    contains: str | None,
    ab_umcp_only: bool,
    context: int,
    follow: bool,
    duration: float | None,
    poll_interval: float,
    path: Path | None,
) -> None:
    """Read the real Unity Editor.log so startup, import, and bridge activity are easy to inspect."""

    if follow:
        if ctx.obj.json_output:
            raise click.ClickException("`debug editor-log --follow` is only available without `--json`.")
        if context != 0:
            raise click.ClickException("`debug editor-log --follow` does not support `--context` yet.")
        if duration is not None and duration < 0:
            raise click.ClickException("--duration cannot be negative.")
        if poll_interval <= 0:
            raise click.ClickException("--poll-interval must be greater than 0.")
        try:
            for line in ctx.obj.backend.iter_editor_log(
                path=path,
                tail=tail,
                contains=contains,
                ab_umcp_only=ab_umcp_only,
                duration=duration,
                poll_interval=poll_interval,
            ):
                click.echo(line)
        except (OSError, ValueError) as exc:
            raise click.ClickException(str(exc)) from exc
        return

    def _callback() -> dict[str, Any]:
        payload = ctx.obj.backend.get_editor_log(
            path=path,
            tail=tail,
            contains=contains,
            ab_umcp_only=ab_umcp_only,
            context=context,
        )
        payload["agent"] = {
            "agentId": ctx.obj.agent_id,
            "profile": _serialize_agent_profile(ctx.obj.agent_profile),
            "source": ctx.obj.agent_source,
            "legacy": ctx.obj.legacy_mode,
        }
        payload["recentCommands"] = ctx.obj.backend.get_history()[-8:]
        return payload

    _run_and_emit(ctx, _callback)


@debug_group.command("capture")
@click.option(
    "--kind",
    type=click.Choice(["game", "scene", "both"], case_sensitive=False),
    default="both",
    show_default=True,
    help="Which Unity views to capture.",
)
@click.option("--width", type=int, default=960, show_default=True, help="Capture width in pixels.")
@click.option("--height", type=int, default=540, show_default=True, help="Capture height in pixels.")
@click.option("--label", type=str, default=None, help="Optional file name prefix for saved captures.")
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Directory where captures should be written. Defaults to .cli-anything-unity-mcp/captures.",
)
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def debug_capture_command(
    ctx: click.Context,
    kind: str,
    width: int,
    height: int,
    label: str | None,
    output_dir: Path | None,
    port: int | None,
) -> None:
    """Capture Game View and/or Scene View screenshots for visual verification."""

    def _callback() -> dict[str, Any]:
        if width < 1 or height < 1:
            raise ValueError("--width and --height must be positive integers.")

        capture_dir = (output_dir or (Path(".cli-anything-unity-mcp") / "captures")).resolve()
        capture_dir.mkdir(parents=True, exist_ok=True)

        safe_label = re.sub(r"[^A-Za-z0-9._-]+", "-", (label or "").strip()).strip("-")
        if not safe_label:
            safe_label = datetime.now(UTC).strftime("debug-capture-%Y%m%d-%H%M%S")

        requested_kinds = ["game", "scene"] if kind.lower() == "both" else [kind.lower()]
        captures: dict[str, Any] = {}

        for requested_kind in requested_kinds:
            route = "graphics/game-capture" if requested_kind == "game" else "graphics/scene-capture"
            result = ctx.obj.backend.call_route(
                route,
                params={"width": width, "height": height},
                port=port,
            )
            encoded = str(result.get("base64") or "")
            if not encoded:
                raise ValueError(f"{requested_kind} capture did not return image data.")
            output_path = (capture_dir / f"{safe_label}-{requested_kind}.png").resolve()
            output_path.write_bytes(base64.b64decode(encoded))
            captures[requested_kind] = {
                "success": True,
                "path": str(output_path),
                "width": int(result.get("width") or width),
                "height": int(result.get("height") or height),
                "cameraName": result.get("cameraName"),
            }

        return {
            "title": "Unity Debug Capture",
            "agent": {
                "agentId": ctx.obj.agent_id,
                "profile": _serialize_agent_profile(ctx.obj.agent_profile),
                "source": ctx.obj.agent_source,
                "legacy": ctx.obj.legacy_mode,
            },
            "capture": {
                "kind": kind.lower(),
                "width": width,
                "height": height,
                "label": safe_label,
                "outputDir": str(capture_dir),
                "port": port,
            },
            "captures": captures,
        }

    _run_and_emit(ctx, _callback)


@debug_group.command("watch")
@click.option("--iterations", type=int, default=3, show_default=True, help="How many samples to capture.")
@click.option("--interval", type=float, default=1.0, show_default=True, help="Seconds to wait between samples.")
@click.option("--console-count", type=int, default=20, show_default=True, help="How many Unity console entries to include per sample.")
@click.option(
    "--type",
    "message_type",
    type=click.Choice(["all", "info", "warning", "error"], case_sensitive=False),
    default="all",
    show_default=True,
    help="Console severity filter.",
)
@click.option("--issue-limit", type=int, default=20, show_default=True, help="How many compilation or missing-reference issues to include.")
@click.option("--include-hierarchy", is_flag=True, help="Include a shallow hierarchy snapshot in each sampled debug bundle.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def debug_watch_command(
    ctx: click.Context,
    iterations: int,
    interval: float,
    console_count: int,
    message_type: str,
    issue_limit: int,
    include_hierarchy: bool,
    port: int | None,
) -> None:
    """Sample Unity debug state over time so console and editor changes are easy to see."""

    def _callback() -> dict[str, Any]:
        if iterations < 1:
            raise ValueError("--iterations must be at least 1.")
        if interval < 0:
            raise ValueError("--interval cannot be negative.")

        samples: list[dict[str, Any]] = []
        for index in range(iterations):
            snapshot = ctx.obj.backend.get_debug_snapshot(
                port=port,
                console_count=console_count,
                message_type=message_type,
                issue_limit=issue_limit,
                include_hierarchy=include_hierarchy,
            )
            sample = {
                "index": index + 1,
                "capturedAt": datetime.now(UTC).isoformat(),
                "summary": snapshot.get("summary"),
                "consoleSummary": snapshot.get("consoleSummary"),
                "compilation": snapshot.get("compilation"),
                "missingReferences": snapshot.get("missingReferences"),
                "queue": snapshot.get("queue"),
            }
            if include_hierarchy and "hierarchy" in snapshot:
                sample["hierarchy"] = snapshot["hierarchy"]
            samples.append(sample)

            if index + 1 < iterations and interval > 0:
                time.sleep(interval)

        latest = samples[-1] if samples else {}
        return {
            "title": "Unity Debug Watch",
            "agent": {
                "agentId": ctx.obj.agent_id,
                "profile": _serialize_agent_profile(ctx.obj.agent_profile),
                "source": ctx.obj.agent_source,
                "legacy": ctx.obj.legacy_mode,
            },
            "watch": {
                "iterations": iterations,
                "intervalSeconds": interval,
                "consoleCount": console_count,
                "messageType": message_type,
                "issueLimit": issue_limit,
                "includeHierarchy": include_hierarchy,
                "port": ((latest.get("summary") or {}).get("port")),
            },
            "latest": latest,
            "samples": samples,
        }

    _run_and_emit(ctx, _callback)
