from __future__ import annotations

from ..expert_lenses import grade_score


def audit_director_lens(context: dict) -> dict:
    findings: list[dict] = []
    guidance = dict(((context.get("raw") or {}).get("audit") or {}).get("guidance") or {})
    assets = dict(context.get("assets") or {})

    if not guidance.get("hasAgentsMd") or not guidance.get("hasContextFolder"):
        findings.append(
            {
                "severity": "high",
                "title": "Missing project guidance",
                "detail": "The project is missing AGENTS.md or Assets/MCP/Context guidance.",
            }
        )
    if int(assets.get("testScriptCount") or 0) == 0:
        findings.append(
            {
                "severity": "medium",
                "title": "No test coverage detected",
                "detail": "The project audit found no test scripts.",
            }
        )

    score = max(35, 92 - (len(findings) * 18))
    return {
        "lens": "director",
        "score": score,
        "grade": grade_score(score),
        "confidence": 0.78,
        "findings": findings,
    }
