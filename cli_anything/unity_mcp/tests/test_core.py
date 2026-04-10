from __future__ import annotations

import json
import os
import shutil
import unittest
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.request import Request, urlopen

from cli_anything.unity_mcp.core.agent_profiles import AgentProfileStore, derive_agent_profiles_path
from cli_anything.unity_mcp.core.debug_dashboard import DashboardConfig, serve_debug_dashboard
from cli_anything.unity_mcp.core.debug_doctor import build_debug_doctor_report
from cli_anything.unity_mcp.core.embedded_cli import EmbeddedCLIOptions, run_cli_json
from cli_anything.unity_mcp.core.mcp_tools import get_mcp_tool, iter_mcp_tools
from cli_anything.unity_mcp.core.project_insights import build_project_insights
from cli_anything.unity_mcp.core.client import UnityMCPClientError, UnityMCPConnectionError, UnityMCPHTTPError
from cli_anything.unity_mcp.core.memory import ProjectMemory
from cli_anything.unity_mcp.core.routes import route_to_tool_name, tool_name_to_route
from cli_anything.unity_mcp.core.session import SessionState, SessionStore
from cli_anything.unity_mcp.core.tool_coverage import build_tool_coverage_matrix
from cli_anything.unity_mcp.core.workflows import build_behaviour_script
from cli_anything.unity_mcp.unity_mcp_cli import _humanize_history_entry, _summarize_trace_entries
from scripts.run_live_mcp_pass import (
    _build_profile_plan,
    _default_report_file,
    _format_live_pass_summary,
    _summarize_live_pass_report,
)
from cli_anything.unity_mcp.core.file_ipc import (
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
            "unity_agents_list",
            "unity_advanced_tool",
            "unity_console_log",
            "unity_list_advanced_tools",
            "unity_list_instances",
            "unity_select_instance",
        ):
            self.assertEqual(all_tools[name]["coverageStatus"], "covered", name)
            self.assertEqual(all_tools[name]["coverageBlocker"], "verified-automated", name)

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
            "unity_animation_add_parameter",
            "unity_animation_add_transition",
            "unity_animation_clip_info",
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
        self.assertTrue(any(item["title"] == "Queue Activity Detected" for item in report["findings"]))
        self.assertIn("cli-anything-unity-mcp --json play stop --port 7892", report["recommendedCommands"])

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
            for index in range(10):
                (project / "Assets" / "Art" / "Textures" / f"HeroAlbedo_{index}.png").write_text("png", encoding="utf-8")
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
            self.assertEqual(insights["assetScan"]["counts"]["textures"], 10)
            self.assertEqual(insights["assetScan"]["counts"]["materials"], 0)
            self.assertEqual(insights["assetScan"]["packageCount"], 1)
            titles = {item["title"] for item in insights["recommendations"]}
            self.assertIn("Build A Material Library", titles)
            self.assertIn("Prefabize Imported Models", titles)
            self.assertIn("Audit Rig And Animation Pipeline", titles)
            self.assertIn("Save Or Snapshot The Active Scene", titles)
            self.assertNotIn("Add Agent Guidance", titles)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
