from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .embedded_cli import EmbeddedCLIOptions, run_cli_json


ToolArgBuilder = Callable[[dict[str, Any]], list[str]]


@dataclass(frozen=True)
class MCPToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    build_args: ToolArgBuilder


def _add_option(args: list[str], flag: str, value: Any) -> None:
    if value is None:
        return
    args.extend([flag, str(value)])


def _add_flag(args: list[str], flag: str, enabled: bool) -> None:
    if enabled:
        args.append(flag)


def _add_toggle(args: list[str], positive_flag: str, negative_flag: str, value: bool | None) -> None:
    if value is None:
        return
    args.append(positive_flag if value else negative_flag)


def _require(arguments: dict[str, Any], key: str) -> Any:
    value = arguments.get(key)
    if value is None:
        raise ValueError(f"`{key}` is required.")
    return value


def _ensure_list(arguments: dict[str, Any], key: str) -> list[str]:
    value = arguments.get(key)
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    raise ValueError(f"`{key}` must be an array when provided.")


def _json_text(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True)


def _build_instances_args(arguments: dict[str, Any]) -> list[str]:
    del arguments
    return ["instances"]


def _build_select_instance_args(arguments: dict[str, Any]) -> list[str]:
    return ["select", str(_require(arguments, "port"))]


def _build_inspect_args(arguments: dict[str, Any]) -> list[str]:
    args = ["workflow", "inspect"]
    _add_option(args, "--hierarchy-depth", arguments.get("hierarchyDepth"))
    _add_option(args, "--hierarchy-nodes", arguments.get("hierarchyNodes"))
    _add_option(args, "--asset-folder", arguments.get("assetFolder"))
    _add_option(args, "--asset-limit", arguments.get("assetLimit"))
    _add_option(args, "--asset-search", arguments.get("assetSearch"))
    _add_option(args, "--port", arguments.get("port"))
    return args


def _build_console_args(arguments: dict[str, Any]) -> list[str]:
    args = ["console"]
    _add_option(args, "--count", arguments.get("count"))
    _add_option(args, "--type", arguments.get("type"))
    _add_option(args, "--port", arguments.get("port"))
    return args


def _build_play_args(arguments: dict[str, Any]) -> list[str]:
    args = ["play", str(_require(arguments, "action"))]
    _add_toggle(args, "--wait", "--no-wait", arguments.get("wait"))
    _add_option(args, "--timeout", arguments.get("timeout"))
    _add_option(args, "--interval", arguments.get("interval"))
    _add_option(args, "--port", arguments.get("port"))
    return args


def _build_validate_scene_args(arguments: dict[str, Any]) -> list[str]:
    args = ["workflow", "validate-scene"]
    _add_option(args, "--limit", arguments.get("limit"))
    _add_flag(args, "--include-hierarchy", bool(arguments.get("includeHierarchy")))
    _add_option(args, "--port", arguments.get("port"))
    return args


def _build_reset_scene_args(arguments: dict[str, Any]) -> list[str]:
    args = ["workflow", "reset-scene"]
    _add_flag(args, "--save-if-dirty", bool(arguments.get("saveIfDirty")))
    _add_flag(args, "--discard-unsaved", bool(arguments.get("discardUnsaved")))
    _add_flag(args, "--force-reload", bool(arguments.get("forceReload")))
    _add_option(args, "--port", arguments.get("port"))
    return args


def _build_create_behaviour_args(arguments: dict[str, Any]) -> list[str]:
    args = ["workflow", "create-behaviour", str(_require(arguments, "name"))]
    _add_option(args, "--folder", arguments.get("folder"))
    _add_option(args, "--namespace", arguments.get("namespace"))
    _add_option(args, "--object-name", arguments.get("objectName"))
    _add_toggle(args, "--attach", "--no-attach", arguments.get("attach"))
    _add_option(args, "--timeout", arguments.get("timeout"))
    _add_option(args, "--interval", arguments.get("interval"))
    _add_option(args, "--port", arguments.get("port"))
    return args


def _build_wire_reference_args(arguments: dict[str, Any]) -> list[str]:
    args = [
        "workflow",
        "wire-reference",
        str(_require(arguments, "targetObject")),
        str(_require(arguments, "componentType")),
        str(_require(arguments, "propertyName")),
    ]
    _add_option(args, "--reference-object", arguments.get("referenceObject"))
    _add_option(args, "--reference-component", arguments.get("referenceComponent"))
    _add_option(args, "--asset-path", arguments.get("assetPath"))
    _add_option(args, "--reference-instance-id", arguments.get("referenceInstanceId"))
    _add_flag(args, "--clear", bool(arguments.get("clear")))
    _add_option(args, "--port", arguments.get("port"))
    return args


def _build_create_prefab_args(arguments: dict[str, Any]) -> list[str]:
    args = ["workflow", "create-prefab", str(_require(arguments, "gameObject"))]
    _add_option(args, "--folder", arguments.get("folder"))
    _add_option(args, "--name", arguments.get("name"))
    _add_flag(args, "--instantiate", bool(arguments.get("instantiate")))
    _add_option(args, "--instance-name", arguments.get("instanceName"))
    _add_option(args, "--parent", arguments.get("parent"))
    _add_option(args, "--port", arguments.get("port"))
    return args


def _build_build_sample_args(arguments: dict[str, Any]) -> list[str]:
    args = ["workflow", "build-sample"]
    _add_option(args, "--name", arguments.get("name"))
    _add_option(args, "--folder", arguments.get("folder"))
    _add_option(args, "--prefab-folder", arguments.get("prefabFolder"))
    _add_option(args, "--visual-mode", arguments.get("visualMode"))
    _add_flag(args, "--replace", bool(arguments.get("replace")))
    _add_flag(args, "--cleanup", bool(arguments.get("cleanup")))
    if "playCheck" in arguments:
        _add_toggle(args, "--play-check", "--no-play-check", bool(arguments.get("playCheck")))
    else:
        args.append("--no-play-check")
    _add_option(args, "--capture", arguments.get("capture", "none"))
    _add_option(args, "--capture-width", arguments.get("captureWidth"))
    _add_option(args, "--capture-height", arguments.get("captureHeight"))
    _add_flag(args, "--save-if-dirty-start", bool(arguments.get("saveIfDirtyStart")))
    _add_option(args, "--timeout", arguments.get("timeout"))
    _add_option(args, "--interval", arguments.get("interval"))
    _add_option(args, "--port", arguments.get("port"))
    return args


def _build_build_fps_sample_args(arguments: dict[str, Any]) -> list[str]:
    args = ["workflow", "build-fps-sample"]
    _add_option(args, "--name", arguments.get("name"))
    _add_option(args, "--scene-path", arguments.get("scenePath"))
    _add_option(args, "--folder", arguments.get("folder"))
    _add_flag(args, "--replace", bool(arguments.get("replace")))
    _add_option(args, "--verify-level", arguments.get("verifyLevel", "quick"))
    _add_toggle(args, "--play-check", "--no-play-check", arguments.get("playCheck"))
    _add_option(args, "--capture", arguments.get("capture"))
    _add_option(args, "--capture-width", arguments.get("captureWidth"))
    _add_option(args, "--capture-height", arguments.get("captureHeight"))
    _add_flag(args, "--save-if-dirty-start", bool(arguments.get("saveIfDirtyStart")))
    _add_option(args, "--timeout", arguments.get("timeout"))
    _add_option(args, "--interval", arguments.get("interval"))
    _add_option(args, "--port", arguments.get("port"))
    return args


def _build_audit_advanced_args(arguments: dict[str, Any]) -> list[str]:
    args = ["workflow", "audit-advanced"]
    for category in _ensure_list(arguments, "categories"):
        args.extend(["--category", category])
    if "sampleBacked" in arguments and not bool(arguments.get("sampleBacked")):
        args.append("--no-sample-backed")
    _add_option(args, "--prefix", arguments.get("prefix"))
    _add_flag(args, "--save-if-dirty-start", bool(arguments.get("saveIfDirtyStart")))
    _add_option(args, "--timeout", arguments.get("timeout"))
    _add_option(args, "--interval", arguments.get("interval"))
    _add_option(args, "--port", arguments.get("port"))
    return args


def _build_advanced_tools_args(arguments: dict[str, Any]) -> list[str]:
    args = ["advanced-tools"]
    _add_option(args, "--category", arguments.get("category"))
    _add_option(args, "--search", arguments.get("search"))
    _add_option(args, "--port", arguments.get("port"))
    return args


def _build_tool_info_args(arguments: dict[str, Any]) -> list[str]:
    args = ["tool-info", str(_require(arguments, "toolName"))]
    _add_option(args, "--port", arguments.get("port"))
    return args


def _build_tool_call_args(arguments: dict[str, Any]) -> list[str]:
    args = ["tool", str(_require(arguments, "toolName"))]
    params = arguments.get("params")
    if params is not None:
        if not isinstance(params, dict):
            raise ValueError("`params` must be a JSON object.")
        args.extend(["--params", _json_text(params)])
    _add_option(args, "--port", arguments.get("port"))
    return args


_MCP_TOOLS: tuple[MCPToolSpec, ...] = (
    MCPToolSpec(
        name="unity_instances",
        description="Discover running Unity editors and show the currently selected target.",
        input_schema={"type": "object", "properties": {}},
        build_args=_build_instances_args,
    ),
    MCPToolSpec(
        name="unity_select_instance",
        description="Select the active Unity editor instance by port for later calls.",
        input_schema={"type": "object", "properties": {"port": {"type": "integer"}}, "required": ["port"]},
        build_args=_build_select_instance_args,
    ),
    MCPToolSpec(
        name="unity_inspect",
        description="Collect a compact project, scene, hierarchy, and asset snapshot for the active Unity editor.",
        input_schema={
            "type": "object",
            "properties": {
                "hierarchyDepth": {"type": "integer", "default": 2},
                "hierarchyNodes": {"type": "integer", "default": 40},
                "assetFolder": {"type": "string", "default": "Assets"},
                "assetLimit": {"type": "integer", "default": 20},
                "assetSearch": {"type": "string"},
                "port": {"type": "integer"},
            },
        },
        build_args=_build_inspect_args,
    ),
    MCPToolSpec(
        name="unity_console",
        description="Read recent Unity console messages for debugging generated content and workflow failures.",
        input_schema={
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "type": {"type": "string", "enum": ["all", "info", "warning", "error"]},
                "port": {"type": "integer"},
            },
        },
        build_args=_build_console_args,
    ),
    MCPToolSpec(
        name="unity_play",
        description="Enter, pause, or stop play mode using the CLI's recovery-aware play wrapper.",
        input_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["play", "pause", "stop"]},
                "wait": {"type": "boolean", "default": True},
                "timeout": {"type": "number", "default": 20.0},
                "interval": {"type": "number", "default": 0.25},
                "port": {"type": "integer"},
            },
            "required": ["action"],
        },
        build_args=_build_play_args,
    ),
    MCPToolSpec(
        name="unity_validate_scene",
        description="Run the high-signal scene validation pass for missing references, compile issues, and hierarchy health.",
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50},
                "includeHierarchy": {"type": "boolean", "default": False},
                "port": {"type": "integer"},
            },
        },
        build_args=_build_validate_scene_args,
    ),
    MCPToolSpec(
        name="unity_reset_scene",
        description="Reload the active scene with explicit dirty-scene behavior to avoid Unity save prompts.",
        input_schema={
            "type": "object",
            "properties": {
                "saveIfDirty": {"type": "boolean", "default": False},
                "discardUnsaved": {"type": "boolean", "default": False},
                "forceReload": {"type": "boolean", "default": False},
                "port": {"type": "integer"},
            },
        },
        build_args=_build_reset_scene_args,
    ),
    MCPToolSpec(
        name="unity_create_behaviour",
        description="Create a MonoBehaviour script and optionally attach it to a new GameObject.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "folder": {"type": "string", "default": "Assets/Scripts/Codex"},
                "namespace": {"type": "string"},
                "objectName": {"type": "string"},
                "attach": {"type": "boolean", "default": True},
                "timeout": {"type": "number", "default": 30.0},
                "interval": {"type": "number", "default": 0.5},
                "port": {"type": "integer"},
            },
            "required": ["name"],
        },
        build_args=_build_create_behaviour_args,
    ),
    MCPToolSpec(
        name="unity_wire_reference",
        description="Assign or clear a serialized object reference without hand-writing route payloads.",
        input_schema={
            "type": "object",
            "properties": {
                "targetObject": {"type": "string"},
                "componentType": {"type": "string"},
                "propertyName": {"type": "string"},
                "referenceObject": {"type": "string"},
                "referenceComponent": {"type": "string"},
                "assetPath": {"type": "string"},
                "referenceInstanceId": {"type": "integer"},
                "clear": {"type": "boolean", "default": False},
                "port": {"type": "integer"},
            },
            "required": ["targetObject", "componentType", "propertyName"],
        },
        build_args=_build_wire_reference_args,
    ),
    MCPToolSpec(
        name="unity_create_prefab",
        description="Create a prefab from a scene object and optionally instantiate the saved prefab back into the scene.",
        input_schema={
            "type": "object",
            "properties": {
                "gameObject": {"type": "string"},
                "folder": {"type": "string", "default": "Assets/Prefabs"},
                "name": {"type": "string"},
                "instantiate": {"type": "boolean", "default": False},
                "instanceName": {"type": "string"},
                "parent": {"type": "string"},
                "port": {"type": "integer"},
            },
            "required": ["gameObject"],
        },
        build_args=_build_create_prefab_args,
    ),
    MCPToolSpec(
        name="unity_build_sample",
        description="Build a compact gameplay slice with efficient defaults: no captures and no play-mode validation unless requested.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "default": "CodexSampleArena"},
                "folder": {"type": "string", "default": "Assets/CodexSamples"},
                "prefabFolder": {"type": "string"},
                "visualMode": {"type": "string", "enum": ["auto", "2d", "3d"], "default": "auto"},
                "replace": {"type": "boolean", "default": False},
                "cleanup": {"type": "boolean", "default": False},
                "playCheck": {"type": "boolean", "default": False},
                "capture": {"type": "string", "enum": ["none", "game", "scene", "both"], "default": "none"},
                "captureWidth": {"type": "integer", "default": 640},
                "captureHeight": {"type": "integer", "default": 360},
                "saveIfDirtyStart": {"type": "boolean", "default": False},
                "timeout": {"type": "number", "default": 30.0},
                "interval": {"type": "number", "default": 0.5},
                "port": {"type": "integer"},
            },
        },
        build_args=_build_build_sample_args,
    ),
    MCPToolSpec(
        name="unity_build_fps_sample",
        description="Build the 3D FPS starter scene. Defaults to quick verification for faster agent loops unless you request a deeper pass.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "default": "CodexFpsShowcase"},
                "scenePath": {"type": "string", "default": "Assets/Scenes/CodexFpsShowcase.unity"},
                "folder": {"type": "string", "default": "Assets/CodexSamples/FPS"},
                "replace": {"type": "boolean", "default": False},
                "verifyLevel": {"type": "string", "enum": ["quick", "standard", "deep"], "default": "quick"},
                "playCheck": {"type": "boolean"},
                "capture": {"type": "string", "enum": ["none", "game", "scene", "both"]},
                "captureWidth": {"type": "integer", "default": 960},
                "captureHeight": {"type": "integer", "default": 540},
                "saveIfDirtyStart": {"type": "boolean", "default": False},
                "timeout": {"type": "number", "default": 30.0},
                "interval": {"type": "number", "default": 0.5},
                "port": {"type": "integer"},
            },
        },
        build_args=_build_build_fps_sample_args,
    ),
    MCPToolSpec(
        name="unity_audit_advanced",
        description="Run the curated advanced-tool audit to measure live compatibility against the current Unity project.",
        input_schema={
            "type": "object",
            "properties": {
                "categories": {"type": "array", "items": {"type": "string"}},
                "sampleBacked": {"type": "boolean", "default": True},
                "prefix": {"type": "string", "default": "CodexAdvancedAudit"},
                "saveIfDirtyStart": {"type": "boolean", "default": False},
                "timeout": {"type": "number", "default": 20.0},
                "interval": {"type": "number", "default": 0.25},
                "port": {"type": "integer"},
            },
        },
        build_args=_build_audit_advanced_args,
    ),
    MCPToolSpec(
        name="unity_advanced_tools",
        description="Browse the advanced-tool compatibility catalog without exposing hundreds of MCP tools individually.",
        input_schema={"type": "object", "properties": {"category": {"type": "string"}, "search": {"type": "string"}, "port": {"type": "integer"}}},
        build_args=_build_advanced_tools_args,
    ),
    MCPToolSpec(
        name="unity_tool_info",
        description="Describe an upstream Unity tool name, including route mapping and compact input-schema hints.",
        input_schema={"type": "object", "properties": {"toolName": {"type": "string"}, "port": {"type": "integer"}}, "required": ["toolName"]},
        build_args=_build_tool_info_args,
    ),
    MCPToolSpec(
        name="unity_tool_call",
        description="Escape hatch for any upstream Unity tool name while keeping the MCP surface area small.",
        input_schema={
            "type": "object",
            "properties": {
                "toolName": {"type": "string"},
                "params": {"type": "object", "additionalProperties": True, "default": {}},
                "port": {"type": "integer"},
            },
            "required": ["toolName"],
        },
        build_args=_build_tool_call_args,
    ),
)


def iter_mcp_tools() -> list[dict[str, Any]]:
    return [{"name": tool.name, "description": tool.description, "inputSchema": tool.input_schema} for tool in _MCP_TOOLS]


def get_mcp_tool(tool_name: str) -> MCPToolSpec | None:
    for tool in _MCP_TOOLS:
        if tool.name == tool_name:
            return tool
    return None


def execute_mcp_tool(tool_name: str, arguments: dict[str, Any] | None, options: EmbeddedCLIOptions) -> Any:
    tool = get_mcp_tool(tool_name)
    if tool is None:
        raise ValueError(f"Unknown MCP tool `{tool_name}`.")
    payload = dict(arguments or {})
    argv = tool.build_args(payload)
    return run_cli_json(argv, options)
