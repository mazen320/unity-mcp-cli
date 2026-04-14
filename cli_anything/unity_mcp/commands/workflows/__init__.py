"""Workflow command modules."""
from ._group import workflow_group
from . import inspect, audit, fix, improve, scaffold  # noqa: F401 — side-effect imports register commands

__all__ = ["workflow_group"]
