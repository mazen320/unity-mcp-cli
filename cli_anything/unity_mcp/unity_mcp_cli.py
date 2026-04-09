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
from .core.session import SessionStore
from .core.workflows import (
    build_2d_sample_clone_repair_code,
    build_2d_sample_layout_code,
    build_3d_fps_sample_scene_code,
    build_asset_path,
    build_behaviour_script,
    build_demo_bob_script,
    build_demo_fps_controller_script,
    build_demo_follow_script,
    build_demo_spin_script,
    build_unity_test_project_bootstrap_script,
    build_unity_test_project_gitignore,
    build_unity_test_project_manifest,
    build_unity_test_project_readme,
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


def _run_and_emit(ctx: click.Context, callback: Callable[[], Any]) -> None:
    try:
        result = callback()
    except (BackendSelectionError, UnityMCPClientError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    _emit(ctx, result)


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
                f"cli-anything-unity-mcp --json debug snapshot --console-count 100 --include-hierarchy{' --port ' + str(active_port) if selected_port is not None else ' --port <port>'}",
                f"cli-anything-unity-mcp --json console --count 50 --type error{' --port ' + str(active_port) if selected_port is not None else ' --port <port>'}",
                f"cli-anything-unity-mcp --json workflow validate-scene --include-hierarchy{' --port ' + str(active_port) if selected_port is not None else ' --port <port>'}",
                f"cli-anything-unity-mcp --json agent queue{' --port ' + str(active_port) if selected_port is not None else ' --port <port>'}",
            ],
            "checklist": [
                "Capture the current editor, scene, console, compilation, and queue state with `debug snapshot`.",
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


@workflow_group.command("scaffold-test-project")
@click.option(
    "--project-path",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Folder to create the disposable Unity smoke project in.",
)
@click.option(
    "--project-name",
    type=str,
    default="UnityMcpCliSmokeProject",
    show_default=True,
    help="Human-friendly project name for the scaffolded test project.",
)
@click.option(
    "--unity-version",
    type=str,
    default="6000.4.0f1",
    show_default=True,
    help="Unity editor version to record in ProjectVersion.txt.",
)
@click.option(
    "--plugin-source",
    type=click.Choice(["auto", "local", "git"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="Use the local plugin clone when available, or fall back to the upstream git URL.",
)
@click.option(
    "--plugin-path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Optional explicit path to a local AnkleBreaker Unity MCP plugin clone.",
)
@click.option("--force", is_flag=True, help="Overwrite the managed scaffold files if the project folder already exists.")
@click.pass_context
def workflow_scaffold_test_project_command(
    ctx: click.Context,
    project_path: Path | None,
    project_name: str,
    unity_version: str,
    plugin_source: str,
    plugin_path: Path | None,
    force: bool,
) -> None:
    """Create a disposable Unity smoke project with the plugin wired in and starter commands ready."""

    def _callback() -> dict[str, Any]:
        inferred_root = Path.cwd().resolve().parent / sanitize_csharp_identifier(project_name)
        target_root = (project_path or inferred_root).resolve()
        if target_root.exists() and any(target_root.iterdir()) and not force:
            raise ValueError(
                f"Test project folder `{target_root}` already exists and is not empty. Rerun with --force to overwrite the managed scaffold files."
            )

        packages_dir = target_root / "Packages"
        project_settings_dir = target_root / "ProjectSettings"
        assets_dir = target_root / "Assets"
        editor_dir = assets_dir / "Editor"

        repo_root = Path(__file__).resolve().parents[4]
        local_plugin_candidate = (plugin_path or (repo_root / "unity-mcp-plugin")).resolve()
        selected_plugin_source = plugin_source.lower()
        if selected_plugin_source == "auto":
            selected_plugin_source = "local" if local_plugin_candidate.exists() else "git"

        if selected_plugin_source == "local":
            if not local_plugin_candidate.exists():
                raise ValueError(
                    "Local plugin source was requested, but no plugin clone was found. Pass --plugin-path or use --plugin-source git."
                )
            relative_plugin = os.path.relpath(local_plugin_candidate, packages_dir).replace("\\", "/")
            plugin_reference = f"file:{relative_plugin}"
            plugin_reference_display = str(local_plugin_candidate)
        else:
            plugin_reference = "https://github.com/AnkleBreaker-Studio/unity-mcp-plugin.git"
            plugin_reference_display = plugin_reference

        scene_path = "Assets/Scenes/CodexCliSmoke.unity"
        files_to_write = {
            target_root / ".gitignore": build_unity_test_project_gitignore(),
            packages_dir / "manifest.json": build_unity_test_project_manifest(plugin_reference),
            project_settings_dir / "ProjectVersion.txt": (
                f"m_EditorVersion: {unity_version}\n"
                f"m_EditorVersionWithRevision: {unity_version} (8cf496087c8f)\n"
            ),
            editor_dir / "CodexCliTestProjectBootstrap.cs": build_unity_test_project_bootstrap_script(
                project_name,
                scene_path=scene_path,
            ),
            target_root / "CLI_TEST_COMMANDS.md": build_unity_test_project_readme(
                project_name,
                plugin_reference_display,
                scene_path=scene_path,
            ),
        }

        written_files: list[str] = []
        for path, content in files_to_write.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            written_files.append(str(path))

        return {
            "projectName": project_name,
            "projectPath": str(target_root),
            "unityVersion": unity_version,
            "pluginSource": selected_plugin_source,
            "pluginReference": plugin_reference,
            "pluginReferenceDisplay": plugin_reference_display,
            "starterScenePath": scene_path,
            "managedFiles": written_files,
            "nextSteps": [
                f"Open `{target_root}` in Unity.",
                "Wait for packages to restore and the bridge to log its port in the Unity console.",
                "Run `cli-anything-unity-mcp instances`, then `select <port>`.",
                "Start with `workflow inspect` or `debug snapshot`, then try `build-sample` and `build-fps-sample`.",
            ],
            "starterCommands": [
                "cli-anything-unity-mcp instances",
                "cli-anything-unity-mcp select <port>",
                "cli-anything-unity-mcp --json workflow inspect --port <port>",
                "cli-anything-unity-mcp --json debug snapshot --console-count 100 --include-hierarchy --port <port>",
                "cli-anything-unity-mcp --json debug watch --iterations 2 --interval 0 --console-count 20 --port <port>",
                "cli-anything-unity-mcp --json agent watch --iterations 2 --interval 0 --port <port>",
                "cli-anything-unity-mcp --json workflow build-sample --name CliSmokeArena --cleanup --port <port>",
                "cli-anything-unity-mcp --json workflow build-fps-sample --name CliSmokeFps --replace --scene-path Assets/Scenes/CliSmokeFps.unity --verify-level quick --port <port>",
            ],
        }

    _run_and_emit(ctx, _callback)


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
@click.option(
    "--visual-mode",
    type=click.Choice(["auto", "2d", "3d"], case_sensitive=False),
    default="auto",
    show_default=True,
    help="Choose whether the sample should be laid out as a 2D or 3D scene slice. Auto detects obvious 2D scenes.",
)
@click.option("--replace", is_flag=True, help="Replace an existing sample with the same root name before building.")
@click.option("--cleanup", is_flag=True, help="Remove the generated sample after validating it. Useful for repeatable testing.")
@click.option("--play-check/--no-play-check", default=True, help="Enter and exit play mode after building the sample.")
@click.option(
    "--capture",
    type=click.Choice(["none", "game", "scene", "both"], case_sensitive=False),
    default="both",
    show_default=True,
    help="Capture post-build validation screenshots from the Game View and/or Scene View.",
)
@click.option("--capture-width", type=int, default=640, show_default=True, help="Width for validation captures.")
@click.option("--capture-height", type=int, default=360, show_default=True, help="Height for validation captures.")
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
    visual_mode: str,
    replace: bool,
    cleanup: bool,
    play_check: bool,
    capture: str,
    capture_width: int,
    capture_height: int,
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
        hierarchy_snapshot = ctx.obj.backend.call_route_with_recovery(
            "scene/hierarchy",
            params={"maxDepth": 2, "maxNodes": 40},
            port=workflow_port,
            recovery_timeout=10.0,
        )
        hierarchy_nodes = list((hierarchy_snapshot or {}).get("hierarchy") or [])
        auto_2d_scene = any(
            isinstance(node, dict) and "Light2D" in list(node.get("components") or [])
            for node in hierarchy_nodes
        )
        resolved_visual_mode = visual_mode.lower()
        if resolved_visual_mode == "auto":
            resolved_visual_mode = "2d" if auto_2d_scene else "3d"

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
        object_paths = {
            "root": root_name,
            "floor": f"{root_name}/{object_names['floor']}",
            "player": f"{root_name}/{object_names['player']}",
            "beacon": f"{root_name}/{object_names['beacon']}",
            "observer": f"{root_name}/{object_names['observer']}",
            "beaconClone": f"{root_name}/{object_names['beaconClone']}",
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
                "visualMode": resolved_visual_mode,
                "cleanupRequested": cleanup,
                "playCheckRequested": play_check,
                "captureMode": capture.lower(),
                "savedAtStart": saved_at_start,
            },
            "before": {
                "scene": scene_info,
                "editorState": editor_state,
                "hierarchy": hierarchy_snapshot,
            },
            "scripts": {},
            "objects": {},
            "components": {},
            "wiring": {},
            "captures": {},
        }
        capture_dir = Path(".cli-anything-unity-mcp") / "captures"

        def _call_route(
            route: str,
            action: str,
            params: dict[str, Any] | None = None,
            recover: bool = False,
            use_queue: bool | None = None,
            record_history: bool = True,
        ) -> dict[str, Any]:
            result = (
                ctx.obj.backend.call_route_with_recovery(
                    route,
                    params=params,
                    port=workflow_port,
                    use_queue=use_queue,
                    record_history=record_history,
                    recovery_timeout=max(timeout, 10.0),
                    recovery_interval=max(0.25, interval),
                )
                if recover
                else ctx.obj.backend.call_route(
                    route,
                    params=params,
                    port=workflow_port,
                    use_queue=use_queue,
                    record_history=record_history,
                )
            )
            return require_workflow_success(result, action)

        def _call_tool(
            tool_name: str,
            action: str,
            params: dict[str, Any] | None = None,
            use_queue: bool | None = None,
        ) -> dict[str, Any]:
            return require_workflow_success(
                ctx.obj.backend.call_tool(tool_name, params=params, port=workflow_port, use_queue=use_queue),
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

        def _wait_for_gameobject_visible(game_object: str) -> dict[str, Any]:
            return require_workflow_success(
                wait_for_result(
                    lambda: ctx.obj.backend.call_route(
                        "gameobject/info",
                        params={"gameObjectPath": game_object},
                        port=workflow_port,
                        use_queue=False,
                        record_history=False,
                    ),
                    lambda result: workflow_error_message(result) is None,
                    timeout=timeout,
                    interval=interval,
                ),
                f"Confirm GameObject {game_object}",
            )

        def _wait_for_component_visible(game_object: str, component_type: str) -> dict[str, Any]:
            return require_workflow_success(
                wait_for_result(
                    lambda: ctx.obj.backend.call_route(
                        "gameobject/info",
                        params={"gameObjectPath": game_object},
                        port=workflow_port,
                        use_queue=False,
                        record_history=False,
                    ),
                    lambda result: workflow_error_message(result) is None and any(
                        (
                            component.get("type")
                            if isinstance(component, dict)
                            else str(component)
                        )
                        == component_type
                        for component in (result or {}).get("components", [])
                    ),
                    timeout=timeout,
                    interval=interval,
                ),
                f"Confirm component {component_type} on {game_object}",
            )

        def _attach_component(game_object: str, component_type: str) -> dict[str, Any]:
            add_result = require_workflow_success(
                wait_for_result(
                    lambda: ctx.obj.backend.call_tool(
                        "unity_component_add",
                        params={
                            "gameObjectPath": game_object,
                            "componentType": component_type,
                        },
                        port=workflow_port,
                        use_queue=False,
                    ),
                    lambda result: workflow_error_message(result) is None,
                    timeout=timeout,
                    interval=interval,
                ),
                f"Attach component {component_type} to {game_object}",
            )
            _wait_for_component_visible(game_object, component_type)
            return add_result

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
                use_queue=False,
            )

        def _capture_view(kind: str) -> dict[str, Any]:
            route = "graphics/game-capture" if kind == "game" else "graphics/scene-capture"
            result = _call_route(
                route,
                f"Capture {kind} view",
                {
                    "width": capture_width,
                    "height": capture_height,
                },
                recover=True,
                record_history=False,
            )
            encoded = str(result.get("base64") or "")
            if not encoded:
                raise ValueError(f"{kind} capture did not return image data.")
            capture_dir.mkdir(parents=True, exist_ok=True)
            output_path = (capture_dir / f"{sample_id}-{kind}.png").resolve()
            output_path.write_bytes(base64.b64decode(encoded))
            return {
                "path": str(output_path),
                "width": int(result.get("width") or capture_width),
                "height": int(result.get("height") or capture_height),
                "cameraName": result.get("cameraName"),
                "success": True,
            }

        def _record_captures() -> None:
            capture_mode = capture.lower()
            requested_kinds: list[str] = []
            if capture_mode in {"game", "both"}:
                requested_kinds.append("game")
            if capture_mode in {"scene", "both"}:
                requested_kinds.append("scene")
            for kind in requested_kinds:
                try:
                    payload["captures"][kind] = _capture_view(kind)
                except ValueError as exc:
                    payload["captures"][kind] = {"success": False, "error": str(exc)}
                    payload.setdefault("warnings", []).append(f"{kind} capture unavailable: {exc}")

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

            if resolved_visual_mode == "2d":
                payload["objects"]["layout"] = _call_route(
                    "editor/execute-code",
                    f"Create 2D sample layout for {root_name}",
                    {"code": build_2d_sample_layout_code(root_name)},
                    recover=True,
                )
                payload["objects"]["root"] = _call_tool(
                    "unity_gameobject_info",
                    f"Inspect sample root {root_name}",
                    {"gameObjectPath": object_paths["root"]},
                )
                payload["objects"]["floor"] = _call_tool(
                    "unity_gameobject_info",
                    f"Inspect sample floor {object_names['floor']}",
                    {"gameObjectPath": object_paths["floor"]},
                )
                payload["objects"]["player"] = _call_tool(
                    "unity_gameobject_info",
                    f"Inspect sample player {object_names['player']}",
                    {"gameObjectPath": object_paths["player"]},
                )
                payload["objects"]["beacon"] = _call_tool(
                    "unity_gameobject_info",
                    f"Inspect sample beacon {object_names['beacon']}",
                    {"gameObjectPath": object_paths["beacon"]},
                )
                payload["objects"]["observer"] = _call_tool(
                    "unity_gameobject_info",
                    f"Inspect sample observer {object_names['observer']}",
                    {"gameObjectPath": object_paths["observer"]},
                )
            else:
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
                object_paths["player"],
                script_names["spin"],
            )
            payload["components"]["beaconBob"] = _attach_component(
                object_paths["beacon"],
                script_names["bob"],
            )
            payload["components"]["observerFollow"] = _attach_component(
                object_paths["observer"],
                script_names["follow"],
            )

            payload["componentConfig"] = {
                "playerSpeed": _set_component_property(
                    object_paths["player"],
                    script_names["spin"],
                    "Speed",
                    36 if resolved_visual_mode == "2d" else 120,
                ),
                "playerAxis": _set_component_property(
                    object_paths["player"],
                    script_names["spin"],
                    "Axis",
                    vec3(0, 0, 1) if resolved_visual_mode == "2d" else vec3(0, 1, 0),
                ),
                "beaconHeight": _set_component_property(
                    object_paths["beacon"],
                    script_names["bob"],
                    "Height",
                    0.22 if resolved_visual_mode == "2d" else 0.45,
                ),
                "beaconSpeed": _set_component_property(
                    object_paths["beacon"],
                    script_names["bob"],
                    "Speed",
                    1.4 if resolved_visual_mode == "2d" else 1.8,
                ),
                "observerOffset": _set_component_property(
                    object_paths["observer"],
                    script_names["follow"],
                    "Offset",
                    vec3(0, 0, -10) if resolved_visual_mode == "2d" else vec3(0, 4.5, -8),
                ),
            }
            payload["wiring"]["observerTarget"] = _call_route(
                "component/set-reference",
                f"Wire observer target to {object_names['player']}",
                {
                    "gameObjectPath": object_paths["observer"],
                    "componentType": script_names["follow"],
                    "propertyName": "Target",
                    "referenceGameObject": object_paths["player"],
                    "referenceComponentType": "Transform",
                },
                use_queue=False,
            )

            payload["prefab"] = _call_route(
                "asset/create-prefab",
                f"Create sample prefab {prefab_path}",
                {
                    "gameObjectPath": object_paths["beacon"],
                    "savePath": prefab_path,
                },
                use_queue=True,
            )
            created_assets.append(prefab_path)
            payload["objects"]["beaconClone"] = _call_route(
                "asset/instantiate-prefab",
                f"Instantiate sample prefab clone {object_names['beaconClone']}",
                {
                    "prefabPath": prefab_path,
                    "name": object_names["beaconClone"],
                    "parent": object_paths["root"],
                    "position": vec3(-4.8, 0.8, 0) if resolved_visual_mode == "2d" else vec3(-4, 1, 0),
                },
                use_queue=True,
            )
            _wait_for_gameobject_visible(object_paths["beaconClone"])
            if resolved_visual_mode == "2d":
                payload["objects"]["beaconCloneRepair"] = _call_route(
                    "editor/execute-code",
                    f"Restore 2D sprite visuals for {object_names['beaconClone']}",
                    {"code": build_2d_sample_clone_repair_code(object_names["beaconClone"])},
                    recover=True,
                )
            payload["componentConfig"]["beaconCloneSpeed"] = _set_component_property(
                object_paths["beaconClone"],
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
            _record_captures()

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


@workflow_group.command("build-fps-sample")
@click.option("--name", type=str, default="CodexFpsShowcase", show_default=True, help="Root name for the generated FPS sample.")
@click.option(
    "--scene-path",
    type=str,
    default="Assets/Scenes/CodexFpsShowcase.unity",
    show_default=True,
    help="Scene asset path for the generated FPS slice.",
)
@click.option(
    "--folder",
    type=str,
    default="Assets/CodexSamples/FPS",
    show_default=True,
    help="Asset folder for generated FPS scripts and materials.",
)
@click.option("--replace", is_flag=True, help="Replace an existing generated scene and material assets with the same paths.")
@click.option(
    "--verify-level",
    type=click.Choice(["quick", "standard", "deep"], case_sensitive=False),
    default="standard",
    show_default=True,
    help="Validation depth: quick for fast rebuilds, standard for one game capture, deep for full captures, scene stats, and play-mode validation.",
)
@click.option(
    "--play-check/--no-play-check",
    default=None,
    help="Override play-mode validation. When omitted, the value is derived from --verify-level.",
)
@click.option(
    "--capture",
    type=click.Choice(["none", "game", "scene", "both"], case_sensitive=False),
    default=None,
    help="Override capture mode. When omitted, the value is derived from --verify-level.",
)
@click.option("--capture-width", type=int, default=960, show_default=True, help="Width for validation captures.")
@click.option("--capture-height", type=int, default=540, show_default=True, help="Height for validation captures.")
@click.option("--save-if-dirty-start", is_flag=True, help="Save the active scene first if the workflow needs to switch away from a dirty scene.")
@click.option("--timeout", type=float, default=30.0, show_default=True, help="Seconds to wait for compilation and play mode transitions.")
@click.option("--interval", type=float, default=0.5, show_default=True, help="Polling interval while waiting for Unity to settle.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_build_fps_sample_command(
    ctx: click.Context,
    name: str,
    scene_path: str,
    folder: str,
    replace: bool,
    verify_level: str,
    play_check: bool | None,
    capture: str | None,
    capture_width: int,
    capture_height: int,
    save_if_dirty_start: bool,
    timeout: float,
    interval: float,
    port: int | None,
) -> None:
    """Build a fresh 3D FPS-ready sample scene with authored materials, lighting, captures, and play-mode validation."""

    def _callback() -> dict[str, Any]:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        verify_level_name = str(verify_level or "standard").lower()
        default_capture_by_level = {
            "quick": "none",
            "standard": "game",
            "deep": "both",
        }
        default_play_check_by_level = {
            "quick": False,
            "standard": False,
            "deep": True,
        }
        effective_capture = str(capture or default_capture_by_level[verify_level_name]).lower()
        effective_play_check = (
            bool(play_check)
            if play_check is not None
            else default_play_check_by_level[verify_level_name]
        )
        include_deep_validation = verify_level_name == "deep"

        root_name = str(name or "").strip()
        if not root_name:
            raise ValueError("A non-empty FPS sample name is required.")

        sample_id = sanitize_csharp_identifier(root_name)
        normalized_folder = folder.replace("\\", "/").strip().rstrip("/")
        if not normalized_folder:
            normalized_folder = "Assets/CodexSamples/FPS"
        if not normalized_folder.lower().startswith("assets"):
            normalized_folder = f"Assets/{normalized_folder.lstrip('/')}"

        normalized_scene_path = scene_path.replace("\\", "/").strip()
        if not normalized_scene_path:
            normalized_scene_path = f"Assets/Scenes/{sample_id}.unity"
        if not normalized_scene_path.lower().startswith("assets/"):
            normalized_scene_path = f"Assets/{normalized_scene_path.lstrip('/')}"
        if not normalized_scene_path.lower().endswith(".unity"):
            normalized_scene_path = f"{normalized_scene_path}.unity"

        material_folder = f"{normalized_folder}/Materials"
        controller_class = f"{sample_id}FpsController"
        controller_script_path = build_asset_path(normalized_folder, controller_class)
        material_paths = {
            "floor": build_asset_path(material_folder, f"{sample_id}Floor", extension=".mat"),
            "wall": build_asset_path(material_folder, f"{sample_id}Wall", extension=".mat"),
            "trim": build_asset_path(material_folder, f"{sample_id}Trim", extension=".mat"),
            "accent": build_asset_path(material_folder, f"{sample_id}Accent", extension=".mat"),
            "sky": build_asset_path(material_folder, f"{sample_id}Sky", extension=".mat"),
        }

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
        try:
            starting_scene_path = get_active_scene_path(scene_info)
        except ValueError:
            starting_scene_path = None
        starting_dirty = bool(editor_state.get("sceneDirty"))
        saved_at_start = False
        if starting_dirty and not starting_scene_path:
            raise ValueError(
                "build-fps-sample started from an unsaved temporary scene. Open or save a real scene first, or discard the temporary scene and rerun."
            )
        if starting_dirty and not save_if_dirty_start:
            raise ValueError(
                "build-fps-sample needs a clean starting scene before switching scenes. Save manually or rerun with --save-if-dirty-start."
            )
        if starting_dirty and save_if_dirty_start and starting_scene_path:
            require_workflow_success(
                ctx.obj.backend.call_route_with_recovery(
                    "scene/save",
                    port=workflow_port,
                    recovery_timeout=15.0,
                ),
                f"Save dirty scene {starting_scene_path}",
            )
            editor_state = ctx.obj.backend.call_route_with_recovery(
                "editor/state",
                port=workflow_port,
                record_history=False,
                recovery_timeout=10.0,
            )
            starting_dirty = bool(editor_state.get("sceneDirty"))
            saved_at_start = True

        payload: dict[str, Any] = {
            "summary": {
                "sampleName": root_name,
                "sampleId": sample_id,
                "scenePath": normalized_scene_path,
                "assetFolder": normalized_folder,
                "materialFolder": material_folder,
                "replace": replace,
                "verifyLevel": verify_level_name,
                "playCheckRequested": effective_play_check,
                "captureMode": effective_capture,
                "savedAtStart": saved_at_start,
            },
            "before": {
                "scene": scene_info,
                "editorState": editor_state,
            },
            "materials": material_paths,
            "captures": {},
        }
        capture_dir = Path(".cli-anything-unity-mcp") / "captures"
        failure_message: str | None = None

        player_path = f"{root_name}/{root_name}_Player"
        camera_path = f"{player_path}/MainCamera"
        floor_path = f"{root_name}/{root_name}_Environment/{root_name}_Floor"
        hud_path = f"{root_name}/{root_name}_HUD"

        def _call_route(
            route: str,
            action: str,
            params: dict[str, Any] | None = None,
            *,
            recover: bool = False,
            use_queue: bool | None = None,
            record_history: bool = True,
        ) -> dict[str, Any]:
            result = (
                ctx.obj.backend.call_route_with_recovery(
                    route,
                    params=params,
                    port=workflow_port,
                    use_queue=use_queue,
                    record_history=record_history,
                    recovery_timeout=max(timeout, 10.0),
                    recovery_interval=max(0.25, interval),
                )
                if recover
                else ctx.obj.backend.call_route(
                    route,
                    params=params,
                    port=workflow_port,
                    use_queue=use_queue,
                    record_history=record_history,
                )
            )
            return require_workflow_success(result, action)

        def _call_tool(
            tool_name: str,
            action: str,
            params: dict[str, Any] | None = None,
            *,
            use_queue: bool | None = None,
        ) -> dict[str, Any]:
            return require_workflow_success(
                ctx.obj.backend.call_tool(tool_name, params=params, port=workflow_port, use_queue=use_queue),
                action,
            )

        def _fetch_editor_state() -> dict[str, Any]:
            return (
                ctx.obj.backend.call_route_with_recovery(
                    "editor/state",
                    port=workflow_port,
                    record_history=False,
                    recovery_timeout=max(timeout, 10.0),
                    recovery_interval=max(0.25, interval),
                )
                or {}
            )

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

        def _wait_for_component_visible(game_object: str, component_type: str) -> dict[str, Any]:
            return require_workflow_success(
                wait_for_result(
                    lambda: ctx.obj.backend.call_route(
                        "gameobject/info",
                        params={"gameObjectPath": game_object},
                        port=workflow_port,
                        use_queue=False,
                        record_history=False,
                    ),
                    lambda result: workflow_error_message(result) is None and any(
                        (
                            component.get("type")
                            if isinstance(component, dict)
                            else str(component)
                        )
                        == component_type
                        for component in (result or {}).get("components", [])
                    ),
                    timeout=timeout,
                    interval=interval,
                ),
                f"Confirm component {component_type} on {game_object}",
            )

        def _capture_view(kind: str) -> dict[str, Any]:
            route = "graphics/game-capture" if kind == "game" else "graphics/scene-capture"
            result = _call_route(
                route,
                f"Capture {kind} view",
                {
                    "width": capture_width,
                    "height": capture_height,
                },
                recover=True,
                record_history=False,
            )
            encoded = str(result.get("base64") or "")
            if not encoded:
                raise ValueError(f"{kind} capture did not return image data.")
            capture_dir.mkdir(parents=True, exist_ok=True)
            output_path = (capture_dir / f"{sample_id}-{kind}.png").resolve()
            output_path.write_bytes(base64.b64decode(encoded))
            return {
                "path": str(output_path),
                "width": int(result.get("width") or capture_width),
                "height": int(result.get("height") or capture_height),
                "cameraName": result.get("cameraName"),
                "success": True,
            }

        def _record_captures() -> None:
            capture_mode = effective_capture
            requested_kinds: list[str] = []
            if capture_mode in {"game", "both"}:
                requested_kinds.append("game")
            if capture_mode in {"scene", "both"}:
                requested_kinds.append("scene")
            for kind in requested_kinds:
                try:
                    payload["captures"][kind] = _capture_view(kind)
                except ValueError as exc:
                    payload["captures"][kind] = {"success": False, "error": str(exc)}
                    payload.setdefault("warnings", []).append(f"{kind} capture unavailable: {exc}")

        def _ensure_script_matches(path: str, content: str) -> tuple[dict[str, Any], bool]:
            existing = ctx.obj.backend.call_route(
                "script/read",
                params={"path": path},
                port=workflow_port,
                record_history=False,
            )
            if not _is_workflow_missing_error(existing):
                existing_payload = require_workflow_success(existing, f"Read script {path}")
                if str(existing_payload.get("content") or "") == content:
                    return (
                        {
                            "success": True,
                            "path": path,
                            "size": len(content),
                            "status": "unchanged",
                            "skippedWrite": True,
                        },
                        False,
                    )
                return (
                    _call_route(
                        "script/update",
                        f"Update FPS controller script {path}",
                        {"path": path, "content": content},
                    )
                    | {"status": "updated", "skippedWrite": False},
                    True,
                )

            return (
                _call_route(
                    "script/create",
                    f"Create FPS controller script {path}",
                    {"path": path, "content": content},
                )
                | {"status": "created", "skippedWrite": False},
                True,
            )

        try:
            controller_script_content = build_demo_fps_controller_script(controller_class)
            payload["script"], script_changed = _ensure_script_matches(
                controller_script_path,
                controller_script_content,
            )

            if script_changed:
                payload["compilation"] = wait_for_compilation(
                    _fetch_compilation,
                    timeout=timeout,
                    interval=interval,
                )
                if int((payload["compilation"] or {}).get("count") or 0) > 0:
                    entries = payload["compilation"].get("entries") or []
                    first_entry = entries[0] if entries and isinstance(entries[0], dict) else {}
                    first_message = first_entry.get("message") or "Unity reported compilation errors."
                    raise ValueError(f"build-fps-sample compilation failed: {first_message}")
            else:
                payload["compilation"] = {
                    "count": 0,
                    "isCompiling": False,
                    "entries": [],
                    "skipped": True,
                    "reason": "Controller script was unchanged.",
                }

            payload["sceneBuild"] = _call_route(
                "editor/execute-code",
                f"Build FPS sample scene {normalized_scene_path}",
                {
                    "code": build_3d_fps_sample_scene_code(
                        root_name,
                        normalized_scene_path,
                        replace_existing=replace,
                        floor_material_path=material_paths["floor"],
                        wall_material_path=material_paths["wall"],
                        trim_material_path=material_paths["trim"],
                        accent_material_path=material_paths["accent"],
                        sky_material_path=material_paths["sky"],
                    )
                },
                recover=True,
                use_queue=True,
            )

            payload["objects"] = {
                "root": _call_tool(
                    "unity_gameobject_info",
                    f"Inspect FPS sample root {root_name}",
                    {"gameObjectPath": root_name},
                ),
                "player": _call_tool(
                    "unity_gameobject_info",
                    f"Inspect FPS sample player {player_path}",
                    {"gameObjectPath": player_path},
                ),
                "camera": _call_tool(
                    "unity_gameobject_info",
                    f"Inspect FPS sample camera {camera_path}",
                    {"gameObjectPath": camera_path},
                ),
                "hud": _call_tool(
                    "unity_gameobject_info",
                    f"Inspect FPS sample HUD {hud_path}",
                    {"gameObjectPath": hud_path},
                ),
            }

            payload["components"] = {
                "controller": _call_tool(
                    "unity_component_add",
                    f"Attach FPS controller {controller_class}",
                    {
                        "gameObjectPath": player_path,
                        "componentType": controller_class,
                    },
                ),
            }
            _wait_for_component_visible(player_path, controller_class)

            payload["componentConfig"] = {
                "moveSpeed": _call_tool(
                    "unity_component_set_property",
                    f"Set {controller_class}.MoveSpeed",
                    {
                        "gameObjectPath": player_path,
                        "componentType": controller_class,
                        "propertyName": "MoveSpeed",
                        "value": 6.75,
                    },
                    use_queue=False,
                ),
                "sprintSpeed": _call_tool(
                    "unity_component_set_property",
                    f"Set {controller_class}.SprintSpeed",
                    {
                        "gameObjectPath": player_path,
                        "componentType": controller_class,
                        "propertyName": "SprintSpeed",
                        "value": 9.5,
                    },
                    use_queue=False,
                ),
                "mouseSensitivity": _call_tool(
                    "unity_component_set_property",
                    f"Set {controller_class}.MouseSensitivity",
                    {
                        "gameObjectPath": player_path,
                        "componentType": controller_class,
                        "propertyName": "MouseSensitivity",
                        "value": 0.085,
                    },
                    use_queue=False,
                ),
                "mouseSensitivityStep": _call_tool(
                    "unity_component_set_property",
                    f"Set {controller_class}.MouseSensitivityStep",
                    {
                        "gameObjectPath": player_path,
                        "componentType": controller_class,
                        "propertyName": "MouseSensitivityStep",
                        "value": 0.01,
                    },
                    use_queue=False,
                ),
                "fireRate": _call_tool(
                    "unity_component_set_property",
                    f"Set {controller_class}.FireRate",
                    {
                        "gameObjectPath": player_path,
                        "componentType": controller_class,
                        "propertyName": "FireRate",
                        "value": 6.75,
                    },
                    use_queue=False,
                ),
                "jumpHeight": _call_tool(
                    "unity_component_set_property",
                    f"Set {controller_class}.JumpHeight",
                    {
                        "gameObjectPath": player_path,
                        "componentType": controller_class,
                        "propertyName": "JumpHeight",
                        "value": 1.15,
                    },
                    use_queue=False,
                ),
            }

            payload["sceneSave"] = _call_route(
                "scene/save",
                f"Save FPS sample scene {normalized_scene_path}",
                recover=True,
            )

            payload["validation"] = {
                "scene": _call_route(
                    "scene/info",
                    "Read FPS scene info",
                    recover=True,
                    record_history=False,
                ),
                "editorState": _call_route(
                    "editor/state",
                    "Read FPS editor state",
                    recover=True,
                    record_history=False,
                ),
            }
            if include_deep_validation:
                payload["validation"].update(
                    {
                        "hierarchy": _call_route(
                            "scene/hierarchy",
                            "Read FPS sample hierarchy",
                            {"maxDepth": 4, "maxNodes": 80},
                            recover=True,
                            record_history=False,
                        ),
                        "stats": _call_tool(
                            "unity_scene_stats",
                            "Read FPS scene stats",
                            {},
                        ),
                        "floorRenderer": _call_tool(
                            "unity_graphics_renderer_info",
                            "Inspect FPS floor renderer",
                            {"objectPath": floor_path},
                        ),
                        "floorMaterial": _call_tool(
                            "unity_graphics_material_info",
                            "Inspect FPS floor material",
                            {
                                "assetPath": material_paths["floor"],
                                "includePreview": False,
                            },
                        ),
                        "accentMaterial": _call_tool(
                            "unity_graphics_material_info",
                            "Inspect FPS accent material",
                            {
                                "assetPath": material_paths["accent"],
                                "includePreview": False,
                            },
                        ),
                    }
                )

            _record_captures()

            if effective_play_check:
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
                    raise ValueError("build-fps-sample timed out waiting for Unity to enter play mode.")

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
                    raise ValueError("build-fps-sample timed out waiting for Unity to exit play mode.")

                payload["playMode"] = {
                    "enter": {"command": play_command_result, "state": play_state},
                    "exit": {"command": stop_command_result, "state": stop_state},
                }

            payload["after"] = {
                "editorState": _call_route(
                    "editor/state",
                    "Read editor state after FPS build",
                    recover=True,
                    record_history=False,
                ),
                "scene": _call_route(
                    "scene/info",
                    "Read scene info after FPS build",
                    recover=True,
                    record_history=False,
                ),
            }
        except Exception as exc:
            failure_message = str(exc)
            can_restore = bool(starting_scene_path) and ((not starting_dirty) or saved_at_start)
            if can_restore:
                try:
                    payload["recovery"] = {
                        "sceneReset": _call_route(
                            "scene/open",
                            f"Restore starting scene {starting_scene_path}",
                            {"path": starting_scene_path, "discardUnsaved": True},
                            recover=True,
                        )
                    }
                except (BackendSelectionError, UnityMCPClientError, ValueError) as recovery_exc:
                    payload["recovery"] = {"error": str(recovery_exc)}

        if failure_message:
            recovery_error = ((payload.get("recovery") or {}).get("error") if isinstance(payload.get("recovery"), dict) else None)
            if recovery_error:
                failure_message += f" Recovery issue: {recovery_error}"
            raise ValueError(failure_message)

        payload["summary"]["sceneCreated"] = (
            ((payload.get("after") or {}).get("scene") or {}).get("activeScene") == Path(normalized_scene_path).stem
        )
        payload["summary"]["finalSceneDirty"] = bool(
            ((payload.get("after") or {}).get("editorState") or {}).get("sceneDirty")
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
    "--sample-backed/--no-sample-backed",
    default=True,
    help="Create a disposable scene sample so graphics and physics tools can be probed against real scene objects.",
)
@click.option("--prefix", type=str, default="CodexAdvancedAudit", show_default=True, help="Prefix used for any temporary sample objects.")
@click.option("--save-if-dirty-start", is_flag=True, help="Save the active scene first if sample-backed probes need a clean rollback path.")
@click.option("--timeout", type=float, default=20.0, show_default=True, help="Seconds to wait for scene recovery and cleanup steps.")
@click.option("--interval", type=float, default=0.25, show_default=True, help="Polling interval while waiting for Unity to settle.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_audit_advanced_command(
    ctx: click.Context,
    categories: tuple[str, ...],
    sample_backed: bool,
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

        scene_mutation_requested = sample_backed or any(
            _category_allowed(category) for category in ("ui", "lighting", "terrain")
        )

        if scene_mutation_requested and starting_dirty and not save_if_dirty_start:
            raise ValueError(
                "Advanced audits that create scene content require a clean starting scene. Save manually or rerun with --save-if-dirty-start."
            )
        if scene_mutation_requested and starting_dirty and save_if_dirty_start:
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
            "sampleBacked": sample_backed,
            "probes": [],
            "sample": None,
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

            if sample_backed:
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
                payload["sample"] = sample_payload

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
                        "Raycast through the disposable sample",
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
                            f"sample-backed:{category}",
                            f"Sample-backed {category} probes",
                            skip_reason="Skipped because --no-sample-backed was used.",
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
            "sampleBacked": sample_backed,
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
