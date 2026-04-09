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
from click.core import ParameterSource

from . import __version__
from .core.agent_profiles import AgentProfile, AgentProfileStore, derive_agent_profiles_path
from .core.client import UnityMCPClient, UnityMCPClientError
from .core.debug_dashboard import DashboardConfig, serve_debug_dashboard
from .core.debug_doctor import build_debug_doctor_report
from .core.session import SessionStore
from .core.workflows import (
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
from .utils.output import format_output, load_json_params, load_text_value
from .utils.unity_mcp_backend import (
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
    agent_id: str
    agent_profile: AgentProfile | None
    agent_source: str
    legacy_mode: bool


def _emit(ctx: click.Context, value: Any) -> None:
    click.echo(format_output(value, ctx.obj.json_output))


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
        command_path=_normalized_command_path(ctx),
        activity=activity,
    )
    _emit_auto_breadcrumb(ctx, stage="start", level="info")
    try:
        result = callback()
    except (BackendSelectionError, UnityMCPClientError, ValueError) as exc:
        _emit_auto_breadcrumb(ctx, stage="error", level="error", extra=str(exc))
        raise click.ClickException(str(exc)) from exc
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


def _slugify_agent_profile_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "sidecar"


def _suggest_agent_id(profile_name: str) -> str:
    return f"cli-anything-unity-mcp-{_slugify_agent_profile_name(profile_name)}-{socket.gethostname()}"


def _serialize_agent_profile(profile: AgentProfile | None) -> dict[str, Any] | None:
    return asdict(profile) if profile is not None else None


def _build_base_args(
    host: str,
    default_port: int,
    registry_path: Path | None,
    session_path: Path | None,
    agent_profiles_path: Path | None,
    json_output: bool,
    agent_id: str | None,
    agent_profile: str | None,
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
    if json_output:
        parts.append("--json")
    if agent_profile:
        parts.extend(["--agent-profile", agent_profile])
    if legacy:
        parts.append("--legacy")
    return tuple(parts)


def _run_repl(ctx: click.Context) -> None:
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


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)
@click.version_option(version=__version__)
@click.option(
    "--host",
    default=lambda: os.environ.get("UNITY_BRIDGE_HOST", "127.0.0.1"),
    show_default=True,
    help="Unity bridge host.",
)
@click.option(
    "--default-port",
    type=int,
    default=lambda: int(os.environ.get("UNITY_BRIDGE_PORT", "7890")),
    show_default=True,
    help="Fallback Unity bridge port.",
)
@click.option(
    "--registry-path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Override the Unity instance registry path.",
)
@click.option(
    "--session-path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Override the CLI session state path.",
)
@click.option(
    "--agent-profiles-path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Override the saved agent profile store path.",
)
@click.option(
    "--port-range-start",
    type=int,
    default=lambda: int(os.environ.get("UNITY_PORT_RANGE_START", "7890")),
    show_default=True,
    help="First port to scan when discovering Unity instances.",
)
@click.option(
    "--port-range-end",
    type=int,
    default=lambda: int(os.environ.get("UNITY_PORT_RANGE_END", "7899")),
    show_default=True,
    help="Last port to scan when discovering Unity instances.",
)
@click.option(
    "--agent-profile",
    default=None,
    help="Use a saved optional agent profile by name.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Emit machine-readable JSON output.",
)
@click.option(
    "--agent-id",
    default=None,
    help="Override the agent identifier sent to the Unity queue headers. If omitted, the CLI uses the selected agent profile or a hostname+pid based default.",
)
@click.option(
    "--legacy",
    is_flag=True,
    help="Bypass queue mode and use legacy direct POST requests.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    host: str,
    default_port: int,
    registry_path: Path | None,
    session_path: Path | None,
    agent_profiles_path: Path | None,
    port_range_start: int,
    port_range_end: int,
    agent_profile: str | None,
    json_output: bool,
    agent_id: str | None,
    legacy: bool,
) -> None:
    """Direct CLI client for Unity projects using the AnkleBreaker Unity MCP editor bridge."""
    profile_store = _build_agent_profile_store(session_path, agent_profiles_path)
    requested_profile_name = agent_profile or profile_store.load().selected_profile
    resolved_profile = profile_store.get_profile(requested_profile_name) if requested_profile_name else None
    if requested_profile_name and resolved_profile is None:
        raise click.ClickException(f"Agent profile `{requested_profile_name}` was not found.")

    agent_id_source = ctx.get_parameter_source("agent_id")
    legacy_source = ctx.get_parameter_source("legacy")

    if agent_id_source != ParameterSource.DEFAULT and agent_id:
        resolved_agent_id = agent_id
        agent_source = "explicit"
    elif resolved_profile is not None:
        resolved_agent_id = resolved_profile.agent_id
        agent_source = "profile"
    else:
        resolved_agent_id = _default_agent_id()
        agent_source = "generated"

    if legacy_source != ParameterSource.DEFAULT:
        resolved_legacy = legacy
    elif resolved_profile is not None:
        resolved_legacy = resolved_profile.legacy
    else:
        resolved_legacy = False

    client = UnityMCPClient(
        host=host,
        agent_id=resolved_agent_id,
        use_queue=not resolved_legacy,
    )
    backend = UnityMCPBackend(
        client=client,
        session_store=SessionStore(session_path) if session_path else SessionStore(),
        registry_path=registry_path or get_default_registry_path(),
        default_port=default_port,
        port_range_start=port_range_start,
        port_range_end=port_range_end,
    )
    ctx.obj = CLIContext(
        backend=backend,
        json_output=json_output,
        base_args=_build_base_args(
            host=host,
            default_port=default_port,
            registry_path=registry_path,
            session_path=session_path,
            agent_profiles_path=agent_profiles_path,
            json_output=json_output,
            agent_id=resolved_agent_id if agent_source != "profile" else None,
            agent_profile=resolved_profile.name if resolved_profile else None,
            legacy=resolved_legacy,
            port_range_start=port_range_start,
            port_range_end=port_range_end,
        ),
        command_path=ctx.command_path or "cli-anything-unity-mcp",
        agent_profile_store=profile_store,
        agent_id=resolved_agent_id,
        agent_profile=resolved_profile,
        agent_source=agent_source,
        legacy_mode=resolved_legacy,
    )
    if ctx.invoked_subcommand is None:
        _run_repl(ctx)


@cli.command("instances")
@click.pass_context
def instances_command(ctx: click.Context) -> None:
    """List running Unity Editor instances."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.list_instances())


@cli.command("select")
@click.argument("port", type=int)
@click.pass_context
def select_command(ctx: click.Context, port: int) -> None:
    """Select a Unity instance by port."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.select_instance(port))


@cli.command("status")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def status_command(ctx: click.Context, port: int | None) -> None:
    """Show selected instance, ping info, and history size."""

    def _callback() -> dict[str, Any]:
        session = ctx.obj.backend.session_store.load()
        payload = {
            "selectedPort": session.selected_port,
            "selectedInstance": session.selected_instance,
            "historyCount": len(session.history),
            "agent": {
                "agentId": ctx.obj.agent_id,
                "profile": _serialize_agent_profile(ctx.obj.agent_profile),
                "source": ctx.obj.agent_source,
                "legacy": ctx.obj.legacy_mode,
            },
        }
        try:
            payload["ping"] = ctx.obj.backend.ping(port=port)
        except (BackendSelectionError, UnityMCPClientError) as exc:
            payload["pingError"] = str(exc)
        return payload

    _run_and_emit(ctx, _callback)


@cli.group("agent")
def agent_group() -> None:
    """Manage optional sidecar agent profiles and inspect live queue sessions."""


@agent_group.command("current")
@click.pass_context
def agent_current_command(ctx: click.Context) -> None:
    """Show the resolved agent identity for this CLI invocation."""

    def _callback() -> dict[str, Any]:
        state = ctx.obj.agent_profile_store.list_profiles()
        return {
            "resolved": {
                "agentId": ctx.obj.agent_id,
                "profile": _serialize_agent_profile(ctx.obj.agent_profile),
                "source": ctx.obj.agent_source,
                "legacy": ctx.obj.legacy_mode,
            },
            "selectedProfile": state.selected_profile,
            "savedProfileCount": len(state.profiles),
        }

    _run_and_emit(ctx, _callback)


@agent_group.command("list")
@click.pass_context
def agent_list_command(ctx: click.Context) -> None:
    """List saved optional agent profiles."""

    def _callback() -> dict[str, Any]:
        state = ctx.obj.agent_profile_store.list_profiles()
        return {
            "selectedProfile": state.selected_profile,
            "profiles": [
                {
                    **asdict(profile),
                    "isSelected": bool(state.selected_profile and state.selected_profile.lower() == profile.name.lower()),
                }
                for profile in state.profiles
            ],
            "count": len(state.profiles),
        }

    _run_and_emit(ctx, _callback)


@agent_group.command("save")
@click.argument("name")
@click.option("--agent-id", "profile_agent_id", default=None, help="Agent ID to persist for this profile.")
@click.option(
    "--role",
    type=click.Choice(["builder", "reviewer", "tester", "researcher", "custom"], case_sensitive=False),
    default="custom",
    show_default=True,
    help="Short role label for this optional sidecar agent.",
)
@click.option("--description", default="", help="Optional human-readable description.")
@click.option("--legacy/--queue", "profile_legacy", default=False, show_default=True, help="Whether this profile should bypass queue mode.")
@click.option("--select/--no-select", default=True, show_default=True, help="Select this profile for future CLI runs.")
@click.pass_context
def agent_save_command(
    ctx: click.Context,
    name: str,
    profile_agent_id: str | None,
    role: str,
    description: str,
    profile_legacy: bool,
    select: bool,
) -> None:
    """Create or update a saved optional agent profile."""

    def _callback() -> dict[str, Any]:
        effective_agent_id = profile_agent_id or _suggest_agent_id(name)
        state = ctx.obj.agent_profile_store.upsert_profile(
            name=name,
            agent_id=effective_agent_id,
            role=role.lower(),
            description=description,
            legacy=profile_legacy,
            select=select,
        )
        profile = ctx.obj.agent_profile_store.get_profile(name)
        return {
            "success": True,
            "message": f"Saved agent profile `{name}`.",
            "profile": _serialize_agent_profile(profile),
            "selectedProfile": state.selected_profile,
        }

    _run_and_emit(ctx, _callback)


@agent_group.command("use")
@click.argument("name")
@click.pass_context
def agent_use_command(ctx: click.Context, name: str) -> None:
    """Select a saved agent profile for future CLI runs."""

    def _callback() -> dict[str, Any]:
        state = ctx.obj.agent_profile_store.select_profile(name)
        profile = ctx.obj.agent_profile_store.get_profile(name)
        return {
            "success": True,
            "message": f"Selected agent profile `{name}`.",
            "selectedProfile": state.selected_profile,
            "profile": _serialize_agent_profile(profile),
        }

    _run_and_emit(ctx, _callback)


@agent_group.command("clear")
@click.pass_context
def agent_clear_command(ctx: click.Context) -> None:
    """Clear the selected saved agent profile."""

    def _callback() -> dict[str, Any]:
        state = ctx.obj.agent_profile_store.clear_selection()
        return {
            "success": True,
            "message": "Cleared the selected agent profile.",
            "selectedProfile": state.selected_profile,
        }

    _run_and_emit(ctx, _callback)


@agent_group.command("remove")
@click.argument("name")
@click.pass_context
def agent_remove_command(ctx: click.Context, name: str) -> None:
    """Delete a saved agent profile."""

    def _callback() -> dict[str, Any]:
        state = ctx.obj.agent_profile_store.remove_profile(name)
        return {
            "success": True,
            "message": f"Removed agent profile `{name}`.",
            "selectedProfile": state.selected_profile,
            "count": len(state.profiles),
        }

    _run_and_emit(ctx, _callback)


@agent_group.command("sessions")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def agent_sessions_command(ctx: click.Context, port: int | None) -> None:
    """List live Unity-side agent sessions if the bridge exposes them."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.call_tool("unity_agents_list", port=port))


@agent_group.command("log")
@click.argument("agent_id")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def agent_log_command(ctx: click.Context, agent_id: str, port: int | None) -> None:
    """Read the Unity-side action log for a specific agent ID."""
    _run_and_emit(
        ctx,
        lambda: ctx.obj.backend.call_tool("unity_agent_log", params={"agentId": agent_id}, port=port),
    )


@agent_group.command("queue")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def agent_queue_command(ctx: click.Context, port: int | None) -> None:
    """Show current Unity queue status for multi-agent work."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.get_queue_info(port=port))


@agent_group.command("watch")
@click.option("--iterations", type=int, default=3, show_default=True, help="How many samples to capture.")
@click.option("--interval", type=float, default=1.0, show_default=True, help="Seconds to wait between samples.")
@click.option("--console-count", type=int, default=20, show_default=True, help="How many Unity console entries to include per sample.")
@click.option("--include-hierarchy", is_flag=True, help="Include a shallow hierarchy snapshot in each sampled debug bundle.")
@click.option(
    "--watch-agent-id",
    type=str,
    default=None,
    help="Optional Unity-side agent ID to fetch log entries for. Defaults to the current CLI agent ID.",
)
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def agent_watch_command(
    ctx: click.Context,
    iterations: int,
    interval: float,
    console_count: int,
    include_hierarchy: bool,
    watch_agent_id: str | None,
    port: int | None,
) -> None:
    """Sample queue, sessions, logs, and debug snapshots over time so multi-agent work is visible."""

    def _callback() -> dict[str, Any]:
        if iterations < 1:
            raise ValueError("--iterations must be at least 1.")
        if interval < 0:
            raise ValueError("--interval cannot be negative.")

        selected_watch_agent_id = watch_agent_id or ctx.obj.agent_id

        def _safe_fetch(fetcher: Callable[[], dict[str, Any]]) -> dict[str, Any]:
            try:
                return fetcher()
            except (BackendSelectionError, UnityMCPClientError, ValueError) as exc:
                return {"error": str(exc)}

        samples: list[dict[str, Any]] = []
        for index in range(iterations):
            snapshot = ctx.obj.backend.get_debug_snapshot(
                port=port,
                console_count=console_count,
                message_type="all",
                issue_limit=20,
                include_hierarchy=include_hierarchy,
            )
            sessions = _safe_fetch(lambda: ctx.obj.backend.call_tool("unity_agents_list", port=port))
            agent_log = _safe_fetch(
                lambda: ctx.obj.backend.call_tool(
                    "unity_agent_log",
                    params={"agentId": selected_watch_agent_id},
                    port=port,
                )
            )

            sample = {
                "index": index + 1,
                "capturedAt": datetime.now(UTC).isoformat(),
                "summary": snapshot.get("summary"),
                "consoleSummary": snapshot.get("consoleSummary"),
                "queue": snapshot.get("queue"),
                "sessions": sessions,
                "watchedAgentId": selected_watch_agent_id,
                "agentLog": agent_log,
            }
            if include_hierarchy and "hierarchy" in snapshot:
                sample["hierarchy"] = snapshot["hierarchy"]
            samples.append(sample)

            if index + 1 < iterations and interval > 0:
                time.sleep(interval)

        latest = samples[-1] if samples else {}
        return {
            "title": "Unity Agent Watch",
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
                "includeHierarchy": include_hierarchy,
                "watchedAgentId": selected_watch_agent_id,
                "port": ((latest.get("summary") or {}).get("port")),
            },
            "latest": latest,
            "samples": samples,
        }

    _run_and_emit(ctx, _callback)


@cli.group("debug")
def debug_group() -> None:
    """Collect richer Unity debugging snapshots and ready-made debug command templates."""


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
        payload["actor"] = payload.get("agentProfile") or payload.get("agentId")
        payload["amount"] = None
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

    payload["phase"] = phase
    payload["summary"] = summary
    payload["target"] = target
    payload["actor"] = payload.get("agentProfile") or payload.get("agentId")
    if amount:
        payload["amount"] = amount
    return payload


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
@click.option("--command-contains", type=str, default=None, help="Only include entries whose command contains this text.")
@click.option("--agent-id", "filter_agent_id", type=str, default=None, help="Only include entries recorded for this agent ID.")
@click.option("--clear", "clear_history", is_flag=True, help="Clear the stored CLI trace after printing.")
@click.pass_context
def debug_trace_command(
    ctx: click.Context,
    tail: int,
    status: str | None,
    command_contains: str | None,
    filter_agent_id: str | None,
    clear_history: bool,
) -> None:
    """Show recent CLI route/tool attempts with status, timing, and errors."""

    def _callback() -> dict[str, Any]:
        history = ctx.obj.backend.get_history()
        entries = _filter_history_entries(
            history,
            tail=tail,
            status=status,
            command_contains=command_contains,
            agent_id=filter_agent_id,
        )
        rendered_entries = [_humanize_history_entry(entry) for entry in entries]
        payload = {
            "title": "Unity CLI Trace",
            "count": len(rendered_entries),
            "tail": tail,
            "filters": {
                "status": status,
                "commandContains": command_contains,
                "agentId": filter_agent_id,
            },
            "entries": rendered_entries,
            "agent": {
                "agentId": ctx.obj.agent_id,
                "profile": _serialize_agent_profile(ctx.obj.agent_profile),
                "source": ctx.obj.agent_source,
                "legacy": ctx.obj.legacy_mode,
            },
        }
        if clear_history:
            ctx.obj.backend.clear_history()
            payload["cleared"] = True
        return payload

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
        report = build_debug_doctor_report(
            payload,
            history_before[-max(0, recent_commands):] if recent_commands > 0 else [],
            selected_port,
        )
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


@cli.command("ping")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def ping_command(ctx: click.Context, port: int | None) -> None:
    """Ping the selected or auto-discovered Unity instance."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.ping(port=port))


@cli.command("state")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def state_command(ctx: click.Context, port: int | None) -> None:
    """Fetch Unity editor state."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.call_route("editor/state", port=port))


@cli.command("project-info")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def project_info_command(ctx: click.Context, port: int | None) -> None:
    """Fetch project information."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.call_route("project/info", port=port))


@cli.command("scene-info")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def scene_info_command(ctx: click.Context, port: int | None) -> None:
    """Fetch active scene details."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.call_route("scene/info", port=port))


@cli.command("scene-open")
@click.argument("path")
@click.option("--save-if-dirty", is_flag=True, help="Save the dirty active scene before opening the target scene.")
@click.option("--discard-unsaved", is_flag=True, help="Discard unsaved changes instead of triggering Unity's save prompt.")
@click.option("--force-reload", is_flag=True, help="Reload even if the target scene is already open.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def scene_open_command(
    ctx: click.Context,
    path: str,
    save_if_dirty: bool,
    discard_unsaved: bool,
    force_reload: bool,
    port: int | None,
) -> None:
    """Open a scene with explicit dirty-scene behavior."""

    def _callback() -> Any:
        if save_if_dirty and discard_unsaved:
            raise ValueError("Choose either --save-if-dirty or --discard-unsaved, not both.")
        params: dict[str, Any] = {"path": path}
        if save_if_dirty:
            params["saveIfDirty"] = True
        if discard_unsaved:
            params["discardUnsaved"] = True
        if force_reload:
            params["forceReload"] = True
        return ctx.obj.backend.call_route("scene/open", params=params, port=port)

    _run_and_emit(ctx, _callback)


@cli.command("scene-save")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def scene_save_command(ctx: click.Context, port: int | None) -> None:
    """Save the active scene."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.call_route("scene/save", port=port))


@cli.command("hierarchy")
@click.option("--max-depth", type=int, default=None, help="Limit hierarchy depth.")
@click.option("--max-nodes", type=int, default=None, help="Limit node count.")
@click.option("--parent-path", type=str, default=None, help="Return only a subtree under this GameObject path.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def hierarchy_command(
    ctx: click.Context,
    max_depth: int | None,
    max_nodes: int | None,
    parent_path: str | None,
    port: int | None,
) -> None:
    """Fetch the current scene hierarchy tree."""
    params = {
        "maxDepth": max_depth,
        "maxNodes": max_nodes,
        "parentPath": parent_path,
    }
    params = {key: value for key, value in params.items() if value is not None}
    _run_and_emit(ctx, lambda: ctx.obj.backend.call_route("scene/hierarchy", params=params, port=port))


@cli.command("console")
@click.option("--count", type=int, default=None, help="How many log entries to fetch.")
@click.option(
    "--type",
    "message_type",
    type=click.Choice(["all", "info", "warning", "error"], case_sensitive=False),
    default=None,
    help="Optional log severity filter.",
)
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def console_command(
    ctx: click.Context,
    count: int | None,
    message_type: str | None,
    port: int | None,
) -> None:
    """Fetch recent Unity console messages."""
    params = {"count": count, "type": message_type}
    params = {key: value for key, value in params.items() if value is not None}
    _run_and_emit(ctx, lambda: ctx.obj.backend.call_route("console/log", params=params, port=port))


@cli.command("play")
@click.argument("action", type=click.Choice(["play", "pause", "stop"], case_sensitive=False))
@click.option("--wait/--no-wait", default=True, help="Poll editor state until the requested play transition settles.")
@click.option("--timeout", type=float, default=20.0, show_default=True, help="Seconds to wait for the requested state transition.")
@click.option("--interval", type=float, default=0.25, show_default=True, help="Polling interval while waiting.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def play_command(
    ctx: click.Context,
    action: str,
    wait: bool,
    timeout: float,
    interval: float,
    port: int | None,
) -> None:
    """Control Unity play mode."""

    def _callback() -> Any:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        command_result = ctx.obj.backend.call_route_with_recovery(
            "editor/play-mode",
            params={"action": action},
            port=workflow_port,
            recovery_timeout=max(timeout, 10.0),
            recovery_interval=max(0.25, interval),
        )
        if action == "pause" or not wait:
            return command_result

        deadline = time.monotonic() + timeout
        final_state: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            try:
                final_state = ctx.obj.backend.call_route_with_recovery(
                    "editor/state",
                    port=workflow_port,
                    record_history=False,
                    recovery_timeout=max(interval, 1.0),
                    recovery_interval=max(0.25, interval),
                )
            except (BackendSelectionError, UnityMCPClientError):
                time.sleep(interval)
                continue
            state_payload = final_state or {}
            is_playing = bool(state_payload.get("isPlaying"))
            is_transitioning = bool(state_payload.get("isPlayingOrWillChangePlaymode"))
            if action == "play" and is_playing:
                return {
                    "command": command_result,
                    "state": state_payload,
                    "waited": True,
                }
            if action == "stop" and (not is_playing) and (not is_transitioning):
                return {
                    "command": command_result,
                    "state": state_payload,
                    "waited": True,
                }
            time.sleep(interval)

        return {
            "command": command_result,
            "state": final_state or {},
            "waited": True,
            "timedOut": True,
            "message": f"Timed out waiting for play action '{action}' to settle.",
        }

    _run_and_emit(ctx, _callback)


@cli.command("build")
@click.option(
    "--target",
    type=click.Choice(
        [
            "StandaloneWindows64",
            "StandaloneOSX",
            "StandaloneLinux64",
            "Android",
            "iOS",
            "WebGL",
        ],
        case_sensitive=False,
    ),
    required=True,
    help="Unity build target.",
)
@click.option("--output-path", required=True, help="Build output path.")
@click.option("--scene", "scenes", multiple=True, help="Scene asset paths to include.")
@click.option("--development-build", is_flag=True, help="Enable development build mode.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def build_command(
    ctx: click.Context,
    target: str,
    output_path: str,
    scenes: tuple[str, ...],
    development_build: bool,
    port: int | None,
) -> None:
    """Start a Unity build."""
    params: dict[str, Any] = {
        "target": target,
        "outputPath": output_path,
        "developmentBuild": development_build,
    }
    if scenes:
        params["scenes"] = list(scenes)
    _run_and_emit(ctx, lambda: ctx.obj.backend.call_route("build/start", params=params, port=port))


@cli.command("script-read")
@click.argument("path")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def script_read_command(ctx: click.Context, path: str, port: int | None) -> None:
    """Read a C# script asset."""
    _run_and_emit(
        ctx,
        lambda: ctx.obj.backend.call_route("script/read", params={"path": path}, port=port),
    )


@cli.command("script-update")
@click.argument("path")
@click.option("--content", type=str, default=None, help="Inline script source.")
@click.option(
    "--file",
    "content_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Read script source from a file.",
)
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def script_update_command(
    ctx: click.Context,
    path: str,
    content: str | None,
    content_file: Path | None,
    port: int | None,
) -> None:
    """Replace an existing C# script asset."""

    def _callback() -> Any:
        body = load_text_value(content=content, file_path=content_file, required=True)
        return ctx.obj.backend.call_route(
            "script/update",
            params={"path": path, "content": body},
            port=port,
        )

    _run_and_emit(ctx, _callback)


@cli.command("script-create")
@click.argument("path")
@click.option("--content", type=str, default=None, help="Inline script source.")
@click.option(
    "--file",
    "content_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Read script source from a file.",
)
@click.option("--class-name", type=str, default=None, help="Optional explicit class name.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def script_create_command(
    ctx: click.Context,
    path: str,
    content: str | None,
    content_file: Path | None,
    class_name: str | None,
    port: int | None,
) -> None:
    """Create a new C# script asset."""

    def _callback() -> Any:
        body = load_text_value(content=content, file_path=content_file, required=True)
        params: dict[str, Any] = {"path": path, "content": body}
        if class_name:
            params["className"] = class_name
        return ctx.obj.backend.call_route("script/create", params=params, port=port)

    _run_and_emit(ctx, _callback)


@cli.command("execute-code")
@click.option("--code", type=str, default=None, help="Inline C# method-body code.")
@click.option(
    "--file",
    "code_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Read C# code from a file.",
)
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def execute_code_command(
    ctx: click.Context,
    code: str | None,
    code_file: Path | None,
    port: int | None,
) -> None:
    """Execute arbitrary C# editor code."""

    def _callback() -> Any:
        body = load_text_value(content=code, file_path=code_file, required=True)
        return ctx.obj.backend.call_route(
            "editor/execute-code",
            params={"code": body},
            port=port,
        )

    _run_and_emit(ctx, _callback)


@cli.command("undo")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def undo_command(ctx: click.Context, port: int | None) -> None:
    """Undo the last Unity operation."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.call_route("undo/perform", port=port))


@cli.command("redo")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def redo_command(ctx: click.Context, port: int | None) -> None:
    """Redo the last undone Unity operation."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.call_route("undo/redo", port=port))


@cli.command("context")
@click.argument("category", required=False)
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def context_command(ctx: click.Context, category: str | None, port: int | None) -> None:
    """Fetch project context payloads from the Unity bridge."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.get_context(category=category, port=port))


@cli.command("routes")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def routes_command(ctx: click.Context, port: int | None) -> None:
    """List live HTTP routes published by the Unity plugin."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.get_routes(port=port))


@cli.command("tools")
@click.option("--category", type=str, default=None, help="Optional category filter.")
@click.option(
    "--tier",
    type=click.Choice(
        ["core", "advanced", "meta", "instance", "context", "hub", "dynamic", "derived"],
        case_sensitive=False,
    ),
    default=None,
    help="Optional tool tier filter.",
)
@click.option("--search", type=str, default=None, help="Filter by tool name or description text.")
@click.option("--include-unsupported", is_flag=True, help="Include tool names this CLI cannot execute yet, such as Unity Hub tools.")
@click.option("--live", is_flag=True, help="Query the connected Unity instance for live routes.")
@click.option(
    "--merged-live",
    is_flag=True,
    help="Merge the upstream tool catalog with the live Unity route list and mark live availability.",
)
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def tools_command(
    ctx: click.Context,
    category: str | None,
    tier: str | None,
    search: str | None,
    include_unsupported: bool,
    live: bool,
    merged_live: bool,
    port: int | None,
) -> None:
    """Browse CLI-known, upstream, or live Unity tool mappings."""
    if live:
        _run_and_emit(ctx, lambda: ctx.obj.backend.dynamic_tools(port=port, category=category))
        return
    _run_and_emit(
        ctx,
        lambda: ctx.obj.backend.list_upstream_tools(
            category=category,
            tier=tier,
            search=search,
            include_unsupported=include_unsupported,
            port=port,
            merge_live=merged_live,
        ),
    )


@cli.command("advanced-tools")
@click.option("--category", type=str, default=None, help="Optional advanced tool category filter.")
@click.option("--search", type=str, default=None, help="Filter by advanced tool name or description text.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def advanced_tools_command(
    ctx: click.Context,
    category: str | None,
    search: str | None,
    port: int | None,
) -> None:
    """List advanced tools in the same vocabulary used by the upstream MCP server."""
    _run_and_emit(
        ctx,
        lambda: ctx.obj.backend.list_advanced_tools(
            category=category,
            search=search,
            port=port,
            merge_live=True,
        ),
    )


@cli.command("tool-info")
@click.argument("tool_name")
@click.option("--port", type=int, default=None, help="Optionally check live availability against a specific Unity port.")
@click.pass_context
def tool_info_command(
    ctx: click.Context,
    tool_name: str,
    port: int | None,
) -> None:
    """Describe a tool name, including route mapping, tier, and input schema when known."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.get_tool_info(tool_name, port=port))


@cli.command("tool-coverage")
@click.option("--category", type=str, default=None, help="Optional category filter for the upstream catalog.")
@click.option(
    "--status",
    type=click.Choice(
        ["live-tested", "covered", "mock-only", "unsupported", "deferred"],
        case_sensitive=False,
    ),
    default=None,
    help="Filter by coverage status.",
)
@click.option("--search", type=str, default=None, help="Filter by tool name or description text.")
@click.option("--summary", "summary_only", is_flag=True, help="Return only summary counts.")
@click.option("--exclude-unsupported", is_flag=True, help="Hide tools marked unsupported in the upstream catalog.")
@click.pass_context
def tool_coverage_command(
    ctx: click.Context,
    category: str | None,
    status: str | None,
    search: str | None,
    summary_only: bool,
    exclude_unsupported: bool,
) -> None:
    """Report upstream tool coverage status across live-tested, covered, mock-only, unsupported, and deferred buckets."""
    _run_and_emit(
        ctx,
        lambda: ctx.obj.backend.get_tool_coverage(
            category=category,
            status=status,
            search=search,
            include_unsupported=not exclude_unsupported,
            summary_only=summary_only,
        ),
    )


@cli.command("tool-template")
@click.argument("tool_name")
@click.option("--include-optional", is_flag=True, help="Include optional fields in the generated template.")
@click.option("--port", type=int, default=None, help="Optionally check live availability against a specific Unity port.")
@click.pass_context
def tool_template_command(
    ctx: click.Context,
    tool_name: str,
    include_optional: bool,
    port: int | None,
) -> None:
    """Generate a compact JSON template for a tool's input schema."""
    _run_and_emit(
        ctx,
        lambda: ctx.obj.backend.get_tool_template(
            tool_name,
            include_optional=include_optional,
            port=port,
        ),
    )


@cli.command("queue-info")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def queue_info_command(ctx: click.Context, port: int | None) -> None:
    """Read queue statistics from the Unity plugin."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.get_queue_info(port=port))


@cli.command("route")
@click.argument("route_name")
@click.option("--params", type=str, default=None, help="Inline JSON object with route params.")
@click.option(
    "--params-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Read params from a JSON file.",
)
@click.option(
    "--param",
    "param_pairs",
    multiple=True,
    help="Add a top-level key=value param. Repeat as needed.",
)
@click.option("--get", "use_get", is_flag=True, help="Use direct GET instead of queued POST.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def route_command(
    ctx: click.Context,
    route_name: str,
    params: str | None,
    params_file: Path | None,
    param_pairs: tuple[str, ...],
    use_get: bool,
    port: int | None,
) -> None:
    """Call an arbitrary Unity bridge route."""

    def _callback() -> Any:
        payload = load_json_params(params_text=params, params_file=params_file, param_pairs=param_pairs)
        return ctx.obj.backend.call_route(
            route_name,
            params=payload,
            port=port,
            use_get=use_get,
        )

    _run_and_emit(ctx, _callback)


@cli.command("tool")
@click.argument("tool_name")
@click.option("--params", type=str, default=None, help="Inline JSON object with tool params.")
@click.option(
    "--params-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Read params from a JSON file.",
)
@click.option(
    "--param",
    "param_pairs",
    multiple=True,
    help="Add a top-level key=value param. Repeat as needed.",
)
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def tool_command(
    ctx: click.Context,
    tool_name: str,
    params: str | None,
    params_file: Path | None,
    param_pairs: tuple[str, ...],
    port: int | None,
) -> None:
    """Call a Unity tool name and let the harness resolve the backing route."""

    def _callback() -> Any:
        payload = load_json_params(params_text=params, params_file=params_file, param_pairs=param_pairs)
        return ctx.obj.backend.call_tool(tool_name, params=payload, port=port)

    _run_and_emit(ctx, _callback)


@cli.command("history")
@click.option("--tail", type=int, default=20, show_default=True, help="How many recent history entries to return.")
@click.option(
    "--status",
    type=click.Choice(["ok", "error"], case_sensitive=False),
    default=None,
    help="Optional status filter.",
)
@click.option("--command-contains", type=str, default=None, help="Only include entries whose command contains this text.")
@click.option("--clear", "clear_history", is_flag=True, help="Clear the stored command history after printing.")
@click.pass_context
def history_command(
    ctx: click.Context,
    tail: int,
    status: str | None,
    command_contains: str | None,
    clear_history: bool,
) -> None:
    """Show or clear the local CLI session history."""

    def _callback() -> dict[str, Any]:
        history = ctx.obj.backend.get_history()
        entries = _filter_history_entries(
            history,
            tail=tail,
            status=status,
            command_contains=command_contains,
        )
        payload = {
            "count": len(entries),
            "history": entries,
            "filters": {
                "tail": tail,
                "status": status,
                "commandContains": command_contains,
            },
        }
        if clear_history:
            ctx.obj.backend.clear_history()
            payload["cleared"] = True
        return payload

    _run_and_emit(ctx, _callback)


@cli.group("workflow")
def workflow_group() -> None:
    """High-level workflows that combine multiple Unity bridge actions safely."""


@workflow_group.command("inspect")
@click.option("--hierarchy-depth", type=int, default=2, show_default=True, help="Hierarchy depth for the snapshot.")
@click.option("--hierarchy-nodes", type=int, default=40, show_default=True, help="Maximum hierarchy nodes to include.")
@click.option("--asset-folder", type=str, default="Assets", show_default=True, help="Folder to sample assets from.")
@click.option("--asset-limit", type=int, default=20, show_default=True, help="Maximum number of assets to sample.")
@click.option("--asset-search", type=str, default=None, help="Optional asset search text.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_inspect_command(
    ctx: click.Context,
    hierarchy_depth: int,
    hierarchy_nodes: int,
    asset_folder: str,
    asset_limit: int,
    asset_search: str | None,
    port: int | None,
) -> None:
    """Collect a high-level snapshot of the active Unity project and scene."""

    def _callback() -> dict[str, Any]:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        _record_progress_step(ctx, "Checking Unity bridge ping", phase="check", port=workflow_port)
        ping = ctx.obj.backend.ping(port=workflow_port)
        _record_progress_step(ctx, "Checking project info", phase="inspect", port=workflow_port)
        project = ctx.obj.backend.call_route_with_recovery(
            "project/info",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        _record_progress_step(ctx, "Checking editor state", phase="check", port=workflow_port)
        state = ctx.obj.backend.call_route_with_recovery(
            "editor/state",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        _record_progress_step(ctx, "Inspecting active scene info", phase="inspect", port=workflow_port)
        scene = ctx.obj.backend.call_route_with_recovery(
            "scene/info",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        _record_progress_step(
            ctx,
            f"Inspecting scene hierarchy (depth {hierarchy_depth}, max {hierarchy_nodes} nodes)",
            phase="inspect",
            port=workflow_port,
        )
        hierarchy = ctx.obj.backend.call_route_with_recovery(
            "scene/hierarchy",
            params={"maxDepth": hierarchy_depth, "maxNodes": hierarchy_nodes},
            port=workflow_port,
            recovery_timeout=10.0,
        )

        asset_params: dict[str, Any] = {
            "folder": asset_folder,
            "recursive": True,
        }
        if asset_search:
            asset_params["search"] = asset_search
        asset_step = f"Listing assets in {asset_folder}"
        if asset_search:
            asset_step += f" matching '{asset_search}'"
        _record_progress_step(ctx, asset_step, phase="inspect", port=workflow_port)
        assets = ctx.obj.backend.call_route_with_recovery(
            "asset/list",
            params=asset_params,
            port=workflow_port,
            recovery_timeout=10.0,
        )
        asset_items = list((assets or {}).get("assets") or [])[:asset_limit]

        active_scene_name = scene.get("activeScene")
        scene_dirty = bool(state.get("sceneDirty"))
        if not scene_dirty:
            for entry in scene.get("scenes") or []:
                if isinstance(entry, dict) and entry.get("name") == active_scene_name:
                    scene_dirty = bool(entry.get("isDirty"))
                    break

        summary = {
            "projectName": ping.get("projectName") or project.get("projectName"),
            "projectPath": ping.get("projectPath") or state.get("projectPath"),
            "unityVersion": ping.get("unityVersion"),
            "port": ping.get("port"),
            "activeScene": active_scene_name or state.get("activeScene"),
            "sceneDirty": scene_dirty,
            "isPlaying": bool(state.get("isPlaying")),
            "isCompiling": bool((project or {}).get("isCompiling")),
            "returnedHierarchyNodes": hierarchy.get("returnedNodes"),
            "sampledAssetCount": len(asset_items),
        }

        return {
            "summary": summary,
            "ping": ping,
            "project": project,
            "editorState": state,
            "scene": scene,
            "hierarchy": hierarchy,
            "assets": {
                "folder": asset_folder,
                "search": asset_search,
                "count": assets.get("count"),
                "sampled": asset_items,
            },
        }

    _run_and_emit(ctx, _callback)


@workflow_group.command("create-behaviour")
@click.argument("name")
@click.option("--folder", type=str, default="Assets/Scripts/Codex", show_default=True, help="Asset folder for the generated C# script.")
@click.option("--namespace", type=str, default=None, help="Optional C# namespace for the generated script.")
@click.option("--object-name", type=str, default=None, help="Optional scene object name to create and attach the component to.")
@click.option("--attach/--no-attach", default=True, help="Create a scene object and attach the new component.")
@click.option("--timeout", type=float, default=30.0, show_default=True, help="Seconds to wait for compilation and attach retries.")
@click.option("--interval", type=float, default=0.5, show_default=True, help="Polling interval while waiting for Unity to settle.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_create_behaviour_command(
    ctx: click.Context,
    name: str,
    folder: str,
    namespace: str | None,
    object_name: str | None,
    attach: bool,
    timeout: float,
    interval: float,
    port: int | None,
) -> None:
    """Create a MonoBehaviour script and optionally attach it to a new GameObject."""

    def _callback() -> dict[str, Any]:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        class_name = sanitize_csharp_identifier(name)
        scene_object_name = object_name or class_name
        script_path = build_asset_path(folder, class_name)
        script_body = build_behaviour_script(class_name, namespace=namespace)
        created_object = False
        payload: dict[str, Any] = {
            "className": class_name,
            "scriptPath": script_path,
            "objectName": scene_object_name,
        }

        _record_progress_step(ctx, f"Creating script {Path(script_path).name}", phase="create", port=workflow_port)
        script_result = require_workflow_success(
            ctx.obj.backend.call_route(
                "script/create",
                params={"path": script_path, "content": script_body},
                port=workflow_port,
            ),
            f"Create script {script_path}",
        )
        payload["script"] = script_result

        def _fetch_compilation() -> dict[str, Any]:
            result = ctx.obj.backend.call_route_with_recovery(
                "compilation/errors",
                params={"count": 50},
                port=workflow_port,
                record_history=False,
                recovery_timeout=max(timeout, 10.0),
                recovery_interval=max(0.25, interval),
            )
            return require_workflow_success(result, "Read compilation status")

        _record_progress_step(ctx, "Waiting for Unity compilation to settle", phase="check", port=workflow_port)
        compilation = wait_for_compilation(_fetch_compilation, timeout=timeout, interval=interval)
        payload["compilation"] = compilation
        if int(compilation.get("count") or 0) > 0:
            entries = compilation.get("entries") or []
            first_entry = entries[0] if entries and isinstance(entries[0], dict) else {}
            first_message = first_entry.get("message") or "Unity reported compilation errors."
            raise ValueError(f"Create script {script_path} failed: {first_message}")

        if not attach:
            return payload

        try:
            _record_progress_step(ctx, f"Creating GameObject {scene_object_name}", phase="create", port=workflow_port)
            game_object = require_workflow_success(
                ctx.obj.backend.call_tool(
                    "unity_gameobject_create",
                    params={"name": scene_object_name, "primitiveType": "Empty"},
                    port=workflow_port,
                ),
                f"Create GameObject {scene_object_name}",
            )
            created_object = True
            payload["gameObject"] = game_object

            _record_progress_step(
                ctx,
                f"Attaching {class_name} to {scene_object_name}",
                phase="edit",
                port=workflow_port,
            )
            component_result = wait_for_result(
                lambda: ctx.obj.backend.call_tool(
                    "unity_component_add",
                    params={
                        "gameObjectPath": scene_object_name,
                        "componentType": class_name,
                    },
                    port=workflow_port,
                ),
                lambda result: workflow_error_message(result) is None,
                timeout=timeout,
                interval=interval,
            )
            payload["component"] = require_workflow_success(
                component_result,
                f"Attach component {class_name} to {scene_object_name}",
            )
            _record_progress_step(
                ctx,
                f"Inspecting component properties for {class_name}",
                phase="inspect",
                port=workflow_port,
            )
            payload["properties"] = require_workflow_success(
                ctx.obj.backend.call_tool(
                    "unity_component_get_properties",
                    params={
                        "gameObjectPath": scene_object_name,
                        "componentType": class_name,
                    },
                    port=workflow_port,
                ),
                f"Read component properties for {class_name}",
            )
            payload["editorState"] = ctx.obj.backend.call_route_with_recovery(
                "editor/state",
                port=workflow_port,
                record_history=False,
                recovery_timeout=10.0,
            )
            return payload
        except ValueError:
            if created_object:
                try:
                    ctx.obj.backend.call_tool(
                        "unity_gameobject_delete",
                        params={"gameObjectPath": scene_object_name},
                        port=workflow_port,
                    )
                    payload["cleanup"] = {"deletedGameObject": scene_object_name}
                except (BackendSelectionError, UnityMCPClientError, ValueError) as cleanup_exc:
                    payload["cleanup"] = {"deleteError": str(cleanup_exc)}
            raise

    _run_and_emit(ctx, _callback)


@workflow_group.command("reset-scene")
@click.option("--save-if-dirty", is_flag=True, help="Save the scene before reloading it.")
@click.option("--discard-unsaved", is_flag=True, help="Discard unsaved changes and reload the active scene.")
@click.option("--force-reload", is_flag=True, help="Reload even if the scene is already open and clean.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_reset_scene_command(
    ctx: click.Context,
    save_if_dirty: bool,
    discard_unsaved: bool,
    force_reload: bool,
    port: int | None,
) -> None:
    """Reload the active scene using the safe dirty-scene behavior."""

    def _callback() -> dict[str, Any]:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        if save_if_dirty and discard_unsaved:
            raise ValueError("Choose either --save-if-dirty or --discard-unsaved, not both.")

        _record_progress_step(ctx, "Inspecting active scene before reload", phase="inspect", port=workflow_port)
        scene_info = ctx.obj.backend.call_route_with_recovery(
            "scene/info",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        scene_path = get_active_scene_path(scene_info)
        params: dict[str, Any] = {"path": scene_path}
        if save_if_dirty:
            params["saveIfDirty"] = True
        if discard_unsaved:
            params["discardUnsaved"] = True
        if force_reload:
            params["forceReload"] = True

        _record_progress_step(ctx, f"Reloading scene {Path(scene_path).name}", phase="open", port=workflow_port)
        result = require_workflow_success(
            ctx.obj.backend.call_route_with_recovery(
                "scene/open",
                params=params,
                port=workflow_port,
                recovery_timeout=15.0,
            ),
            f"Reload scene {scene_path}",
        )
        payload: dict[str, Any] = {
            "scenePath": scene_path,
            "scene": scene_info,
            "result": result,
        }
        if not result.get("requiresDecision"):
            payload["editorState"] = ctx.obj.backend.call_route_with_recovery(
                "editor/state",
                port=workflow_port,
                record_history=False,
                recovery_timeout=10.0,
            )
        return payload

    _run_and_emit(ctx, _callback)


@workflow_group.command("audit-advanced")
@click.option(
    "--category",
    "categories",
    multiple=True,
    help="Limit the audit to one or more advanced categories such as graphics, memory, physics, profiler, sceneview, settings, testing, ui, audio, lighting, animation, input, shadergraph, terrain, or navmesh.",
)
@click.option(
    "--probe-backed/--no-probe-backed",
    default=True,
    help="Create disposable scene probes so graphics and physics tools can be exercised against real scene objects.",
)
@click.option("--prefix", type=str, default="CodexAdvancedAudit", show_default=True, help="Prefix used for temporary probe objects.")
@click.option("--save-if-dirty-start", is_flag=True, help="Save the active scene first if probe creation needs a clean rollback path.")
@click.option("--timeout", type=float, default=20.0, show_default=True, help="Seconds to wait for scene recovery and cleanup steps.")
@click.option("--interval", type=float, default=0.25, show_default=True, help="Polling interval while waiting for Unity to settle.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_audit_advanced_command(
    ctx: click.Context,
    categories: tuple[str, ...],
    probe_backed: bool,
    prefix: str,
    save_if_dirty_start: bool,
    timeout: float,
    interval: float,
    port: int | None,
) -> None:
    """Run a curated validation pass across safe advanced tools and report pass/fail results."""

    def _callback() -> dict[str, Any]:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        _record_progress_step(ctx, "Inspecting audit start scene state", phase="inspect", port=workflow_port)
        requested_categories = {item.strip().lower() for item in categories if item.strip()}
        scene_info = ctx.obj.backend.call_route_with_recovery(
            "scene/info",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        editor_state = ctx.obj.backend.call_route_with_recovery(
            "editor/state",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        scene_path = get_active_scene_path(scene_info)
        starting_dirty = bool(editor_state.get("sceneDirty"))
        saved_at_start = False

        def _category_allowed(name: str) -> bool:
            return not requested_categories or name.lower() in requested_categories

        scene_mutation_requested = probe_backed or any(
            _category_allowed(category) for category in ("ui", "lighting", "terrain")
        )

        if scene_mutation_requested and starting_dirty and not save_if_dirty_start:
            raise ValueError(
                "Advanced audits that create scene content require a clean starting scene. Save manually or rerun with --save-if-dirty-start."
            )
        if scene_mutation_requested and starting_dirty and save_if_dirty_start:
            _record_progress_step(ctx, f"Saving dirty scene {Path(scene_path).name}", phase="save", port=workflow_port)
            require_workflow_success(
                ctx.obj.backend.call_route_with_recovery(
                    "scene/save",
                    port=workflow_port,
                    recovery_timeout=15.0,
                ),
                f"Save dirty scene {scene_path}",
            )
            editor_state = ctx.obj.backend.call_route_with_recovery(
                "editor/state",
                port=workflow_port,
                record_history=False,
                recovery_timeout=10.0,
            )
            starting_dirty = bool(editor_state.get("sceneDirty"))
            saved_at_start = True

        sample_root = unique_probe_name(prefix)
        sample_object_names = {
            "root": sample_root,
            "floor": f"{sample_root}_Floor",
            "probe": f"{sample_root}_Probe",
        }
        created_sample = False
        scene_mutated = False
        created_assets: list[str] = []
        failure_message: str | None = None

        payload: dict[str, Any] = {
            "before": {
                "scene": scene_info,
                "editorState": editor_state,
                "scenePath": scene_path,
                "savedAtStart": saved_at_start,
            },
            "requestedCategories": sorted(requested_categories),
            "probeBacked": probe_backed,
            "probes": [],
            "probeFixture": None,
        }

        def _call_tool(
            tool_name: str,
            action: str,
            params: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return require_workflow_success(
                ctx.obj.backend.call_tool(tool_name, params=params, port=workflow_port),
                action,
            )

        def _fetch_editor_state() -> dict[str, Any]:
            result = ctx.obj.backend.call_route_with_recovery(
                "editor/state",
                port=workflow_port,
                record_history=False,
                recovery_timeout=max(timeout, 10.0),
                recovery_interval=max(0.1, interval),
            )
            return result or {}

        def _record_probe(
            category: str,
            tool_name: str,
            description: str,
            params: dict[str, Any] | None = None,
            *,
            skip_reason: str | None = None,
        ) -> dict[str, Any]:
            entry: dict[str, Any] = {
                "category": category,
                "tool": tool_name,
                "description": description,
            }
            if params:
                entry["params"] = params
            if skip_reason:
                entry["status"] = "skipped"
                entry["skipReason"] = skip_reason
                payload["probes"].append(entry)
                return
            try:
                _record_progress_step(
                    ctx,
                    f"Probing {category} via {tool_name}",
                    phase="inspect",
                    port=workflow_port,
                )
                result = _call_tool(tool_name, description, params or {})
                entry["status"] = "passed"
                entry["result"] = result
            except (BackendSelectionError, UnityMCPClientError, ValueError) as exc:
                entry["status"] = "failed"
                entry["error"] = str(exc)
            payload["probes"].append(entry)
            return entry

        def _note_asset(asset_path: str | None) -> None:
            if not asset_path:
                return
            if asset_path not in created_assets:
                created_assets.append(asset_path)

        read_only_probes = [
            ("memory", "unity_memory_status", "Inspect memory profiler status", {}),
            ("graphics", "unity_graphics_lighting_summary", "Summarize scene lighting", {}),
            ("sceneview", "unity_sceneview_info", "Inspect scene view camera state", {}),
            ("settings", "unity_settings_quality", "Inspect quality settings", {}),
            ("settings", "unity_settings_time", "Inspect time settings", {}),
            ("profiler", "unity_profiler_stats", "Inspect rendering profiler stats", {}),
            ("audio", "unity_audio_info", "Inspect scene audio sources and listeners", {}),
            ("navmesh", "unity_navmesh_info", "Inspect NavMesh availability and agent types", {}),
            ("shadergraph", "unity_shadergraph_status", "Inspect installed Shader Graph support", {}),
            (
                "testing",
                "unity_testing_list_tests",
                "List available Unity tests",
                {"mode": "EditMode", "maxResults": 20},
            ),
        ]

        try:
            for category, tool_name, description, params in read_only_probes:
                if _category_allowed(category):
                    _record_probe(category, tool_name, description, params)

            if probe_backed:
                sample_payload: dict[str, Any] = {"rootName": sample_root, "objects": {}}
                sample_payload["objects"]["root"] = _call_tool(
                    "unity_gameobject_create",
                    f"Create advanced-audit root {sample_root}",
                    {
                        "name": sample_object_names["root"],
                        "primitiveType": "Empty",
                        "position": vec3(0, 0, 0),
                    },
                )
                sample_payload["objects"]["floor"] = _call_tool(
                    "unity_gameobject_create",
                    f"Create advanced-audit floor {sample_object_names['floor']}",
                    {
                        "name": sample_object_names["floor"],
                        "primitiveType": "Plane",
                        "parent": sample_object_names["root"],
                        "position": vec3(0, 0, 0),
                        "scale": vec3(2.0, 1.0, 2.0),
                    },
                )
                sample_payload["objects"]["probe"] = _call_tool(
                    "unity_gameobject_create",
                    f"Create advanced-audit probe {sample_object_names['probe']}",
                    {
                        "name": sample_object_names["probe"],
                        "primitiveType": "Sphere",
                        "parent": sample_object_names["root"],
                        "position": vec3(0, 1, 0),
                    },
                )
                created_sample = True
                scene_mutated = True
                payload["probeFixture"] = sample_payload

                sample_probes = [
                    (
                        "graphics",
                        "unity_graphics_renderer_info",
                        "Inspect renderer info on the sample probe",
                        {"objectPath": sample_object_names["probe"]},
                    ),
                    (
                        "graphics",
                        "unity_graphics_mesh_info",
                        "Inspect mesh info on the sample probe",
                        {"objectPath": sample_object_names["probe"]},
                    ),
                    (
                        "graphics",
                        "unity_graphics_material_info",
                        "Inspect material info on the sample probe",
                        {"objectPath": sample_object_names["probe"], "includePreview": False},
                    ),
                    (
                        "physics",
                        "unity_physics_raycast",
                        "Raycast through the disposable probe fixture",
                        {
                            "origin": vec3(0, 10, 0),
                            "direction": vec3(0, -1, 0),
                            "maxDistance": 30,
                        },
                    ),
                ]
                for category, tool_name, description, params in sample_probes:
                    if _category_allowed(category):
                        _record_probe(category, tool_name, description, params)
            else:
                for category in ("graphics", "physics"):
                    if _category_allowed(category):
                        _record_probe(
                            category,
                            f"probe-backed:{category}",
                            f"Probe-backed {category} probes",
                            skip_reason="Skipped because --no-probe-backed was used.",
                        )
        except Exception as exc:  # pragma: no cover - covered via cleanup path
            failure_message = str(exc)
        try:
            if _category_allowed("ui"):
                canvas_entry = _record_probe(
                    "ui",
                    "unity_ui_create_canvas",
                    "Create a disposable overlay canvas",
                    {"name": f"{sample_root}_Canvas", "renderMode": "overlay"},
                )
                if canvas_entry.get("status") == "passed":
                    scene_mutated = True
                _record_probe(
                    "ui",
                    "unity_ui_info",
                    "Inspect UI canvas and element counts",
                    {},
                )

            if _category_allowed("lighting"):
                light_entry = _record_probe(
                    "lighting",
                    "unity_lighting_create",
                    "Create a disposable point light",
                    {
                        "name": f"{sample_root}_Light",
                        "lightType": "Point",
                        "intensity": 1.5,
                        "position": vec3(0, 4, 0),
                    },
                )
                if light_entry.get("status") == "passed":
                    scene_mutated = True
                _record_probe(
                    "lighting",
                    "unity_lighting_info",
                    "Inspect scene lighting configuration",
                    {},
                )

            if _category_allowed("animation"):
                animation_root = f"Assets/{sample_root}/Animation"
                controller_path = f"{animation_root}/{sample_root}.controller"
                clip_path = f"{animation_root}/{sample_root}.anim"
                controller_entry = _record_probe(
                    "animation",
                    "unity_animation_create_controller",
                    "Create a disposable Animator Controller",
                    {"path": controller_path},
                )
                if controller_entry.get("status") == "passed":
                    _note_asset(controller_path)
                clip_entry = _record_probe(
                    "animation",
                    "unity_animation_create_clip",
                    "Create a disposable Animation Clip",
                    {"path": clip_path, "loop": True, "frameRate": 30},
                )
                if clip_entry.get("status") == "passed":
                    _note_asset(clip_path)
                _record_probe(
                    "animation",
                    "unity_animation_set_clip_curve",
                    "Author a simple transform curve on the disposable clip",
                    {
                        "clipPath": clip_path,
                        "propertyName": "localPosition.x",
                        "keyframes": [{"time": 0, "value": 0}, {"time": 0.5, "value": 1}],
                        "type": "Transform",
                    },
                )
                _record_probe(
                    "animation",
                    "unity_animation_add_layer",
                    "Add a disposable animator layer",
                    {"controllerPath": controller_path, "layerName": "UpperBody", "weight": 1},
                )
                _record_probe(
                    "animation",
                    "unity_animation_add_state",
                    "Add a disposable animator state",
                    {
                        "controllerPath": controller_path,
                        "stateName": "Idle",
                        "layerIndex": 0,
                        "clipPath": clip_path,
                        "isDefault": True,
                    },
                )
                _record_probe(
                    "animation",
                    "unity_animation_controller_info",
                    "Inspect the disposable Animator Controller",
                    {"path": controller_path},
                )

            if _category_allowed("input"):
                input_root = f"Assets/{sample_root}/Input"
                input_path = f"{input_root}/{sample_root}.inputactions"
                input_entry = _record_probe(
                    "input",
                    "unity_input_create",
                    "Create a disposable Input Actions asset",
                    {"path": input_path, "name": sample_root, "maps": [{"name": "Gameplay"}]},
                )
                if input_entry.get("status") == "passed":
                    _note_asset(input_path)
                _record_probe(
                    "input",
                    "unity_input_info",
                    "Inspect the disposable Input Actions asset",
                    {"path": input_path},
                )

            if _category_allowed("shadergraph"):
                shader_root = f"Assets/{sample_root}/Shaders"
                shader_path = f"{shader_root}/{sample_root}.shadergraph"
                shader_entry = _record_probe(
                    "shadergraph",
                    "unity_shadergraph_create",
                    "Create a disposable Shader Graph asset",
                    {"path": shader_path, "template": "urp_unlit"},
                )
                if shader_entry.get("status") == "passed":
                    _note_asset(shader_path)
                _record_probe(
                    "shadergraph",
                    "unity_shadergraph_list",
                    "List shader graphs filtered to the disposable audit asset",
                    {"filter": sample_root, "maxResults": 10},
                )

            if _category_allowed("terrain"):
                terrain_root = f"Assets/{sample_root}/Terrain"
                terrain_name = f"{sample_root}_Terrain"
                terrain_data_path = f"{terrain_root}/{sample_root}_Data.asset"
                terrain_entry = _record_probe(
                    "terrain",
                    "unity_terrain_create",
                    "Create a disposable terrain",
                    {
                        "name": terrain_name,
                        "width": 128,
                        "length": 128,
                        "height": 60,
                        "heightmapResolution": 129,
                        "position": vec3(48, 0, 48),
                        "dataPath": terrain_data_path,
                    },
                )
                if terrain_entry.get("status") == "passed":
                    scene_mutated = True
                    _note_asset(terrain_data_path)
                _record_probe(
                    "terrain",
                    "unity_terrain_info",
                    "Inspect the disposable terrain",
                    {"name": terrain_name},
                )
                _record_probe(
                    "terrain",
                    "unity_terrain_get_height",
                    "Sample the disposable terrain height at its origin",
                    {"worldX": 48, "worldZ": 48, "name": terrain_name},
                )
        except Exception as exc:  # pragma: no cover - covered via cleanup path
            failure_message = str(exc)
        finally:
            cleanup: dict[str, Any] = {"performed": created_sample or scene_mutated or bool(created_assets)}
            if scene_mutated:
                try:
                    cleanup_state = _fetch_editor_state()
                    if bool(cleanup_state.get("isPlaying")) or bool(cleanup_state.get("isPlayingOrWillChangePlaymode")):
                        cleanup["forceStop"] = require_workflow_success(
                            ctx.obj.backend.call_route_with_recovery(
                                "editor/play-mode",
                                params={"action": "stop"},
                                port=workflow_port,
                                recovery_timeout=max(timeout, 10.0),
                                recovery_interval=max(0.1, interval),
                            ),
                            "Force stop play mode during advanced-audit cleanup",
                        )
                        cleanup["forceStopState"] = wait_for_result(
                            _fetch_editor_state,
                            lambda state: (not bool((state or {}).get("isPlaying")))
                            and (not bool((state or {}).get("isPlayingOrWillChangePlaymode"))),
                            timeout=timeout,
                            interval=interval,
                        )
                except (BackendSelectionError, UnityMCPClientError, ValueError) as cleanup_exc:
                    cleanup["forceStopError"] = str(cleanup_exc)

                try:
                    cleanup["sceneReset"] = require_workflow_success(
                        ctx.obj.backend.call_route_with_recovery(
                            "scene/open",
                            params={"path": scene_path, "discardUnsaved": True},
                            port=workflow_port,
                            recovery_timeout=max(timeout, 10.0),
                            recovery_interval=max(0.1, interval),
                        ),
                        f"Reload scene {scene_path} during advanced-audit cleanup",
                    )
                except (BackendSelectionError, UnityMCPClientError, ValueError) as cleanup_exc:
                    cleanup["sceneResetError"] = str(cleanup_exc)

            if created_assets:
                cleanup["deletedAssets"] = []
                for asset_path in created_assets:
                    try:
                        delete_result = require_workflow_success(
                            ctx.obj.backend.call_tool(
                                "unity_asset_delete",
                                params={"path": asset_path},
                                port=workflow_port,
                            ),
                            f"Delete audit asset {asset_path}",
                        )
                        cleanup["deletedAssets"].append({"path": asset_path, "result": delete_result})
                    except (BackendSelectionError, UnityMCPClientError, ValueError) as cleanup_exc:
                        cleanup.setdefault("assetDeleteErrors", []).append(
                            {"path": asset_path, "error": str(cleanup_exc)}
                        )

            try:
                payload["after"] = {
                    "editorState": ctx.obj.backend.call_route_with_recovery(
                        "editor/state",
                        port=workflow_port,
                        record_history=False,
                        recovery_timeout=10.0,
                    ),
                    "scene": ctx.obj.backend.call_route_with_recovery(
                        "scene/info",
                        port=workflow_port,
                        record_history=False,
                        recovery_timeout=10.0,
                    ),
                }
            except (BackendSelectionError, UnityMCPClientError, ValueError) as after_exc:
                cleanup["afterStateError"] = str(after_exc)

            payload["cleanup"] = cleanup

        if failure_message:
            cleanup_errors = [
                cleanup_error
                for key, cleanup_error in payload.get("cleanup", {}).items()
                if key.endswith("Error")
            ]
            if cleanup_errors:
                failure_message += " Cleanup issues: " + "; ".join(cleanup_errors)
            raise ValueError(failure_message)

        total = len(payload["probes"])
        passed = sum(1 for probe in payload["probes"] if probe.get("status") == "passed")
        failed = sum(1 for probe in payload["probes"] if probe.get("status") == "failed")
        skipped = sum(1 for probe in payload["probes"] if probe.get("status") == "skipped")
        payload["summary"] = {
            "totalProbes": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "requestedCategories": sorted(requested_categories),
            "probeBacked": probe_backed,
            "finalSceneDirty": bool(((payload.get("after") or {}).get("editorState") or {}).get("sceneDirty")),
        }
        return payload

    _run_and_emit(ctx, _callback)


@workflow_group.command("wire-reference")
@click.argument("target_object")
@click.argument("component_type")
@click.argument("property_name")
@click.option("--reference-object", type=str, default=None, help="Scene object name or hierarchy path to assign.")
@click.option("--reference-component", type=str, default=None, help="Optional component type on the referenced scene object.")
@click.option("--asset-path", type=str, default=None, help="Project asset path to assign instead of a scene object.")
@click.option("--reference-instance-id", type=int, default=None, help="Assign an object by Unity instance ID.")
@click.option("--clear", "clear_reference", is_flag=True, help="Clear the reference instead of assigning a new target.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_wire_reference_command(
    ctx: click.Context,
    target_object: str,
    component_type: str,
    property_name: str,
    reference_object: str | None,
    reference_component: str | None,
    asset_path: str | None,
    reference_instance_id: int | None,
    clear_reference: bool,
    port: int | None,
) -> None:
    """Wire a serialized ObjectReference on a component without hand-building route payloads."""

    def _callback() -> dict[str, Any]:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        provided_targets = [
            bool(reference_object),
            bool(asset_path),
            reference_instance_id is not None,
            bool(clear_reference),
        ]
        if sum(1 for item in provided_targets if item) != 1:
            raise ValueError(
                "Choose exactly one of --reference-object, --asset-path, --reference-instance-id, or --clear."
            )

        params: dict[str, Any] = {
            "gameObjectPath": target_object,
            "componentType": component_type,
            "propertyName": property_name,
        }
        if reference_object:
            params["referenceGameObject"] = reference_object
        if reference_component:
            if not reference_object:
                raise ValueError("--reference-component requires --reference-object.")
            params["referenceComponentType"] = reference_component
        if asset_path:
            params["assetPath"] = asset_path
        if reference_instance_id is not None:
            params["referenceInstanceId"] = reference_instance_id
        if clear_reference:
            params["clear"] = True

        _record_progress_step(
            ctx,
            f"Wiring {property_name} on {target_object}",
            phase="wire",
            port=workflow_port,
        )
        result = require_workflow_success(
            ctx.obj.backend.call_route("component/set-reference", params=params, port=workflow_port),
            f"Wire reference {property_name} on {target_object}",
        )
        _record_progress_step(
            ctx,
            f"Inspecting updated GameObject {target_object}",
            phase="inspect",
            port=workflow_port,
        )
        target_info = require_workflow_success(
            ctx.obj.backend.call_tool(
                "unity_gameobject_info",
                params={"gameObjectPath": target_object},
                port=workflow_port,
            ),
            f"Inspect GameObject {target_object}",
        )
        return {
            "targetObject": target_object,
            "componentType": component_type,
            "propertyName": property_name,
            "result": result,
            "gameObject": target_info,
        }

    _run_and_emit(ctx, _callback)


@workflow_group.command("create-prefab")
@click.argument("game_object")
@click.option("--folder", type=str, default="Assets/Prefabs", show_default=True, help="Destination folder for the prefab asset.")
@click.option("--name", type=str, default=None, help="Optional prefab asset name. Defaults to the scene object name.")
@click.option("--instantiate", is_flag=True, help="Instantiate the new prefab back into the current scene.")
@click.option("--instance-name", type=str, default=None, help="Optional name for the instantiated prefab copy.")
@click.option("--parent", type=str, default=None, help="Optional parent object for the instantiated prefab copy.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_create_prefab_command(
    ctx: click.Context,
    game_object: str,
    folder: str,
    name: str | None,
    instantiate: bool,
    instance_name: str | None,
    parent: str | None,
    port: int | None,
) -> None:
    """Save a scene object as a prefab and optionally instantiate the saved prefab."""

    def _callback() -> dict[str, Any]:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        _record_progress_step(ctx, f"Inspecting source GameObject {game_object}", phase="inspect", port=workflow_port)
        object_info = require_workflow_success(
            ctx.obj.backend.call_tool(
                "unity_gameobject_info",
                params={"gameObjectPath": game_object},
                port=workflow_port,
            ),
            f"Inspect GameObject {game_object}",
        )
        prefab_name = sanitize_csharp_identifier(name or object_info.get("name") or game_object)
        save_path = build_asset_path(folder, prefab_name, extension=".prefab")
        _record_progress_step(ctx, f"Creating prefab {Path(save_path).name}", phase="create", port=workflow_port)
        prefab_result = require_workflow_success(
            ctx.obj.backend.call_route(
                "asset/create-prefab",
                params={"gameObjectPath": game_object, "savePath": save_path},
                port=workflow_port,
            ),
            f"Create prefab from {game_object}",
        )

        payload: dict[str, Any] = {
            "gameObject": object_info,
            "prefab": prefab_result,
            "savePath": save_path,
        }

        if instantiate:
            instantiate_params: dict[str, Any] = {"prefabPath": save_path}
            if instance_name:
                instantiate_params["name"] = instance_name
            if parent:
                instantiate_params["parent"] = parent
            _record_progress_step(
                ctx,
                f"Instantiating prefab {Path(save_path).name}",
                phase="create",
                port=workflow_port,
            )
            instance_result = require_workflow_success(
                ctx.obj.backend.call_route(
                    "asset/instantiate-prefab",
                    params=instantiate_params,
                    port=workflow_port,
                ),
                f"Instantiate prefab {save_path}",
            )
            payload["instance"] = instance_result

        return payload

    _run_and_emit(ctx, _callback)


@workflow_group.command("validate-scene")
@click.option("--limit", type=int, default=50, show_default=True, help="Maximum missing-reference results to request.")
@click.option("--include-hierarchy", is_flag=True, help="Include a small hierarchy snapshot in the validation report.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_validate_scene_command(
    ctx: click.Context,
    limit: int,
    include_hierarchy: bool,
    port: int | None,
) -> None:
    """Collect the high-signal scene health checks needed before building gameplay on top."""

    def _callback() -> dict[str, Any]:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        _record_progress_step(ctx, "Checking editor state", phase="check", port=workflow_port)
        state = ctx.obj.backend.call_route_with_recovery(
            "editor/state",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        _record_progress_step(ctx, "Inspecting active scene info", phase="inspect", port=workflow_port)
        scene = ctx.obj.backend.call_route_with_recovery(
            "scene/info",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        stats_warning: str | None = None
        try:
            _record_progress_step(ctx, "Inspecting scene stats", phase="inspect", port=workflow_port)
            stats = require_workflow_success(
                ctx.obj.backend.call_route_with_recovery(
                    "scene/stats",
                    port=workflow_port,
                    recovery_timeout=10.0,
                ),
                "Read scene stats",
            )
        except (UnityMCPClientError, ValueError) as exc:
            _record_progress_step(ctx, "Falling back to hierarchy-derived scene stats", phase="inspect", port=workflow_port)
            hierarchy_fallback = ctx.obj.backend.call_route_with_recovery(
                "scene/hierarchy",
                params={"maxDepth": 6, "maxNodes": 2000},
                port=workflow_port,
                recovery_timeout=10.0,
            )
            stats = {
                "sceneName": scene.get("activeScene") or state.get("activeScene"),
                "totalGameObjects": hierarchy_fallback.get("totalSceneObjects")
                or hierarchy_fallback.get("returnedNodes")
                or 0,
                "totalComponents": None,
                "totalMeshes": None,
                "totalVertices": None,
                "totalTriangles": None,
                "totalLights": None,
                "totalCameras": None,
                "totalColliders": None,
                "totalRigidbodies": None,
                "topComponents": [],
                "fallback": True,
                "message": "Fell back to hierarchy-derived counts because scene/stats was unavailable.",
            }
            stats_warning = str(exc)
        _record_progress_step(ctx, f"Checking missing references (limit {limit})", phase="check", port=workflow_port)
        missing_references = require_workflow_success(
            ctx.obj.backend.call_route_with_recovery(
                "search/missing-references",
                params={"limit": limit},
                port=workflow_port,
                recovery_timeout=10.0,
            ),
            "Search for missing references",
        )
        _record_progress_step(ctx, f"Checking compilation errors (limit {limit})", phase="check", port=workflow_port)
        compilation = require_workflow_success(
            ctx.obj.backend.call_route_with_recovery(
                "compilation/errors",
                params={"count": limit},
                port=workflow_port,
                recovery_timeout=10.0,
            ),
            "Read compilation errors",
        )

        payload: dict[str, Any] = {
            "summary": {
                "activeScene": scene.get("activeScene") or state.get("activeScene"),
                "sceneDirty": bool(state.get("sceneDirty")),
                "isPlaying": bool(state.get("isPlaying")),
                "isCompiling": bool(compilation.get("isCompiling")),
                "missingReferenceCount": int(missing_references.get("totalFound") or 0),
                "compilationIssueCount": int(compilation.get("count") or 0),
                "totalGameObjects": int(stats.get("totalGameObjects") or 0),
                "totalComponents": int(stats.get("totalComponents") or 0)
                if stats.get("totalComponents") is not None
                else None,
            },
            "editorState": state,
            "scene": scene,
            "stats": stats,
            "missingReferences": missing_references,
            "compilation": compilation,
        }
        if stats_warning:
            payload["warnings"] = [f"scene/stats unavailable: {stats_warning}"]
        if include_hierarchy:
            _record_progress_step(ctx, "Inspecting hierarchy snapshot", phase="inspect", port=workflow_port)
            payload["hierarchy"] = ctx.obj.backend.call_route_with_recovery(
                "scene/hierarchy",
                params={"maxDepth": 2, "maxNodes": 30},
                port=workflow_port,
                recovery_timeout=10.0,
            )
        return payload

    _run_and_emit(ctx, _callback)

