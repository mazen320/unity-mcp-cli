from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _safe_csharp_identifier(value: str) -> str:
    raw = "".join(ch for ch in str(value or "") if ch.isalnum() or ch == "_")
    if not raw:
        raw = "Project"
    if raw[0].isdigit():
        raw = f"_{raw}"
    return raw


def _project_identity(context: dict[str, Any]) -> tuple[str, str]:
    project = dict(context.get("project") or {})
    project_name = (
        str(project.get("name") or "").strip()
        or Path(str(project.get("path") or "")).name
        or "Project"
    )
    return project_name, _safe_csharp_identifier(project_name)


def _packages_from_context(context: dict[str, Any] | None) -> set[str]:
    if not isinstance(context, dict):
        return set()
    packages = {
        str(package)
        for package in (((((context.get("raw") or {}).get("audit") or {}).get("assetScan") or {}).get("packages")) or [])
        if str(package).strip()
    }
    normalized_packages = {package.strip().lower() for package in packages}

    project = dict(context.get("project") or {})
    project_path = str(project.get("path") or "").strip()
    manifest_path = Path(project_path) / "Packages" / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
            dependencies = manifest.get("dependencies") or {}
            if isinstance(dependencies, dict):
                normalized_packages.update(
                    str(name).strip().lower()
                    for name in dependencies.keys()
                    if str(name).strip()
                )
        except json.JSONDecodeError:
            pass

    return normalized_packages


def _default_animation_controller_path(context: dict[str, Any]) -> str:
    _project_name, safe_name = _project_identity(context)
    return f"Assets/Animations/Generated/{safe_name}_Auto.controller"


def _flatten_scene_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def _find_first_animator_path(context: dict[str, Any]) -> str:
    inspect_payload = dict(((context.get("raw") or {}).get("inspect")) or {})
    hierarchy = dict(inspect_payload.get("hierarchy") or {})
    raw_nodes = hierarchy.get("nodes") or hierarchy.get("hierarchy") or []
    nodes = _flatten_scene_nodes([node for node in raw_nodes if isinstance(node, dict)])
    for node in nodes:
        components = {str(component) for component in (node.get("components") or [])}
        if "Animator" not in components:
            continue
        path = str(node.get("path") or node.get("name") or "").strip()
        if path:
            return path
    raise ValueError(
        "Animation controller wireup needs a live scene with at least one Animator component."
    )


def choose_event_system_module(
    *,
    context: dict[str, Any] | None = None,
    audit_report: dict[str, Any] | None = None,
) -> str:
    packages: list[str] = []
    if isinstance(audit_report, dict):
        packages = [
            str(package)
            for package in ((((audit_report.get("assetScan") or {}).get("packages")) or []))
            if str(package).strip()
        ]
    elif isinstance(context, dict):
        packages = [
            str(package)
            for package in (((((context.get("raw") or {}).get("audit") or {}).get("assetScan") or {}).get("packages")) or [])
            if str(package).strip()
        ]

    normalized_packages = {package.strip().lower() for package in packages}
    if "com.unity.inputsystem" in normalized_packages:
        return "InputSystemUIInputModule"
    return "StandaloneInputModule"


def build_test_scaffold_spec(
    *,
    context: dict[str, Any],
) -> dict[str, str]:
    project_name, safe_name = _project_identity(context)
    folder = "Assets/Tests/EditMode"
    return {
        "projectName": project_name,
        "safeName": safe_name,
        "folder": folder,
        "scriptPath": f"{folder}/{safe_name}SmokeTests.cs",
        "asmdefPath": f"{folder}/{safe_name}.EditMode.Tests.asmdef",
        "className": f"{safe_name}SmokeTests",
        "assemblyName": f"{safe_name}.EditMode.Tests",
    }


def build_quality_fix_plan(
    *,
    context: dict[str, Any],
    lens_name: str,
    fix_name: str,
) -> dict[str, Any]:
    project_path = (
        (context.get("project") or {}).get("path")
        or (context.get("project") or {}).get("projectPath")
        or (context.get("raw") or {}).get("audit", {}).get("projectRoot")
    )

    if not project_path:
        raise ValueError("Quality fixes need a project path in the expert context.")

    normalized_fix = str(fix_name or "").strip().lower()
    normalized_lens = str(lens_name or "").strip().lower()

    if normalized_fix == "guidance":
        return {
            "mode": "workflow",
            "title": "Bootstrap project guidance",
            "description": "Generate AGENTS.md and optional MCP context files from the current audit.",
            "command": ["workflow", "bootstrap-guidance", str(project_path)],
            "lens": normalized_lens,
            "fix": normalized_fix,
            "projectRoot": str(project_path),
            "safe": True,
        }

    if normalized_fix == "test-scaffold":
        spec = build_test_scaffold_spec(context=context)
        has_test_framework = "com.unity.test-framework" in _packages_from_context(context)
        return {
            "mode": "workflow" if has_test_framework else "manual",
            "title": "Scaffold EditMode smoke tests",
            "description": "Create a minimal Unity EditMode smoke test and matching test assembly so the project has a stable starting point for CLI-driven verification.",
            "command": [
                "workflow",
                "quality-fix",
                "--lens",
                "director",
                "--fix",
                "test-scaffold",
                "--apply",
            ],
            "lens": normalized_lens,
            "fix": normalized_fix,
            "projectRoot": str(project_path),
            "safe": True,
            "requiresTestFrameworkPackage": True,
            "hasTestFrameworkPackage": has_test_framework,
            "fileCount": 2,
            "scriptPath": spec["scriptPath"],
            "asmdefPath": spec["asmdefPath"],
            "className": spec["className"],
            "assemblyName": spec["assemblyName"],
            "nextSteps": [
                "Confirm the project already includes com.unity.test-framework.",
                f"Write the smoke test at {spec['scriptPath']}.",
                f"Write the test assembly definition at {spec['asmdefPath']}.",
            ],
        }

    if normalized_fix == "sandbox-scene":
        return {
            "mode": "workflow",
            "title": "Create sandbox scene",
            "description": "Create a disposable sandbox scene for safer probes and content passes.",
            "command": ["workflow", "create-sandbox-scene"],
            "lens": normalized_lens,
            "fix": normalized_fix,
            "projectRoot": str(project_path),
            "safe": True,
        }

    if normalized_fix == "event-system":
        module_type = choose_event_system_module(context=context)
        return {
            "mode": "workflow",
            "title": "Add EventSystem",
            "description": "Create or repair a scene EventSystem object so Canvas UI can receive input, choosing the input module that matches the project packages.",
            "command": [
                "workflow",
                "quality-fix",
                "--lens",
                "systems",
                "--fix",
                "event-system",
                "--apply",
            ],
            "lens": normalized_lens,
            "fix": normalized_fix,
            "projectRoot": str(project_path),
            "gameObjectName": "EventSystem",
            "moduleType": module_type,
            "safe": True,
            "requiresLiveUnity": True,
            "nextSteps": [
                "Run workflow expert-audit --lens systems to confirm the EventSystem gap.",
                f"Create or repair the EventSystem object with {module_type}.",
                "Re-run the systems audit after the UI input path is in place.",
            ],
        }

    if normalized_fix == "ui-canvas-scaler":
        return {
            "mode": "workflow",
            "title": "Add CanvasScaler components",
            "description": "Inspect each Canvas that is missing a CanvasScaler and add one through the bounded workflow fix path.",
            "command": [
                "workflow",
                "quality-fix",
                "--lens",
                "ui",
                "--fix",
                "ui-canvas-scaler",
                "--apply",
            ],
            "lens": normalized_lens,
            "fix": normalized_fix,
            "projectRoot": str(project_path),
            "safe": True,
            "nextSteps": [
                "Run workflow expert-audit --lens ui to confirm which canvases need attention.",
                "Add CanvasScaler to the canvases that are missing one.",
                "Re-check the scene after changes.",
            ],
        }

    if normalized_fix == "texture-imports":
        return {
            "mode": "workflow",
            "title": "Repair texture importer mismatches",
            "description": "Apply the bounded tech-art fix that marks likely normal maps and sprite textures with the right importer type through Unity.",
            "command": [
                "workflow",
                "quality-fix",
                "--lens",
                "tech-art",
                "--fix",
                "texture-imports",
                "--apply",
            ],
            "lens": normalized_lens,
            "fix": normalized_fix,
            "projectRoot": str(project_path),
            "safe": True,
            "requiresLiveUnity": True,
            "nextSteps": [
                "Run workflow expert-audit --lens tech-art to confirm the importer mismatch findings.",
                "Apply the texture importer repair through a live Unity editor session.",
                "Re-run the tech-art audit after the importer changes.",
            ],
        }

    if normalized_fix == "controller-scaffold":
        controller_path = _default_animation_controller_path(context)
        return {
            "mode": "workflow",
            "title": "Scaffold an Animator Controller",
            "description": "Create a generated Animator Controller asset through Unity so the animation pipeline has a safe place to start wiring clips and states.",
            "command": [
                "workflow",
                "quality-fix",
                "--lens",
                "animation",
                "--fix",
                "controller-scaffold",
                "--apply",
            ],
            "lens": normalized_lens,
            "fix": normalized_fix,
            "projectRoot": str(project_path),
            "controllerPath": controller_path,
            "safe": True,
            "requiresLiveUnity": True,
            "nextSteps": [
                "Run workflow expert-audit --lens animation to confirm the controller gap.",
                f"Create the generated controller at {controller_path}.",
                "Assign clips and states once the scaffold asset exists.",
            ],
        }

    if normalized_fix == "controller-wireup":
        controller_path = _default_animation_controller_path(context)
        target_path = _find_first_animator_path(context)
        return {
            "mode": "workflow",
            "title": "Wire a generated Animator Controller",
            "description": "Create the generated Animator Controller if needed, then assign it to the first live Animator in the inspected scene.",
            "command": [
                "workflow",
                "quality-fix",
                "--lens",
                "animation",
                "--fix",
                "controller-wireup",
                "--apply",
            ],
            "lens": normalized_lens,
            "fix": normalized_fix,
            "projectRoot": str(project_path),
            "controllerPath": controller_path,
            "targetGameObjectPath": target_path,
            "safe": True,
            "requiresLiveUnity": True,
            "nextSteps": [
                "Confirm the scene really contains the Animator you want to wire up.",
                f"Create or reuse the generated controller at {controller_path}.",
                f"Assign that controller to {target_path}.",
            ],
        }

    raise ValueError(f"Unsupported fix '{fix_name}' for lens '{lens_name}'.")
