from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT_GUIDANCE_FILES: tuple[tuple[str, str], ...] = (
    ("agents", "AGENTS.md"),
    ("readme", "README.md"),
    ("design", "DESIGN.md"),
)

ASSET_CATEGORY_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "scenes": (".unity",),
    "scripts": (".cs",),
    "asmdefs": (".asmdef",),
    "prefabs": (".prefab",),
    "materials": (".mat",),
    "textures": (".png", ".jpg", ".jpeg", ".tga", ".psd", ".tif", ".tiff", ".exr", ".bmp", ".gif"),
    "models": (".fbx", ".obj", ".blend", ".glb", ".gltf", ".dae"),
    "animations": (".anim",),
    "animatorControllers": (".controller", ".overridecontroller"),
    "audio": (".wav", ".mp3", ".ogg", ".aiff", ".aif", ".flac"),
    "mixers": (".mixer",),
    "shaders": (".shader",),
    "shaderGraphs": (".shadergraph", ".shadersubgraph"),
}

RECOMMENDATION_PRIORITY_ORDER: dict[str, int] = {
    "high": 0,
    "medium": 1,
    "low": 2,
}

IMPORTER_AUDIT_SAMPLE_KEYS: tuple[str, ...] = (
    "modelMaterialImportDisabled",
    "modelAnimationImportDisabled",
    "modelRigConfigured",
    "potentialNormalMapMisconfigured",
    "potentialSpriteMisconfigured",
)


def _new_importer_audit() -> dict[str, Any]:
    return {
        "available": False,
        "modelImporterCount": 0,
        "modelImportMaterialDisabledCount": 0,
        "modelImportAnimationDisabledCount": 0,
        "modelRigConfiguredCount": 0,
        "textureImporterCount": 0,
        "potentialNormalMapCount": 0,
        "potentialNormalMapMisconfiguredCount": 0,
        "potentialSpriteCount": 0,
        "potentialSpriteMisconfiguredCount": 0,
        "samples": {name: [] for name in IMPORTER_AUDIT_SAMPLE_KEYS},
    }


def _priority_rank(priority: str | None) -> int:
    return RECOMMENDATION_PRIORITY_ORDER.get(str(priority or "").lower(), 99)


def _sort_recommendations(recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for _, item in sorted(
            enumerate(recommendations),
            key=lambda pair: (_priority_rank(pair[1].get("priority")), pair[0]),
        )
    ]


def _build_priority_breakdown(recommendations: list[dict[str, Any]]) -> dict[str, int]:
    breakdown = {"high": 0, "medium": 0, "low": 0}
    for item in recommendations:
        priority = str(item.get("priority") or "").lower()
        if priority in breakdown:
            breakdown[priority] += 1
    return breakdown


def _build_focus_areas(
    recommendations: list[dict[str, Any]],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    category_counts: dict[str, int] = {}
    for item in recommendations:
        category = str(item.get("category") or "").strip().lower()
        if not category:
            continue
        category_counts[category] = category_counts.get(category, 0) + 1

    ranked = sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        {
            "category": category,
            "count": count,
        }
        for category, count in ranked[:limit]
    ]


def _read_preview(path: Path, preview_chars: int) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    preview = " ".join(text.strip().split())
    if len(preview) > preview_chars:
        preview = preview[: preview_chars - 3].rstrip() + "..."
    return {
        "path": path.as_posix(),
        "chars": len(text),
        "preview": preview,
    }


def _append_sample(samples: list[str], path: str, sample_limit: int) -> None:
    if len(samples) < sample_limit:
        samples.append(path)


def _read_asset_meta(asset_path: Path) -> str | None:
    meta_path = Path(f"{asset_path}.meta")
    if not meta_path.is_file():
        return None
    return meta_path.read_text(encoding="utf-8", errors="replace")


def _extract_meta_scalar(meta_text: str | None, key: str) -> str | None:
    if not meta_text:
        return None
    prefix = f"{key}:"
    for raw_line in meta_text.splitlines():
        line = raw_line.strip()
        if not line.startswith(prefix):
            continue
        return line[len(prefix) :].split("#", 1)[0].strip()
    return None


def _looks_like_normal_map(file_name: str, normalized_path: str) -> bool:
    return (
        "/normal" in normalized_path
        or "/normals/" in normalized_path
        or "_n." in file_name
        or "_normal." in file_name
        or file_name.endswith("normal.png")
        or file_name.endswith("normal.tga")
    )


def _looks_like_sprite(file_name: str, normalized_path: str) -> bool:
    return (
        "/sprites/" in normalized_path
        or "/ui/" in normalized_path
        or "sprite" in file_name
        or "icon" in file_name
    )


def _is_normal_map_import(meta_text: str | None) -> bool:
    texture_type = (_extract_meta_scalar(meta_text, "textureType") or "").lower()
    convert_to_normal_map = _extract_meta_scalar(meta_text, "convertToNormalMap")
    return texture_type in {"1", "normalmap"} or convert_to_normal_map == "1"


def _is_sprite_import(meta_text: str | None) -> bool:
    texture_type = (_extract_meta_scalar(meta_text, "textureType") or "").lower()
    sprite_mode = _extract_meta_scalar(meta_text, "spriteMode")
    return texture_type in {"8", "sprite"} or (
        sprite_mode is not None and sprite_mode not in {"0", ""}
    )


def _audit_model_importer(
    file_path: Path,
    *,
    relative_path: str,
    importer_audit: dict[str, Any],
    sample_limit: int,
) -> None:
    importer_audit["available"] = True
    importer_audit["modelImporterCount"] += 1

    meta_text = _read_asset_meta(file_path)
    material_import_mode = _extract_meta_scalar(meta_text, "materialImportMode")
    import_materials = _extract_meta_scalar(meta_text, "importMaterials")
    if material_import_mode == "0" or import_materials == "0":
        importer_audit["modelImportMaterialDisabledCount"] += 1
        _append_sample(
            importer_audit["samples"]["modelMaterialImportDisabled"],
            relative_path,
            sample_limit,
        )

    if _extract_meta_scalar(meta_text, "importAnimation") == "0":
        importer_audit["modelImportAnimationDisabledCount"] += 1
        _append_sample(
            importer_audit["samples"]["modelAnimationImportDisabled"],
            relative_path,
            sample_limit,
        )

    animation_type = (_extract_meta_scalar(meta_text, "animationType") or "").lower()
    if animation_type in {"2", "3", "generic", "human", "humanoid"}:
        importer_audit["modelRigConfiguredCount"] += 1
        _append_sample(
            importer_audit["samples"]["modelRigConfigured"],
            relative_path,
            sample_limit,
        )


def _audit_texture_importer(
    file_path: Path,
    *,
    relative_path: str,
    importer_audit: dict[str, Any],
    sample_limit: int,
) -> None:
    importer_audit["available"] = True
    importer_audit["textureImporterCount"] += 1

    normalized_path = relative_path.lower()
    file_name = file_path.name.lower()
    meta_text = _read_asset_meta(file_path)

    if _looks_like_normal_map(file_name, normalized_path):
        importer_audit["potentialNormalMapCount"] += 1
        if meta_text and not _is_normal_map_import(meta_text):
            importer_audit["potentialNormalMapMisconfiguredCount"] += 1
            _append_sample(
                importer_audit["samples"]["potentialNormalMapMisconfigured"],
                relative_path,
                sample_limit,
            )

    if _looks_like_sprite(file_name, normalized_path):
        importer_audit["potentialSpriteCount"] += 1
        if meta_text and not _is_sprite_import(meta_text):
            importer_audit["potentialSpriteMisconfiguredCount"] += 1
            _append_sample(
                importer_audit["samples"]["potentialSpriteMisconfigured"],
                relative_path,
                sample_limit,
            )


def collect_project_guidance(
    project_root: Path,
    *,
    preview_chars: int = 280,
    max_context_files: int = 8,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    has_agents = False
    has_readme = False
    has_design = False

    for kind, relative_name in ROOT_GUIDANCE_FILES:
        path = project_root / relative_name
        if not path.is_file():
            continue
        entry = _read_preview(path, preview_chars)
        entry["kind"] = kind
        entry["relativePath"] = relative_name.replace("\\", "/")
        files.append(entry)
        has_agents = has_agents or kind == "agents"
        has_readme = has_readme or kind == "readme"
        has_design = has_design or kind == "design"

    context_root = project_root / "Assets" / "MCP" / "Context"
    context_files: list[dict[str, Any]] = []
    if context_root.is_dir():
        for file_path in sorted(
            (
                path
                for path in context_root.rglob("*")
                if path.is_file() and path.suffix.lower() != ".meta"
            ),
            key=lambda item: item.as_posix().lower(),
        )[:max_context_files]:
            entry = _read_preview(file_path, preview_chars)
            entry["kind"] = "context"
            entry["relativePath"] = file_path.relative_to(project_root).as_posix()
            entry["category"] = file_path.stem
            context_files.append(entry)
    files.extend(context_files)

    return {
        "found": bool(files),
        "hasAgentsMd": has_agents,
        "hasReadme": has_readme,
        "hasDesignMd": has_design,
        "hasContextFolder": context_root.is_dir(),
        "fileCount": len(files),
        "files": files,
    }


def scan_project_assets(
    project_root: Path,
    *,
    sample_limit_per_category: int = 5,
) -> dict[str, Any]:
    assets_root = project_root / "Assets"
    counts = {name: 0 for name in ASSET_CATEGORY_EXTENSIONS}
    counts["testScripts"] = 0
    samples: dict[str, list[str]] = {name: [] for name in ASSET_CATEGORY_EXTENSIONS}
    top_level_folders: list[str] = []
    importer_audit = _new_importer_audit()

    if not assets_root.is_dir():
        return {
            "exists": False,
            "assetsRoot": "Assets",
            "counts": counts,
            "samples": samples,
            "importerAudit": importer_audit,
            "topLevelFolders": top_level_folders,
            "packageCount": 0,
            "packages": [],
        }

    top_level_folders = sorted(
        child.name for child in assets_root.iterdir() if child.is_dir()
    )

    for file_path in assets_root.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() == ".meta":
            continue

        relative_path = file_path.relative_to(project_root).as_posix()
        suffix = file_path.suffix.lower()
        normalized_name = file_path.name.lower()

        for category, extensions in ASSET_CATEGORY_EXTENSIONS.items():
            if suffix in extensions or normalized_name.endswith(extensions):
                counts[category] += 1
                if len(samples[category]) < sample_limit_per_category:
                    samples[category].append(relative_path)

        if suffix == ".cs" and ("/Tests/" in relative_path or normalized_name.endswith("tests.cs")):
            counts["testScripts"] += 1

        if suffix in ASSET_CATEGORY_EXTENSIONS["models"]:
            _audit_model_importer(
                file_path,
                relative_path=relative_path,
                importer_audit=importer_audit,
                sample_limit=sample_limit_per_category,
            )

        if suffix in ASSET_CATEGORY_EXTENSIONS["textures"]:
            _audit_texture_importer(
                file_path,
                relative_path=relative_path,
                importer_audit=importer_audit,
                sample_limit=sample_limit_per_category,
            )

    manifest_path = project_root / "Packages" / "manifest.json"
    packages: list[str] = []
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
            dependencies = manifest.get("dependencies") or {}
            if isinstance(dependencies, dict):
                packages = sorted(str(name) for name in dependencies.keys())
        except json.JSONDecodeError:
            packages = []

    return {
        "exists": True,
        "assetsRoot": "Assets",
        "counts": counts,
        "samples": samples,
        "importerAudit": importer_audit,
        "topLevelFolders": top_level_folders,
        "packageCount": len(packages),
        "packages": packages[:25],
    }


def build_project_recommendations(
    *,
    guidance: dict[str, Any],
    asset_scan: dict[str, Any],
    inspect_payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    counts = dict(asset_scan.get("counts") or {})
    importer_audit = dict(asset_scan.get("importerAudit") or {})
    recommendations: list[dict[str, Any]] = []

    def add(priority: str, category: str, title: str, detail: str) -> None:
        recommendations.append(
            {
                "priority": priority,
                "category": category,
                "title": title,
                "detail": detail,
            }
        )

    if not guidance.get("hasAgentsMd") and not guidance.get("hasContextFolder"):
        add(
            "high",
            "documentation",
            "Add Agent Guidance",
            "This project has no AGENTS.md or Assets/MCP/Context guidance. Add project instructions so the CLI and agents understand architecture, conventions, and asset workflow expectations before editing.",
        )

    if counts.get("scripts", 0) >= 40 and counts.get("asmdefs", 0) == 0:
        add(
            "medium",
            "codebase",
            "Add Assembly Definitions",
            "The project has a larger script surface but no .asmdef files were detected. Splitting assemblies usually improves compile times and makes dependencies clearer.",
        )

    if counts.get("textures", 0) >= 10 and counts.get("materials", 0) == 0:
        add(
            "medium",
            "assets",
            "Build A Material Library",
            "Textures are present but no .mat files were found. Add reusable materials or import presets so model and environment work does not stay in default white or raw texture state.",
        )

    if counts.get("models", 0) > 0 and counts.get("prefabs", 0) == 0:
        add(
            "medium",
            "assets",
            "Prefabize Imported Models",
            "Model files were found without matching prefabs. Wrapping imported content in prefabs makes rig setup, overrides, colliders, scripts, and reuse much easier.",
        )

    if counts.get("models", 0) > 0 and counts.get("animations", 0) == 0 and counts.get("animatorControllers", 0) == 0:
        add(
            "medium",
            "animation",
            "Audit Rig And Animation Pipeline",
            "The project has model assets but no .anim clips or Animator Controllers were detected. If characters are planned, this is a good time to define rig import settings, avatar setup, and animation ownership.",
        )

    if (
        importer_audit.get("modelImporterCount", 0) > 0
        and importer_audit.get("modelImportMaterialDisabledCount", 0) > 0
        and counts.get("materials", 0) == 0
    ):
        add(
            "medium",
            "assets",
            "Review Model Material Import",
            "One or more model importers appear to have material import disabled while the project still has no material library. Decide whether materials should be extracted, generated, or owned manually.",
        )

    if counts.get("animations", 0) > 0 and counts.get("animatorControllers", 0) == 0:
        add(
            "medium",
            "animation",
            "Create Animator Controllers",
            "Animation clips exist but no Animator Controllers were detected. Add controllers or a runtime animation state layer so those clips are actually reusable in scene logic.",
        )

    if importer_audit.get("potentialNormalMapMisconfiguredCount", 0) > 0:
        add(
            "medium",
            "assets",
            "Fix Likely Normal Map Imports",
            "Some texture assets look like normal maps by folder or filename, but their import settings do not appear to mark them as Normal Map textures.",
        )

    if importer_audit.get("potentialSpriteMisconfiguredCount", 0) > 0:
        add(
            "medium",
            "assets",
            "Fix Likely Sprite Imports",
            "Some texture assets live in sprite-like folders or use sprite-style names, but their import settings do not appear to mark them as Sprite textures.",
        )

    if counts.get("audio", 0) > 0 and counts.get("mixers", 0) == 0:
        add(
            "low",
            "audio",
            "Add Audio Mixers",
            "Audio assets are present but no mixer assets were found. Adding mixers early makes it easier to balance music, SFX, VO, and debug volume routing later.",
        )

    if counts.get("scripts", 0) >= 20 and counts.get("testScripts", 0) == 0:
        add(
            "medium",
            "testing",
            "Add Editor Or Play Mode Tests",
            "The project already has a meaningful script surface but no test scripts were detected. Even a small smoke suite helps protect scene tools, import steps, and core gameplay helpers.",
        )

    scene_samples = [Path(path).stem.lower() for path in (asset_scan.get("samples") or {}).get("scenes", [])]
    if counts.get("scenes", 0) > 0 and not any(token in name for name in scene_samples for token in ("test", "sandbox", "dev", "playground")):
        add(
            "low",
            "scene",
            "Add A Sandbox Scene",
            "No obvious test or sandbox scene was detected. A disposable scene for probes and agent passes makes iteration safer and faster.",
        )

    summary = dict((inspect_payload or {}).get("summary") or {})
    if summary.get("sceneDirty"):
        add(
            "low",
            "workflow",
            "Save Or Snapshot The Active Scene",
            "The active scene is currently dirty. Saving or snapshotting before a larger agent pass makes it easier to compare results and recover from bad edits.",
        )

    return recommendations


def build_project_insights(
    project_root: str | Path | None,
    *,
    inspect_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not project_root:
        return {
            "available": False,
            "error": "Project path is unavailable.",
        }

    root = Path(project_root)
    guidance = collect_project_guidance(root)
    asset_scan = scan_project_assets(root)
    recommendations = build_project_recommendations(
        guidance=guidance,
        asset_scan=asset_scan,
        inspect_payload=inspect_payload,
    )

    return {
        "available": True,
        "projectRoot": str(root),
        "guidance": guidance,
        "assetScan": asset_scan,
        "recommendations": recommendations,
    }


def build_asset_audit_report(
    project_root: str | Path | None,
    *,
    inspect_payload: dict[str, Any] | None = None,
    recommendation_limit: int = 6,
) -> dict[str, Any]:
    insights = build_project_insights(project_root, inspect_payload=inspect_payload)
    if not insights.get("available"):
        return insights

    asset_scan = dict(insights.get("assetScan") or {})
    counts = dict(asset_scan.get("counts") or {})
    importer_audit = dict(asset_scan.get("importerAudit") or {})
    guidance = dict(insights.get("guidance") or {})
    recommendations = list(insights.get("recommendations") or [])
    ordered_recommendations = _sort_recommendations(recommendations)
    priority_breakdown = _build_priority_breakdown(recommendations)
    focus_areas = _build_focus_areas(recommendations)

    inspect_summary = dict((inspect_payload or {}).get("summary") or {})
    inspect_project = dict((inspect_payload or {}).get("project") or {})
    project_name = (
        inspect_summary.get("projectName")
        or inspect_project.get("productName")
        or Path(str(insights.get("projectRoot") or project_root)).name
    )

    summary = {
        "projectName": project_name,
        "projectRoot": insights.get("projectRoot"),
        "renderPipeline": inspect_project.get("renderPipeline") or inspect_project.get("currentRenderPipeline"),
        "activeScene": inspect_summary.get("activeScene"),
        "sceneDirty": bool(inspect_summary.get("sceneDirty")),
        "hasGuidance": bool(guidance.get("found")),
        "guidanceFileCount": int(guidance.get("fileCount") or 0),
        "topLevelFolderCount": len(asset_scan.get("topLevelFolders") or []),
        "sceneCount": int(counts.get("scenes") or 0),
        "scriptCount": int(counts.get("scripts") or 0),
        "testScriptCount": int(counts.get("testScripts") or 0),
        "asmdefCount": int(counts.get("asmdefs") or 0),
        "prefabCount": int(counts.get("prefabs") or 0),
        "materialCount": int(counts.get("materials") or 0),
        "textureCount": int(counts.get("textures") or 0),
        "modelCount": int(counts.get("models") or 0),
        "animationCount": int(counts.get("animations") or 0),
        "animatorControllerCount": int(counts.get("animatorControllers") or 0),
        "audioCount": int(counts.get("audio") or 0),
        "packageCount": int(asset_scan.get("packageCount") or 0),
        "hasImporterAudit": bool(importer_audit.get("available")),
        "modelImporterCount": int(importer_audit.get("modelImporterCount") or 0),
        "textureImporterCount": int(importer_audit.get("textureImporterCount") or 0),
        "potentialNormalMapMisconfiguredCount": int(
            importer_audit.get("potentialNormalMapMisconfiguredCount") or 0
        ),
        "potentialSpriteMisconfiguredCount": int(
            importer_audit.get("potentialSpriteMisconfiguredCount") or 0
        ),
        "recommendationCount": len(recommendations),
        "highestPriority": ordered_recommendations[0].get("priority") if ordered_recommendations else None,
    }

    return {
        "available": True,
        "projectRoot": insights.get("projectRoot"),
        "summary": summary,
        "priorityBreakdown": priority_breakdown,
        "focusAreas": focus_areas,
        "topRecommendations": ordered_recommendations[: max(1, recommendation_limit)],
        "guidance": guidance,
        "assetScan": asset_scan,
        "recommendations": recommendations,
    }
