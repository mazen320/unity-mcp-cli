from __future__ import annotations

from ..expert_lenses import grade_score


def audit_tech_art_lens(context: dict) -> dict:
    findings: list[dict] = []
    importer_audit = dict(
        ((((context.get("raw") or {}).get("audit") or {}).get("assetScan") or {}).get("importerAudit") or {})
    )

    if int(importer_audit.get("potentialNormalMapMisconfiguredCount") or 0) > 0 or int(
        importer_audit.get("potentialSpriteMisconfiguredCount") or 0
    ) > 0:
        findings.append(
            {
                "severity": "medium",
                "title": "Texture importer mismatches detected",
                "detail": "Likely normal-map or sprite-import mismatches were found.",
            }
        )

    score = max(45, 92 - (len(findings) * 16))
    return {
        "lens": "tech-art",
        "score": score,
        "grade": grade_score(score),
        "confidence": 0.82,
        "findings": findings,
    }
