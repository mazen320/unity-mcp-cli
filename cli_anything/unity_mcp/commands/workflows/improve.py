"""Workflow improve-project command."""
from __future__ import annotations
from ._group import workflow_group
from ._helpers import *  # noqa: F401, F403

@workflow_group.command("improve-project")
@click.argument("project_root", required=False)
@click.option("--overwrite", is_flag=True, help="Overwrite existing file-based guidance or test scaffold outputs.")
@click.option("--include-context/--agents-only", default=True, help="When writing guidance, also generate Assets/MCP/Context/ProjectSummary.md.")
@click.option("--open-sandbox", is_flag=True, help="Leave the sandbox scene open after creating it.")
@click.option(
    "--save-if-dirty/--no-save-if-dirty",
    default=True,
    show_default=True,
    help="Save the active scene before creating the sandbox scene when needed.",
)
@click.option("--discard-unsaved", is_flag=True, help="Discard unsaved scene changes before creating the sandbox scene.")
@click.option("--port", type=int, default=None, help="Temporarily target a specific Unity port for live scene repairs.")
@click.option(
    "--markdown-file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Optional file path for a GitHub-friendly markdown summary of the improvement run.",
)
@click.pass_context
def workflow_improve_project_command(
    ctx: click.Context,
    project_root: str | None,
    overwrite: bool,
    include_context: bool,
    open_sandbox: bool,
    save_if_dirty: bool,
    discard_unsaved: bool,
    port: int | None,
    markdown_file: Path | None,
) -> None:
    """Run the bounded safe-improvement pass for a Unity project and report the score delta."""

    if project_root:
        ctx.meta["disable_auto_breadcrumbs"] = True

    def _callback() -> dict[str, Any]:
        resolved_project_root, workflow_port, inspect_payload, ping, project, editor_state, live_unity_available = _resolve_improve_project_context(
            ctx,
            project_root=project_root,
            port=port,
            progress_label="Checking project context for improve-project",
        )
        project_name = Path(resolved_project_root).name

        baseline_score: float | None = None
        try:
            baseline_payload = _build_quality_score_payload(
                ctx,
                resolved_project_root=resolved_project_root,
                workflow_port=workflow_port,
                inspect_payload=inspect_payload,
            )
            baseline_raw = baseline_payload.get("overallScore")
            baseline_score = float(baseline_raw) if baseline_raw is not None else None
        except Exception:
            baseline_score = None

        shared_audit_report = build_asset_audit_report(
            resolved_project_root,
            inspect_payload=inspect_payload,
            recommendation_limit=8,
        )

        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        project_changed = False
        scene_changed = False

        def _record_applied(*, lens: str, fix: str, summary: str, result: dict[str, Any]) -> None:
            applied.append(
                {
                    "lens": lens,
                    "fix": fix,
                    "summary": summary,
                    "result": result,
                }
            )

        def _record_skipped(*, lens: str, fix: str, reason: str) -> None:
            skipped.append(
                {
                    "lens": lens,
                    "fix": fix,
                    "reason": reason,
                }
            )

        try:
            _record_progress_step(ctx, "Applying project guidance fix", phase="edit", port=workflow_port)
            guidance_bundle = build_guidance_bundle(
                resolved_project_root,
                inspect_payload=inspect_payload,
                include_context=include_context,
                recommendation_limit=5,
            )
            guidance_write = write_guidance_bundle(guidance_bundle, overwrite=overwrite)
            if int(guidance_write.get("writeCount") or 0) > 0:
                project_changed = True
                _record_applied(
                    lens="director",
                    fix="guidance",
                    summary=f"Wrote {guidance_write.get('writeCount')} guidance file(s).",
                    result={
                        "projectRoot": guidance_bundle.get("projectRoot"),
                        "writeResult": guidance_write,
                    },
                )
            else:
                _record_skipped(
                    lens="director",
                    fix="guidance",
                    reason="Guidance already exists.",
                )
        except Exception as exc:
            _record_skipped(lens="director", fix="guidance", reason=str(exc))

        sandbox_path = Path(resolved_project_root) / "Assets" / "Scenes" / f"{project_name}_Sandbox.unity"
        if not live_unity_available:
            _record_skipped(
                lens="director",
                fix="sandbox-scene",
                reason="Sandbox scene skipped because no live Unity session is available.",
            )
        elif sandbox_path.exists():
            _record_skipped(
                lens="director",
                fix="sandbox-scene",
                reason="Sandbox scene already exists.",
            )
        else:
            try:
                _record_progress_step(ctx, "Creating sandbox scene", phase="edit", port=workflow_port)
                sandbox_payload = _create_sandbox_scene_payload(
                    ctx,
                    workflow_port=workflow_port,
                    name=None,
                    folder="Assets/Scenes",
                    open_scene=open_sandbox,
                    save_if_dirty=save_if_dirty,
                    discard_unsaved=discard_unsaved,
                )
                if str(sandbox_payload.get("path") or "").strip():
                    project_changed = True
                    scene_changed = True
                    _record_applied(
                        lens="director",
                        fix="sandbox-scene",
                        summary=f"Created sandbox scene at {sandbox_payload.get('path')}.",
                        result=sandbox_payload,
                    )
                else:
                    _record_skipped(
                        lens="director",
                        fix="sandbox-scene",
                        reason="Sandbox scene fix did not return a scene path.",
                    )
            except Exception as exc:
                _record_skipped(lens="director", fix="sandbox-scene", reason=str(exc))

        if not live_unity_available:
            _record_skipped(
                lens="systems",
                fix="disposable-cleanup",
                reason="Disposable cleanup skipped because no live Unity session is available.",
            )
        else:
            try:
                _record_progress_step(ctx, "Cleaning disposable scene objects", phase="edit", port=workflow_port)
                cleanup_payload = _apply_systems_disposable_cleanup_fix(
                    ctx,
                    workflow_port=workflow_port,
                    inspect_payload=inspect_payload,
                )
                if int(cleanup_payload.get("updatedCount") or 0) > 0:
                    scene_changed = True
                    _record_applied(
                        lens="systems",
                        fix="disposable-cleanup",
                        summary=f"Removed {cleanup_payload.get('removedCount')} disposable scene object(s).",
                        result=cleanup_payload,
                    )
                else:
                    _record_skipped(
                        lens="systems",
                        fix="disposable-cleanup",
                        reason=str(cleanup_payload.get("reason") or "Disposable cleanup not needed."),
                    )
            except Exception as exc:
                _record_skipped(lens="systems", fix="disposable-cleanup", reason=str(exc))

        if not live_unity_available:
            _record_skipped(
                lens="systems",
                fix="audio-listener",
                reason="AudioListener fix skipped because no live Unity session is available.",
            )
        else:
            try:
                _record_progress_step(ctx, "Repairing AudioListener setup", phase="edit", port=workflow_port)
                audio_payload = _apply_systems_audio_listener_fix(
                    ctx,
                    workflow_port=workflow_port,
                    inspect_payload=inspect_payload,
                )
                if int(audio_payload.get("updatedCount") or 0) > 0:
                    scene_changed = True
                    if int(audio_payload.get("addedCount") or 0) > 0:
                        summary = f"Added AudioListener to {audio_payload.get('keptPath')}."
                    else:
                        summary = (
                            f"Removed {audio_payload.get('removedCount')} extra AudioListener(s) and kept "
                            f"{audio_payload.get('keptPath')}."
                        )
                    _record_applied(
                        lens="systems",
                        fix="audio-listener",
                        summary=summary,
                        result=audio_payload,
                    )
                else:
                    _record_skipped(
                        lens="systems",
                        fix="audio-listener",
                        reason=str(audio_payload.get("reason") or "AudioListener setup already looked healthy."),
                    )
            except Exception as exc:
                _record_skipped(lens="systems", fix="audio-listener", reason=str(exc))

        if not live_unity_available:
            _record_skipped(
                lens="systems",
                fix="event-system",
                reason="EventSystem fix skipped because no live Unity session is available.",
            )
        else:
            try:
                _record_progress_step(ctx, "Repairing EventSystem setup", phase="edit", port=workflow_port)
                event_payload = _apply_systems_event_system_fix(
                    ctx,
                    workflow_port=workflow_port,
                    inspect_payload=inspect_payload,
                    audit_report=shared_audit_report,
                )
                if int(event_payload.get("updatedCount") or 0) > 0:
                    scene_changed = True
                    summary = "Repaired EventSystem setup."
                    if event_payload.get("moduleType"):
                        summary = f"Repaired EventSystem with {event_payload.get('moduleType')}."
                    _record_applied(
                        lens="systems",
                        fix="event-system",
                        summary=summary,
                        result=event_payload,
                    )
                else:
                    _record_skipped(
                        lens="systems",
                        fix="event-system",
                        reason=str(event_payload.get("reason") or "EventSystem setup already looked healthy."),
                    )
            except Exception as exc:
                _record_skipped(lens="systems", fix="event-system", reason=str(exc))

        if not live_unity_available:
            _record_skipped(
                lens="ui",
                fix="ui-canvas-scaler",
                reason="CanvasScaler fix skipped because no live Unity session is available.",
            )
        else:
            try:
                _record_progress_step(ctx, "Repairing CanvasScaler setup", phase="edit", port=workflow_port)
                canvas_scaler_payload = _apply_ui_canvas_scaler_fix(
                    ctx,
                    workflow_port=workflow_port,
                    inspect_payload=inspect_payload,
                )
                if int(canvas_scaler_payload.get("updatedCount") or 0) > 0:
                    scene_changed = True
                    _record_applied(
                        lens="ui",
                        fix="ui-canvas-scaler",
                        summary=f"Added CanvasScaler to {canvas_scaler_payload.get('updatedCount')} Canvas object(s).",
                        result=canvas_scaler_payload,
                    )
                else:
                    _record_skipped(
                        lens="ui",
                        fix="ui-canvas-scaler",
                        reason="CanvasScaler fix not needed.",
                    )
            except Exception as exc:
                _record_skipped(lens="ui", fix="ui-canvas-scaler", reason=str(exc))

        if not live_unity_available:
            _record_skipped(
                lens="ui",
                fix="ui-graphic-raycaster",
                reason="GraphicRaycaster fix skipped because no live Unity session is available.",
            )
        else:
            try:
                _record_progress_step(ctx, "Repairing GraphicRaycaster setup", phase="edit", port=workflow_port)
                graphic_raycaster_payload = _apply_ui_graphic_raycaster_fix(
                    ctx,
                    workflow_port=workflow_port,
                    inspect_payload=inspect_payload,
                )
                if int(graphic_raycaster_payload.get("updatedCount") or 0) > 0:
                    scene_changed = True
                    _record_applied(
                        lens="ui",
                        fix="ui-graphic-raycaster",
                        summary=(
                            f"Added GraphicRaycaster to {graphic_raycaster_payload.get('updatedCount')} Canvas object(s)."
                        ),
                        result=graphic_raycaster_payload,
                    )
                else:
                    _record_skipped(
                        lens="ui",
                        fix="ui-graphic-raycaster",
                        reason="GraphicRaycaster fix not needed.",
                    )
            except Exception as exc:
                _record_skipped(lens="ui", fix="ui-graphic-raycaster", reason=str(exc))

        if not live_unity_available:
            _record_skipped(
                lens="physics",
                fix="player-character-controller",
                reason="CharacterController fix skipped because no live Unity session is available.",
            )
        else:
            try:
                _record_progress_step(ctx, "Repairing likely player movement body", phase="edit", port=workflow_port)
                controller_payload = _apply_physics_player_character_controller_fix(
                    ctx,
                    workflow_port=workflow_port,
                    inspect_payload=inspect_payload,
                )
                if int(controller_payload.get("updatedCount") or 0) > 0:
                    scene_changed = True
                    _record_applied(
                        lens="physics",
                        fix="player-character-controller",
                        summary=f"Added CharacterController to {controller_payload.get('targetPath')}.",
                        result=controller_payload,
                    )
                else:
                    _record_skipped(
                        lens="physics",
                        fix="player-character-controller",
                        reason=str(
                            controller_payload.get("reason")
                            or "CharacterController fix did not identify a safe target."
                        ),
                    )
            except Exception as exc:
                _record_skipped(lens="physics", fix="player-character-controller", reason=str(exc))

        try:
            _record_progress_step(ctx, "Applying test scaffold fix", phase="edit", port=workflow_port)
            test_plan = build_quality_fix_plan(
                context={
                    "project": {
                        "path": resolved_project_root,
                        "name": project_name,
                    }
                },
                lens_name="director",
                fix_name="test-scaffold",
            )
            if str(test_plan.get("mode") or "") != "workflow":
                _record_skipped(
                    lens="director",
                    fix="test-scaffold",
                    reason="Test scaffold skipped because com.unity.test-framework is not installed.",
                )
            else:
                test_payload = _apply_director_test_scaffold_fix(
                    resolved_project_root=resolved_project_root,
                    overwrite=overwrite,
                    audit_report=None,
                )
                if int(test_payload.get("writeCount") or 0) > 0:
                    project_changed = True
                    _record_applied(
                        lens="director",
                        fix="test-scaffold",
                        summary=f"Wrote {test_payload.get('writeCount')} EditMode scaffold file(s).",
                        result=test_payload,
                    )
                else:
                    _record_skipped(
                        lens="director",
                        fix="test-scaffold",
                        reason="EditMode test scaffold already exists.",
                    )
        except Exception as exc:
            _record_skipped(lens="director", fix="test-scaffold", reason=str(exc))

        final_score: float | None = None
        final_payload: dict[str, Any] | None = None
        try:
            final_project_root, final_workflow_port, final_inspect_payload, final_ping, final_project, final_editor_state, _ = _resolve_improve_project_context(
                ctx,
                project_root=resolved_project_root,
                port=port,
                progress_label="Refreshing project context after improve-project",
            )
            final_payload = _build_quality_score_payload(
                ctx,
                resolved_project_root=final_project_root,
                workflow_port=final_workflow_port,
                inspect_payload=final_inspect_payload,
            )
            final_raw = final_payload.get("overallScore")
            final_score = float(final_raw) if final_raw is not None else None
            ping.update(final_ping)
            project.update(final_project)
            editor_state.update(final_editor_state)
        except Exception:
            final_score = None

        score_delta = None
        if baseline_score is not None and final_score is not None:
            score_delta = round(final_score - baseline_score, 1)

        payload: dict[str, Any] = {
            "available": True,
            "projectRoot": resolved_project_root,
            "liveUnityAvailable": live_unity_available,
            "projectChanged": project_changed,
            "sceneChanged": scene_changed,
            "baselineScore": baseline_score,
            "finalScore": final_score,
            "scoreDelta": score_delta,
            "appliedCount": len(applied),
            "skippedCount": len(skipped),
            "applied": applied,
            "skipped": skipped,
        }
        if markdown_file is not None:
            markdown_path = Path(markdown_file)
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(_render_improve_project_markdown(payload), encoding="utf-8")
            payload["markdownFile"] = str(markdown_path)
        if final_payload is not None:
            payload["finalLensScores"] = list(final_payload.get("lensScores") or [])
        return _attach_unity_context(
            payload,
            ping=ping,
            project=project,
            editor_state=editor_state,
        )

    _run_and_emit(ctx, _callback)



workflow_group.add_command(workflow_improve_project_command)
