from __future__ import annotations

from ..expert_lenses import grade_score


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


def audit_ui_lens(context: dict) -> dict:
    findings: list[dict] = []
    hierarchy = (((context.get("raw") or {}).get("inspect") or {}).get("hierarchy") or {})
    raw_nodes = hierarchy.get("nodes") or hierarchy.get("hierarchy") or []
    nodes = _flatten_nodes(list(raw_nodes))

    for node in nodes:
        components = set(node.get("components") or [])
        if "Canvas" in components and "CanvasScaler" not in components:
            findings.append(
                {
                    "severity": "high",
                    "title": "Canvas without CanvasScaler",
                    "detail": f"Canvas `{node.get('name')}` has no CanvasScaler.",
                    "path": node.get("path") or node.get("hierarchyPath"),
                }
            )
        if "Canvas" in components and "GraphicRaycaster" not in components:
            findings.append(
                {
                    "severity": "medium",
                    "title": "Canvas without GraphicRaycaster",
                    "detail": f"Canvas `{node.get('name')}` has no GraphicRaycaster.",
                    "path": node.get("path") or node.get("hierarchyPath"),
                }
            )

    score = max(40, 90 - (len(findings) * 20))
    return {
        "lens": "ui",
        "score": score,
        "grade": grade_score(score),
        "confidence": 0.76,
        "findings": findings,
    }
