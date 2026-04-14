from __future__ import annotations

from typing import Any


_SANDBOX_SCENE_TOKENS: tuple[str, ...] = ("sandbox", "test", "prototype", "playground", "lab")
_DISPOSABLE_OBJECT_TOKENS: tuple[str, ...] = (
    "probe",
    "fixture",
    "temp",
    "debug",
    "standalone",
)
_PLAYER_TOKENS: tuple[str, ...] = ("player", "hero", "avatar", "character", "pawn")


def _extract_hierarchy_nodes(hierarchy_payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_nodes = hierarchy_payload.get("nodes") or hierarchy_payload.get("hierarchy") or []
    if not isinstance(raw_nodes, list):
        return []
    return [node for node in raw_nodes if isinstance(node, dict)]


def _flatten_hierarchy_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    stack = list(reversed(nodes))
    while stack:
        node = stack.pop()
        flattened.append(node)
        children = node.get("children") or []
        if isinstance(children, list):
            for child in reversed(children):
                if isinstance(child, dict):
                    stack.append(child)
    return flattened


def _node_path(node: dict[str, Any]) -> str:
    return str(
        node.get("path")
        or node.get("hierarchyPath")
        or node.get("gameObjectPath")
        or node.get("name")
        or ""
    ).strip()


def _count_matching_components(nodes: list[dict[str, Any]], matcher: Any) -> int:
    count = 0
    for node in nodes:
        for component in node.get("components") or []:
            component_name = str(component or "").strip()
            if component_name and matcher(component_name):
                count += 1
    return count


def _looks_like_sandbox_scene(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lower()
    return any(token in normalized for token in _SANDBOX_SCENE_TOKENS)


def _looks_disposable_object(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lower()
    return any(token in normalized for token in _DISPOSABLE_OBJECT_TOKENS)


def _looks_like_player_candidate(node: dict[str, Any]) -> bool:
    path = _node_path(node).lower()
    if any(token in path for token in _PLAYER_TOKENS):
        return True
    components = {str(component or "").strip() for component in (node.get("components") or [])}
    return "CharacterController" in components


def _build_systems_summary(
    inspect_payload: dict[str, Any],
    audit_report: dict[str, Any],
) -> dict[str, Any]:
    hierarchy = dict(inspect_payload.get("hierarchy") or {})
    nodes = _flatten_hierarchy_nodes(_extract_hierarchy_nodes(hierarchy))
    asset_scan = dict(audit_report.get("assetScan") or {})
    counts = dict(asset_scan.get("counts") or {})
    scene_samples = [str(path) for path in (asset_scan.get("samples") or {}).get("scenes", []) if str(path).strip()]

    disposable_paths = [
        path for path in (_node_path(node) for node in nodes) if path and _looks_disposable_object(path)
    ]
    player_candidates = [
        _node_path(node) for node in nodes if _node_path(node) and _looks_like_player_candidate(node)
    ]

    scene_stats = dict(inspect_payload.get("sceneStats") or {})

    return {
        "contextAvailable": bool(nodes or scene_stats or inspect_payload.get("state") or inspect_payload.get("scene")),
        "hierarchyNodeCount": len(nodes),
        "activeCameraCount": _count_matching_components(nodes, lambda name: name == "Camera"),
        "audioListenerCount": _count_matching_components(nodes, lambda name: name == "AudioListener"),
        "canvasCount": _count_matching_components(nodes, lambda name: name == "Canvas"),
        "eventSystemCount": _count_matching_components(nodes, lambda name: name == "EventSystem"),
        "colliderCount": _count_matching_components(nodes, lambda name: name.endswith("Collider")),
        "rigidbodyCount": _count_matching_components(nodes, lambda name: name in {"Rigidbody", "Rigidbody2D"}),
        "characterControllerCount": _count_matching_components(nodes, lambda name: name == "CharacterController"),
        "animatorCount": _count_matching_components(nodes, lambda name: name == "Animator"),
        "likelyPlayerCount": len(player_candidates),
        "playerCandidates": player_candidates[:8],
        "disposableObjectCount": len(disposable_paths),
        "disposableObjects": disposable_paths[:8],
        "hasSandboxScene": any(_looks_like_sandbox_scene(path) for path in scene_samples),
        "sceneCount": int(counts.get("scenes") or 0),
        "prefabCount": int(counts.get("prefabs") or 0),
        "scriptCount": int(counts.get("scripts") or 0),
        "testScriptCount": int(counts.get("testScripts") or 0),
        "sceneStats": scene_stats,
    }


def build_expert_context(
    *,
    inspect_payload: dict[str, Any] | None,
    audit_report: dict[str, Any] | None,
    lens_name: str,
    capture_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    inspect_payload = dict(inspect_payload or {})
    audit_report = dict(audit_report or {})
    inspect_summary = dict(inspect_payload.get("summary") or {})
    audit_summary = dict(audit_report.get("summary") or {})

    return {
        "lens": {"name": lens_name},
        "project": {
            "name": inspect_summary.get("projectName")
            or audit_summary.get("projectName"),
            "path": inspect_summary.get("projectPath")
            or audit_report.get("projectRoot"),
            "renderPipeline": inspect_summary.get("renderPipeline")
            or audit_summary.get("renderPipeline"),
            "activeScene": inspect_summary.get("activeScene")
            or audit_summary.get("activeScene"),
            "sceneDirty": bool(inspect_summary.get("sceneDirty")),
        },
        "state": dict(inspect_payload.get("state") or {}),
        "scene": dict(inspect_payload.get("scene") or {}),
        "assets": {
            "sceneCount": int(audit_summary.get("sceneCount") or 0),
            "scriptCount": int(audit_summary.get("scriptCount") or 0),
            "testScriptCount": int(audit_summary.get("testScriptCount") or 0),
            "asmdefCount": int(audit_summary.get("asmdefCount") or 0),
            "prefabCount": int(audit_summary.get("prefabCount") or 0),
            "materialCount": int(audit_summary.get("materialCount") or 0),
            "modelCount": int(audit_summary.get("modelCount") or 0),
            "animationCount": int(audit_summary.get("animationCount") or 0),
            "animatorControllerCount": int(audit_summary.get("animatorControllerCount") or 0),
            "textureCount": int(audit_summary.get("textureCount") or 0),
            "audioCount": int(audit_summary.get("audioCount") or 0),
        },
        "systems": _build_systems_summary(inspect_payload, audit_report),
        "focusAreas": list(audit_report.get("focusAreas") or []),
        "recommendations": list(audit_report.get("topRecommendations") or []),
        "captures": dict(capture_summary or {}),
        "raw": {
            "inspect": inspect_payload,
            "audit": audit_report,
        },
    }
