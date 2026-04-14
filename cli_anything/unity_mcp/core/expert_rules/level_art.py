from __future__ import annotations

from ..expert_lenses import grade_score


def audit_level_art_lens(context: dict) -> dict:
    findings: list[dict] = []
    scene_stats = dict(((context.get("raw") or {}).get("inspect") or {}).get("sceneStats") or {})

    if int(scene_stats.get("totalMeshes") or 0) < 5:
        findings.append(
            {
                "severity": "medium",
                "title": "Sparse scene composition",
                "detail": "The active scene has very low mesh density.",
            }
        )

    score = max(45, 91 - (len(findings) * 18))
    return {
        "lens": "level-art",
        "score": score,
        "grade": grade_score(score),
        "confidence": 0.68,
        "findings": findings,
    }
