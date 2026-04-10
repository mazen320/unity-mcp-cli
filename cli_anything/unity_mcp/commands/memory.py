from __future__ import annotations

import click

from ._shared import (
    ALL_CATEGORIES,
    ProjectMemory,
    _emit,
    memory_for_session,
)


def _require_memory(ctx: click.Context) -> "ProjectMemory":
    """Return a ProjectMemory for the active project, or exit with a helpful message."""
    state = ctx.obj.backend.session_store.load()
    mem = memory_for_session(state)
    if mem is None:
        raise click.ClickException(
            "No Unity instance selected. Run 'cli-anything-unity-mcp select <port>' first."
        )
    return mem


@click.group("memory")
def memory_group() -> None:
    """Persistent per-project memory — store and recall learned patterns and fixes."""


@memory_group.command("recall")
@click.option(
    "--category",
    type=click.Choice(sorted(ALL_CATEGORIES)),
    default=None,
    help="Filter by category.",
)
@click.option("--search", type=str, default=None, help="Case-insensitive substring search.")
@click.option("--limit", type=int, default=20, show_default=True, help="Max entries to return.")
@click.pass_context
def memory_recall_command(
    ctx: click.Context,
    category: "str | None",
    search: "str | None",
    limit: int,
) -> None:
    """Show what the CLI remembers about the current project."""
    mem = _require_memory(ctx)
    results = mem.recall(category=category, search=search, limit=limit)
    _emit(ctx, {"projectPath": mem.project_path, "count": len(results), "entries": results})


@memory_group.command("remember-fix")
@click.argument("error_pattern")
@click.argument("fix_command")
@click.option("--context", "fix_context", type=str, default="", help="Optional note about when this applies.")
@click.pass_context
def memory_remember_fix_command(
    ctx: click.Context,
    error_pattern: str,
    fix_command: str,
    fix_context: str,
) -> None:
    """Record that FIX_COMMAND resolved an error matching ERROR_PATTERN.

    \b
    Example:
      memory remember-fix "CS0246" "cli-anything-unity-mcp script-update ..."
    """
    mem = _require_memory(ctx)
    mem.remember_fix(error_pattern, fix_command, context=fix_context)
    _emit(ctx, {"saved": True, "errorPattern": error_pattern, "fixCommand": fix_command})


@memory_group.command("remember")
@click.argument("category", type=click.Choice(sorted(ALL_CATEGORIES)))
@click.argument("key")
@click.argument("value")
@click.pass_context
def memory_remember_command(
    ctx: click.Context,
    category: str,
    key: str,
    value: str,
) -> None:
    """Save an arbitrary memory entry.

    \b
    Examples:
      memory remember structure render_pipeline URP
      memory remember pattern addressables "Project uses Addressables, not Resources.Load"
    """
    mem = _require_memory(ctx)
    mem.save(category, key, {"value": value})
    _emit(ctx, {"saved": True, "category": category, "key": key, "value": value})


@memory_group.command("forget")
@click.option(
    "--category",
    type=click.Choice(sorted(ALL_CATEGORIES)),
    default=None,
    help="Limit deletion to a category.",
)
@click.option("--key", type=str, default=None, help="Delete a specific entry by key.")
@click.option("--all", "forget_all", is_flag=True, help="Clear all memories for this project.")
@click.pass_context
def memory_forget_command(
    ctx: click.Context,
    category: "str | None",
    key: "str | None",
    forget_all: bool,
) -> None:
    """Delete memories for the current project."""
    if not category and not forget_all:
        raise click.UsageError("Specify --category, --category + --key, or --all.")
    mem = _require_memory(ctx)
    deleted = mem.forget(category=None if forget_all else category, key=key)
    _emit(ctx, {"deleted": deleted})


@memory_group.command("stats")
@click.pass_context
def memory_stats_command(ctx: click.Context) -> None:
    """Show a summary of stored memories for the current project."""
    mem = _require_memory(ctx)
    _emit(ctx, mem.stats())
