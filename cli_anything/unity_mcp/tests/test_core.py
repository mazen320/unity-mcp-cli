from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from cli_anything.unity_mcp.core.agent_profiles import AgentProfileStore, derive_agent_profiles_path
from cli_anything.unity_mcp.core.embedded_cli import EmbeddedCLIOptions, run_cli_json
from cli_anything.unity_mcp.core.mcp_tools import get_mcp_tool, iter_mcp_tools
from cli_anything.unity_mcp.core.client import UnityMCPClientError, UnityMCPConnectionError
from cli_anything.unity_mcp.core.routes import route_to_tool_name, tool_name_to_route
from cli_anything.unity_mcp.core.session import SessionStore
from cli_anything.unity_mcp.core.tool_coverage import build_tool_coverage_matrix
from cli_anything.unity_mcp.core.workflows import build_demo_fps_controller_script
from scripts.run_live_mcp_pass import _build_profile_plan, _default_report_file
from cli_anything.unity_mcp.utils.unity_mcp_backend import (
    BackendSelectionError,
    UnityMCPBackend,
)


class FakeClient:
    def __init__(self, pings: dict[int, dict]) -> None:
        self.pings = pings

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
        self.assertFalse(terrain_plan["includeFpsSample"])

        ui_heavy_plan = _build_profile_plan("ui", include_heavy=True)
        self.assertEqual(ui_heavy_plan["advancedCategory"], "ui")
        self.assertTrue(ui_heavy_plan["includeFpsSample"])

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

        self.assertIn("unity_build_fps_sample", names)
        self.assertIn("unity_tool_call", names)
        self.assertIn("unity_validate_scene", names)

        fps_tool = get_mcp_tool("unity_build_fps_sample")
        self.assertIsNotNone(fps_tool)
        self.assertEqual(
            fps_tool.input_schema["properties"]["verifyLevel"]["default"],
            "quick",
        )

    def test_fps_controller_script_prefers_input_system_when_available(self) -> None:
        script = build_demo_fps_controller_script("SampleFpsController")

        self.assertIn("#if ENABLE_INPUT_SYSTEM", script)
        self.assertIn("using UnityEngine.InputSystem;", script)
        self.assertIn("Mouse.current", script)
        self.assertIn("Keyboard.current", script)
        self.assertIn("Gamepad.current", script)
        self.assertIn("public float MouseSensitivity = 0.085f;", script)
        self.assertIn("public bool FireDebugShot()", script)
        self.assertIn("private bool IsFirePressed()", script)
        self.assertIn("DrawCrosshair(", script)
        self.assertIn("WasSensitivityIncreasePressedThisFrame()", script)
        self.assertIn("Input.GetAxisRaw(\"Horizontal\")", script)

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
            store.record_command("project/info", {}, 7890)

            state = store.load()
            self.assertEqual(len(state.history), 2)
            self.assertEqual(state.history[0]["command"], "console/log")
            self.assertEqual(state.history[1]["command"], "project/info")
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
