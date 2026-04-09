from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from cli_anything.unity_mcp.core.agent_profiles import AgentProfileStore, derive_agent_profiles_path
from cli_anything.unity_mcp.core.debug_doctor import build_debug_doctor_report
from cli_anything.unity_mcp.core.embedded_cli import EmbeddedCLIOptions, run_cli_json
from cli_anything.unity_mcp.core.mcp_tools import get_mcp_tool, iter_mcp_tools
from cli_anything.unity_mcp.core.client import UnityMCPClientError, UnityMCPConnectionError
from cli_anything.unity_mcp.core.routes import route_to_tool_name, tool_name_to_route
from cli_anything.unity_mcp.core.session import SessionState, SessionStore
from cli_anything.unity_mcp.core.tool_coverage import build_tool_coverage_matrix
from cli_anything.unity_mcp.core.workflows import build_behaviour_script
from cli_anything.unity_mcp.unity_mcp_cli import _humanize_history_entry
from scripts.run_live_mcp_pass import _build_profile_plan, _default_report_file
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


class CoreTests(unittest.TestCase):
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
        self.assertEqual(tools["unity_terrain_create_grid"]["coverageStatus"], "deferred")
        self.assertEqual(tools["unity_terrain_create_grid"]["coverageBlocker"], "stateful-live-audit")
        self.assertIn("disposable fixtures", tools["unity_terrain_create_grid"]["coverageNote"])
        self.assertGreaterEqual(payload["summary"]["countsByStatus"]["live-tested"], 1)

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
