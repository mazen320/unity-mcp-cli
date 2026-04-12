from __future__ import annotations

from pathlib import Path
from typing import Any

from .project_insights import build_asset_audit_report


def _relativize(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _bullet_list(items: list[str], *, fallback: str) -> str:
    clean = [item.strip() for item in items if item and item.strip()]
    if not clean:
        clean = [fallback]
    return "\n".join(f"- {item}" for item in clean)


def _build_agents_md(
    *,
    project_name: str,
    render_pipeline: str | None,
    active_scene: str | None,
    summary: dict[str, Any],
    focus_areas: list[dict[str, Any]],
    top_recommendations: list[dict[str, Any]],
) -> str:
    focus_lines = [
        f"{item.get('category')} ({item.get('count')})"
        for item in focus_areas
        if item.get("category")
    ]
    recommendation_lines = [
        f"{item.get('title')}: {item.get('detail')}"
        for item in top_recommendations
        if item.get("title") and item.get("detail")
    ]

    return "\n".join(
        [
            "# AGENTS",
            "",
            f"This repository is the Unity project `{project_name}`.",
            "",
            "## Project Snapshot",
            "",
            f"- Render pipeline: {render_pipeline or 'Unknown'}",
            f"- Active scene during last audit: {active_scene or 'Unknown'}",
            f"- Scenes: {summary.get('sceneCount', 0)}",
            f"- Scripts: {summary.get('scriptCount', 0)}",
            f"- Tests: {summary.get('testScriptCount', 0)}",
            f"- Prefabs: {summary.get('prefabCount', 0)}",
            f"- Materials: {summary.get('materialCount', 0)}",
            f"- Models: {summary.get('modelCount', 0)}",
            f"- Animations: {summary.get('animationCount', 0)}",
            "",
            "## Agent Workflow",
            "",
            "- Start with `cli-anything-unity-mcp --json workflow inspect` or `workflow asset-audit` before large edits.",
            "- Prefer small, reversible changes and save the active scene before risky passes.",
            "- Use disposable sandbox scenes or temporary probes instead of mutating production scenes first.",
            "- Keep generated validation content temporary and remove it when the task is complete.",
            "",
            "## Current Focus Areas",
            "",
            _bullet_list(focus_lines, fallback="No major focus areas were detected in the last audit."),
            "",
            "## Current Recommendations",
            "",
            _bullet_list(
                recommendation_lines,
                fallback="No major audit recommendations were generated in the last scan.",
            ),
            "",
        ]
    )


def _build_project_context_md(
    *,
    project_name: str,
    project_root: Path,
    report: dict[str, Any],
) -> str:
    summary = dict(report.get("summary") or {})
    asset_scan = dict(report.get("assetScan") or {})
    importer_audit = dict(asset_scan.get("importerAudit") or {})
    guidance = dict(report.get("guidance") or {})
    top_level_folders = list(asset_scan.get("topLevelFolders") or [])
    packages = list(asset_scan.get("packages") or [])
    recommendations = list(report.get("topRecommendations") or [])

    folder_lines = top_level_folders[:8]
    package_lines = packages[:8]
    recommendation_lines = [
        f"{item.get('priority', 'unknown')}: {item.get('title')}"
        for item in recommendations
        if item.get("title")
    ]

    return "\n".join(
        [
            f"# {project_name} Project Context",
            "",
            f"- Project root: {project_root.as_posix()}",
            f"- Render pipeline: {summary.get('renderPipeline') or 'Unknown'}",
            f"- Active scene: {summary.get('activeScene') or 'Unknown'}",
            f"- Scene dirty during last audit: {'yes' if summary.get('sceneDirty') else 'no'}",
            "",
            "## Asset Overview",
            "",
            f"- Scenes: {summary.get('sceneCount', 0)}",
            f"- Scripts: {summary.get('scriptCount', 0)}",
            f"- Tests: {summary.get('testScriptCount', 0)}",
            f"- Materials: {summary.get('materialCount', 0)}",
            f"- Models: {summary.get('modelCount', 0)}",
            f"- Textures: {summary.get('textureCount', 0)}",
            f"- Audio: {summary.get('audioCount', 0)}",
            f"- Packages: {summary.get('packageCount', 0)}",
            "",
            "## Top-Level Folders",
            "",
            _bullet_list(folder_lines, fallback="No top-level Asset folders were detected."),
            "",
            "## Installed Package Highlights",
            "",
            _bullet_list(package_lines, fallback="No package manifest data was available."),
            "",
            "## Importer Notes",
            "",
            f"- Model importers scanned: {importer_audit.get('modelImporterCount', 0)}",
            f"- Texture importers scanned: {importer_audit.get('textureImporterCount', 0)}",
            f"- Likely normal-map mismatches: {importer_audit.get('potentialNormalMapMisconfiguredCount', 0)}",
            f"- Likely sprite mismatches: {importer_audit.get('potentialSpriteMisconfiguredCount', 0)}",
            "",
            "## Existing Guidance",
            "",
            f"- Root guidance files found: {guidance.get('fileCount', 0)}",
            f"- Has AGENTS.md: {'yes' if guidance.get('hasAgentsMd') else 'no'}",
            f"- Has README.md: {'yes' if guidance.get('hasReadme') else 'no'}",
            f"- Has Assets/MCP/Context: {'yes' if guidance.get('hasContextFolder') else 'no'}",
            "",
            "## Top Recommendations",
            "",
            _bullet_list(
                recommendation_lines,
                fallback="No major recommendations were generated in the last audit.",
            ),
            "",
        ]
    )


def build_guidance_bundle(
    project_root: str | Path | None,
    *,
    inspect_payload: dict[str, Any] | None = None,
    include_context: bool = True,
    recommendation_limit: int = 5,
) -> dict[str, Any]:
    report = build_asset_audit_report(
        project_root,
        inspect_payload=inspect_payload,
        recommendation_limit=recommendation_limit,
    )
    if not report.get("available"):
        return report

    root = Path(str(report.get("projectRoot") or project_root))
    summary = dict(report.get("summary") or {})
    project_name = summary.get("projectName") or root.name
    render_pipeline = summary.get("renderPipeline")
    active_scene = summary.get("activeScene")
    focus_areas = list(report.get("focusAreas") or [])
    top_recommendations = list(report.get("topRecommendations") or [])

    files: list[dict[str, Any]] = []

    agents_path = root / "AGENTS.md"
    agents_content = _build_agents_md(
        project_name=project_name,
        render_pipeline=render_pipeline,
        active_scene=active_scene,
        summary=summary,
        focus_areas=focus_areas,
        top_recommendations=top_recommendations,
    )
    files.append(
        {
            "kind": "agents",
            "path": str(agents_path),
            "relativePath": _relativize(agents_path, root),
            "content": agents_content,
        }
    )

    if include_context:
        context_path = root / "Assets" / "MCP" / "Context" / "ProjectSummary.md"
        context_content = _build_project_context_md(
            project_name=project_name,
            project_root=root,
            report=report,
        )
        files.append(
            {
                "kind": "context",
                "path": str(context_path),
                "relativePath": _relativize(context_path, root),
                "content": context_content,
            }
        )

    return {
        "available": True,
        "projectRoot": str(root),
        "summary": summary,
        "files": files,
        "assetAudit": report,
    }


def write_guidance_bundle(bundle: dict[str, Any], *, overwrite: bool = False) -> dict[str, Any]:
    writes: list[dict[str, Any]] = []
    for file_entry in bundle.get("files") or []:
        path = Path(str(file_entry.get("path") or ""))
        content = str(file_entry.get("content") or "")
        if not path:
            continue

        if path.exists() and not overwrite:
            writes.append(
                {
                    "path": str(path),
                    "relativePath": file_entry.get("relativePath"),
                    "kind": file_entry.get("kind"),
                    "status": "skipped_existing",
                }
            )
            continue

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        writes.append(
            {
                "path": str(path),
                "relativePath": file_entry.get("relativePath"),
                "kind": file_entry.get("kind"),
                "status": "written",
                "chars": len(content),
            }
        )

    return {
        "projectRoot": bundle.get("projectRoot"),
        "writeCount": sum(1 for item in writes if item.get("status") == "written"),
        "skipCount": sum(1 for item in writes if item.get("status") == "skipped_existing"),
        "writes": writes,
    }
