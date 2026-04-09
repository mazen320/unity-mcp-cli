from __future__ import annotations

from typing import Any, Dict, List


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


def build_debug_doctor_report(
    snapshot: dict[str, Any],
    recent_history: List[dict[str, Any]] | None,
    active_port: int | None,
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
        entries = compilation.get("entries") or []
        first_entry = entries[0] if entries and isinstance(entries[0], dict) else {}
        findings.append(
            _finding(
                "error",
                "Compilation Issues",
                str(first_entry.get("message") or "Unity reports script compilation errors."),
                f"cli-anything-unity-mcp --json debug snapshot --console-count 100 --include-hierarchy{port_suffix}",
                {"count": int(compilation.get("count") or 0)},
            )
        )
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

    if int(queue.get("totalQueued") or 0) > 0 or int(queue.get("activeAgents") or 0) > 0:
        findings.append(
            _finding(
                "warning",
                "Queue Activity Detected",
                "Unity still has queued or active agent work, which can delay or distort current results.",
                f"cli-anything-unity-mcp --json agent queue{port_suffix}",
                {
                    "totalQueued": int(queue.get("totalQueued") or 0),
                    "activeAgents": int(queue.get("activeAgents") or 0),
                },
            )
        )
        add_command(f"cli-anything-unity-mcp --json agent queue{port_suffix}")
        add_command(f"cli-anything-unity-mcp --json agent sessions{port_suffix}")

    add_command(f"cli-anything-unity-mcp --json debug snapshot --console-count 100 --include-hierarchy{port_suffix}")
    add_command(f"cli-anything-unity-mcp --json debug capture --kind both{port_suffix}")

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

    return {
        "title": "Unity Debug Doctor",
        "summary": {
            **summary,
            "assessment": overall,
            "headline": headline,
            "findingCount": len(findings),
        },
        "findings": findings,
        "recentCommands": list(recent_history or []),
        "recommendedCommands": recommended_commands,
        "snapshot": snapshot,
    }
