from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from .tool_catalog import get_upstream_catalog, iter_upstream_tools


COVERAGE_STATUSES = (
    "live-tested",
    "covered",
    "mock-only",
    "unsupported",
    "deferred",
)


LIVE_TESTED_ROUTE_NOTES: Dict[str, str] = {
    "profiler/memory-status": "Verified against a real Unity editor through the advanced audit workflow.",
    "graphics/lighting-summary": "Verified against a real Unity editor through the advanced audit workflow.",
    "sceneview/info": "Verified against a real Unity editor through the advanced audit workflow.",
    "settings/quality": "Verified against a real Unity editor through the advanced audit workflow.",
    "settings/time": "Verified against a real Unity editor through the advanced audit workflow.",
    "profiler/stats": "Verified against a real Unity editor through the advanced audit workflow.",
    "testing/list-tests": "Verified against a real Unity editor through the advanced audit workflow.",
    "graphics/renderer-info": "Verified against a real Unity editor through the advanced audit workflow.",
    "graphics/mesh-info": "Verified against a real Unity editor through the advanced audit workflow.",
    "graphics/material-info": "Verified against a real Unity editor through the advanced audit workflow.",
    "physics/raycast": "Verified against a real Unity editor through the advanced audit workflow.",
    "ui/create-canvas": "Verified against a real Unity editor through the advanced audit workflow.",
    "ui/info": "Verified against a real Unity editor through the advanced audit workflow.",
    "audio/info": "Verified against a real Unity editor through the advanced audit workflow.",
    "lighting/create": "Verified against a real Unity editor through the advanced audit workflow.",
    "lighting/info": "Verified against a real Unity editor through the advanced audit workflow.",
    "animation/create-controller": "Verified against a real Unity editor through the advanced audit workflow.",
    "animation/create-clip": "Verified against a real Unity editor through the advanced audit workflow.",
    "animation/set-clip-curve": "Verified against a real Unity editor through the advanced audit workflow.",
    "animation/add-layer": "Verified against a real Unity editor through the advanced audit workflow.",
    "animation/add-state": "Verified against a real Unity editor through the advanced audit workflow.",
    "animation/controller-info": "Verified against a real Unity editor through the advanced audit workflow.",
    "input/create": "Verified against a real Unity editor through the advanced audit workflow.",
    "input/info": "Verified against a real Unity editor through the advanced audit workflow.",
    "shadergraph/status": "Verified against a real Unity editor through the advanced audit workflow.",
    "shadergraph/create": "Verified against a real Unity editor through the advanced audit workflow.",
    "shadergraph/list": "Verified against a real Unity editor through the advanced audit workflow.",
    "terrain/create": "Verified against a real Unity editor through the advanced audit workflow.",
    "terrain/info": "Verified against a real Unity editor through the advanced audit workflow.",
    "terrain/get-height": "Verified against a real Unity editor through the advanced audit workflow.",
    "navigation/info": "Verified against a real Unity editor through the advanced audit workflow.",
}


COVERED_ROUTE_NOTES: Dict[str, str] = {
    "scene/info": "Covered by automated tests and higher-level workflows.",
    "project/info": "Covered by automated tests and higher-level workflows.",
    "scene/open": "Covered by automated tests and higher-level workflows.",
    "scene/save": "Covered by automated tests and higher-level workflows.",
    "scene/hierarchy": "Covered by automated tests and higher-level workflows.",
    "search/missing-references": "Covered by automated tests and higher-level workflows.",
    "search/scene-stats": "Covered by automated tests and higher-level workflows.",
    "editor/state": "Covered by automated tests and higher-level workflows.",
    "editor/play-mode": "Covered by automated tests and live-pass workflows.",
    "compilation/errors": "Covered by automated tests and higher-level workflows.",
    "editor/execute-code": "Covered by automated tests and higher-level workflows.",
    "asset/list": "Covered by automated tests and higher-level workflows.",
    "asset/delete": "Covered by automated tests and higher-level workflows.",
    "asset/create-prefab": "Covered by automated tests and higher-level workflows.",
    "asset/instantiate-prefab": "Covered by automated tests and higher-level workflows.",
    "script/create": "Covered by automated tests and higher-level workflows.",
    "script/read": "Covered by automated tests and higher-level workflows.",
    "script/update": "Covered by automated tests and higher-level workflows.",
    "gameobject/create": "Covered by automated tests and higher-level workflows.",
    "gameobject/info": "Covered by automated tests and higher-level workflows.",
    "gameobject/delete": "Covered by automated tests and higher-level workflows.",
    "gameobject/set-transform": "Covered by automated tests and higher-level workflows.",
    "component/add": "Covered by automated tests and higher-level workflows.",
    "component/get-properties": "Covered by automated tests and higher-level workflows.",
    "component/set-property": "Covered by automated tests and higher-level workflows.",
    "component/set-reference": "Covered by automated tests and higher-level workflows.",
    "graphics/game-capture": "Covered by automated tests and higher-level workflows.",
    "graphics/scene-capture": "Covered by automated tests and higher-level workflows.",
    "queue/info": "Covered by automated tests and live MCP pass workflows.",
    "queue/status": "Covered by automated tests and live MCP pass workflows.",
    "undo/perform": "Covered by automated tests and higher-level workflows.",
}


MOCK_ONLY_ROUTE_NOTES: Dict[str, str] = {}

PACKAGE_DEPENDENT_CATEGORIES = {
    "amplify",
    "shadergraph",
    "spriteatlas",
    "uma",
}

STATEFUL_MUTATION_CATEGORIES = {
    "animation",
    "asset",
    "audio",
    "component",
    "constraint",
    "gameobject",
    "graphics",
    "input",
    "lighting",
    "lod",
    "material",
    "navmesh",
    "packages",
    "particle",
    "physics",
    "prefab",
    "renderer",
    "scene",
    "sceneview",
    "scriptableobject",
    "search",
    "selection",
    "settings",
    "terrain",
    "texture",
    "ui",
    "undo",
    "vfx",
}

ENVIRONMENT_DEPENDENT_CATEGORIES = {
    "build",
    "console",
    "debugger",
    "editor",
    "editorprefs",
    "execute",
    "memory",
    "playerprefs",
    "profiler",
    "screenshot",
    "testing",
}

META_SURFACE_CATEGORIES = {
    "agent",
    "agents",
    "context",
    "list",
    "meta",
    "select",
}


def _unsupported_note(tool: Dict[str, Any]) -> tuple[str, str]:
    category = str(tool.get("category") or "").lower()
    if category == "hub":
        return (
            "Requires separate Unity Hub integration. These commands are outside the current editor bridge and need Hub discovery/install automation.",
            "unity-hub-integration",
        )
    return "Marked unsupported in the upstream catalog.", "upstream-unsupported"


def _deferred_note(tool: Dict[str, Any]) -> tuple[str, str]:
    category = str(tool.get("category") or "").lower()
    if category in PACKAGE_DEPENDENT_CATEGORIES:
        return (
            "Known upstream tool, but it depends on optional packages/assets and still needs fixture-based live validation before promotion.",
            "package-dependent-live-audit",
        )
    if category in STATEFUL_MUTATION_CATEGORIES:
        return (
            "Known upstream tool, but it performs stateful editor mutations. We need disposable fixtures and live audit coverage before promoting it.",
            "stateful-live-audit",
        )
    if category in ENVIRONMENT_DEPENDENT_CATEGORIES:
        return (
            "Known upstream tool, but it depends on machine/editor/runtime state that has not been fully wired into the automated coverage pass yet.",
            "environment-sensitive",
        )
    if category in META_SURFACE_CATEGORIES:
        return (
            "Known upstream/meta surface, but the CLI-first equivalent has not been explicitly mapped into the coverage matrix yet.",
            "matrix-mapping-gap",
        )
    return (
        "Known in the upstream catalog, but it has not been wrapped or verified deeply enough yet.",
        "wrapper-gap",
    )


def _coverage_status(tool: Dict[str, Any]) -> tuple[str, str, str]:
    route = str(tool.get("route") or "")
    if tool.get("unsupported"):
        note, blocker = _unsupported_note(tool)
        return "unsupported", note, blocker
    if route in LIVE_TESTED_ROUTE_NOTES:
        return "live-tested", LIVE_TESTED_ROUTE_NOTES[route], "verified-live"
    if route in COVERED_ROUTE_NOTES:
        return "covered", COVERED_ROUTE_NOTES[route], "verified-automated"
    if route in MOCK_ONLY_ROUTE_NOTES:
        return "mock-only", MOCK_ONLY_ROUTE_NOTES[route], "verified-mock"
    note, blocker = _deferred_note(tool)
    return "deferred", note, blocker


def build_tool_coverage_matrix(
    category: str | None = None,
    status: str | None = None,
    search: str | None = None,
    include_unsupported: bool = True,
    summary_only: bool = False,
) -> Dict[str, Any]:
    status_filter = (status or "").strip().lower() or None
    if status_filter and status_filter not in COVERAGE_STATUSES:
        raise ValueError(
            f"Unsupported coverage status `{status}`. Expected one of: {', '.join(COVERAGE_STATUSES)}."
        )

    tools: List[Dict[str, Any]] = []
    for tool in iter_upstream_tools(
        category=category,
        search=search,
        include_unsupported=True,
    ):
        coverage_status, note, blocker = _coverage_status(tool)
        if not include_unsupported and coverage_status == "unsupported":
            continue
        if status_filter and coverage_status != status_filter:
            continue
        item = dict(tool)
        item["coverageStatus"] = coverage_status
        item["coverageNote"] = note
        item["coverageBlocker"] = blocker
        tools.append(item)

    tools.sort(key=lambda item: str(item.get("name", "")))

    counts_by_status = {name: 0 for name in COVERAGE_STATUSES}
    counts_by_category: Dict[str, Dict[str, int]] = {}
    for tool in tools:
        coverage_status = str(tool["coverageStatus"])
        counts_by_status[coverage_status] = counts_by_status.get(coverage_status, 0) + 1
        category_name = str(tool.get("category") or "uncategorized")
        category_counts = counts_by_category.setdefault(
            category_name,
            {"total": 0, **{name: 0 for name in COVERAGE_STATUSES}},
        )
        category_counts["total"] += 1
        category_counts[coverage_status] = category_counts.get(coverage_status, 0) + 1

    summary = {
        "catalogVersion": str(get_upstream_catalog().get("version") or "unknown"),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totalTools": len(tools),
        "countsByStatus": counts_by_status,
        "countsByCategory": counts_by_category,
        "filters": {
            "category": category,
            "status": status_filter,
            "search": search,
            "includeUnsupported": include_unsupported,
            "summaryOnly": summary_only,
        },
    }

    payload: Dict[str, Any] = {"summary": summary}
    if not summary_only:
        payload["tools"] = tools
    return payload
