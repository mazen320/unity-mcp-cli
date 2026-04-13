from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

import click

from ..core.expert_context import build_expert_context
from ..core.expert_fixes import (
    build_quality_fix_plan,
    build_test_scaffold_spec,
    choose_event_system_module,
)
from ..core.expert_lenses import grade_score, get_builtin_expert_lens, iter_builtin_expert_lenses
from ..core.project_guidance import build_guidance_bundle, write_guidance_bundle
from ..core.project_insights import build_asset_audit_report, build_project_insights
from ..core.memory import ProjectMemory, memory_for_session
from ._shared import (
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


@click.group("workflow")
def workflow_group() -> None:
    """High-level workflows that combine multiple Unity bridge actions safely."""


# Register agent-loop command
from .agent_loop_cmd import agent_loop_command as _agent_loop_cmd  # noqa: E402
from .agent_chat_cmd import agent_chat_command as _agent_chat_cmd  # noqa: E402
workflow_group.add_command(_agent_loop_cmd)
workflow_group.add_command(_agent_chat_cmd)


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


def _build_expert_audit_payload(
    *,
    project_root: str,
    inspect_payload: dict[str, Any] | None,
    lens_name: str,
) -> dict[str, Any]:
    audit_report = build_asset_audit_report(
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


def _collect_expert_audit_results(
    ctx: click.Context,
    *,
    resolved_project_root: str,
    workflow_port: int | None,
    inspect_payload: dict[str, Any] | None,
    requested_lenses: list[str],
    progress_template: str,
) -> list[dict[str, Any]]:
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
            )
        )
    return results


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


@workflow_group.command("inspect")
@click.option("--hierarchy-depth", type=int, default=2, show_default=True, help="Hierarchy depth for the snapshot.")
@click.option("--hierarchy-nodes", type=int, default=40, show_default=True, help="Maximum hierarchy nodes to include.")
@click.option("--asset-folder", type=str, default="Assets", show_default=True, help="Folder to sample assets from.")
@click.option("--asset-limit", type=int, default=20, show_default=True, help="Maximum number of assets to sample.")
@click.option("--asset-search", type=str, default=None, help="Optional asset search text.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_inspect_command(
    ctx: click.Context,
    hierarchy_depth: int,
    hierarchy_nodes: int,
    asset_folder: str,
    asset_limit: int,
    asset_search: str | None,
    port: int | None,
) -> None:
    """Collect a high-level snapshot of the active Unity project and scene."""

    def _callback() -> dict[str, Any]:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        _record_progress_step(ctx, "Checking Unity bridge ping", phase="check", port=workflow_port)
        ping = ctx.obj.backend.ping(port=workflow_port)
        _record_progress_step(ctx, "Checking project info", phase="inspect", port=workflow_port)
        project = ctx.obj.backend.call_route_with_recovery(
            "project/info",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        _record_progress_step(ctx, "Checking editor state", phase="check", port=workflow_port)
        state = ctx.obj.backend.call_route_with_recovery(
            "editor/state",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        _record_progress_step(ctx, "Inspecting active scene info", phase="inspect", port=workflow_port)
        scene = ctx.obj.backend.call_route_with_recovery(
            "scene/info",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        _record_progress_step(
            ctx,
            f"Inspecting scene hierarchy (depth {hierarchy_depth}, max {hierarchy_nodes} nodes)",
            phase="inspect",
            port=workflow_port,
        )
        hierarchy = ctx.obj.backend.call_route_with_recovery(
            "scene/hierarchy",
            params={"maxDepth": hierarchy_depth, "maxNodes": hierarchy_nodes},
            port=workflow_port,
            recovery_timeout=10.0,
        )

        asset_params: dict[str, Any] = {
            "folder": asset_folder,
            "recursive": True,
        }
        if asset_search:
            asset_params["search"] = asset_search
        asset_step = f"Listing assets in {asset_folder}"
        if asset_search:
            asset_step += f" matching '{asset_search}'"
        _record_progress_step(ctx, asset_step, phase="inspect", port=workflow_port)
        assets = ctx.obj.backend.call_route_with_recovery(
            "asset/list",
            params=asset_params,
            port=workflow_port,
            recovery_timeout=10.0,
        )
        asset_items = list((assets or {}).get("assets") or [])[:asset_limit]

        active_scene_name = scene.get("activeScene")
        scene_dirty = bool(state.get("sceneDirty"))
        if not scene_dirty:
            for entry in scene.get("scenes") or []:
                if isinstance(entry, dict) and entry.get("name") == active_scene_name:
                    scene_dirty = bool(entry.get("isDirty"))
                    break

        summary = {
            "projectName": ping.get("projectName") or project.get("projectName"),
            "projectPath": ping.get("projectPath") or state.get("projectPath"),
            "unityVersion": ping.get("unityVersion"),
            "port": ping.get("port"),
            "activeScene": active_scene_name or state.get("activeScene"),
            "sceneDirty": scene_dirty,
            "isPlaying": bool(state.get("isPlaying")),
            "isCompiling": bool((project or {}).get("isCompiling")),
            "returnedHierarchyNodes": hierarchy.get("returnedNodes"),
            "sampledAssetCount": len(asset_items),
        }

        result = {
            "summary": summary,
            "ping": ping,
            "project": project,
            "editorState": state,
            "scene": scene,
            "hierarchy": hierarchy,
            "assets": {
                "folder": asset_folder,
                "search": asset_search,
                "count": assets.get("count"),
                "sampled": asset_items,
            },
        }
        project_root = summary.get("projectPath") or ping.get("projectPath") or project.get("projectPath")
        if project_root:
            insights = build_project_insights(project_root, inspect_payload=result)
            result["projectInsights"] = insights
            summary["hasProjectGuidance"] = bool((insights.get("guidance") or {}).get("found"))
            summary["improvementSuggestionCount"] = len(insights.get("recommendations") or [])
        else:
            result["projectInsights"] = {
                "available": False,
                "error": "Project path is unavailable for local project analysis.",
            }
        _learn_from_inspect(ctx, result)
        return result

    _run_and_emit(ctx, _callback)


@workflow_group.command("asset-audit")
@click.argument("project_root", required=False)
@click.option(
    "--top-recommendations",
    type=click.IntRange(1, None),
    default=6,
    show_default=True,
    help="Maximum number of top recommendations to highlight in the summary block.",
)
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_asset_audit_command(
    ctx: click.Context,
    project_root: str | None,
    top_recommendations: int,
    port: int | None,
) -> None:
    """Audit a Unity project's asset layout, importer hints, and likely improvement areas."""

    if project_root:
        ctx.meta["disable_auto_breadcrumbs"] = True

    def _callback() -> dict[str, Any]:
        workflow_port = port
        ping: dict[str, Any] | None = None
        project: dict[str, Any] | None = None
        editor_state: dict[str, Any] | None = None
        inspect_payload: dict[str, Any] | None = None

        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        resolved_project_root = project_root
        if not resolved_project_root:
            _record_progress_step(ctx, "Checking project context for asset audit", phase="check", port=workflow_port)
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
                },
                "project": project,
                "ping": ping,
            }

        if not resolved_project_root:
            raise ValueError(
                "Asset audit needs a Unity project path. Pass PROJECT_ROOT explicitly or select a Unity editor first."
            )

        _record_progress_step(
            ctx,
            f"Auditing assets in {Path(resolved_project_root).name}",
            phase="inspect",
            port=workflow_port,
        )
        report = build_asset_audit_report(
            resolved_project_root,
            inspect_payload=inspect_payload,
            recommendation_limit=top_recommendations,
        )
        if ping or project or editor_state:
            report["unityContext"] = {
                "ping": ping or {},
                "project": project or {},
                "editorState": editor_state or {},
            }
        return report

    _run_and_emit(ctx, _callback)


@workflow_group.command("expert-audit")
@click.argument("project_root", required=False)
@click.option("--lens", "lens_name", required=True, type=str, help="Expert lens to run.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_expert_audit_command(
    ctx: click.Context,
    project_root: str | None,
    lens_name: str,
    port: int | None,
) -> None:
    """Run a specialist Unity quality audit using one expert lens."""

    if project_root:
        ctx.meta["disable_auto_breadcrumbs"] = True

    def _callback() -> dict[str, Any]:
        resolved_project_root, workflow_port, inspect_payload, ping, project, editor_state = _resolve_workflow_project_context(
            ctx,
            project_root=project_root,
            port=port,
            progress_label="Checking project context for expert audit",
        )
        lens = get_builtin_expert_lens(lens_name)
        inspect_payload = _enrich_inspect_payload_for_lenses(
            ctx,
            workflow_port=workflow_port,
            inspect_payload=inspect_payload,
            lens_names=[lens.name],
        )
        _record_progress_step(
            ctx,
            f"Running {lens.name} expert audit for {Path(resolved_project_root).name}",
            phase="inspect",
            port=workflow_port,
        )
        payload = _build_expert_audit_payload(
            project_root=resolved_project_root,
            inspect_payload=inspect_payload,
            lens_name=lens.name,
        )
        if ping or project or editor_state:
            payload["unityContext"] = {
                "ping": ping or {},
                "project": project or {},
                "editorState": editor_state or {},
            }
        return payload

    _run_and_emit(ctx, _callback)


@workflow_group.command("scene-critique")
@click.argument("project_root", required=False)
@click.option(
    "--lens",
    "lens_names",
    multiple=True,
    help="Optional expert lens override. Defaults to director, ui, and level-art.",
)
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_scene_critique_command(
    ctx: click.Context,
    project_root: str | None,
    lens_names: tuple[str, ...],
    port: int | None,
) -> None:
    """Run a scene-facing critique across the high-signal content lenses."""

    if project_root:
        ctx.meta["disable_auto_breadcrumbs"] = True

    def _callback() -> dict[str, Any]:
        resolved_project_root, workflow_port, inspect_payload, ping, project, editor_state = _resolve_workflow_project_context(
            ctx,
            project_root=project_root,
            port=port,
            progress_label="Checking project context for scene critique",
        )
        requested_lenses = list(lens_names) or ["director", "ui", "level-art"]
        inspect_payload = _enrich_inspect_payload_for_lenses(
            ctx,
            workflow_port=workflow_port,
            inspect_payload=inspect_payload,
            lens_names=requested_lenses,
        )
        critiques: list[dict[str, Any]] = []
        for requested_lens in requested_lenses:
            lens = get_builtin_expert_lens(requested_lens)
            _record_progress_step(
                ctx,
                f"Running {lens.name} scene critique",
                phase="inspect",
                port=workflow_port,
            )
            critiques.append(
                _build_expert_audit_payload(
                    project_root=resolved_project_root,
                    inspect_payload=inspect_payload,
                    lens_name=lens.name,
                )
            )

        available_critiques = [item for item in critiques if item.get("available")]
        scored_critiques = [item for item in available_critiques if item.get("score") is not None]
        findings = [
            finding
            for critique in available_critiques
            for finding in (critique.get("findings") or [])
        ]
        payload: dict[str, Any] = {
            "available": True,
            "projectRoot": resolved_project_root,
            "lenses": [item.get("lens") for item in available_critiques],
            "averageScore": round(
                sum(int(item.get("score") or 0) for item in scored_critiques) / len(scored_critiques),
                1,
            )
            if scored_critiques
            else None,
            "findingCount": len(findings),
            "findings": findings,
            "critiques": available_critiques,
        }
        if ping or project or editor_state:
            payload["unityContext"] = {
                "ping": ping or {},
                "project": project or {},
                "editorState": editor_state or {},
            }
        return payload

    _run_and_emit(ctx, _callback)


@workflow_group.command("quality-score")
@click.argument("project_root", required=False)
@click.option(
    "--lens",
    "lens_names",
    multiple=True,
    help="Optional expert lens override. Defaults to all built-in lenses.",
)
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_quality_score_command(
    ctx: click.Context,
    project_root: str | None,
    lens_names: tuple[str, ...],
    port: int | None,
) -> None:
    """Score project quality across one or more expert lenses."""

    if project_root:
        ctx.meta["disable_auto_breadcrumbs"] = True

    def _callback() -> dict[str, Any]:
        resolved_project_root, workflow_port, inspect_payload, ping, project, editor_state = _resolve_workflow_project_context(
            ctx,
            project_root=project_root,
            port=port,
            progress_label="Checking project context for quality scoring",
        )
        requested_lenses = list(lens_names) or [lens.name for lens in iter_builtin_expert_lenses()]
        inspect_payload = _enrich_inspect_payload_for_lenses(
            ctx,
            workflow_port=workflow_port,
            inspect_payload=inspect_payload,
            lens_names=requested_lenses,
        )
        results = _collect_expert_audit_results(
            ctx,
            resolved_project_root=resolved_project_root,
            workflow_port=workflow_port,
            inspect_payload=inspect_payload,
            requested_lenses=requested_lenses,
            progress_template="Scoring {lens} quality",
        )

        available_results = [item for item in results if item.get("available")]
        scored_results = [item for item in available_results if item.get("score") is not None]
        payload: dict[str, Any] = {
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
        if ping or project or editor_state:
            payload["unityContext"] = {
                "ping": ping or {},
                "project": project or {},
                "editorState": editor_state or {},
            }
        return payload

    _run_and_emit(ctx, _callback)


@workflow_group.command("benchmark-report")
@click.argument("project_root", required=False)
@click.option(
    "--lens",
    "lens_names",
    multiple=True,
    help="Optional expert lens override. Defaults to all built-in lenses.",
)
@click.option("--label", type=str, default=None, help="Optional benchmark label.")
@click.option(
    "--report-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Optional JSON file path to write the benchmark report to.",
)
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_benchmark_report_command(
    ctx: click.Context,
    project_root: str | None,
    lens_names: tuple[str, ...],
    label: str | None,
    report_file: Path | None,
    port: int | None,
) -> None:
    """Build a stable quality benchmark report for GitHub, docs, or local snapshots."""

    if project_root:
        ctx.meta["disable_auto_breadcrumbs"] = True

    def _callback() -> dict[str, Any]:
        resolved_project_root, workflow_port, inspect_payload, ping, project, editor_state = _resolve_workflow_project_context(
            ctx,
            project_root=project_root,
            port=port,
            progress_label="Checking project context for benchmark report",
        )
        requested_lenses = list(lens_names) or [lens.name for lens in iter_builtin_expert_lenses()]
        inspect_payload = _enrich_inspect_payload_for_lenses(
            ctx,
            workflow_port=workflow_port,
            inspect_payload=inspect_payload,
            lens_names=requested_lenses,
        )
        results = _collect_expert_audit_results(
            ctx,
            resolved_project_root=resolved_project_root,
            workflow_port=workflow_port,
            inspect_payload=inspect_payload,
            requested_lenses=requested_lenses,
            progress_template="Benchmarking {lens} quality",
        )

        available_results = [item for item in results if item.get("available")]
        scored_results = [item for item in available_results if item.get("score") is not None]
        overall_score = round(
            sum(int(item.get("score") or 0) for item in scored_results) / len(scored_results),
            1,
        ) if scored_results else None

        severity_breakdown = {"high": 0, "medium": 0, "low": 0, "info": 0}
        flattened_findings: list[dict[str, Any]] = []
        focus_areas: list[dict[str, Any]] = []
        project_summary: dict[str, Any] = {}
        for item in available_results:
            lens_payload = dict(item.get("lens") or {})
            raw_audit = dict((item.get("raw") or {}).get("auditReport") or {})
            if raw_audit and not project_summary:
                project_summary = dict(raw_audit.get("summary") or {})
            if raw_audit and not focus_areas:
                focus_areas = [
                    dict(focus_area)
                    for focus_area in (raw_audit.get("focusAreas") or [])
                    if isinstance(focus_area, dict)
                ]
            for finding in item.get("findings") or []:
                severity = str(finding.get("severity") or "info").strip().lower()
                if severity in severity_breakdown:
                    severity_breakdown[severity] += 1
                flattened_findings.append(
                    {
                        "lens": lens_payload.get("name"),
                        "severity": severity,
                        "title": finding.get("title"),
                        "detail": finding.get("detail"),
                    }
                )

        flattened_findings.sort(
            key=lambda item: (
                _benchmark_severity_rank(item.get("severity")),
                str(item.get("lens") or ""),
                str(item.get("title") or ""),
            )
        )

        weakest_lenses = sorted(
            [
                {
                    "name": (item.get("lens") or {}).get("name"),
                    "score": item.get("score"),
                    "grade": item.get("grade"),
                }
                for item in scored_results
            ],
            key=lambda item: (item.get("score") is None, item.get("score") or 999, item.get("name") or ""),
        )[:3]
        project_memory = ProjectMemory(resolved_project_root)
        recurring_compilation_errors = project_memory.get_recurring_compilation_errors()
        recurring_operational_signals = project_memory.get_recurring_operational_signals()
        queue_diagnostics = _build_queue_diagnostics_summary(recurring_operational_signals)
        queue_trend = project_memory.get_queue_trend_summary()

        payload: dict[str, Any] = {
            "available": True,
            "benchmarkVersion": "unity-mastery-v1",
            "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "label": str(label or Path(resolved_project_root).name),
            "projectRoot": resolved_project_root,
            "projectSummary": project_summary,
            "overallScore": overall_score,
            "overallGrade": grade_score(int(overall_score)) if overall_score is not None else None,
            "lensScores": [
                {
                    "name": (item.get("lens") or {}).get("name"),
                    "score": item.get("score"),
                    "grade": item.get("grade"),
                    "findingCount": len(item.get("findings") or []),
                }
                for item in available_results
            ],
            "weakestLenses": weakest_lenses,
            "findingCount": len(flattened_findings),
            "severityBreakdown": severity_breakdown,
            "focusAreas": focus_areas[:5],
            "topFindings": flattened_findings[:5],
            "diagnosticsMemory": {
                "recurringCompilationErrorCount": len(recurring_compilation_errors),
                "recurringOperationalSignalCount": len(recurring_operational_signals),
                "recurringCompilationErrors": recurring_compilation_errors[:5],
                "recurringOperationalSignals": recurring_operational_signals[:5],
            },
            "queueDiagnostics": queue_diagnostics,
            "queueTrend": queue_trend,
            "results": available_results,
        }
        if report_file is not None:
            report_file.parent.mkdir(parents=True, exist_ok=True)
            report_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            payload["reportFile"] = str(report_file)
        if ping or project or editor_state:
            payload["unityContext"] = {
                "ping": ping or {},
                "project": project or {},
                "editorState": editor_state or {},
            }
        return payload

    _run_and_emit(ctx, _callback)


@workflow_group.command("benchmark-compare")
@click.argument("before_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("after_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--report-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Optional JSON file path to write the comparison report to.",
)
@click.option(
    "--markdown-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Optional Markdown file path to write a compact GitHub-friendly summary to.",
)
@click.pass_context
def workflow_benchmark_compare_command(
    ctx: click.Context,
    before_file: Path,
    after_file: Path,
    report_file: Path | None,
    markdown_file: Path | None,
) -> None:
    """Compare two saved benchmark-report JSON files without talking to Unity."""

    ctx.meta["disable_auto_breadcrumbs"] = True

    def _callback() -> dict[str, Any]:
        before_report = _load_benchmark_report(before_file)
        after_report = _load_benchmark_report(after_file)
        payload = _compare_benchmark_reports(
            before_report,
            after_report,
            before_file=before_file,
            after_file=after_file,
        )
        payload["markdownSummary"] = _render_benchmark_compare_markdown(payload)
        if report_file is not None:
            report_file.parent.mkdir(parents=True, exist_ok=True)
            report_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            payload["reportFile"] = str(report_file)
        if markdown_file is not None:
            markdown_file.parent.mkdir(parents=True, exist_ok=True)
            markdown_file.write_text(str(payload.get("markdownSummary") or ""), encoding="utf-8")
            payload["markdownFile"] = str(markdown_file)
        return payload

    _run_and_emit(ctx, _callback)


@workflow_group.command("quality-fix")
@click.argument("project_root", required=False)
@click.option("--lens", "lens_name", required=True, type=str, help="Expert lens to use.")
@click.option("--fix", "fix_name", required=True, type=str, help="Fix type to plan.")
@click.option("--apply", "apply_fix", is_flag=True, help="Run the planned safe fix immediately when supported.")
@click.option("--overwrite", is_flag=True, help="Overwrite existing files when applying the guidance fix.")
@click.option("--include-context/--agents-only", default=True, help="When applying guidance, also write Assets/MCP/Context/ProjectSummary.md.")
@click.option("--open", "open_scene", is_flag=True, help="When applying sandbox-scene, leave the sandbox scene open.")
@click.option("--save-if-dirty", is_flag=True, help="When applying sandbox-scene, save the current scene first if needed.")
@click.option("--discard-unsaved", is_flag=True, help="When applying sandbox-scene, discard unsaved scene changes first.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_quality_fix_command(
    ctx: click.Context,
    project_root: str | None,
    lens_name: str,
    fix_name: str,
    apply_fix: bool,
    overwrite: bool,
    include_context: bool,
    open_scene: bool,
    save_if_dirty: bool,
    discard_unsaved: bool,
    port: int | None,
) -> None:
    """Plan a safe next action for a lens-specific quality issue."""

    if project_root:
        ctx.meta["disable_auto_breadcrumbs"] = True

    def _callback() -> dict[str, Any]:
        resolved_project_root, workflow_port, inspect_payload, ping, project, editor_state = _resolve_workflow_project_context(
            ctx,
            project_root=project_root,
            port=port,
            progress_label="Checking project context for quality fix planning",
        )
        inspect_payload = _enrich_inspect_payload_for_lenses(
            ctx,
            workflow_port=workflow_port,
            inspect_payload=inspect_payload,
            lens_names=[lens_name],
        )
        payload = _build_expert_audit_payload(
            project_root=resolved_project_root,
            inspect_payload=inspect_payload,
            lens_name=lens_name,
        )
        if not payload.get("available"):
            return payload

        lens = get_builtin_expert_lens(lens_name)
        normalized_fix = str(fix_name or "").strip().lower()
        if normalized_fix not in set(lens.supported_fix_types):
            raise ValueError(
                f"Fix '{fix_name}' is not supported for lens '{lens.name}'. Supported fixes: {', '.join(lens.supported_fix_types) or 'none'}."
            )

        _record_progress_step(
            ctx,
            f"Planning {normalized_fix} fix for {lens.name}",
            phase="plan",
            port=workflow_port,
        )
        expert_context = build_expert_context(
            inspect_payload=inspect_payload,
            audit_report=(payload.get("raw") or {}).get("auditReport"),
            lens_name=lens.name,
        )
        plan = build_quality_fix_plan(
            context=expert_context,
            lens_name=lens.name,
            fix_name=normalized_fix,
        )
        result: dict[str, Any] = {
            "available": True,
            "projectRoot": resolved_project_root,
            "lens": payload.get("lens"),
            "fix": {
                "name": normalized_fix,
                "supported": True,
            },
            "score": payload.get("score"),
            "grade": payload.get("grade"),
            "findings": payload.get("findings") or [],
            "plan": plan,
            "applyResult": {
                "applied": False,
                "mode": plan.get("mode"),
            },
        }

        if apply_fix:
            if plan.get("mode") == "manual":
                raise ValueError(
                    f"Fix '{normalized_fix}' for lens '{lens.name}' still requires manual follow-up and cannot be applied automatically yet."
                )

            _record_progress_step(
                ctx,
                f"Applying {normalized_fix} fix for {lens.name}",
                phase="edit",
                port=workflow_port,
            )
            apply_payload: dict[str, Any]
            if normalized_fix == "guidance":
                bundle = build_guidance_bundle(
                    resolved_project_root,
                    inspect_payload=inspect_payload,
                    include_context=include_context,
                    recommendation_limit=5,
                )
                if not bundle.get("available"):
                    apply_payload = bundle
                else:
                    bundle["writeResult"] = write_guidance_bundle(bundle, overwrite=overwrite)
                    apply_payload = bundle
            elif normalized_fix == "test-scaffold":
                apply_payload = _apply_director_test_scaffold_fix(
                    resolved_project_root=resolved_project_root,
                    overwrite=overwrite,
                    audit_report=(payload.get("raw") or {}).get("auditReport"),
                )
            elif normalized_fix == "sandbox-scene":
                apply_payload = _create_sandbox_scene_payload(
                    ctx,
                    workflow_port=workflow_port,
                    name=None,
                    folder="Assets/Scenes",
                    open_scene=open_scene,
                    save_if_dirty=save_if_dirty,
                    discard_unsaved=discard_unsaved,
                )
            elif normalized_fix == "ui-canvas-scaler":
                apply_payload = _apply_ui_canvas_scaler_fix(
                    ctx,
                    workflow_port=workflow_port,
                    inspect_payload=inspect_payload,
                )
            elif normalized_fix == "ui-graphic-raycaster":
                apply_payload = _apply_ui_graphic_raycaster_fix(
                    ctx,
                    workflow_port=workflow_port,
                    inspect_payload=inspect_payload,
                )
            elif normalized_fix == "event-system":
                apply_payload = _apply_systems_event_system_fix(
                    ctx,
                    workflow_port=workflow_port,
                    inspect_payload=inspect_payload,
                    audit_report=(payload.get("raw") or {}).get("auditReport"),
                )
            elif normalized_fix == "audio-listener":
                apply_payload = _apply_systems_audio_listener_fix(
                    ctx,
                    workflow_port=workflow_port,
                    inspect_payload=inspect_payload,
                )
            elif normalized_fix == "disposable-cleanup":
                apply_payload = _apply_systems_disposable_cleanup_fix(
                    ctx,
                    workflow_port=workflow_port,
                    inspect_payload=inspect_payload,
                )
            elif normalized_fix == "player-character-controller":
                apply_payload = _apply_physics_player_character_controller_fix(
                    ctx,
                    workflow_port=workflow_port,
                    inspect_payload=inspect_payload,
                )
            elif normalized_fix == "texture-imports":
                apply_payload = _apply_texture_import_fix(
                    ctx,
                    workflow_port=workflow_port,
                    audit_report=(payload.get("raw") or {}).get("auditReport"),
                )
            elif normalized_fix == "controller-scaffold":
                apply_payload = _apply_animation_controller_scaffold_fix(
                    ctx,
                    workflow_port=workflow_port,
                    controller_path=str(plan.get("controllerPath") or ""),
                )
            elif normalized_fix == "controller-wireup":
                apply_payload = _apply_animation_controller_wireup_fix(
                    ctx,
                    workflow_port=workflow_port,
                    controller_path=str(plan.get("controllerPath") or ""),
                    target_gameobject_path=str(plan.get("targetGameObjectPath") or ""),
                )
            else:
                raise ValueError(
                    f"Fix '{normalized_fix}' is marked supported for '{lens.name}' but has no bounded apply implementation yet."
                )

            result["applyResult"] = {
                "applied": True,
                "mode": plan.get("mode"),
                "command": plan.get("command") or [],
                "result": apply_payload,
            }
        if ping or project or editor_state:
            result["unityContext"] = {
                "ping": ping or {},
                "project": project or {},
                "editorState": editor_state or {},
            }
        return result

    _run_and_emit(ctx, _callback)


@workflow_group.command("bootstrap-guidance")
@click.argument("project_root", required=False)
@click.option("--write/--preview", "write_files", default=False, help="Write the generated guidance files instead of only previewing them.")
@click.option("--overwrite", is_flag=True, help="Overwrite existing guidance files when used with --write.")
@click.option("--include-context/--agents-only", default=True, help="Also generate Assets/MCP/Context/ProjectSummary.md.")
@click.option("--top-recommendations", type=click.IntRange(1, None), default=5, show_default=True, help="Number of audit recommendations to fold into the generated guidance.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_bootstrap_guidance_command(
    ctx: click.Context,
    project_root: str | None,
    write_files: bool,
    overwrite: bool,
    include_context: bool,
    top_recommendations: int,
    port: int | None,
) -> None:
    """Generate AGENTS.md and optional MCP context files from a project audit."""

    if project_root:
        ctx.meta["disable_auto_breadcrumbs"] = True

    def _callback() -> dict[str, Any]:
        workflow_port = port
        ping: dict[str, Any] | None = None
        project: dict[str, Any] | None = None
        editor_state: dict[str, Any] | None = None
        inspect_payload: dict[str, Any] | None = None

        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        resolved_project_root = project_root
        if not resolved_project_root:
            _record_progress_step(ctx, "Checking project context for guidance bootstrap", phase="check", port=workflow_port)
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
                },
                "project": project,
                "ping": ping,
            }

        if not resolved_project_root:
            raise ValueError(
                "Guidance bootstrap needs a Unity project path. Pass PROJECT_ROOT explicitly or select a Unity editor first."
            )

        _record_progress_step(
            ctx,
            f"Generating guidance bundle for {Path(resolved_project_root).name}",
            phase="create",
            port=workflow_port,
        )
        bundle = build_guidance_bundle(
            resolved_project_root,
            inspect_payload=inspect_payload,
            include_context=include_context,
            recommendation_limit=top_recommendations,
        )
        if write_files:
            _record_progress_step(
                ctx,
                "Writing generated guidance files",
                phase="edit",
                port=workflow_port,
            )
            bundle["writeResult"] = write_guidance_bundle(bundle, overwrite=overwrite)
        else:
            bundle["writeResult"] = {
                "projectRoot": bundle.get("projectRoot"),
                "writeCount": 0,
                "skipCount": 0,
                "writes": [
                    {
                        "path": item.get("path"),
                        "relativePath": item.get("relativePath"),
                        "kind": item.get("kind"),
                        "status": "preview",
                    }
                    for item in bundle.get("files") or []
                ],
            }
        if ping or project or editor_state:
            bundle["unityContext"] = {
                "ping": ping or {},
                "project": project or {},
                "editorState": editor_state or {},
            }
        return bundle

    _run_and_emit(ctx, _callback)


@workflow_group.command("create-sandbox-scene")
@click.option("--name", type=str, default=None, help="Optional sandbox scene name. Defaults to <ProjectName>_Sandbox.")
@click.option("--folder", type=str, default="Assets/Scenes", show_default=True, help="Asset folder for the sandbox scene.")
@click.option("--open", "open_scene", is_flag=True, help="Leave the sandbox scene open instead of restoring the original scene.")
@click.option("--save-if-dirty", is_flag=True, help="Save the current scene first if it has unsaved changes.")
@click.option("--discard-unsaved", is_flag=True, help="Discard unsaved changes in the current scene before creating the sandbox.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_create_sandbox_scene_command(
    ctx: click.Context,
    name: str | None,
    folder: str,
    open_scene: bool,
    save_if_dirty: bool,
    discard_unsaved: bool,
    port: int | None,
) -> None:
    """Create a disposable sandbox scene for safer probes and agent passes."""

    def _callback() -> dict[str, Any]:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        return _create_sandbox_scene_payload(
            ctx,
            workflow_port=workflow_port,
            name=name,
            folder=folder,
            open_scene=open_scene,
            save_if_dirty=save_if_dirty,
            discard_unsaved=discard_unsaved,
        )

    _run_and_emit(ctx, _callback)


@workflow_group.command("create-behaviour")
@click.argument("name")
@click.option("--folder", type=str, default="Assets/Scripts/Codex", show_default=True, help="Asset folder for the generated C# script.")
@click.option("--namespace", type=str, default=None, help="Optional C# namespace for the generated script.")
@click.option("--object-name", type=str, default=None, help="Optional scene object name to create and attach the component to.")
@click.option("--attach/--no-attach", default=True, help="Create a scene object and attach the new component.")
@click.option("--timeout", type=float, default=30.0, show_default=True, help="Seconds to wait for compilation and attach retries.")
@click.option("--interval", type=float, default=0.5, show_default=True, help="Polling interval while waiting for Unity to settle.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_create_behaviour_command(
    ctx: click.Context,
    name: str,
    folder: str,
    namespace: str | None,
    object_name: str | None,
    attach: bool,
    timeout: float,
    interval: float,
    port: int | None,
) -> None:
    """Create a MonoBehaviour script and optionally attach it to a new GameObject."""

    def _callback() -> dict[str, Any]:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        class_name = sanitize_csharp_identifier(name)
        scene_object_name = object_name or class_name
        script_path = build_asset_path(folder, class_name)
        script_body = build_behaviour_script(class_name, namespace=namespace)
        created_object = False
        payload: dict[str, Any] = {
            "className": class_name,
            "scriptPath": script_path,
            "objectName": scene_object_name,
        }

        _record_progress_step(ctx, f"Creating script {Path(script_path).name}", phase="create", port=workflow_port)
        script_result = require_workflow_success(
            ctx.obj.backend.call_route(
                "script/create",
                params={"path": script_path, "content": script_body},
                port=workflow_port,
            ),
            f"Create script {script_path}",
        )
        payload["script"] = script_result

        def _fetch_compilation() -> dict[str, Any]:
            result = ctx.obj.backend.call_route_with_recovery(
                "compilation/errors",
                params={"count": 50},
                port=workflow_port,
                record_history=False,
                recovery_timeout=max(timeout, 10.0),
                recovery_interval=max(0.25, interval),
            )
            return require_workflow_success(result, "Read compilation status")

        _record_progress_step(ctx, "Waiting for Unity compilation to settle", phase="check", port=workflow_port)
        compilation = wait_for_compilation(_fetch_compilation, timeout=timeout, interval=interval)
        payload["compilation"] = compilation
        if int(compilation.get("count") or 0) > 0:
            entries = compilation.get("entries") or []
            first_entry = entries[0] if entries and isinstance(entries[0], dict) else {}
            first_message = first_entry.get("message") or "Unity reported compilation errors."
            raise ValueError(f"Create script {script_path} failed: {first_message}")

        if not attach:
            return payload

        try:
            _record_progress_step(ctx, f"Creating GameObject {scene_object_name}", phase="create", port=workflow_port)
            game_object = require_workflow_success(
                ctx.obj.backend.call_tool(
                    "unity_gameobject_create",
                    params={"name": scene_object_name, "primitiveType": "Empty"},
                    port=workflow_port,
                ),
                f"Create GameObject {scene_object_name}",
            )
            created_object = True
            payload["gameObject"] = game_object

            _record_progress_step(
                ctx,
                f"Attaching {class_name} to {scene_object_name}",
                phase="edit",
                port=workflow_port,
            )
            component_result = wait_for_result(
                lambda: ctx.obj.backend.call_tool(
                    "unity_component_add",
                    params={
                        "gameObjectPath": scene_object_name,
                        "componentType": class_name,
                    },
                    port=workflow_port,
                ),
                lambda result: workflow_error_message(result) is None,
                timeout=timeout,
                interval=interval,
            )
            payload["component"] = require_workflow_success(
                component_result,
                f"Attach component {class_name} to {scene_object_name}",
            )
            _record_progress_step(
                ctx,
                f"Inspecting component properties for {class_name}",
                phase="inspect",
                port=workflow_port,
            )
            payload["properties"] = require_workflow_success(
                ctx.obj.backend.call_tool(
                    "unity_component_get_properties",
                    params={
                        "gameObjectPath": scene_object_name,
                        "componentType": class_name,
                    },
                    port=workflow_port,
                ),
                f"Read component properties for {class_name}",
            )
            payload["editorState"] = ctx.obj.backend.call_route_with_recovery(
                "editor/state",
                port=workflow_port,
                record_history=False,
                recovery_timeout=10.0,
            )
            return payload
        except ValueError:
            if created_object:
                try:
                    ctx.obj.backend.call_tool(
                        "unity_gameobject_delete",
                        params={"gameObjectPath": scene_object_name},
                        port=workflow_port,
                    )
                    payload["cleanup"] = {"deletedGameObject": scene_object_name}
                except (BackendSelectionError, UnityMCPClientError, ValueError) as cleanup_exc:
                    payload["cleanup"] = {"deleteError": str(cleanup_exc)}
            raise

    _run_and_emit(ctx, _callback)


@workflow_group.command("reset-scene")
@click.option("--save-if-dirty", is_flag=True, help="Save the scene before reloading it.")
@click.option("--discard-unsaved", is_flag=True, help="Discard unsaved changes and reload the active scene.")
@click.option("--force-reload", is_flag=True, help="Reload even if the scene is already open and clean.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_reset_scene_command(
    ctx: click.Context,
    save_if_dirty: bool,
    discard_unsaved: bool,
    force_reload: bool,
    port: int | None,
) -> None:
    """Reload the active scene using the safe dirty-scene behavior."""

    def _callback() -> dict[str, Any]:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        if save_if_dirty and discard_unsaved:
            raise ValueError("Choose either --save-if-dirty or --discard-unsaved, not both.")

        _record_progress_step(ctx, "Inspecting active scene before reload", phase="inspect", port=workflow_port)
        scene_info = ctx.obj.backend.call_route_with_recovery(
            "scene/info",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        scene_path = get_active_scene_path(scene_info)
        params: dict[str, Any] = {"path": scene_path}
        if save_if_dirty:
            params["saveIfDirty"] = True
        if discard_unsaved:
            params["discardUnsaved"] = True
        if force_reload:
            params["forceReload"] = True

        _record_progress_step(ctx, f"Reloading scene {Path(scene_path).name}", phase="open", port=workflow_port)
        result = require_workflow_success(
            ctx.obj.backend.call_route_with_recovery(
                "scene/open",
                params=params,
                port=workflow_port,
                recovery_timeout=15.0,
            ),
            f"Reload scene {scene_path}",
        )
        payload: dict[str, Any] = {
            "scenePath": scene_path,
            "scene": scene_info,
            "result": result,
        }
        if not result.get("requiresDecision"):
            payload["editorState"] = ctx.obj.backend.call_route_with_recovery(
                "editor/state",
                port=workflow_port,
                record_history=False,
                recovery_timeout=10.0,
            )
        return payload

    _run_and_emit(ctx, _callback)


@workflow_group.command("audit-advanced")
@click.option(
    "--category",
    "categories",
    multiple=True,
    help="Limit the audit to one or more advanced categories such as graphics, memory, physics, profiler, sceneview, settings, testing, ui, audio, lighting, animation, input, shadergraph, terrain, or navmesh.",
)
@click.option(
    "--probe-backed/--no-probe-backed",
    default=True,
    help="Create disposable scene probes so graphics and physics tools can be exercised against real scene objects.",
)
@click.option("--prefix", type=str, default="CodexAdvancedAudit", show_default=True, help="Prefix used for temporary probe objects.")
@click.option("--save-if-dirty-start", is_flag=True, help="Save the active scene first if probe creation needs a clean rollback path.")
@click.option("--timeout", type=float, default=20.0, show_default=True, help="Seconds to wait for scene recovery and cleanup steps.")
@click.option("--interval", type=float, default=0.25, show_default=True, help="Polling interval while waiting for Unity to settle.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_audit_advanced_command(
    ctx: click.Context,
    categories: tuple[str, ...],
    probe_backed: bool,
    prefix: str,
    save_if_dirty_start: bool,
    timeout: float,
    interval: float,
    port: int | None,
) -> None:
    """Run a curated validation pass across safe advanced tools and report pass/fail results."""

    def _callback() -> dict[str, Any]:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        _record_progress_step(ctx, "Inspecting audit start scene state", phase="inspect", port=workflow_port)
        requested_categories = {item.strip().lower() for item in categories if item.strip()}
        scene_info = ctx.obj.backend.call_route_with_recovery(
            "scene/info",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        editor_state = ctx.obj.backend.call_route_with_recovery(
            "editor/state",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        scene_path = get_active_scene_path(scene_info)
        starting_dirty = bool(editor_state.get("sceneDirty"))
        saved_at_start = False

        def _category_allowed(name: str) -> bool:
            return not requested_categories or name.lower() in requested_categories

        scene_mutation_requested = probe_backed or any(
            _category_allowed(category) for category in ("ui", "lighting", "terrain")
        )

        if scene_mutation_requested and starting_dirty and not save_if_dirty_start:
            raise ValueError(
                "Advanced audits that create scene content require a clean starting scene. Save manually or rerun with --save-if-dirty-start."
            )
        if scene_mutation_requested and starting_dirty and save_if_dirty_start:
            _record_progress_step(ctx, f"Saving dirty scene {Path(scene_path).name}", phase="save", port=workflow_port)
            require_workflow_success(
                ctx.obj.backend.call_route_with_recovery(
                    "scene/save",
                    port=workflow_port,
                    recovery_timeout=15.0,
                ),
                f"Save dirty scene {scene_path}",
            )
            editor_state = ctx.obj.backend.call_route_with_recovery(
                "editor/state",
                port=workflow_port,
                record_history=False,
                recovery_timeout=10.0,
            )
            starting_dirty = bool(editor_state.get("sceneDirty"))
            saved_at_start = True

        sample_root = unique_probe_name(prefix)
        sample_object_names = {
            "root": sample_root,
            "floor": f"{sample_root}_Floor",
            "probe": f"{sample_root}_Probe",
        }
        created_sample = False
        scene_mutated = False
        created_assets: list[str] = []
        failure_message: str | None = None

        payload: dict[str, Any] = {
            "before": {
                "scene": scene_info,
                "editorState": editor_state,
                "scenePath": scene_path,
                "savedAtStart": saved_at_start,
            },
            "requestedCategories": sorted(requested_categories),
            "probeBacked": probe_backed,
            "probes": [],
            "probeFixture": None,
        }

        def _call_tool(
            tool_name: str,
            action: str,
            params: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return require_workflow_success(
                ctx.obj.backend.call_tool(tool_name, params=params, port=workflow_port),
                action,
            )

        def _fetch_editor_state() -> dict[str, Any]:
            result = ctx.obj.backend.call_route_with_recovery(
                "editor/state",
                port=workflow_port,
                record_history=False,
                recovery_timeout=max(timeout, 10.0),
                recovery_interval=max(0.1, interval),
            )
            return result or {}

        def _record_probe(
            category: str,
            tool_name: str,
            description: str,
            params: dict[str, Any] | None = None,
            *,
            skip_reason: str | None = None,
        ) -> dict[str, Any]:
            entry: dict[str, Any] = {
                "category": category,
                "tool": tool_name,
                "description": description,
            }
            if params:
                entry["params"] = params
            if skip_reason:
                entry["status"] = "skipped"
                entry["skipReason"] = skip_reason
                payload["probes"].append(entry)
                return
            try:
                _record_progress_step(
                    ctx,
                    f"Probing {category} via {tool_name}",
                    phase="inspect",
                    port=workflow_port,
                )
                result = _call_tool(tool_name, description, params or {})
                entry["status"] = "passed"
                entry["result"] = result
            except (BackendSelectionError, UnityMCPClientError, ValueError) as exc:
                entry["status"] = "failed"
                entry["error"] = str(exc)
            payload["probes"].append(entry)
            return entry

        def _note_asset(asset_path: str | None) -> None:
            if not asset_path:
                return
            if asset_path not in created_assets:
                created_assets.append(asset_path)

        read_only_probes = [
            ("memory", "unity_memory_status", "Inspect memory profiler status", {}),
            ("graphics", "unity_graphics_lighting_summary", "Summarize scene lighting", {}),
            ("sceneview", "unity_sceneview_info", "Inspect scene view camera state", {}),
            ("settings", "unity_settings_quality", "Inspect quality settings", {}),
            ("settings", "unity_settings_time", "Inspect time settings", {}),
            ("profiler", "unity_profiler_stats", "Inspect rendering profiler stats", {}),
            ("audio", "unity_audio_info", "Inspect scene audio sources and listeners", {}),
            ("navmesh", "unity_navmesh_info", "Inspect NavMesh availability and agent types", {}),
            ("shadergraph", "unity_shadergraph_status", "Inspect installed Shader Graph support", {}),
            (
                "testing",
                "unity_testing_list_tests",
                "List available Unity tests",
                {"mode": "EditMode", "maxResults": 20},
            ),
        ]

        try:
            for category, tool_name, description, params in read_only_probes:
                if _category_allowed(category):
                    _record_probe(category, tool_name, description, params)

            if probe_backed:
                sample_payload: dict[str, Any] = {"rootName": sample_root, "objects": {}}
                sample_payload["objects"]["root"] = _call_tool(
                    "unity_gameobject_create",
                    f"Create advanced-audit root {sample_root}",
                    {
                        "name": sample_object_names["root"],
                        "primitiveType": "Empty",
                        "position": vec3(0, 0, 0),
                    },
                )
                sample_payload["objects"]["floor"] = _call_tool(
                    "unity_gameobject_create",
                    f"Create advanced-audit floor {sample_object_names['floor']}",
                    {
                        "name": sample_object_names["floor"],
                        "primitiveType": "Plane",
                        "parent": sample_object_names["root"],
                        "position": vec3(0, 0, 0),
                        "scale": vec3(2.0, 1.0, 2.0),
                    },
                )
                sample_payload["objects"]["probe"] = _call_tool(
                    "unity_gameobject_create",
                    f"Create advanced-audit probe {sample_object_names['probe']}",
                    {
                        "name": sample_object_names["probe"],
                        "primitiveType": "Sphere",
                        "parent": sample_object_names["root"],
                        "position": vec3(0, 1, 0),
                    },
                )
                created_sample = True
                scene_mutated = True
                payload["probeFixture"] = sample_payload

                sample_probes = [
                    (
                        "graphics",
                        "unity_graphics_renderer_info",
                        "Inspect renderer info on the sample probe",
                        {"objectPath": sample_object_names["probe"]},
                    ),
                    (
                        "graphics",
                        "unity_graphics_mesh_info",
                        "Inspect mesh info on the sample probe",
                        {"objectPath": sample_object_names["probe"]},
                    ),
                    (
                        "graphics",
                        "unity_graphics_material_info",
                        "Inspect material info on the sample probe",
                        {"objectPath": sample_object_names["probe"], "includePreview": False},
                    ),
                    (
                        "physics",
                        "unity_physics_raycast",
                        "Raycast through the disposable probe fixture",
                        {
                            "origin": vec3(0, 10, 0),
                            "direction": vec3(0, -1, 0),
                            "maxDistance": 30,
                        },
                    ),
                ]
                for category, tool_name, description, params in sample_probes:
                    if _category_allowed(category):
                        _record_probe(category, tool_name, description, params)
            else:
                for category in ("graphics", "physics"):
                    if _category_allowed(category):
                        _record_probe(
                            category,
                            f"probe-backed:{category}",
                            f"Probe-backed {category} probes",
                            skip_reason="Skipped because --no-probe-backed was used.",
                        )
        except Exception as exc:  # pragma: no cover - covered via cleanup path
            failure_message = str(exc)
        try:
            if _category_allowed("ui"):
                canvas_entry = _record_probe(
                    "ui",
                    "unity_ui_create_canvas",
                    "Create a disposable overlay canvas",
                    {"name": f"{sample_root}_Canvas", "renderMode": "overlay"},
                )
                if canvas_entry.get("status") == "passed":
                    scene_mutated = True
                _record_probe(
                    "ui",
                    "unity_ui_info",
                    "Inspect UI canvas and element counts",
                    {},
                )

            if _category_allowed("lighting"):
                light_entry = _record_probe(
                    "lighting",
                    "unity_lighting_create",
                    "Create a disposable point light",
                    {
                        "name": f"{sample_root}_Light",
                        "lightType": "Point",
                        "intensity": 1.5,
                        "position": vec3(0, 4, 0),
                    },
                )
                if light_entry.get("status") == "passed":
                    scene_mutated = True
                _record_probe(
                    "lighting",
                    "unity_lighting_info",
                    "Inspect scene lighting configuration",
                    {},
                )

            if _category_allowed("animation"):
                animation_root = f"Assets/{sample_root}/Animation"
                controller_path = f"{animation_root}/{sample_root}.controller"
                clip_path = f"{animation_root}/{sample_root}.anim"
                controller_entry = _record_probe(
                    "animation",
                    "unity_animation_create_controller",
                    "Create a disposable Animator Controller",
                    {"path": controller_path},
                )
                if controller_entry.get("status") == "passed":
                    _note_asset(controller_path)
                clip_entry = _record_probe(
                    "animation",
                    "unity_animation_create_clip",
                    "Create a disposable Animation Clip",
                    {"path": clip_path, "loop": True, "frameRate": 30},
                )
                if clip_entry.get("status") == "passed":
                    _note_asset(clip_path)
                _record_probe(
                    "animation",
                    "unity_animation_set_clip_curve",
                    "Author a simple transform curve on the disposable clip",
                    {
                        "clipPath": clip_path,
                        "propertyName": "localPosition.x",
                        "keyframes": [{"time": 0, "value": 0}, {"time": 0.5, "value": 1}],
                        "type": "Transform",
                    },
                )
                _record_probe(
                    "animation",
                    "unity_animation_add_layer",
                    "Add a disposable animator layer",
                    {"controllerPath": controller_path, "layerName": "UpperBody", "weight": 1},
                )
                _record_probe(
                    "animation",
                    "unity_animation_add_state",
                    "Add a disposable animator state",
                    {
                        "controllerPath": controller_path,
                        "stateName": "Idle",
                        "layerIndex": 0,
                        "clipPath": clip_path,
                        "isDefault": True,
                    },
                )
                _record_probe(
                    "animation",
                    "unity_animation_controller_info",
                    "Inspect the disposable Animator Controller",
                    {"path": controller_path},
                )

            if _category_allowed("input"):
                input_root = f"Assets/{sample_root}/Input"
                input_path = f"{input_root}/{sample_root}.inputactions"
                input_entry = _record_probe(
                    "input",
                    "unity_input_create",
                    "Create a disposable Input Actions asset",
                    {"path": input_path, "name": sample_root, "maps": [{"name": "Gameplay"}]},
                )
                if input_entry.get("status") == "passed":
                    _note_asset(input_path)
                _record_probe(
                    "input",
                    "unity_input_info",
                    "Inspect the disposable Input Actions asset",
                    {"path": input_path},
                )

            if _category_allowed("shadergraph"):
                shader_root = f"Assets/{sample_root}/Shaders"
                shader_path = f"{shader_root}/{sample_root}.shadergraph"
                shader_entry = _record_probe(
                    "shadergraph",
                    "unity_shadergraph_create",
                    "Create a disposable Shader Graph asset",
                    {"path": shader_path, "template": "urp_unlit"},
                )
                if shader_entry.get("status") == "passed":
                    _note_asset(shader_path)
                _record_probe(
                    "shadergraph",
                    "unity_shadergraph_list",
                    "List shader graphs filtered to the disposable audit asset",
                    {"filter": sample_root, "maxResults": 10},
                )

            if _category_allowed("terrain"):
                terrain_root = f"Assets/{sample_root}/Terrain"
                terrain_name = f"{sample_root}_Terrain"
                terrain_data_path = f"{terrain_root}/{sample_root}_Data.asset"
                terrain_entry = _record_probe(
                    "terrain",
                    "unity_terrain_create",
                    "Create a disposable terrain",
                    {
                        "name": terrain_name,
                        "width": 128,
                        "length": 128,
                        "height": 60,
                        "heightmapResolution": 129,
                        "position": vec3(48, 0, 48),
                        "dataPath": terrain_data_path,
                    },
                )
                if terrain_entry.get("status") == "passed":
                    scene_mutated = True
                    _note_asset(terrain_data_path)
                _record_probe(
                    "terrain",
                    "unity_terrain_info",
                    "Inspect the disposable terrain",
                    {"name": terrain_name},
                )
                _record_probe(
                    "terrain",
                    "unity_terrain_get_height",
                    "Sample the disposable terrain height at its origin",
                    {"worldX": 48, "worldZ": 48, "name": terrain_name},
                )
        except Exception as exc:  # pragma: no cover - covered via cleanup path
            failure_message = str(exc)
        finally:
            cleanup: dict[str, Any] = {"performed": created_sample or scene_mutated or bool(created_assets)}
            if scene_mutated:
                try:
                    cleanup_state = _fetch_editor_state()
                    if bool(cleanup_state.get("isPlaying")) or bool(cleanup_state.get("isPlayingOrWillChangePlaymode")):
                        cleanup["forceStop"] = require_workflow_success(
                            ctx.obj.backend.call_route_with_recovery(
                                "editor/play-mode",
                                params={"action": "stop"},
                                port=workflow_port,
                                recovery_timeout=max(timeout, 10.0),
                                recovery_interval=max(0.1, interval),
                            ),
                            "Force stop play mode during advanced-audit cleanup",
                        )
                        cleanup["forceStopState"] = wait_for_result(
                            _fetch_editor_state,
                            lambda state: (not bool((state or {}).get("isPlaying")))
                            and (not bool((state or {}).get("isPlayingOrWillChangePlaymode"))),
                            timeout=timeout,
                            interval=interval,
                        )
                except (BackendSelectionError, UnityMCPClientError, ValueError) as cleanup_exc:
                    cleanup["forceStopError"] = str(cleanup_exc)

                try:
                    cleanup["sceneReset"] = require_workflow_success(
                        ctx.obj.backend.call_route_with_recovery(
                            "scene/open",
                            params={"path": scene_path, "discardUnsaved": True},
                            port=workflow_port,
                            recovery_timeout=max(timeout, 10.0),
                            recovery_interval=max(0.1, interval),
                        ),
                        f"Reload scene {scene_path} during advanced-audit cleanup",
                    )
                except (BackendSelectionError, UnityMCPClientError, ValueError) as cleanup_exc:
                    cleanup["sceneResetError"] = str(cleanup_exc)

            if created_assets:
                cleanup["deletedAssets"] = []
                for asset_path in created_assets:
                    try:
                        delete_result = require_workflow_success(
                            ctx.obj.backend.call_tool(
                                "unity_asset_delete",
                                params={"path": asset_path},
                                port=workflow_port,
                            ),
                            f"Delete audit asset {asset_path}",
                        )
                        cleanup["deletedAssets"].append({"path": asset_path, "result": delete_result})
                    except (BackendSelectionError, UnityMCPClientError, ValueError) as cleanup_exc:
                        cleanup.setdefault("assetDeleteErrors", []).append(
                            {"path": asset_path, "error": str(cleanup_exc)}
                        )

            try:
                payload["after"] = {
                    "editorState": ctx.obj.backend.call_route_with_recovery(
                        "editor/state",
                        port=workflow_port,
                        record_history=False,
                        recovery_timeout=10.0,
                    ),
                    "scene": ctx.obj.backend.call_route_with_recovery(
                        "scene/info",
                        port=workflow_port,
                        record_history=False,
                        recovery_timeout=10.0,
                    ),
                }
            except (BackendSelectionError, UnityMCPClientError, ValueError) as after_exc:
                cleanup["afterStateError"] = str(after_exc)

            payload["cleanup"] = cleanup

        if failure_message:
            cleanup_errors = [
                cleanup_error
                for key, cleanup_error in payload.get("cleanup", {}).items()
                if key.endswith("Error")
            ]
            if cleanup_errors:
                failure_message += " Cleanup issues: " + "; ".join(cleanup_errors)
            raise ValueError(failure_message)

        total = len(payload["probes"])
        passed = sum(1 for probe in payload["probes"] if probe.get("status") == "passed")
        failed = sum(1 for probe in payload["probes"] if probe.get("status") == "failed")
        skipped = sum(1 for probe in payload["probes"] if probe.get("status") == "skipped")
        payload["summary"] = {
            "totalProbes": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "requestedCategories": sorted(requested_categories),
            "probeBacked": probe_backed,
            "finalSceneDirty": bool(((payload.get("after") or {}).get("editorState") or {}).get("sceneDirty")),
        }
        return payload

    _run_and_emit(ctx, _callback)


@workflow_group.command("wire-reference")
@click.argument("target_object")
@click.argument("component_type")
@click.argument("property_name")
@click.option("--reference-object", type=str, default=None, help="Scene object name or hierarchy path to assign.")
@click.option("--reference-component", type=str, default=None, help="Optional component type on the referenced scene object.")
@click.option("--asset-path", type=str, default=None, help="Project asset path to assign instead of a scene object.")
@click.option("--reference-instance-id", type=int, default=None, help="Assign an object by Unity instance ID.")
@click.option("--clear", "clear_reference", is_flag=True, help="Clear the reference instead of assigning a new target.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_wire_reference_command(
    ctx: click.Context,
    target_object: str,
    component_type: str,
    property_name: str,
    reference_object: str | None,
    reference_component: str | None,
    asset_path: str | None,
    reference_instance_id: int | None,
    clear_reference: bool,
    port: int | None,
) -> None:
    """Wire a serialized ObjectReference on a component without hand-building route payloads."""

    def _callback() -> dict[str, Any]:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        provided_targets = [
            bool(reference_object),
            bool(asset_path),
            reference_instance_id is not None,
            bool(clear_reference),
        ]
        if sum(1 for item in provided_targets if item) != 1:
            raise ValueError(
                "Choose exactly one of --reference-object, --asset-path, --reference-instance-id, or --clear."
            )

        params: dict[str, Any] = {
            "gameObjectPath": target_object,
            "componentType": component_type,
            "propertyName": property_name,
        }
        if reference_object:
            params["referenceGameObject"] = reference_object
        if reference_component:
            if not reference_object:
                raise ValueError("--reference-component requires --reference-object.")
            params["referenceComponentType"] = reference_component
        if asset_path:
            params["assetPath"] = asset_path
        if reference_instance_id is not None:
            params["referenceInstanceId"] = reference_instance_id
        if clear_reference:
            params["clear"] = True

        _record_progress_step(
            ctx,
            f"Wiring {property_name} on {target_object}",
            phase="wire",
            port=workflow_port,
        )
        result = require_workflow_success(
            ctx.obj.backend.call_route("component/set-reference", params=params, port=workflow_port),
            f"Wire reference {property_name} on {target_object}",
        )
        _record_progress_step(
            ctx,
            f"Inspecting updated GameObject {target_object}",
            phase="inspect",
            port=workflow_port,
        )
        target_info = require_workflow_success(
            ctx.obj.backend.call_tool(
                "unity_gameobject_info",
                params={"gameObjectPath": target_object},
                port=workflow_port,
            ),
            f"Inspect GameObject {target_object}",
        )
        return {
            "targetObject": target_object,
            "componentType": component_type,
            "propertyName": property_name,
            "result": result,
            "gameObject": target_info,
        }

    _run_and_emit(ctx, _callback)


@workflow_group.command("create-prefab")
@click.argument("game_object")
@click.option("--folder", type=str, default="Assets/Prefabs", show_default=True, help="Destination folder for the prefab asset.")
@click.option("--name", type=str, default=None, help="Optional prefab asset name. Defaults to the scene object name.")
@click.option("--instantiate", is_flag=True, help="Instantiate the new prefab back into the current scene.")
@click.option("--instance-name", type=str, default=None, help="Optional name for the instantiated prefab copy.")
@click.option("--parent", type=str, default=None, help="Optional parent object for the instantiated prefab copy.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_create_prefab_command(
    ctx: click.Context,
    game_object: str,
    folder: str,
    name: str | None,
    instantiate: bool,
    instance_name: str | None,
    parent: str | None,
    port: int | None,
) -> None:
    """Save a scene object as a prefab and optionally instantiate the saved prefab."""

    def _callback() -> dict[str, Any]:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        _record_progress_step(ctx, f"Inspecting source GameObject {game_object}", phase="inspect", port=workflow_port)
        object_info = require_workflow_success(
            ctx.obj.backend.call_tool(
                "unity_gameobject_info",
                params={"gameObjectPath": game_object},
                port=workflow_port,
            ),
            f"Inspect GameObject {game_object}",
        )
        prefab_name = sanitize_csharp_identifier(name or object_info.get("name") or game_object)
        save_path = build_asset_path(folder, prefab_name, extension=".prefab")
        _record_progress_step(ctx, f"Creating prefab {Path(save_path).name}", phase="create", port=workflow_port)
        prefab_result = require_workflow_success(
            ctx.obj.backend.call_route(
                "asset/create-prefab",
                params={"gameObjectPath": game_object, "savePath": save_path},
                port=workflow_port,
            ),
            f"Create prefab from {game_object}",
        )

        payload: dict[str, Any] = {
            "gameObject": object_info,
            "prefab": prefab_result,
            "savePath": save_path,
        }

        if instantiate:
            instantiate_params: dict[str, Any] = {"prefabPath": save_path}
            if instance_name:
                instantiate_params["name"] = instance_name
            if parent:
                instantiate_params["parent"] = parent
            _record_progress_step(
                ctx,
                f"Instantiating prefab {Path(save_path).name}",
                phase="create",
                port=workflow_port,
            )
            instance_result = require_workflow_success(
                ctx.obj.backend.call_route(
                    "asset/instantiate-prefab",
                    params=instantiate_params,
                    port=workflow_port,
                ),
                f"Instantiate prefab {save_path}",
            )
            payload["instance"] = instance_result

        return payload

    _run_and_emit(ctx, _callback)


@workflow_group.command("validate-scene")
@click.option("--limit", type=int, default=50, show_default=True, help="Maximum missing-reference results to request.")
@click.option("--include-hierarchy", is_flag=True, help="Include a small hierarchy snapshot in the validation report.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port.")
@click.pass_context
def workflow_validate_scene_command(
    ctx: click.Context,
    limit: int,
    include_hierarchy: bool,
    port: int | None,
) -> None:
    """Collect the high-signal scene health checks needed before building gameplay on top."""

    def _callback() -> dict[str, Any]:
        workflow_port = port
        if port is not None:
            ctx.obj.backend.select_instance(port)
            workflow_port = None

        _record_progress_step(ctx, "Checking editor state", phase="check", port=workflow_port)
        state = ctx.obj.backend.call_route_with_recovery(
            "editor/state",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        _record_progress_step(ctx, "Inspecting active scene info", phase="inspect", port=workflow_port)
        scene = ctx.obj.backend.call_route_with_recovery(
            "scene/info",
            port=workflow_port,
            recovery_timeout=10.0,
        )
        stats_warning: str | None = None
        try:
            _record_progress_step(ctx, "Inspecting scene stats", phase="inspect", port=workflow_port)
            stats = require_workflow_success(
                ctx.obj.backend.call_route_with_recovery(
                    "scene/stats",
                    port=workflow_port,
                    recovery_timeout=10.0,
                ),
                "Read scene stats",
            )
        except (UnityMCPClientError, ValueError) as exc:
            _record_progress_step(ctx, "Falling back to hierarchy-derived scene stats", phase="inspect", port=workflow_port)
            hierarchy_fallback = ctx.obj.backend.call_route_with_recovery(
                "scene/hierarchy",
                params={"maxDepth": 6, "maxNodes": 2000},
                port=workflow_port,
                recovery_timeout=10.0,
            )
            stats = {
                "sceneName": scene.get("activeScene") or state.get("activeScene"),
                "totalGameObjects": hierarchy_fallback.get("totalSceneObjects")
                or hierarchy_fallback.get("returnedNodes")
                or 0,
                "totalComponents": None,
                "totalMeshes": None,
                "totalVertices": None,
                "totalTriangles": None,
                "totalLights": None,
                "totalCameras": None,
                "totalColliders": None,
                "totalRigidbodies": None,
                "topComponents": [],
                "fallback": True,
                "message": "Fell back to hierarchy-derived counts because scene/stats was unavailable.",
            }
            stats_warning = str(exc)
        _record_progress_step(ctx, f"Checking missing references (limit {limit})", phase="check", port=workflow_port)
        missing_references = require_workflow_success(
            ctx.obj.backend.call_route_with_recovery(
                "search/missing-references",
                params={"limit": limit},
                port=workflow_port,
                recovery_timeout=10.0,
            ),
            "Search for missing references",
        )
        _record_progress_step(ctx, f"Checking compilation errors (limit {limit})", phase="check", port=workflow_port)
        compilation = require_workflow_success(
            ctx.obj.backend.call_route_with_recovery(
                "compilation/errors",
                params={"count": limit},
                port=workflow_port,
                recovery_timeout=10.0,
            ),
            "Read compilation errors",
        )

        payload: dict[str, Any] = {
            "summary": {
                "activeScene": scene.get("activeScene") or state.get("activeScene"),
                "sceneDirty": bool(state.get("sceneDirty")),
                "isPlaying": bool(state.get("isPlaying")),
                "isCompiling": bool(compilation.get("isCompiling")),
                "missingReferenceCount": int(missing_references.get("totalFound") or 0),
                "compilationIssueCount": int(compilation.get("count") or 0),
                "totalGameObjects": int(stats.get("totalGameObjects") or 0),
                "totalComponents": int(stats.get("totalComponents") or 0)
                if stats.get("totalComponents") is not None
                else None,
            },
            "editorState": state,
            "scene": scene,
            "stats": stats,
            "missingReferences": missing_references,
            "compilation": compilation,
        }
        if stats_warning:
            payload["warnings"] = [f"scene/stats unavailable: {stats_warning}"]
        if include_hierarchy:
            _record_progress_step(ctx, "Inspecting hierarchy snapshot", phase="inspect", port=workflow_port)
            payload["hierarchy"] = ctx.obj.backend.call_route_with_recovery(
                "scene/hierarchy",
                params={"maxDepth": 2, "maxNodes": 30},
                port=workflow_port,
                recovery_timeout=10.0,
            )

        # ── Memory: track recurring missing references ───────────────────
        try:
            session_state = ctx.obj.backend.session_store.load()
            mem = memory_for_session(session_state)
            if mem is not None:
                ref_results = missing_references.get("results") or []
                active_scene = (
                    scene.get("activeScene")
                    or state.get("activeScene")
                    or "unknown"
                )
                tracking = mem.record_missing_references(ref_results, active_scene)

                # Add tracking summary to the payload so the caller sees it.
                payload["missingRefTracking"] = tracking

                # Surface repeat offenders as top-level warnings.
                recurring = mem.get_recurring_missing_refs(min_seen=2)
                if recurring:
                    payload["recurringMissingRefs"] = recurring
                    repeat_summary = []
                    for r in recurring[:5]:
                        repeat_summary.append(
                            f"  - {r['gameObject']}"
                            + (f" ({r['component']})" if r.get("component") else "")
                            + f" - seen {r['seenCount']}x since {r['firstSeen'][:10]}"
                        )
                    warnings = payload.get("warnings") or []
                    warnings.append(
                        "Recurring missing references detected (repeat offenders):\n"
                        + "\n".join(repeat_summary)
                    )
                    payload["warnings"] = warnings
        except Exception as exc:
            # Memory integration is best-effort; never break validation.
            warnings = payload.get("warnings") or []
            warnings.append(f"Missing-reference memory tracking skipped: {exc}")
            payload["warnings"] = warnings

        return payload

    _run_and_emit(ctx, _callback)
