from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from ._shared import (
    _run_and_emit,
    load_json_params,
)


@click.command("routes")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def routes_command(ctx: click.Context, port: int | None) -> None:
    """List live HTTP routes published by the Unity plugin."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.get_routes(port=port))


@click.command("tools")
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


@click.command("advanced-tools")
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


@click.command("tool-info")
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


@click.command("tool-coverage")
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
@click.option(
    "--next-batch",
    "next_batch_limit",
    type=click.IntRange(0, 50),
    default=0,
    show_default=True,
    help="Include a prioritized batch of deferred tools for the next live-validation pass.",
)
@click.option(
    "--fixture-plan",
    is_flag=True,
    help="Include package-level fixture plans for deferred optional-package live audits.",
)
@click.option(
    "--support-plan",
    is_flag=True,
    help="Include implementation plans for unsupported integration surfaces.",
)
@click.option(
    "--handoff-plan",
    is_flag=True,
    help="Include a compact cross-track plan for remaining coverage work.",
)
@click.pass_context
def tool_coverage_command(
    ctx: click.Context,
    category: str | None,
    status: str | None,
    search: str | None,
    summary_only: bool,
    exclude_unsupported: bool,
    next_batch_limit: int,
    fixture_plan: bool,
    support_plan: bool,
    handoff_plan: bool,
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
            next_batch_limit=next_batch_limit,
            fixture_plan=fixture_plan,
            support_plan=support_plan,
            handoff_plan=handoff_plan,
        ),
    )


@click.command("tool-template")
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


@click.command("queue-info")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def queue_info_command(ctx: click.Context, port: int | None) -> None:
    """Read queue statistics from the Unity plugin."""
    _run_and_emit(ctx, lambda: ctx.obj.backend.get_queue_info(port=port))


@click.command("route")
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


@click.command("tool")
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
