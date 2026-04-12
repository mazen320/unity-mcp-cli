from __future__ import annotations

import base64
import os
import re
import shlex
import socket
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Optional

import click

from .. import __version__
from ..core.agent_profiles import AgentProfile, AgentProfileStore, derive_agent_profiles_path
from ..core.client import UnityMCPClient, UnityMCPClientError
from ..core.debug_dashboard import DashboardConfig, serve_debug_dashboard
from ..core.debug_doctor import build_debug_doctor_report
from ..core.developer_profiles import (
    DeveloperProfile,
    DeveloperProfileStore,
    derive_developer_profiles_path,
)
from ..core.memory import ALL_CATEGORIES, ProjectMemory, memory_for_session
from ..core.routes import route_to_tool_name
from ..core.session import SessionStore
from ..core.workflows import (
    build_asset_path,
    build_behaviour_script,
    get_active_scene_path,
    require_workflow_success,
    sanitize_csharp_identifier,
    unique_probe_name,
    vec3,
    wait_for_compilation,
    wait_for_result,
    workflow_error_message,
)
from ..utils.output import format_output, load_json_params, load_text_value
from ..utils.unity_mcp_backend import (
    BackendSelectionError,
    UnityMCPBackend,
    get_default_registry_path,
)


def _default_agent_id() -> str:
    return f"cli-anything-unity-mcp-{socket.gethostname()}-{os.getpid()}"


@dataclass
class CLIContext:
    backend: UnityMCPBackend
    json_output: bool
    base_args: tuple[str, ...]
    command_path: str
    agent_profile_store: AgentProfileStore
    developer_profile_store: DeveloperProfileStore
    agent_id: str
    agent_profile: AgentProfile | None
    developer_profile: DeveloperProfile
    agent_source: str
    developer_source: str
    legacy_mode: bool


def _emit(ctx: click.Context, value: Any) -> None:
    click.echo(format_output(value, ctx.obj.json_output))


def _format_failed_route_hint(entry: dict[str, Any] | None) -> str | None:
    if not isinstance(entry, dict):
        return None
    route = str(entry.get("command") or "").strip()
    if not route:
        return None
    transport = str(entry.get("transport") or "unknown").strip()
    port = entry.get("port")
    tool_name = route_to_tool_name(route)
    port_flag = f" --port {port}" if isinstance(port, int) and port > 0 else ""
    extra_commands: list[str] = []
    if transport == "file-ipc":
        retry_command = "cli-anything-unity-mcp --json debug bridge"
    elif transport == "queue":
        retry_command = f"cli-anything-unity-mcp --json debug doctor{port_flag}"
        extra_commands = [
            f"cli-anything-unity-mcp --json agent queue{port_flag}",
            f"cli-anything-unity-mcp --json agent sessions{port_flag}",
        ]
    else:
        retry_command = f"cli-anything-unity-mcp --json debug doctor{port_flag}"
    details = [f"route {route}"]
    if tool_name:
        details.append(f"tool {tool_name}")
    details.append(f"transport {transport}")
    if port is not None:
        details.append(f"port {port}")
    hint = f"Last failing {'; '.join(details)}. Try: {retry_command}"
    if extra_commands:
        hint += f". Then inspect: {'; '.join(extra_commands)}"
    return hint


def _format_cli_exception_message(ctx: click.Context, exc: Exception) -> str:
    base_message = str(exc)
    try:
        state = ctx.obj.backend.session_store.load()
        history = list(getattr(state, "history", []) or [])
    except Exception:
        return base_message
    if not history:
        return base_message
    latest = history[-1]
    if str(latest.get("status") or "").strip().lower() != "error":
        return base_message
    latest_error = str(latest.get("error") or "").strip()
    if latest_error and base_message not in latest_error and latest_error not in base_message:
        return base_message
    hint = _format_failed_route_hint(latest)
    if not hint:
        return base_message
    return f"{base_message}. {hint}"


def _current_port_from_params(ctx: click.Context) -> int | None:
    params = getattr(ctx, "params", None)
    if isinstance(params, dict):
        value = params.get("port")
        if isinstance(value, int):
            return value
    return None


def _normalized_command_tokens(ctx: click.Context) -> list[str]:
    tokens: list[str] = []
    current: click.Context | None = ctx
    while current is not None:
        name = str(current.info_name or "").strip()
        if name:
            tokens.append(name)
        current = current.parent
    tokens.reverse()
    if tokens:
        tokens = tokens[1:]
    return [token.lower() for token in tokens if token]


def _normalized_command_path(ctx: click.Context) -> str:
    tokens = _normalized_command_tokens(ctx)
    if not tokens:
        return "cli-anything-unity-mcp"
    return " ".join(tokens)


def _describe_cli_activity(ctx: click.Context) -> str:
    params = dict(getattr(ctx, "params", {}) or {})
    tokens = _normalized_command_tokens(ctx)
    if not tokens:
        return "running CLI command"

    def _path_name(value: Any) -> str | None:
        if value in (None, ""):
            return None
        try:
            return Path(str(value)).name or str(value)
        except (TypeError, ValueError):
            return str(value)

    def _inline_text(value: Any) -> str | None:
        if value in (None, ""):
            return None
        return str(value).strip() or None

    def _csv(values: Any, *, limit: int = 4) -> str | None:
        if not values:
            return None
        if isinstance(values, str):
            items = [values]
        else:
            try:
                items = [str(item).strip() for item in values if str(item).strip()]
            except TypeError:
                items = [str(values).strip()]
        if not items:
            return None
        if len(items) <= limit:
            return ", ".join(items)
        return ", ".join(items[:limit]) + f" +{len(items) - limit} more"

    def _with_details(base: str, *details: Any) -> str:
        filtered = [str(detail).strip() for detail in details if str(detail).strip()]
        if not filtered:
            return base
        return f"{base} ({'; '.join(filtered)})"

    first = tokens[0].lower()
    second = tokens[1].lower() if len(tokens) > 1 else ""

    if first == "instances":
        return "checking Unity instances"
    if first == "select":
        return f"selecting Unity instance {params.get('port')}" if params.get("port") else "selecting Unity instance"
    if first == "status":
        return "checking CLI status"
    if first == "history":
        return "inspecting CLI history"
    if first == "tool-template":
        tool_name = params.get("tool_name")
        return f"inspecting tool template for {tool_name}" if tool_name else "inspecting tool template"
    if first == "tool-info":
        tool_name = params.get("tool_name")
        return f"inspecting tool info for {tool_name}" if tool_name else "inspecting tool info"
    if first == "tool-coverage":
        category = params.get("category")
        status = params.get("status")
        if category:
            return f"inspecting tool coverage for {category}"
        if status:
            return f"inspecting {status} tool coverage"
        return "inspecting tool coverage"
    if first == "tools":
        return _with_details(
            "browsing tool catalog",
            "live routes" if params.get("live") else "",
            "merged with live routes" if params.get("merged_live") else "",
            f"category {params.get('category')}" if params.get("category") else "",
            f"tier {params.get('tier')}" if params.get("tier") else "",
            f"search '{params.get('search')}'" if params.get("search") else "",
        )
    if first == "advanced-tools":
        category = params.get("category")
        return _with_details(
            f"browsing advanced tools for {category}" if category else "browsing advanced tools",
            f"search '{params.get('search')}'" if params.get("search") else "",
        )
    if first == "scene-info":
        return "inspecting scene info"
    if first == "scene-open":
        target = params.get("path")
        return _with_details(
            f"opening scene {_path_name(target)}" if target else "opening scene",
            "save dirty scene first" if params.get("save_if_dirty") else "",
            "discard unsaved changes" if params.get("discard_unsaved") else "",
            "force reload" if params.get("force_reload") else "",
        )
    if first == "scene-save":
        return "saving scene"
    if first == "project-info":
        return "inspecting project info"
    if first == "state":
        return "checking editor state"
    if first == "context":
        category = params.get("category")
        return f"inspecting project context for {category}" if category else "inspecting project context"
    if first == "hierarchy":
        return _with_details(
            "inspecting scene hierarchy",
            f"under {params.get('parent_path')}" if params.get("parent_path") else "",
            f"depth {params.get('max_depth')}" if params.get("max_depth") is not None else "",
            f"max {params.get('max_nodes')} nodes" if params.get("max_nodes") is not None else "",
        )
    if first == "route":
        route = params.get("route_name") or params.get("route")
        param_count = len(params.get("param_pairs") or ())
        return _with_details(
            f"calling route {route}" if route else "calling bridge route",
            "using GET" if params.get("use_get") else "",
            f"{param_count} inline params" if param_count else "",
            "JSON params provided" if params.get("params") or params.get("params_file") else "",
        )
    if first == "console":
        count = params.get("count")
        return _with_details(
            "inspecting Unity console",
            f"type {params.get('message_type')}" if params.get("message_type") else "",
            f"{count} items" if count is not None else "",
        )
    if first == "script-read":
        target = params.get("path")
        return f"inspecting script {Path(str(target)).name}" if target else "inspecting script"
    if first == "script-update":
        target = params.get("path")
        return f"editing script {Path(str(target)).name}" if target else "editing script"
    if first == "script-create":
        target = params.get("path") or params.get("name")
        return f"creating script {Path(str(target)).name}" if target else "creating script"
    if first == "tool":
        tool_name = params.get("tool_name") or params.get("tool")
        param_count = len(params.get("param_pairs") or ())
        return _with_details(
            f"calling Unity tool {tool_name}" if tool_name else "calling Unity tool",
            f"{param_count} inline params" if param_count else "",
            "JSON params provided" if params.get("params") or params.get("params_file") else "",
        )
    if first == "workflow":
        if second == "inspect":
            return _with_details(
                "inspecting Unity project",
                f"assets from {params.get('asset_folder')}" if params.get("asset_folder") else "",
                f"asset search '{params.get('asset_search')}'" if params.get("asset_search") else "",
                f"sample {params.get('asset_limit')} assets" if params.get("asset_limit") is not None else "",
                (
                    f"hierarchy depth {params.get('hierarchy_depth')}, max {params.get('hierarchy_nodes')} nodes"
                    if params.get("hierarchy_depth") is not None and params.get("hierarchy_nodes") is not None
                    else ""
                ),
            )
        if second == "asset-audit":
            return _with_details(
                "auditing Unity assets",
                _path_name(params.get("project_root")) if params.get("project_root") else "",
                (
                    f"top {params.get('top_recommendations')} recommendations"
                    if params.get("top_recommendations") is not None
                    else ""
                ),
            )
        if second == "expert-audit":
            return _with_details(
                "running expert Unity audit",
                f"lens {params.get('lens_name')}" if params.get("lens_name") else "",
                _path_name(params.get("project_root")) if params.get("project_root") else "",
            )
        if second == "scene-critique":
            return _with_details(
                "running scene critique",
                (
                    f"lenses {_csv(params.get('lens_names'))}"
                    if params.get("lens_names")
                    else "default critique lenses"
                ),
                _path_name(params.get("project_root")) if params.get("project_root") else "",
            )
        if second == "quality-score":
            return _with_details(
                "scoring project quality",
                (
                    f"lenses {_csv(params.get('lens_names'))}"
                    if params.get("lens_names")
                    else "all expert lenses"
                ),
                _path_name(params.get("project_root")) if params.get("project_root") else "",
            )
        if second == "quality-fix":
            return _with_details(
                "planning quality fix",
                f"lens {params.get('lens_name')}" if params.get("lens_name") else "",
                f"fix {params.get('fix_name')}" if params.get("fix_name") else "",
                "apply now" if params.get("apply_fix") else "plan only",
                _path_name(params.get("project_root")) if params.get("project_root") else "",
            )
        if second == "bootstrap-guidance":
            return _with_details(
                "bootstrapping Unity guidance",
                _path_name(params.get("project_root")) if params.get("project_root") else "",
                "write files" if params.get("write_files") else "preview only",
                "include MCP context" if params.get("include_context") else "agents only",
                "overwrite existing" if params.get("overwrite") else "",
            )
        if second == "create-sandbox-scene":
            return _with_details(
                "creating sandbox scene",
                f"name {params.get('name')}" if params.get("name") else "",
                f"folder {params.get('folder')}" if params.get("folder") else "",
                "leave sandbox open" if params.get("open_scene") else "restore original scene",
                "save dirty scene first" if params.get("save_if_dirty") else "",
                "discard unsaved changes" if params.get("discard_unsaved") else "",
            )
        if second == "reset-scene":
            return _with_details(
                "reloading the active scene",
                "save dirty scene first" if params.get("save_if_dirty") else "",
                "discard unsaved changes" if params.get("discard_unsaved") else "",
                "force reload" if params.get("force_reload") else "",
            )
        if second == "validate-scene":
            return _with_details(
                "validating scene",
                f"missing-reference limit {params.get('limit')}" if params.get("limit") is not None else "",
                "include hierarchy snapshot" if params.get("include_hierarchy") else "",
            )
        if second == "audit-advanced":
            categories = _csv(params.get("categories"))
            return _with_details(
                "auditing advanced Unity tools",
                f"categories {categories}" if categories else "all safe categories",
                "probe-backed checks" if params.get("probe_backed") else "route-only checks",
                f"timeout {params.get('timeout')}s" if params.get("timeout") is not None else "",
            )
        if second == "create-behaviour":
            target = params.get("class_name") or params.get("name")
            return _with_details(
                f"creating behaviour {target}" if target else "creating behaviour",
                f"folder {params.get('folder')}" if params.get("folder") else "",
                f"namespace {params.get('namespace')}" if params.get("namespace") else "",
                f"attach to {params.get('object_name')}" if params.get("object_name") else ("attach to a new scene object" if params.get("attach") else "script only"),
            )
        if second == "wire-reference":
            target_object = params.get("target_object")
            property_name = params.get("property_name")
            return _with_details(
                (
                    f"wiring {property_name} on {target_object}"
                    if target_object and property_name
                    else "wiring object reference"
                ),
                f"component {params.get('component_type')}" if params.get("component_type") else "",
                f"scene object {params.get('reference_object')}" if params.get("reference_object") else "",
                f"asset {params.get('asset_path')}" if params.get("asset_path") else "",
                f"instance ID {params.get('reference_instance_id')}" if params.get("reference_instance_id") is not None else "",
                "clearing reference" if params.get("clear_reference") else "",
            )
        if second == "create-prefab":
            source = params.get("game_object")
            prefab_name = params.get("name")
            return _with_details(
                f"creating prefab from {source}" if source else "creating prefab",
                f"name {prefab_name}" if prefab_name else "",
                f"folder {params.get('folder')}" if params.get("folder") else "",
                "instantiate in scene" if params.get("instantiate") else "",
                f"instance name {params.get('instance_name')}" if params.get("instance_name") else "",
                f"parent {params.get('parent')}" if params.get("parent") else "",
            )
        if second:
            return f"running workflow {second}"
        return "running workflow"
    if first == "agent":
        if second == "watch":
            return "watching agent activity"
        if second == "sessions":
            return "inspecting agent sessions"
        if second == "queue":
            return "checking agent queue"
        if second == "log":
            return f"inspecting agent log {params.get('agent_id')}" if params.get("agent_id") else "inspecting agent log"
        if second:
            return f"running agent command {second}"
        return "running agent command"
    if first == "debug":
        if second == "snapshot":
            return _with_details(
                "capturing Unity debug snapshot",
                f"console {params.get('console_count')} items" if params.get("console_count") is not None else "",
                f"type {params.get('message_type')}" if params.get("message_type") else "",
                f"issue limit {params.get('issue_limit')}" if params.get("issue_limit") is not None else "",
                "include hierarchy" if params.get("include_hierarchy") else "",
            )
        if second == "doctor":
            return _with_details(
                "running Unity debug doctor",
                f"console {params.get('console_count')} items" if params.get("console_count") is not None else "",
                f"issue limit {params.get('issue_limit')}" if params.get("issue_limit") is not None else "",
                f"recent {params.get('recent_commands')} commands" if params.get("recent_commands") is not None else "",
                "include hierarchy" if params.get("include_hierarchy") else "",
            )
        if second == "bridge":
            return _with_details(
                "inspecting bridge diagnostics",
                f"ping timeout {params.get('ping_timeout')}s" if params.get("ping_timeout") is not None else "",
                f"focus port {params.get('port')}" if params.get("port") is not None else "",
            )
        if second == "trace":
            return _with_details(
                "inspecting CLI trace",
                f"tail {params.get('tail')}" if params.get("tail") is not None else "",
                f"status {params.get('status')}" if params.get("status") else "",
                f"command contains '{params.get('command_contains')}'" if params.get("command_contains") else "",
                f"agent {params.get('filter_agent_id')}" if params.get("filter_agent_id") else "",
            )
        if second == "capture":
            return _with_details(
                "capturing Unity views",
                f"kind {params.get('kind')}" if params.get("kind") else "",
                (
                    f"{params.get('width')}x{params.get('height')}"
                    if params.get("width") is not None and params.get("height") is not None
                    else ""
                ),
                f"label {params.get('label')}" if params.get("label") else "",
            )
        if second == "editor-log":
            return _with_details(
                "reading Unity editor log",
                f"tail {params.get('tail')}" if params.get("tail") is not None else "",
                f"contains '{params.get('contains')}'" if params.get("contains") else "",
                "AB-UMCP only" if params.get("ab_umcp_only") else "",
                f"context {params.get('context')}" if params.get("context") else "",
                "follow mode" if params.get("follow") else "",
            )
        if second == "settings":
            return "inspecting debug settings"
        if second == "dashboard":
            return _with_details(
                "opening live debug dashboard",
                f"host {params.get('host')}" if params.get("host") else "",
                "browser auto-open" if params.get("open_browser") else "headless launch",
            )
        if second == "watch":
            return _with_details(
                "watching Unity debug state",
                f"{params.get('iterations')} samples" if params.get("iterations") is not None else "",
                f"interval {params.get('interval')}s" if params.get("interval") is not None else "",
                f"console {params.get('console_count')} items" if params.get("console_count") is not None else "",
                "include hierarchy" if params.get("include_hierarchy") else "",
            )
        if second == "breadcrumb":
            message = _inline_text(params.get("message"))
            return _with_details(
                "emitting manual breadcrumb",
                f"message '{message[:40]}{'...' if len(message) > 40 else ''}'" if message else "",
                f"level {params.get('level')}" if params.get("level") else "",
            )
        if second:
            return f"running debug command {second}"
        return "running debug command"
    if first == "ping":
        return "checking Unity bridge"
    if first == "play":
        action = params.get("action")
        return f"changing play mode to {action}" if action else "changing play mode"
    return "running " + " ".join(tokens)


def _should_auto_breadcrumb(ctx: click.Context) -> bool:
    if bool((getattr(ctx, "meta", None) or {}).get("disable_auto_breadcrumbs")):
        return False
    tokens = _normalized_command_tokens(ctx)
    if not tokens:
        return False
    if tokens == ["debug", "breadcrumb"]:
        return False
    if tokens == ["instances"]:
        return False
    if tokens[0] in {"history", "tool-template", "tool-info", "tool-coverage", "tools", "advanced-tools"}:
        return False
    if tokens[0] == "debug" and len(tokens) > 1 and tokens[1] in {"trace", "template", "editor-log", "settings", "dashboard"}:
        return False
    if tokens[0] == "agent" and len(tokens) > 1 and tokens[1] in {"current", "list", "save", "use", "clear", "remove"}:
        return False
    return True


def _friendly_agent_label(ctx: click.Context) -> str:
    if ctx.obj.agent_profile:
        return ctx.obj.agent_profile.name
    if ctx.obj.developer_profile and ctx.obj.developer_source != "default":
        return ctx.obj.developer_profile.name
    agent_id = str(ctx.obj.agent_id or "").strip()
    if not agent_id:
        return "CLI"
    if agent_id == "cli-anything-unity-mcp-mcp":
        return "MCP"
    if agent_id.startswith("cli-anything-unity-mcp-"):
        return "CLI"
    if agent_id == "cli-anything-unity-mcp":
        return "CLI"
    return agent_id


def _capitalize_activity(activity: str) -> str:
    text = str(activity or "").strip()
    if not text:
        return "Running command"
    return text[0].upper() + text[1:]


def _emit_auto_breadcrumb(
    ctx: click.Context,
    *,
    stage: str,
    level: str = "info",
    extra: str | None = None,
) -> None:
    if not _should_auto_breadcrumb(ctx):
        return
    activity = _describe_cli_activity(ctx)
    agent_label = _friendly_agent_label(ctx)
    activity_label = _capitalize_activity(activity)
    if stage == "start":
        message = f"{agent_label}: {activity_label}"
    elif stage == "done":
        message = f"{agent_label}: Finished {activity}"
    else:
        detail = f": {extra}" if extra else ""
        message = f"{agent_label}: Failed {activity}{detail}"
    try:
        ctx.obj.backend.emit_unity_breadcrumb(
            message=message,
            port=_current_port_from_params(ctx),
            level=level,
            record_history=False,
        )
    except (BackendSelectionError, UnityMCPClientError, ValueError, OSError):
        return


def _run_and_emit(ctx: click.Context, callback: Callable[[], Any]) -> None:
    activity = _describe_cli_activity(ctx)
    ctx.obj.backend.set_runtime_context(
        agent_id=ctx.obj.agent_id,
        agent_profile=ctx.obj.agent_profile.name if ctx.obj.agent_profile else None,
        developer_profile=ctx.obj.developer_profile.name if ctx.obj.developer_profile else None,
        command_path=_normalized_command_path(ctx),
        activity=activity,
    )
    _emit_auto_breadcrumb(ctx, stage="start", level="info")
    try:
        result = callback()
    except (BackendSelectionError, UnityMCPClientError, ValueError) as exc:
        _emit_auto_breadcrumb(ctx, stage="error", level="error", extra=str(exc))
        raise click.ClickException(_format_cli_exception_message(ctx, exc)) from exc
    _emit_auto_breadcrumb(ctx, stage="done", level="info")
    _emit(ctx, result)


def _record_progress_step(
    ctx: click.Context,
    message: str,
    *,
    phase: str = "inspect",
    level: str = "info",
    port: int | None = None,
) -> None:
    if bool((getattr(ctx, "meta", None) or {}).get("disable_auto_breadcrumbs")):
        return
    agent_label = _friendly_agent_label(ctx)
    ctx.obj.backend.record_progress(
        message=message,
        port=port if port is not None else _current_port_from_params(ctx),
        phase=phase,
        level=level,
        breadcrumb_message=f"{agent_label}: {message}",
    )


def _is_workflow_missing_error(result: Any) -> bool:
    message = workflow_error_message(result)
    if not message:
        return False
    lowered = message.lower()
    return "not found" in lowered or "file not found" in lowered


def _build_agent_profile_store(
    session_path: Path | None,
    agent_profiles_path: Path | None,
) -> AgentProfileStore:
    if agent_profiles_path:
        return AgentProfileStore(agent_profiles_path)
    if session_path:
        return AgentProfileStore(derive_agent_profiles_path(session_path))
    return AgentProfileStore()


def _build_developer_profile_store(
    session_path: Path | None,
    developer_profiles_path: Path | None,
) -> DeveloperProfileStore:
    if developer_profiles_path:
        return DeveloperProfileStore(developer_profiles_path)
    if session_path:
        return DeveloperProfileStore(derive_developer_profiles_path(session_path))
    return DeveloperProfileStore()


def _slugify_agent_profile_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "sidecar"


def _suggest_agent_id(profile_name: str) -> str:
    return f"cli-anything-unity-mcp-{_slugify_agent_profile_name(profile_name)}-{socket.gethostname()}"


def _serialize_agent_profile(profile: AgentProfile | None) -> dict[str, Any] | None:
    return asdict(profile) if profile is not None else None


def _serialize_developer_profile(profile: DeveloperProfile | None) -> dict[str, Any] | None:
    return asdict(profile) if profile is not None else None


def _build_base_args(
    host: str,
    default_port: int,
    registry_path: Path | None,
    session_path: Path | None,
    agent_profiles_path: Path | None,
    developer_profiles_path: Path | None,
    json_output: bool,
    agent_id: str | None,
    agent_profile: str | None,
    developer_profile: str | None,
    legacy: bool,
    port_range_start: int,
    port_range_end: int,
) -> tuple[str, ...]:
    parts: list[str] = [
        "--host",
        host,
        "--default-port",
        str(default_port),
        "--port-range-start",
        str(port_range_start),
        "--port-range-end",
        str(port_range_end),
    ]
    if agent_id:
        parts.extend(["--agent-id", agent_id])
    if registry_path:
        parts.extend(["--registry-path", str(registry_path)])
    if session_path:
        parts.extend(["--session-path", str(session_path)])
    if agent_profiles_path:
        parts.extend(["--agent-profiles-path", str(agent_profiles_path)])
    if developer_profiles_path:
        parts.extend(["--developer-profiles-path", str(developer_profiles_path)])
    if json_output:
        parts.append("--json")
    if agent_profile:
        parts.extend(["--agent-profile", agent_profile])
    if developer_profile:
        parts.extend(["--developer-profile", developer_profile])
    if legacy:
        parts.append("--legacy")
    return tuple(parts)


def _run_repl(ctx: click.Context) -> None:
    # Import cli lazily to avoid circular imports
    from ..unity_mcp_cli import cli

    click.echo("Unity MCP CLI REPL. Type `help` for commands or `quit` to exit.")
    base_args = list(ctx.obj.base_args)
    while True:
        try:
            line = input("unity-mcp> ")
        except EOFError:
            click.echo()
            return

        line = line.strip()
        if not line:
            continue
        if line in {"quit", "exit"}:
            return

        try:
            argv = shlex.split(line)
        except ValueError as exc:
            click.echo(f"Input error: {exc}")
            continue

        if argv and argv[0] == "help":
            if len(argv) == 1:
                argv = ["--help"]
            else:
                argv = argv[1:] + ["--help"]

        try:
            cli.main(
                args=base_args + argv,
                prog_name=ctx.obj.command_path,
                standalone_mode=False,
            )
        except click.ClickException as exc:
            exc.show()
        except SystemExit:
            continue
        except Exception as exc:  # pragma: no cover - defensive REPL guard
            click.echo(f"Error: {exc}")


def _detect_and_learn_fixes(
    mem: "ProjectMemory",
    current_report: dict[str, Any],
    history_before: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare current doctor findings to the last saved state.

    When issues that were present last time are now gone, credit the CLI
    commands that ran in between and save them as fix suggestions.
    Returns a list of auto-learned fix records (for report transparency).
    """
    try:
        last_state = mem.get_last_doctor_state()
        current_findings = current_report.get("findings") or []
        now_iso = datetime.now(timezone.utc).isoformat()

        # Save current state for the next doctor run to diff against.
        mem.save_doctor_state(current_findings, now_iso)

        if not last_state:
            return []

        last_findings_titles = {
            f["title"] for f in (last_state.get("findings") or [])
            if f.get("severity") in ("error", "warning")
        }
        current_titles = {
            f["title"] for f in current_findings
            if f.get("title") != "Healthy Snapshot" and f.get("severity") in ("error", "warning")
        }
        resolved = last_findings_titles - current_titles
        if not resolved:
            return []

        # Find commands that ran after the last doctor state was saved.
        last_ts = last_state.get("timestamp", "")
        intervening = [
            h for h in history_before
            if h.get("timestamp", "") > last_ts
            and h.get("status") == "ok"
            and "debug" not in str(h.get("command", ""))  # skip debug/inspect commands
            and h.get("command") not in {"instances", "status", "ping", "history", "memory"}
        ]

        if not intervening:
            return []

        learned = []
        for issue_title in resolved:
            # Credit the most recent non-trivial command before resolution.
            best = intervening[-1]
            cmd = best.get("command", "")
            args = best.get("args") or {}
            # Reconstruct a CLI command string from history.
            arg_str = " ".join(
                f"--{k} {v}" for k, v in args.items()
                if v is not None and k not in {"port", "agent_id"}
            )
            fix_command = f"cli-anything-unity-mcp {cmd} {arg_str}".strip()
            mem.remember_fix(
                error_pattern=issue_title,
                fix_command=fix_command,
                context=f"Auto-learned: resolved '{issue_title}'",
            )
            learned.append({"resolvedIssue": issue_title, "creditedCommand": fix_command})

        return learned
    except Exception:
        return []


def _learn_from_inspect(ctx: click.Context, result: dict[str, Any]) -> None:
    """Silently cache project structure facts from a workflow-inspect result."""
    try:
        state = ctx.obj.backend.session_store.load()
        mem = memory_for_session(state)
        if mem is None:
            return

        project = result.get("project") or {}
        ping = result.get("ping") or {}
        summary = result.get("summary") or {}
        assets = result.get("assets") or {}

        # Render pipeline
        pipeline = project.get("renderPipeline") or project.get("currentRenderPipeline")
        if pipeline:
            mem.remember_structure("render_pipeline", pipeline)

        # Unity version
        version = ping.get("unityVersion") or project.get("unityVersion")
        if version:
            mem.remember_structure("unity_version", version)

        # Project name
        name = summary.get("projectName") or project.get("productName")
        if name:
            mem.remember_structure("project_name", name)

        # Installed packages (compact list of name:version)
        packages = project.get("packages") or project.get("installedPackages")
        if isinstance(packages, list) and packages:
            pkg_summary = []
            for pkg in packages:
                if isinstance(pkg, dict):
                    pkg_name = pkg.get("name") or pkg.get("packageId") or ""
                    pkg_ver = pkg.get("version") or ""
                    if pkg_name:
                        pkg_summary.append(f"{pkg_name}@{pkg_ver}" if pkg_ver else pkg_name)
                elif isinstance(pkg, str):
                    pkg_summary.append(pkg)
            if pkg_summary:
                mem.remember_structure("packages", pkg_summary)

        # Script directories seen in asset listing
        sampled = assets.get("sampled") or []
        script_dirs: set[str] = set()
        for item in sampled:
            path = item.get("path") or item.get("name") or "" if isinstance(item, dict) else str(item)
            if path.endswith(".cs"):
                parts = path.replace("\\", "/").rsplit("/", 1)
                if len(parts) == 2:
                    script_dirs.add(parts[0])
        if script_dirs:
            mem.remember_structure("script_directories", sorted(script_dirs))

        # Active scene
        active_scene = summary.get("activeScene")
        if active_scene:
            mem.remember_structure("last_active_scene", active_scene)

    except Exception:
        # Memory learning is best-effort — never break the inspect workflow.
        pass
