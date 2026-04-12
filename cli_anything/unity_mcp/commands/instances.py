from __future__ import annotations

from typing import Any

import click

from ..core.memory import memory_for_session
from ._shared import (
    BackendSelectionError,
    UnityMCPClientError,
    _run_and_emit,
    _serialize_agent_profile,
    _serialize_developer_profile,
)


@click.command("instances")
@click.pass_context
def instances_command(ctx: click.Context) -> None:
    """List running Unity Editor instances."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.list_instances())


@click.command("select")
@click.argument("port", type=int)
@click.pass_context
def select_command(ctx: click.Context, port: int) -> None:
    """Select a Unity instance by port. Shows cached memory if available."""

    def _callback() -> dict[str, Any]:
        result = ctx.obj.backend.select_instance(port)

        # Auto-surface memory for known projects.
        try:
            session = ctx.obj.backend.session_store.load()
            mem = memory_for_session(session)
            if mem is not None:
                memory_summary = mem.summarize_for_selection()
                if memory_summary:
                    result["memory"] = memory_summary
        except Exception as exc:
            # Memory surfacing is best-effort, but keep failures visible.
            result["memoryWarning"] = f"Could not read project memory: {exc}"

        return result

    _run_and_emit(ctx, _callback)


@click.command("ping")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def ping_command(ctx: click.Context, port: int | None) -> None:
    """Ping the selected or auto-discovered Unity instance."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.ping(port=port))


@click.command("status")
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
            "developer": {
                "profile": _serialize_developer_profile(ctx.obj.developer_profile),
                "source": ctx.obj.developer_source,
            },
        }
        try:
            payload["ping"] = ctx.obj.backend.ping(port=port)
        except (BackendSelectionError, UnityMCPClientError) as exc:
            payload["pingError"] = str(exc)
        return payload

    _run_and_emit(ctx, _callback)
