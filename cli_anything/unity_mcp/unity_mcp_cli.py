from __future__ import annotations

import os
from pathlib import Path

import click
from click.core import ParameterSource

from . import __version__
from .commands._shared import (
    CLIContext,
    SessionStore,
    UnityMCPBackend,
    UnityMCPClient,
    _build_agent_profile_store,
    _build_base_args,
    _default_agent_id,
    _run_repl,
    _serialize_agent_profile,
    get_default_registry_path,
)
from .commands.instances import instances_command, select_command, status_command, ping_command
from .commands.agent import agent_group
from .commands.debug import debug_group
from .commands.scene import (
    state_command,
    project_info_command,
    scene_info_command,
    scene_open_command,
    scene_save_command,
    hierarchy_command,
    console_command,
    play_command,
    build_command,
    script_read_command,
    script_update_command,
    script_create_command,
    execute_code_command,
    undo_command,
    redo_command,
    context_command,
    history_command,
)
from .commands.tools import (
    routes_command,
    tools_command,
    advanced_tools_command,
    tool_info_command,
    tool_coverage_command,
    tool_template_command,
    queue_info_command,
    route_command,
    tool_command,
)
from .commands.workflow import workflow_group
from .commands.memory import memory_group

# Re-export for backward compatibility (test_core.py imports these directly)
from .commands.debug import _humanize_history_entry, _summarize_trace_entries


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
@click.option(
    "--transport",
    type=click.Choice(["auto", "http", "file"], case_sensitive=False),
    default=lambda: os.environ.get("UNITY_TRANSPORT", "auto"),
    show_default=True,
    help="Transport mode: auto (try HTTP then file IPC), http (HTTP only), file (file IPC only).",
)
@click.option(
    "--file-ipc-path",
    "file_ipc_paths",
    type=click.Path(exists=False, file_okay=False, path_type=Path),
    multiple=True,
    help="Unity project root to check for .umcp file IPC bridge. Repeat for multiple projects.",
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
    transport: str,
    file_ipc_paths: tuple[Path, ...],
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
        transport=transport.lower(),
        file_ipc_paths=list(file_ipc_paths) if file_ipc_paths else None,
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


# ─── Register commands ────────────────────────────────────────────────────────

cli.add_command(instances_command)
cli.add_command(select_command)
cli.add_command(status_command)
cli.add_command(ping_command)
cli.add_command(agent_group)
cli.add_command(debug_group)
cli.add_command(state_command)
cli.add_command(project_info_command)
cli.add_command(scene_info_command)
cli.add_command(scene_open_command)
cli.add_command(scene_save_command)
cli.add_command(hierarchy_command)
cli.add_command(console_command)
cli.add_command(play_command)
cli.add_command(build_command)
cli.add_command(script_read_command)
cli.add_command(script_update_command)
cli.add_command(script_create_command)
cli.add_command(execute_code_command)
cli.add_command(undo_command)
cli.add_command(redo_command)
cli.add_command(context_command)
cli.add_command(history_command)
cli.add_command(routes_command)
cli.add_command(tools_command)
cli.add_command(advanced_tools_command)
cli.add_command(tool_info_command)
cli.add_command(tool_coverage_command)
cli.add_command(tool_template_command)
cli.add_command(queue_info_command)
cli.add_command(route_command)
cli.add_command(tool_command)
cli.add_command(workflow_group)
cli.add_command(memory_group)
