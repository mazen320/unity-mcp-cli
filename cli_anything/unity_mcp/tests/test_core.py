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

from click.testing import CliRunner

from cli_anything.unity_mcp.core.agent_profiles import AgentProfileStore, derive_agent_profiles_path
from cli_anything.unity_mcp.core.agent_chat import ChatBridge, _OfflineUnityAssistant
from cli_anything.unity_mcp.core.developer_profiles import DeveloperProfileStore, derive_developer_profiles_path
from cli_anything.unity_mcp.core.debug_dashboard import DashboardConfig, serve_debug_dashboard
from cli_anything.unity_mcp.core.debug_doctor import build_debug_doctor_report
from cli_anything.unity_mcp.core.embedded_cli import EmbeddedCLIOptions, run_cli_json
from cli_anything.unity_mcp.core.internal_workflows import run_internal_workflow_json
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
from cli_anything.unity_mcp.commands.workflow import workflow_group
from cli_anything.unity_mcp.unity_mcp_cli import _humanize_history_entry, _summarize_trace_entries, cli
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

    def test_embedded_cli_runner_returns_json_payload(self) -> None:
        payload = run_cli_json(["tool-template", "unity_scene_stats"], EmbeddedCLIOptions())

        self.assertEqual(payload["name"], "unity_scene_stats")
        self.assertEqual(payload["route"], "search/scene-stats")
        self.assertIn("template", payload)

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

    # ── File IPC transport tests ─────────────────────────────────────────

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
            self.assertIn("create and script things directly in the editor", bridge._history[-1]["content"])
            self.assertIn("compile errors", bridge._history[-1]["content"])
            self.assertIn("What do you want to build or fix?", bridge._history[-1]["content"])
            self.assertNotIn("benchmark", bridge._history[-1]["content"].lower())
            self.assertNotIn("quality score", bridge._history[-1]["content"].lower())
            self.assertNotIn("audit your project", bridge._history[-1]["content"].lower())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_bridge_help_reply_stays_on_copilot_surface(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            class ClientStub:
                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    return {}

            bridge = ChatBridge(project, ClientStub())  # type: ignore[arg-type]
            bridge._process_message({"id": "msg-1", "role": "user", "content": "help"})

            reply = bridge._history[-1]["content"].lower()
            self.assertIn("build", reply)
            self.assertIn("compile errors", reply)
            self.assertNotIn("benchmark", reply)
            self.assertNotIn("quality score", reply)
            self.assertNotIn("create sandbox scenes", reply)
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

    def test_chat_assistant_improve_project_uses_internal_workflow_when_available(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            class ClientStub:
                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    return {}

            bridge = ChatBridge(project, ClientStub(), embedded_options=object())  # type: ignore[arg-type]
            captured_calls: list[tuple[str, list[str]]] = []

            def fake_run_internal_workflow(command_name: str, argv: list[str]) -> dict[str, Any]:
                captured_calls.append((command_name, list(argv)))
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

            bridge._assistant._run_internal_workflow = fake_run_internal_workflow  # type: ignore[method-assign]
            bridge._process_message({"id": "msg-1", "role": "user", "content": "improve project"})

            reply = bridge._history[-1]["content"]
            self.assertEqual(
                captured_calls,
                [("improve-project", [str(project)])],
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
            self.assertIn("llmAvailable", payload)
            self.assertIn("llmProvider", payload)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_workflow_group_hides_retired_product_commands_after_reset(self) -> None:
        hidden_commands = {
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
        for command_name in hidden_commands:
            self.assertIn(command_name, workflow_group.commands)
            self.assertTrue(workflow_group.commands[command_name].hidden)
        self.assertFalse(workflow_group.commands["agent-chat"].hidden)
        self.assertFalse(workflow_group.commands["agent-loop"].hidden)

    def test_cli_no_longer_exposes_developer_profile_surface_after_reset(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("developer", cli.commands)
        self.assertNotIn("--developer-profile", result.output)
        self.assertNotIn("--developer-profiles-path", result.output)

    def test_agent_window_no_longer_contains_improve_project_report_card_methods(self) -> None:
        window_path = Path(__file__).resolve().parents[3] / "unity-scripts" / "Editor" / "CliAnythingWindow.cs"
        source = window_path.read_text(encoding="utf-8")

        self.assertNotIn("TryGetLatestImproveProjectMessage", source)
        self.assertNotIn("DrawImproveProjectSummary", source)
        self.assertNotIn("ExportImproveProjectMarkdown", source)
        self.assertNotIn("Latest Improve Project", source)

    def test_chat_bridge_status_reports_llm_provider(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            class ClientStub:
                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    return {}

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
                bridge = ChatBridge(project, ClientStub())  # type: ignore[arg-type]
                bridge.write_status("idle", 0, 0, "")

            status_path = project / ".umcp" / "agent-status.json"
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["llmAvailable"])
            self.assertEqual(payload["llmProvider"], "OpenAI")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_bridge_status_reports_selected_model_from_agent_config(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            (project / ".umcp").mkdir(parents=True, exist_ok=True)
            (project / ".umcp" / "agent-config.json").write_text(
                json.dumps({"preferredProvider": "openai", "preferredModel": "gpt-5-codex"}),
                encoding="utf-8",
            )

            class ClientStub:
                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    return {}

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
                bridge = ChatBridge(project, ClientStub())  # type: ignore[arg-type]
                bridge.write_status("idle", 0, 0, "")

            status_path = project / ".umcp" / "agent-status.json"
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["llmProvider"], "OpenAI")
            self.assertEqual(payload["llmModel"], "gpt-5-codex")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_bridge_loads_openai_key_from_project_env_file(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            (project / ".umcp").mkdir(parents=True, exist_ok=True)
            (project / ".umcp" / "agent.env").write_text(
                "# local bridge secrets\nOPENAI_API_KEY=project-secret\n",
                encoding="utf-8",
            )

            class ClientStub:
                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    return {}

            with patch.dict(os.environ, {}, clear=True):
                bridge = ChatBridge(project, ClientStub())  # type: ignore[arg-type]
                bridge.write_status("idle", 0, 0, "")
                self.assertEqual(os.environ.get("OPENAI_API_KEY"), "project-secret")

            status_path = project / ".umcp" / "agent-status.json"
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["llmAvailable"])
            self.assertEqual(payload["llmProvider"], "OpenAI")
            self.assertEqual(payload["llmConfigSource"], ".umcp/agent.env")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_chat_bridge_does_not_override_process_env_with_project_env_file(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        project.mkdir(parents=True, exist_ok=True)
        try:
            (project / ".umcp").mkdir(parents=True, exist_ok=True)
            (project / ".umcp" / "agent.env").write_text(
                "OPENAI_API_KEY=project-secret\n",
                encoding="utf-8",
            )

            class ClientStub:
                def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                    return {}

            with patch.dict(os.environ, {"OPENAI_API_KEY": "process-secret"}, clear=True):
                bridge = ChatBridge(project, ClientStub())  # type: ignore[arg-type]
                bridge.write_status("idle", 0, 0, "")
                self.assertEqual(os.environ.get("OPENAI_API_KEY"), "process-secret")

            status_path = project / ".umcp" / "agent-status.json"
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["llmConfigSource"], "environment")
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

    def test_internal_workflow_runner_can_apply_quality_fix_for_guidance(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "DemoProject"
        try:
            (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
            (project / "Assets" / "Scripts" / "Player.cs").write_text(
                "public class Player {}",
                encoding="utf-8",
            )

            payload = run_internal_workflow_json(
                "quality-fix",
                [
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
                project_path=project,
            )

            self.assertTrue(payload["available"])
            self.assertTrue(payload["applyResult"]["applied"])
            self.assertEqual(payload["applyResult"]["mode"], "workflow")
            self.assertEqual(payload["applyResult"]["result"]["writeResult"]["writeCount"], 2)
            self.assertTrue((project / "AGENTS.md").exists())
            self.assertTrue((project / "Assets" / "MCP" / "Context" / "ProjectSummary.md").exists())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_internal_workflow_runner_can_run_improve_project_offline_safe_pass(self) -> None:
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

            payload = run_internal_workflow_json(
                "improve-project",
                [
                    "--markdown-file",
                    str(report_path),
                    str(project),
                ],
                EmbeddedCLIOptions(
                    session_path=tmpdir / "session.json",
                    registry_path=tmpdir / "instances.json",
                ),
                project_path=project,
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
            self.assertEqual(payload["markdownFile"], str(report_path))
            self.assertTrue(report_path.exists())
            markdown = report_path.read_text(encoding="utf-8")
            self.assertIn("## Improve Project", markdown)
            self.assertIn("Quality score", markdown)
            self.assertIn("### Applied fixes", markdown)
            self.assertIn("### Skipped fixes", markdown)
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
