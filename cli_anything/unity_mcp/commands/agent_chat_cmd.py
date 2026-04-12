from __future__ import annotations

import json
import time
from pathlib import Path

import click

from ..core.agent_chat import ChatBridge
from ..core.file_ipc import FileIPCClient
from .agent_loop_cmd import _resolve_file_ipc_client


def _emit_payload(ctx: click.Context, payload: dict) -> None:
    if ctx.obj.json_output:
        click.echo(json.dumps(payload))
        return
    click.echo(payload.get("message") or str(payload))


@click.command("agent-chat")
@click.argument("project_root", required=False, type=click.Path(exists=False, file_okay=False, path_type=Path))
@click.option("--once", is_flag=True, help="Process at most one pending message and exit.")
@click.option("--iterations", type=int, default=None, help="Poll a fixed number of times, then exit.")
@click.option("--poll-interval", type=float, default=0.25, show_default=True, help="Seconds between polls.")
@click.pass_context
def agent_chat_command(
    ctx: click.Context,
    project_root: Path | None,
    once: bool,
    iterations: int | None,
    poll_interval: float,
) -> None:
    """Run the File IPC chat bridge for the Unity Agent tab."""
    if project_root is not None:
        file_client = FileIPCClient(project_root)
    else:
        file_client = _resolve_file_ipc_client(ctx.obj.backend)
        project_root = Path(file_client.project_path)

    bridge = ChatBridge(project_root, file_client, poll_interval=max(0.05, float(poll_interval)))

    if once or iterations is not None:
        loops = 1 if once else max(0, int(iterations or 0))
        processed = 0
        for index in range(loops):
            if bridge.poll_once():
                processed += 1
            if index + 1 < loops:
                time.sleep(bridge.poll_interval)
        _emit_payload(
            ctx,
            {
                "success": True,
                "projectPath": str(project_root),
                "processed": processed > 0,
                "processedCount": processed,
                "historyPath": str(project_root / ".umcp" / "chat" / "history.json"),
                "statusPath": str(project_root / ".umcp" / "agent-status.json"),
                "message": f"Processed {processed} queued message(s).",
            },
        )
        return

    _emit_payload(
        ctx,
        {
            "success": True,
            "projectPath": str(project_root),
            "message": f"Starting agent chat bridge for {project_root}. Press Ctrl+C to stop.",
        },
    )
    bridge.run()
