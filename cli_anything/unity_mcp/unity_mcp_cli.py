from __future__ import annotations

import os
import shlex
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import click

from . import __version__
from .core.client import UnityMCPClient, UnityMCPClientError
from .core.session import SessionStore
from .core.workflows import (
    build_asset_path,
    build_behaviour_script,
    build_demo_bob_script,
    build_demo_follow_script,
    build_demo_spin_script,
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


def _emit(ctx: click.Context, value: Any) -> None:
    click.echo(format_output(value, ctx.obj.json_output))


def _run_and_emit(ctx: click.Context, callback: Callable[[], Any]) -> None:
    try:
        result = callback()
    except (BackendSelectionError, UnityMCPClientError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(ctx, result)


def _build_base_args(
    host: str,
    default_port: int,
    registry_path: Path | None,
    session_path: Path | None,
    json_output: bool,
    agent_id: str,
    legacy: bool,
    port_range_start: int,
    port_range_end: int,
) -> tuple[str, ...]:
    parts: list[str] = [
        "--host",
        host,
        "--default-port",
        str(default_port),
        "--agent-id",
        agent_id,
        "--port-range-start",
        str(port_range_start),
        "--port-range-end",
        str(port_range_end),
    ]
    if registry_path:
        parts.extend(["--registry-path", str(registry_path)])
    if session_path:
        parts.extend(["--session-path", str(session_path)])
    if json_output:
        parts.append("--json")
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
    "--json",
    "json_output",
    is_flag=True,
    help="Emit machine-readable JSON output.",
)
@click.option(
    "--agent-id",
    default=_default_agent_id,
    show_default="hostname+pid based",
    help="Agent identifier sent to the Unity queue headers.",
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
    port_range_start: int,
    port_range_end: int,
    json_output: bool,
    agent_id: str,
    legacy: bool,
) -> None:
    """Direct CLI for the AnkleBreaker Unity MCP editor bridge."""
    client = UnityMCPClient(
        host=host,
        agent_id=agent_id,
        use_queue=not legacy,
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
            json_output=json_output,
            agent_id=agent_id,
            legacy=legacy,
            port_range_start=port_range_start,
            port_range_end=port_range_end,
        ),
        command_path=ctx.command_path or "cli-anything-unity-mcp",
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
        }
        try:
            payload["ping"] = ctx.obj.backend.ping(port=port)
        except (BackendSelectionError, UnityMCPClientError) as exc:
            payload["pingError"] = str(exc)
        return payload

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
@click.option("--clear", "clear_history", is_flag=True, help="Clear the stored command history after printing.")
@click.pass_context
def history_command(ctx: click.Context, clear_history: bool) -> None:
    """Show or clear the local CLI session history."""

    def _callback() -> dict[str, Any]:
        history = ctx.obj.backend.get_history()
        payload = {"count": len(history), "history": history}
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

        ping = ctx.obj.backend.ping(port=workflow_port)
        project = ctx.obj.backend.call_route_with_recovery(
            "project/info",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        state = ctx.obj.backend.call_route_with_recovery(
            "editor/state",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        scene = ctx.obj.backend.call_route_with_recovery(
            "scene/info",
            port=workflow_port,
            recovery_timeout=10.0,
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


@workflow_group.command("smoke-test")
@click.option("--prefix", type=str, default="CodexSmoke", show_default=True, help="Prefix used for temporary test objects and scripts.")
@click.option("--folder", type=str, default="Assets/CodexSmoke", show_default=True, help="Asset folder for temporary test scripts.")
@click.option("--script/--no-script", "include_script", default=True, help="Create a temporary MonoBehaviour and attach it.")
@click.option("--play-check/--no-play-check", default=True, help="Enter and exit play mode during the smoke test.")
@click.option("--save-if-dirty-start", is_flag=True, help="Save the active scene first if it already has unsaved user changes.")
@click.option("--timeout", type=float, default=30.0, show_default=True, help="Seconds to wait for compilation and play mode transitions.")
@click.option("--interval", type=float, default=0.5, show_default=True, help="Polling interval while waiting for Unity to settle.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_smoke_test_command(
    ctx: click.Context,
    prefix: str,
    folder: str,
    include_script: bool,
    play_check: bool,
    save_if_dirty_start: bool,
    timeout: float,
    interval: float,
    port: int | None,
) -> None:
    """Run a reversible end-to-end validation pass against the active Unity scene."""

    def _callback() -> dict[str, Any]:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

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

        if starting_dirty and not save_if_dirty_start:
            raise ValueError(
                "Smoke test requires a clean starting scene. Save manually or rerun with --save-if-dirty-start."
            )
        if starting_dirty:
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

        probe_name = unique_probe_name(prefix)
        class_name = sanitize_csharp_identifier(probe_name)
        script_path = build_asset_path(folder, class_name)
        created_game_object = False
        created_script = False
        failure_message: str | None = None

        payload: dict[str, Any] = {
            "before": {
                "scene": scene_info,
                "editorState": editor_state,
                "scenePath": scene_path,
                "wasDirty": starting_dirty,
                "savedAtStart": starting_dirty and save_if_dirty_start,
            },
            "probe": {
                "name": probe_name,
                "className": class_name,
                "scriptPath": script_path,
            },
        }

        def _fetch_editor_state() -> dict[str, Any]:
            result = ctx.obj.backend.call_route_with_recovery(
                "editor/state",
                port=workflow_port,
                record_history=False,
                recovery_timeout=max(timeout, 10.0),
                recovery_interval=max(0.25, interval),
            )
            return result or {}

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

        try:
            payload["gameObject"] = require_workflow_success(
                ctx.obj.backend.call_tool(
                    "unity_gameobject_create",
                    params={"name": probe_name, "primitiveType": "Empty"},
                    port=workflow_port,
                ),
                f"Create smoke-test GameObject {probe_name}",
            )
            created_game_object = True

            payload["gameObjectInfo"] = require_workflow_success(
                ctx.obj.backend.call_tool(
                    "unity_gameobject_info",
                    params={"gameObjectPath": probe_name},
                    port=workflow_port,
                ),
                f"Inspect smoke-test GameObject {probe_name}",
            )

            if include_script:
                payload["script"] = require_workflow_success(
                    ctx.obj.backend.call_route(
                        "script/create",
                        params={
                            "path": script_path,
                            "content": build_behaviour_script(class_name),
                        },
                        port=workflow_port,
                    ),
                    f"Create smoke-test script {script_path}",
                )
                created_script = True

                payload["compilation"] = wait_for_compilation(
                    _fetch_compilation,
                    timeout=timeout,
                    interval=interval,
                )
                if int((payload["compilation"] or {}).get("count") or 0) > 0:
                    entries = payload["compilation"].get("entries") or []
                    first_entry = entries[0] if entries and isinstance(entries[0], dict) else {}
                    first_message = first_entry.get("message") or "Unity reported compilation errors."
                    raise ValueError(f"Smoke test compilation failed: {first_message}")

                payload["component"] = require_workflow_success(
                    wait_for_result(
                        lambda: ctx.obj.backend.call_tool(
                            "unity_component_add",
                            params={
                                "gameObjectPath": probe_name,
                                "componentType": class_name,
                            },
                            port=workflow_port,
                        ),
                        lambda result: workflow_error_message(result) is None,
                        timeout=timeout,
                        interval=interval,
                    ),
                    f"Attach smoke-test component {class_name}",
                )
                payload["properties"] = require_workflow_success(
                    ctx.obj.backend.call_tool(
                        "unity_component_get_properties",
                        params={
                            "gameObjectPath": probe_name,
                            "componentType": class_name,
                        },
                        port=workflow_port,
                    ),
                    f"Read smoke-test component properties for {class_name}",
                )
                payload["propertyUpdate"] = require_workflow_success(
                    ctx.obj.backend.call_tool(
                        "unity_component_set_property",
                        params={
                            "gameObjectPath": probe_name,
                            "componentType": class_name,
                            "propertyName": "Count",
                            "value": 2,
                        },
                        port=workflow_port,
                    ),
                    f"Update smoke-test component property on {class_name}",
                )

            if play_check:
                play_command_result = require_workflow_success(
                    ctx.obj.backend.call_route_with_recovery(
                        "editor/play-mode",
                        params={"action": "play"},
                        port=workflow_port,
                        recovery_timeout=max(timeout, 10.0),
                        recovery_interval=max(0.25, interval),
                    ),
                    "Enter play mode",
                )
                play_state = wait_for_result(
                    _fetch_editor_state,
                    lambda state: bool((state or {}).get("isPlaying")),
                    timeout=timeout,
                    interval=interval,
                )
                if not bool(play_state.get("isPlaying")):
                    raise ValueError("Smoke test timed out waiting for Unity to enter play mode.")

                stop_command_result = require_workflow_success(
                    ctx.obj.backend.call_route_with_recovery(
                        "editor/play-mode",
                        params={"action": "stop"},
                        port=workflow_port,
                        recovery_timeout=max(timeout, 10.0),
                        recovery_interval=max(0.25, interval),
                    ),
                    "Exit play mode",
                )
                stop_state = wait_for_result(
                    _fetch_editor_state,
                    lambda state: (not bool((state or {}).get("isPlaying")))
                    and (not bool((state or {}).get("isPlayingOrWillChangePlaymode"))),
                    timeout=timeout,
                    interval=interval,
                )
                if bool(stop_state.get("isPlaying")) or bool(stop_state.get("isPlayingOrWillChangePlaymode")):
                    raise ValueError("Smoke test timed out waiting for Unity to exit play mode.")

                payload["playMode"] = {
                    "enter": {"command": play_command_result, "state": play_state},
                    "exit": {"command": stop_command_result, "state": stop_state},
                }
        except Exception as exc:  # pragma: no cover - exercised indirectly via cleanup path
            failure_message = str(exc)
        finally:
            cleanup: dict[str, Any] = {}

            if created_game_object:
                try:
                    cleanup["gameObject"] = require_workflow_success(
                        ctx.obj.backend.call_tool(
                            "unity_gameobject_delete",
                            params={"gameObjectPath": probe_name},
                            port=workflow_port,
                        ),
                        f"Delete smoke-test GameObject {probe_name}",
                    )
                except (BackendSelectionError, UnityMCPClientError, ValueError) as cleanup_exc:
                    cleanup["gameObjectError"] = str(cleanup_exc)

            if created_script:
                try:
                    cleanup["script"] = require_workflow_success(
                        ctx.obj.backend.call_route(
                            "asset/delete",
                            params={"path": script_path},
                            port=workflow_port,
                        ),
                        f"Delete smoke-test script {script_path}",
                    )
                except (BackendSelectionError, UnityMCPClientError, ValueError) as cleanup_exc:
                    cleanup["scriptError"] = str(cleanup_exc)

            try:
                cleanup_state = _fetch_editor_state()
                if bool(cleanup_state.get("isPlaying")) or bool(cleanup_state.get("isPlayingOrWillChangePlaymode")):
                    cleanup["forceStop"] = require_workflow_success(
                        ctx.obj.backend.call_route_with_recovery(
                            "editor/play-mode",
                            params={"action": "stop"},
                            port=workflow_port,
                            recovery_timeout=max(timeout, 10.0),
                            recovery_interval=max(0.25, interval),
                        ),
                        "Force stop play mode during smoke-test cleanup",
                    )
                    cleanup["forceStopState"] = wait_for_result(
                        _fetch_editor_state,
                        lambda state: (not bool((state or {}).get("isPlaying")))
                        and (not bool((state or {}).get("isPlayingOrWillChangePlaymode"))),
                        timeout=timeout,
                        interval=interval,
                    )
                cleanup["sceneReset"] = require_workflow_success(
                    ctx.obj.backend.call_route_with_recovery(
                        "scene/open",
                        params={"path": scene_path, "discardUnsaved": True},
                        port=workflow_port,
                        recovery_timeout=max(timeout, 10.0),
                        recovery_interval=max(0.25, interval),
                    ),
                    f"Reload scene {scene_path}",
                )
            except (BackendSelectionError, UnityMCPClientError, ValueError) as cleanup_exc:
                cleanup["sceneResetError"] = str(cleanup_exc)

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

        return payload

    _run_and_emit(ctx, _callback)


@workflow_group.command("build-sample")
@click.option("--name", type=str, default="CodexSampleArena", show_default=True, help="Root name for the generated sample in the scene.")
@click.option("--folder", type=str, default="Assets/CodexSamples", show_default=True, help="Asset folder for generated sample scripts.")
@click.option("--prefab-folder", type=str, default=None, help="Optional prefab folder. Defaults to <folder>/Prefabs.")
@click.option("--replace", is_flag=True, help="Replace an existing sample with the same root name before building.")
@click.option("--cleanup", is_flag=True, help="Remove the generated sample after validating it. Useful for repeatable testing.")
@click.option("--play-check/--no-play-check", default=True, help="Enter and exit play mode after building the sample.")
@click.option("--save-if-dirty-start", is_flag=True, help="Save the active scene first if cleanup might need to restore a dirty starting point safely.")
@click.option("--timeout", type=float, default=30.0, show_default=True, help="Seconds to wait for compilation and play mode transitions.")
@click.option("--interval", type=float, default=0.5, show_default=True, help="Polling interval while waiting for Unity to settle.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_build_sample_command(
    ctx: click.Context,
    name: str,
    folder: str,
    prefab_folder: str | None,
    replace: bool,
    cleanup: bool,
    play_check: bool,
    save_if_dirty_start: bool,
    timeout: float,
    interval: float,
    port: int | None,
) -> None:
    """Build a small gameplay sample that exercises scripts, transforms, prefabs, wiring, and play mode."""

    def _callback() -> dict[str, Any]:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        root_name = str(name or "").strip()
        if not root_name:
            raise ValueError("A non-empty sample name is required.")
        sample_id = sanitize_csharp_identifier(root_name)
        normalized_folder = folder.replace("\\", "/").rstrip("/")
        if not normalized_folder:
            normalized_folder = "Assets/CodexSamples"
        normalized_prefab_folder = (
            (prefab_folder or f"{normalized_folder}/Prefabs").replace("\\", "/").rstrip("/")
        )

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

        if cleanup and starting_dirty and not save_if_dirty_start:
            raise ValueError(
                "build-sample with --cleanup requires a clean starting scene. Save manually or rerun with --save-if-dirty-start."
            )
        if starting_dirty and save_if_dirty_start:
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

        object_names = {
            "root": root_name,
            "floor": f"{root_name}_Floor",
            "player": f"{root_name}_Player",
            "beacon": f"{root_name}_Beacon",
            "observer": f"{root_name}_Observer",
            "beaconClone": f"{root_name}_BeaconClone",
        }
        script_names = {
            "spin": f"{sample_id}Spin",
            "bob": f"{sample_id}Bob",
            "follow": f"{sample_id}Follow",
        }
        script_paths = {
            "spin": build_asset_path(normalized_folder, script_names["spin"]),
            "bob": build_asset_path(normalized_folder, script_names["bob"]),
            "follow": build_asset_path(normalized_folder, script_names["follow"]),
        }
        prefab_path = build_asset_path(
            normalized_prefab_folder,
            f"{sample_id}Beacon",
            extension=".prefab",
        )
        created_assets: list[str] = []
        failure_message: str | None = None

        payload: dict[str, Any] = {
            "summary": {
                "sampleName": root_name,
                "sampleId": sample_id,
                "scenePath": scene_path,
                "cleanupRequested": cleanup,
                "playCheckRequested": play_check,
                "savedAtStart": saved_at_start,
            },
            "before": {
                "scene": scene_info,
                "editorState": editor_state,
            },
            "scripts": {},
            "objects": {},
            "components": {},
            "wiring": {},
        }

        def _call_route(
            route: str,
            action: str,
            params: dict[str, Any] | None = None,
            recover: bool = False,
            record_history: bool = True,
        ) -> dict[str, Any]:
            result = (
                ctx.obj.backend.call_route_with_recovery(
                    route,
                    params=params,
                    port=workflow_port,
                    record_history=record_history,
                    recovery_timeout=max(timeout, 10.0),
                    recovery_interval=max(0.25, interval),
                )
                if recover
                else ctx.obj.backend.call_route(
                    route,
                    params=params,
                    port=workflow_port,
                    record_history=record_history,
                )
            )
            return require_workflow_success(result, action)

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
                recovery_interval=max(0.25, interval),
            )
            return result or {}

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

        def _attach_component(game_object: str, component_type: str) -> dict[str, Any]:
            return require_workflow_success(
                wait_for_result(
                    lambda: ctx.obj.backend.call_tool(
                        "unity_component_add",
                        params={
                            "gameObjectPath": game_object,
                            "componentType": component_type,
                        },
                        port=workflow_port,
                    ),
                    lambda result: workflow_error_message(result) is None,
                    timeout=timeout,
                    interval=interval,
                ),
                f"Attach component {component_type} to {game_object}",
            )

        def _set_component_property(
            game_object: str,
            component_type: str,
            property_name: str,
            value: Any,
        ) -> dict[str, Any]:
            return _call_tool(
                "unity_component_set_property",
                f"Set {component_type}.{property_name} on {game_object}",
                {
                    "gameObjectPath": game_object,
                    "componentType": component_type,
                    "propertyName": property_name,
                    "value": value,
                },
            )

        def _delete_asset_if_present(asset_path: str) -> dict[str, Any] | None:
            try:
                result = ctx.obj.backend.call_route(
                    "asset/delete",
                    params={"path": asset_path},
                    port=workflow_port,
                )
            except (BackendSelectionError, UnityMCPClientError, ValueError):
                return None
            if isinstance(result, dict) and result.get("success"):
                return result
            return None

        if replace:
            replacements: dict[str, Any] = {}
            try:
                replacements["root"] = _call_tool(
                    "unity_gameobject_delete",
                    f"Delete existing sample root {root_name}",
                    {"gameObjectPath": root_name},
                )
            except ValueError:
                pass
            for asset_path in [*script_paths.values(), prefab_path]:
                deleted = _delete_asset_if_present(asset_path)
                if deleted:
                    replacements.setdefault("assets", []).append(deleted)
            if replacements:
                payload["replaced"] = replacements
        else:
            try:
                _call_tool(
                    "unity_gameobject_info",
                    f"Inspect existing sample root {root_name}",
                    {"gameObjectPath": root_name},
                )
                raise ValueError(
                    f"A sample root named {root_name} already exists. Rerun with --replace to rebuild it."
                )
            except ValueError as exc:
                if "already exists" in str(exc):
                    raise

        try:
            payload["scripts"]["spin"] = _call_route(
                "script/create",
                f"Create sample script {script_paths['spin']}",
                {
                    "path": script_paths["spin"],
                    "content": build_demo_spin_script(script_names["spin"]),
                },
            )
            created_assets.append(script_paths["spin"])
            payload["scripts"]["bob"] = _call_route(
                "script/create",
                f"Create sample script {script_paths['bob']}",
                {
                    "path": script_paths["bob"],
                    "content": build_demo_bob_script(script_names["bob"]),
                },
            )
            created_assets.append(script_paths["bob"])
            payload["scripts"]["follow"] = _call_route(
                "script/create",
                f"Create sample script {script_paths['follow']}",
                {
                    "path": script_paths["follow"],
                    "content": build_demo_follow_script(script_names["follow"]),
                },
            )
            created_assets.append(script_paths["follow"])

            payload["compilation"] = wait_for_compilation(
                _fetch_compilation,
                timeout=timeout,
                interval=interval,
            )
            if int((payload["compilation"] or {}).get("count") or 0) > 0:
                entries = payload["compilation"].get("entries") or []
                first_entry = entries[0] if entries and isinstance(entries[0], dict) else {}
                first_message = first_entry.get("message") or "Unity reported compilation errors."
                raise ValueError(f"build-sample compilation failed: {first_message}")

            payload["objects"]["root"] = _call_tool(
                "unity_gameobject_create",
                f"Create sample root {root_name}",
                {
                    "name": object_names["root"],
                    "primitiveType": "Empty",
                    "position": vec3(0, 0, 0),
                },
            )
            payload["objects"]["floor"] = _call_tool(
                "unity_gameobject_create",
                f"Create sample floor {object_names['floor']}",
                {
                    "name": object_names["floor"],
                    "primitiveType": "Plane",
                    "parent": object_names["root"],
                    "position": vec3(0, 0, 0),
                    "scale": vec3(3.0, 1.0, 3.0),
                },
            )
            payload["objects"]["player"] = _call_tool(
                "unity_gameobject_create",
                f"Create sample player {object_names['player']}",
                {
                    "name": object_names["player"],
                    "primitiveType": "Capsule",
                    "parent": object_names["root"],
                    "position": vec3(0, 1, 0),
                },
            )
            payload["objects"]["beacon"] = _call_tool(
                "unity_gameobject_create",
                f"Create sample beacon {object_names['beacon']}",
                {
                    "name": object_names["beacon"],
                    "primitiveType": "Sphere",
                    "parent": object_names["root"],
                    "position": vec3(4, 1, 0),
                    "scale": vec3(1.25, 1.25, 1.25),
                },
            )
            payload["objects"]["observer"] = _call_tool(
                "unity_gameobject_create",
                f"Create sample observer {object_names['observer']}",
                {
                    "name": object_names["observer"],
                    "primitiveType": "Empty",
                    "parent": object_names["root"],
                    "position": vec3(0, 4, -8),
                },
            )
            payload["objects"]["observerTransform"] = _call_route(
                "gameobject/set-transform",
                f"Adjust sample observer transform for {object_names['observer']}",
                {
                    "path": object_names["observer"],
                    "position": vec3(0, 5, -8),
                },
            )

            payload["components"]["playerSpin"] = _attach_component(
                object_names["player"],
                script_names["spin"],
            )
            payload["components"]["beaconBob"] = _attach_component(
                object_names["beacon"],
                script_names["bob"],
            )
            payload["components"]["observerFollow"] = _attach_component(
                object_names["observer"],
                script_names["follow"],
            )

            payload["componentConfig"] = {
                "playerSpeed": _set_component_property(
                    object_names["player"],
                    script_names["spin"],
                    "Speed",
                    120,
                ),
                "beaconHeight": _set_component_property(
                    object_names["beacon"],
                    script_names["bob"],
                    "Height",
                    0.45,
                ),
                "beaconSpeed": _set_component_property(
                    object_names["beacon"],
                    script_names["bob"],
                    "Speed",
                    1.8,
                ),
                "observerOffset": _set_component_property(
                    object_names["observer"],
                    script_names["follow"],
                    "Offset",
                    vec3(0, 4.5, -8),
                ),
            }
            payload["wiring"]["observerTarget"] = _call_route(
                "component/set-reference",
                f"Wire observer target to {object_names['player']}",
                {
                    "gameObjectPath": object_names["observer"],
                    "componentType": script_names["follow"],
                    "propertyName": "Target",
                    "referenceGameObject": object_names["player"],
                    "referenceComponentType": "Transform",
                },
            )

            payload["prefab"] = _call_route(
                "asset/create-prefab",
                f"Create sample prefab {prefab_path}",
                {
                    "gameObjectPath": object_names["beacon"],
                    "savePath": prefab_path,
                },
            )
            created_assets.append(prefab_path)
            payload["objects"]["beaconClone"] = _call_route(
                "asset/instantiate-prefab",
                f"Instantiate sample prefab clone {object_names['beaconClone']}",
                {
                    "prefabPath": prefab_path,
                    "name": object_names["beaconClone"],
                    "parent": object_names["root"],
                    "position": vec3(-4, 1, 0),
                },
            )
            payload["componentConfig"]["beaconCloneSpeed"] = _set_component_property(
                object_names["beaconClone"],
                script_names["bob"],
                "Speed",
                2.2,
            )

            validation_hierarchy = _call_route(
                "scene/hierarchy",
                "Read sample hierarchy snapshot",
                params={"maxDepth": 3, "maxNodes": 40},
                recover=True,
                record_history=False,
            )
            try:
                validation_stats = _call_tool(
                    "unity_scene_stats",
                    "Read scene stats after building sample",
                    {},
                )
            except ValueError as exc:
                validation_stats = {
                    "sceneName": scene_info.get("activeScene") or editor_state.get("activeScene"),
                    "totalGameObjects": validation_hierarchy.get("totalSceneObjects")
                    or validation_hierarchy.get("returnedNodes")
                    or 0,
                    "totalComponents": None,
                    "fallback": True,
                    "message": "Fell back to hierarchy-derived counts because unity_scene_stats was unavailable.",
                }
                payload.setdefault("warnings", []).append(f"unity_scene_stats unavailable: {exc}")

            payload["validation"] = {
                "editorState": _call_route(
                    "editor/state",
                    "Read editor state after building sample",
                    recover=True,
                    record_history=False,
                ),
                "scene": _call_route(
                    "scene/info",
                    "Read scene info after building sample",
                    recover=True,
                    record_history=False,
                ),
                "hierarchy": validation_hierarchy,
                "stats": validation_stats,
            }

            if play_check:
                play_command_result = _call_route(
                    "editor/play-mode",
                    "Enter play mode",
                    {"action": "play"},
                    recover=True,
                )
                play_state = wait_for_result(
                    _fetch_editor_state,
                    lambda state: bool((state or {}).get("isPlaying")),
                    timeout=timeout,
                    interval=interval,
                )
                if not bool(play_state.get("isPlaying")):
                    raise ValueError("build-sample timed out waiting for Unity to enter play mode.")

                stop_command_result = _call_route(
                    "editor/play-mode",
                    "Exit play mode",
                    {"action": "stop"},
                    recover=True,
                )
                stop_state = wait_for_result(
                    _fetch_editor_state,
                    lambda state: (not bool((state or {}).get("isPlaying")))
                    and (not bool((state or {}).get("isPlayingOrWillChangePlaymode"))),
                    timeout=timeout,
                    interval=interval,
                )
                if bool(stop_state.get("isPlaying")) or bool(stop_state.get("isPlayingOrWillChangePlaymode")):
                    raise ValueError("build-sample timed out waiting for Unity to exit play mode.")

                payload["playMode"] = {
                    "enter": {"command": play_command_result, "state": play_state},
                    "exit": {"command": stop_command_result, "state": stop_state},
                }
        except Exception as exc:  # pragma: no cover - exercised via cleanup path
            failure_message = str(exc)
        finally:
            should_cleanup = cleanup or failure_message is not None
            cleanup_payload: dict[str, Any] = {"performed": should_cleanup}

            if should_cleanup:
                try:
                    cleanup_state = _fetch_editor_state()
                    if bool(cleanup_state.get("isPlaying")) or bool(cleanup_state.get("isPlayingOrWillChangePlaymode")):
                        cleanup_payload["forceStop"] = _call_route(
                            "editor/play-mode",
                            "Force stop play mode during sample cleanup",
                            {"action": "stop"},
                            recover=True,
                        )
                        cleanup_payload["forceStopState"] = wait_for_result(
                            _fetch_editor_state,
                            lambda state: (not bool((state or {}).get("isPlaying")))
                            and (not bool((state or {}).get("isPlayingOrWillChangePlaymode"))),
                            timeout=timeout,
                            interval=interval,
                        )
                except (BackendSelectionError, UnityMCPClientError, ValueError) as cleanup_exc:
                    cleanup_payload["forceStopError"] = str(cleanup_exc)

                can_reset_scene = (not starting_dirty) or saved_at_start
                if can_reset_scene:
                    try:
                        cleanup_payload["sceneReset"] = _call_route(
                            "scene/open",
                            f"Reload scene {scene_path} during sample cleanup",
                            {"path": scene_path, "discardUnsaved": True},
                            recover=True,
                        )
                    except (BackendSelectionError, UnityMCPClientError, ValueError) as cleanup_exc:
                        cleanup_payload["sceneResetError"] = str(cleanup_exc)
                else:
                    try:
                        cleanup_payload["rootDelete"] = _call_tool(
                            "unity_gameobject_delete",
                            f"Delete sample root {root_name} during cleanup",
                            {"gameObjectPath": root_name},
                        )
                    except (BackendSelectionError, UnityMCPClientError, ValueError) as cleanup_exc:
                        cleanup_payload["rootDeleteError"] = str(cleanup_exc)
                    cleanup_payload["sceneResetSkipped"] = (
                        "Skipped scene reload because the scene started dirty and was not saved at the beginning."
                    )

                asset_cleanup: list[dict[str, Any]] = []
                for asset_path in reversed(created_assets):
                    deleted = _delete_asset_if_present(asset_path)
                    if deleted:
                        asset_cleanup.append(deleted)
                if asset_cleanup:
                    cleanup_payload["assets"] = asset_cleanup

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
                cleanup_payload["afterStateError"] = str(after_exc)

            payload["cleanup"] = cleanup_payload

        if failure_message:
            cleanup_errors = [
                cleanup_error
                for key, cleanup_error in payload.get("cleanup", {}).items()
                if key.endswith("Error")
            ]
            if cleanup_errors:
                failure_message += " Cleanup issues: " + "; ".join(cleanup_errors)
            raise ValueError(failure_message)

        payload["summary"]["createdAssetCount"] = len(created_assets)
        payload["summary"]["cleanupPerformed"] = bool(payload.get("cleanup", {}).get("performed"))
        payload["summary"]["finalSceneDirty"] = bool(
            ((payload.get("after") or {}).get("editorState") or {}).get("sceneDirty")
        )
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

        result = require_workflow_success(
            ctx.obj.backend.call_route("component/set-reference", params=params, port=workflow_port),
            f"Wire reference {property_name} on {target_object}",
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

        state = ctx.obj.backend.call_route_with_recovery(
            "editor/state",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        scene = ctx.obj.backend.call_route_with_recovery(
            "scene/info",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        stats_warning: str | None = None
        try:
            stats = require_workflow_success(
                ctx.obj.backend.call_route_with_recovery(
                    "scene/stats",
                    port=workflow_port,
                    recovery_timeout=10.0,
                ),
                "Read scene stats",
            )
        except (UnityMCPClientError, ValueError) as exc:
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
        missing_references = require_workflow_success(
            ctx.obj.backend.call_route_with_recovery(
                "search/missing-references",
                params={"limit": limit},
                port=workflow_port,
                recovery_timeout=10.0,
            ),
            "Search for missing references",
        )
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
            payload["hierarchy"] = ctx.obj.backend.call_route_with_recovery(
                "scene/hierarchy",
                params={"maxDepth": 2, "maxNodes": 30},
                port=workflow_port,
                recovery_timeout=10.0,
            )
        return payload

    _run_and_emit(ctx, _callback)
