from __future__ import annotations

from ..expert_lenses import grade_score

_PLAYER_TOKENS: tuple[str, ...] = ("player", "hero", "avatar", "character", "pawn")


def _flatten_nodes(nodes: list[dict]) -> list[dict]:
    flattened: list[dict] = []
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


def _node_components(node: dict) -> set[str]:
    return {str(component or "").strip() for component in (node.get("components") or [])}


def _node_label(node: dict) -> str:
    return str(node.get("path") or node.get("hierarchyPath") or node.get("name") or "Unnamed")


def _has_any_collider(components: set[str]) -> bool:
    return any(component.endswith("Collider") for component in components)


def _looks_like_player(node: dict, components: set[str]) -> bool:
    label = _node_label(node).lower()
    return any(token in label for token in _PLAYER_TOKENS) or "CharacterController" in components


def _severity_penalty(severity: str) -> int:
    normalized = str(severity or "").strip().lower()
    if normalized == "high":
        return 18
    if normalized == "medium":
        return 10
    if normalized == "low":
        return 5
    return 0


def audit_physics_lens(context: dict) -> dict:
    findings: list[dict] = []
    systems = dict(context.get("systems") or {})
    hierarchy = (((context.get("raw") or {}).get("inspect") or {}).get("hierarchy") or {})
    raw_nodes = hierarchy.get("nodes") or hierarchy.get("hierarchy") or []
    nodes = _flatten_nodes(list(raw_nodes))

    if not systems.get("contextAvailable"):
        findings.append(
            {
                "severity": "low",
                "title": "Live scene context unavailable",
                "detail": "Physics auditing needs a live hierarchy snapshot to reason about colliders, rigidbodies, and controller setup.",
            }
        )
        score = 74
        return {
            "lens": "physics",
            "score": score,
            "grade": grade_score(score),
            "confidence": 0.64,
            "findings": findings,
            "summary": {"contextAvailable": False},
        }

    rigidbody_without_collider: list[str] = []
    likely_player_without_body: list[str] = []

    for node in nodes:
        components = _node_components(node)
        label = _node_label(node)
        has_rigidbody = bool(components & {"Rigidbody", "Rigidbody2D"})
        has_controller = "CharacterController" in components
        has_collider = _has_any_collider(components) or has_controller
        if has_rigidbody and not has_collider:
            rigidbody_without_collider.append(label)
        if _looks_like_player(node, components) and not has_rigidbody and not has_controller:
            likely_player_without_body.append(label)

    if rigidbody_without_collider:
        sampled = ", ".join(rigidbody_without_collider[:3])
        findings.append(
            {
                "severity": "high",
                "title": "Rigidbody objects without collider coverage",
                "detail": f"These objects have Rigidbody components but no collider on the same object: {sampled}. Physics responses and grounding will be unreliable.",
            }
        )

    active_camera_count = int(systems.get("activeCameraCount") or 0)
    collider_count = int(systems.get("colliderCount") or 0)
    character_controller_count = int(systems.get("characterControllerCount") or 0)
    hierarchy_node_count = int(systems.get("hierarchyNodeCount") or 0)

    if active_camera_count > 0 and hierarchy_node_count >= 4 and collider_count == 0 and character_controller_count == 0:
        findings.append(
            {
                "severity": "high",
                "title": "Playable scene has no collision foundation",
                "detail": "A live Camera exists and the hierarchy looks substantive, but no Collider or CharacterController components were found. Traversal, hits, and blocking volumes are currently undefined.",
            }
        )

    if likely_player_without_body:
        sampled = ", ".join(likely_player_without_body[:3])
        findings.append(
            {
                "severity": "medium",
                "title": "Likely player objects lack a movement body",
                "detail": f"These likely player objects do not have a Rigidbody or CharacterController: {sampled}. Movement, grounding, and collision ownership may be ambiguous.",
            }
        )

    score = max(40, 92 - sum(_severity_penalty(item.get("severity")) for item in findings))
    return {
        "lens": "physics",
        "score": score,
        "grade": grade_score(score),
        "confidence": 0.79,
        "findings": findings,
        "summary": {"contextAvailable": True},
    }
