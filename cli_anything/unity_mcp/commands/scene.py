from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import click

from ._shared import (
    BackendSelectionError,
    UnityMCPClientError,
    _run_and_emit,
    load_text_value,
    load_json_params,
)
from .debug import _filter_history_entries


@click.command("state")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def state_command(ctx: click.Context, port: int | None) -> None:
    """Fetch Unity editor state."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.call_route("editor/state", port=port))


@click.command("project-info")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def project_info_command(ctx: click.Context, port: int | None) -> None:
    """Fetch project information."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.call_route("project/info", port=port))


@click.command("scene-info")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def scene_info_command(ctx: click.Context, port: int | None) -> None:
    """Fetch active scene details."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.call_route("scene/info", port=port))


@click.command("scene-open")
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


@click.command("scene-save")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def scene_save_command(ctx: click.Context, port: int | None) -> None:
    """Save the active scene."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.call_route("scene/save", port=port))


@click.command("hierarchy")
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


@click.command("console")
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


@click.command("play")
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


@click.command("build")
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


@click.command("script-read")
@click.argument("path")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def script_read_command(ctx: click.Context, path: str, port: int | None) -> None:
    """Read a C# script asset."""
    _run_and_emit(
        ctx,
        lambda: ctx.obj.backend.call_route("script/read", params={"path": path}, port=port),
    )


@click.command("script-update")
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


@click.command("script-create")
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


@click.command("execute-code")
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


@click.command("undo")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def undo_command(ctx: click.Context, port: int | None) -> None:
    """Undo the last Unity operation."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.call_route("undo/perform", port=port))


@click.command("redo")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def redo_command(ctx: click.Context, port: int | None) -> None:
    """Redo the last undone Unity operation."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.call_route("undo/redo", port=port))


@click.command("context")
@click.argument("category", required=False)
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def context_command(ctx: click.Context, category: str | None, port: int | None) -> None:
    """Fetch project context payloads from the Unity bridge."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.get_context(category=category, port=port))


@click.command("history")
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
