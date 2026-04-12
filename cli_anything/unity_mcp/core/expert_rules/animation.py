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


def audit_animation_lens(context: dict) -> dict:
    findings: list[dict] = []
    assets = dict(context.get("assets") or {})
    animation_count = int(assets.get("animationCount") or 0)
    controller_count = int(assets.get("animatorControllerCount") or 0)
    model_count = int(assets.get("modelCount") or 0)

    if model_count > 0 and animation_count == 0:
        findings.append(
            {
                "severity": "medium",
                "title": "Models found without animation evidence",
                "detail": "Models exist, but the audit did not find clips or controller coverage.",
            }
        )

    if animation_count > 0 and controller_count == 0:
        findings.append(
            {
                "severity": "medium",
                "title": "Animation clips without controller coverage",
                "detail": "Animation clips exist, but no Animator Controllers were detected.",
            }
        )

    hierarchy = (((context.get("raw") or {}).get("inspect") or {}).get("hierarchy") or {})
    raw_nodes = hierarchy.get("nodes") or hierarchy.get("hierarchy") or []
    nodes = _flatten_nodes(list(raw_nodes))
    has_animator = any("Animator" in set(node.get("components") or []) for node in nodes)
    if nodes and animation_count > 0 and not has_animator:
        findings.append(
            {
                "severity": "low",
                "title": "No Animator components found in scene",
                "detail": "Animation assets exist, but the inspected scene hierarchy does not currently include any Animator components.",
            }
        )

    score = max(35, 92 - (len(findings) * 18))
    return {
        "lens": "animation",
        "score": score,
        "grade": grade_score(score),
        "confidence": 0.74,
        "findings": findings,
    }
