"""workflow_group Click group and sub-command registration."""
from __future__ import annotations
import click


@click.group("workflow")
def workflow_group() -> None:
    """High-level workflows that combine multiple Unity bridge actions safely."""


# Register agent-loop and agent-chat commands
from ..agent_loop_cmd import agent_loop_command as _agent_loop_cmd  # noqa: E402
from ..agent_chat_cmd import agent_chat_command as _agent_chat_cmd  # noqa: E402
workflow_group.add_command(_agent_loop_cmd)
workflow_group.add_command(_agent_chat_cmd)
