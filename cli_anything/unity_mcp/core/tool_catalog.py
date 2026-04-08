from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any, Dict, List


@lru_cache(maxsize=1)
def _load_catalog() -> Dict[str, Any]:
    data_path = resources.files("cli_anything.unity_mcp").joinpath(
        "data", "upstream_tool_catalog.json"
    )
    with data_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def get_upstream_catalog() -> Dict[str, Any]:
    return _load_catalog()


def get_upstream_tool(tool_name: str) -> Dict[str, Any] | None:
    for tool in _load_catalog().get("tools", []):
        if tool.get("name") == tool_name:
            return dict(tool)
    return None


@lru_cache(maxsize=1)
def get_route_index() -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for tool in _load_catalog().get("tools", []):
        route = tool.get("route")
        if route and route not in index:
            index[route] = dict(tool)
    return index


def iter_upstream_tools(
    category: str | None = None,
    tier: str | None = None,
    search: str | None = None,
    include_unsupported: bool = False,
) -> List[Dict[str, Any]]:
    category_filter = (category or "").strip().lower() or None
    tier_filter = (tier or "").strip().lower() or None
    search_filter = (search or "").strip().lower() or None

    result: List[Dict[str, Any]] = []
    for tool in _load_catalog().get("tools", []):
        if not include_unsupported and tool.get("unsupported"):
            continue
        if category_filter and str(tool.get("category", "")).lower() != category_filter:
            continue
        if tier_filter and str(tool.get("tier", "")).lower() != tier_filter:
            continue
        if search_filter:
            haystacks = [
                str(tool.get("name", "")),
                str(tool.get("description", "")),
                str(tool.get("category", "")),
                str(tool.get("tier", "")),
            ]
            if not any(search_filter in haystack.lower() for haystack in haystacks):
                continue
        result.append(dict(tool))
    return result
