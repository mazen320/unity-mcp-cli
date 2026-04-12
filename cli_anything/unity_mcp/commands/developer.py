from __future__ import annotations

from dataclasses import asdict
from typing import Any

import click

from ._shared import _run_and_emit, _serialize_developer_profile


@click.group("developer")
def developer_group() -> None:
    """Manage the CLI developer profile that shapes how this harness works."""


@developer_group.command("current")
@click.pass_context
def developer_current_command(ctx: click.Context) -> None:
    """Show the resolved developer profile for this CLI invocation."""

    def _callback() -> dict[str, Any]:
        state = ctx.obj.developer_profile_store.list_profiles()
        return {
            "resolved": {
                "profile": _serialize_developer_profile(ctx.obj.developer_profile),
                "source": ctx.obj.developer_source,
            },
            "selectedProfile": state.selected_profile,
            "availableProfileCount": len(state.profiles),
        }

    _run_and_emit(ctx, _callback)


@developer_group.command("list")
@click.pass_context
def developer_list_command(ctx: click.Context) -> None:
    """List the available developer profiles."""

    def _callback() -> dict[str, Any]:
        state = ctx.obj.developer_profile_store.list_profiles()
        resolved_name = ctx.obj.developer_profile.name.lower()
        return {
            "selectedProfile": state.selected_profile,
            "resolvedProfile": ctx.obj.developer_profile.name,
            "profiles": [
                {
                    **asdict(profile),
                    "isSelected": bool(state.selected_profile and state.selected_profile.lower() == profile.name.lower()),
                    "isResolved": profile.name.lower() == resolved_name,
                }
                for profile in state.profiles
            ],
            "count": len(state.profiles),
        }

    _run_and_emit(ctx, _callback)


@developer_group.command("use")
@click.argument("name")
@click.pass_context
def developer_use_command(ctx: click.Context, name: str) -> None:
    """Select a developer profile for future CLI runs."""

    def _callback() -> dict[str, Any]:
        state = ctx.obj.developer_profile_store.select_profile(name)
        profile = ctx.obj.developer_profile_store.get_profile(name)
        return {
            "success": True,
            "message": f"Selected developer profile `{name}`.",
            "selectedProfile": state.selected_profile,
            "profile": _serialize_developer_profile(profile),
        }

    _run_and_emit(ctx, _callback)


@developer_group.command("clear")
@click.pass_context
def developer_clear_command(ctx: click.Context) -> None:
    """Clear the saved developer profile selection and fall back to normal mode."""

    def _callback() -> dict[str, Any]:
        state = ctx.obj.developer_profile_store.clear_selection()
        profile = ctx.obj.developer_profile_store.default_profile()
        return {
            "success": True,
            "message": "Cleared the selected developer profile. The CLI will fall back to `normal`.",
            "selectedProfile": state.selected_profile,
            "resolvedProfile": _serialize_developer_profile(profile),
        }

    _run_and_emit(ctx, _callback)
