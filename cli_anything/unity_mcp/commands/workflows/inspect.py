"""Workflow inspect and asset-audit commands."""
from __future__ import annotations
from ._group import workflow_group
from ._helpers import *  # noqa: F401, F403

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

        result = {
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
        project_root = summary.get("projectPath") or ping.get("projectPath") or project.get("projectPath")
        if project_root:
            insights = build_project_insights(project_root, inspect_payload=result)
            result["projectInsights"] = insights
            summary["hasProjectGuidance"] = bool((insights.get("guidance") or {}).get("found"))
            summary["improvementSuggestionCount"] = len(insights.get("recommendations") or [])
        else:
            result["projectInsights"] = {
                "available": False,
                "error": "Project path is unavailable for local project analysis.",
            }
        _learn_from_inspect(ctx, result)
        return result

    _run_and_emit(ctx, _callback)


@workflow_group.command("asset-audit")
@click.argument("project_root", required=False)
@click.option(
    "--top-recommendations",
    type=click.IntRange(1, None),
    default=6,
    show_default=True,
    help="Maximum number of top recommendations to highlight in the summary block.",
)
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_asset_audit_command(
    ctx: click.Context,
    project_root: str | None,
    top_recommendations: int,
    port: int | None,
) -> None:
    """Audit a Unity project's asset layout, importer hints, and likely improvement areas."""

    if project_root:
        ctx.meta["disable_auto_breadcrumbs"] = True

    def _callback() -> dict[str, Any]:
        workflow_port = port
        ping: dict[str, Any] | None = None
        project: dict[str, Any] | None = None
        editor_state: dict[str, Any] | None = None
        inspect_payload: dict[str, Any] | None = None

        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        resolved_project_root = project_root
        if not resolved_project_root:
            _record_progress_step(ctx, "Checking project context for asset audit", phase="check", port=workflow_port)
            ping = ctx.obj.backend.ping(port=workflow_port)
            project = ctx.obj.backend.call_route_with_recovery(
                "project/info",
                port=workflow_port,
                recovery_timeout=10.0,
            )
            editor_state = ctx.obj.backend.call_route_with_recovery(
                "editor/state",
                port=workflow_port,
                recovery_timeout=10.0,
            )
            resolved_project_root = (
                ping.get("projectPath")
                or editor_state.get("projectPath")
                or project.get("projectPath")
            )
            inspect_payload = {
                "summary": {
                    "projectName": ping.get("projectName") or project.get("projectName"),
                    "projectPath": resolved_project_root,
                    "activeScene": editor_state.get("activeScene"),
                    "sceneDirty": bool(editor_state.get("sceneDirty")),
                },
                "project": project,
                "ping": ping,
            }

        if not resolved_project_root:
            raise ValueError(
                "Asset audit needs a Unity project path. Pass PROJECT_ROOT explicitly or select a Unity editor first."
            )

        _record_progress_step(
            ctx,
            f"Auditing assets in {Path(resolved_project_root).name}",
            phase="inspect",
            port=workflow_port,
        )
        report = build_asset_audit_report(
            resolved_project_root,
            inspect_payload=inspect_payload,
            recommendation_limit=top_recommendations,
        )
        if ping or project or editor_state:
            report["unityContext"] = {
                "ping": ping or {},
                "project": project or {},
                "editorState": editor_state or {},
            }
        return report

    _run_and_emit(ctx, _callback)



workflow_group.add_command(workflow_inspect_command)
workflow_group.add_command(workflow_asset_audit_command)
