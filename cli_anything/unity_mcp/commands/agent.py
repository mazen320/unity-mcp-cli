from __future__ import annotations

import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Callable

import click

from ._shared import (
    BackendSelectionError,
    UnityMCPClientError,
    _run_and_emit,
    _serialize_agent_profile,
    _suggest_agent_id,
)


@click.group("agent")
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
