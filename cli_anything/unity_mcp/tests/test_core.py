from __future__ import annotations

import hashlib
import json
import os
import shutil
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from urllib.request import Request, urlopen

from cli_anything.unity_mcp.core.agent_profiles import AgentProfileStore, derive_agent_profiles_path
from cli_anything.unity_mcp.core.agent_chat import ChatBridge, _OfflineUnityAssistant
from cli_anything.unity_mcp.core.developer_profiles import DeveloperProfileStore, derive_developer_profiles_path
from cli_anything.unity_mcp.core.debug_dashboard import DashboardConfig, serve_debug_dashboard
from cli_anything.unity_mcp.core.debug_doctor import build_debug_doctor_report
from cli_anything.unity_mcp.core.embedded_cli import EmbeddedCLIOptions, run_cli_json
from cli_anything.unity_mcp.core.mcp_tools import get_mcp_tool, iter_mcp_tools
from cli_anything.unity_mcp.core.project_guidance import build_guidance_bundle, write_guidance_bundle
from cli_anything.unity_mcp.core.project_insights import build_asset_audit_report, build_project_insights
from cli_anything.unity_mcp.core.client import UnityMCPClientError, UnityMCPConnectionError, UnityMCPHTTPError
from cli_anything.unity_mcp.core.memory import ProjectMemory
from cli_anything.unity_mcp.core.routes import route_to_tool_name, tool_name_to_route
from cli_anything.unity_mcp.core.session import SessionState, SessionStore
from cli_anything.unity_mcp.core.tool_coverage import build_tool_coverage_matrix
from cli_anything.unity_mcp.core.workflows import build_behaviour_script
from cli_anything.unity_mcp.commands._shared import _format_cli_exception_message, _format_failed_route_hint
from cli_anything.unity_mcp.unity_mcp_cli import _humanize_history_entry, _summarize_trace_entries
from scripts.run_live_mcp_pass import (
    _build_profile_plan,
    _default_report_file,
    _format_live_pass_summary,
    _summarize_live_pass_report,
)
from cli_anything.unity_mcp.core.file_ipc import (
    ContextInjector,
    FileIPCClient,
    FileIPCConnectionError,
    FileIPCError,
    FileIPCTimeoutError,
    _atomic_write,
    _safe_read_json,
    discover_file_ipc_instances,
)
from cli_anything.unity_mcp.utils.unity_mcp_backend import (
    BackendSelectionError,
    UnityMCPBackend,
)


class FakeClient:
    def __init__(self, pings: dict[int, dict]) -> None:
        self.pings = pings
        self.use_queue = True

    def ping(self, port: int, timeout: float | None = None) -> dict:
        if port not in self.pings:
            raise UnityMCPClientError("bridge unavailable")
        return self.pings[port]


class RebindingClient(FakeClient):
    def __init__(self, pings: dict[int, dict]) -> None:
        super().__init__(pings)
        self.route_calls: list[int] = []

    def call_route(self, port: int, route: str, params: dict | None = None) -> dict:
        self.route_calls.append(port)
        if port == 7890:
            raise UnityMCPConnectionError("old port is unavailable")
        return {"success": True, "route": route, "port": port, "params": params or {}}


class CatalogClient(FakeClient):
    def __init__(self, pings: dict[int, dict]) -> None:
        super().__init__(pings)
        self.calls: list[tuple[str, int, dict]] = []

    def call_route(self, port: int, route: str, params: dict | None = None) -> dict:
        self.calls.append((route, port, params or {}))
        return {"success": True, "route": route, "port": port, "params": params or {}}


class ErrorRouteClient(FakeClient):
    def call_route(self, port: int, route: str, params: dict | None = None) -> dict:
        raise UnityMCPClientError(f"route failed: {route}")


class ContextFallbackClient(FakeClient):
    def __init__(self, pings: dict[int, dict]) -> None:
        super().__init__(pings)
        self.route_calls: list[tuple[int, str, dict]] = []
        self.get_calls: list[tuple[int, str]] = []

    def call_route(self, port: int, route: str, params: dict | None = None) -> dict:
        self.route_calls.append((port, route, params or {}))
        raise UnityMCPHTTPError(404, "not found")

    def get_api(self, port: int, api_path: str, query: dict | None = None, timeout: float | None = None) -> dict:
        self.get_calls.append((port, api_path))
        return {"projectPath": "C:/Projects/Demo", "apiPath": api_path}


class ContextQueueUnknownClient(FakeClient):
    def __init__(self, pings: dict[int, dict]) -> None:
        super().__init__(pings)
        self.route_calls: list[tuple[int, str, dict]] = []
        self.get_calls: list[tuple[int, str]] = []

    def call_route(self, port: int, route: str, params: dict | None = None) -> dict:
        self.route_calls.append((port, route, params or {}))
        if route == "context":
            return {"error": "Unknown API endpoint: context"}
        if route == "editor/execute-code":
            return {
                "success": True,
                "result": {
                    "enabled": True,
                    "contextPath": "Assets/MCP/Context",
                    "fileCount": 1,
                    "categories": [
                        {
                            "category": "Architecture",
                            "content": "Main-thread-safe context.",
                        }
                    ],
                },
            }
        return {"error": f"Unexpected route: {route}"}

    def get_api(self, port: int, api_path: str, query: dict | None = None, timeout: float | None = None) -> dict:
        self.get_calls.append((port, api_path))
        raise AssertionError("context queue fallback should not use direct GET when execute-code works")


class RebindingBackend(UnityMCPBackend):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.discovery_calls = 0

    def discover_instances(self) -> list[dict]:
        self.discovery_calls += 1
        if self.discovery_calls < 2:
            return []
        return [
            {
                "port": 7891,
                "projectName": "Demo",
                "projectPath": "C:/Projects/Demo",
                "unityVersion": "6000.0.0f1",
                "platform": "WindowsEditor",
                "isClone": False,
                "cloneIndex": -1,
                "processId": 1234,
                "source": "portscan",
            }
        ]


class NeverRecoveringBackend(UnityMCPBackend):
    def discover_instances(self) -> list[dict]:
        return []


class DashboardBackendStub:
    def __init__(self) -> None:
        self.preferences = {
            "unityConsoleBreadcrumbs": True,
            "dashboardAutoRefresh": False,
            "dashboardRefreshSeconds": 5.0,
            "dashboardConsoleCount": 20,
            "dashboardIssueLimit": 20,
            "dashboardIncludeHierarchy": False,
            "dashboardEditorLogTail": 40,
            "dashboardAbUmcpOnly": False,
        }
        self.last_state_args: dict[str, Any] | None = None
        self.last_live_args: dict[str, Any] | None = None

    def get_debug_preferences(self) -> dict[str, Any]:
        return dict(self.preferences)

    def update_debug_preferences(self, **updates: Any) -> dict[str, Any]:
        self.preferences.update({key: value for key, value in updates.items() if value is not None})
        return dict(self.preferences)

    def build_debug_dashboard_state(
        self,
        *,
        port: int | None = None,
        console_count: int = 40,
        message_type: str = "all",
        issue_limit: int = 20,
        include_hierarchy: bool = False,
        editor_log_tail: int = 80,
        editor_log_contains: str | None = None,
        ab_umcp_only: bool = False,
        trace_tail: int = 20,
        history_formatter: Any = None,
    ) -> dict[str, Any]:
        self.last_state_args = {
            "port": port,
            "console_count": console_count,
            "message_type": message_type,
            "issue_limit": issue_limit,
            "include_hierarchy": include_hierarchy,
            "editor_log_tail": editor_log_tail,
            "editor_log_contains": editor_log_contains,
            "ab_umcp_only": ab_umcp_only,
            "trace_tail": trace_tail,
            "history_formatter": history_formatter,
        }
        return {
            "title": "Unity Debug Dashboard",
            "generatedAt": 123.0,
            "preferences": dict(self.preferences),
            "snapshot": {
                "summary": {
                    "projectName": "Demo",
                    "activeScene": "MainScene",
                    "sceneDirty": False,
                    "consoleEntryCount": 1,
                    "consoleHighestSeverity": "info",
                    "queueQueuedRequests": 0,
                },
                "editorState": {"isPlaying": False, "isCompiling": False},
                "consoleSummary": {"highestSeverity": "info"},
                "console": {"entries": [{"type": "info", "message": "ok"}]},
                "compilation": {"count": 0, "entries": []},
                "missingReferences": {"totalFound": 0, "results": []},
                "queue": {"totalQueued": 0, "activeAgents": 0},
                "cameraDiagnostics": {},
            },
            "bridge": {"summary": {"assessment": "healthy"}},
            "editorLog": {
                "summary": {"status": "ok", "returnedCount": 1},
                "entries": [{"lineNumber": 1, "text": "[AB-UMCP] Server started", "matched": True}],
            },
            "trace": {"entries": [{"summary": "Checking project info", "phase": "inspect"}]},
            "request": {"port": port},
        }

    def build_debug_dashboard_live_state(
        self,
        *,
        port: int | None = None,
        console_count: int = 20,
        message_type: str = "all",
        trace_tail: int = 20,
        history_formatter: Any = None,
    ) -> dict[str, Any]:
        self.last_live_args = {
            "port": port,
            "console_count": console_count,
            "message_type": message_type,
            "trace_tail": trace_tail,
            "history_formatter": history_formatter,
        }
        return {
            "title": "Unity Debug Dashboard",
            "generatedAt": 124.0,
            "preferences": dict(self.preferences),
            "snapshot": {
                "summary": {
                    "projectName": "Demo",
                    "activeScene": "LiveScene",
                    "sceneDirty": False,
                    "consoleEntryCount": 1,
                    "consoleHighestSeverity": "info",
                    "queueQueuedRequests": 0,
                },
                "editorState": {"isPlaying": False, "isCompiling": False},
                "consoleSummary": {"highestSeverity": "info"},
                "console": {"entries": [{"type": "info", "message": "live"}]},
                "compilation": {"count": 0, "entries": []},
                "missingReferences": {"totalFound": 0, "results": []},
                "queue": {"totalQueued": 0, "activeAgents": 0},
            },
            "trace": {"entries": [{"summary": "Inspecting scene info", "phase": "inspect"}]},
            "request": {"port": port},
        }


class CoreTests(unittest.TestCase):
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

    def test_embedded_cli_runner_returns_json_payload(self) -> None:
        payload = run_cli_json(["tool-template", "unity_scene_stats"], EmbeddedCLIOptions())

        self.assertEqual(payload["name"], "unity_scene_stats")
        self.assertEqual(payload["route"], "search/scene-stats")
        self.assertIn("template", payload)

    def test_tool_coverage_matrix_marks_live_tested_and_deferred_tools(self) -> None:
        payload = build_tool_coverage_matrix(category="terrain")

        tools = {tool["name"]: tool for tool in payload["tools"]}
        self.assertEqual(tools["unity_terrain_create"]["coverageStatus"], "live-tested")
        self.assertEqual(tools["unity_terrain_info"]["coverageStatus"], "live-tested")
        # terrain/create-grid is now mock-only (promoted from deferred in this session).
        self.assertEqual(tools["unity_terrain_create_grid"]["coverageStatus"], "mock-only")
        self.assertIn("mock Unity bridge", tools["unity_terrain_create_grid"]["coverageNote"])
        self.assertGreaterEqual(payload["summary"]["countsByStatus"]["live-tested"], 1)

        full_payload = build_tool_coverage_matrix()
        all_tools = {tool["name"]: tool for tool in full_payload["tools"]}
        for name in (
            "unity_animation_add_parameter",
            "unity_animation_add_state",
            "unity_animation_set_default_state",
            "unity_animation_add_transition",
            "unity_animation_assign_controller",
            "unity_animation_clip_info",
            "unity_animation_controller_info",
            "unity_asset_create_prefab",
            "unity_asset_instantiate_prefab",
            "unity_graphics_material_info",
            "unity_graphics_renderer_info",
            "unity_material_create",
            "unity_prefab_info",
            "unity_renderer_set_material",
        ):
            self.assertEqual(all_tools[name]["coverageStatus"], "live-tested", name)
            self.assertEqual(all_tools[name]["coverageBlocker"], "verified-live", name)
            if name.startswith("unity_animation_"):
                self.assertIn("standalone File IPC", all_tools[name]["coverageNote"], name)
            else:
                self.assertIn("standalone File IPC prefab/material/renderer parity probe", all_tools[name]["coverageNote"], name)
        for name in (
            "unity_agents_list",
            "unity_advanced_tool",
            "unity_console_log",
            "unity_list_advanced_tools",
            "unity_list_instances",
            "unity_select_instance",
        ):
            self.assertEqual(all_tools[name]["coverageStatus"], "covered", name)
            self.assertEqual(all_tools[name]["coverageBlocker"], "verified-automated", name)

    def test_file_ipc_bridge_owns_public_prefab_material_renderer_routes(self) -> None:
        bridge_path = (
            Path(__file__).resolve().parents[3]
            / "unity-scripts"
            / "Editor"
            / "FileIPCBridge.cs"
        )
        source = bridge_path.read_text(encoding="utf-8")

        for route in (
            "asset/create-material",
            "asset/create-prefab",
            "asset/instantiate-prefab",
            "renderer/set-material",
            "graphics/material-info",
            "graphics/renderer-info",
        ):
            self.assertIn(f'"{route}"', source)

    def test_tool_coverage_matrix_marks_mock_only_focused_routes(self) -> None:
        payload = build_tool_coverage_matrix()

        tools = {tool["name"]: tool for tool in payload["tools"]}
        for name in (
            "unity_ui_create_element",
            "unity_ui_set_text",
            "unity_ui_set_image",
            "unity_lighting_create_light_probe_group",
            "unity_lighting_create_reflection_probe",
            "unity_lighting_set_environment",
            "unity_animation_add_event",
            "unity_animation_get_curve_keyframes",
            "unity_animation_get_events",
            "unity_terrain_get_heights_region",
            "unity_terrain_get_steepness",
            "unity_terrain_get_tree_instances",
            "unity_terrain_list",
            "unity_playerprefs_get",
            "unity_playerprefs_set",
            "unity_playerprefs_delete",
            "unity_playerprefs_delete_all",
            "unity_input_add_action",
            "unity_input_add_binding",
            "unity_input_add_composite_binding",
            "unity_input_add_map",
            "unity_input_remove_action",
            "unity_input_remove_map",
            "unity_spriteatlas_add",
            "unity_spriteatlas_create",
            "unity_spriteatlas_delete",
            "unity_spriteatlas_info",
            "unity_spriteatlas_list",
            "unity_spriteatlas_remove",
            "unity_spriteatlas_settings",
            "unity_mppm_activate_scenario",
            "unity_mppm_info",
            "unity_mppm_list_scenarios",
            "unity_mppm_start",
            "unity_mppm_status",
            "unity_mppm_stop",
        ):
            self.assertEqual(tools[name]["coverageStatus"], "mock-only", name)
            self.assertEqual(tools[name]["coverageBlocker"], "verified-mock", name)
            self.assertIn("mock Unity bridge", tools[name]["coverageNote"], name)

    def test_tool_coverage_matrix_can_build_next_agent_batch(self) -> None:
        # Use "amplify" category — package-dependent, stays deferred long-term.
        payload = build_tool_coverage_matrix(
            category="amplify",
            status="deferred",
            summary_only=True,
            next_batch_limit=3,
        )

        self.assertNotIn("tools", payload)
        self.assertEqual(payload["summary"]["filters"]["nextBatchLimit"], 3)
        self.assertGreaterEqual(len(payload["nextBatch"]), 1)
        self.assertLessEqual(len(payload["nextBatch"]), 3)
        candidate = payload["nextBatch"][0]
        self.assertEqual(candidate["coverageStatus"], "deferred")
        self.assertEqual(candidate["category"], "amplify")
        self.assertEqual(candidate["coverageBlocker"], "package-dependent-live-audit")
        self.assertEqual(candidate["fixtureHint"]["package"], "Amplify Shader Editor")
        self.assertIn("Assets/CLIAnythingFixtures/Amplify", candidate["fixtureHint"]["fixtureRoot"])
        self.assertIn(candidate["risk"], {"read-only", "safe-mutation", "stateful-mutation", "destructive"})
        self.assertIn("cli-anything-unity-mcp --json tool-info", candidate["recommendedCommands"][0])
        self.assertIn("cli-anything-unity-mcp --json tool-template", candidate["recommendedCommands"][1])
        self.assertIn("disposable Unity project", candidate["handoffPrompt"])
        self.assertIn("preflight", candidate["handoffPrompt"])

    def test_tool_coverage_matrix_can_build_package_fixture_plans(self) -> None:
        payload = build_tool_coverage_matrix(
            status="deferred",
            summary_only=True,
            fixture_plan=True,
        )

        self.assertNotIn("tools", payload)
        self.assertTrue(payload["summary"]["filters"]["fixturePlan"])
        plans = {plan["category"]: plan for plan in payload["fixturePlans"]}
        self.assertEqual(sorted(plans), ["amplify", "uma"])
        self.assertEqual(plans["amplify"]["package"], "Amplify Shader Editor")
        self.assertEqual(plans["amplify"]["deferredToolCount"], 23)
        self.assertEqual(plans["uma"]["package"], "UMA / UMA DCS")
        self.assertEqual(plans["uma"]["deferredToolCount"], 15)
        self.assertIn("Assets/CLIAnythingFixtures/Amplify", plans["amplify"]["fixtureRoot"])
        self.assertIn("unity_amplify_status", plans["amplify"]["preflight"])
        self.assertIn("--next-batch 10", plans["amplify"]["recommendedCommands"][0])
        self.assertIn("preflight commands first", plans["amplify"]["handoffPrompt"])
        self.assertIn("readOnlyFirst", plans["amplify"])
        self.assertIn("safeMutationNext", plans["amplify"])
        self.assertIn("statefulMutationLater", plans["amplify"])
        self.assertIn("destructiveLast", plans["amplify"])

    def test_tool_coverage_matrix_can_build_unsupported_support_plans(self) -> None:
        payload = build_tool_coverage_matrix(
            status="unsupported",
            summary_only=True,
            support_plan=True,
        )

        self.assertNotIn("tools", payload)
        self.assertTrue(payload["summary"]["filters"]["supportPlan"])
        support_plans = {plan["category"]: plan for plan in payload["supportPlans"]}
        self.assertEqual(sorted(support_plans), ["hub"])
        hub_plan = support_plans["hub"]
        self.assertEqual(hub_plan["coverageBlocker"], "unity-hub-integration")
        self.assertEqual(hub_plan["toolCount"], 6)
        self.assertIn("unity_hub_list_editors", {tool["name"] for tool in hub_plan["tools"]})
        self.assertIn("read-only editor discovery", hub_plan["handoffPrompt"])
        self.assertIn("cli-anything-unity-mcp --json tool-info unity_hub_list_editors", hub_plan["recommendedCommands"])
        self.assertGreaterEqual(len(hub_plan["safeImplementationOrder"]), 3)

    def test_tool_coverage_matrix_can_build_cross_track_handoff_plan(self) -> None:
        payload = build_tool_coverage_matrix(
            summary_only=True,
            handoff_plan=True,
        )

        self.assertNotIn("tools", payload)
        self.assertTrue(payload["summary"]["filters"]["handoffPlan"])
        handoff = payload["handoffPlan"]
        self.assertEqual(handoff["remainingToolCount"], 44)
        self.assertEqual(handoff["deferredToolCount"], 38)
        self.assertEqual(handoff["unsupportedToolCount"], 6)
        self.assertEqual(handoff["deferredByBlocker"], {"package-dependent-live-audit": 38})
        self.assertEqual(handoff["unsupportedByBlocker"], {"unity-hub-integration": 6})
        tracks = {track["name"]: track for track in handoff["tracks"]}
        self.assertEqual(sorted(tracks), ["optional-package-live-audits", "unity-hub-backend"])
        self.assertEqual(tracks["optional-package-live-audits"]["categories"], ["amplify", "uma"])
        self.assertEqual(tracks["optional-package-live-audits"]["toolCount"], 38)
        self.assertEqual(tracks["unity-hub-backend"]["categories"], ["hub"])
        self.assertEqual(tracks["unity-hub-backend"]["toolCount"], 6)
        self.assertIn("--fixture-plan", tracks["optional-package-live-audits"]["nextCommand"])
        self.assertIn("--support-plan", tracks["unity-hub-backend"]["nextCommand"])
        self.assertIn("coverage work", handoff["handoffPrompt"])

    def test_tool_coverage_matrix_explains_hub_tools_as_unity_hub_integration_gap(self) -> None:
        payload = build_tool_coverage_matrix(category="hub")

        tools = {tool["name"]: tool for tool in payload["tools"]}
        self.assertEqual(tools["unity_hub_list_editors"]["coverageStatus"], "unsupported")
        self.assertEqual(tools["unity_hub_list_editors"]["coverageBlocker"], "unity-hub-integration")
        self.assertIn("Unity Hub integration", tools["unity_hub_list_editors"]["coverageNote"])

    def test_live_pass_profile_plan_supports_focused_profiles_and_heavy_overlay(self) -> None:
        terrain_plan = _build_profile_plan("terrain")
        self.assertEqual(terrain_plan["advancedCategory"], "terrain")
        self.assertEqual(terrain_plan["toolInfoTool"], "unity_terrain_info")
        self.assertEqual(terrain_plan["toolCallTool"], "unity_terrain_info")
        self.assertEqual(terrain_plan["auditCategories"], ["terrain", "lighting", "navmesh"])

        ui_heavy_plan = _build_profile_plan("ui", include_heavy=True)
        self.assertEqual(ui_heavy_plan["advancedCategory"], "ui")
        self.assertIn("terrain", ui_heavy_plan["auditCategories"])
        self.assertIn("shadergraph", ui_heavy_plan["auditCategories"])
        self.assertGreaterEqual(
            len(ui_heavy_plan["auditCategories"]),
            len(terrain_plan["auditCategories"]),
        )

    def test_live_pass_default_report_file_uses_profile_name(self) -> None:
        report_file = _default_report_file(
            Path("C:/Temp/.cli-anything-unity-mcp"),
            "lighting",
            timestamp="20260409-120000",
        )
        self.assertEqual(
            str(report_file).replace("\\", "/"),
            "C:/Temp/.cli-anything-unity-mcp/live-pass-lighting-20260409-120000.json",
        )

    def test_live_pass_summary_highlights_failures_timeouts_and_port_hops(self) -> None:
        report = {
            "steps": [
                {
                    "name": "unity_select_instance",
                    "status": "passed",
                    "durationMs": 12.0,
                    "result": {"selectedPort": 7891},
                },
                {
                    "name": "unity_inspect",
                    "status": "passed",
                    "durationMs": 130.25,
                    "result": {"summary": {"port": 7892}},
                },
                {
                    "name": "unity_play(play)",
                    "status": "failed",
                    "durationMs": 20000.0,
                    "result": {"timedOut": True, "error": "play mode did not settle"},
                    "consoleSnapshot": {
                        "status": "passed",
                        "result": {
                            "entries": [
                                {
                                    "type": "error",
                                    "message": "Input exception during play mode",
                                }
                            ]
                        },
                    },
                },
            ],
            "summary": {
                "port": 7891,
                "passed": 2,
                "failed": 1,
                "profile": "ui",
                "reportFile": "C:/Temp/live-pass-ui.json",
            },
        }

        summary = _summarize_live_pass_report(report)

        self.assertEqual(summary["totalSteps"], 3)
        self.assertEqual(summary["passed"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["timedOut"], 1)
        failed_step = summary["failedSteps"][0]
        self.assertEqual(failed_step["name"], "unity_play(play)")
        self.assertEqual(failed_step["status"], "timed-out")
        self.assertEqual(failed_step["durationMs"], 20000.0)
        self.assertEqual(failed_step["detail"], "play mode did not settle")
        self.assertEqual(failed_step["consoleSummary"], "error: Input exception during play mode")
        self.assertIn(
            "cli-anything-unity-mcp --json play stop --port 7891",
            failed_step["recommendedCommands"],
        )
        self.assertIn(
            "cli-anything-unity-mcp --json debug doctor --recent-commands 8 --port 7891",
            summary["recommendedCommands"],
        )
        self.assertEqual(
            summary["portHops"],
            [{"step": "unity_inspect", "from": 7891, "to": 7892}],
        )

        report["liveSummary"] = summary
        text = _format_live_pass_summary(report, failures_only=True)

        self.assertIn("Unity MCP Live Pass", text)
        self.assertIn("Failures And Timeouts", text)
        self.assertIn("unity_play(play) [timed-out] in 20000.0ms: play mode did not settle", text)
        self.assertIn("console: error: Input exception during play mode", text)
        self.assertIn("next: cli-anything-unity-mcp --json play stop --port 7891", text)
        self.assertIn("Port Hops", text)
        self.assertIn("7891 -> 7892 during unity_inspect", text)
        self.assertNotIn("Slowest Steps", text)

    def test_mcp_tool_registry_is_curated_and_has_fast_defaults(self) -> None:
        names = [tool["name"] for tool in iter_mcp_tools()]

        self.assertIn("unity_tool_call", names)
        self.assertIn("unity_validate_scene", names)
        self.assertNotIn("unity_build_sample", names)
        self.assertNotIn("unity_build_fps_sample", names)

        audit_tool = get_mcp_tool("unity_audit_advanced")
        self.assertIsNotNone(audit_tool)
        self.assertEqual(
            audit_tool.input_schema["properties"]["probeBacked"]["default"],
            True,
        )

    def test_build_behaviour_script_generates_minimal_component(self) -> None:
        script = build_behaviour_script("ProbeBehaviour", namespace="Codex.Tests")

        self.assertIn("using UnityEngine;", script)
        self.assertIn("namespace Codex.Tests", script)
        self.assertIn("public class ProbeBehaviour : MonoBehaviour", script)
        self.assertIn('public string Label = "ProbeBehaviour";', script)
        self.assertIn("public int Count = 1;", script)

    def test_humanize_history_entry_summarizes_script_edit(self) -> None:
        entry = _humanize_history_entry(
            {
                "command": "script/update",
                "args": {"path": "Assets/Scripts/PlayerController.cs", "content": "public class PlayerController {}"},
                "status": "ok",
            }
        )

        self.assertEqual(entry["phase"], "edit")
        self.assertEqual(entry["target"], "PlayerController.cs")
        self.assertEqual(entry["summary"], "Editing script PlayerController.cs")

    def test_humanize_history_entry_preserves_cli_progress_message(self) -> None:
        entry = _humanize_history_entry(
            {
                "command": "cli/progress",
                "args": {"message": "Checking project info", "phase": "inspect", "level": "info"},
                "status": "ok",
            }
        )

        self.assertEqual(entry["phase"], "inspect")
        self.assertIsNone(entry["target"])
        self.assertEqual(entry["summary"], "Checking project info")

    def test_humanize_history_entry_adds_route_and_tool_metadata(self) -> None:
        entry = _humanize_history_entry(
            {
                "command": "scene/info",
                "args": {},
                "status": "ok",
            }
        )

        self.assertEqual(entry["commandKind"], "route")
        self.assertEqual(entry["routeName"], "scene/info")
        self.assertEqual(entry["toolName"], "unity_scene_info")
        self.assertEqual(entry["category"], "scene")
        self.assertEqual(entry["summary"], "Inspecting scene info")

    def test_summarize_trace_entries_adds_problem_guidance(self) -> None:
        entries = [
            _humanize_history_entry(
                {
                    "command": "scene/info",
                    "args": {},
                    "status": "error",
                    "error": "bridge unavailable",
                    "timestamp": "2026-04-09T10:00:00+00:00",
                    "durationMs": 22.5,
                }
            ),
            _humanize_history_entry(
                {
                    "command": "debug/breadcrumb",
                    "args": {"message": "noise"},
                    "status": "error",
                    "timestamp": "2026-04-09T10:00:01+00:00",
                }
            ),
        ]

        groups = _summarize_trace_entries(entries, selected_port=7892)

        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group["routeName"], "scene/info")
        self.assertEqual(group["toolName"], "unity_scene_info")
        self.assertEqual(group["errorCount"], 1)
        self.assertEqual(group["lastError"], "bridge unavailable")
        self.assertEqual(group["diagnosis"], "Scene inspection or mutation failed recently.")
        self.assertIn(
            "cli-anything-unity-mcp --json debug trace --route scene/info",
            group["suggestedNextCommands"],
        )
        self.assertIn(
            "cli-anything-unity-mcp --json workflow inspect --port 7892",
            group["suggestedNextCommands"],
        )

    def test_tool_route_overrides_and_round_trip(self) -> None:
        self.assertEqual(tool_name_to_route("unity_execute_code"), "editor/execute-code")
        self.assertEqual(tool_name_to_route("unity_scene_hierarchy"), "scene/hierarchy")
        self.assertEqual(tool_name_to_route("unity_scene_stats"), "search/scene-stats")
        self.assertEqual(
            tool_name_to_route("unity_settings_set_quality_level"),
            "settings/quality-level",
        )
        self.assertEqual(tool_name_to_route("unity_get_project_context"), "context")
        self.assertEqual(route_to_tool_name("editor/execute-code"), "unity_execute_code")
        self.assertEqual(route_to_tool_name("scene/hierarchy"), "unity_scene_hierarchy")
        self.assertEqual(route_to_tool_name("search/scene-stats"), "unity_scene_stats")

    def test_session_store_persists_and_trims_history(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            session_path = tmpdir / "session.json"
            store = SessionStore(session_path, max_history=2)
            store.record_command("scene/info", {"path": "MainScene"}, 7890)
            store.record_command("console/log", {"count": 10}, 7890)
            store.record_command("project/info", {}, 7890, status="error", error="boom", duration_ms=12.5)

            state = store.load()
            self.assertEqual(len(state.history), 2)
            self.assertEqual(state.history[0]["command"], "console/log")
            self.assertEqual(state.history[1]["command"], "project/info")
            self.assertEqual(state.history[1]["status"], "error")
            self.assertEqual(state.history[1]["error"], "boom")
            self.assertEqual(state.history[1]["durationMs"], 12.5)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_session_store_persists_debug_preferences(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            session_path = tmpdir / "session.json"
            store = SessionStore(session_path)
            state = store.update_debug_preferences(
                unityConsoleBreadcrumbs=False,
                dashboardRefreshSeconds=1.5,
                dashboardConsoleCount=64,
                dashboardIssueLimit=12,
                dashboardIncludeHierarchy=True,
            )

            self.assertFalse(state.debug_preferences["unityConsoleBreadcrumbs"])
            self.assertEqual(state.debug_preferences["dashboardRefreshSeconds"], 1.5)
            self.assertEqual(state.debug_preferences["dashboardConsoleCount"], 64)
            self.assertEqual(state.debug_preferences["dashboardIssueLimit"], 12)
            self.assertTrue(state.debug_preferences["dashboardIncludeHierarchy"])

            reloaded = SessionStore(session_path).get_debug_preferences()
            self.assertFalse(reloaded["unityConsoleBreadcrumbs"])
            self.assertEqual(reloaded["dashboardRefreshSeconds"], 1.5)
            self.assertEqual(reloaded["dashboardConsoleCount"], 64)
            self.assertEqual(reloaded["dashboardIssueLimit"], 12)
            self.assertTrue(reloaded["dashboardIncludeHierarchy"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_debug_dashboard_server_exposes_state_and_persists_settings(self) -> None:
        backend = DashboardBackendStub()
        handle = serve_debug_dashboard(
            backend=backend,
            config=DashboardConfig(
                host="127.0.0.1",
                port=0,
                unity_port=7892,
                open_browser=False,
            ),
        )
        try:
            settings_payload = json.loads(urlopen(handle.url + "api/settings", timeout=5).read().decode("utf-8"))
            self.assertTrue(settings_payload["preferences"]["unityConsoleBreadcrumbs"])

            request = Request(
                handle.url + "api/settings",
                data=json.dumps(
                    {
                        "unityConsoleBreadcrumbs": False,
                        "dashboardConsoleCount": 22,
                        "dashboardIncludeHierarchy": True,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            save_payload = json.loads(urlopen(request, timeout=5).read().decode("utf-8"))
            self.assertTrue(save_payload["success"])
            self.assertFalse(save_payload["preferences"]["unityConsoleBreadcrumbs"])
            self.assertEqual(save_payload["preferences"]["dashboardConsoleCount"], 22)
            self.assertTrue(save_payload["preferences"]["dashboardIncludeHierarchy"])

            live_payload = json.loads(
                urlopen(
                    handle.url + "api/live?consoleCount=9&traceTail=4&messageType=info",
                    timeout=5,
                )
                .read()
                .decode("utf-8")
            )
            self.assertEqual(live_payload["title"], "Unity Debug Dashboard")
            self.assertEqual(live_payload["doctor"]["summary"]["assessment"], "healthy")
            self.assertEqual(backend.last_live_args["port"], 7892)
            self.assertEqual(backend.last_live_args["console_count"], 9)
            self.assertEqual(backend.last_live_args["trace_tail"], 4)
            self.assertEqual(backend.last_live_args["message_type"], "info")

            state_payload = json.loads(
                urlopen(
                    handle.url
                    + "api/state?consoleCount=11&issueLimit=7&traceTail=5&editorLogTail=33"
                    + "&messageType=warning&includeHierarchy=true&abUmcpOnly=true&editorLogContains=AB-UMCP",
                    timeout=5,
                )
                .read()
                .decode("utf-8")
            )
            self.assertEqual(state_payload["title"], "Unity Debug Dashboard")
            self.assertEqual(state_payload["doctor"]["summary"]["assessment"], "healthy")
            self.assertEqual(backend.last_state_args["port"], 7892)
            self.assertEqual(backend.last_state_args["console_count"], 11)
            self.assertEqual(backend.last_state_args["issue_limit"], 7)
            self.assertEqual(backend.last_state_args["trace_tail"], 5)
            self.assertEqual(backend.last_state_args["editor_log_tail"], 33)
            self.assertEqual(backend.last_state_args["message_type"], "warning")
            self.assertTrue(backend.last_state_args["include_hierarchy"])
            self.assertTrue(backend.last_state_args["ab_umcp_only"])
            self.assertEqual(backend.last_state_args["editor_log_contains"], "AB-UMCP")
        finally:
            handle.close()

    def test_call_route_records_error_trace_entry(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            registry_path = tmpdir / "instances.json"
            registry_path.write_text(
                json.dumps(
                    [
                        {
                            "port": 7890,
                            "projectName": "Demo",
                            "projectPath": "C:/Projects/Demo",
                            "unityVersion": "6000.0.0f1",
                            "platform": "WindowsEditor",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            session_store = SessionStore(tmpdir / "session.json")
            backend = UnityMCPBackend(
                client=ErrorRouteClient(
                    {
                        7890: {
                            "status": "ok",
                            "projectName": "Demo",
                            "projectPath": "C:/Projects/Demo",
                            "unityVersion": "6000.0.0f1",
                            "platform": "WindowsEditor",
                        }
                    }
                ),
                session_store=session_store,
                registry_path=registry_path,
                default_port=7890,
                port_range_start=7890,
                port_range_end=7890,
            )
            backend.select_instance(7890)

            with self.assertRaises(UnityMCPClientError):
                backend.call_route("scene/info")

            history = backend.get_history()
            self.assertEqual(history[-1]["command"], "scene/info")
            self.assertEqual(history[-1]["status"], "error")
            self.assertIn("route failed", history[-1]["error"])
            self.assertEqual(history[-1]["transport"], "queue")
            self.assertIn("durationMs", history[-1])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_emit_unity_breadcrumb_can_fail_without_polluting_trace_history(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            registry_path = tmpdir / "instances.json"
            registry_path.write_text(
                json.dumps(
                    [
                        {
                            "port": 7890,
                            "projectName": "Demo",
                            "projectPath": "C:/Projects/Demo",
                            "unityVersion": "6000.0.0f1",
                            "platform": "WindowsEditor",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            session_store = SessionStore(tmpdir / "session.json")
            backend = UnityMCPBackend(
                client=ErrorRouteClient(
                    {
                        7890: {
                            "status": "ok",
                            "projectName": "Demo",
                            "projectPath": "C:/Projects/Demo",
                            "unityVersion": "6000.0.0f1",
                            "platform": "WindowsEditor",
                        }
                    }
                ),
                session_store=session_store,
                registry_path=registry_path,
                default_port=7890,
                port_range_start=7890,
                port_range_end=7890,
            )
            backend.select_instance(7890)

            with self.assertRaises(UnityMCPClientError):
                backend.emit_unity_breadcrumb("hello", record_history=False)

            self.assertEqual(backend.get_history(), [])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_backend_auto_selects_single_instance(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            registry_path = tmpdir / "instances.json"
            session_path = tmpdir / "session.json"
            registry_path.write_text(
                json.dumps(
                    [
                        {
                            "port": 7890,
                            "projectName": "Demo",
                            "projectPath": "C:/Projects/Demo",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            backend = UnityMCPBackend(
                client=FakeClient(
                    {
                        7890: {
                            "status": "ok",
                            "projectName": "Demo",
                            "projectPath": "C:/Projects/Demo",
                            "unityVersion": "6000.0.0f1",
                        }
                    }
                ),
                session_store=SessionStore(session_path),
                registry_path=registry_path,
            )

            listing = backend.list_instances()
            self.assertEqual(listing["totalCount"], 1)
            self.assertEqual(backend.resolve_port(), 7890)
            self.assertEqual(backend.session_store.load().selected_port, 7890)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_backend_requires_selection_when_multiple_instances_exist(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            registry_path = tmpdir / "instances.json"
            session_path = tmpdir / "session.json"
            registry_path.write_text(
                json.dumps(
                    [
                        {
                            "port": 7890,
                            "projectName": "DemoA",
                            "projectPath": "C:/Projects/DemoA",
                        },
                        {
                            "port": 7891,
                            "projectName": "DemoB",
                            "projectPath": "C:/Projects/DemoB",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            backend = UnityMCPBackend(
                client=FakeClient(
                    {
                        7890: {
                            "status": "ok",
                            "projectName": "DemoA",
                            "projectPath": "C:/Projects/DemoA",
                        },
                        7891: {
                            "status": "ok",
                            "projectName": "DemoB",
                            "projectPath": "C:/Projects/DemoB",
                        },
                    }
                ),
                session_store=SessionStore(session_path),
                registry_path=registry_path,
            )

            with self.assertRaises(BackendSelectionError):
                backend.resolve_port()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_call_route_with_recovery_follows_project_rebind(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            session_path = tmpdir / "session.json"
            store = SessionStore(session_path)
            store.update_selection(
                {
                    "port": 7890,
                    "projectName": "Demo",
                    "projectPath": "C:/Projects/Demo",
                    "unityVersion": "6000.0.0f1",
                    "platform": "WindowsEditor",
                    "isClone": False,
                    "cloneIndex": -1,
                    "processId": 111,
                    "source": "registry",
                }
            )

            client = RebindingClient(
                {
                    7891: {
                        "status": "ok",
                        "projectName": "Demo",
                        "projectPath": "C:/Projects/Demo",
                        "unityVersion": "6000.0.0f1",
                    }
                }
            )
            backend = RebindingBackend(
                client=client,
                session_store=store,
                registry_path=tmpdir / "instances.json",
            )

            result = backend.call_route_with_recovery(
                "editor/state",
                recovery_timeout=1.0,
                recovery_interval=0.01,
            )

            self.assertTrue(result["success"])
            self.assertEqual(result["port"], 7891)
            self.assertEqual(client.route_calls, [7890, 7891])
            self.assertEqual(store.load().selected_port, 7891)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_call_route_with_recovery_times_out_with_route_context(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            session_path = tmpdir / "session.json"
            store = SessionStore(session_path)
            store.update_selection(
                {
                    "port": 7890,
                    "projectName": "Demo",
                    "projectPath": "C:/Projects/Demo",
                    "unityVersion": "6000.0.0f1",
                    "platform": "WindowsEditor",
                    "isClone": False,
                    "cloneIndex": -1,
                    "processId": 111,
                    "source": "registry",
                }
            )

            client = RebindingClient({})
            backend = NeverRecoveringBackend(
                client=client,
                session_store=store,
                registry_path=tmpdir / "instances.json",
            )

            with self.assertRaises(BackendSelectionError) as ctx:
                backend.call_route_with_recovery(
                    "editor/state",
                    recovery_timeout=0.02,
                    recovery_interval=0.01,
                )

            message = str(ctx.exception)
            self.assertIn("editor/state", message)
            self.assertIn("C:/Projects/Demo", message)
            self.assertIn("old port is unavailable", message)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_advanced_tool_meta_dispatches_to_nested_tool(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            registry_path = tmpdir / "instances.json"
            session_path = tmpdir / "session.json"
            registry_path.write_text(
                json.dumps(
                    [
                        {
                            "port": 7890,
                            "projectName": "Demo",
                            "projectPath": "C:/Projects/Demo",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            client = CatalogClient(
                {
                    7890: {
                        "status": "ok",
                        "projectName": "Demo",
                        "projectPath": "C:/Projects/Demo",
                        "unityVersion": "6000.0.0f1",
                    }
                }
            )
            backend = UnityMCPBackend(
                client=client,
                session_store=SessionStore(session_path),
                registry_path=registry_path,
            )

            result = backend.call_tool(
                "unity_advanced_tool",
                params={
                    "tool": "unity_scene_stats",
                    "params": {},
                },
            )

            self.assertTrue(result["success"])
            self.assertEqual(client.calls[0][0], "search/scene-stats")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_graphics_tool_aliases_object_path_to_gameobject_path(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            registry_path = tmpdir / "instances.json"
            session_path = tmpdir / "session.json"
            registry_path.write_text(
                json.dumps(
                    [
                        {
                            "port": 7890,
                            "projectName": "Demo",
                            "projectPath": "C:/Projects/Demo",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            client = CatalogClient(
                {
                    7890: {
                        "status": "ok",
                        "projectName": "Demo",
                        "projectPath": "C:/Projects/Demo",
                        "unityVersion": "6000.0.0f1",
                    }
                }
            )
            backend = UnityMCPBackend(
                client=client,
                session_store=SessionStore(session_path),
                registry_path=registry_path,
            )

            backend.call_tool(
                "unity_graphics_renderer_info",
                params={"objectPath": "Probe"},
            )

            self.assertEqual(client.calls[0][0], "graphics/renderer-info")
            self.assertEqual(client.calls[0][2]["objectPath"], "Probe")
            self.assertEqual(client.calls[0][2]["gameObjectPath"], "Probe")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_context_tool_uses_queue_safe_route_before_direct_get(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            registry_path = tmpdir / "instances.json"
            registry_path.write_text(
                json.dumps(
                    [
                        {
                            "port": 7890,
                            "projectName": "Demo",
                            "projectPath": "C:/Projects/Demo",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            client = CatalogClient(
                {
                    7890: {
                        "status": "ok",
                        "projectName": "Demo",
                        "projectPath": "C:/Projects/Demo",
                        "unityVersion": "6000.0.0f1",
                    }
                }
            )
            backend = UnityMCPBackend(
                client=client,
                session_store=SessionStore(tmpdir / "session.json"),
                registry_path=registry_path,
            )

            result = backend.call_tool("unity_get_project_context", params={"category": "Architecture"})

            self.assertTrue(result["success"])
            self.assertEqual(client.calls[0][0], "context")
            self.assertEqual(client.calls[0][2]["category"], "Architecture")
            history = backend.session_store.load().history
            self.assertEqual(history[-1]["command"], "context")
            self.assertEqual(history[-1]["transport"], "queue")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_context_tool_uses_execute_code_shim_when_queue_route_is_missing(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            registry_path = tmpdir / "instances.json"
            registry_path.write_text(
                json.dumps(
                    [
                        {
                            "port": 7890,
                            "projectName": "Demo",
                            "projectPath": "C:/Projects/Demo",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            client = ContextQueueUnknownClient(
                {
                    7890: {
                        "status": "ok",
                        "projectName": "Demo",
                        "projectPath": "C:/Projects/Demo",
                        "unityVersion": "6000.0.0f1",
                    }
                }
            )
            backend = UnityMCPBackend(
                client=client,
                session_store=SessionStore(tmpdir / "session.json"),
                registry_path=registry_path,
            )

            result = backend.call_tool("unity_get_project_context", params={"category": "Architecture"})

            self.assertTrue(result["enabled"])
            self.assertEqual(result["categories"][0]["content"], "Main-thread-safe context.")
            self.assertEqual([call[1] for call in client.route_calls], ["context", "editor/execute-code"])
            self.assertEqual(client.get_calls, [])
            self.assertIn(
                'GetContextResponse("Architecture")',
                client.route_calls[1][2]["code"],
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_context_tool_falls_back_to_direct_get_for_legacy_bridge(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            registry_path = tmpdir / "instances.json"
            registry_path.write_text(
                json.dumps(
                    [
                        {
                            "port": 7890,
                            "projectName": "Demo",
                            "projectPath": "C:/Projects/Demo",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            client = ContextFallbackClient(
                {
                    7890: {
                        "status": "ok",
                        "projectName": "Demo",
                        "projectPath": "C:/Projects/Demo",
                        "unityVersion": "6000.0.0f1",
                    }
                }
            )
            backend = UnityMCPBackend(
                client=client,
                session_store=SessionStore(tmpdir / "session.json"),
                registry_path=registry_path,
            )

            result = backend.call_tool("unity_get_project_context", params={"category": "Architecture"})

            self.assertEqual(result["apiPath"], "context/Architecture")
            self.assertEqual(client.route_calls[0][1], "context")
            self.assertEqual(client.route_calls[1][1], "editor/execute-code")
            self.assertEqual(client.get_calls[0][1], "context/Architecture")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_list_advanced_tools_meta_groups_by_category(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            backend = UnityMCPBackend(
                client=FakeClient({}),
                session_store=SessionStore(tmpdir / "session.json"),
                registry_path=tmpdir / "instances.json",
            )

            result = backend.call_tool("unity_list_advanced_tools", params={"category": "terrain"})

            self.assertEqual(result["category"], "terrain")
            self.assertGreater(result["totalCount"], 0)
            self.assertTrue(any(tool["name"] == "unity_terrain_list" for tool in result["tools"]))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_debug_doctor_report_prioritizes_missing_references_and_queue(self) -> None:
        snapshot = {
            "summary": {
                "port": 7892,
                "projectName": "Demo",
                "activeScene": "MainScene",
                "sceneDirty": True,
                "consoleEntryCount": 3,
            },
            "editorState": {
                "isPlaying": True,
                "isPlayingOrWillChangePlaymode": False,
                "isCompiling": False,
            },
            "console": {
                "entries": [
                    {"message": "Sample warning log", "type": "warning"},
                ]
            },
            "consoleSummary": {"highestSeverity": "warning"},
            "compilation": {"count": 0, "entries": []},
            "missingReferences": {
                "totalFound": 1,
                "results": [{"issue": "Missing script (component is null)", "path": "MainScene/BrokenThing"}],
            },
            "queue": {"totalQueued": 2, "activeAgents": 1},
        }

        report = build_debug_doctor_report(
            snapshot,
            [{"command": "workflow/inspect", "port": 7892}],
            7892,
        )

        self.assertEqual(report["title"], "Unity Debug Doctor")
        self.assertEqual(report["summary"]["assessment"], "error")
        self.assertEqual(report["summary"]["headline"], "Missing References")
        self.assertGreaterEqual(report["summary"]["findingCount"], 4)
        self.assertEqual(report["recentCommands"][0]["command"], "workflow/inspect")
        self.assertTrue(any(item["title"] == "Missing References" for item in report["findings"]))
        self.assertTrue(any(item["title"] == "Queued Requests Pending" for item in report["findings"]))
        self.assertTrue(any(item["title"] == "Active Unity Agents Running" for item in report["findings"]))
        self.assertIn("cli-anything-unity-mcp --json play stop --port 7892", report["recommendedCommands"])
        self.assertIn("cli-anything-unity-mcp --json agent queue --port 7892", report["recommendedCommands"])
        self.assertIn("cli-anything-unity-mcp --json agent sessions --port 7892", report["recommendedCommands"])

    def test_debug_doctor_distinguishes_backlog_without_active_agents(self) -> None:
        snapshot = {
            "summary": {"port": 7892, "consoleEntryCount": 0, "sceneDirty": False},
            "editorState": {"isPlaying": False, "isCompiling": False},
            "console": {"entries": []},
            "consoleSummary": {"highestSeverity": "info"},
            "compilation": {"count": 0, "entries": []},
            "missingReferences": {"totalFound": 0, "results": []},
            "queue": {"totalQueued": 3, "activeAgents": 0},
        }

        report = build_debug_doctor_report(snapshot, [], 7892)

        titles = [item["title"] for item in report["findings"]]
        self.assertIn("Queued Requests Pending", titles)
        self.assertNotIn("Active Unity Agents Running", titles)
        backlog = next(item for item in report["findings"] if item["title"] == "Queued Requests Pending")
        self.assertEqual(backlog["evidence"]["totalQueued"], 3)
        self.assertEqual(backlog["evidence"]["activeAgents"], 0)

    def test_debug_doctor_flags_skybox_camera_using_renderer2d(self) -> None:
        snapshot = {
            "summary": {
                "port": 7892,
                "consoleEntryCount": 0,
                "sceneDirty": False,
            },
            "editorState": {
                "isPlaying": False,
                "isPlayingOrWillChangePlaymode": False,
                "isCompiling": False,
            },
            "console": {"entries": []},
            "consoleSummary": {"highestSeverity": "info"},
            "compilation": {"count": 0, "entries": []},
            "missingReferences": {"totalFound": 0, "results": []},
            "queue": {"totalQueued": 0, "activeAgents": 0},
            "cameraDiagnostics": {
                "cameraName": "MainCamera",
                "clearFlags": "Skybox",
                "rendererName": "UnityEngine.Rendering.Universal.Renderer2D",
                "pipeline": "UniversalRP",
            },
        }

        report = build_debug_doctor_report(snapshot, [], 7892)

        self.assertEqual(report["summary"]["assessment"], "error")
        self.assertEqual(report["summary"]["headline"], "Skybox Blocked By 2D Renderer")
        self.assertTrue(
            any(item["title"] == "Skybox Blocked By 2D Renderer" for item in report["findings"])
        )
        self.assertIn(
            "cli-anything-unity-mcp --json debug capture --kind both --port 7892",
            report["recommendedCommands"],
        )

    def test_debug_doctor_enriches_compilation_errors_with_heuristics(self) -> None:
        snapshot = {
            "summary": {"port": 7892, "consoleEntryCount": 0, "sceneDirty": False},
            "editorState": {"isPlaying": False, "isCompiling": False},
            "console": {"entries": []},
            "consoleSummary": {"highestSeverity": "info"},
            "compilation": {
                "count": 2,
                "entries": [
                    {
                        "message": (
                            "Assets/Scripts/Player.cs(12,8): error CS0246: "
                            "The type or namespace name 'Foo' could not be found"
                        )
                    },
                    {
                        "message": (
                            "Assets/Scripts/Enemy.cs(18,20): error CS0103: "
                            "The name 'target' does not exist in the current context"
                        )
                    },
                ],
            },
            "missingReferences": {"totalFound": 0, "results": []},
            "queue": {"totalQueued": 0, "activeAgents": 0},
        }

        report = build_debug_doctor_report(snapshot, [], 7892)

        titles = [finding["title"] for finding in report["findings"]]
        self.assertIn("Compilation Issues", titles)
        self.assertIn("CS0246: Missing Type or Namespace", titles)
        self.assertIn("CS0103: Undefined Name in Scope", titles)
        self.assertEqual(report["compilationSummary"]["totalErrors"], 2)
        self.assertEqual(report["compilationSummary"]["uniqueErrorCodes"], ["CS0246", "CS0103"])
        self.assertIn("Assets/Scripts/Player.cs", report["compilationSummary"]["affectedFiles"])
        self.assertTrue(
            any(
                finding.get("evidence", {}).get("location") == "Assets/Scripts/Player.cs line 12"
                for finding in report["findings"]
            )
        )
        self.assertIn(
            "cli-anything-unity-mcp --json debug snapshot --console-count 50 --port 7892",
            report["recommendedCommands"],
        )

    def test_debug_doctor_enriches_runtime_console_patterns(self) -> None:
        snapshot = {
            "summary": {"port": 7892, "consoleEntryCount": 1, "sceneDirty": False},
            "editorState": {"isPlaying": False, "isCompiling": False},
            "console": {
                "entries": [
                    {
                        "type": "error",
                        "message": "NullReferenceException: Object reference not set to an instance of an object",
                    }
                ]
            },
            "consoleSummary": {"highestSeverity": "error"},
            "compilation": {"count": 0, "entries": []},
            "missingReferences": {"totalFound": 0, "results": []},
            "queue": {"totalQueued": 0, "activeAgents": 0},
        }

        report = build_debug_doctor_report(snapshot, [], 7892)

        null_ref = next(
            finding for finding in report["findings"] if finding["title"] == "NullReferenceException at Runtime"
        )
        self.assertTrue(null_ref["heuristic"])
        self.assertIn("serialized field", null_ref["detail"].lower())
        self.assertIn(
            "cli-anything-unity-mcp --json console --count 50 --type error --port 7892",
            report["recommendedCommands"],
        )

    def test_debug_doctor_surfaces_recurring_compilation_queue_and_bridge_signals(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            memory = ProjectMemory("C:/Projects/Demo", store_root=tmpdir, allow_fallback=False)
            compilation_entry = {
                "message": (
                    "Assets/Scripts/Player.cs(12,8): error CS0246: "
                    "The type or namespace name 'Foo' could not be found"
                )
            }
            memory.record_compilation_errors([compilation_entry], "MainScene")
            memory.record_compilation_errors([compilation_entry], "MainScene")
            memory.record_operational_signals(
                [
                    {
                        "kind": "queue",
                        "key": "queue-contention",
                        "title": "Queue contention",
                        "detail": "Queue still had active work pending.",
                    },
                    {
                        "kind": "bridge",
                        "key": "bridge-port-hop",
                        "title": "Bridge port hop",
                        "detail": "Recent CLI calls hopped between Unity ports.",
                    },
                ],
                "MainScene",
            )
            memory.record_operational_signals(
                [
                    {
                        "kind": "queue",
                        "key": "queue-contention",
                        "title": "Queue contention",
                        "detail": "Queue still had active work pending.",
                    },
                    {
                        "kind": "bridge",
                        "key": "bridge-port-hop",
                        "title": "Bridge port hop",
                        "detail": "Recent CLI calls hopped between Unity ports.",
                    },
                ],
                "MainScene",
            )
            memory.record_queue_snapshot({"totalQueued": 2, "activeAgents": 1}, "MainScene")
            memory.record_queue_snapshot({"totalQueued": 2, "activeAgents": 1}, "MainScene")
            memory.record_queue_snapshot({"totalQueued": 2, "activeAgents": 1}, "MainScene")

            snapshot = {
                "summary": {"port": 7892, "consoleEntryCount": 0, "sceneDirty": False},
                "editorState": {"isPlaying": False, "isCompiling": False},
                "console": {"entries": []},
                "consoleSummary": {"highestSeverity": "info"},
                "compilation": {"count": 1, "entries": [compilation_entry]},
                "missingReferences": {"totalFound": 0, "results": []},
                "queue": {"totalQueued": 2, "activeAgents": 1},
            }

            report = build_debug_doctor_report(
                snapshot,
                [
                    {"command": "scene/info", "port": 7891},
                    {"command": "scene/info", "port": 7892},
                ],
                7892,
                memory=memory,
            )

            titles = [finding["title"] for finding in report["findings"]]
            self.assertIn("Recurring Compilation Errors", titles)
            self.assertIn("Recurring Queue Contention", titles)
            self.assertIn("Recurring Bridge Port Hops", titles)
            self.assertIn("Queue backlog trend looks persistent", titles)
            self.assertEqual(report["queueDiagnostics"]["status"], "backlog-and-active")
            self.assertEqual(report["queueDiagnostics"]["recurringSignalCount"], 1)
            self.assertIn("queued work pending", report["queueDiagnostics"]["summary"])
            self.assertEqual(report["queueTrend"]["status"], "stalled-backlog-suspected")
            self.assertEqual(report["queueTrend"]["sampleCount"], 3)
            self.assertIn(
                "cli-anything-unity-mcp --json debug bridge --port 7892",
                report["recommendedCommands"],
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_bridge_diagnostics_reports_selected_port_mismatch(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            registry_path = tmpdir / "instances.json"
            session_path = tmpdir / "session.json"
            registry_path.write_text(
                json.dumps(
                    [
                        {
                            "port": 7890,
                            "projectName": "Demo",
                            "projectPath": "C:/Projects/Demo",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            session_store = SessionStore(session_path)
            session_store.save(
                SessionState(
                    selected_port=7891,
                    selected_instance={"port": 7891, "projectName": "Demo", "projectPath": "C:/Projects/Demo"},
                    history=[],
                )
            )
            backend = UnityMCPBackend(
                client=FakeClient(
                    {
                        7890: {
                            "status": "ok",
                            "projectName": "Demo",
                            "projectPath": "C:/Projects/Demo",
                            "unityVersion": "6000.0.0f1",
                            "platform": "WindowsEditor",
                        }
                    }
                ),
                session_store=session_store,
                registry_path=registry_path,
                default_port=7890,
                port_range_start=7890,
                port_range_end=7891,
            )

            payload = backend.get_bridge_diagnostics()

            self.assertEqual(payload["title"], "Unity Bridge Diagnostics")
            self.assertEqual(payload["summary"]["assessment"], "warning")
            self.assertEqual(payload["summary"]["connectionMode"], "registry-backed")
            self.assertTrue(payload["summary"]["canReachUnity"])
            self.assertEqual(payload["summary"]["selectedPort"], 7891)
            self.assertEqual(payload["summary"]["respondingPortCount"], 1)
            self.assertTrue(any(check["port"] == 7890 and check["status"] == "ok" for check in payload["portChecks"]))
            self.assertTrue(any(check["port"] == 7891 and check["status"] != "ok" for check in payload["portChecks"]))
            self.assertTrue(any(item["title"] == "Selected Port Is Not Responding" for item in payload["findings"]))
            self.assertTrue(any(command.startswith("cli-anything-unity-mcp instances") for command in payload["recommendedCommands"]))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_bridge_diagnostics_reports_registry_access_denied_fallback(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            session_path = tmpdir / "session.json"
            session_store = SessionStore(session_path)
            session_store.update_selection(
                {
                    "port": 7892,
                    "projectName": "Demo",
                    "projectPath": "C:/Projects/Demo",
                }
            )
            backend = UnityMCPBackend(
                client=FakeClient(
                    {
                        7892: {
                            "status": "ok",
                            "projectName": "Demo",
                            "projectPath": "C:/Projects/Demo",
                            "unityVersion": "6000.0.0f1",
                            "platform": "WindowsEditor",
                        }
                    }
                ),
                session_store=session_store,
                registry_path=tmpdir / "instances.json",
                default_port=7890,
                port_range_start=7892,
                port_range_end=7892,
            )
            backend.discover_instances = lambda: [  # type: ignore[method-assign]
                {
                    "port": 7892,
                    "projectName": "Demo",
                    "projectPath": "C:/Projects/Demo",
                    "unityVersion": "6000.0.0f1",
                    "platform": "WindowsEditor",
                    "source": "portscan",
                }
            ]
            backend._read_registry_snapshot = lambda: {  # type: ignore[method-assign]
                "path": str(tmpdir / "instances.json"),
                "status": "access-denied",
                "error": "Access is denied",
                "entries": [],
            }

            payload = backend.get_bridge_diagnostics(port=7892)

            self.assertEqual(payload["summary"]["assessment"], "warning")
            self.assertEqual(payload["summary"]["connectionMode"], "portscan-fallback")
            self.assertEqual(payload["summary"]["registryStatus"], "access-denied")
            self.assertEqual(payload["summary"]["registryError"], "Access is denied")
            self.assertTrue(any(item["title"] == "Registry File Access Denied" for item in payload["findings"]))
            self.assertTrue(any("debug doctor" in command for command in payload["recommendedCommands"]))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ── File IPC transport tests ─────────────────────────────────────────

    def test_file_ipc_client_ping_raises_when_no_umcp_dir(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            client = FileIPCClient(tmpdir)
            with self.assertRaises(FileIPCConnectionError):
                client.ping()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_file_ipc_client_ping_reads_heartbeat(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            umcp = tmpdir / ".umcp"
            umcp.mkdir()
            from datetime import datetime, timezone
            ping_data = {
                "status": "ok",
                "projectName": "TestProject",
                "projectPath": str(tmpdir),
                "unityVersion": "6000.4.0f1",
                "platform": "WindowsEditor",
                "lastHeartbeat": datetime.now(timezone.utc).isoformat(),
                "transport": "file-ipc",
            }
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            client = FileIPCClient(tmpdir)
            result = client.ping()
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["projectName"], "TestProject")
            self.assertEqual(result["transport"], "file-ipc")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_file_ipc_client_ping_rejects_stale_heartbeat(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            umcp = tmpdir / ".umcp"
            umcp.mkdir()
            from datetime import datetime, timezone, timedelta
            stale_time = datetime.now(timezone.utc) - timedelta(seconds=30)
            ping_data = {
                "status": "ok",
                "projectName": "StaleProject",
                "lastHeartbeat": stale_time.isoformat(),
            }
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            client = FileIPCClient(tmpdir)
            with self.assertRaises(FileIPCConnectionError):
                client.ping()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_file_ipc_client_call_route_roundtrip(self) -> None:
        """Simulate Unity responding to a file IPC command."""
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            client = FileIPCClient(tmpdir, poll_interval=0.01, timeout=2.0)
            client.ensure_dirs()

            import threading
            captured: dict[str, Any] = {}

            def fake_unity_responder():
                """Watch inbox, write response to outbox."""
                import time as _time
                deadline = _time.monotonic() + 2.0
                while _time.monotonic() < deadline:
                    inbox = tmpdir / ".umcp" / "inbox"
                    if inbox.exists():
                        for f in inbox.iterdir():
                            if f.suffix == ".json":
                                cmd = json.loads(f.read_text())
                                captured.update(cmd)
                                f.unlink()
                                response = {
                                    "id": cmd["id"],
                                    "result": {
                                        "success": True,
                                        "route": cmd["route"],
                                        "echo": json.loads(cmd.get("params") or "{}"),
                                    },
                                }
                                outbox = tmpdir / ".umcp" / "outbox"
                                outbox.mkdir(parents=True, exist_ok=True)
                                resp_path = outbox / f"{cmd['id']}.json"
                                resp_path.write_text(json.dumps(response))
                                return
                    _time.sleep(0.01)

            responder = threading.Thread(target=fake_unity_responder, daemon=True)
            responder.start()

            result = client.call_route("scene/info", params={"key": "value"})
            self.assertTrue(result["success"])
            self.assertEqual(result["route"], "scene/info")
            self.assertEqual(result["echo"]["key"], "value")
            self.assertIsInstance(captured["params"], str)

            responder.join(timeout=2.0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_file_ipc_client_timeout_raises(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            client = FileIPCClient(tmpdir, poll_interval=0.01, timeout=0.05)
            client.ensure_dirs()

            with self.assertRaises(FileIPCTimeoutError):
                client.call_route("scene/info")

            # Command file should have been cleaned up on timeout
            inbox_files = list((tmpdir / ".umcp" / "inbox").iterdir())
            self.assertEqual(len(inbox_files), 0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_file_ipc_discovery_finds_active_project(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            umcp = tmpdir / ".umcp"
            umcp.mkdir()
            from datetime import datetime, timezone
            ping_data = {
                "status": "ok",
                "projectName": "DiscoverMe",
                "projectPath": str(tmpdir),
                "unityVersion": "6000.4.0f1",
                "lastHeartbeat": datetime.now(timezone.utc).isoformat(),
            }
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            instances = discover_file_ipc_instances([tmpdir])
            self.assertEqual(len(instances), 1)
            self.assertEqual(instances[0]["projectName"], "DiscoverMe")
            self.assertEqual(instances[0]["transport"], "file-ipc")
            self.assertIsNone(instances[0]["port"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_file_ipc_discovery_skips_stale_project(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            umcp = tmpdir / ".umcp"
            umcp.mkdir()
            from datetime import datetime, timezone, timedelta
            stale = datetime.now(timezone.utc) - timedelta(seconds=60)
            ping_data = {"status": "ok", "lastHeartbeat": stale.isoformat()}
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            instances = discover_file_ipc_instances([tmpdir])
            self.assertEqual(len(instances), 0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_file_ipc_cleanup_removes_stale_files(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            client = FileIPCClient(tmpdir)
            client.ensure_dirs()

            # Create old files
            old_file = tmpdir / ".umcp" / "inbox" / "old-command.json"
            old_file.write_text('{"id":"old"}')
            # Backdate the file
            import time
            old_time = time.time() - 120
            os.utime(old_file, (old_time, old_time))

            # Create recent file
            new_file = tmpdir / ".umcp" / "inbox" / "new-command.json"
            new_file.write_text('{"id":"new"}')

            cleaned = client.cleanup_stale(max_age_seconds=60.0)
            self.assertEqual(cleaned, 1)
            self.assertFalse(old_file.exists())
            self.assertTrue(new_file.exists())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_backend_discovers_file_ipc_instances(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            # Set up a file IPC project
            umcp = tmpdir / "MyProject" / ".umcp"
            umcp.mkdir(parents=True)
            from datetime import datetime, timezone
            ping_data = {
                "status": "ok",
                "projectName": "MyProject",
                "projectPath": str(tmpdir / "MyProject"),
                "unityVersion": "6000.4.0f1",
                "lastHeartbeat": datetime.now(timezone.utc).isoformat(),
                "transport": "file-ipc",
            }
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            # Create backend with file transport only (skip HTTP)
            fake_client = FakeClient(pings={})
            session_path = tmpdir / "session.json"
            backend = UnityMCPBackend(
                client=fake_client,
                session_store=SessionStore(session_path),
                registry_path=tmpdir / "instances.json",
                transport="file",
                file_ipc_paths=[tmpdir / "MyProject"],
            )

            instances = backend.discover_instances()
            self.assertEqual(len(instances), 1)
            self.assertEqual(instances[0]["projectName"], "MyProject")
            self.assertEqual(instances[0]["transport"], "file-ipc")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_backend_file_ipc_ping_and_queue_info_do_not_use_http(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        umcp = project / ".umcp"
        umcp.mkdir(parents=True, exist_ok=True)
        try:
            from datetime import datetime, timezone

            ping_data = {
                "status": "ok",
                "projectName": "MyProject",
                "projectPath": str(project),
                "unityVersion": "6000.4.0f1",
                "lastHeartbeat": datetime.now(timezone.utc).isoformat(),
                "transport": "file-ipc",
            }
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            session_store = SessionStore(tmpdir / "session.json")
            session_store.save(
                SessionState(
                    selected_port=None,
                    selected_instance={
                        "projectName": "MyProject",
                        "projectPath": str(project),
                        "port": None,
                        "transport": "file-ipc",
                    },
                    history=[],
                )
            )
            backend = UnityMCPBackend(
                client=FakeClient(pings={}),
                session_store=session_store,
                registry_path=tmpdir / "instances.json",
                transport="file",
                file_ipc_paths=[project],
            )
            backend.set_runtime_context(agent_id="agent-file-ipc")

            ping = backend.ping()
            self.assertEqual(ping["projectName"], "MyProject")
            self.assertEqual(ping["transport"], "file-ipc")
            self.assertIsNone(ping["port"])

            with patch.object(
                FileIPCClient,
                "call_route",
                return_value={
                    "transport": "file-ipc",
                    "queueSupported": False,
                    "activeAgents": 1,
                    "totalQueued": 0,
                    "agentId": "agent-file-ipc",
                    "message": "File IPC executes each request on Unity's main thread from .umcp/inbox; no Unity queue is required.",
                },
            ) as call_route:
                queue = backend.get_queue_info()
            self.assertFalse(queue["queueSupported"])
            self.assertEqual(queue["transport"], "file-ipc")
            self.assertEqual(queue["activeAgents"], 1)
            self.assertEqual(queue["totalQueued"], 0)
            self.assertEqual(queue["agentId"], "agent-file-ipc")
            self.assertIn("no Unity queue is required", queue["message"])
            call_route.assert_called_once_with("queue/info", timeout=1.0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_ping_auto_selects_single_file_ipc_instance_when_none_is_selected(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        umcp = project / ".umcp"
        umcp.mkdir(parents=True, exist_ok=True)
        try:
            from datetime import datetime, timezone

            ping_data = {
                "status": "ok",
                "projectName": "MyProject",
                "projectPath": str(project),
                "unityVersion": "6000.4.0f1",
                "lastHeartbeat": datetime.now(timezone.utc).isoformat(),
                "transport": "file-ipc",
            }
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            backend = UnityMCPBackend(
                client=FakeClient(pings={}),
                session_store=SessionStore(tmpdir / "session.json"),
                registry_path=tmpdir / "instances.json",
                transport="file",
                file_ipc_paths=[project],
            )

            result = backend.ping()

            self.assertEqual(result["projectName"], "MyProject")
            self.assertEqual(result["transport"], "file-ipc")
            state = backend.session_store.load()
            self.assertEqual((state.selected_instance or {}).get("projectPath"), str(project))
            self.assertEqual((state.selected_instance or {}).get("transport"), "file-ipc")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_emit_unity_breadcrumb_uses_file_ipc_route_when_selected_instance_is_file_transport(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        umcp = project / ".umcp"
        umcp.mkdir(parents=True, exist_ok=True)
        try:
            from datetime import datetime, timezone

            ping_data = {
                "status": "ok",
                "projectName": "MyProject",
                "projectPath": str(project),
                "unityVersion": "6000.4.0f1",
                "lastHeartbeat": datetime.now(timezone.utc).isoformat(),
                "transport": "file-ipc",
            }
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            session_store = SessionStore(tmpdir / "session.json")
            session_store.save(
                SessionState(
                    selected_port=None,
                    selected_instance={
                        "projectName": "MyProject",
                        "projectPath": str(project),
                        "port": None,
                        "transport": "file-ipc",
                    },
                    history=[],
                )
            )
            backend = UnityMCPBackend(
                client=FakeClient(pings={}),
                session_store=session_store,
                registry_path=tmpdir / "instances.json",
                transport="file",
                file_ipc_paths=[project],
            )

            with patch.object(
                FileIPCClient,
                "call_route",
                return_value={"success": True, "level": "info", "message": "hello"},
            ) as call_route:
                result = backend.emit_unity_breadcrumb("hello")

            self.assertTrue(result["success"])
            call_route.assert_called_once_with(
                "debug/breadcrumb",
                params={"message": "hello", "level": "info"},
            )
            history = backend.get_history()
            self.assertEqual(history[-1]["command"], "debug/breadcrumb")
            self.assertEqual(history[-1]["transport"], "file-ipc")
            self.assertEqual(history[-1]["status"], "ok")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_get_context_uses_file_ipc_route_when_selected_instance_is_file_transport(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        umcp = project / ".umcp"
        umcp.mkdir(parents=True, exist_ok=True)
        try:
            from datetime import datetime, timezone

            ping_data = {
                "status": "ok",
                "projectName": "MyProject",
                "projectPath": str(project),
                "unityVersion": "6000.4.0f1",
                "lastHeartbeat": datetime.now(timezone.utc).isoformat(),
                "transport": "file-ipc",
            }
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            session_store = SessionStore(tmpdir / "session.json")
            session_store.save(
                SessionState(
                    selected_port=None,
                    selected_instance={
                        "projectName": "MyProject",
                        "projectPath": str(project),
                        "port": None,
                        "transport": "file-ipc",
                    },
                    history=[],
                )
            )
            backend = UnityMCPBackend(
                client=FakeClient(pings={}),
                session_store=session_store,
                registry_path=tmpdir / "instances.json",
                transport="file",
                file_ipc_paths=[project],
            )

            with patch.object(
                FileIPCClient,
                "call_route",
                return_value={"projectPath": str(project), "renderPipeline": "builtin"},
            ) as call_route:
                result = backend.get_context()

            self.assertEqual(result["projectPath"], str(project))
            call_route.assert_called_once_with("context", params={})
            history = backend.get_history()
            self.assertEqual(history[-1]["command"], "context")
            self.assertEqual(history[-1]["transport"], "file-ipc")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_record_progress_uses_file_ipc_breadcrumb_without_fake_port_zero(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        umcp = project / ".umcp"
        umcp.mkdir(parents=True, exist_ok=True)
        try:
            from datetime import datetime, timezone

            ping_data = {
                "status": "ok",
                "projectName": "MyProject",
                "projectPath": str(project),
                "unityVersion": "6000.4.0f1",
                "lastHeartbeat": datetime.now(timezone.utc).isoformat(),
                "transport": "file-ipc",
            }
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            session_store = SessionStore(tmpdir / "session.json")
            session_store.save(
                SessionState(
                    selected_port=None,
                    selected_instance={
                        "projectName": "MyProject",
                        "projectPath": str(project),
                        "port": None,
                        "transport": "file-ipc",
                    },
                    history=[],
                )
            )
            backend = UnityMCPBackend(
                client=FakeClient(pings={}),
                session_store=session_store,
                registry_path=tmpdir / "instances.json",
                transport="file",
                file_ipc_paths=[project],
            )

            with patch.object(backend, "emit_unity_breadcrumb", return_value={"success": True}) as emit_breadcrumb:
                backend.record_progress("Checking project info")

            emit_breadcrumb.assert_called_once()
            self.assertIsNone(emit_breadcrumb.call_args.kwargs["port"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_agent_loop_prefers_backend_file_ipc_resolver(self) -> None:
        from cli_anything.unity_mcp.commands.agent_loop_cmd import _resolve_file_ipc_client

        sentinel = object()

        class BackendStub:
            def _resolve_file_ipc_client(self) -> object:
                return sentinel

        client = _resolve_file_ipc_client(BackendStub())
        self.assertIs(client, sentinel)

    def test_agent_loop_falls_back_to_selected_instance_project_path(self) -> None:
        from cli_anything.unity_mcp.commands.agent_loop_cmd import _resolve_file_ipc_client

        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        umcp = project / ".umcp"
        umcp.mkdir(parents=True, exist_ok=True)
        try:
            session_store = SessionStore(tmpdir / "session.json")
            session_store.save(
                SessionState(
                    selected_port=None,
                    selected_instance={
                        "projectName": "MyProject",
                        "projectPath": str(project),
                        "port": None,
                        "transport": "file-ipc",
                    },
                    history=[],
                )
            )

            class BackendStub:
                def __init__(self, store: SessionStore) -> None:
                    self.session_store = store

            with patch.object(FileIPCClient, "is_alive", return_value=True):
                client = _resolve_file_ipc_client(BackendStub(session_store))

            self.assertIsInstance(client, FileIPCClient)
            self.assertEqual(client.project_path, project)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_bridge_reads_queued_user_inbox_messages(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        inbox_dir = project / ".umcp" / "chat" / "user-inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        try:
            class ClientStub:
                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    return {}

            first = inbox_dir / "20260411T1000000000000-first.json"
            second = inbox_dir / "20260411T1000000000001-second.json"
            first.write_text(json.dumps({"role": "user", "content": "first"}), encoding="utf-8")
            second.write_text(json.dumps({"role": "user", "content": "second"}), encoding="utf-8")

            bridge = ChatBridge(project, ClientStub())  # type: ignore[arg-type]

            message = bridge._read_inbox()

            self.assertEqual(message["content"], "first")
            self.assertFalse(first.exists())
            self.assertTrue(second.exists())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_bridge_reads_bom_prefixed_queued_message(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        inbox_dir = project / ".umcp" / "chat" / "user-inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        try:
            class ClientStub:
                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    return {}

            payload = json.dumps({"role": "user", "content": "bom-test"})
            (inbox_dir / "20260411T1000000000000-bom.json").write_text("\ufeff" + payload, encoding="utf-8")

            bridge = ChatBridge(project, ClientStub())  # type: ignore[arg-type]
            message = bridge._read_inbox()

            self.assertEqual(message["content"], "bom-test")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_agent_chat_once_processes_one_message(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        inbox_dir = project / ".umcp" / "chat" / "user-inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        try:
            (inbox_dir / "20260411T1000000000000-msg.json").write_text(
                json.dumps({"id": "msg-1", "role": "user", "content": "hello from unity"}),
                encoding="utf-8",
            )

            payload = run_cli_json(
                ["workflow", "agent-chat", "--once", str(project)],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            self.assertTrue(payload["processed"])
            self.assertEqual(payload["processedCount"], 1)
            history_path = project / ".umcp" / "chat" / "history.json"
            self.assertTrue(history_path.exists())
            history = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(history[0]["id"], "msg-1")
            self.assertEqual(history[0]["role"], "user")
            self.assertEqual(history[0]["content"], "hello from unity")
            self.assertEqual(history[1]["role"], "ai")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_bridge_greeting_reply_mentions_capabilities(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            class ClientStub:
                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    if route == "context":
                        return {
                            "projectName": "DemoProject",
                            "unityVersion": "6000.0.1",
                            "renderPipeline": "URP",
                            "scene": {"name": "MainScene", "objectCount": 12},
                            "assetCounts": {"prefabs": 1, "materials": 3},
                            "scriptCount": 4,
                            "compileErrors": [],
                            "recentConsoleErrors": [],
                        }
                    return {}

            bridge = ChatBridge(project, ClientStub())  # type: ignore[arg-type]
            bridge._process_message({"id": "msg-1", "role": "user", "content": "hi"})

            self.assertEqual(bridge._history[-1]["role"], "ai")
            self.assertIn("I", bridge._history[-1]["content"])
            self.assertIn("inspect project", bridge._history[-1]["content"])
            self.assertIn("improve project", bridge._history[-1]["content"])
            self.assertIn("create sandbox scene", bridge._history[-1]["content"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_agent_chat_once_runs_project_audit_reply(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        inbox_dir = project / ".umcp" / "chat" / "user-inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text(
                "public class Player {}",
                encoding="utf-8",
            )
            (project / "Assets" / "Scenes" / "Main.unity").write_text(
                "scene",
                encoding="utf-8",
            )
            (inbox_dir / "20260411T1000000000000-msg.json").write_text(
                json.dumps({"id": "msg-1", "role": "user", "content": "inspect project"}),
                encoding="utf-8",
            )

            run_cli_json(
                ["workflow", "agent-chat", "--once", str(project)],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            history = json.loads((project / ".umcp" / "chat" / "history.json").read_text(encoding="utf-8"))
            self.assertEqual(history[-1]["role"], "ai")
            self.assertIn("Overall quality:", history[-1]["content"])
            self.assertIn("Best next moves:", history[-1]["content"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_agent_chat_once_can_write_guidance(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        inbox_dir = project / ".umcp" / "chat" / "user-inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text(
                "public class Player {}",
                encoding="utf-8",
            )
            (inbox_dir / "20260411T1000000000000-msg.json").write_text(
                json.dumps({"id": "msg-1", "role": "user", "content": "create guidance"}),
                encoding="utf-8",
            )

            run_cli_json(
                ["workflow", "agent-chat", "--once", str(project)],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            self.assertTrue((project / "AGENTS.md").exists())
            self.assertTrue((project / "Assets" / "MCP" / "Context" / "ProjectSummary.md").exists())
            history = json.loads((project / ".umcp" / "chat" / "history.json").read_text(encoding="utf-8"))
            self.assertIn("Guidance written", history[-1]["content"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_agent_chat_once_can_run_safe_project_improvement_pass(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        inbox_dir = project / ".umcp" / "chat" / "user-inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Packages").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text(
                "public class Player {}",
                encoding="utf-8",
            )
            (project / "Packages" / "manifest.json").write_text(
                json.dumps({"dependencies": {"com.unity.test-framework": "1.6.0"}}),
                encoding="utf-8",
            )
            (inbox_dir / "20260411T1000000000000-msg.json").write_text(
                json.dumps({"id": "msg-1", "role": "user", "content": "improve project"}),
                encoding="utf-8",
            )

            run_cli_json(
                ["workflow", "agent-chat", "--once", str(project)],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            self.assertTrue((project / "AGENTS.md").exists())
            self.assertTrue((project / "Assets" / "Tests" / "EditMode" / "DemoProjectSmokeTests.cs").exists())
            history = json.loads((project / ".umcp" / "chat" / "history.json").read_text(encoding="utf-8"))
            self.assertIn("Safe project improvement pass finished.", history[-1]["content"])
            self.assertIn("Applied:", history[-1]["content"])
            self.assertIn("Skipped:", history[-1]["content"])
            self.assertIn("Sandbox scene skipped because no live Unity session is available.", history[-1]["content"])
            self.assertIn("Quality score:", history[-1]["content"])
            self.assertIn("->", history[-1]["content"])
            metadata = dict(history[-1].get("metadata") or {})
            self.assertEqual(metadata.get("kind"), "improve-project")
            self.assertIn("## Improve Project", str(metadata.get("markdown") or ""))
            self.assertEqual(dict(metadata.get("payload") or {}).get("projectRoot"), str(project))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_assistant_improve_project_uses_embedded_workflow_when_available(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            class ClientStub:
                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    return {}

            bridge = ChatBridge(project, ClientStub(), embedded_options=object())  # type: ignore[arg-type]
            captured_argv: list[list[str]] = []

            def fake_run_embedded_cli(argv: list[str]) -> dict[str, Any]:
                captured_argv.append(list(argv))
                return {
                    "available": True,
                    "baselineScore": 70.0,
                    "finalScore": 89.0,
                    "scoreDelta": 19.0,
                    "applied": [
                        {"fix": "guidance", "summary": "Wrote 2 guidance file(s)."},
                        {"fix": "event-system", "summary": "Repaired EventSystem with InputSystemUIInputModule."},
                    ],
                    "skipped": [
                        {"fix": "sandbox-scene", "reason": "Sandbox scene already exists."},
                    ],
            }

            bridge._assistant._run_embedded_cli = fake_run_embedded_cli  # type: ignore[method-assign]
            bridge._process_message({"id": "msg-1", "role": "user", "content": "improve project"})

            reply = bridge._history[-1]["content"]
            self.assertEqual(
                captured_argv,
                [["workflow", "improve-project", str(project)]],
            )
            self.assertIn("Safe project improvement pass finished.", reply)
            self.assertIn("Applied:", reply)
            self.assertIn("Wrote 2 guidance file(s).", reply)
            self.assertIn("Repaired EventSystem with InputSystemUIInputModule.", reply)
            self.assertIn("Skipped:", reply)
            self.assertIn("Sandbox scene already exists.", reply)
            self.assertIn("Quality score: 70.0 -> 89.0 (+19.0).", reply)
            metadata = dict(bridge._history[-1].get("metadata") or {})
            self.assertEqual(metadata.get("kind"), "improve-project")
            self.assertEqual(dict(metadata.get("payload") or {}).get("baselineScore"), 70.0)
            self.assertEqual(dict(metadata.get("payload") or {}).get("finalScore"), 89.0)
            self.assertIn("## Improve Project", str(metadata.get("markdown") or ""))
            self.assertIn("### Applied fixes", str(metadata.get("markdown") or ""))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_agent_chat_explicit_project_updates_selected_file_ipc_session(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            run_cli_json(
                ["workflow", "agent-chat", "--iterations", "0", str(project)],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            state = SessionStore(tmpdir / "session.json").load()
            self.assertEqual((state.selected_instance or {}).get("projectPath"), str(project))
            self.assertEqual((state.selected_instance or {}).get("projectName"), "DemoProject")
            self.assertEqual((state.selected_instance or {}).get("transport"), "file-ipc")
            self.assertIsNone((state.selected_instance or {}).get("port"))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_resolve_improve_project_context_uses_matching_selected_live_session(self) -> None:
        import click

        from cli_anything.unity_mcp.commands.workflow import _resolve_improve_project_context

        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            session_store = SessionStore(tmpdir / "session.json")
            session_store.save(
                SessionState(
                    selected_port=None,
                    selected_instance={
                        "projectName": "DemoProject",
                        "projectPath": str(project),
                        "port": None,
                        "transport": "file-ipc",
                    },
                )
            )

            class BackendStub:
                def __init__(self) -> None:
                    self.session_store = session_store
                    self.calls: list[tuple[str, Any]] = []

                def record_progress(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
                    return {"success": True}

                def ping(self, port: int | None = None) -> dict[str, Any]:
                    self.calls.append(("ping", port))
                    return {"projectName": "DemoProject", "projectPath": str(project)}

                def call_route_with_recovery(
                    self,
                    route: str,
                    *,
                    port: int | None = None,
                    recovery_timeout: float = 10.0,
                ) -> dict[str, Any]:
                    self.calls.append((route, port))
                    if route == "project/info":
                        return {"projectName": "DemoProject", "projectPath": str(project)}
                    if route == "editor/state":
                        return {"projectPath": str(project), "activeScene": "Main", "sceneDirty": False}
                    raise AssertionError(f"Unexpected route: {route}")

            ctx = click.Context(click.Command("workflow"))
            ctx.obj = SimpleNamespace(
                backend=BackendStub(),
                agent_profile=None,
                developer_profile=None,
                developer_source="default",
                agent_id="cli-anything-unity-mcp",
            )

            (
                resolved_project_root,
                workflow_port,
                inspect_payload,
                ping,
                project_info,
                editor_state,
                live_unity_available,
            ) = _resolve_improve_project_context(
                ctx,
                project_root=str(project),
                port=None,
                progress_label="Checking project context for improve-project",
            )

            self.assertEqual(resolved_project_root, str(project))
            self.assertIsNone(workflow_port)
            self.assertTrue(live_unity_available)
            self.assertEqual((inspect_payload or {}).get("summary", {}).get("projectPath"), str(project))
            self.assertEqual(ping.get("projectPath"), str(project))
            self.assertEqual(project_info.get("projectPath"), str(project))
            self.assertEqual(editor_state.get("projectPath"), str(project))
            self.assertEqual(
                ctx.obj.backend.calls,
                [
                    ("ping", None),
                    ("project/info", None),
                    ("editor/state", None),
                ],
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_agent_chat_once_skips_sandbox_creation_without_live_unity(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        inbox_dir = project / ".umcp" / "chat" / "user-inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text(
                "public class Player {}",
                encoding="utf-8",
            )
            (inbox_dir / "20260411T1000000000000-msg.json").write_text(
                json.dumps({"id": "msg-1", "role": "user", "content": "create sandbox scene"}),
                encoding="utf-8",
            )

            run_cli_json(
                ["workflow", "agent-chat", "--once", str(project)],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            history = json.loads((project / ".umcp" / "chat" / "history.json").read_text(encoding="utf-8"))
            self.assertIn(
                "Could not create the sandbox scene because no live Unity session is available.",
                history[-1]["content"],
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_assistant_improve_project_repairs_missing_event_system(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes" / "DemoProject_Sandbox.unity").write_text("", encoding="utf-8")

            class LiveClientStub:
                def __init__(self) -> None:
                    self.gameobjects = {
                        "Canvas": {
                            "path": "Canvas",
                            "components": ["Transform", "Canvas"],
                        }
                    }

                def is_alive(self, timeout: float = 0.2) -> bool:
                    return True

                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    if route == "scene/hierarchy":
                        return {
                            "hierarchy": [
                                {
                                    "name": name,
                                    "path": payload["path"],
                                    "hierarchyPath": payload["path"],
                                    "components": list(payload["components"]),
                                }
                                for name, payload in self.gameobjects.items()
                            ]
                        }
                    if route == "gameobject/create":
                        name = str(params.get("name") or "EventSystem")
                        self.gameobjects[name] = {
                            "path": name,
                            "components": ["Transform"],
                        }
                        return {"success": True, "name": name, "path": name}
                    if route == "component/add":
                        path = str(params.get("gameObjectPath") or params.get("path") or "")
                        component_type = str(params.get("componentType") or params.get("type") or "")
                        self.gameobjects.setdefault(path, {"path": path, "components": ["Transform"]})
                        if component_type not in self.gameobjects[path]["components"]:
                            self.gameobjects[path]["components"].append(component_type)
                        return {"success": True, "gameObjectPath": path, "component": component_type}
                    raise AssertionError(f"Unexpected route: {route}")

            bridge = ChatBridge(project, LiveClientStub())  # type: ignore[arg-type]
            bridge._process_message({"id": "msg-1", "role": "user", "content": "improve project"})

            reply = bridge._history[-1]["content"]
            self.assertIn("Repaired scene EventSystem setup", reply)
            self.assertIn("Sandbox scene already exists.", reply)
            self.assertIn("StandaloneInputModule", reply)
            self.assertIn("EventSystem", bridge.client.gameobjects)
            self.assertIn("EventSystem", bridge.client.gameobjects["EventSystem"]["components"])
            self.assertIn("StandaloneInputModule", bridge.client.gameobjects["EventSystem"]["components"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_assistant_improve_project_repairs_duplicate_audio_listeners(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes" / "DemoProject_Sandbox.unity").write_text("", encoding="utf-8")

            class LiveClientStub:
                def __init__(self) -> None:
                    self.gameobjects = {
                        "Main Camera": {
                            "path": "Main Camera",
                            "components": ["Transform", "Camera", "AudioListener"],
                        },
                        "UICamera": {
                            "path": "UICamera",
                            "components": ["Transform", "Camera", "AudioListener"],
                        },
                    }

                def is_alive(self, timeout: float = 0.2) -> bool:
                    return True

                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    if route == "scene/hierarchy":
                        return {
                            "hierarchy": [
                                {
                                    "name": name,
                                    "path": payload["path"],
                                    "hierarchyPath": payload["path"],
                                    "components": list(payload["components"]),
                                }
                                for name, payload in self.gameobjects.items()
                            ]
                        }
                    if route == "component/remove":
                        path = str(params.get("gameObjectPath") or params.get("gameObject") or "")
                        component = str(params.get("component") or "")
                        comps = self.gameobjects.get(path, {}).get("components", [])
                        if component in comps:
                            comps.remove(component)
                        return {"success": True, "gameObjectPath": path, "component": component, "removed": True}
                    raise AssertionError(f"Unexpected route: {route}")

            bridge = ChatBridge(project, LiveClientStub())  # type: ignore[arg-type]
            bridge._process_message({"id": "msg-1", "role": "user", "content": "improve project"})

            reply = bridge._history[-1]["content"]
            self.assertIn("Removed 1 extra AudioListener", reply)
            self.assertIn("Main Camera", reply)
            self.assertIn("EventSystem fix not needed because no Canvas UI was found.", reply)
            self.assertIn("AudioListener", bridge.client.gameobjects["Main Camera"]["components"])
            self.assertNotIn("AudioListener", bridge.client.gameobjects["UICamera"]["components"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_assistant_improve_project_cleans_disposable_probe_objects(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes" / "DemoProject_Sandbox.unity").write_text("", encoding="utf-8")

            class LiveClientStub:
                def __init__(self) -> None:
                    self.gameobjects = {
                        "Main Camera": {
                            "path": "Main Camera",
                            "components": ["Transform", "Camera", "AudioListener"],
                        },
                        "StandaloneProbe": {
                            "path": "StandaloneProbe",
                            "components": ["Transform"],
                        },
                    }

                def is_alive(self, timeout: float = 0.2) -> bool:
                    return True

                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    if route == "scene/hierarchy":
                        return {
                            "hierarchy": [
                                {
                                    "name": name,
                                    "path": payload["path"],
                                    "hierarchyPath": payload["path"],
                                    "components": list(payload["components"]),
                                }
                                for name, payload in self.gameobjects.items()
                            ]
                        }
                    if route == "gameobject/delete":
                        path = str(params.get("gameObjectPath") or params.get("path") or "")
                        removed = self.gameobjects.pop(path, None) is not None
                        return {"success": removed, "deleted": path}
                    raise AssertionError(f"Unexpected route: {route}")

            bridge = ChatBridge(project, LiveClientStub())  # type: ignore[arg-type]
            bridge._process_message({"id": "msg-1", "role": "user", "content": "improve project"})

            reply = bridge._history[-1]["content"]
            self.assertIn("Removed 1 disposable probe/demo object", reply)
            self.assertIn("StandaloneProbe", reply)
            self.assertNotIn("StandaloneProbe", bridge.client.gameobjects)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_assistant_improve_project_adds_missing_audio_listener(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes" / "DemoProject_Sandbox.unity").write_text("", encoding="utf-8")

            class LiveClientStub:
                def __init__(self) -> None:
                    self.gameobjects = {
                        "Main Camera": {
                            "path": "Main Camera",
                            "components": ["Transform", "Camera"],
                        },
                        "UICamera": {
                            "path": "UICamera",
                            "components": ["Transform", "Camera"],
                        },
                    }

                def is_alive(self, timeout: float = 0.2) -> bool:
                    return True

                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    if route == "scene/hierarchy":
                        return {
                            "hierarchy": [
                                {
                                    "name": name,
                                    "path": payload["path"],
                                    "hierarchyPath": payload["path"],
                                    "components": list(payload["components"]),
                                }
                                for name, payload in self.gameobjects.items()
                            ]
                        }
                    if route == "component/add":
                        path = str(params.get("gameObjectPath") or params.get("path") or "")
                        component_type = str(params.get("componentType") or params.get("type") or "")
                        self.gameobjects.setdefault(path, {"path": path, "components": ["Transform"]})
                        if component_type not in self.gameobjects[path]["components"]:
                            self.gameobjects[path]["components"].append(component_type)
                        return {"success": True, "gameObjectPath": path, "component": component_type}
                    raise AssertionError(f"Unexpected route: {route}")

            bridge = ChatBridge(project, LiveClientStub())  # type: ignore[arg-type]
            bridge._process_message({"id": "msg-1", "role": "user", "content": "improve project"})

            reply = bridge._history[-1]["content"]
            self.assertIn("Added AudioListener to Main Camera.", reply)
            self.assertIn("AudioListener", bridge.client.gameobjects["Main Camera"]["components"])
            self.assertNotIn("AudioListener", bridge.client.gameobjects["UICamera"]["components"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_assistant_improve_project_adds_missing_canvas_scaler(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes" / "DemoProject_Sandbox.unity").write_text("", encoding="utf-8")

            class LiveClientStub:
                def __init__(self) -> None:
                    self.gameobjects = {
                        "Main Camera": {
                            "path": "Main Camera",
                            "components": ["Transform", "Camera", "AudioListener"],
                        },
                        "HUDCanvas": {
                            "path": "HUDCanvas",
                            "components": ["Transform", "RectTransform", "Canvas", "GraphicRaycaster"],
                        },
                    }

                def is_alive(self, timeout: float = 0.2) -> bool:
                    return True

                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    if route == "scene/hierarchy":
                        return {
                            "hierarchy": [
                                {
                                    "name": name,
                                    "path": payload["path"],
                                    "hierarchyPath": payload["path"],
                                    "components": list(payload["components"]),
                                }
                                for name, payload in self.gameobjects.items()
                            ]
                        }
                    if route == "component/add":
                        path = str(params.get("gameObjectPath") or params.get("path") or "")
                        component_type = str(params.get("componentType") or params.get("type") or "")
                        self.gameobjects.setdefault(path, {"path": path, "components": ["Transform"]})
                        if component_type not in self.gameobjects[path]["components"]:
                            self.gameobjects[path]["components"].append(component_type)
                        return {"success": True, "gameObjectPath": path, "component": component_type}
                    if route == "gameobject/create":
                        name = str(params.get("name") or "EventSystem")
                        self.gameobjects[name] = {
                            "path": name,
                            "components": ["Transform"],
                        }
                        return {"success": True, "name": name, "path": name}
                    raise AssertionError(f"Unexpected route: {route}")

            bridge = ChatBridge(project, LiveClientStub())  # type: ignore[arg-type]
            bridge._process_message({"id": "msg-1", "role": "user", "content": "improve project"})

            reply = bridge._history[-1]["content"]
            self.assertIn("Added CanvasScaler to 1 Canvas object", reply)
            self.assertIn("HUDCanvas", reply)
            self.assertIn("CanvasScaler", bridge.client.gameobjects["HUDCanvas"]["components"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_assistant_improve_project_adds_missing_graphic_raycaster(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes" / "DemoProject_Sandbox.unity").write_text("", encoding="utf-8")

            class LiveClientStub:
                def __init__(self) -> None:
                    self.gameobjects = {
                        "Main Camera": {
                            "path": "Main Camera",
                            "components": ["Transform", "Camera", "AudioListener"],
                        },
                        "HUDCanvas": {
                            "path": "HUDCanvas",
                            "components": ["Transform", "RectTransform", "Canvas", "CanvasScaler"],
                        },
                    }

                def is_alive(self, timeout: float = 0.2) -> bool:
                    return True

                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    if route == "scene/hierarchy":
                        return {
                            "hierarchy": [
                                {
                                    "name": name,
                                    "path": payload["path"],
                                    "hierarchyPath": payload["path"],
                                    "components": list(payload["components"]),
                                }
                                for name, payload in self.gameobjects.items()
                            ]
                        }
                    if route == "component/add":
                        path = str(params.get("gameObjectPath") or params.get("path") or "")
                        component_type = str(params.get("componentType") or params.get("type") or "")
                        self.gameobjects.setdefault(path, {"path": path, "components": ["Transform"]})
                        if component_type not in self.gameobjects[path]["components"]:
                            self.gameobjects[path]["components"].append(component_type)
                        return {"success": True, "gameObjectPath": path, "component": component_type}
                    if route == "gameobject/create":
                        name = str(params.get("name") or "EventSystem")
                        self.gameobjects[name] = {
                            "path": name,
                            "components": ["Transform"],
                        }
                        return {"success": True, "name": name, "path": name}
                    raise AssertionError(f"Unexpected route: {route}")

            bridge = ChatBridge(project, LiveClientStub())  # type: ignore[arg-type]
            bridge._process_message({"id": "msg-1", "role": "user", "content": "improve project"})

            reply = bridge._history[-1]["content"]
            self.assertIn("Added GraphicRaycaster to 1 Canvas object", reply)
            self.assertIn("HUDCanvas", reply)
            self.assertIn("GraphicRaycaster", bridge.client.gameobjects["HUDCanvas"]["components"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_assistant_improve_project_adds_character_controller_to_likely_player(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes" / "DemoProject_Sandbox.unity").write_text("", encoding="utf-8")

            class LiveClientStub:
                def __init__(self) -> None:
                    self.gameobjects = {
                        "Main Camera": {
                            "path": "Main Camera",
                            "components": ["Transform", "Camera", "AudioListener"],
                        },
                        "PlayerAvatar": {
                            "path": "PlayerAvatar",
                            "components": ["Transform", "CapsuleCollider"],
                        },
                    }

                def is_alive(self, timeout: float = 0.2) -> bool:
                    return True

                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    if route == "scene/hierarchy":
                        return {
                            "hierarchy": [
                                {
                                    "name": name,
                                    "path": payload["path"],
                                    "hierarchyPath": payload["path"],
                                    "components": list(payload["components"]),
                                }
                                for name, payload in self.gameobjects.items()
                            ]
                        }
                    if route == "component/add":
                        path = str(params.get("gameObjectPath") or params.get("path") or "")
                        component_type = str(params.get("componentType") or params.get("type") or "")
                        self.gameobjects.setdefault(path, {"path": path, "components": ["Transform"]})
                        if component_type not in self.gameobjects[path]["components"]:
                            self.gameobjects[path]["components"].append(component_type)
                        return {"success": True, "gameObjectPath": path, "component": component_type}
                    raise AssertionError(f"Unexpected route: {route}")

            bridge = ChatBridge(project, LiveClientStub())  # type: ignore[arg-type]
            bridge._process_message({"id": "msg-1", "role": "user", "content": "improve project"})

            reply = bridge._history[-1]["content"]
            self.assertIn("Added CharacterController to PlayerAvatar.", reply)
            self.assertIn("CharacterController", bridge.client.gameobjects["PlayerAvatar"]["components"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_assistant_improve_project_refuses_ambiguous_character_controller_fix(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes" / "DemoProject_Sandbox.unity").write_text("", encoding="utf-8")

            class LiveClientStub:
                def __init__(self) -> None:
                    self.gameobjects = {
                        "Main Camera": {
                            "path": "Main Camera",
                            "components": ["Transform", "Camera", "AudioListener"],
                        },
                        "PlayerAvatar": {
                            "path": "PlayerAvatar",
                            "components": ["Transform", "CapsuleCollider"],
                        },
                        "HeroPawn": {
                            "path": "HeroPawn",
                            "components": ["Transform", "CapsuleCollider"],
                        },
                    }

                def is_alive(self, timeout: float = 0.2) -> bool:
                    return True

                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    if route == "scene/hierarchy":
                        return {
                            "hierarchy": [
                                {
                                    "name": name,
                                    "path": payload["path"],
                                    "hierarchyPath": payload["path"],
                                    "components": list(payload["components"]),
                                }
                                for name, payload in self.gameobjects.items()
                            ]
                        }
                    if route == "component/add":
                        raise AssertionError("CharacterController fix should not guess across multiple likely players.")
                    raise AssertionError(f"Unexpected route: {route}")

            bridge = ChatBridge(project, LiveClientStub())  # type: ignore[arg-type]
            bridge._process_message({"id": "msg-1", "role": "user", "content": "improve project"})

            reply = bridge._history[-1]["content"]
            self.assertIn("Multiple likely player objects were found", reply)
            self.assertNotIn("CharacterController", bridge.client.gameobjects["PlayerAvatar"]["components"])
            self.assertNotIn("CharacterController", bridge.client.gameobjects["HeroPawn"]["components"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_assistant_improve_project_repairs_existing_event_system_module(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes" / "DemoProject_Sandbox.unity").write_text("", encoding="utf-8")
            (project / "Packages").mkdir(parents=True, exist_ok=True)
            (project / "Packages" / "manifest.json").write_text(
                json.dumps({"dependencies": {"com.unity.inputsystem": "1.8.0"}}),
                encoding="utf-8",
            )

            class LiveClientStub:
                def __init__(self) -> None:
                    self.gameobjects = {
                        "Main Camera": {
                            "path": "Main Camera",
                            "components": ["Transform", "Camera", "AudioListener"],
                        },
                        "HUDCanvas": {
                            "path": "HUDCanvas",
                            "components": ["Transform", "RectTransform", "Canvas", "GraphicRaycaster", "CanvasScaler"],
                        },
                        "EventSystem": {
                            "path": "EventSystem",
                            "components": ["Transform", "EventSystem"],
                        },
                    }

                def is_alive(self, timeout: float = 0.2) -> bool:
                    return True

                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    if route == "scene/hierarchy":
                        return {
                            "hierarchy": [
                                {
                                    "name": name,
                                    "path": payload["path"],
                                    "hierarchyPath": payload["path"],
                                    "components": list(payload["components"]),
                                }
                                for name, payload in self.gameobjects.items()
                            ]
                        }
                    if route == "component/add":
                        path = str(params.get("gameObjectPath") or params.get("path") or "")
                        component_type = str(params.get("componentType") or params.get("type") or "")
                        self.gameobjects.setdefault(path, {"path": path, "components": ["Transform"]})
                        if component_type not in self.gameobjects[path]["components"]:
                            self.gameobjects[path]["components"].append(component_type)
                        return {"success": True, "gameObjectPath": path, "component": component_type}
                    raise AssertionError(f"Unexpected route: {route}")

            bridge = ChatBridge(project, LiveClientStub())  # type: ignore[arg-type]
            bridge._process_message({"id": "msg-1", "role": "user", "content": "improve project"})

            reply = bridge._history[-1]["content"]
            self.assertIn("Repaired scene EventSystem setup with InputSystemUIInputModule.", reply)
            self.assertIn("InputSystemUIInputModule", bridge.client.gameobjects["EventSystem"]["components"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_assistant_improve_project_removes_duplicate_event_system_components(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes" / "DemoProject_Sandbox.unity").write_text("", encoding="utf-8")
            (project / "Packages").mkdir(parents=True, exist_ok=True)
            (project / "Packages" / "manifest.json").write_text(
                json.dumps({"dependencies": {"com.unity.inputsystem": "1.8.0"}}),
                encoding="utf-8",
            )

            class LiveClientStub:
                def __init__(self) -> None:
                    self.gameobjects = {
                        "Main Camera": {
                            "path": "Main Camera",
                            "components": ["Transform", "Camera", "AudioListener"],
                        },
                        "HUDCanvas": {
                            "path": "HUDCanvas",
                            "components": ["Transform", "RectTransform", "Canvas", "GraphicRaycaster", "CanvasScaler"],
                        },
                        "EventSystem": {
                            "path": "EventSystem",
                            "components": ["Transform", "EventSystem", "InputSystemUIInputModule"],
                        },
                        "UIRoot/DuplicateEventSystem": {
                            "path": "UIRoot/DuplicateEventSystem",
                            "components": ["Transform", "EventSystem", "StandaloneInputModule"],
                        },
                    }

                def is_alive(self, timeout: float = 0.2) -> bool:
                    return True

                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    if route == "scene/hierarchy":
                        return {
                            "hierarchy": [
                                {
                                    "name": name,
                                    "path": payload["path"],
                                    "hierarchyPath": payload["path"],
                                    "components": list(payload["components"]),
                                }
                                for name, payload in self.gameobjects.items()
                            ]
                        }
                    if route == "component/add":
                        path = str(params.get("gameObjectPath") or params.get("path") or "")
                        component_type = str(params.get("componentType") or params.get("type") or "")
                        self.gameobjects.setdefault(path, {"path": path, "components": ["Transform"]})
                        if component_type not in self.gameobjects[path]["components"]:
                            self.gameobjects[path]["components"].append(component_type)
                        return {"success": True, "gameObjectPath": path, "component": component_type}
                    if route == "component/remove":
                        path = str(params.get("gameObjectPath") or params.get("gameObject") or "")
                        component = str(params.get("component") or "")
                        comps = self.gameobjects.get(path, {}).get("components", [])
                        if component in comps:
                            comps.remove(component)
                        return {"success": True, "gameObjectPath": path, "component": component, "removed": True}
                    raise AssertionError(f"Unexpected route: {route}")

            bridge = ChatBridge(project, LiveClientStub())  # type: ignore[arg-type]
            bridge._process_message({"id": "msg-1", "role": "user", "content": "improve project"})

            reply = bridge._history[-1]["content"]
            self.assertIn("Removed 1 duplicate EventSystem object", reply)
            self.assertIn("UIRoot/DuplicateEventSystem", reply)
            self.assertIn("EventSystem", bridge.client.gameobjects["EventSystem"]["components"])
            self.assertIn("InputSystemUIInputModule", bridge.client.gameobjects["EventSystem"]["components"])
            self.assertNotIn("EventSystem", bridge.client.gameobjects["UIRoot/DuplicateEventSystem"]["components"])
            self.assertNotIn(
                "StandaloneInputModule",
                bridge.client.gameobjects["UIRoot/DuplicateEventSystem"]["components"],
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_assistant_improve_project_removes_wrong_primary_event_system_module(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes" / "DemoProject_Sandbox.unity").write_text("", encoding="utf-8")
            (project / "Packages").mkdir(parents=True, exist_ok=True)
            (project / "Packages" / "manifest.json").write_text(
                json.dumps({"dependencies": {"com.unity.inputsystem": "1.8.0"}}),
                encoding="utf-8",
            )

            class LiveClientStub:
                def __init__(self) -> None:
                    self.gameobjects = {
                        "Main Camera": {
                            "path": "Main Camera",
                            "components": ["Transform", "Camera", "AudioListener"],
                        },
                        "HUDCanvas": {
                            "path": "HUDCanvas",
                            "components": ["Transform", "RectTransform", "Canvas", "GraphicRaycaster", "CanvasScaler"],
                        },
                        "EventSystem": {
                            "path": "EventSystem",
                            "components": [
                                "Transform",
                                "EventSystem",
                                "InputSystemUIInputModule",
                                "StandaloneInputModule",
                            ],
                        },
                    }

                def is_alive(self, timeout: float = 0.2) -> bool:
                    return True

                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    if route == "scene/hierarchy":
                        return {
                            "hierarchy": [
                                {
                                    "name": name,
                                    "path": payload["path"],
                                    "hierarchyPath": payload["path"],
                                    "components": list(payload["components"]),
                                }
                                for name, payload in self.gameobjects.items()
                            ]
                        }
                    if route == "component/add":
                        path = str(params.get("gameObjectPath") or params.get("path") or "")
                        component_type = str(params.get("componentType") or params.get("type") or "")
                        self.gameobjects.setdefault(path, {"path": path, "components": ["Transform"]})
                        if component_type not in self.gameobjects[path]["components"]:
                            self.gameobjects[path]["components"].append(component_type)
                        return {"success": True, "gameObjectPath": path, "component": component_type}
                    if route == "component/remove":
                        path = str(params.get("gameObjectPath") or params.get("gameObject") or "")
                        component = str(params.get("component") or "")
                        comps = self.gameobjects.get(path, {}).get("components", [])
                        if component in comps:
                            comps.remove(component)
                        return {"success": True, "gameObjectPath": path, "component": component, "removed": True}
                    raise AssertionError(f"Unexpected route: {route}")

            bridge = ChatBridge(project, LiveClientStub())  # type: ignore[arg-type]
            bridge._process_message({"id": "msg-1", "role": "user", "content": "improve project"})

            reply = bridge._history[-1]["content"]
            self.assertIn("Repaired scene EventSystem setup with InputSystemUIInputModule.", reply)
            self.assertIn("InputSystemUIInputModule", bridge.client.gameobjects["EventSystem"]["components"])
            self.assertNotIn("StandaloneInputModule", bridge.client.gameobjects["EventSystem"]["components"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_assistant_test_detection_ignores_tmp_parent_folder_names(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text(
                "public class Player {}",
                encoding="utf-8",
            )

            class ClientStub:
                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    return {}

            bridge = ChatBridge(project, ClientStub())  # type: ignore[arg-type]
            assistant = _OfflineUnityAssistant(bridge)

            self.assertFalse(assistant._project_has_tests())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_bridge_status_includes_pid(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            class ClientStub:
                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    return {}

            bridge = ChatBridge(project, ClientStub())  # type: ignore[arg-type]
            bridge.write_status("idle", 0, 0, "")

            status_path = project / ".umcp" / "agent-status.json"
            self.assertTrue(status_path.exists())
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["state"], "idle")
            self.assertEqual(payload["pid"], os.getpid())
            self.assertEqual(payload["projectPath"], str(project))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_bridge_idle_poll_refreshes_status_heartbeat(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            class ClientStub:
                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    return {}

            bridge = ChatBridge(project, ClientStub())  # type: ignore[arg-type]
            bridge._status_heartbeat_interval = 0.0

            bridge.poll_once()
            status_path = project / ".umcp" / "agent-status.json"
            first = json.loads(status_path.read_text(encoding="utf-8"))

            bridge.poll_once()
            second = json.loads(status_path.read_text(encoding="utf-8"))

            self.assertEqual(second["state"], "idle")
            self.assertNotEqual(first["lastUpdated"], second["lastUpdated"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_context_injector_refetches_for_full_context(self) -> None:
        class ClientStub:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, Any]]] = []

            def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                self.calls.append((route, params))
                return {"mode": "full" if params.get("full") else "summary"}

        client = ClientStub()
        injector = ContextInjector(client)  # type: ignore[arg-type]

        summary = injector.get()
        full = injector.get(full=True)

        self.assertEqual(summary["mode"], "summary")
        self.assertEqual(full["mode"], "full")
        self.assertEqual(
            client.calls,
            [
                ("context", {"full": False}),
                ("context", {"full": True}),
            ],
        )

    def test_mcp_server_context_prompt_uses_selected_instance_project_path(self) -> None:
        from cli_anything.unity_mcp.mcp_server import UnityThinMCPServer

        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        try:
            session_path = tmpdir / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(
                json.dumps(
                    {
                        "selected_instance": {
                            "projectName": "DemoProject",
                            "projectPath": "C:/Projects/DemoProject",
                            "transport": "file-ipc",
                        }
                    }
                ),
                encoding="utf-8",
            )

            server = UnityThinMCPServer(EmbeddedCLIOptions(session_path=session_path))

            with patch("cli_anything.unity_mcp.core.file_ipc.FileIPCClient") as file_client_cls:
                with patch("cli_anything.unity_mcp.core.file_ipc.ContextInjector") as injector_cls:
                    injector_cls.return_value.as_system_prompt.return_value = "ctx"

                    prompt = server._get_context_prompt()

            self.assertEqual(prompt, "ctx")
            file_client_cls.assert_called_once_with("C:/Projects/DemoProject")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_build_project_insights_detects_guidance_and_asset_pipeline_gaps(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Art" / "Models").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Art" / "Textures").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Packages").mkdir(parents=True, exist_ok=True)

            (project / "AGENTS.md").write_text("# Project instructions\nUse URP.\n", encoding="utf-8")
            (project / "Assets" / "Scripts" / "Player.cs").write_text("public class Player {}", encoding="utf-8")
            (project / "Assets" / "Art" / "Models" / "Hero.fbx").write_text("fbx", encoding="utf-8")
            (project / "Assets" / "Art" / "Models" / "Hero.fbx.meta").write_text(
                "\n".join(
                    (
                        "fileFormatVersion: 2",
                        "guid: hero-guid",
                        "ModelImporter:",
                        "  materialImportMode: 0",
                        "  importAnimation: 0",
                        "  animationType: 3",
                    )
                ),
                encoding="utf-8",
            )
            for index in range(10):
                (project / "Assets" / "Art" / "Textures" / f"HeroAlbedo_{index}.png").write_text("png", encoding="utf-8")
                (project / "Assets" / "Art" / "Textures" / f"HeroAlbedo_{index}.png.meta").write_text(
                    "\n".join(
                        (
                            "fileFormatVersion: 2",
                            f"guid: hero-albedo-{index}",
                            "TextureImporter:",
                            "  textureType: 0",
                        )
                    ),
                    encoding="utf-8",
                )
            (project / "Assets" / "Art" / "Textures" / "Hero_normal.png").write_text("png", encoding="utf-8")
            (project / "Assets" / "Art" / "Textures" / "Hero_normal.png.meta").write_text(
                "\n".join(
                    (
                        "fileFormatVersion: 2",
                        "guid: hero-normal",
                        "TextureImporter:",
                        "  textureType: 0",
                    )
                ),
                encoding="utf-8",
            )
            (project / "Assets" / "UI" / "Icons").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "UI" / "Icons" / "HudIcon.png").write_text("png", encoding="utf-8")
            (project / "Assets" / "UI" / "Icons" / "HudIcon.png.meta").write_text(
                "\n".join(
                    (
                        "fileFormatVersion: 2",
                        "guid: hud-icon",
                        "TextureImporter:",
                        "  textureType: 0",
                        "  spriteMode: 0",
                    )
                ),
                encoding="utf-8",
            )
            (project / "Assets" / "Scenes" / "Main.unity").write_text("scene", encoding="utf-8")
            (project / "Packages" / "manifest.json").write_text(
                json.dumps({"dependencies": {"com.unity.inputsystem": "1.8.0"}}),
                encoding="utf-8",
            )

            insights = build_project_insights(
                project,
                inspect_payload={"summary": {"sceneDirty": True}},
            )

            self.assertTrue(insights["available"])
            self.assertTrue(insights["guidance"]["hasAgentsMd"])
            self.assertEqual(insights["assetScan"]["counts"]["models"], 1)
            self.assertEqual(insights["assetScan"]["counts"]["textures"], 12)
            self.assertEqual(insights["assetScan"]["counts"]["materials"], 0)
            self.assertEqual(insights["assetScan"]["packageCount"], 1)
            self.assertEqual(insights["assetScan"]["importerAudit"]["modelImporterCount"], 1)
            self.assertEqual(
                insights["assetScan"]["importerAudit"]["modelImportMaterialDisabledCount"],
                1,
            )
            self.assertEqual(
                insights["assetScan"]["importerAudit"]["modelImportAnimationDisabledCount"],
                1,
            )
            self.assertEqual(insights["assetScan"]["importerAudit"]["modelRigConfiguredCount"], 1)
            self.assertEqual(insights["assetScan"]["importerAudit"]["textureImporterCount"], 12)
            self.assertEqual(
                insights["assetScan"]["importerAudit"]["potentialNormalMapMisconfiguredCount"],
                1,
            )
            self.assertEqual(
                insights["assetScan"]["importerAudit"]["potentialSpriteMisconfiguredCount"],
                1,
            )
            titles = {item["title"] for item in insights["recommendations"]}
            self.assertIn("Build A Material Library", titles)
            self.assertIn("Prefabize Imported Models", titles)
            self.assertIn("Audit Rig And Animation Pipeline", titles)
            self.assertIn("Review Model Material Import", titles)
            self.assertIn("Fix Likely Normal Map Imports", titles)
            self.assertIn("Fix Likely Sprite Imports", titles)
            self.assertIn("Save Or Snapshot The Active Scene", titles)
            self.assertNotIn("Add Agent Guidance", titles)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_build_asset_audit_report_summarizes_focus_areas(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Art" / "Models").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Art" / "Textures").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Packages").mkdir(parents=True, exist_ok=True)

            (project / "AGENTS.md").write_text("# Project instructions\nUse URP.\n", encoding="utf-8")
            (project / "Assets" / "Scripts" / "Player.cs").write_text("public class Player {}", encoding="utf-8")
            (project / "Assets" / "Art" / "Models" / "Hero.fbx").write_text("fbx", encoding="utf-8")
            (project / "Assets" / "Art" / "Models" / "Hero.fbx.meta").write_text(
                "\n".join(
                    (
                        "fileFormatVersion: 2",
                        "guid: hero-guid",
                        "ModelImporter:",
                        "  materialImportMode: 0",
                        "  importAnimation: 0",
                        "  animationType: 3",
                    )
                ),
                encoding="utf-8",
            )
            (project / "Assets" / "Art" / "Textures" / "Hero_normal.png").write_text("png", encoding="utf-8")
            (project / "Assets" / "Art" / "Textures" / "Hero_normal.png.meta").write_text(
                "\n".join(
                    (
                        "fileFormatVersion: 2",
                        "guid: hero-normal",
                        "TextureImporter:",
                        "  textureType: 0",
                    )
                ),
                encoding="utf-8",
            )
            (project / "Assets" / "UI" / "Icons").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "UI" / "Icons" / "HudIcon.png").write_text("png", encoding="utf-8")
            (project / "Assets" / "UI" / "Icons" / "HudIcon.png.meta").write_text(
                "\n".join(
                    (
                        "fileFormatVersion: 2",
                        "guid: hud-icon",
                        "TextureImporter:",
                        "  textureType: 0",
                        "  spriteMode: 0",
                    )
                ),
                encoding="utf-8",
            )
            (project / "Assets" / "Scenes" / "Main.unity").write_text("scene", encoding="utf-8")
            (project / "Packages" / "manifest.json").write_text(
                json.dumps({"dependencies": {"com.unity.inputsystem": "1.8.0"}}),
                encoding="utf-8",
            )

            report = build_asset_audit_report(
                project,
                inspect_payload={
                    "summary": {
                        "projectName": "DemoProject",
                        "activeScene": "Main",
                        "sceneDirty": True,
                    },
                    "project": {"renderPipeline": "UniversalRP"},
                },
                recommendation_limit=3,
            )

            self.assertTrue(report["available"])
            self.assertEqual(report["summary"]["projectName"], "DemoProject")
            self.assertEqual(report["summary"]["renderPipeline"], "UniversalRP")
            self.assertEqual(report["summary"]["textureCount"], 2)
            self.assertEqual(report["summary"]["modelCount"], 1)
            self.assertEqual(report["summary"]["packageCount"], 1)
            self.assertTrue(report["summary"]["hasGuidance"])
            self.assertTrue(report["summary"]["hasImporterAudit"])
            self.assertEqual(report["summary"]["highestPriority"], "medium")
            self.assertEqual(report["summary"]["potentialNormalMapMisconfiguredCount"], 1)
            self.assertEqual(report["summary"]["potentialSpriteMisconfiguredCount"], 1)
            self.assertEqual(report["priorityBreakdown"]["high"], 0)
            self.assertGreaterEqual(report["priorityBreakdown"]["medium"], 4)
            self.assertEqual(len(report["topRecommendations"]), 3)
            self.assertEqual(report["focusAreas"][0]["category"], "assets")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_build_guidance_bundle_creates_agents_and_context_templates(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Packages").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text("public class Player {}", encoding="utf-8")
            (project / "Assets" / "Scenes" / "Main.unity").write_text("scene", encoding="utf-8")
            (project / "Packages" / "manifest.json").write_text(
                json.dumps({"dependencies": {"com.unity.inputsystem": "1.8.0"}}),
                encoding="utf-8",
            )

            bundle = build_guidance_bundle(
                project,
                inspect_payload={
                    "summary": {
                        "projectName": "DemoProject",
                        "activeScene": "Main",
                        "sceneDirty": True,
                    },
                    "project": {"renderPipeline": "UniversalRP"},
                },
            )

            self.assertTrue(bundle["available"])
            files = {item["relativePath"]: item for item in bundle["files"]}
            self.assertIn("AGENTS.md", files)
            self.assertIn("Assets/MCP/Context/ProjectSummary.md", files)
            self.assertIn("Unity project `DemoProject`", files["AGENTS.md"]["content"])
            self.assertIn("Render pipeline: UniversalRP", files["AGENTS.md"]["content"])
            self.assertIn("Project Context", files["Assets/MCP/Context/ProjectSummary.md"]["content"])

            write_result = write_guidance_bundle(bundle)
            self.assertEqual(write_result["writeCount"], 2)
            self.assertTrue((project / "AGENTS.md").is_file())
            self.assertTrue((project / "Assets" / "MCP" / "Context" / "ProjectSummary.md").is_file())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_bootstrap_guidance_preview_works_with_direct_project_path(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text("public class Player {}", encoding="utf-8")
            (project / "Assets" / "Scenes" / "Main.unity").write_text("scene", encoding="utf-8")
            options = EmbeddedCLIOptions(
                session_path=tmpdir / "session.json",
                registry_path=tmpdir / "instances.json",
            )

            payload = run_cli_json(
                ["workflow", "bootstrap-guidance", str(project)],
                options,
            )

            self.assertTrue(payload["available"])
            self.assertEqual(payload["summary"]["projectName"], "DemoProject")
            self.assertEqual(payload["writeResult"]["writeCount"], 0)
            self.assertEqual(
                {item["status"] for item in payload["writeResult"]["writes"]},
                {"preview"},
            )
            self.assertFalse((project / "AGENTS.md").exists())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_developer_profiles_include_unity_expert_profiles(self) -> None:
        store = DeveloperProfileStore(path=Path("test-developer-profiles.json"))

        names = {profile.name for profile in store.list_profiles().profiles}

        self.assertTrue(
            {"director", "animator", "physics", "systems", "tech-artist", "ui-designer", "level-designer"} <= names
        )

    def test_expert_lens_registry_returns_expected_lenses(self) -> None:
        from cli_anything.unity_mcp.core.expert_lenses import (
            grade_score,
            iter_builtin_expert_lenses,
        )

        names = {lens.name for lens in iter_builtin_expert_lenses()}

        self.assertEqual(
            names,
            {"director", "systems", "physics", "animation", "tech-art", "ui", "level-art"},
        )
        self.assertEqual(grade_score(22), "poor")
        self.assertEqual(grade_score(55), "weak")
        self.assertEqual(grade_score(68), "workable")
        self.assertEqual(grade_score(80), "strong")
        self.assertEqual(grade_score(94), "excellent")

    def test_physics_lens_flags_rigidbody_without_collider(self) -> None:
        from cli_anything.unity_mcp.core.expert_rules.physics import audit_physics_lens

        result = audit_physics_lens(
            {
                "systems": {
                    "contextAvailable": True,
                    "hierarchyNodeCount": 3,
                    "activeCameraCount": 1,
                    "colliderCount": 0,
                    "characterControllerCount": 0,
                },
                "raw": {
                    "inspect": {
                        "hierarchy": {
                            "nodes": [
                                {"name": "Main Camera", "components": ["Transform", "Camera"]},
                                {"name": "PlayerRoot", "components": ["Transform", "Rigidbody"]},
                                {"name": "Environment", "components": ["Transform"]},
                            ]
                        }
                    }
                },
            }
        )

        titles = {item["title"] for item in result["findings"]}
        self.assertIn("Rigidbody objects without collider coverage", titles)
        finding = next(item for item in result["findings"] if item["title"] == "Rigidbody objects without collider coverage")
        self.assertIn("PlayerRoot", finding["detail"])

    def test_physics_lens_flags_likely_player_without_body(self) -> None:
        from cli_anything.unity_mcp.core.expert_rules.physics import audit_physics_lens

        result = audit_physics_lens(
            {
                "systems": {
                    "contextAvailable": True,
                    "hierarchyNodeCount": 4,
                    "activeCameraCount": 1,
                    "colliderCount": 2,
                    "characterControllerCount": 0,
                },
                "raw": {
                    "inspect": {
                        "hierarchy": {
                            "nodes": [
                                {"name": "Main Camera", "components": ["Transform", "Camera"]},
                                {"name": "PlayerAvatar", "components": ["Transform", "CapsuleCollider"]},
                                {"name": "Ground", "components": ["Transform", "BoxCollider"]},
                                {"name": "Light", "components": ["Transform", "Light"]},
                            ]
                        }
                    }
                },
            }
        )

        titles = {item["title"] for item in result["findings"]}
        self.assertIn("Likely player objects lack a movement body", titles)
        finding = next(item for item in result["findings"] if item["title"] == "Likely player objects lack a movement body")
        self.assertIn("PlayerAvatar", finding["detail"])

    def test_build_expert_context_merges_audit_and_inspect(self) -> None:
        from cli_anything.unity_mcp.core.expert_context import build_expert_context

        inspect_payload = {
            "available": True,
            "summary": {
                "projectName": "DemoGame",
                "projectPath": "C:/Projects/DemoGame",
                "activeScene": "Arena",
                "renderPipeline": "URP",
                "sceneDirty": False,
            },
            "state": {"isPlaying": False, "isCompiling": False},
            "scene": {"activeScene": "Arena"},
        }
        audit_report = {
            "available": True,
            "summary": {
                "projectName": "DemoGame",
                "renderPipeline": "URP",
                "materialCount": 8,
                "modelCount": 2,
                "animationCount": 1,
                "testScriptCount": 0,
            },
            "topRecommendations": [
                {"title": "Add tests", "detail": "No test scripts found."}
            ],
        }

        context = build_expert_context(
            inspect_payload=inspect_payload,
            audit_report=audit_report,
            lens_name="director",
        )

        self.assertEqual(context["project"]["name"], "DemoGame")
        self.assertEqual(context["project"]["renderPipeline"], "URP")
        self.assertEqual(context["lens"]["name"], "director")
        self.assertEqual(context["assets"]["materialCount"], 8)
        self.assertEqual(context["recommendations"][0]["title"], "Add tests")

    def test_director_lens_flags_missing_guidance_and_tests(self) -> None:
        from cli_anything.unity_mcp.core.expert_rules.director import audit_director_lens

        context = {
            "assets": {"testScriptCount": 0},
            "raw": {
                "audit": {
                    "guidance": {
                        "hasAgentsMd": False,
                        "hasContextFolder": False,
                    }
                }
            },
        }

        result = audit_director_lens(context)
        titles = {item["title"] for item in result["findings"]}

        self.assertIn("Missing project guidance", titles)
        self.assertIn("No test coverage detected", titles)

    def test_animation_lens_flags_models_without_animation(self) -> None:
        from cli_anything.unity_mcp.core.expert_rules.animation import (
            audit_animation_lens,
        )

        result = audit_animation_lens(
            {"assets": {"modelCount": 3, "animationCount": 0}}
        )

        self.assertIn(
            "Models found without animation evidence",
            {item["title"] for item in result["findings"]},
        )

    def test_animation_lens_flags_clips_without_controller(self) -> None:
        from cli_anything.unity_mcp.core.expert_rules.animation import (
            audit_animation_lens,
        )

        result = audit_animation_lens(
            {
                "assets": {
                    "modelCount": 0,
                    "animationCount": 2,
                    "animatorControllerCount": 0,
                }
            }
        )

        self.assertIn(
            "Animation clips without controller coverage",
            {item["title"] for item in result["findings"]},
        )

    def test_animation_lens_flags_scene_without_animator_components(self) -> None:
        from cli_anything.unity_mcp.core.expert_rules.animation import (
            audit_animation_lens,
        )

        result = audit_animation_lens(
            {
                "assets": {
                    "animationCount": 1,
                    "animatorControllerCount": 1,
                },
                "raw": {
                    "inspect": {
                        "hierarchy": {
                            "nodes": [
                                {
                                    "name": "PlayerRigRoot",
                                    "components": ["Transform", "SkinnedMeshRenderer"],
                                }
                            ]
                        }
                    }
                },
            }
        )

        self.assertIn(
            "No Animator components found in scene",
            {item["title"] for item in result["findings"]},
        )

    def test_systems_lens_flags_scene_without_audio_listener(self) -> None:
        from cli_anything.unity_mcp.core.expert_rules.systems import audit_systems_lens

        result = audit_systems_lens(
            {
                "assets": {"sceneCount": 1, "scriptCount": 0, "prefabCount": 0},
                "systems": {
                    "contextAvailable": True,
                    "hierarchyNodeCount": 2,
                    "activeCameraCount": 1,
                    "audioListenerCount": 0,
                    "canvasCount": 0,
                    "eventSystemCount": 0,
                    "characterControllerCount": 0,
                    "rigidbodyCount": 0,
                    "colliderCount": 0,
                    "likelyPlayerCount": 0,
                    "disposableObjectCount": 0,
                },
                "raw": {
                    "inspect": {
                        "hierarchy": {
                            "nodes": [
                                {"name": "Main Camera", "components": ["Transform", "Camera"]},
                                {"name": "HUDRoot", "components": ["Transform"]},
                            ]
                        }
                    }
                },
            }
        )

        self.assertIn(
            "No AudioListener in scene",
            {item["title"] for item in result["findings"]},
        )
        finding = next(item for item in result["findings"] if item["title"] == "No AudioListener in scene")
        self.assertIn("Main Camera", finding["detail"])

    def test_systems_lens_flags_duplicate_audio_listeners_with_names(self) -> None:
        from cli_anything.unity_mcp.core.expert_rules.systems import audit_systems_lens

        result = audit_systems_lens(
            {
                "assets": {"sceneCount": 1, "scriptCount": 0, "prefabCount": 0},
                "systems": {
                    "contextAvailable": True,
                    "hierarchyNodeCount": 3,
                    "activeCameraCount": 2,
                    "audioListenerCount": 2,
                    "canvasCount": 0,
                    "eventSystemCount": 0,
                    "characterControllerCount": 0,
                    "rigidbodyCount": 0,
                    "colliderCount": 0,
                    "likelyPlayerCount": 0,
                    "disposableObjectCount": 0,
                },
                "raw": {
                    "inspect": {
                        "hierarchy": {
                            "nodes": [
                                {"name": "Main Camera", "components": ["Transform", "Camera", "AudioListener"]},
                                {"name": "UICamera", "components": ["Transform", "Camera", "AudioListener"]},
                                {"name": "HUDRoot", "components": ["Transform"]},
                            ]
                        }
                    }
                },
            }
        )

        self.assertIn(
            "Multiple AudioListeners in scene",
            {item["title"] for item in result["findings"]},
        )
        finding = next(item for item in result["findings"] if item["title"] == "Multiple AudioListeners in scene")
        self.assertIn("Main Camera", finding["detail"])
        self.assertIn("UICamera", finding["detail"])
        self.assertIn("Likely keep target: Main Camera", finding["detail"])

    def test_systems_lens_flags_duplicate_event_systems(self) -> None:
        from cli_anything.unity_mcp.core.expert_rules.systems import audit_systems_lens

        result = audit_systems_lens(
            {
                "assets": {"sceneCount": 1, "scriptCount": 0, "prefabCount": 0},
                "systems": {
                    "contextAvailable": True,
                    "hierarchyNodeCount": 3,
                    "activeCameraCount": 1,
                    "audioListenerCount": 1,
                    "canvasCount": 1,
                    "eventSystemCount": 2,
                    "characterControllerCount": 0,
                    "rigidbodyCount": 0,
                    "colliderCount": 0,
                    "likelyPlayerCount": 0,
                    "disposableObjectCount": 0,
                },
                "raw": {
                    "inspect": {
                        "hierarchy": {
                            "nodes": [
                                {"name": "HUDCanvas", "components": ["Canvas", "CanvasScaler", "GraphicRaycaster"]},
                                {"name": "EventSystem", "components": ["EventSystem", "StandaloneInputModule"]},
                                {
                                    "name": "DuplicateEventSystem",
                                    "components": ["EventSystem", "StandaloneInputModule"],
                                },
                            ]
                        }
                    }
                },
            }
        )

        self.assertIn(
            "Multiple EventSystems in scene",
            {item["title"] for item in result["findings"]},
        )
        duplicate_finding = next(item for item in result["findings"] if item["title"] == "Multiple EventSystems in scene")
        self.assertIn("DuplicateEventSystem", duplicate_finding["detail"])

    def test_systems_lens_flags_event_system_without_input_module(self) -> None:
        from cli_anything.unity_mcp.core.expert_rules.systems import audit_systems_lens

        result = audit_systems_lens(
            {
                "assets": {"sceneCount": 1, "scriptCount": 0, "prefabCount": 0},
                "systems": {
                    "contextAvailable": True,
                    "hierarchyNodeCount": 2,
                    "activeCameraCount": 1,
                    "audioListenerCount": 1,
                    "canvasCount": 1,
                    "eventSystemCount": 1,
                    "characterControllerCount": 0,
                    "rigidbodyCount": 0,
                    "colliderCount": 0,
                    "likelyPlayerCount": 0,
                    "disposableObjectCount": 0,
                },
                "raw": {
                    "inspect": {
                        "hierarchy": {
                            "nodes": [
                                {"name": "HUDCanvas", "components": ["Canvas", "CanvasScaler", "GraphicRaycaster"]},
                                {"name": "EventSystem", "components": ["EventSystem"]},
                            ]
                        }
                    }
                },
            }
        )

        self.assertIn(
            "EventSystem missing UI input module",
            {item["title"] for item in result["findings"]},
        )

    def test_systems_lens_flags_conflicting_event_system_modules(self) -> None:
        from cli_anything.unity_mcp.core.expert_rules.systems import audit_systems_lens

        result = audit_systems_lens(
            {
                "assets": {"sceneCount": 1, "scriptCount": 0, "prefabCount": 0},
                "systems": {
                    "contextAvailable": True,
                    "hierarchyNodeCount": 2,
                    "activeCameraCount": 1,
                    "audioListenerCount": 1,
                    "canvasCount": 1,
                    "eventSystemCount": 1,
                    "characterControllerCount": 0,
                    "rigidbodyCount": 0,
                    "colliderCount": 0,
                    "likelyPlayerCount": 0,
                    "disposableObjectCount": 0,
                },
                "raw": {
                    "inspect": {
                        "hierarchy": {
                            "nodes": [
                                {"name": "HUDCanvas", "components": ["Canvas", "CanvasScaler", "GraphicRaycaster"]},
                                {
                                    "name": "EventSystem",
                                    "components": ["EventSystem", "StandaloneInputModule", "InputSystemUIInputModule"],
                                },
                            ]
                        }
                    }
                },
            }
        )

        self.assertIn(
            "EventSystem has conflicting UI input modules",
            {item["title"] for item in result["findings"]},
        )

    def test_tech_art_lens_flags_importer_mismatches(self) -> None:
        from cli_anything.unity_mcp.core.expert_rules.tech_art import (
            audit_tech_art_lens,
        )

        context = {
            "raw": {
                "audit": {
                    "assetScan": {
                        "importerAudit": {
                            "potentialNormalMapMisconfiguredCount": 1,
                            "potentialSpriteMisconfiguredCount": 1,
                        }
                    }
                }
            }
        }

        result = audit_tech_art_lens(context)

        self.assertIn(
            "Texture importer mismatches detected",
            {item["title"] for item in result["findings"]},
        )

    def test_ui_lens_flags_canvas_without_scaler(self) -> None:
        from cli_anything.unity_mcp.core.expert_rules.ui import audit_ui_lens

        context = {
            "raw": {
                "inspect": {
                    "hierarchy": {
                        "nodes": [
                            {
                                "name": "HUD",
                                "components": ["Canvas", "GraphicRaycaster"],
                            }
                        ]
                    }
                }
            }
        }

        result = audit_ui_lens(context)

        self.assertIn(
            "Canvas without CanvasScaler",
            {item["title"] for item in result["findings"]},
        )

    def test_ui_lens_flags_canvas_without_graphic_raycaster(self) -> None:
        from cli_anything.unity_mcp.core.expert_rules.ui import audit_ui_lens

        context = {
            "raw": {
                "inspect": {
                    "hierarchy": {
                        "nodes": [
                            {
                                "name": "HUD",
                                "components": ["Canvas", "CanvasScaler"],
                            }
                        ]
                    }
                }
            }
        }

        result = audit_ui_lens(context)

        self.assertIn(
            "Canvas without GraphicRaycaster",
            {item["title"] for item in result["findings"]},
        )

    def test_build_quality_fix_plan_supports_guidance_and_sandbox(self) -> None:
        from cli_anything.unity_mcp.core.expert_fixes import build_quality_fix_plan

        context = {
            "project": {"path": "C:/Projects/DemoGame", "name": "DemoGame"},
            "raw": {
                "audit": {
                    "assetScan": {
                        "packages": ["com.unity.inputsystem"],
                    }
                },
                "inspect": {
                    "hierarchy": {
                        "nodes": [
                            {
                                "name": "Hero",
                                "path": "/Hero",
                                "components": ["Transform", "Animator"],
                            }
                        ]
                    }
                }
            },
        }

        guidance_plan = build_quality_fix_plan(
            context=context,
            lens_name="director",
            fix_name="guidance",
        )
        test_scaffold_plan = build_quality_fix_plan(
            context=context,
            lens_name="director",
            fix_name="test-scaffold",
        )
        sandbox_plan = build_quality_fix_plan(
            context=context,
            lens_name="level-art",
            fix_name="sandbox-scene",
        )
        systems_plan = build_quality_fix_plan(
            context=context,
            lens_name="systems",
            fix_name="event-system",
        )
        systems_audio_plan = build_quality_fix_plan(
            context=context,
            lens_name="systems",
            fix_name="audio-listener",
        )
        systems_cleanup_plan = build_quality_fix_plan(
            context=context,
            lens_name="systems",
            fix_name="disposable-cleanup",
        )
        ui_graphic_raycaster_plan = build_quality_fix_plan(
            context=context,
            lens_name="ui",
            fix_name="ui-graphic-raycaster",
        )
        tech_art_plan = build_quality_fix_plan(
            context=context,
            lens_name="tech-art",
            fix_name="texture-imports",
        )
        animation_plan = build_quality_fix_plan(
            context=context,
            lens_name="animation",
            fix_name="controller-scaffold",
        )
        animation_wireup_plan = build_quality_fix_plan(
            context=context,
            lens_name="animation",
            fix_name="controller-wireup",
        )
        physics_plan = build_quality_fix_plan(
            context=context,
            lens_name="physics",
            fix_name="player-character-controller",
        )

        self.assertEqual(guidance_plan["command"][0:2], ["workflow", "bootstrap-guidance"])
        self.assertEqual(test_scaffold_plan["command"][0:2], ["workflow", "quality-fix"])
        self.assertTrue(test_scaffold_plan["requiresTestFrameworkPackage"])
        self.assertEqual(test_scaffold_plan["fileCount"], 2)
        self.assertTrue(str(test_scaffold_plan["scriptPath"]).endswith("DemoGameSmokeTests.cs"))
        self.assertTrue(str(test_scaffold_plan["asmdefPath"]).endswith("DemoGame.EditMode.Tests.asmdef"))
        self.assertEqual(sandbox_plan["command"][0:2], ["workflow", "create-sandbox-scene"])
        self.assertEqual(systems_plan["command"][0:2], ["workflow", "quality-fix"])
        self.assertEqual(systems_plan["moduleType"], "InputSystemUIInputModule")
        self.assertEqual(systems_plan["gameObjectName"], "EventSystem")
        self.assertTrue(systems_plan["requiresLiveUnity"])
        self.assertEqual(systems_audio_plan["command"][0:2], ["workflow", "quality-fix"])
        self.assertEqual(systems_audio_plan["fix"], "audio-listener")
        self.assertTrue(systems_audio_plan["requiresLiveUnity"])
        self.assertEqual(systems_cleanup_plan["command"][0:2], ["workflow", "quality-fix"])
        self.assertEqual(systems_cleanup_plan["fix"], "disposable-cleanup")
        self.assertTrue(systems_cleanup_plan["requiresLiveUnity"])
        self.assertEqual(ui_graphic_raycaster_plan["command"][0:2], ["workflow", "quality-fix"])
        self.assertEqual(ui_graphic_raycaster_plan["fix"], "ui-graphic-raycaster")
        self.assertTrue(ui_graphic_raycaster_plan["requiresLiveUnity"])
        self.assertEqual(tech_art_plan["command"][0:2], ["workflow", "quality-fix"])
        self.assertEqual(animation_plan["command"][0:2], ["workflow", "quality-fix"])
        self.assertTrue(animation_plan["requiresLiveUnity"])
        self.assertEqual(animation_wireup_plan["command"][0:2], ["workflow", "quality-fix"])
        self.assertEqual(animation_wireup_plan["targetGameObjectPath"], "/Hero")
        self.assertTrue(animation_wireup_plan["requiresLiveUnity"])
        self.assertEqual(physics_plan["command"][0:2], ["workflow", "quality-fix"])
        self.assertEqual(physics_plan["fix"], "player-character-controller")
        self.assertTrue(physics_plan["requiresLiveUnity"])
        self.assertEqual(physics_plan["targetGameObjectPath"], "/Hero")

    def test_workflow_expert_audit_returns_lens_result(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text(
                "public class Player {}",
                encoding="utf-8",
            )
            (project / "Assets" / "Scenes" / "Main.unity").write_text(
                "scene",
                encoding="utf-8",
            )

            payload = run_cli_json(
                ["workflow", "expert-audit", "--lens", "director", str(project)],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            self.assertTrue(payload["available"])
            self.assertEqual(payload["lens"]["name"], "director")
            self.assertIn("score", payload)
            self.assertIn("findings", payload)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_expert_audit_returns_systems_findings_for_project_path(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text(
                "public class Player {}",
                encoding="utf-8",
            )
            (project / "Assets" / "Scenes" / "Main.unity").write_text(
                "scene",
                encoding="utf-8",
            )

            payload = run_cli_json(
                ["workflow", "expert-audit", "--lens", "systems", str(project)],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            self.assertTrue(payload["available"])
            self.assertEqual(payload["lens"]["name"], "systems")
            self.assertIn(
                "No sandbox scene detected",
                {item["title"] for item in payload["findings"]},
            )
            self.assertIn(
                "Scene-first content with no prefab coverage",
                {item["title"] for item in payload["findings"]},
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_quality_fix_returns_plan_for_guidance(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text(
                "public class Player {}",
                encoding="utf-8",
            )

            payload = run_cli_json(
                [
                    "workflow",
                    "quality-fix",
                    "--lens",
                    "director",
                    "--fix",
                    "guidance",
                    str(project),
                ],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            self.assertTrue(payload["available"])
            self.assertEqual(payload["fix"]["name"], "guidance")
            self.assertEqual(payload["plan"]["mode"], "workflow")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_quality_fix_apply_writes_guidance_for_project_path(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text(
                "public class Player {}",
                encoding="utf-8",
            )

            payload = run_cli_json(
                [
                    "workflow",
                    "quality-fix",
                    "--lens",
                    "director",
                    "--fix",
                    "guidance",
                    "--apply",
                    str(project),
                ],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            self.assertTrue(payload["available"])
            self.assertTrue(payload["applyResult"]["applied"])
            self.assertEqual(payload["applyResult"]["mode"], "workflow")
            self.assertEqual(payload["applyResult"]["result"]["writeResult"]["writeCount"], 2)
            self.assertTrue((project / "AGENTS.md").exists())
            self.assertTrue((project / "Assets" / "MCP" / "Context" / "ProjectSummary.md").exists())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_quality_fix_apply_writes_test_scaffold_for_project_path(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Packages").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text(
                "public class Player {}",
                encoding="utf-8",
            )
            (project / "Packages" / "manifest.json").write_text(
                json.dumps({"dependencies": {"com.unity.test-framework": "1.6.0"}}),
                encoding="utf-8",
            )

            payload = run_cli_json(
                [
                    "workflow",
                    "quality-fix",
                    "--lens",
                    "director",
                    "--fix",
                    "test-scaffold",
                    "--apply",
                    str(project),
                ],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            self.assertTrue(payload["available"])
            self.assertTrue(payload["applyResult"]["applied"])
            self.assertEqual(payload["applyResult"]["result"]["writeCount"], 2)
            script_path = project / "Assets" / "Tests" / "EditMode" / "DemoProjectSmokeTests.cs"
            asmdef_path = project / "Assets" / "Tests" / "EditMode" / "DemoProject.EditMode.Tests.asmdef"
            self.assertTrue(script_path.exists())
            self.assertTrue(asmdef_path.exists())
            self.assertIn("NUnit.Framework", script_path.read_text(encoding="utf-8"))
            asmdef_payload = json.loads(asmdef_path.read_text(encoding="utf-8"))
            self.assertEqual(asmdef_payload["name"], "DemoProject.EditMode.Tests")
            self.assertIn("TestAssemblies", asmdef_payload["optionalUnityReferences"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_improve_project_runs_offline_safe_pass(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Packages").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text(
                "public class Player {}",
                encoding="utf-8",
            )
            (project / "Packages" / "manifest.json").write_text(
                json.dumps({"dependencies": {"com.unity.test-framework": "1.6.0"}}),
                encoding="utf-8",
            )

            payload = run_cli_json(
                [
                    "workflow",
                    "improve-project",
                    str(project),
                ],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            self.assertTrue(payload["available"])
            self.assertFalse(payload["liveUnityAvailable"])
            self.assertGreaterEqual(payload["appliedCount"], 2)
            self.assertGreaterEqual(payload["skippedCount"], 1)
            self.assertIsNotNone(payload["baselineScore"])
            self.assertIsNotNone(payload["finalScore"])
            self.assertGreater(payload["finalScore"], payload["baselineScore"])
            applied_fixes = {item["fix"] for item in payload["applied"]}
            skipped_fixes = {item["fix"] for item in payload["skipped"]}
            self.assertIn("guidance", applied_fixes)
            self.assertIn("test-scaffold", applied_fixes)
            self.assertIn("sandbox-scene", skipped_fixes)
            self.assertIn("event-system", skipped_fixes)
            self.assertTrue((project / "AGENTS.md").exists())
            self.assertTrue((project / "Assets" / "Tests" / "EditMode" / "DemoProjectSmokeTests.cs").exists())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_improve_project_writes_markdown_report(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        report_path = tmpdir / "improve-project.md"
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Packages").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text(
                "public class Player {}",
                encoding="utf-8",
            )
            (project / "Packages" / "manifest.json").write_text(
                json.dumps({"dependencies": {"com.unity.test-framework": "1.6.0"}}),
                encoding="utf-8",
            )

            payload = run_cli_json(
                [
                    "workflow",
                    "improve-project",
                    "--markdown-file",
                    str(report_path),
                    str(project),
                ],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            self.assertEqual(payload["markdownFile"], str(report_path))
            self.assertTrue(report_path.exists())
            markdown = report_path.read_text(encoding="utf-8")
            self.assertIn("## Improve Project", markdown)
            self.assertIn("Quality score", markdown)
            self.assertIn("### Applied fixes", markdown)
            self.assertIn("### Skipped fixes", markdown)
            self.assertIn("Wrote 2 guidance file(s).", markdown)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_build_quality_fix_plan_reads_test_framework_from_manifest_when_audit_packages_are_truncated(self) -> None:
        from cli_anything.unity_mcp.core.expert_fixes import build_quality_fix_plan

        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        try:
            (project / "Packages").mkdir(parents=True, exist_ok=True)
            (project / "Packages" / "manifest.json").write_text(
                json.dumps(
                    {
                        "dependencies": {
                            "com.unity.inputsystem": "1.6.0",
                            "com.unity.test-framework": "1.6.0",
                        }
                    }
                ),
                encoding="utf-8",
            )
            context = {
                "project": {
                    "path": str(project),
                    "name": "DemoProject",
                },
                "raw": {
                    "audit": {
                        "assetScan": {
                            "packages": ["com.unity.inputsystem"],
                        }
                    }
                },
            }

            plan = build_quality_fix_plan(
                context=context,
                lens_name="director",
                fix_name="test-scaffold",
            )

            self.assertEqual(plan["mode"], "workflow")
            self.assertTrue(plan["hasTestFrameworkPackage"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_quality_fix_apply_reads_test_framework_from_manifest_when_audit_packages_are_truncated(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Packages").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text(
                "public class Player {}",
                encoding="utf-8",
            )
            dependencies = {
                f"com.example.pkg{i:02d}": "1.0.0"
                for i in range(30)
            }
            dependencies["com.unity.test-framework"] = "1.6.0"
            (project / "Packages" / "manifest.json").write_text(
                json.dumps({"dependencies": dependencies}),
                encoding="utf-8",
            )

            payload = run_cli_json(
                [
                    "workflow",
                    "quality-fix",
                    "--lens",
                    "director",
                    "--fix",
                    "test-scaffold",
                    "--apply",
                    str(project),
                ],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            self.assertTrue(payload["available"])
            self.assertTrue(payload["applyResult"]["applied"])
            self.assertEqual(payload["applyResult"]["result"]["writeCount"], 2)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_quality_fix_returns_animation_controller_scaffold_plan(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        try:
            (project / "Assets" / "Animations").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Characters").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Characters" / "Hero.fbx").write_bytes(b"fbx")

            payload = run_cli_json(
                [
                    "workflow",
                    "quality-fix",
                    "--lens",
                    "animation",
                    "--fix",
                    "controller-scaffold",
                    str(project),
                ],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            self.assertTrue(payload["available"])
            self.assertEqual(payload["fix"]["name"], "controller-scaffold")
            self.assertEqual(payload["plan"]["mode"], "workflow")
            self.assertTrue(payload["plan"]["requiresLiveUnity"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_scene_critique_returns_multiple_lenses(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text(
                "public class Player {}",
                encoding="utf-8",
            )

            payload = run_cli_json(
                ["workflow", "scene-critique", str(project)],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            self.assertTrue(payload["available"])
            self.assertGreaterEqual(len(payload["lenses"]), 3)
            self.assertIn("findingCount", payload)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_quality_score_returns_overall_score(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text(
                "public class Player {}",
                encoding="utf-8",
            )

            payload = run_cli_json(
                ["workflow", "quality-score", str(project)],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            self.assertTrue(payload["available"])
            self.assertIsNotNone(payload["overallScore"])
            self.assertGreaterEqual(len(payload["lensScores"]), 6)
            self.assertIn("systems", {item["name"] for item in payload["lensScores"]})
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_benchmark_report_writes_stable_json_summary(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        report_file = tmpdir / "benchmark.json"
        original_memory_dir = os.environ.get("CLI_ANYTHING_UNITY_MCP_MEMORY_DIR")
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scenes").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text(
                "public class Player {}",
                encoding="utf-8",
            )
            (project / "Assets" / "Scenes" / "Main.unity").write_text(
                "scene",
                encoding="utf-8",
            )
            memory_root = tmpdir / "memory"
            memory = ProjectMemory(str(project), store_root=memory_root, allow_fallback=False)
            compilation_entry = {
                "message": (
                    "Assets/Scripts/Player.cs(12,8): error CS0246: "
                    "The type or namespace name 'Foo' could not be found"
                )
            }
            queue_signal = {
                "kind": "queue",
                "key": "queue-contention",
                "title": "Queue contention",
                "detail": "Queue still had active work pending.",
            }
            memory.record_compilation_errors([compilation_entry], "MainScene")
            memory.record_compilation_errors([compilation_entry], "MainScene")
            memory.record_operational_signals([queue_signal], "MainScene")
            memory.record_operational_signals([queue_signal], "MainScene")
            memory.record_queue_snapshot({"totalQueued": 2, "activeAgents": 1}, "MainScene")
            memory.record_queue_snapshot({"totalQueued": 2, "activeAgents": 1}, "MainScene")
            memory.record_queue_snapshot({"totalQueued": 2, "activeAgents": 1}, "MainScene")
            os.environ["CLI_ANYTHING_UNITY_MCP_MEMORY_DIR"] = str(memory_root)

            payload = run_cli_json(
                [
                    "workflow",
                    "benchmark-report",
                    "--report-file",
                    str(report_file),
                    str(project),
                ],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            self.assertTrue(payload["available"])
            self.assertEqual(payload["benchmarkVersion"], "unity-mastery-v1")
            self.assertIsNotNone(payload["overallScore"])
            self.assertTrue(report_file.exists())
            written = json.loads(report_file.read_text(encoding="utf-8"))
            self.assertEqual(written["overallScore"], payload["overallScore"])
            self.assertIn("systems", {item["name"] for item in payload["lensScores"]})
            self.assertEqual(
                payload["diagnosticsMemory"]["recurringCompilationErrorCount"],
                1,
            )
            self.assertEqual(
                payload["diagnosticsMemory"]["recurringOperationalSignalCount"],
                1,
            )
            self.assertEqual(
                written["diagnosticsMemory"]["recurringCompilationErrors"][0]["code"],
                "CS0246",
            )
            self.assertEqual(
                written["diagnosticsMemory"]["recurringOperationalSignals"][0]["key"],
                "queue-contention",
            )
            self.assertEqual(
                payload["queueDiagnostics"]["status"],
                "contention-observed",
            )
            self.assertEqual(
                payload["queueDiagnostics"]["recurringSignalCount"],
                1,
            )
            self.assertEqual(
                payload["queueDiagnostics"]["keys"],
                ["queue-contention"],
            )
            self.assertIn(
                "Queue pressure",
                payload["queueDiagnostics"]["summary"],
            )
            self.assertEqual(
                payload["queueTrend"]["status"],
                "stalled-backlog-suspected",
            )
            self.assertEqual(
                payload["queueTrend"]["sampleCount"],
                3,
            )
        finally:
            if original_memory_dir is None:
                os.environ.pop("CLI_ANYTHING_UNITY_MCP_MEMORY_DIR", None)
            else:
                os.environ["CLI_ANYTHING_UNITY_MCP_MEMORY_DIR"] = original_memory_dir
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_benchmark_compare_summarizes_deltas_and_recurring_diagnostics(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        before_file = tmpdir / "before.json"
        after_file = tmpdir / "after.json"
        markdown_file = tmpdir / "compare.md"
        try:
            tmpdir.mkdir(parents=True, exist_ok=True)
            before_payload = {
                "available": True,
                "benchmarkVersion": "unity-mastery-v1",
                "label": "before",
                "overallScore": 78.0,
                "overallGrade": "strong",
                "lensScores": [
                    {"name": "director", "score": 80, "grade": "strong", "findingCount": 2},
                    {"name": "systems", "score": 76, "grade": "strong", "findingCount": 1},
                ],
                "topFindings": [
                    {"lens": "director", "severity": "medium", "title": "No tests", "detail": "Add tests."},
                    {"lens": "systems", "severity": "low", "title": "No sandbox scene", "detail": "Create one."},
                ],
                "diagnosticsMemory": {
                    "recurringCompilationErrorCount": 1,
                    "recurringOperationalSignalCount": 1,
                    "recurringCompilationErrors": [
                        {"code": "CS0246", "file": "Assets/Scripts/Player.cs", "message": "Missing type"}
                    ],
                    "recurringOperationalSignals": [
                        {"kind": "queue", "key": "queue-contention", "title": "Queue contention"}
                    ],
                },
                "queueDiagnostics": {
                    "status": "contention-observed",
                    "recurringSignalCount": 1,
                    "keys": ["queue-contention"],
                    "summary": "Queue pressure has shown up repeatedly in this project.",
                },
                "queueTrend": {
                    "status": "stalled-backlog-suspected",
                    "sampleCount": 4,
                    "backlogSamples": 4,
                    "activeSamples": 4,
                    "peakQueued": 3,
                    "peakActiveAgents": 1,
                    "consecutiveBacklogSamples": 4,
                    "summary": "Queue backlog has stayed non-zero with the same shape across repeated samples.",
                },
            }
            after_payload = {
                "available": True,
                "benchmarkVersion": "unity-mastery-v1",
                "label": "after",
                "overallScore": 86.0,
                "overallGrade": "strong",
                "lensScores": [
                    {"name": "director", "score": 92, "grade": "excellent", "findingCount": 1},
                    {"name": "systems", "score": 80, "grade": "strong", "findingCount": 1},
                ],
                "topFindings": [
                    {"lens": "systems", "severity": "low", "title": "No sandbox scene", "detail": "Create one."},
                    {"lens": "tech-art", "severity": "medium", "title": "Importer mismatch", "detail": "Fix texture importers."},
                ],
                "diagnosticsMemory": {
                    "recurringCompilationErrorCount": 0,
                    "recurringOperationalSignalCount": 1,
                    "recurringCompilationErrors": [],
                    "recurringOperationalSignals": [
                        {"kind": "bridge", "key": "bridge-port-hop", "title": "Bridge port hop"}
                    ],
                },
                "queueDiagnostics": {
                    "status": "clear",
                    "recurringSignalCount": 0,
                    "keys": [],
                    "summary": "No recurring queue pressure detected.",
                },
                "queueTrend": {
                    "status": "clear",
                    "sampleCount": 4,
                    "backlogSamples": 0,
                    "activeSamples": 0,
                    "peakQueued": 0,
                    "peakActiveAgents": 0,
                    "consecutiveBacklogSamples": 0,
                    "summary": "Recent queue samples stayed clear.",
                },
            }
            before_file.write_text(json.dumps(before_payload, indent=2), encoding="utf-8")
            after_file.write_text(json.dumps(after_payload, indent=2), encoding="utf-8")

            payload = run_cli_json(
                [
                    "workflow",
                    "benchmark-compare",
                    "--markdown-file",
                    str(markdown_file),
                    str(before_file),
                    str(after_file),
                ],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            self.assertTrue(payload["available"])
            self.assertEqual(payload["overallScoreDelta"], 8.0)
            self.assertEqual(payload["findingDelta"]["newCount"], 1)
            self.assertEqual(payload["findingDelta"]["resolvedCount"], 1)
            self.assertEqual(payload["diagnosticsDelta"]["newRecurringOperationalSignalCount"], 1)
            self.assertEqual(payload["diagnosticsDelta"]["resolvedRecurringCompilationErrorCount"], 1)
            self.assertEqual(payload["queueDiagnosticsDelta"]["beforeStatus"], "contention-observed")
            self.assertEqual(payload["queueDiagnosticsDelta"]["afterStatus"], "clear")
            self.assertEqual(payload["queueDiagnosticsDelta"]["resolvedCount"], 1)
            self.assertEqual(payload["queueDiagnosticsDelta"]["recurringSignalDelta"], -1)
            self.assertEqual(payload["queueTrendDelta"]["beforeStatus"], "stalled-backlog-suspected")
            self.assertEqual(payload["queueTrendDelta"]["afterStatus"], "clear")
            self.assertEqual(payload["queueTrendDelta"]["backlogSampleDelta"], -4)
            self.assertEqual(payload["queueTrendDelta"]["consecutiveBacklogDelta"], -4)
            self.assertEqual(payload["lensDeltas"][0]["name"], "director")
            self.assertEqual(payload["lensDeltas"][0]["scoreDelta"], 12)
            self.assertEqual(payload["newFindings"][0]["title"], "Importer mismatch")
            self.assertEqual(payload["resolvedFindings"][0]["title"], "No tests")
            self.assertTrue(markdown_file.exists())
            self.assertIn("Overall score: `78.0 -> 86.0` (`+8.0`)", payload["markdownSummary"])
            self.assertIn("- New findings: 1", payload["markdownSummary"])
            self.assertIn("- Resolved findings: 1", payload["markdownSummary"])
            self.assertIn("Queue health", payload["markdownSummary"])
            self.assertIn("Queue trend", payload["markdownSummary"])
            self.assertIn("Recurring diagnostics", markdown_file.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_failed_route_hint_includes_tool_transport_port_and_retry(self) -> None:
        hint = _format_failed_route_hint(
            {
                "command": "editor/state",
                "transport": "queue",
                "port": 7890,
            }
        )
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertIn("editor/state", hint)
        self.assertIn("unity_editor_state", hint)
        self.assertIn("queue", hint)
        self.assertIn("7890", hint)
        self.assertIn("debug doctor --port 7890", hint)
        self.assertIn("agent queue --port 7890", hint)
        self.assertIn("agent sessions --port 7890", hint)

    def test_failed_route_hint_handles_file_ipc_without_port(self) -> None:
        hint = _format_failed_route_hint(
            {
                "command": "scene/info",
                "transport": "file-ipc",
                "port": None,
            }
        )
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertIn("scene/info", hint)
        self.assertIn("unity_scene_info", hint)
        self.assertIn("file-ipc", hint)
        self.assertIn("debug bridge", hint)
        self.assertNotIn("--port", hint)

    def test_cli_exception_message_ignores_stale_unrelated_history_error(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            store = SessionStore(tmpdir / "session.json")
            store.record_command(
                "editor/state",
                port=7890,
                status="error",
                error="bridge unavailable",
                transport="queue",
            )
            ctx = SimpleNamespace(
                obj=SimpleNamespace(
                    backend=SimpleNamespace(session_store=store),
                )
            )
            message = _format_cli_exception_message(ctx, RuntimeError("totally different failure"))
            self.assertEqual(message, "totally different failure")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_cli_exception_message_appends_route_hint_for_recovery_timeout(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            store = SessionStore(tmpdir / "session.json")
            store.record_command(
                "editor/state",
                port=7890,
                status="error",
                error="old port is unavailable",
                transport="queue",
            )
            ctx = SimpleNamespace(
                obj=SimpleNamespace(
                    backend=SimpleNamespace(session_store=store),
                )
            )
            message = _format_cli_exception_message(
                ctx,
                BackendSelectionError(
                    "Timed out recovering route editor/state for project C:/Projects/Demo "
                    "after 0.02s. Last error: old port is unavailable"
                ),
            )
            self.assertIn("Timed out recovering route editor/state", message)
            self.assertIn("Try: cli-anything-unity-mcp --json debug doctor --port 7890", message)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_expert_audit_marks_ui_lens_live_context_unavailable_for_project_only(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text(
                "public class Player {}",
                encoding="utf-8",
            )

            payload = run_cli_json(
                ["workflow", "expert-audit", "--lens", "ui", str(project)],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
            )

            self.assertTrue(payload["available"])
            self.assertTrue(payload["lens"]["requiresLiveUnity"])
            self.assertFalse(payload["lens"]["contextAvailable"])
            self.assertIsNone(payload["score"])
            self.assertIn(
                "Live scene context unavailable",
                {item["title"] for item in payload["findings"]},
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
