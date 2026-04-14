from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _runtime_dir() -> Path:
    path = Path(".cli-anything-unity-mcp")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _default_report_file(timestamp: str) -> Path:
    return _runtime_dir() / f"file-ipc-smoke-{timestamp}.json"


def _build_cli_prefix(project_path: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "cli_anything.unity_mcp",
        "--transport",
        "file",
        "--file-ipc-path",
        project_path,
        "--json",
    ]


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _run_step(
    *,
    cli_prefix: list[str],
    command: list[str],
    label: str,
    required: bool = True,
    timeout: float = 120.0,
) -> dict[str, Any]:
    started = time.monotonic()
    proc = subprocess.run(
        cli_prefix + command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    duration_ms = round((time.monotonic() - started) * 1000, 2)
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    payload: Any = None
    parse_error = ""

    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            parse_error = str(exc)

    success = proc.returncode == 0 and (payload is not None or not stdout)
    if parse_error:
        success = False

    return {
        "label": label,
        "command": command,
        "required": required,
        "success": success,
        "returnCode": proc.returncode,
        "durationMs": duration_ms,
        "stdout": stdout,
        "stderr": stderr,
        "parseError": parse_error or None,
        "result": payload,
    }


def _summarize(steps: list[dict[str, Any]]) -> dict[str, Any]:
    required_steps = [step for step in steps if step["required"]]
    failed_required = [step for step in required_steps if not step["success"]]
    failed_optional = [step for step in steps if not step["required"] and not step["success"]]
    assessment = "healthy"
    if failed_required:
        assessment = "error"
    elif failed_optional:
        assessment = "warning"
    return {
        "assessment": assessment,
        "stepCount": len(steps),
        "requiredCount": len(required_steps),
        "requiredFailures": len(failed_required),
        "optionalFailures": len(failed_optional),
    }


def _render_text(report: dict[str, Any]) -> str:
    lines = []
    summary = dict(report.get("summary") or {})
    lines.append(f"File IPC smoke: {summary.get('assessment', 'unknown')}")
    lines.append(
        f"Steps: {summary.get('stepCount', 0)} total, "
        f"{summary.get('requiredFailures', 0)} required failures, "
        f"{summary.get('optionalFailures', 0)} optional failures"
    )
    lines.append("")
    for step in report.get("steps") or []:
        status = "PASS" if step.get("success") else ("WARN" if not step.get("required") else "FAIL")
        lines.append(f"[{status}] {step.get('label')} ({step.get('durationMs')} ms)")
        result = step.get("result")
        if isinstance(result, dict):
            if step["label"] == "state":
                lines.append(
                    f"  scene={result.get('activeScene')} playing={result.get('isPlaying')} compiling={result.get('isCompiling')}"
                )
            elif step["label"] == "context":
                lines.append(
                    f"  pipeline={result.get('renderPipeline')} contextFiles={result.get('fileCount')}"
                )
            elif step["label"] == "scene-stats":
                lines.append(
                    f"  gameObjects={result.get('totalGameObjects')} components={result.get('totalComponents')} meshes={result.get('totalMeshes')}"
                )
            elif step["label"] == "missing-references":
                lines.append(f"  totalFound={result.get('totalFound')}")
            elif step["label"] == "search-by-component":
                lines.append(
                    f"  component={result.get('component')} count={result.get('count')}"
                )
            elif step["label"] == "selection-get":
                lines.append(
                    f"  count={result.get('count')} active={result.get('activePath')}"
                )
            elif step["label"] == "selection-set":
                lines.append(
                    f"  count={result.get('count')} active={result.get('activePath')}"
                )
            elif step["label"] == "focus-scene-view":
                lines.append(
                    f"  focused={result.get('focused')} path={result.get('path')}"
                )
            elif step["label"] == "capture":
                captures = result.get("captures") or {}
                lines.append(
                    "  captures="
                    + ", ".join(f"{name}:{info.get('path')}" for name, info in captures.items())
                )
            elif step["label"] == "console-readback":
                entries = result.get("entries") or []
                last_message = entries[-1]["message"] if entries else ""
                lines.append(f"  entries={result.get('count')} last={last_message}")
        if not step.get("success"):
            detail = step.get("stderr") or step.get("stdout") or step.get("parseError") or "unknown failure"
            lines.append(f"  error={detail}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a standalone File IPC smoke pass against a live Unity project.")
    parser.add_argument("--file-ipc-path", required=True, help="Absolute path to the Unity project root that contains .umcp/.")
    parser.add_argument("--report-file", type=Path, default=None, help="Optional JSON report file path.")
    parser.add_argument("--capture-label", default=None, help="Optional label prefix for debug capture output.")
    parser.add_argument("--skip-capture", action="store_true", help="Skip the optional debug capture step.")
    parser.add_argument("--json", action="store_true", help="Print the final report as JSON.")
    args = parser.parse_args()

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    report_file = args.report_file or _default_report_file(timestamp)
    capture_label = args.capture_label or f"file-ipc-smoke-{timestamp}"
    breadcrumb_message = f"file ipc smoke breadcrumb {timestamp}"
    cli_prefix = _build_cli_prefix(args.file_ipc_path)

    steps: list[dict[str, Any]] = [
        _run_step(cli_prefix=cli_prefix, command=["instances"], label="instances"),
        _run_step(cli_prefix=cli_prefix, command=["state"], label="state"),
        _run_step(cli_prefix=cli_prefix, command=["context"], label="context"),
        _run_step(cli_prefix=cli_prefix, command=["scene-info"], label="scene-info"),
        _run_step(cli_prefix=cli_prefix, command=["route", "search/scene-stats"], label="scene-stats"),
        _run_step(
            cli_prefix=cli_prefix,
            command=["route", "search/missing-references", "--params", _compact_json({"limit": 20})],
            label="missing-references",
        ),
        _run_step(
            cli_prefix=cli_prefix,
            command=["route", "search/by-component", "--params", _compact_json({"componentType": "Transform", "limit": 5})],
            label="search-by-component",
        ),
        _run_step(cli_prefix=cli_prefix, command=["agent", "queue"], label="agent-queue"),
        _run_step(cli_prefix=cli_prefix, command=["agent", "sessions"], label="agent-sessions"),
        _run_step(
            cli_prefix=cli_prefix,
            command=["debug", "breadcrumb", breadcrumb_message, "--level", "info"],
            label="breadcrumb",
        ),
        _run_step(
            cli_prefix=cli_prefix,
            command=["route", "console/log", "--params", _compact_json({"count": 12})],
            label="console-readback",
        ),
    ]

    primary_object_path = ""
    for step in steps:
        if step["label"] != "search-by-component":
            continue
        result = step.get("result") or {}
        results = result.get("results") or []
        if results:
            primary_object_path = str(results[0].get("path") or "")
        break

    steps.append(
        _run_step(
            cli_prefix=cli_prefix,
            command=["route", "selection/get"],
            label="selection-get",
        )
    )

    if primary_object_path:
        steps.append(
            _run_step(
                cli_prefix=cli_prefix,
                command=["route", "selection/set", "--params", _compact_json({"path": primary_object_path})],
                label="selection-set",
            )
        )
        steps.append(
            _run_step(
                cli_prefix=cli_prefix,
                command=["route", "selection/focus-scene-view", "--params", _compact_json({"path": primary_object_path})],
                label="focus-scene-view",
            )
        )
    else:
        steps.append(
            {
                "label": "selection-set",
                "command": ["route", "selection/set"],
                "required": True,
                "success": False,
                "returnCode": -1,
                "durationMs": 0,
                "stdout": "",
                "stderr": "search-by-component returned no object path to select",
                "parseError": None,
                "result": None,
            }
        )
        steps.append(
            {
                "label": "focus-scene-view",
                "command": ["route", "selection/focus-scene-view"],
                "required": True,
                "success": False,
                "returnCode": -1,
                "durationMs": 0,
                "stdout": "",
                "stderr": "search-by-component returned no object path to focus",
                "parseError": None,
                "result": None,
            }
        )

    if not args.skip_capture:
        steps.append(
            _run_step(
                cli_prefix=cli_prefix,
                command=["debug", "capture", "--kind", "both", "--label", capture_label],
                label="capture",
                required=False,
            )
        )

    breadcrumb_verified = False
    for step in steps:
        if step["label"] != "console-readback":
            continue
        result = step.get("result") or {}
        entries = result.get("entries") or []
        breadcrumb_verified = any(breadcrumb_message in str(entry.get("message") or "") for entry in entries)
        step["breadcrumbVerified"] = breadcrumb_verified
        if not breadcrumb_verified:
            step["success"] = False
            step["stderr"] = (step.get("stderr") or "") + ("; breadcrumb not found in console readback" if step.get("stderr") else "breadcrumb not found in console readback")

    summary = _summarize(steps)
    summary["breadcrumbVerified"] = breadcrumb_verified

    report = {
        "title": "Standalone File IPC Smoke Pass",
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "projectPath": str(Path(args.file_ipc_path).resolve()),
        "summary": summary,
        "steps": steps,
    }

    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(_render_text(report))
        print(f"\nReport: {report_file}")

    return 1 if summary["requiredFailures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
