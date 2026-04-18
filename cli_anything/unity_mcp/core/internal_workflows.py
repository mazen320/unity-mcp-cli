from __future__ import annotations

import json
from contextlib import redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Sequence

import click

from ..commands._shared import (
    CLIContext,
    SessionStore,
    UnityMCPBackend,
    UnityMCPClient,
    _build_agent_profile_store,
    _build_base_args,
    _build_developer_profile_store,
)
from ..commands.workflows.audit import (
    workflow_benchmark_report_command,
    workflow_expert_audit_command,
    workflow_quality_score_command,
    workflow_scene_critique_command,
)
from ..commands.workflows.fix import workflow_quality_fix_command
from ..commands.workflows.improve import workflow_improve_project_command
from .embedded_cli import EmbeddedCLIOptions


@dataclass(frozen=True)
class InternalWorkflowInvocation:
    command: click.Command
    prog_name: str
    project_path: Path


_COMMANDS: dict[str, click.Command] = {
    "expert-audit": workflow_expert_audit_command,
    "scene-critique": workflow_scene_critique_command,
    "quality-score": workflow_quality_score_command,
    "benchmark-report": workflow_benchmark_report_command,
    "quality-fix": workflow_quality_fix_command,
    "improve-project": workflow_improve_project_command,
}


def _build_cli_context(
    *,
    options: EmbeddedCLIOptions,
    project_path: Path,
) -> CLIContext:
    profile_store = _build_agent_profile_store(options.session_path, None)
    developer_store = _build_developer_profile_store(options.session_path, None)
    developer_profile = developer_store.default_profile()
    resolved_agent_id = options.agent_id

    client = UnityMCPClient(
        host=options.host,
        agent_id=resolved_agent_id,
        use_queue=not options.legacy,
    )
    backend = UnityMCPBackend(
        client=client,
        session_store=SessionStore(options.session_path) if options.session_path else SessionStore(),
        registry_path=options.registry_path,
        default_port=options.default_port,
        port_range_start=options.port_range_start,
        port_range_end=options.port_range_end,
        transport="auto",
        file_ipc_paths=[project_path],
    )
    return CLIContext(
        backend=backend,
        json_output=True,
        base_args=tuple(
            _build_base_args(
                host=options.host,
                default_port=options.default_port,
                registry_path=options.registry_path,
                session_path=options.session_path,
                agent_profiles_path=None,
                developer_profiles_path=None,
                json_output=True,
                agent_id=resolved_agent_id,
                agent_profile=None,
                developer_profile=None,
                legacy=options.legacy,
                port_range_start=options.port_range_start,
                port_range_end=options.port_range_end,
            )
        ),
        command_path="workflow",
        agent_profile_store=profile_store,
        developer_profile_store=developer_store,
        agent_id=resolved_agent_id,
        agent_profile=None,
        developer_profile=developer_profile,
        agent_source="explicit",
        developer_source="default",
        legacy_mode=options.legacy,
    )


def _resolve_invocation(
    command_name: str,
    *,
    project_path: Path,
) -> InternalWorkflowInvocation:
    command = _COMMANDS.get(str(command_name or "").strip().lower())
    if command is None:
        raise RuntimeError(f"Unknown internal workflow command `{command_name}`.")
    return InternalWorkflowInvocation(
        command=command,
        prog_name=f"workflow {command.name}",
        project_path=project_path,
    )


def run_internal_workflow_json(
    command_name: str,
    argv: Sequence[str],
    options: EmbeddedCLIOptions,
    *,
    project_path: str | Path,
) -> Any:
    invocation = _resolve_invocation(command_name, project_path=Path(project_path))
    cli_context = _build_cli_context(options=options, project_path=invocation.project_path)
    stdout = StringIO()

    with redirect_stdout(stdout):
        try:
            invocation.command.main(
                args=list(argv),
                prog_name=invocation.prog_name,
                standalone_mode=False,
                obj=cli_context,
            )
        except SystemExit as exc:  # pragma: no cover - defensive guard
            code = exc.code if isinstance(exc.code, int) else 1
            if code:
                raise RuntimeError(
                    f"Internal workflow `{command_name}` exited with status {code}."
                ) from exc

    raw = stdout.getvalue().strip()
    if not raw:
        return {}
    last_line = next((line for line in reversed(raw.splitlines()) if line.strip()), "")
    if not last_line:
        return {}
    return json.loads(last_line)
