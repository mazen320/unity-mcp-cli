"""Workflow command modules."""
from ._group import workflow_group
from . import inspect, audit, fix, improve, scaffold  # noqa: F401

_HIDDEN_COMMANDS = {
    "asset-audit",
    "benchmark-compare",
    "benchmark-report",
    "bootstrap-guidance",
    "create-sandbox-scene",
    "expert-audit",
    "improve-project",
    "quality-fix",
    "quality-score",
    "scene-critique",
}

for _command_name in _HIDDEN_COMMANDS:
    if _command_name in workflow_group.commands:
        workflow_group.commands[_command_name].hidden = True

__all__ = ["workflow_group"]
