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

    if not assets_root.is_dir():
        return {
            "exists": False,
            "assetsRoot": "Assets",
            "counts": counts,
            "samples": samples,
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

    if counts.get("animations", 0) > 0 and counts.get("animatorControllers", 0) == 0:
        add(
            "medium",
            "animation",
            "Create Animator Controllers",
            "Animation clips exist but no Animator Controllers were detected. Add controllers or a runtime animation state layer so those clips are actually reusable in scene logic.",
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
