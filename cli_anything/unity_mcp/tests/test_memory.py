"""Tests for core/memory.py — ProjectMemory, project-id persistence, recall, agent/developer profiles."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from cli_anything.unity_mcp.core.agent_profiles import AgentProfileStore, derive_agent_profiles_path
from cli_anything.unity_mcp.core.developer_profiles import DeveloperProfileStore, derive_developer_profiles_path
from cli_anything.unity_mcp.core.memory import ProjectMemory


class MemoryTests(unittest.TestCase):

    def test_project_memory_tracks_recurring_and_resolved_missing_references(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            memory = ProjectMemory("C:/Projects/Demo", store_root=tmpdir, allow_fallback=False)
            issue = {
                "path": "MainScene/Player",
                "component": "PlayerController",
                "issue": "Missing object reference",
            }

            first = memory.record_missing_references([issue], "MainScene")
            second = memory.record_missing_references([issue], "MainScene")
            recurring = memory.get_recurring_missing_refs()
            resolved = memory.record_missing_references([], "MainScene")

            self.assertEqual(len(first["newIssues"]), 1)
            self.assertEqual(first["recurringIssues"], [])
            self.assertEqual(second["recurringIssues"][0]["seenCount"], 2)
            self.assertEqual(recurring[0]["gameObject"], "MainScene/Player")
            self.assertEqual(recurring[0]["seenCount"], 2)
            self.assertEqual(resolved["resolvedIssues"][0]["gameObject"], "MainScene/Player")
            self.assertEqual(resolved["totalTracked"], 0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_project_memory_tracks_recurring_and_resolved_compilation_errors(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            memory = ProjectMemory("C:/Projects/Demo", store_root=tmpdir, allow_fallback=False)
            entry = {
                "message": (
                    "Assets/Scripts/Player.cs(12,8): error CS0246: "
                    "The type or namespace name 'Foo' could not be found"
                )
            }

            first = memory.record_compilation_errors([entry], "MainScene")
            second = memory.record_compilation_errors([entry], "MainScene")
            recurring = memory.get_recurring_compilation_errors()
            resolved = memory.record_compilation_errors([], "MainScene")

            self.assertEqual(len(first["newIssues"]), 1)
            self.assertEqual(first["recurringIssues"], [])
            self.assertEqual(second["recurringIssues"][0]["seenCount"], 2)
            self.assertEqual(recurring[0]["code"], "CS0246")
            self.assertEqual(recurring[0]["file"], "Assets/Scripts/Player.cs")
            self.assertEqual(resolved["resolvedIssues"][0]["code"], "CS0246")
            self.assertEqual(resolved["totalTracked"], 0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_project_memory_tracks_recurring_operational_signals(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            memory = ProjectMemory("C:/Projects/Demo", store_root=tmpdir, allow_fallback=False)
            queue_signal = {
                "kind": "queue",
                "key": "queue-contention",
                "title": "Queue contention",
                "detail": "Queue still had active work pending.",
            }

            first = memory.record_operational_signals([queue_signal], "MainScene")
            second = memory.record_operational_signals([queue_signal], "MainScene")
            recurring = memory.get_recurring_operational_signals()
            resolved = memory.record_operational_signals([], "MainScene")

            self.assertEqual(len(first["newIssues"]), 1)
            self.assertEqual(first["recurringIssues"], [])
            self.assertEqual(second["recurringIssues"][0]["seenCount"], 2)
            self.assertEqual(recurring[0]["kind"], "queue")
            self.assertEqual(recurring[0]["key"], "queue-contention")
            self.assertEqual(resolved["resolvedIssues"][0]["kind"], "queue")
            self.assertEqual(resolved["totalTracked"], 0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_project_memory_summarizes_queue_trends(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            memory = ProjectMemory("C:/Projects/Demo", store_root=tmpdir, allow_fallback=False)
            memory.record_queue_snapshot({"totalQueued": 2, "activeAgents": 1}, "MainScene")
            memory.record_queue_snapshot({"totalQueued": 2, "activeAgents": 1}, "MainScene")
            summary = memory.record_queue_snapshot({"totalQueued": 2, "activeAgents": 1}, "MainScene")

            self.assertEqual(summary["status"], "stalled-backlog-suspected")
            self.assertEqual(summary["sampleCount"], 3)
            self.assertEqual(summary["consecutiveBacklogSamples"], 3)
            self.assertEqual(summary["peakQueued"], 2)
            self.assertEqual(summary["latestActiveAgents"], 1)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_project_memory_selection_summary_is_compact_and_public(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            memory = ProjectMemory("C:/Projects/Demo", store_root=tmpdir, allow_fallback=False)
            issue = {
                "path": "MainScene/Player",
                "component": "PlayerController",
                "issue": "Missing object reference",
            }
            memory.remember_structure("render_pipeline", "URP")
            memory.remember_structure("_last_doctor_state", {"findings": []})
            memory.remember_fix(
                "CS0246",
                "cli-anything-unity-mcp --json debug doctor",
                context="Missing namespace or package.",
            )
            memory.record_missing_references([issue], "MainScene")
            memory.record_missing_references([issue], "MainScene")

            summary = memory.summarize_for_selection(max_fixes=1, max_recurring=1)

            self.assertIsNotNone(summary)
            assert summary is not None
            self.assertEqual(summary["totalEntries"], 4)
            self.assertEqual(summary["structure"]["render_pipeline"], "URP")
            self.assertNotIn("_last_doctor_state", summary["structure"])
            self.assertEqual(summary["knownFixes"][0]["pattern"], "CS0246")
            self.assertEqual(summary["recurringMissingRefs"][0]["gameObject"], "MainScene/Player")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_project_memory_explicit_roots_do_not_read_workspace_fallback(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        original_cwd = Path.cwd()
        original_env = os.environ.get("CLI_ANYTHING_UNITY_MCP_MEMORY_DIR")
        try:
            os.chdir(tmpdir)
            fallback_root = tmpdir / ".cli-anything-unity-mcp" / "memory"
            fallback_memory = ProjectMemory(
                "C:/Projects/Demo",
                store_root=fallback_root,
                allow_fallback=False,
            )
            fallback_memory.save("pattern", "stale_fallback", {"value": "do not read this"})

            explicit_memory = ProjectMemory("C:/Projects/Demo", store_root=tmpdir / "explicit")
            self.assertEqual(explicit_memory.recall(), [])

            os.environ["CLI_ANYTHING_UNITY_MCP_MEMORY_DIR"] = str(tmpdir / "env")
            env_memory = ProjectMemory("C:/Projects/Demo")
            self.assertEqual(env_memory.recall(), [])
        finally:
            if original_env is None:
                os.environ.pop("CLI_ANYTHING_UNITY_MCP_MEMORY_DIR", None)
            else:
                os.environ["CLI_ANYTHING_UNITY_MCP_MEMORY_DIR"] = original_env
            os.chdir(original_cwd)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_project_memory_uses_persisted_project_id_across_path_moves(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            store_root = tmpdir / "memory"
            original_project = tmpdir / "ProjectA"
            original_project.mkdir(parents=True, exist_ok=True)
            project_id_path = original_project / ".umcp" / "project-id"
            project_id_path.parent.mkdir(parents=True, exist_ok=True)
            project_id_path.write_text("demo-project-id", encoding="utf-8")

            memory = ProjectMemory(str(original_project), store_root=store_root, allow_fallback=False)
            memory.save("pattern", "scene_hygiene", {"value": "keep"})

            moved_project = tmpdir / "ProjectMoved"
            shutil.move(str(original_project), moved_project)

            moved_memory = ProjectMemory(str(moved_project), store_root=store_root, allow_fallback=False)

            self.assertEqual(moved_memory.project_id, "demo-project-id")
            self.assertEqual(moved_memory.recall(category="pattern")[0]["content"]["value"], "keep")
            self.assertEqual(
                moved_memory.stats()["storePath"],
                str(store_root / "demo-project-id.json"),
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_project_memory_migrates_legacy_path_hash_store_to_persisted_project_id(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            store_root = tmpdir / "memory"
            store_root.mkdir(parents=True, exist_ok=True)
            project_root = tmpdir / "LegacyProject"
            project_root.mkdir(parents=True, exist_ok=True)
            legacy_id = hashlib.sha256(str(project_root).encode("utf-8")).hexdigest()[:8]
            legacy_path = store_root / f"{legacy_id}.json"
            legacy_path.write_text(
                json.dumps(
                    {
                        "projectPath": str(project_root),
                        "entries": {
                            "pattern:legacy_fix": {
                                "category": "pattern",
                                "key": "legacy_fix",
                                "content": {"value": "still here"},
                                "created": "2026-01-01T00:00:00+00:00",
                                "updated": "2026-01-01T00:00:00+00:00",
                                "hit_count": 0,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            project_id_path = project_root / ".umcp" / "project-id"
            project_id_path.parent.mkdir(parents=True, exist_ok=True)
            project_id_path.write_text("stable-project-id", encoding="utf-8")

            memory = ProjectMemory(str(project_root), store_root=store_root, allow_fallback=False)

            self.assertEqual(memory.project_id, "stable-project-id")
            self.assertEqual(memory.recall(category="pattern")[0]["content"]["value"], "still here")

            migrated_path = store_root / "stable-project-id.json"
            self.assertTrue(migrated_path.exists())
            migrated = json.loads(migrated_path.read_text(encoding="utf-8"))
            self.assertEqual(migrated["projectPath"], str(project_root))
            self.assertIn("pattern:legacy_fix", migrated["entries"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_agent_profile_store_persists_selection_and_profiles(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            session_path = tmpdir / "session.json"
            store = AgentProfileStore(derive_agent_profiles_path(session_path))
            state = store.upsert_profile(
                name="reviewer",
                agent_id="cli-anything-unity-mcp-reviewer",
                role="reviewer",
                description="Optional sidecar reviewer",
                legacy=False,
                select=True,
            )

            self.assertEqual(state.selected_profile, "reviewer")
            profile = store.get_profile("reviewer")
            self.assertIsNotNone(profile)
            assert profile is not None
            self.assertEqual(profile.agent_id, "cli-anything-unity-mcp-reviewer")
            self.assertEqual(profile.role, "reviewer")

            state = store.select_profile("reviewer")
            self.assertEqual(state.selected_profile, "reviewer")

            state = store.remove_profile("reviewer")
            self.assertEqual(state.selected_profile, None)
            self.assertEqual(state.profiles, [])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_developer_profile_store_defaults_to_normal_and_persists_selection(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            session_path = tmpdir / "session.json"
            store = DeveloperProfileStore(derive_developer_profiles_path(session_path))

            default_profile = store.default_profile()
            self.assertEqual(default_profile.name, "normal")

            state = store.list_profiles()
            self.assertEqual(state.selected_profile, None)
            self.assertEqual(
                [profile.name for profile in state.profiles],
                [
                    "animator",
                    "builder",
                    "caveman",
                    "director",
                    "level-designer",
                    "normal",
                    "physics",
                    "review",
                    "systems",
                    "tech-artist",
                    "ui-designer",
                ],
            )

            state = store.select_profile("caveman")
            self.assertEqual(state.selected_profile, "caveman")

            selected = store.get_profile(state.selected_profile)
            self.assertIsNotNone(selected)
            assert selected is not None
            self.assertEqual(selected.token_strategy, "aggressive-saver")

            cleared = store.clear_selection()
            self.assertEqual(cleared.selected_profile, None)
            self.assertEqual(store.default_profile().name, "normal")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_developer_profiles_include_unity_expert_profiles(self) -> None:
        store = DeveloperProfileStore(path=Path("test-developer-profiles.json"))

        names = {profile.name for profile in store.list_profiles().profiles}

        self.assertTrue(
            {"director", "animator", "physics", "systems", "tech-artist", "ui-designer", "level-designer"} <= names
        )
