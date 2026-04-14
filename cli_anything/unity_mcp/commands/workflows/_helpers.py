"""Private helpers shared across workflow domain modules."""
from __future__ import annotations

# Expose all names (including underscore-prefixed) for wildcard imports in domain modules.
__all__ = [
    # stdlib re-exports
    "UTC", "datetime", "json", "Path", "Any",
    # third-party
    "click",
    # core imports
    "build_expert_context",
    "build_quality_fix_plan", "build_test_scaffold_spec", "choose_event_system_module",
    "grade_score", "get_builtin_expert_lens", "iter_builtin_expert_lenses",
    "build_guidance_bundle", "write_guidance_bundle",
    "build_asset_audit_report", "build_project_insights",
    "ProjectMemory", "memory_for_session",
    # shared imports
    "BackendSelectionError", "UnityMCPClientError",
    "_learn_from_inspect", "_record_progress_step", "_run_and_emit",
    "build_asset_path", "build_behaviour_script", "get_active_scene_path",
    "require_workflow_success", "sanitize_csharp_identifier",
    "unique_probe_name", "vec3", "wait_for_compilation", "wait_for_result",
    "workflow_error_message",
    # helper functions
    "_normalize_sandbox_folder", "_is_missing_route_error",
    "_unwrap_execute_code_result", "_build_create_sandbox_execute_code",
    "_resolve_workflow_project_context", "_normalize_project_path_for_compare",
    "_resolve_improve_project_context", "_attach_unity_context",
    "_build_expert_audit_payload", "_enrich_inspect_payload_for_lenses",
    "_iter_hierarchy_nodes", "_extract_hierarchy_nodes",
    "_benchmark_severity_rank", "_load_benchmark_report",
    "_normalize_benchmark_finding", "_normalize_benchmark_diagnostic_entry",
    "_build_queue_diagnostics_summary", "_default_queue_trend_summary",
    "_compare_benchmark_reports", "_format_signed_delta",
    "_render_benchmark_compare_markdown", "_collect_expert_audit_results",
    "_build_quality_score_payload", "_rank_scene_camera_node",
    "_rank_likely_player_node", "_looks_disposable_scene_object",
    "_rank_scene_event_system_node", "_render_editmode_smoke_test",
    "_render_editmode_test_asmdef", "_create_sandbox_scene_payload",
    "_render_improve_project_markdown",
    # fix helpers
    "_apply_ui_canvas_scaler_fix", "_apply_ui_graphic_raycaster_fix",
    "_apply_systems_audio_listener_fix", "_apply_systems_disposable_cleanup_fix",
    "_apply_physics_player_character_controller_fix", "_apply_systems_event_system_fix",
    "_apply_director_test_scaffold_fix", "_apply_texture_import_fix",
    "_apply_animation_controller_scaffold_fix", "_apply_animation_controller_wireup_fix",
]
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
import click
from ...core.expert_context import build_expert_context
from ...core.expert_fixes import (
    build_quality_fix_plan,
    build_test_scaffold_spec,
    choose_event_system_module,
)
from ...core.expert_lenses import grade_score, get_builtin_expert_lens, iter_builtin_expert_lenses
from ...core.project_guidance import build_guidance_bundle, write_guidance_bundle
from ...core.project_insights import build_asset_audit_report, build_project_insights
from ...core.memory import ProjectMemory, memory_for_session
from .._shared import (
    BackendSelectionError,
    UnityMCPClientError,
    _learn_from_inspect,
    _record_progress_step,
    _run_and_emit,
    build_asset_path,
    build_behaviour_script,
    get_active_scene_path,
    require_workflow_success,
    sanitize_csharp_identifier,
    unique_probe_name,
    vec3,
    wait_for_compilation,
    wait_for_result,
    workflow_error_message,
)

def _normalize_sandbox_folder(folder: str) -> str:
    normalized = str(folder or "Assets/Scenes").strip().replace("\\", "/").rstrip("/")
    if not normalized:
        normalized = "Assets/Scenes"
    if not normalized.startswith("Assets"):
        raise ValueError("Sandbox scene folder must live under Assets/.")
    return normalized


def _is_missing_route_error(message: str | None) -> bool:
    if not message:
        return False
    lowered = message.lower()
    return (
        "unknown route" in lowered
        or "unknown api endpoint" in lowered
        or "not found" in lowered
    )


def _unwrap_execute_code_result(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    if payload.get("success") is True and "result" in payload:
        return payload.get("result")
    return payload


def _build_create_sandbox_execute_code(
    *,
    name: str | None,
    folder: str,
    open_scene: bool,
    save_if_dirty: bool,
    discard_unsaved: bool,
) -> str:
    name_literal = "null" if name is None else json.dumps(name)
    folder_literal = json.dumps(folder)
    open_literal = "true" if open_scene else "false"
    save_literal = "true" if save_if_dirty else "false"
    discard_literal = "true" if discard_unsaved else "false"
    return f"""
string folder = {folder_literal};
bool leaveOpen = {open_literal};
bool saveIfDirty = {save_literal};
bool discardUnsaved = {discard_literal};
string requestedName = {name_literal};

folder = string.IsNullOrWhiteSpace(folder) ? "Assets/Scenes" : folder.Trim().TrimEnd('/', '\\\\');
if (!folder.StartsWith("Assets", StringComparison.OrdinalIgnoreCase))
    return new Dictionary<string, object> {{ {{ "error", "Sandbox scene folder must live under Assets/." }} }};

var activeScene = UnityEngine.SceneManagement.SceneManager.GetActiveScene();
string originalPath = activeScene.path ?? "";
string originalName = activeScene.name ?? "";

if (activeScene.isDirty)
{{
    if (discardUnsaved)
    {{
    }}
    else if (saveIfDirty)
    {{
        if (string.IsNullOrEmpty(activeScene.path))
            return new Dictionary<string, object> {{ {{ "error", "Active scene is dirty and unsaved. Save it first or pass discardUnsaved." }} }};
        if (!EditorSceneManager.SaveScene(activeScene))
            return new Dictionary<string, object> {{ {{ "error", "Failed to save the active scene before creating the sandbox scene." }} }};
    }}
    else
    {{
        return new Dictionary<string, object> {{ {{ "error", "Active scene has unsaved changes. Pass saveIfDirty or discardUnsaved." }} }};
    }}
}}

if (string.IsNullOrWhiteSpace(requestedName))
{{
    string safeProjectName = new string((UnityEngine.Application.productName ?? "Project").Where(ch => char.IsLetterOrDigit(ch) || ch == '_').ToArray());
    if (string.IsNullOrWhiteSpace(safeProjectName))
        safeProjectName = "Project";
    requestedName = safeProjectName + "_Sandbox";
}}
requestedName = new string(requestedName.Where(ch => char.IsLetterOrDigit(ch) || ch == '_' || ch == '-').ToArray());
if (string.IsNullOrWhiteSpace(requestedName))
    requestedName = "Sandbox";

string relativePath = folder + "/" + requestedName + ".unity";
string projectRoot = System.IO.Path.GetDirectoryName(UnityEngine.Application.dataPath);
string fullPath = System.IO.Path.Combine(projectRoot, relativePath.Replace("/", System.IO.Path.DirectorySeparatorChar.ToString()));
string targetDirectory = System.IO.Path.GetDirectoryName(fullPath);
if (!string.IsNullOrEmpty(targetDirectory))
    System.IO.Directory.CreateDirectory(targetDirectory);

bool existed = System.IO.File.Exists(fullPath);
var sandboxScene = existed
    ? EditorSceneManager.OpenScene(relativePath, OpenSceneMode.Single)
    : EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);

if (!existed && !EditorSceneManager.SaveScene(sandboxScene, relativePath))
    return new Dictionary<string, object> {{ {{ "error", "Failed to save sandbox scene at " + relativePath }} }};

bool reopenedOriginal = false;
bool keptOpen = true;
string activeSceneName = sandboxScene.name;

if (!leaveOpen && !string.IsNullOrEmpty(originalPath))
{{
    var reopened = EditorSceneManager.OpenScene(originalPath, OpenSceneMode.Single);
    reopenedOriginal = true;
    keptOpen = false;
    activeSceneName = reopened.name;
}}

return new Dictionary<string, object>
{{
    {{ "success", true }},
    {{ "sceneName", requestedName }},
    {{ "path", relativePath }},
    {{ "folder", folder }},
    {{ "existed", existed }},
    {{ "reopenedOriginal", reopenedOriginal }},
    {{ "keptOpen", keptOpen }},
    {{ "originalSceneName", originalName }},
    {{ "originalScenePath", originalPath }},
    {{ "activeSceneName", activeSceneName }}
}};
"""


def _resolve_workflow_project_context(
    ctx: click.Context,
    *,
    project_root: str | None,
    port: int | None,
    progress_label: str,
) -> tuple[str, int | None, dict[str, Any] | None, dict[str, Any], dict[str, Any], dict[str, Any]]:
    workflow_port = port
    ping: dict[str, Any] = {}
    project: dict[str, Any] = {}
    editor_state: dict[str, Any] = {}
    inspect_payload: dict[str, Any] | None = None

    if project_root:
        return project_root, workflow_port, inspect_payload, ping, project, editor_state

    if port is not None:
        ctx.obj.backend.select_instance(port)
        workflow_port = None

    _record_progress_step(ctx, progress_label, phase="check", port=workflow_port)
    ping = ctx.obj.backend.ping(port=workflow_port)
    project = ctx.obj.backend.call_route_with_recovery(
        "project/info",
        port=workflow_port,
        recovery_timeout=10.0,
    )
    editor_state = ctx.obj.backend.call_route_with_recovery(
        "editor/state",
        port=workflow_port,
        recovery_timeout=10.0,
    )
    resolved_project_root = (
        ping.get("projectPath")
        or editor_state.get("projectPath")
        or project.get("projectPath")
    )
    inspect_payload = {
        "summary": {
            "projectName": ping.get("projectName") or project.get("projectName"),
            "projectPath": resolved_project_root,
            "activeScene": editor_state.get("activeScene"),
            "sceneDirty": bool(editor_state.get("sceneDirty")),
            "isPlaying": bool(editor_state.get("isPlaying")),
            "isCompiling": bool(project.get("isCompiling") or editor_state.get("isCompiling")),
        },
        "project": project,
        "ping": ping,
        "state": editor_state,
        "editorState": editor_state,
        "scene": {"activeScene": editor_state.get("activeScene")},
    }
    if not resolved_project_root:
        raise ValueError(
            "This workflow needs a Unity project path. Pass PROJECT_ROOT explicitly or select a Unity editor first."
        )
    return resolved_project_root, workflow_port, inspect_payload, ping, project, editor_state


def _normalize_project_path_for_compare(path: str | None) -> str:
    if not path:
        return ""
    try:
        return Path(path).resolve(strict=False).as_posix().rstrip("/").lower()
    except OSError:
        return str(path).replace("\\", "/").rstrip("/").lower()


def _resolve_improve_project_context(
    ctx: click.Context,
    *,
    project_root: str | None,
    port: int | None,
    progress_label: str,
) -> tuple[str, int | None, dict[str, Any] | None, dict[str, Any], dict[str, Any], dict[str, Any], bool]:
    workflow_port = port
    ping: dict[str, Any] = {}
    project: dict[str, Any] = {}
    editor_state: dict[str, Any] = {}
    inspect_payload: dict[str, Any] | None = None
    live_project_root: str | None = None

    if port is not None:
        ctx.obj.backend.select_instance(port)
        workflow_port = None
        _record_progress_step(ctx, progress_label, phase="check", port=workflow_port)
        ping = ctx.obj.backend.ping(port=workflow_port)
        project = ctx.obj.backend.call_route_with_recovery(
            "project/info",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        editor_state = ctx.obj.backend.call_route_with_recovery(
            "editor/state",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        live_project_root = (
            ping.get("projectPath")
            or editor_state.get("projectPath")
            or project.get("projectPath")
        )
        inspect_payload = {
            "summary": {
                "projectName": ping.get("projectName") or project.get("projectName"),
                "projectPath": live_project_root,
                "activeScene": editor_state.get("activeScene"),
                "sceneDirty": bool(editor_state.get("sceneDirty")),
                "isPlaying": bool(editor_state.get("isPlaying")),
                "isCompiling": bool(project.get("isCompiling") or editor_state.get("isCompiling")),
            },
            "project": project,
            "ping": ping,
            "state": editor_state,
            "editorState": editor_state,
            "scene": {"activeScene": editor_state.get("activeScene")},
        }
    elif project_root:
        selected_instance = getattr(ctx.obj.backend.session_store.load(), "selected_instance", None) or {}
        selected_project_root = (
            selected_instance.get("projectPath")
            or selected_instance.get("project_path")
            or ""
        )
        requested_root = _normalize_project_path_for_compare(project_root)
        active_root = _normalize_project_path_for_compare(selected_project_root)
        if requested_root and active_root and requested_root == active_root:
            try:
                _record_progress_step(ctx, progress_label, phase="check", port=workflow_port)
                ping = ctx.obj.backend.ping(port=workflow_port)
                project = ctx.obj.backend.call_route_with_recovery(
                    "project/info",
                    port=workflow_port,
                    recovery_timeout=10.0,
                )
                editor_state = ctx.obj.backend.call_route_with_recovery(
                    "editor/state",
                    port=workflow_port,
                    recovery_timeout=10.0,
                )
                live_project_root = (
                    ping.get("projectPath")
                    or editor_state.get("projectPath")
                    or project.get("projectPath")
                )
                inspect_payload = {
                    "summary": {
                        "projectName": ping.get("projectName") or project.get("projectName"),
                        "projectPath": live_project_root,
                        "activeScene": editor_state.get("activeScene"),
                        "sceneDirty": bool(editor_state.get("sceneDirty")),
                        "isPlaying": bool(editor_state.get("isPlaying")),
                        "isCompiling": bool(project.get("isCompiling") or editor_state.get("isCompiling")),
                    },
                    "project": project,
                    "ping": ping,
                    "state": editor_state,
                    "editorState": editor_state,
                    "scene": {"activeScene": editor_state.get("activeScene")},
                }
            except Exception:
                ping = {}
                project = {}
                editor_state = {}
                inspect_payload = None
                live_project_root = None

    resolved_project_root = str(project_root or live_project_root or "").strip()
    if not resolved_project_root:
        raise ValueError(
            "This workflow needs a Unity project path. Pass PROJECT_ROOT explicitly or target a live Unity editor with --port."
        )

    if project_root and live_project_root:
        requested_root = _normalize_project_path_for_compare(project_root)
        active_root = _normalize_project_path_for_compare(live_project_root)
        if requested_root and active_root and requested_root != active_root:
            raise ValueError(
                "PROJECT_ROOT does not match the Unity editor targeted by --port. Pass the matching project root or omit PROJECT_ROOT."
            )

    return (
        resolved_project_root,
        workflow_port,
        inspect_payload,
        ping,
        project,
        editor_state,
        inspect_payload is not None,
    )


def _attach_unity_context(
    payload: dict[str, Any],
    *,
    ping: dict[str, Any],
    project: dict[str, Any],
    editor_state: dict[str, Any],
) -> dict[str, Any]:
    if ping or project or editor_state:
        payload["unityContext"] = {
            "ping": ping or {},
            "project": project or {},
            "editorState": editor_state or {},
        }
    return payload


def _build_expert_audit_payload(
    *,
    project_root: str,
    inspect_payload: dict[str, Any] | None,
    lens_name: str,
    audit_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    audit_report = audit_report or build_asset_audit_report(
        project_root,
        inspect_payload=inspect_payload,
        recommendation_limit=8,
    )
    if not audit_report.get("available"):
        return audit_report

    lens = get_builtin_expert_lens(lens_name)
    context_available = True
    if lens.requires_live_scene:
        if lens.name in {"ui", "physics"}:
            hierarchy = dict((inspect_payload or {}).get("hierarchy") or {})
            context_available = bool(_extract_hierarchy_nodes(hierarchy))
        elif lens.name == "level-art":
            scene_stats = dict((inspect_payload or {}).get("sceneStats") or {})
            context_available = bool(scene_stats)

    if not context_available:
        return {
            "available": True,
            "projectRoot": audit_report.get("projectRoot"),
            "lens": {
                "name": lens.name,
                "description": lens.description,
                "focus": lens.focus,
                "requiresLiveUnity": True,
                "contextAvailable": False,
            },
            "score": None,
            "grade": None,
            "confidence": 0.0,
            "findings": [
                {
                    "severity": "info",
                    "title": "Live scene context unavailable",
                    "detail": f"The {lens.name} lens needs a selected Unity editor or --port so it can inspect live scene data.",
                }
            ],
            "supportedFixes": list(lens.supported_fix_types),
            "focusAreas": audit_report.get("focusAreas") or [],
            "topRecommendations": audit_report.get("topRecommendations") or [],
            "summary": audit_report.get("summary") or {},
            "context": {
                "project": {},
                "state": {},
                "scene": {},
            },
            "raw": {
                "auditReport": audit_report,
            },
        }

    expert_context = build_expert_context(
        inspect_payload=inspect_payload,
        audit_report=audit_report,
        lens_name=lens.name,
    )
    result = lens.audit(expert_context)
    return {
        "available": True,
        "projectRoot": audit_report.get("projectRoot"),
        "lens": {
            "name": lens.name,
            "description": lens.description,
            "focus": lens.focus,
            "requiresLiveUnity": lens.requires_live_scene,
            "contextAvailable": context_available,
        },
        "score": int(result.get("score") or 0),
        "grade": result.get("grade"),
        "confidence": result.get("confidence"),
        "findings": result.get("findings") or [],
        "supportedFixes": list(lens.supported_fix_types),
        "focusAreas": audit_report.get("focusAreas") or [],
        "topRecommendations": audit_report.get("topRecommendations") or [],
        "summary": audit_report.get("summary") or {},
        "context": {
            "project": expert_context.get("project") or {},
            "state": expert_context.get("state") or {},
            "scene": expert_context.get("scene") or {},
        },
        "raw": {
            "auditReport": audit_report,
        },
    }


def _enrich_inspect_payload_for_lenses(
    ctx: click.Context,
    *,
    workflow_port: int | None,
    inspect_payload: dict[str, Any] | None,
    lens_names: list[str],
) -> dict[str, Any] | None:
    if inspect_payload is None:
        return None

    normalized_lenses = {str(name or "").strip().lower() for name in lens_names}
    enriched = dict(inspect_payload)

    if (
        "ui" in normalized_lenses
        or "animation" in normalized_lenses
        or "systems" in normalized_lenses
        or "physics" in normalized_lenses
    ) and "hierarchy" not in enriched:
        _record_progress_step(
            ctx,
            "Inspecting hierarchy for expert scene audit",
            phase="inspect",
            port=workflow_port,
        )
        enriched["hierarchy"] = ctx.obj.backend.call_route_with_recovery(
            "scene/hierarchy",
            params={"maxDepth": 8, "maxNodes": 800},
            port=workflow_port,
            recovery_timeout=10.0,
        )

    if ("level-art" in normalized_lenses or "systems" in normalized_lenses) and "sceneStats" not in enriched:
        _record_progress_step(
            ctx,
            "Inspecting scene stats for level-art audit",
            phase="inspect",
            port=workflow_port,
        )
        try:
            enriched["sceneStats"] = ctx.obj.backend.call_route_with_recovery(
                "scene/stats",
                port=workflow_port,
                recovery_timeout=10.0,
            )
        except (UnityMCPClientError, ValueError):
            enriched["sceneStats"] = ctx.obj.backend.call_route_with_recovery(
                "search/scene-stats",
                port=workflow_port,
                recovery_timeout=10.0,
            )

    return enriched


def _iter_hierarchy_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def _extract_hierarchy_nodes(hierarchy_payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_nodes = hierarchy_payload.get("nodes")
    if not raw_nodes:
        raw_nodes = hierarchy_payload.get("hierarchy")
    if not isinstance(raw_nodes, list):
        return []
    return [node for node in raw_nodes if isinstance(node, dict)]


def _benchmark_severity_rank(severity: str | None) -> int:
    normalized = str(severity or "").strip().lower()
    if normalized == "high":
        return 0
    if normalized == "medium":
        return 1
    if normalized == "low":
        return 2
    return 3


def _load_benchmark_report(report_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Benchmark report not found: {report_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Benchmark report is not valid JSON: {report_path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Benchmark report must be a JSON object: {report_path}")
    return payload


def _normalize_benchmark_finding(finding: dict[str, Any]) -> tuple[tuple[str, str, str, str], dict[str, Any]]:
    normalized = {
        "lens": str(finding.get("lens") or "").strip(),
        "severity": str(finding.get("severity") or "info").strip().lower(),
        "title": str(finding.get("title") or "").strip(),
        "detail": str(finding.get("detail") or "").strip(),
    }
    key = (
        normalized["lens"],
        normalized["severity"],
        normalized["title"],
        normalized["detail"],
    )
    return key, normalized


def _normalize_benchmark_diagnostic_entry(
    item: dict[str, Any],
    *,
    kind: str,
) -> tuple[tuple[str, ...], dict[str, Any]]:
    if kind == "compilation":
        normalized = {
            "code": str(item.get("code") or "").strip(),
            "file": str(item.get("file") or "").strip(),
            "message": str(item.get("message") or "").strip(),
            "location": str(item.get("location") or "").strip(),
        }
        key = (
            normalized["code"],
            normalized["file"],
            normalized["message"],
            normalized["location"],
        )
        return key, normalized
    normalized = {
        "kind": str(item.get("kind") or "").strip(),
        "key": str(item.get("key") or "").strip(),
        "title": str(item.get("title") or "").strip(),
        "detail": str(item.get("detail") or "").strip(),
    }
    key = (
        normalized["kind"],
        normalized["key"],
        normalized["title"],
        normalized["detail"],
    )
    return key, normalized


def _build_queue_diagnostics_summary(
    recurring_operational_signals: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    queue_signals = [
        dict(item)
        for item in (recurring_operational_signals or [])
        if isinstance(item, dict) and str(item.get("kind") or "").strip().lower() == "queue"
    ]
    queue_signals.sort(
        key=lambda item: (
            -int(item.get("seenCount") or 0),
            str(item.get("key") or ""),
        )
    )
    keys = [
        key
        for key in sorted(
            {
                str(item.get("key") or "").strip()
                for item in queue_signals
                if str(item.get("key") or "").strip()
            }
        )
    ]
    recurring_count = len(queue_signals)
    if recurring_count <= 0:
        return {
            "status": "clear",
            "recurringSignalCount": 0,
            "keys": [],
            "signals": [],
            "summary": "No recurring queue pressure detected.",
        }

    summary = "Recurring queue-related signals are showing up in this project."
    if "queue-contention" in keys:
        summary = "Queue pressure has shown up repeatedly in this project."
    return {
        "status": "contention-observed" if "queue-contention" in keys else "queue-signals-observed",
        "recurringSignalCount": recurring_count,
        "keys": keys,
        "signals": queue_signals[:5],
        "summary": summary,
    }


def _default_queue_trend_summary() -> dict[str, Any]:
    return {
        "status": "no-history",
        "sampleCount": 0,
        "backlogSamples": 0,
        "activeSamples": 0,
        "peakQueued": 0,
        "peakActiveAgents": 0,
        "latestTotalQueued": 0,
        "latestActiveAgents": 0,
        "consecutiveBacklogSamples": 0,
        "summary": "No queue history recorded yet.",
    }


def _compare_benchmark_reports(
    before_report: dict[str, Any],
    after_report: dict[str, Any],
    *,
    before_file: Path,
    after_file: Path,
) -> dict[str, Any]:
    before_score = before_report.get("overallScore")
    after_score = after_report.get("overallScore")
    overall_delta = None
    if before_score is not None and after_score is not None:
        overall_delta = round(float(after_score) - float(before_score), 1)

    before_lenses = {
        str(item.get("name") or "").strip(): dict(item)
        for item in (before_report.get("lensScores") or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    after_lenses = {
        str(item.get("name") or "").strip(): dict(item)
        for item in (after_report.get("lensScores") or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    lens_deltas: list[dict[str, Any]] = []
    for name in sorted(set(before_lenses) | set(after_lenses)):
        before_item = before_lenses.get(name, {})
        after_item = after_lenses.get(name, {})
        before_lens_score = before_item.get("score")
        after_lens_score = after_item.get("score")
        score_delta = None
        if before_lens_score is not None and after_lens_score is not None:
            score_delta = int(after_lens_score) - int(before_lens_score)
        lens_deltas.append(
            {
                "name": name,
                "beforeScore": before_lens_score,
                "afterScore": after_lens_score,
                "scoreDelta": score_delta,
                "beforeGrade": before_item.get("grade"),
                "afterGrade": after_item.get("grade"),
                "beforeFindingCount": before_item.get("findingCount"),
                "afterFindingCount": after_item.get("findingCount"),
                "findingDelta": (
                    int(after_item.get("findingCount") or 0)
                    - int(before_item.get("findingCount") or 0)
                ),
            }
        )
    lens_deltas.sort(
        key=lambda item: (
            item.get("scoreDelta") is None,
            -abs(int(item.get("scoreDelta") or 0)),
            str(item.get("name") or ""),
        )
    )

    before_findings = dict(
        _normalize_benchmark_finding(item)
        for item in (before_report.get("topFindings") or [])
        if isinstance(item, dict)
    )
    after_findings = dict(
        _normalize_benchmark_finding(item)
        for item in (after_report.get("topFindings") or [])
        if isinstance(item, dict)
    )
    new_findings = [after_findings[key] for key in after_findings.keys() - before_findings.keys()]
    resolved_findings = [before_findings[key] for key in before_findings.keys() - after_findings.keys()]
    unchanged_findings = [after_findings[key] for key in before_findings.keys() & after_findings.keys()]
    for collection in (new_findings, resolved_findings, unchanged_findings):
        collection.sort(
            key=lambda item: (
                _benchmark_severity_rank(item.get("severity")),
                str(item.get("lens") or ""),
                str(item.get("title") or ""),
            )
        )

    before_diag = dict(before_report.get("diagnosticsMemory") or {})
    after_diag = dict(after_report.get("diagnosticsMemory") or {})

    before_compilation = dict(
        _normalize_benchmark_diagnostic_entry(item, kind="compilation")
        for item in (before_diag.get("recurringCompilationErrors") or [])
        if isinstance(item, dict)
    )
    after_compilation = dict(
        _normalize_benchmark_diagnostic_entry(item, kind="compilation")
        for item in (after_diag.get("recurringCompilationErrors") or [])
        if isinstance(item, dict)
    )
    before_operational = dict(
        _normalize_benchmark_diagnostic_entry(item, kind="operational")
        for item in (before_diag.get("recurringOperationalSignals") or [])
        if isinstance(item, dict)
    )
    after_operational = dict(
        _normalize_benchmark_diagnostic_entry(item, kind="operational")
        for item in (after_diag.get("recurringOperationalSignals") or [])
        if isinstance(item, dict)
    )

    new_compilation = [after_compilation[key] for key in after_compilation.keys() - before_compilation.keys()]
    resolved_compilation = [before_compilation[key] for key in before_compilation.keys() - after_compilation.keys()]
    new_operational = [after_operational[key] for key in after_operational.keys() - before_operational.keys()]
    resolved_operational = [before_operational[key] for key in before_operational.keys() - after_operational.keys()]
    for collection in (new_compilation, resolved_compilation):
        collection.sort(key=lambda item: (str(item.get("code") or ""), str(item.get("file") or "")))
    for collection in (new_operational, resolved_operational):
        collection.sort(key=lambda item: (str(item.get("kind") or ""), str(item.get("key") or "")))

    before_queue_diagnostics = dict(before_report.get("queueDiagnostics") or {})
    if not before_queue_diagnostics:
        before_queue_diagnostics = _build_queue_diagnostics_summary(
            list(before_diag.get("recurringOperationalSignals") or [])
        )
    after_queue_diagnostics = dict(after_report.get("queueDiagnostics") or {})
    if not after_queue_diagnostics:
        after_queue_diagnostics = _build_queue_diagnostics_summary(
            list(after_diag.get("recurringOperationalSignals") or [])
        )
    before_queue_signal_source = list(before_queue_diagnostics.get("signals") or [])
    if not before_queue_signal_source:
        before_queue_signal_source = [
            dict(item)
            for item in before_operational.values()
            if str(item.get("kind") or "").strip().lower() == "queue"
        ]
    after_queue_signal_source = list(after_queue_diagnostics.get("signals") or [])
    if not after_queue_signal_source:
        after_queue_signal_source = [
            dict(item)
            for item in after_operational.values()
            if str(item.get("kind") or "").strip().lower() == "queue"
        ]
    before_queue_signals = {
        _normalize_benchmark_diagnostic_entry(item, kind="operational")[0]: _normalize_benchmark_diagnostic_entry(
            item,
            kind="operational",
        )[1]
        for item in before_queue_signal_source
        if isinstance(item, dict)
    }
    after_queue_signals = {
        _normalize_benchmark_diagnostic_entry(item, kind="operational")[0]: _normalize_benchmark_diagnostic_entry(
            item,
            kind="operational",
        )[1]
        for item in after_queue_signal_source
        if isinstance(item, dict)
    }
    new_queue_signals = [
        after_queue_signals[key]
        for key in after_queue_signals.keys() - before_queue_signals.keys()
    ]
    resolved_queue_signals = [
        before_queue_signals[key]
        for key in before_queue_signals.keys() - after_queue_signals.keys()
    ]
    for collection in (new_queue_signals, resolved_queue_signals):
        collection.sort(key=lambda item: (str(item.get("kind") or ""), str(item.get("key") or "")))

    before_queue_trend = dict(before_report.get("queueTrend") or {})
    if not before_queue_trend:
        before_queue_trend = _default_queue_trend_summary()
    after_queue_trend = dict(after_report.get("queueTrend") or {})
    if not after_queue_trend:
        after_queue_trend = _default_queue_trend_summary()

    return {
        "available": True,
        "benchmarkVersion": str(after_report.get("benchmarkVersion") or before_report.get("benchmarkVersion") or ""),
        "comparedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "beforeFile": str(before_file),
        "afterFile": str(after_file),
        "beforeLabel": before_report.get("label"),
        "afterLabel": after_report.get("label"),
        "beforeOverallScore": before_score,
        "afterOverallScore": after_score,
        "overallScoreDelta": overall_delta,
        "beforeOverallGrade": before_report.get("overallGrade"),
        "afterOverallGrade": after_report.get("overallGrade"),
        "lensDeltas": lens_deltas,
        "findingDelta": {
            "newCount": len(new_findings),
            "resolvedCount": len(resolved_findings),
            "unchangedCount": len(unchanged_findings),
        },
        "newFindings": new_findings,
        "resolvedFindings": resolved_findings,
        "diagnosticsDelta": {
            "newRecurringCompilationErrorCount": len(new_compilation),
            "resolvedRecurringCompilationErrorCount": len(resolved_compilation),
            "newRecurringOperationalSignalCount": len(new_operational),
            "resolvedRecurringOperationalSignalCount": len(resolved_operational),
            "newRecurringCompilationErrors": new_compilation,
            "resolvedRecurringCompilationErrors": resolved_compilation,
            "newRecurringOperationalSignals": new_operational,
            "resolvedRecurringOperationalSignals": resolved_operational,
        },
        "queueDiagnosticsDelta": {
            "beforeStatus": before_queue_diagnostics.get("status"),
            "afterStatus": after_queue_diagnostics.get("status"),
            "beforeRecurringSignalCount": int(before_queue_diagnostics.get("recurringSignalCount") or 0),
            "afterRecurringSignalCount": int(after_queue_diagnostics.get("recurringSignalCount") or 0),
            "recurringSignalDelta": (
                int(after_queue_diagnostics.get("recurringSignalCount") or 0)
                - int(before_queue_diagnostics.get("recurringSignalCount") or 0)
            ),
            "newCount": len(new_queue_signals),
            "resolvedCount": len(resolved_queue_signals),
            "newSignals": new_queue_signals,
            "resolvedSignals": resolved_queue_signals,
        },
        "queueTrendDelta": {
            "beforeStatus": before_queue_trend.get("status"),
            "afterStatus": after_queue_trend.get("status"),
            "sampleCountDelta": (
                int(after_queue_trend.get("sampleCount") or 0)
                - int(before_queue_trend.get("sampleCount") or 0)
            ),
            "backlogSampleDelta": (
                int(after_queue_trend.get("backlogSamples") or 0)
                - int(before_queue_trend.get("backlogSamples") or 0)
            ),
            "activeSampleDelta": (
                int(after_queue_trend.get("activeSamples") or 0)
                - int(before_queue_trend.get("activeSamples") or 0)
            ),
            "peakQueuedDelta": (
                int(after_queue_trend.get("peakQueued") or 0)
                - int(before_queue_trend.get("peakQueued") or 0)
            ),
            "peakActiveAgentsDelta": (
                int(after_queue_trend.get("peakActiveAgents") or 0)
                - int(before_queue_trend.get("peakActiveAgents") or 0)
            ),
            "consecutiveBacklogDelta": (
                int(after_queue_trend.get("consecutiveBacklogSamples") or 0)
                - int(before_queue_trend.get("consecutiveBacklogSamples") or 0)
            ),
            "beforeSummary": before_queue_trend.get("summary"),
            "afterSummary": after_queue_trend.get("summary"),
        },
    }


def _format_signed_delta(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    numeric = float(value)
    if numeric > 0:
        return f"+{numeric:.1f}" if isinstance(value, float) or numeric % 1 else f"+{int(numeric)}"
    if numeric < 0:
        return f"{numeric:.1f}" if isinstance(value, float) or numeric % 1 else f"{int(numeric)}"
    return "0.0" if isinstance(value, float) else "0"


def _render_benchmark_compare_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "## Benchmark Comparison",
        "",
        f"- Before: `{payload.get('beforeLabel') or Path(str(payload.get('beforeFile') or '')).stem}`",
        f"- After: `{payload.get('afterLabel') or Path(str(payload.get('afterFile') or '')).stem}`",
        (
            f"- Overall score: `{payload.get('beforeOverallScore')} -> {payload.get('afterOverallScore')}` "
            f"(`{_format_signed_delta(payload.get('overallScoreDelta'))}`)"
        ),
        f"- New findings: {int((payload.get('findingDelta') or {}).get('newCount') or 0)}",
        f"- Resolved findings: {int((payload.get('findingDelta') or {}).get('resolvedCount') or 0)}",
        "",
        "### Top Lens Deltas",
    ]
    for lens in (payload.get("lensDeltas") or [])[:3]:
        lines.append(
            f"- `{lens.get('name')}`: `{lens.get('beforeScore')} -> {lens.get('afterScore')}` "
            f"(`{_format_signed_delta(lens.get('scoreDelta'))}`)"
        )
    diagnostics = dict(payload.get("diagnosticsDelta") or {})
    queue_diagnostics = dict(payload.get("queueDiagnosticsDelta") or {})
    queue_trend = dict(payload.get("queueTrendDelta") or {})
    lines.extend(
        [
            "",
            "### Recurring diagnostics",
            f"- New recurring compilation errors: {int(diagnostics.get('newRecurringCompilationErrorCount') or 0)}",
            f"- Resolved recurring compilation errors: {int(diagnostics.get('resolvedRecurringCompilationErrorCount') or 0)}",
            f"- New recurring operational signals: {int(diagnostics.get('newRecurringOperationalSignalCount') or 0)}",
            f"- Resolved recurring operational signals: {int(diagnostics.get('resolvedRecurringOperationalSignalCount') or 0)}",
            "",
            "### Queue health",
            (
                f"- Status: `{queue_diagnostics.get('beforeStatus')} -> "
                f"{queue_diagnostics.get('afterStatus')}`"
            ),
            (
                f"- Recurring queue signals: "
                f"`{queue_diagnostics.get('beforeRecurringSignalCount')} -> "
                f"{queue_diagnostics.get('afterRecurringSignalCount')}` "
                f"(`{_format_signed_delta(queue_diagnostics.get('recurringSignalDelta'))}`)"
            ),
            f"- New recurring queue signals: {int(queue_diagnostics.get('newCount') or 0)}",
            f"- Resolved recurring queue signals: {int(queue_diagnostics.get('resolvedCount') or 0)}",
            "",
            "### Queue trend",
            (
                f"- Trend status: `{queue_trend.get('beforeStatus')} -> "
                f"{queue_trend.get('afterStatus')}`"
            ),
            (
                f"- Sample count delta: "
                f"`{_format_signed_delta(queue_trend.get('sampleCountDelta'))}`"
            ),
            (
                f"- Backlog sample delta: "
                f"`{_format_signed_delta(queue_trend.get('backlogSampleDelta'))}`"
            ),
            (
                f"- Consecutive backlog delta: "
                f"`{_format_signed_delta(queue_trend.get('consecutiveBacklogDelta'))}`"
            ),
            (
                f"- Peak queued delta: "
                f"`{_format_signed_delta(queue_trend.get('peakQueuedDelta'))}`"
            ),
            (
                f"- Peak active agents delta: "
                f"`{_format_signed_delta(queue_trend.get('peakActiveAgentsDelta'))}`"
            ),
        ]
    )
    return "\n".join(lines)


def _render_improve_project_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "## Improve Project",
        "",
        f"- Project root: `{payload.get('projectRoot')}`",
        f"- Live Unity available: `{bool(payload.get('liveUnityAvailable'))}`",
        (
            f"- Quality score: `{payload.get('baselineScore')} -> {payload.get('finalScore')}` "
            f"(`{_format_signed_delta(payload.get('scoreDelta'))}`)"
        ),
        f"- Applied fixes: {int(payload.get('appliedCount') or 0)}",
        f"- Skipped fixes: {int(payload.get('skippedCount') or 0)}",
    ]

    applied_items = list(payload.get("applied") or [])
    if applied_items:
        lines.extend(["", "### Applied fixes"])
        for item in applied_items:
            entry = dict(item) if isinstance(item, dict) else {"summary": str(item)}
            lens = str(entry.get("lens") or "").strip()
            fix = str(entry.get("fix") or "").strip()
            summary = str(entry.get("summary") or fix or "Applied").strip()
            prefix = f"`{lens}` / `{fix}`" if lens and fix else (f"`{fix}`" if fix else None)
            lines.append(f"- {prefix}: {summary}" if prefix else f"- {summary}")

    skipped_items = list(payload.get("skipped") or [])
    if skipped_items:
        lines.extend(["", "### Skipped fixes"])
        for item in skipped_items:
            entry = dict(item) if isinstance(item, dict) else {"reason": str(item)}
            lens = str(entry.get("lens") or "").strip()
            fix = str(entry.get("fix") or "").strip()
            reason = str(entry.get("reason") or fix or "Skipped").strip()
            prefix = f"`{lens}` / `{fix}`" if lens and fix else (f"`{fix}`" if fix else None)
            lines.append(f"- {prefix}: {reason}" if prefix else f"- {reason}")

    return "\n".join(lines) + "\n"


def _collect_expert_audit_results(
    ctx: click.Context,
    *,
    resolved_project_root: str,
    workflow_port: int | None,
    inspect_payload: dict[str, Any] | None,
    requested_lenses: list[str],
    progress_template: str,
) -> list[dict[str, Any]]:
    shared_audit_report = build_asset_audit_report(
        resolved_project_root,
        inspect_payload=inspect_payload,
        recommendation_limit=8,
    )
    results: list[dict[str, Any]] = []
    for requested_lens in requested_lenses:
        lens = get_builtin_expert_lens(requested_lens)
        _record_progress_step(
            ctx,
            progress_template.format(lens=lens.name),
            phase="inspect",
            port=workflow_port,
        )
        results.append(
            _build_expert_audit_payload(
                project_root=resolved_project_root,
                inspect_payload=inspect_payload,
                lens_name=lens.name,
                audit_report=shared_audit_report,
            )
        )
    return results


def _build_quality_score_payload(
    ctx: click.Context,
    *,
    resolved_project_root: str,
    workflow_port: int | None,
    inspect_payload: dict[str, Any] | None,
    requested_lenses: list[str] | None = None,
) -> dict[str, Any]:
    selected_lenses = list(requested_lenses or [lens.name for lens in iter_builtin_expert_lenses()])
    enriched_inspect = _enrich_inspect_payload_for_lenses(
        ctx,
        workflow_port=workflow_port,
        inspect_payload=inspect_payload,
        lens_names=selected_lenses,
    )
    results = _collect_expert_audit_results(
        ctx,
        resolved_project_root=resolved_project_root,
        workflow_port=workflow_port,
        inspect_payload=enriched_inspect,
        requested_lenses=selected_lenses,
        progress_template="Scoring {lens} quality",
    )

    available_results = [item for item in results if item.get("available")]
    scored_results = [item for item in available_results if item.get("score") is not None]
    return {
        "available": True,
        "projectRoot": resolved_project_root,
        "overallScore": round(
            sum(int(item.get("score") or 0) for item in scored_results) / len(scored_results),
            1,
        )
        if scored_results
        else None,
        "lensScores": [
            {
                "name": (item.get("lens") or {}).get("name"),
                "score": item.get("score"),
                "grade": item.get("grade"),
            }
            for item in available_results
        ],
        "results": available_results,
    }


def _apply_ui_canvas_scaler_fix(
    ctx: click.Context,
    *,
    workflow_port: int | None,
    inspect_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if inspect_payload is None:
        raise ValueError(
            "Applying the ui-canvas-scaler fix needs live Unity scene context. Select a Unity editor first or pass --port."
        )

    enriched_inspect = _enrich_inspect_payload_for_lenses(
        ctx,
        workflow_port=workflow_port,
        inspect_payload=inspect_payload,
        lens_names=["ui"],
    ) or {}
    hierarchy = dict(enriched_inspect.get("hierarchy") or {})
    nodes = _iter_hierarchy_nodes(_extract_hierarchy_nodes(hierarchy))
    targets = [
        node
        for node in nodes
        if "Canvas" in set(node.get("components") or [])
        and "CanvasScaler" not in set(node.get("components") or [])
    ]

    updates: list[dict[str, Any]] = []
    for target in targets:
        gameobject_path = str(
            target.get("path")
            or target.get("hierarchyPath")
            or target.get("name")
            or ""
        ).strip()
        if not gameobject_path:
            continue
        _record_progress_step(
            ctx,
            f"Adding CanvasScaler to {target.get('name') or gameobject_path}",
            phase="edit",
            port=workflow_port,
        )
        add_result = require_workflow_success(
            ctx.obj.backend.call_route_with_recovery(
                "component/add",
                params={
                    "gameObjectPath": gameobject_path,
                    "componentType": "CanvasScaler",
                },
                port=workflow_port,
                recovery_timeout=10.0,
            ),
            f"Add CanvasScaler to {gameobject_path}",
        )
        updates.append(
            {
                "name": target.get("name"),
                "path": gameobject_path,
                "result": add_result,
            }
        )

    editor_state = require_workflow_success(
        ctx.obj.backend.call_route_with_recovery(
            "editor/state",
            port=workflow_port,
            recovery_timeout=10.0,
        ),
        "Read editor state after UI fix",
    )
    return {
        "updatedCount": len(updates),
        "targets": updates,
        "editorState": editor_state,
    }


def _apply_ui_graphic_raycaster_fix(
    ctx: click.Context,
    *,
    workflow_port: int | None,
    inspect_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if inspect_payload is None:
        raise ValueError(
            "Applying the ui-graphic-raycaster fix needs live Unity scene context. Select a Unity editor first or pass --port."
        )

    enriched_inspect = _enrich_inspect_payload_for_lenses(
        ctx,
        workflow_port=workflow_port,
        inspect_payload=inspect_payload,
        lens_names=["ui"],
    ) or {}
    hierarchy = dict(enriched_inspect.get("hierarchy") or {})
    nodes = _iter_hierarchy_nodes(_extract_hierarchy_nodes(hierarchy))
    targets = [
        node
        for node in nodes
        if "Canvas" in set(node.get("components") or [])
        and "GraphicRaycaster" not in set(node.get("components") or [])
    ]

    updates: list[dict[str, Any]] = []
    for target in targets:
        gameobject_path = str(
            target.get("path")
            or target.get("hierarchyPath")
            or target.get("name")
            or ""
        ).strip()
        if not gameobject_path:
            continue
        _record_progress_step(
            ctx,
            f"Adding GraphicRaycaster to {target.get('name') or gameobject_path}",
            phase="edit",
            port=workflow_port,
        )
        add_result = require_workflow_success(
            ctx.obj.backend.call_route_with_recovery(
                "component/add",
                params={
                    "gameObjectPath": gameobject_path,
                    "componentType": "GraphicRaycaster",
                },
                port=workflow_port,
                recovery_timeout=10.0,
            ),
            f"Add GraphicRaycaster to {gameobject_path}",
        )
        updates.append(
            {
                "name": target.get("name"),
                "path": gameobject_path,
                "result": add_result,
            }
        )

    editor_state = require_workflow_success(
        ctx.obj.backend.call_route_with_recovery(
            "editor/state",
            port=workflow_port,
            recovery_timeout=10.0,
        ),
        "Read editor state after UI fix",
    )
    return {
        "updatedCount": len(updates),
        "targets": updates,
        "editorState": editor_state,
    }


def _rank_scene_camera_node(node: dict[str, Any]) -> tuple[int, int, str]:
    path = str(
        node.get("path")
        or node.get("hierarchyPath")
        or node.get("name")
        or ""
    ).strip()
    normalized = path.lower()
    priority = 2
    if "main camera" in normalized:
        priority = 0
    elif "camera" in normalized:
        priority = 1
    return (priority, len(normalized), normalized)


def _rank_likely_player_node(node: dict[str, Any]) -> tuple[int, int, str]:
    path = str(
        node.get("path")
        or node.get("hierarchyPath")
        or node.get("name")
        or ""
    ).strip()
    normalized = path.lower()
    priority = 2
    if normalized == "player" or normalized.endswith("/player"):
        priority = 0
    elif "player" in normalized:
        priority = 1
    return (priority, len(normalized), normalized)


def _looks_disposable_scene_object(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lower()
    return any(token in normalized for token in ("probe", "fixture", "temp", "debug", "standalone"))


def _rank_scene_event_system_node(node: dict[str, Any]) -> tuple[int, int, str]:
    path = str(
        node.get("path")
        or node.get("hierarchyPath")
        or node.get("name")
        or ""
    ).strip()
    normalized = path.lower()
    priority = 1
    if normalized == "eventsystem" or normalized.endswith("/eventsystem"):
        priority = 0
    return (priority, len(normalized), normalized)


def _apply_systems_audio_listener_fix(
    ctx: click.Context,
    *,
    workflow_port: int | None,
    inspect_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if inspect_payload is None:
        raise ValueError(
            "Applying the audio-listener fix needs live Unity scene context. Select a Unity editor first or pass --port."
        )

    enriched_inspect = _enrich_inspect_payload_for_lenses(
        ctx,
        workflow_port=workflow_port,
        inspect_payload=inspect_payload,
        lens_names=["systems"],
    ) or {}
    hierarchy = dict(enriched_inspect.get("hierarchy") or {})
    nodes = _iter_hierarchy_nodes(_extract_hierarchy_nodes(hierarchy))

    camera_nodes = [node for node in nodes if "Camera" in set(node.get("components") or [])]
    listener_nodes = [node for node in nodes if "AudioListener" in set(node.get("components") or [])]

    if not camera_nodes and not listener_nodes:
        return {
            "updatedCount": 0,
            "keptPath": None,
            "addedCount": 0,
            "removedCount": 0,
            "removedPaths": [],
            "reason": "No Camera or AudioListener components were found in the inspected scene.",
        }

    if not listener_nodes:
        keep_node = sorted(camera_nodes, key=_rank_scene_camera_node)[0]
        keep_path = str(
            keep_node.get("path")
            or keep_node.get("hierarchyPath")
            or keep_node.get("name")
            or ""
        ).strip()
        _record_progress_step(
            ctx,
            f"Adding AudioListener to {keep_node.get('name') or keep_path}",
            phase="edit",
            port=workflow_port,
        )
        add_result = require_workflow_success(
            ctx.obj.backend.call_route_with_recovery(
                "component/add",
                params={
                    "gameObjectPath": keep_path,
                    "componentType": "AudioListener",
                },
                port=workflow_port,
                recovery_timeout=10.0,
            ),
            f"Add AudioListener to {keep_path}",
        )
        editor_state = require_workflow_success(
            ctx.obj.backend.call_route_with_recovery(
                "editor/state",
                port=workflow_port,
                recovery_timeout=10.0,
            ),
            "Read editor state after audio fix",
        )
        return {
            "updatedCount": 1,
            "keptPath": keep_path,
            "addedCount": 1,
            "removedCount": 0,
            "removedPaths": [],
            "result": add_result,
            "editorState": editor_state,
        }

    if len(listener_nodes) == 1:
        keep_node = listener_nodes[0]
        keep_path = str(
            keep_node.get("path")
            or keep_node.get("hierarchyPath")
            or keep_node.get("name")
            or ""
        ).strip()
        return {
            "updatedCount": 0,
            "keptPath": keep_path or None,
            "addedCount": 0,
            "removedCount": 0,
            "removedPaths": [],
            "reason": "Exactly one AudioListener is already present in the inspected scene.",
        }

    keep_node = sorted(listener_nodes, key=_rank_scene_camera_node)[0]
    keep_path = str(
        keep_node.get("path")
        or keep_node.get("hierarchyPath")
        or keep_node.get("name")
        or ""
    ).strip()
    removed: list[dict[str, Any]] = []
    for node in listener_nodes:
        gameobject_path = str(
            node.get("path")
            or node.get("hierarchyPath")
            or node.get("name")
            or ""
        ).strip()
        if not gameobject_path or gameobject_path == keep_path:
            continue
        _record_progress_step(
            ctx,
            f"Removing extra AudioListener from {node.get('name') or gameobject_path}",
            phase="edit",
            port=workflow_port,
        )
        remove_result = require_workflow_success(
            ctx.obj.backend.call_route_with_recovery(
                "component/remove",
                params={
                    "gameObjectPath": gameobject_path,
                    "component": "AudioListener",
                },
                port=workflow_port,
                recovery_timeout=10.0,
            ),
            f"Remove AudioListener from {gameobject_path}",
        )
        removed.append(
            {
                "name": node.get("name"),
                "path": gameobject_path,
                "result": remove_result,
            }
        )

    editor_state = require_workflow_success(
        ctx.obj.backend.call_route_with_recovery(
            "editor/state",
            port=workflow_port,
            recovery_timeout=10.0,
        ),
        "Read editor state after audio fix",
    )
    return {
        "updatedCount": len(removed),
        "keptPath": keep_path,
        "addedCount": 0,
        "removedCount": len(removed),
        "removedPaths": [item["path"] for item in removed],
        "removed": removed,
        "editorState": editor_state,
    }


def _apply_systems_disposable_cleanup_fix(
    ctx: click.Context,
    *,
    workflow_port: int | None,
    inspect_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if inspect_payload is None:
        raise ValueError(
            "Applying the disposable-cleanup fix needs live Unity scene context. Select a Unity editor first or pass --port."
        )

    enriched_inspect = _enrich_inspect_payload_for_lenses(
        ctx,
        workflow_port=workflow_port,
        inspect_payload=inspect_payload,
        lens_names=["systems"],
    ) or {}
    hierarchy = dict(enriched_inspect.get("hierarchy") or {})
    nodes = _iter_hierarchy_nodes(_extract_hierarchy_nodes(hierarchy))

    disposable_paths: list[str] = []
    seen_paths: set[str] = set()
    for node in nodes:
        gameobject_path = str(
            node.get("path")
            or node.get("hierarchyPath")
            or node.get("name")
            or ""
        ).strip()
        if not gameobject_path or gameobject_path in seen_paths:
            continue
        if not _looks_disposable_scene_object(gameobject_path):
            continue
        seen_paths.add(gameobject_path)
        disposable_paths.append(gameobject_path)

    if not disposable_paths:
        return {
            "updatedCount": 0,
            "removedCount": 0,
            "removedPaths": [],
            "reason": "No disposable probe or demo objects were found in the inspected scene.",
        }

    removed: list[dict[str, Any]] = []
    for gameobject_path in disposable_paths:
        _record_progress_step(
            ctx,
            f"Deleting disposable object {gameobject_path}",
            phase="edit",
            port=workflow_port,
        )
        remove_result = require_workflow_success(
            ctx.obj.backend.call_route_with_recovery(
                "gameobject/delete",
                params={
                    "gameObjectPath": gameobject_path,
                    "path": gameobject_path,
                },
                port=workflow_port,
                recovery_timeout=10.0,
            ),
            f"Delete disposable object {gameobject_path}",
        )
        removed.append(
            {
                "path": gameobject_path,
                "result": remove_result,
            }
        )

    editor_state = require_workflow_success(
        ctx.obj.backend.call_route_with_recovery(
            "editor/state",
            port=workflow_port,
            recovery_timeout=10.0,
        ),
        "Read editor state after disposable cleanup",
    )
    return {
        "updatedCount": len(removed),
        "removedCount": len(removed),
        "removedPaths": [item["path"] for item in removed],
        "removed": removed,
        "editorState": editor_state,
    }


def _apply_physics_player_character_controller_fix(
    ctx: click.Context,
    *,
    workflow_port: int | None,
    inspect_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if inspect_payload is None:
        raise ValueError(
            "Applying the player-character-controller fix needs live Unity scene context. Select a Unity editor first or pass --port."
        )

    enriched_inspect = _enrich_inspect_payload_for_lenses(
        ctx,
        workflow_port=workflow_port,
        inspect_payload=inspect_payload,
        lens_names=["physics"],
    ) or {}
    hierarchy = dict(enriched_inspect.get("hierarchy") or {})
    nodes = _iter_hierarchy_nodes(_extract_hierarchy_nodes(hierarchy))

    candidate_nodes = []
    for node in nodes:
        path = str(
            node.get("path")
            or node.get("hierarchyPath")
            or node.get("name")
            or ""
        ).strip()
        if not path:
            continue
        normalized = path.lower()
        components = set(node.get("components") or [])
        looks_like_player = any(token in normalized for token in ("player", "hero", "avatar", "character", "pawn"))
        if not looks_like_player:
            continue
        if "CharacterController" in components or "Rigidbody" in components or "Rigidbody2D" in components:
            continue
        candidate_nodes.append(node)

    if not candidate_nodes:
        return {
            "updatedCount": 0,
            "targetPath": None,
            "reason": "No likely player object without an existing Rigidbody or CharacterController was found.",
        }

    if len(candidate_nodes) > 1:
        candidate_paths = [
            str(node.get("path") or node.get("hierarchyPath") or node.get("name") or "").strip()
            for node in sorted(candidate_nodes, key=_rank_likely_player_node)
            if str(node.get("path") or node.get("hierarchyPath") or node.get("name") or "").strip()
        ]
        return {
            "updatedCount": 0,
            "targetPath": None,
            "candidateCount": len(candidate_paths),
            "candidatePaths": candidate_paths[:6],
            "reason": "Multiple likely player objects were found, so the bounded CharacterController fix refused to guess.",
        }

    target = candidate_nodes[0]
    target_path = str(
        target.get("path")
        or target.get("hierarchyPath")
        or target.get("name")
        or ""
    ).strip()
    _record_progress_step(
        ctx,
        f"Adding CharacterController to {target.get('name') or target_path}",
        phase="edit",
        port=workflow_port,
    )
    add_result = require_workflow_success(
        ctx.obj.backend.call_route_with_recovery(
            "component/add",
            params={
                "gameObjectPath": target_path,
                "componentType": "CharacterController",
            },
            port=workflow_port,
            recovery_timeout=10.0,
        ),
        f"Add CharacterController to {target_path}",
    )
    editor_state = require_workflow_success(
        ctx.obj.backend.call_route_with_recovery(
            "editor/state",
            port=workflow_port,
            recovery_timeout=10.0,
        ),
        "Read editor state after physics fix",
    )
    return {
        "updatedCount": 1,
        "targetPath": target_path,
        "result": add_result,
        "editorState": editor_state,
    }


def _apply_systems_event_system_fix(
    ctx: click.Context,
    *,
    workflow_port: int | None,
    inspect_payload: dict[str, Any] | None,
    audit_report: dict[str, Any] | None,
) -> dict[str, Any]:
    if inspect_payload is None:
        raise ValueError(
            "Applying the event-system fix needs live Unity scene context. Select a Unity editor first or pass --port."
        )

    enriched_inspect = _enrich_inspect_payload_for_lenses(
        ctx,
        workflow_port=workflow_port,
        inspect_payload=inspect_payload,
        lens_names=["systems"],
    ) or {}
    hierarchy = dict(enriched_inspect.get("hierarchy") or {})
    nodes = _iter_hierarchy_nodes(_extract_hierarchy_nodes(hierarchy))

    canvas_nodes = [
        node for node in nodes if "Canvas" in set(node.get("components") or [])
    ]
    if not canvas_nodes:
        return {
            "updatedCount": 0,
            "createdObject": False,
            "gameObjectPath": None,
            "moduleType": None,
            "reason": "No Canvas components were found in the inspected scene.",
        }

    module_type = choose_event_system_module(audit_report=audit_report)
    existing_event_system = next(
        (
            node for node in nodes
            if "EventSystem" in set(node.get("components") or [])
        ),
        None,
    )
    event_system_nodes = [
        node for node in nodes if "EventSystem" in set(node.get("components") or [])
    ]
    if existing_event_system is not None and event_system_nodes:
        keep_node = sorted(event_system_nodes, key=_rank_scene_event_system_node)[0]
        gameobject_path = str(
            keep_node.get("path")
            or keep_node.get("hierarchyPath")
            or keep_node.get("name")
            or ""
        ).strip()
        existing_components = set(keep_node.get("components") or [])
        component_results: list[dict[str, Any]] = []
        removable_modules = {"StandaloneInputModule", "InputSystemUIInputModule"}
        primary_removed_components: list[str] = []
        for component_type in sorted((removable_modules - {module_type}) & existing_components):
            _record_progress_step(
                ctx,
                f"Removing {component_type} from {gameobject_path}",
                phase="edit",
                port=workflow_port,
            )
            component_results.append(
                require_workflow_success(
                    ctx.obj.backend.call_route_with_recovery(
                        "component/remove",
                        params={
                            "gameObjectPath": gameobject_path,
                            "component": component_type,
                        },
                        port=workflow_port,
                        recovery_timeout=10.0,
                    ),
                    f"Remove {component_type} from {gameobject_path}",
                )
            )
            primary_removed_components.append(component_type)

        if module_type not in existing_components:
            _record_progress_step(
                ctx,
                f"Adding {module_type} to {gameobject_path}",
                phase="edit",
                port=workflow_port,
            )
            component_results.append(
                require_workflow_success(
                    ctx.obj.backend.call_route_with_recovery(
                        "component/add",
                        params={
                            "gameObjectPath": gameobject_path,
                            "componentType": module_type,
                        },
                        port=workflow_port,
                        recovery_timeout=10.0,
                    ),
                    f"Add {module_type} to {gameobject_path}",
                )
            )

        duplicate_paths: list[str] = []
        for node in event_system_nodes:
            target_path = str(
                node.get("path")
                or node.get("hierarchyPath")
                or node.get("name")
                or ""
            ).strip()
            if not target_path or target_path == gameobject_path:
                continue
            target_components = set(node.get("components") or [])
            removed_any = False
            for component_type in sorted({"EventSystem", *removable_modules} & target_components):
                _record_progress_step(
                    ctx,
                    f"Removing {component_type} from {target_path}",
                    phase="edit",
                    port=workflow_port,
                )
                component_results.append(
                    require_workflow_success(
                        ctx.obj.backend.call_route_with_recovery(
                            "component/remove",
                            params={
                                "gameObjectPath": target_path,
                                "component": component_type,
                            },
                            port=workflow_port,
                            recovery_timeout=10.0,
                        ),
                        f"Remove {component_type} from {target_path}",
                    )
                )
                removed_any = True
            if removed_any:
                duplicate_paths.append(target_path)

        updated_count = len(duplicate_paths) + (1 if (primary_removed_components or module_type not in existing_components) else 0)
        if updated_count == 0:
            return {
                "updatedCount": 0,
                "createdObject": False,
                "gameObjectPath": gameobject_path or None,
                "moduleType": module_type,
                "reason": "An EventSystem component already exists in the inspected scene.",
            }

        editor_state = require_workflow_success(
            ctx.obj.backend.call_route_with_recovery(
                "editor/state",
                port=workflow_port,
                recovery_timeout=10.0,
            ),
            "Read editor state after systems fix",
        )
        components_added = [module_type] if module_type not in existing_components else []
        return {
            "updatedCount": updated_count,
            "createdObject": False,
            "gameObjectPath": gameobject_path or None,
            "moduleType": module_type,
            "componentsAdded": components_added,
            "componentResults": component_results,
            "duplicateRemovedCount": len(duplicate_paths),
            "duplicatePaths": duplicate_paths,
            "primaryRemovedComponents": primary_removed_components,
            "editorState": editor_state,
        }

    target_node = next(
        (
            node for node in nodes
            if str(node.get("name") or "").strip() == "EventSystem"
        ),
        None,
    )
    created_object = False
    if target_node is None:
        _record_progress_step(
            ctx,
            "Creating EventSystem GameObject",
            phase="edit",
            port=workflow_port,
        )
        create_result = require_workflow_success(
            ctx.obj.backend.call_route_with_recovery(
                "gameobject/create",
                params={"name": "EventSystem", "primitiveType": "Empty"},
                port=workflow_port,
                recovery_timeout=10.0,
            ),
            "Create EventSystem GameObject",
        )
        gameobject_path = str(create_result.get("name") or "EventSystem").strip() or "EventSystem"
        created_object = True
    else:
        gameobject_path = str(
            target_node.get("path")
            or target_node.get("hierarchyPath")
            or target_node.get("name")
            or ""
        ).strip()
        if not gameobject_path:
            raise ValueError("Unable to resolve the existing EventSystem GameObject path.")

    component_results: list[dict[str, Any]] = []
    for component_type in ("EventSystem", module_type):
        _record_progress_step(
            ctx,
            f"Adding {component_type} to {gameobject_path}",
            phase="edit",
            port=workflow_port,
        )
        component_results.append(
            require_workflow_success(
                ctx.obj.backend.call_route_with_recovery(
                    "component/add",
                    params={
                        "gameObjectPath": gameobject_path,
                        "componentType": component_type,
                    },
                    port=workflow_port,
                    recovery_timeout=10.0,
                ),
                f"Add {component_type} to {gameobject_path}",
            )
        )

    editor_state = require_workflow_success(
        ctx.obj.backend.call_route_with_recovery(
            "editor/state",
            port=workflow_port,
            recovery_timeout=10.0,
        ),
        "Read editor state after systems fix",
    )
    return {
        "updatedCount": 1,
        "createdObject": created_object,
        "gameObjectPath": gameobject_path,
        "moduleType": module_type,
        "componentsAdded": ["EventSystem", module_type],
        "componentResults": component_results,
        "editorState": editor_state,
    }


def _render_editmode_smoke_test(*, class_name: str, project_name: str) -> str:
    return (
        "using NUnit.Framework;\n"
        "using UnityEngine.SceneManagement;\n\n"
        f"public class {class_name}\n"
        "{\n"
        "    [Test]\n"
        "    public void ActiveSceneHasAStableIdentity()\n"
        "    {\n"
        "        var scene = SceneManager.GetActiveScene();\n"
        "        Assert.IsFalse(string.IsNullOrWhiteSpace(scene.name), \"Active scene should have a name.\");\n"
        "        Assert.IsTrue(\n"
        "            string.IsNullOrWhiteSpace(scene.path) || scene.path.EndsWith(\".unity\"),\n"
        "            \"Active scene path should be empty or point to a Unity scene asset.\"\n"
        "        );\n"
        f"        TestContext.WriteLine(\"{project_name} smoke test checked scene: \" + scene.name);\n"
        "    }\n"
        "}\n"
    )


def _render_editmode_test_asmdef(*, assembly_name: str) -> str:
    return json.dumps(
        {
            "name": assembly_name,
            "references": [],
            "includePlatforms": ["Editor"],
            "excludePlatforms": [],
            "allowUnsafeCode": False,
            "overrideReferences": False,
            "precompiledReferences": [],
            "autoReferenced": True,
            "defineConstraints": [],
            "versionDefines": [],
            "noEngineReferences": False,
            "optionalUnityReferences": ["TestAssemblies"],
        },
        indent=2,
    ) + "\n"


def _apply_director_test_scaffold_fix(
    *,
    resolved_project_root: str,
    overwrite: bool,
    audit_report: dict[str, Any] | None,
) -> dict[str, Any]:
    packages = {
        str(package).strip().lower()
        for package in (((audit_report or {}).get("assetScan") or {}).get("packages") or [])
        if str(package).strip()
    }
    manifest_path = Path(resolved_project_root) / "Packages" / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
            dependencies = manifest.get("dependencies") or {}
            if isinstance(dependencies, dict):
                packages.update(
                    str(name).strip().lower()
                    for name in dependencies.keys()
                    if str(name).strip()
                )
        except json.JSONDecodeError:
            pass
    if "com.unity.test-framework" not in packages:
        raise ValueError(
            "Applying the test-scaffold fix requires com.unity.test-framework in Packages/manifest.json."
        )

    spec = build_test_scaffold_spec(
        context={
            "project": {
                "path": resolved_project_root,
                "name": Path(resolved_project_root).name,
            }
        }
    )
    project_root = Path(resolved_project_root)
    script_path = project_root / Path(spec["scriptPath"])
    asmdef_path = project_root / Path(spec["asmdefPath"])
    script_path.parent.mkdir(parents=True, exist_ok=True)

    files_to_write = [
        (
            script_path,
            _render_editmode_smoke_test(
                class_name=spec["className"],
                project_name=spec["projectName"],
            ),
            "script",
        ),
        (
            asmdef_path,
            _render_editmode_test_asmdef(assembly_name=spec["assemblyName"]),
            "asmdef",
        ),
    ]

    writes: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for path, content, kind in files_to_write:
        if path.exists() and not overwrite:
            skipped.append({"path": str(path), "kind": kind, "reason": "exists"})
            continue
        path.write_text(content, encoding="utf-8")
        writes.append({"path": str(path), "kind": kind, "chars": len(content)})

    return {
        "writeCount": len(writes),
        "skipCount": len(skipped),
        "writes": writes,
        "skipped": skipped,
        "scriptPath": str(script_path),
        "asmdefPath": str(asmdef_path),
        "className": spec["className"],
        "assemblyName": spec["assemblyName"],
    }


def _apply_texture_import_fix(
    ctx: click.Context,
    *,
    workflow_port: int | None,
    audit_report: dict[str, Any] | None,
) -> dict[str, Any]:
    importer_audit = dict((((audit_report or {}).get("assetScan") or {}).get("importerAudit") or {}))
    samples = dict(importer_audit.get("samples") or {})
    normal_targets = [str(path) for path in (samples.get("potentialNormalMapMisconfigured") or []) if str(path).strip()]
    sprite_targets = [str(path) for path in (samples.get("potentialSpriteMisconfigured") or []) if str(path).strip()]

    updates: list[dict[str, Any]] = []
    for path in normal_targets:
        _record_progress_step(
            ctx,
            f"Marking {Path(path).name} as Normal Map",
            phase="edit",
            port=workflow_port,
        )
        result = require_workflow_success(
            ctx.obj.backend.call_route_with_recovery(
                "texture/set-normalmap",
                params={"path": path},
                port=workflow_port,
                recovery_timeout=10.0,
            ),
            f"Set normal map import for {path}",
        )
        updates.append({"path": path, "targetType": "NormalMap", "result": result})

    for path in sprite_targets:
        _record_progress_step(
            ctx,
            f"Marking {Path(path).name} as Sprite",
            phase="edit",
            port=workflow_port,
        )
        result = require_workflow_success(
            ctx.obj.backend.call_route_with_recovery(
                "texture/set-sprite",
                params={"path": path},
                port=workflow_port,
                recovery_timeout=10.0,
            ),
            f"Set sprite import for {path}",
        )
        updates.append({"path": path, "targetType": "Sprite", "result": result})

    return {
        "updatedCount": len(updates),
        "normalMapCount": len(normal_targets),
        "spriteCount": len(sprite_targets),
        "targets": updates,
    }


def _apply_animation_controller_scaffold_fix(
    ctx: click.Context,
    *,
    workflow_port: int | None,
    controller_path: str,
) -> dict[str, Any]:
    normalized_path = str(controller_path or "").strip().replace("\\", "/")
    if not normalized_path:
        raise ValueError("Animation controller scaffold fix needs a target controller path.")
    if not normalized_path.startswith("Assets/"):
        raise ValueError("Animation controller scaffold path must live under Assets/.")

    _record_progress_step(
        ctx,
        f"Creating Animator Controller {Path(normalized_path).name}",
        phase="edit",
        port=workflow_port,
    )
    create_result = require_workflow_success(
        ctx.obj.backend.call_route_with_recovery(
            "animation/create-controller",
            params={"path": normalized_path},
            port=workflow_port,
            recovery_timeout=10.0,
        ),
        f"Create Animator Controller at {normalized_path}",
    )
    return {
        "path": normalized_path,
        "result": create_result,
    }


def _apply_animation_controller_wireup_fix(
    ctx: click.Context,
    *,
    workflow_port: int | None,
    controller_path: str,
    target_gameobject_path: str,
) -> dict[str, Any]:
    normalized_target = str(target_gameobject_path or "").strip()
    if not normalized_target:
        raise ValueError("Animation controller wireup needs a target Animator path.")

    scaffold_payload = _apply_animation_controller_scaffold_fix(
        ctx,
        workflow_port=workflow_port,
        controller_path=controller_path,
    )
    normalized_path = str(scaffold_payload.get("path") or "").strip().replace("\\", "/")

    _record_progress_step(
        ctx,
        f"Assigning Animator Controller to {normalized_target}",
        phase="edit",
        port=workflow_port,
    )
    assign_result = require_workflow_success(
        ctx.obj.backend.call_route_with_recovery(
            "animation/assign-controller",
            params={
                "path": normalized_target,
                "gameObjectPath": normalized_target,
                "controllerPath": normalized_path,
            },
            port=workflow_port,
            recovery_timeout=10.0,
        ),
        f"Assign Animator Controller to {normalized_target}",
    )
    return {
        "controllerPath": normalized_path,
        "targetGameObjectPath": normalized_target,
        "scaffold": scaffold_payload.get("result"),
        "assignment": assign_result,
    }


def _create_sandbox_scene_payload(
    ctx: click.Context,
    *,
    workflow_port: int | None,
    name: str | None,
    folder: str,
    open_scene: bool,
    save_if_dirty: bool,
    discard_unsaved: bool,
) -> dict[str, Any]:
    if save_if_dirty and discard_unsaved:
        raise ValueError("Choose either --save-if-dirty or --discard-unsaved, not both.")

    normalized_folder = _normalize_sandbox_folder(folder)
    params: dict[str, Any] = {
        "folder": normalized_folder,
        "open": open_scene,
        "saveIfDirty": save_if_dirty,
        "discardUnsaved": discard_unsaved,
    }
    if name:
        params["name"] = name

    _record_progress_step(
        ctx,
        f"Creating sandbox scene in {normalized_folder}",
        phase="create",
        port=workflow_port,
    )
    route_result = ctx.obj.backend.call_route(
        "scene/create-sandbox",
        params=params,
        port=workflow_port,
    )
    route_error = workflow_error_message(route_result)
    if _is_missing_route_error(route_error):
        _record_progress_step(
            ctx,
            "Falling back to execute-code for sandbox scene creation",
            phase="create",
            port=workflow_port,
        )
        execute_result = ctx.obj.backend.call_route_with_recovery(
            "editor/execute-code",
            params={
                "code": _build_create_sandbox_execute_code(
                    name=name,
                    folder=normalized_folder,
                    open_scene=open_scene,
                    save_if_dirty=save_if_dirty,
                    discard_unsaved=discard_unsaved,
                )
            },
            port=workflow_port,
            recovery_timeout=10.0,
        )
        route_result = _unwrap_execute_code_result(execute_result)

    payload = require_workflow_success(route_result, "Create sandbox scene")
    _record_progress_step(
        ctx,
        f"Inspecting sandbox scene {payload.get('sceneName') or payload.get('path')}",
        phase="inspect",
        port=workflow_port,
    )
    payload["editorState"] = require_workflow_success(
        ctx.obj.backend.call_route_with_recovery(
            "editor/state",
            port=workflow_port,
            recovery_timeout=10.0,
        ),
        "Read editor state after sandbox creation",
    )
    return payload


