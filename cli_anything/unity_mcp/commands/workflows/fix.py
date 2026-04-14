"""Workflow fix commands and bounded scene repair functions."""
from __future__ import annotations
from ._group import workflow_group
from ._helpers import *  # noqa: F401, F403

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



workflow_group.add_command(workflow_quality_fix_command)
