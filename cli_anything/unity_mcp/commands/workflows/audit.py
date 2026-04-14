"""Workflow audit commands: expert-audit, scene-critique, quality-score, benchmark-report, benchmark-compare."""
from __future__ import annotations
from ._group import workflow_group
from ._helpers import *  # noqa: F401, F403

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
        payload = _build_quality_score_payload(
            ctx,
            resolved_project_root=resolved_project_root,
            workflow_port=workflow_port,
            inspect_payload=inspect_payload,
            requested_lenses=list(lens_names) or None,
        )
        return _attach_unity_context(
            payload,
            ping=ping,
            project=project,
            editor_state=editor_state,
        )

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



workflow_group.add_command(workflow_expert_audit_command)
workflow_group.add_command(workflow_scene_critique_command)
workflow_group.add_command(workflow_quality_score_command)
workflow_group.add_command(workflow_benchmark_report_command)
workflow_group.add_command(workflow_benchmark_compare_command)
