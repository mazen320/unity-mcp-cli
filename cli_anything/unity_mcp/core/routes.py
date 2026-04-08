from __future__ import annotations

from typing import Dict, Iterable, List


class RouteResolutionError(ValueError):
    """Raised when a Unity tool name cannot be mapped to an HTTP route."""


TOOL_ROUTE_OVERRIDES: Dict[str, str] = {
    "unity_editor_ping": "ping",
    "unity_execute_code": "editor/execute-code",
    "unity_build": "build/start",
    "unity_play_mode": "editor/play-mode",
    "unity_execute_menu_item": "editor/execute-menu-item",
    "unity_get_compilation_errors": "compilation/errors",
    "unity_set_object_reference": "prefab/set-object-reference",
    "unity_selection_focus_scene_view": "selection/focus-scene-view",
    "unity_selection_find_by_type": "selection/find-by-type",
    "unity_undo": "undo/perform",
    "unity_redo": "undo/redo",
    "unity_undo_history": "undo/history",
    "unity_undo_clear": "undo/clear",
    "unity_graphics_scene_capture": "graphics/scene-capture",
    "unity_graphics_game_capture": "graphics/game-capture",
    "unity_mppm_list_scenarios": "scenario/list",
    "unity_mppm_status": "scenario/status",
    "unity_mppm_activate_scenario": "scenario/activate",
    "unity_mppm_start": "scenario/start",
    "unity_mppm_stop": "scenario/stop",
    "unity_mppm_info": "scenario/info",
}

ROUTE_TOOL_OVERRIDES: Dict[str, str] = {route: tool for tool, route in TOOL_ROUTE_OVERRIDES.items()}

UNSUPPORTED_TOOL_PREFIXES = ("unity_hub_",)

KNOWN_TOOL_SPECS: Dict[str, Dict[str, str]] = {
    "unity_editor_ping": {
        "route": "ping",
        "description": "Check whether the Unity bridge is reachable.",
    },
    "unity_editor_state": {
        "route": "editor/state",
        "description": "Get play mode, project, and editor status information.",
    },
    "unity_project_info": {
        "route": "project/info",
        "description": "Get project metadata and package/build details.",
    },
    "unity_scene_info": {
        "route": "scene/info",
        "description": "Get information about the active scene.",
    },
    "unity_scene_hierarchy": {
        "route": "scene/hierarchy",
        "description": "Fetch the current scene hierarchy tree.",
    },
    "unity_scene_stats": {
        "route": "scene/stats",
        "description": "Collect high-level object and component counts for the active scene.",
    },
    "unity_console_log": {
        "route": "console/log",
        "description": "Read recent Unity console entries.",
    },
    "unity_search_missing_references": {
        "route": "search/missing-references",
        "description": "Find missing scene references and null script components.",
    },
    "unity_script_read": {
        "route": "script/read",
        "description": "Read a C# script asset from the Unity project.",
    },
    "unity_script_update": {
        "route": "script/update",
        "description": "Replace the contents of a C# script asset.",
    },
    "unity_script_create": {
        "route": "script/create",
        "description": "Create a new C# script asset.",
    },
    "unity_execute_code": {
        "route": "editor/execute-code",
        "description": "Run arbitrary C# editor code through the bridge.",
    },
    "unity_play_mode": {
        "route": "editor/play-mode",
        "description": "Enter, pause, or stop Unity play mode.",
    },
    "unity_build": {
        "route": "build/start",
        "description": "Start a Unity build.",
    },
    "unity_component_set_reference": {
        "route": "component/set-reference",
        "description": "Assign or clear an ObjectReference field on a component.",
    },
    "unity_asset_create_prefab": {
        "route": "asset/create-prefab",
        "description": "Save a scene object as a prefab asset.",
    },
    "unity_asset_instantiate_prefab": {
        "route": "asset/instantiate-prefab",
        "description": "Instantiate a prefab asset into the current scene.",
    },
    "unity_undo": {
        "route": "undo/perform",
        "description": "Undo the last Unity editor action.",
    },
    "unity_redo": {
        "route": "undo/redo",
        "description": "Redo the last undone Unity editor action.",
    },
}


def tool_name_to_route(tool_name: str) -> str:
    if not tool_name:
        raise RouteResolutionError("Tool name is required.")
    if any(tool_name.startswith(prefix) for prefix in UNSUPPORTED_TOOL_PREFIXES):
        raise RouteResolutionError(
            f"{tool_name} is not supported by this harness yet because it depends on Unity Hub, not the editor bridge."
        )
    if tool_name in TOOL_ROUTE_OVERRIDES:
        return TOOL_ROUTE_OVERRIDES[tool_name]
    if not tool_name.startswith("unity_"):
        raise RouteResolutionError(
            f"{tool_name} is not a valid Unity MCP tool name. Expected a name like unity_scene_info."
        )
    without_prefix = tool_name[len("unity_") :]
    parts = without_prefix.split("_")
    if len(parts) < 2:
        raise RouteResolutionError(
            f"{tool_name} does not contain enough segments to derive a route."
        )
    category = parts[0]
    action = "-".join(parts[1:])
    return f"{category}/{action}"


def route_to_tool_name(route: str) -> str:
    if route in ROUTE_TOOL_OVERRIDES:
        return ROUTE_TOOL_OVERRIDES[route]
    return "unity_" + route.replace("/", "_").replace("-", "_")


def iter_known_tools(category: str | None = None) -> List[Dict[str, str]]:
    items: Iterable[tuple[str, Dict[str, str]]] = KNOWN_TOOL_SPECS.items()
    result: List[Dict[str, str]] = []
    for name, spec in sorted(items):
        derived_category = spec["route"].split("/", 1)[0]
        if category and derived_category != category.lower():
            continue
        result.append(
            {
                "name": name,
                "route": spec["route"],
                "description": spec["description"],
            }
        )
    return result
