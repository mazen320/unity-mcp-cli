from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from ..core.memory import memory_for_session
from ._shared import (
    BackendSelectionError,
    UnityMCPClientError,
    _learn_from_inspect,
    _record_progress_step,
    _run_and_emit,
    build_asset_path,
    build_behaviour_script,
    get_active_scene_path,
    require_workflow_success,
    sanitize_csharp_identifier,
    unique_probe_name,
    vec3,
    wait_for_compilation,
    wait_for_result,
    workflow_error_message,
)


@click.group("workflow")
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
        _learn_from_inspect(ctx, result)
        return result

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

        _record_progress_step(ctx, f"Creating script {Path(script_path).name}", phase="create", port=workflow_port)
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

        _record_progress_step(ctx, "Waiting for Unity compilation to settle", phase="check", port=workflow_port)
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
            _record_progress_step(ctx, f"Creating GameObject {scene_object_name}", phase="create", port=workflow_port)
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

            _record_progress_step(
                ctx,
                f"Attaching {class_name} to {scene_object_name}",
                phase="edit",
                port=workflow_port,
            )
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
            _record_progress_step(
                ctx,
                f"Inspecting component properties for {class_name}",
                phase="inspect",
                port=workflow_port,
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

        _record_progress_step(ctx, "Inspecting active scene before reload", phase="inspect", port=workflow_port)
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

        _record_progress_step(ctx, f"Reloading scene {Path(scene_path).name}", phase="open", port=workflow_port)
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


@workflow_group.command("audit-advanced")
@click.option(
    "--category",
    "categories",
    multiple=True,
    help="Limit the audit to one or more advanced categories such as graphics, memory, physics, profiler, sceneview, settings, testing, ui, audio, lighting, animation, input, shadergraph, terrain, or navmesh.",
)
@click.option(
    "--probe-backed/--no-probe-backed",
    default=True,
    help="Create disposable scene probes so graphics and physics tools can be exercised against real scene objects.",
)
@click.option("--prefix", type=str, default="CodexAdvancedAudit", show_default=True, help="Prefix used for temporary probe objects.")
@click.option("--save-if-dirty-start", is_flag=True, help="Save the active scene first if probe creation needs a clean rollback path.")
@click.option("--timeout", type=float, default=20.0, show_default=True, help="Seconds to wait for scene recovery and cleanup steps.")
@click.option("--interval", type=float, default=0.25, show_default=True, help="Polling interval while waiting for Unity to settle.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_audit_advanced_command(
    ctx: click.Context,
    categories: tuple[str, ...],
    probe_backed: bool,
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

        _record_progress_step(ctx, "Inspecting audit start scene state", phase="inspect", port=workflow_port)
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

        scene_mutation_requested = probe_backed or any(
            _category_allowed(category) for category in ("ui", "lighting", "terrain")
        )

        if scene_mutation_requested and starting_dirty and not save_if_dirty_start:
            raise ValueError(
                "Advanced audits that create scene content require a clean starting scene. Save manually or rerun with --save-if-dirty-start."
            )
        if scene_mutation_requested and starting_dirty and save_if_dirty_start:
            _record_progress_step(ctx, f"Saving dirty scene {Path(scene_path).name}", phase="save", port=workflow_port)
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
            "probeBacked": probe_backed,
            "probes": [],
            "probeFixture": None,
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
                _record_progress_step(
                    ctx,
                    f"Probing {category} via {tool_name}",
                    phase="inspect",
                    port=workflow_port,
                )
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

            if probe_backed:
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
                payload["probeFixture"] = sample_payload

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
                        "Raycast through the disposable probe fixture",
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
                            f"probe-backed:{category}",
                            f"Probe-backed {category} probes",
                            skip_reason="Skipped because --no-probe-backed was used.",
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
            "probeBacked": probe_backed,
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

        _record_progress_step(
            ctx,
            f"Wiring {property_name} on {target_object}",
            phase="wire",
            port=workflow_port,
        )
        result = require_workflow_success(
            ctx.obj.backend.call_route("component/set-reference", params=params, port=workflow_port),
            f"Wire reference {property_name} on {target_object}",
        )
        _record_progress_step(
            ctx,
            f"Inspecting updated GameObject {target_object}",
            phase="inspect",
            port=workflow_port,
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

        _record_progress_step(ctx, f"Inspecting source GameObject {game_object}", phase="inspect", port=workflow_port)
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
        _record_progress_step(ctx, f"Creating prefab {Path(save_path).name}", phase="create", port=workflow_port)
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
            _record_progress_step(
                ctx,
                f"Instantiating prefab {Path(save_path).name}",
                phase="create",
                port=workflow_port,
            )
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
        stats_warning: str | None = None
        try:
            _record_progress_step(ctx, "Inspecting scene stats", phase="inspect", port=workflow_port)
            stats = require_workflow_success(
                ctx.obj.backend.call_route_with_recovery(
                    "scene/stats",
                    port=workflow_port,
                    recovery_timeout=10.0,
                ),
                "Read scene stats",
            )
        except (UnityMCPClientError, ValueError) as exc:
            _record_progress_step(ctx, "Falling back to hierarchy-derived scene stats", phase="inspect", port=workflow_port)
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
        _record_progress_step(ctx, f"Checking missing references (limit {limit})", phase="check", port=workflow_port)
        missing_references = require_workflow_success(
            ctx.obj.backend.call_route_with_recovery(
                "search/missing-references",
                params={"limit": limit},
                port=workflow_port,
                recovery_timeout=10.0,
            ),
            "Search for missing references",
        )
        _record_progress_step(ctx, f"Checking compilation errors (limit {limit})", phase="check", port=workflow_port)
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
            _record_progress_step(ctx, "Inspecting hierarchy snapshot", phase="inspect", port=workflow_port)
            payload["hierarchy"] = ctx.obj.backend.call_route_with_recovery(
                "scene/hierarchy",
                params={"maxDepth": 2, "maxNodes": 30},
                port=workflow_port,
                recovery_timeout=10.0,
            )

        # ── Memory: track recurring missing references ───────────────────
        try:
            session_state = ctx.obj.backend.session_store.load()
            mem = memory_for_session(session_state)
            if mem is not None:
                ref_results = missing_references.get("results") or []
                active_scene = (
                    scene.get("activeScene")
                    or state.get("activeScene")
                    or "unknown"
                )
                tracking = mem.record_missing_references(ref_results, active_scene)

                # Add tracking summary to the payload so the caller sees it.
                payload["missingRefTracking"] = tracking

                # Surface repeat offenders as top-level warnings.
                recurring = mem.get_recurring_missing_refs(min_seen=2)
                if recurring:
                    payload["recurringMissingRefs"] = recurring
                    repeat_summary = []
                    for r in recurring[:5]:
                        repeat_summary.append(
                            f"  - {r['gameObject']}"
                            + (f" ({r['component']})" if r.get("component") else "")
                            + f" - seen {r['seenCount']}x since {r['firstSeen'][:10]}"
                        )
                    warnings = payload.get("warnings") or []
                    warnings.append(
                        "Recurring missing references detected (repeat offenders):\n"
                        + "\n".join(repeat_summary)
                    )
                    payload["warnings"] = warnings
        except Exception as exc:
            # Memory integration is best-effort; never break validation.
            warnings = payload.get("warnings") or []
            warnings.append(f"Missing-reference memory tracking skipped: {exc}")
            payload["warnings"] = warnings

        return payload

    _run_and_emit(ctx, _callback)
