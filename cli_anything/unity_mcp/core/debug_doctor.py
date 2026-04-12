from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .error_heuristics import (
    analyze_compilation_errors,
    analyze_console_messages,
    summarize_compilation_errors,
)

if TYPE_CHECKING:
    from .memory import ProjectMemory


def _port_suffix(port: int | None) -> str:
    return f" --port {port}" if port is not None else " --port <port>"


def _finding(
    severity: str,
    title: str,
    detail: str,
    command: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "severity": severity,
        "title": title,
        "detail": detail,
    }
    if command:
        payload["command"] = command
    if evidence:
        payload["evidence"] = evidence
    return payload


def _distinct_history_ports(recent_history: List[dict[str, Any]] | None) -> list[int]:
    ports: list[int] = []
    seen: set[int] = set()
    for entry in recent_history or []:
        raw_port = entry.get("port")
        try:
            port = int(raw_port)
        except (TypeError, ValueError):
            continue
        if port in seen:
            continue
        seen.add(port)
        ports.append(port)
    return ports


def _check_structure_drift(
    findings: list[dict[str, Any]],
    structure: dict[str, Any],
    snapshot: dict[str, Any],
    port_suffix: str,
    add_command: Any,
) -> None:
    """Add findings when the current snapshot diverges from cached project structure."""

    cached_pipeline = structure.get("render_pipeline")
    if cached_pipeline:
        camera_diag = dict(snapshot.get("cameraDiagnostics") or {})
        current_pipeline = camera_diag.get("pipeline") or ""

        def _normalize_pipeline(p: str) -> str:
            """Collapse known aliases to a canonical name."""
            p = p.lower().replace(" ", "").replace("-", "").replace("_", "")
            if p in {"urp", "universalrp", "universalrenderpipeline"}:
                return "urp"
            if p in {"hdrp", "highdefinitionrp", "highdefinitionrenderpipeline"}:
                return "hdrp"
            if p in {"builtin", "builtinrenderpipeline", "legacy", "none", ""}:
                return "builtin"
            return p

        # Detect pipeline change (e.g. someone switched from URP to Built-in).
        # Normalize before comparing so "URP" == "UniversalRP" == "Universal Render Pipeline".
        if current_pipeline and _normalize_pipeline(cached_pipeline) != _normalize_pipeline(current_pipeline):
            findings.append(
                _finding(
                    "warning",
                    "Render Pipeline Changed",
                    f"Project was using '{cached_pipeline}' but camera now reports '{current_pipeline}'. "
                    f"This can break materials, lighting, and post-processing.",
                    f"cli-anything-unity-mcp --json workflow inspect{port_suffix}",
                    {"cachedPipeline": cached_pipeline, "currentPipeline": current_pipeline},
                )
            )
            add_command(f"cli-anything-unity-mcp --json workflow inspect{port_suffix}")

    cached_version = structure.get("unity_version")
    if cached_version:
        editor_state = dict(snapshot.get("editorState") or {})
        current_version = editor_state.get("unityVersion") or ""
        if current_version and current_version != cached_version:
            findings.append(
                _finding(
                    "info",
                    "Unity Version Changed",
                    f"Project was last inspected on Unity {cached_version}, now running {current_version}. "
                    f"Re-inspect to update cached structure.",
                    f"cli-anything-unity-mcp --json workflow inspect{port_suffix}",
                    {"cachedVersion": cached_version, "currentVersion": current_version},
                )
            )
            add_command(f"cli-anything-unity-mcp --json workflow inspect{port_suffix}")

    # Detect known package-dependent tools vs installed packages
    cached_packages = structure.get("packages")
    if isinstance(cached_packages, list):
        pkg_names = {p.split("@")[0] if "@" in p else p for p in cached_packages}
        compilation = dict(snapshot.get("compilation") or {})
        entries = compilation.get("entries") or []
        for entry in entries:
            msg = str(entry.get("message") or "").lower() if isinstance(entry, dict) else ""
            # Common: user tries TextMeshPro API without the package
            if "tmpro" in msg or "textmeshpro" in msg:
                if not any("textmeshpro" in p.lower() or "com.unity.textmeshpro" in p.lower() for p in pkg_names):
                    findings.append(
                        _finding(
                            "error",
                            "TextMeshPro Not Installed",
                            "Compilation references TextMeshPro but the package is not in the cached package list. "
                            "Install it via Package Manager or 'cli-anything-unity-mcp tool unity_packages_add'.",
                            f"cli-anything-unity-mcp --json tool unity_packages_add --params '{{\"packageId\":\"com.unity.textmeshpro\"}}'",
                        )
                    )
                    break


def build_debug_doctor_report(
    snapshot: dict[str, Any],
    recent_history: List[dict[str, Any]] | None,
    active_port: int | None,
    memory: Optional["ProjectMemory"] = None,
) -> dict[str, Any]:
    summary = dict(snapshot.get("summary") or {})
    editor_state = dict(snapshot.get("editorState") or {})
    console = dict(snapshot.get("console") or {})
    console_summary = dict(snapshot.get("consoleSummary") or {})
    compilation = dict(snapshot.get("compilation") or {})
    missing_references = dict(snapshot.get("missingReferences") or {})
    queue = dict(snapshot.get("queue") or {})
    camera_diagnostics = dict(snapshot.get("cameraDiagnostics") or {})

    findings: list[dict[str, Any]] = []
    recommended_commands: list[str] = []

    def add_command(command: str) -> None:
        if command not in recommended_commands:
            recommended_commands.append(command)

    port_suffix = _port_suffix(active_port)

    renderer_name = str(camera_diagnostics.get("rendererName") or "")
    clear_flags = str(camera_diagnostics.get("clearFlags") or "")
    if "renderer2d" in renderer_name.lower():
        if clear_flags.lower() == "skybox":
            findings.append(
                _finding(
                    "error",
                    "Skybox Blocked By 2D Renderer",
                    "MainCamera is using URP Renderer2D while its clear flags are set to Skybox. Renderer2D will not render a 3D skybox, so the view falls back to a flat background instead.",
                    f"cli-anything-unity-mcp --json debug capture --kind both{port_suffix}",
                    {
                        "cameraName": camera_diagnostics.get("cameraName"),
                        "rendererName": renderer_name,
                        "clearFlags": clear_flags,
                        "pipeline": camera_diagnostics.get("pipeline"),
                    },
                )
            )
        else:
            findings.append(
                _finding(
                    "warning",
                    "Camera Uses 2D Renderer",
                    "MainCamera is using URP Renderer2D. That is fine for 2D scenes, but it will block skyboxes and some 3D rendering expectations until the camera or pipeline is switched to a Universal forward renderer.",
                    f"cli-anything-unity-mcp --json debug capture --kind both{port_suffix}",
                    {
                        "cameraName": camera_diagnostics.get("cameraName"),
                        "rendererName": renderer_name,
                        "clearFlags": clear_flags,
                        "pipeline": camera_diagnostics.get("pipeline"),
                    },
                )
            )
        add_command(f"cli-anything-unity-mcp --json debug capture --kind both{port_suffix}")

    if int(compilation.get("count") or 0) > 0:
        comp_entries = list(compilation.get("entries") or [])
        comp_summary = summarize_compilation_errors(comp_entries)

        # Top-level umbrella finding so the summary is always visible.
        findings.append(
            _finding(
                "error",
                "Compilation Issues",
                (
                    f"{comp_summary['totalErrors']} error(s) across "
                    f"{len(comp_summary['affectedFiles'])} file(s). "
                    f"Unique codes: {', '.join(comp_summary['uniqueErrorCodes'][:5]) or 'unknown'}."
                    if comp_summary["uniqueErrorCodes"]
                    else f"{comp_summary['totalErrors']} compiler error(s) detected."
                ),
                f"cli-anything-unity-mcp --json debug snapshot --console-count 100 --include-hierarchy{port_suffix}",
                {
                    "count": comp_summary["totalErrors"],
                    "uniqueErrorCodes": comp_summary["uniqueErrorCodes"],
                    "affectedFiles": comp_summary["affectedFiles"],
                    "errorCodeCounts": comp_summary["errorCodeCounts"],
                },
            )
        )
        # Per-code enriched findings (deduped, human-readable).
        for heuristic_finding in analyze_compilation_errors(comp_entries, port_suffix):
            findings.append(heuristic_finding)
            cmd = heuristic_finding.get("command")
            if cmd:
                add_command(cmd)
        add_command(f"cli-anything-unity-mcp --json console --count 50 --type error{port_suffix}")

    if int(missing_references.get("totalFound") or 0) > 0:
        results = missing_references.get("results") or []
        first_result = results[0] if results and isinstance(results[0], dict) else {}
        findings.append(
            _finding(
                "error",
                "Missing References",
                str(
                    first_result.get("issue")
                    or "The active scene contains missing object or script references."
                ),
                f"cli-anything-unity-mcp --json workflow validate-scene --include-hierarchy{port_suffix}",
                {
                    "count": int(missing_references.get("totalFound") or 0),
                    "path": first_result.get("path"),
                    "gameObject": first_result.get("gameObject"),
                },
            )
        )
        add_command(f"cli-anything-unity-mcp --json workflow validate-scene --include-hierarchy{port_suffix}")

    highest_severity = str(console_summary.get("highestSeverity") or "none").lower()
    entries = list(console.get("entries") or [])
    if highest_severity in {"warning", "error"}:
        matching = [
            entry for entry in entries if str(entry.get("type") or "").lower() == highest_severity
        ]
        latest = matching[-1] if matching else (entries[-1] if entries else {})
        findings.append(
            _finding(
                highest_severity,
                "Unity Console Issues",
                str(latest.get("message") or f"Unity console contains {highest_severity} entries."),
                f"cli-anything-unity-mcp --json console --count 50 --type {highest_severity}{port_suffix}",
                {
                    "highestSeverity": highest_severity,
                    "consoleEntryCount": int(summary.get("consoleEntryCount") or len(entries)),
                },
            )
        )
        add_command(f"cli-anything-unity-mcp --json console --count 50 --type {highest_severity}{port_suffix}")
        # Enrich with Unity-specific runtime pattern heuristics.
        for heuristic_finding in analyze_console_messages(entries, port_suffix):
            findings.append(heuristic_finding)
            cmd = heuristic_finding.get("command")
            if cmd:
                add_command(cmd)

    if bool(editor_state.get("isCompiling")):
        findings.append(
            _finding(
                "warning",
                "Unity Is Compiling",
                "The editor is still compiling, so scene and play-mode behavior may not be stable yet.",
                f"cli-anything-unity-mcp --json debug watch --iterations 3 --interval 1 --console-count 20{port_suffix}",
            )
        )
        add_command(f"cli-anything-unity-mcp --json debug watch --iterations 3 --interval 1 --console-count 20{port_suffix}")

    if bool(editor_state.get("isPlaying")) or bool(editor_state.get("isPlayingOrWillChangePlaymode")):
        findings.append(
            _finding(
                "warning",
                "Editor Still In Play Mode",
                "Unity is still playing or transitioning, so captures and inspection may reflect runtime state instead of the saved scene.",
                f"cli-anything-unity-mcp --json play stop{port_suffix}",
            )
        )
        add_command(f"cli-anything-unity-mcp --json play stop{port_suffix}")

    if bool(summary.get("sceneDirty")):
        findings.append(
            _finding(
                "warning",
                "Scene Has Unsaved Changes",
                "The active scene is dirty, so resets and scene switches can behave differently until it is saved or discarded.",
                f"cli-anything-unity-mcp --json scene-save{port_suffix}",
            )
        )
        add_command(f"cli-anything-unity-mcp --json scene-save{port_suffix}")

    total_queued = int(queue.get("totalQueued") or 0)
    active_agents = int(queue.get("activeAgents") or 0)
    if total_queued > 0:
        findings.append(
            _finding(
                "warning",
                "Queued Requests Pending",
                "Unity still has queued work waiting to run, which usually means the bridge is backlogged or waiting on worker capacity.",
                f"cli-anything-unity-mcp --json agent queue{port_suffix}",
                {
                    "totalQueued": total_queued,
                    "activeAgents": active_agents,
                },
            )
        )
        add_command(f"cli-anything-unity-mcp --json agent queue{port_suffix}")
    if active_agents > 0:
        findings.append(
            _finding(
                "warning",
                "Active Unity Agents Running",
                "Unity still has active agent work in flight, so scene or console state can keep changing while you inspect it.",
                f"cli-anything-unity-mcp --json agent sessions{port_suffix}",
                {
                    "totalQueued": total_queued,
                    "activeAgents": active_agents,
                },
            )
        )
        add_command(f"cli-anything-unity-mcp --json agent sessions{port_suffix}")

    bridge_ports = _distinct_history_ports(recent_history)
    if len(bridge_ports) > 1:
        findings.append(
            _finding(
                "warning",
                "Bridge Port Hop Detected",
                (
                    "Recent CLI activity hopped across Unity bridge ports "
                    + " -> ".join(str(port) for port in bridge_ports)
                    + ". This usually means Unity rebound the bridge or the selected editor changed."
                ),
                f"cli-anything-unity-mcp --json debug bridge{port_suffix}",
                {"ports": bridge_ports, "activePort": active_port},
            )
        )
        add_command(f"cli-anything-unity-mcp --json debug bridge{port_suffix}")

    add_command(f"cli-anything-unity-mcp --json debug snapshot --console-count 100 --include-hierarchy{port_suffix}")
    add_command(f"cli-anything-unity-mcp --json debug capture --kind both{port_suffix}")

    # ── Memory-powered diagnostics ───────────────────────────────────────────
    if memory is not None:
        # Annotate findings with past fixes.
        for finding in findings:
            evidence_text = json.dumps(finding.get("evidence") or {}) + " " + str(finding.get("detail", ""))
            past_fixes = memory.suggest_fix(evidence_text)
            if not past_fixes:
                past_fixes = memory.suggest_fix(finding.get("title", ""))
            if past_fixes:
                best = past_fixes[0]["content"]
                finding["pastFix"] = {
                    "fixCommand": best.get("fixCommand"),
                    "context": best.get("context", ""),
                    "note": "This pattern was seen before — the command below fixed it last time.",
                }

        # Cross-check snapshot against cached project structure.
        structure = memory.get_all_structure()
        if structure:
            _check_structure_drift(findings, structure, snapshot, port_suffix, add_command)

        if int(compilation.get("count") or 0) > 0:
            current_compilation = []
            for entry in comp_entries:
                if not isinstance(entry, dict):
                    continue
                parsed = memory._parse_compilation_issue(entry)
                if parsed:
                    current_compilation.append(
                        (parsed.get("code", ""), parsed.get("file", ""), parsed.get("message", ""))
                    )
            recurring_compilation = [
                issue
                for issue in memory.get_recurring_compilation_errors(min_seen=2)
                if (issue.get("code", ""), issue.get("file", ""), issue.get("message", "")) in current_compilation
            ]
            if recurring_compilation:
                findings.append(
                    _finding(
                        "error",
                        "Recurring Compilation Errors",
                        "Compiler issues that have already appeared in this project are still recurring.",
                        f"cli-anything-unity-mcp --json debug doctor --recent-commands 8{port_suffix}",
                        {
                            "issues": [
                                {
                                    "code": issue.get("code"),
                                    "file": issue.get("file"),
                                    "seenCount": issue.get("seenCount"),
                                }
                                for issue in recurring_compilation[:5]
                            ]
                        },
                    )
                )
                add_command(f"cli-anything-unity-mcp --json debug doctor --recent-commands 8{port_suffix}")

        recurring_signals = {
            (str(issue.get("kind") or "").strip().lower(), str(issue.get("key") or "").strip()): issue
            for issue in memory.get_recurring_operational_signals(min_seen=2)
        }
        if (
            (int(queue.get("totalQueued") or 0) > 0 or int(queue.get("activeAgents") or 0) > 0)
            and ("queue", "queue-contention") in recurring_signals
        ):
            recurring_queue = recurring_signals[("queue", "queue-contention")]
            findings.append(
                _finding(
                    "warning",
                    "Recurring Queue Contention",
                    "Queue pressure keeps showing up in repeated doctor runs, which usually means overlapping agent work or long-running Unity-side tasks.",
                    f"cli-anything-unity-mcp --json agent queue{port_suffix}",
                    {
                        "seenCount": recurring_queue.get("seenCount"),
                        "firstSeen": recurring_queue.get("firstSeen"),
                        "lastSeen": recurring_queue.get("lastSeen"),
                    },
                )
            )
            add_command(f"cli-anything-unity-mcp --json agent queue{port_suffix}")
            add_command(f"cli-anything-unity-mcp --json agent sessions{port_suffix}")
        if len(bridge_ports) > 1 and ("bridge", "bridge-port-hop") in recurring_signals:
            recurring_bridge = recurring_signals[("bridge", "bridge-port-hop")]
            findings.append(
                _finding(
                    "warning",
                    "Recurring Bridge Port Hops",
                    "Recent command history keeps bouncing across Unity ports, so bridge discovery or editor selection is not staying stable.",
                    f"cli-anything-unity-mcp --json debug bridge{port_suffix}",
                    {
                        "seenCount": recurring_bridge.get("seenCount"),
                        "ports": bridge_ports,
                        "firstSeen": recurring_bridge.get("firstSeen"),
                        "lastSeen": recurring_bridge.get("lastSeen"),
                    },
                )
            )
            add_command(f"cli-anything-unity-mcp --json debug bridge{port_suffix}")

    if findings:
        severity_rank = {"info": 0, "warning": 1, "error": 2}
        top = max(findings, key=lambda item: severity_rank.get(str(item.get("severity")), 0))
        overall = "error" if top["severity"] == "error" else "warning"
        headline = top["title"]
    else:
        overall = "healthy"
        headline = "No major Unity issues detected"
        findings.append(
            _finding(
                "info",
                "Healthy Snapshot",
                "No compilation issues, missing references, queue backlog, or console warnings/errors were detected in the current snapshot.",
            )
        )

    # Compilation summary at top level for quick agent scanning.
    comp_entries = list(compilation.get("entries") or [])
    comp_summary_block = summarize_compilation_errors(comp_entries) if comp_entries else None

    return {
        "title": "Unity Debug Doctor",
        "summary": {
            **summary,
            "assessment": overall,
            "headline": headline,
            "findingCount": len(findings),
        },
        "findings": findings,
        "compilationSummary": comp_summary_block,
        "recentCommands": list(recent_history or []),
        "recommendedCommands": recommended_commands,
        "snapshot": snapshot,
    }
