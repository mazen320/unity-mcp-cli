# Track 1 — Housekeeping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate technical debt that blocks contributors — split monolithic files, compress docs, merge stale branch, update PLAN.md to match current product vision.

**Architecture:** Pure refactoring. No new behavior. Every split preserves existing public APIs exactly. Tests must pass before and after each task.

**Tech Stack:** Python, Click, pytest, git

---

## File Structure After This Plan

```
commands/
    workflow.py                     # SHRINKS: thin re-export only (was 4804 lines)
    workflows/
        __init__.py                 # exports workflow_group
        _helpers.py                 # all private helpers (_normalize_*, _build_*, _attach_*, etc.)
        inspect.py                  # workflow_inspect_command, workflow_asset_audit_command
        audit.py                    # expert_audit, scene_critique, quality_score, benchmark_*, audit_advanced
        fix.py                      # quality_fix + all _apply_* functions
        improve.py                  # improve_project + _render_improve_project_markdown
        scaffold.py                 # sandbox_scene, bootstrap_guidance, validate_scene, wire_reference, create_prefab, reset_scene, create_behaviour

tests/
    test_core.py                    # SHRINKS: backend/client/routing tests only (~1000 lines)
    test_memory.py                  # NEW: all ProjectMemory tests
    test_coverage.py                # NEW: tool_coverage tests
    test_heuristics.py              # NEW: error_heuristics tests
    test_file_ipc.py                # NEW: FileIPCClient tests
    mock_bridge.py                  # NEW: MockBridgeServer + MockBridgeHandler (shared infra)
    test_workflow_e2e.py            # NEW: workflow command e2e tests
    test_mock_routes.py             # NEW: mock-only route coverage tests
    test_chat_e2e.py                # NEW: agent chat + agent loop e2e tests

PLAN.md                             # UPDATED: reflects current state + new vision
README.md                           # COMPRESSED: ~200 lines max
TODO.md                             # COMPRESSED: trim history, keep priorities + backlog
AGENTS.md                           # COMPRESSED: keep commands + rules, cut prose
```

---

## Task 1: Merge codex branch + clean up stale branches

**Files:**
- No code changes. Git operations only.

- [ ] **Step 1: Verify branch state**

```bash
git log --oneline -5 main
git log --oneline -5 codex/unity-mastery-pack-phase-1
git diff main...codex/unity-mastery-pack-phase-1 --stat
```

Expected: codex branch has ~5 commits ahead of main (learning system spec, FILE_IPC updates, unified product plan).

- [ ] **Step 2: Merge codex branch into main**

```bash
git checkout main
git merge codex/unity-mastery-pack-phase-1 --no-ff -m "merge: integrate learning system spec and unified product plan"
```

Expected: clean merge, no conflicts (these were doc/spec commits only).

- [ ] **Step 3: Run tests to confirm merge didn't break anything**

```bash
cd <agent-harness-root>
py -3.12 -m pytest cli_anything/unity_mcp/tests/ -x -q 2>&1 | tail -10
```

Expected: all tests pass (162+).

- [ ] **Step 4: Delete stale merged branches**

```bash
git branch -d claude/gracious-meninsky
git branch -d codex/unity-mastery-pack-phase-1
```

Expected: both deleted without error (both already merged).

- [ ] **Step 5: Commit**

```bash
git log --oneline -3 main
```

Expected: merge commit at top. No push.

---

## Task 2: Split workflow.py into domain modules

**Files:**
- Create: `cli_anything/unity_mcp/commands/workflows/__init__.py`
- Create: `cli_anything/unity_mcp/commands/workflows/_helpers.py`
- Create: `cli_anything/unity_mcp/commands/workflows/inspect.py`
- Create: `cli_anything/unity_mcp/commands/workflows/audit.py`
- Create: `cli_anything/unity_mcp/commands/workflows/fix.py`
- Create: `cli_anything/unity_mcp/commands/workflows/improve.py`
- Create: `cli_anything/unity_mcp/commands/workflows/scaffold.py`
- Modify: `cli_anything/unity_mcp/commands/workflow.py` → thin re-export

- [ ] **Step 1: Create the workflows package directory and __init__.py**

```bash
mkdir -p cli_anything/unity_mcp/commands/workflows
```

`cli_anything/unity_mcp/commands/workflows/__init__.py`:
```python
"""Workflow command modules — split from the original monolithic workflow.py."""
from ._group import workflow_group

__all__ = ["workflow_group"]
```

- [ ] **Step 2: Extract the Click group + agent command registration into _group.py**

Create `cli_anything/unity_mcp/commands/workflows/_group.py`:
```python
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
```

- [ ] **Step 3: Extract all private helper functions into _helpers.py**

Move these functions from `workflow.py` to `cli_anything/unity_mcp/commands/workflows/_helpers.py` (copy the full function bodies exactly):

- `_normalize_sandbox_folder`
- `_is_missing_route_error`
- `_unwrap_execute_code_result`
- `_build_create_sandbox_execute_code`
- `_resolve_workflow_project_context`
- `_normalize_project_path_for_compare`
- `_resolve_improve_project_context`
- `_attach_unity_context`
- `_build_expert_audit_payload`
- `_enrich_inspect_payload_for_lenses`
- `_iter_hierarchy_nodes`
- `_extract_hierarchy_nodes`
- `_benchmark_severity_rank`
- `_load_benchmark_report`
- `_normalize_benchmark_finding`
- `_normalize_benchmark_diagnostic_entry`
- `_build_queue_diagnostics_summary`
- `_default_queue_trend_summary`
- `_compare_benchmark_reports`
- `_format_signed_delta`
- `_render_benchmark_compare_markdown`
- `_collect_expert_audit_results`
- `_build_quality_score_payload`
- `_rank_scene_camera_node`
- `_rank_likely_player_node`
- `_looks_disposable_scene_object`
- `_rank_scene_event_system_node`
- `_render_editmode_smoke_test`
- `_render_editmode_test_asmdef`
- `_create_sandbox_scene_payload`

`_helpers.py` header:
```python
"""Private helpers shared across workflow domain modules."""
from __future__ import annotations
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
import click
from ...core.expert_context import build_expert_context
from ...core.expert_fixes import (
    build_quality_fix_plan,
    build_test_scaffold_spec,
    choose_event_system_module,
)
from ...core.expert_lenses import grade_score, get_builtin_expert_lens, iter_builtin_expert_lenses
from ...core.project_guidance import build_guidance_bundle, write_guidance_bundle
from ...core.project_insights import build_asset_audit_report, build_project_insights
from ...core.memory import ProjectMemory, memory_for_session
from .._shared import (
    BackendSelectionError,
    UnityMCPClientError,
    _learn_from_inspect,
    _record_progress_step,
    _run_and_emit,
    build_asset_path,
    build_behaviour_script,
    get_active_scene_path,
    require_workflow_success,
    sanitize_csharp_identifier,
    unique_probe_name,
    vec3,
    wait_for_compilation,
    wait_for_result,
    workflow_error_message,
)
```

- [ ] **Step 4: Create inspect.py with inspect and asset-audit commands**

`cli_anything/unity_mcp/commands/workflows/inspect.py` header + registrations:
```python
"""Workflow inspect and asset-audit commands."""
from __future__ import annotations
from ._group import workflow_group
from ._helpers import *  # noqa: F401, F403 — all helpers available
```

Move these complete functions from `workflow.py` into this file (copy full bodies):
- `workflow_inspect_command` (L2284 in original)
- `workflow_asset_audit_command` (L2415 in original)

Register them at the bottom:
```python
workflow_group.add_command(workflow_inspect_command)
workflow_group.add_command(workflow_asset_audit_command)
```

- [ ] **Step 5: Create audit.py with expert-audit, scene-critique, quality-score, benchmark, audit-advanced**

`cli_anything/unity_mcp/commands/workflows/audit.py` header:
```python
"""Workflow audit commands: expert-audit, scene-critique, quality-score, benchmark-report, benchmark-compare, audit-advanced."""
from __future__ import annotations
from ._group import workflow_group
from ._helpers import *  # noqa: F401, F403
```

Move these complete functions (copy full bodies):
- `workflow_expert_audit_command` (L2499)
- `workflow_scene_critique_command` (L2556)
- `workflow_quality_score_command` (L2640)
- `workflow_benchmark_report_command` (L2692)
- `workflow_benchmark_compare_command` (L2852)
- `workflow_audit_advanced_command` (L3944)
- `_render_benchmark_compare_markdown` (already in _helpers, skip)

Register all at bottom:
```python
workflow_group.add_command(workflow_expert_audit_command)
workflow_group.add_command(workflow_scene_critique_command)
workflow_group.add_command(workflow_quality_score_command)
workflow_group.add_command(workflow_benchmark_report_command)
workflow_group.add_command(workflow_benchmark_compare_command)
workflow_group.add_command(workflow_audit_advanced_command)
```

- [ ] **Step 6: Create fix.py with quality-fix and all _apply_* functions**

`cli_anything/unity_mcp/commands/workflows/fix.py` header:
```python
"""Workflow fix commands and bounded scene repair functions."""
from __future__ import annotations
from ._group import workflow_group
from ._helpers import *  # noqa: F401, F403
```

Move these (copy full bodies):
- `_apply_ui_canvas_scaler_fix` (L1148)
- `_apply_ui_graphic_raycaster_fix` (L1225)
- `_apply_systems_audio_listener_fix` (L1353)
- `_apply_systems_disposable_cleanup_fix` (L1509)
- `_apply_physics_player_character_controller_fix` (L1597)
- `_apply_systems_event_system_fix` (L1698)
- `_apply_director_test_scaffold_fix` (L1987)
- `_apply_texture_import_fix` (L2066)
- `_apply_animation_controller_scaffold_fix` (L2122)
- `_apply_animation_controller_wireup_fix` (L2155)
- `workflow_quality_fix_command` (L2898)

Register:
```python
workflow_group.add_command(workflow_quality_fix_command)
```

- [ ] **Step 7: Create improve.py with improve-project command**

`cli_anything/unity_mcp/commands/workflows/improve.py` header:
```python
"""Workflow improve-project command."""
from __future__ import annotations
from ._group import workflow_group
from ._helpers import *  # noqa: F401, F403
```

Move (copy full bodies):
- `_render_improve_project_markdown` (L1028 in _helpers — already there, just import it)
- `workflow_improve_project_command` (L3117)

Register:
```python
workflow_group.add_command(workflow_improve_project_command)
```

- [ ] **Step 8: Create scaffold.py with remaining commands**

`cli_anything/unity_mcp/commands/workflows/scaffold.py` header:
```python
"""Workflow scaffold commands: sandbox-scene, bootstrap-guidance, validate-scene, wire-reference, create-prefab, reset-scene, create-behaviour."""
from __future__ import annotations
from ._group import workflow_group
from ._helpers import *  # noqa: F401, F403
```

Move (copy full bodies):
- `workflow_bootstrap_guidance_command` (L3566)
- `workflow_create_sandbox_scene_command` (L3680)
- `workflow_create_behaviour_command` (L3720)
- `workflow_reset_scene_command` (L3866)
- `workflow_wire_reference_command` (L4479)
- `workflow_create_prefab_command` (L4572)
- `workflow_validate_scene_command` (L4649)

Register all.

- [ ] **Step 9: Update __init__.py to import all domain modules (triggering command registration)**

`cli_anything/unity_mcp/commands/workflows/__init__.py`:
```python
"""Workflow command modules."""
from ._group import workflow_group
from . import inspect, audit, fix, improve, scaffold  # noqa: F401 — side-effect imports register commands

__all__ = ["workflow_group"]
```

- [ ] **Step 10: Replace commands/workflow.py with thin re-export**

`cli_anything/unity_mcp/commands/workflow.py` — replace entire file with:
```python
"""Workflow commands — thin re-export from split domain modules."""
from .workflows import workflow_group

__all__ = ["workflow_group"]
```

- [ ] **Step 11: Run tests**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/ -x -q 2>&1 | tail -15
```

Expected: all tests pass. If any fail, the most likely cause is a missing import in one of the domain files — check that every function referenced in a domain file is imported via `_helpers.py` or directly.

- [ ] **Step 12: Verify CLI still works**

```bash
py -3.12 -m cli_anything.unity_mcp.unity_mcp_cli workflow --help 2>&1 | head -20
```

Expected: full list of workflow subcommands visible.

- [ ] **Step 13: Commit**

```bash
git add cli_anything/unity_mcp/commands/workflows/ cli_anything/unity_mcp/commands/workflow.py
git commit -m "refactor(workflow): split 4.8k-line monolith into domain modules"
```

---

## Task 3: Split test_core.py by domain

**Files:**
- Create: `cli_anything/unity_mcp/tests/test_memory.py`
- Create: `cli_anything/unity_mcp/tests/test_coverage.py`
- Create: `cli_anything/unity_mcp/tests/test_heuristics.py`
- Create: `cli_anything/unity_mcp/tests/test_file_ipc.py`
- Modify: `cli_anything/unity_mcp/tests/test_core.py` → keep backend/client/routing tests only

- [ ] **Step 1: Identify test boundaries in test_core.py**

```bash
py -3.12 -c "
import ast, sys
src = open('cli_anything/unity_mcp/tests/test_core.py', encoding='utf-8').read()
tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and 'test_' in node.name:
        print(f'L{node.lineno}: {node.name}')
" | head -80
```

Categorize output by prefix:
- `test_memory_*`, `test_project_memory_*` → `test_memory.py`
- `test_tool_coverage_*`, `test_coverage_*` → `test_coverage.py`
- `test_error_heuristics_*`, `test_compilation_*` → `test_heuristics.py`
- `test_file_ipc_*`, `test_discover_*` → `test_file_ipc.py`
- Everything else → stays in `test_core.py`

- [ ] **Step 2: Create test_memory.py**

`cli_anything/unity_mcp/tests/test_memory.py`:
```python
"""Tests for core/memory.py — ProjectMemory, project-id persistence, recall."""
from __future__ import annotations
import unittest
# Copy all memory-related test methods from CoreTests in test_core.py here.
# Keep the same class structure: class MemoryTests(unittest.TestCase):
```

Move all `test_*` methods that test `ProjectMemory`, `memory_for_session`, project-id file creation, legacy hash migration, and `record_missing_references`.

- [ ] **Step 3: Create test_coverage.py**

`cli_anything/unity_mcp/tests/test_coverage.py`:
```python
"""Tests for core/tool_coverage.py — evidence buckets, summary, handoff plans."""
from __future__ import annotations
import unittest
# Copy all tool_coverage-related test methods here.
# class CoverageTests(unittest.TestCase):
```

- [ ] **Step 4: Create test_heuristics.py**

`cli_anything/unity_mcp/tests/test_heuristics.py`:
```python
"""Tests for core/error_heuristics.py — CS codes, Unity runtime patterns, doctor integration."""
from __future__ import annotations
import unittest
# Copy all error_heuristics-related test methods here.
# class HeuristicsTests(unittest.TestCase):
```

- [ ] **Step 5: Create test_file_ipc.py**

`cli_anything/unity_mcp/tests/test_file_ipc.py`:
```python
"""Tests for core/file_ipc.py — FileIPCClient, discovery, ping, roundtrip."""
from __future__ import annotations
import unittest
# Copy all file_ipc-related test methods here.
# class FileIPCTests(unittest.TestCase):
```

- [ ] **Step 6: Run all new test files individually**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/test_memory.py -v 2>&1 | tail -5
py -3.12 -m pytest cli_anything/unity_mcp/tests/test_coverage.py -v 2>&1 | tail -5
py -3.12 -m pytest cli_anything/unity_mcp/tests/test_heuristics.py -v 2>&1 | tail -5
py -3.12 -m pytest cli_anything/unity_mcp/tests/test_file_ipc.py -v 2>&1 | tail -5
```

Expected: all pass. Total count across new files should match what was removed from `test_core.py`.

- [ ] **Step 7: Run full suite**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/ -q 2>&1 | tail -5
```

Expected: same pass count as before (no tests lost, no tests duplicated).

- [ ] **Step 8: Commit**

```bash
git add cli_anything/unity_mcp/tests/test_memory.py cli_anything/unity_mcp/tests/test_coverage.py cli_anything/unity_mcp/tests/test_heuristics.py cli_anything/unity_mcp/tests/test_file_ipc.py cli_anything/unity_mcp/tests/test_core.py
git commit -m "refactor(tests): split test_core.py by domain"
```

---

## Task 4: Split test_full_e2e.py by domain

**Files:**
- Create: `cli_anything/unity_mcp/tests/mock_bridge.py`
- Create: `cli_anything/unity_mcp/tests/test_workflow_e2e.py`
- Create: `cli_anything/unity_mcp/tests/test_mock_routes.py`
- Create: `cli_anything/unity_mcp/tests/test_chat_e2e.py`
- Modify: `cli_anything/unity_mcp/tests/test_full_e2e.py` → thin re-export or delete

- [ ] **Step 1: Extract MockBridgeServer + MockBridgeHandler into mock_bridge.py**

`cli_anything/unity_mcp/tests/mock_bridge.py`:
```python
"""Shared mock Unity bridge infrastructure for e2e tests.

Import MockBridgeServer and MockBridgeHandler from here in all e2e test files.
"""
from __future__ import annotations
# Copy MockBridgeServer (L44) and MockBridgeHandler (L2623) in full from test_full_e2e.py
```

- [ ] **Step 2: Create test_workflow_e2e.py with workflow command tests**

`cli_anything/unity_mcp/tests/test_workflow_e2e.py`:
```python
"""E2E tests for workflow commands using the mock bridge."""
from __future__ import annotations
import unittest
from .mock_bridge import MockBridgeServer, MockBridgeHandler
# Copy all FullE2ETests methods that test workflow_* commands
# class WorkflowE2ETests(unittest.TestCase):
```

- [ ] **Step 3: Create test_mock_routes.py with mock-route coverage tests**

`cli_anything/unity_mcp/tests/test_mock_routes.py`:
```python
"""Tests verifying mock-only route coverage against MockBridgeHandler."""
from __future__ import annotations
import unittest
from .mock_bridge import MockBridgeServer, MockBridgeHandler
# Copy test_mock_only_advanced_routes_work_against_mock_bridge and related tests
# class MockRouteTests(unittest.TestCase):
```

- [ ] **Step 4: Create test_chat_e2e.py with agent chat + agent loop tests**

`cli_anything/unity_mcp/tests/test_chat_e2e.py`:
```python
"""E2E tests for agent chat and agent loop via mock bridge."""
from __future__ import annotations
import unittest
from .mock_bridge import MockBridgeServer, MockBridgeHandler
# Copy all chat/agent-loop related FullE2ETests methods
# class ChatE2ETests(unittest.TestCase):
```

- [ ] **Step 5: Run all new files**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/test_workflow_e2e.py -q 2>&1 | tail -5
py -3.12 -m pytest cli_anything/unity_mcp/tests/test_mock_routes.py -q 2>&1 | tail -5
py -3.12 -m pytest cli_anything/unity_mcp/tests/test_chat_e2e.py -q 2>&1 | tail -5
```

Expected: all pass.

- [ ] **Step 6: Run full suite**

```bash
py -3.12 -m pytest cli_anything/unity_mcp/tests/ -q 2>&1 | tail -5
```

Expected: same or higher pass count.

- [ ] **Step 7: Commit**

```bash
git add cli_anything/unity_mcp/tests/mock_bridge.py cli_anything/unity_mcp/tests/test_workflow_e2e.py cli_anything/unity_mcp/tests/test_mock_routes.py cli_anything/unity_mcp/tests/test_chat_e2e.py cli_anything/unity_mcp/tests/test_full_e2e.py
git commit -m "refactor(tests): split test_full_e2e.py into domain test files"
```

---

## Task 5: Compress docs

**Files:**
- Modify: `README.md`
- Modify: `TODO.md`
- Modify: `AGENTS.md`

**Target sizes:**
- `README.md`: ~200 lines. What it is, why different, quick install, 5 hero commands, links to AGENTS.md and TODO.md.
- `TODO.md`: ~150 lines. Current baseline, immediate priorities (ordered), execution tracks (brief). Cut all "What Was Built" history — that belongs in CHANGELOG.md.
- `AGENTS.md`: ~200 lines. Keep all commands, rules, and reference tables. Cut prose explanations that repeat what the commands already say.

- [ ] **Step 1: Compress README.md**

Target structure (200 lines max):
```markdown
# unity-mcp-agent-harness
[one-line description]

## What it is
[3-4 sentences: AI agent, Unity editor, specialist skills, learns your project]

## Why different
[3 bullets: File IPC, expert lenses, learns from outcomes]

## Install
[pip install command]

## Quick start
[5 hero commands with one-line descriptions]

## Documentation
- [AGENTS.md](AGENTS.md) — operating manual for AI agents
- [TODO.md](TODO.md) — roadmap and priorities
- [PLAN.md](../PLAN.md) — product strategy
```

- [ ] **Step 2: Compress TODO.md**

Keep:
- Current Baseline section (update numbers)
- Execution Tracks (Engine, Magic, Proof, Learning) — brief
- Immediate priorities P0/P1 ordered list
- Definition of Done
- Agent-to-Agent Notes (condensed)
- What NOT to duplicate

Cut entirely:
- All "What Was Built" narrative sections (history) — this is in CHANGELOG.md
- All "Latest X Pass" sections

- [ ] **Step 3: Compress AGENTS.md**

Keep:
- All command reference blocks (the powershell code blocks — these are used by AI agents)
- Command Selection Rules table
- Required Debugging Behavior steps
- Memory categories table
- Tool Coverage System (condensed)
- File IPC section (condensed to essential usage)
- Documentation Update Rule
- What Not To Do list

Cut:
- Long prose paragraphs that restate what commands already show
- Repeated examples that duplicate command blocks

- [ ] **Step 4: Verify line counts**

```bash
wc -l README.md TODO.md AGENTS.md
```

Expected: README <250, TODO <200, AGENTS <250.

- [ ] **Step 5: Commit**

```bash
git add README.md TODO.md AGENTS.md
git commit -m "docs: compress README, TODO, and AGENTS to contributor-readable length"
```

---

## Task 6: Update PLAN.md

**Files:**
- Modify: `../PLAN.md` (one level above agent-harness)

- [ ] **Step 1: Update phase completion status**

Add a `## Current Phase Status` section after `## Product Phases`:

```markdown
## Current Phase Status

| Phase | Status |
|-------|--------|
| Phase 1 — Reliable Control Surface | ✅ Complete |
| Phase 2 — Reusable Workflow Engine | ✅ Complete |
| Phase 3 — Visible Product Magic | 🔄 In Progress |
| Phase 4 — Expert Unity Developer Layer | 🔄 In Progress (lenses exist, build+polish missing) |
| Phase 5 — Model-Backed Orchestration | ⏳ Not started |
| Phase 6 — Proof and Benchmarks | 🔄 In Progress |
| Phase 7 — Learning System | 📋 Specced, not started |
```

- [ ] **Step 2: Move learning system to parallel track**

Add to `## Current Strategic Priority` section:

```markdown
## Learning System — Parallel Track

The learning system (Phase 7 in the original sequence) is being promoted to a **parallel track** that starts alongside Phase 3/4 work. Waiting for phases 5 and 6 to complete first is the wrong sequencing — the learning loop strengthens every other phase.

Start with: run ledger → structured memory → basic eval/replay. See `docs/superpowers/specs/2026-04-14-learning-system-design.md`.
```

- [ ] **Step 3: Update Immediate Product Focus**

Replace the existing `## Immediate Product Focus` with:

```markdown
## Immediate Product Focus

### Track 1 — Housekeeping (parallel, do once)
Split monolithic files, compress docs, merge stale branches. Unblocks contributors.
See: `docs/superpowers/plans/2026-04-14-track1-housekeeping.md`

### Track 2A — Chat → Action Pipeline (immediate product)
All three agent modes working end-to-end: reactive, watchdog, autonomous.
Visual proof after every action. Player prototype in one command.
See: `docs/superpowers/plans/2026-04-14-track2a-chat-action-pipeline.md`

### Track 2B — Specialist Skills (after 2A gate)
Flip expert lenses from audit-only to full lifecycle: build + polish + explain + learn.
Learning system MVP starts here in parallel.

### Track 3 — Polish + Proof (after 2A gate)
Panel UX, benchmarks, contributing guide, external validation.
```

- [ ] **Step 4: Commit**

```bash
git add ../PLAN.md
git commit -m "docs: update PLAN.md with phase status and parallel track roadmap"
```

---

## Verification

After all tasks complete:

```bash
# Full test suite
py -3.12 -m pytest cli_anything/unity_mcp/tests/ -q 2>&1 | tail -5

# CLI smoke test
py -3.12 -m cli_anything.unity_mcp.unity_mcp_cli workflow --help 2>&1 | head -25
py -3.12 -m cli_anything.unity_mcp.unity_mcp_cli workflow inspect --help 2>&1 | head -10

# File size check
python3 -c "
import os
files = [
    'cli_anything/unity_mcp/commands/workflow.py',
    'cli_anything/unity_mcp/commands/workflows/inspect.py',
    'cli_anything/unity_mcp/commands/workflows/audit.py',
    'cli_anything/unity_mcp/commands/workflows/fix.py',
    'cli_anything/unity_mcp/commands/workflows/improve.py',
    'cli_anything/unity_mcp/commands/workflows/scaffold.py',
]
for f in files:
    lines = open(f, encoding='utf-8').readlines()
    print(f'{len(lines):>5} lines  {f}')
"
```

Expected: `workflow.py` drops to ~5 lines. Each domain module under 600 lines.

**Exit gate:** any contributor can open `commands/workflows/` and immediately find any workflow by domain name.
