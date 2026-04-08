from __future__ import annotations

from typing import Dict, Iterable, List

from .tool_catalog import get_route_index, get_upstream_tool, iter_upstream_tools


class RouteResolutionError(ValueError):
    """Raised when a Unity tool name cannot be mapped to an HTTP route."""


TOOL_ROUTE_OVERRIDES: Dict[str, str] = {
    "unity_get_project_context": "context",
    "unity_queue_info": "queue/info",
    "unity_queue_ticket_status": "queue/status",
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


def tool_name_to_route(tool_name: str) -> str:
    if not tool_name:
        raise RouteResolutionError("Tool name is required.")
    if any(tool_name.startswith(prefix) for prefix in UNSUPPORTED_TOOL_PREFIXES):
        raise RouteResolutionError(
            f"{tool_name} is not supported by this harness yet because it depends on Unity Hub, not the editor bridge."
        )
    if tool_name in TOOL_ROUTE_OVERRIDES:
        return TOOL_ROUTE_OVERRIDES[tool_name]
    upstream_tool = get_upstream_tool(tool_name)
    if upstream_tool and upstream_tool.get("route"):
        return str(upstream_tool["route"])
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
    upstream_match = get_route_index().get(route)
    if upstream_match:
        return str(upstream_match["name"])
    return "unity_" + route.replace("/", "_").replace("-", "_")


def iter_known_tools(
    category: str | None = None,
    tier: str | None = None,
    search: str | None = None,
    include_unsupported: bool = False,
) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    for tool in iter_upstream_tools(
        category=category,
        tier=tier,
        search=search,
        include_unsupported=include_unsupported,
    ):
        result.append(
            {
                "name": str(tool["name"]),
                "route": str(tool["route"]) if tool.get("route") else "",
                "description": str(tool.get("description", "")),
                "tier": str(tool.get("tier", "")),
                "category": str(tool.get("category", "")),
                "execution": str(tool.get("execution", "")),
            }
        )
    return result
