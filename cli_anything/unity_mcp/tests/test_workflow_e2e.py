"""E2E tests for workflow commands using the mock bridge."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import unittest
import uuid
from pathlib import Path

from click.testing import CliRunner

from .mock_bridge import MockBridgeServer, MockBridgeHandler, get_cli_command, get_mcp_command, PNG_1X1_BASE64


class WorkflowE2ETests(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = MockBridgeServer(("127.0.0.1", 0))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]
        cls.cli_command = get_cli_command()
        cls.mcp_command = get_mcp_command()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self) -> None:
        self.server.reset_state()
        self.tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.tmpdir / "instances.json"
        self.session_path = self.tmpdir / "session.json"
        self.registry_path.write_text(
            json.dumps(
                [
                    {
                        "port": self.port,
                        "projectName": "Demo",
                        "projectPath": "C:/Projects/Demo",
                    }
                ]
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def run_cli(
        self,
        *args: str,
        input_text: str | None = None,
        timeout: float = 20,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            *self.cli_command,
            "--host",
            "127.0.0.1",
            "--default-port",
            str(self.port),
            "--port-range-start",
            str(self.port),
            "--port-range-end",
            str(self.port),
            "--registry-path",
            str(self.registry_path),
            "--session-path",
            str(self.session_path),
            *args,
        ]
        env = os.environ.copy()
        env["CLI_ANYTHING_UNITY_MCP_MEMORY_DIR"] = str(self.tmpdir / "memory")
        result = subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        if result.returncode != 0:
            self.fail(f"CLI failed.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        return result

    def start_mcp_server(self) -> subprocess.Popen[str]:
        command = [
            *self.mcp_command,
            "--host",
            "127.0.0.1",
            "--default-port",
            str(self.port),
            "--port-range-start",
            str(self.port),
            "--port-range-end",
            str(self.port),
            "--registry-path",
            str(self.registry_path),
            "--session-path",
            str(self.session_path),
        ]
        env = os.environ.copy()
        env["CLI_ANYTHING_UNITY_MCP_MEMORY_DIR"] = str(self.tmpdir / "memory")
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
        )
        self.addCleanup(self.stop_mcp_server, process)

        initialize = self.call_mcp(
            process,
            1,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "unittest", "version": "1.0"},
            },
        )
        self.assertIn("tools", initialize["capabilities"])
        self.send_mcp_notification(process, "notifications/initialized", {})
        return process

    def stop_mcp_server(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive cleanup
                process.kill()
        if process.stderr:
            process.stderr.close()
        if process.stdout:
            process.stdout.close()
        if process.stdin:
            process.stdin.close()

    def send_mcp_notification(self, process: subprocess.Popen[str], method: str, params: dict | None = None) -> None:
        self.assertIsNotNone(process.stdin)
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()

    def call_mcp(
        self,
        process: subprocess.Popen[str],
        request_id: int,
        method: str,
        params: dict | None = None,
    ) -> dict:
        self.assertIsNotNone(process.stdin)
        self.assertIsNotNone(process.stdout)
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        if not line:
            stderr = process.stderr.read() if process.stderr else ""
            self.fail(f"MCP server did not respond.\nSTDERR:\n{stderr}")
        response = json.loads(line)
        if "error" in response:
            self.fail(f"MCP call failed: {response['error']}")
        return response["result"]

    def test_workflow_inspect_returns_combined_snapshot(self) -> None:
        self.server.scripts["Assets/Scripts/Existing.cs"] = "public class Existing {}"

        result = self.run_cli("--json", "workflow", "inspect", "--asset-limit", "5")
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["summary"]["projectName"], "Demo")
        self.assertEqual(payload["summary"]["activeScene"], "MainScene")
        self.assertIn("editorState", payload)
        self.assertEqual(payload["assets"]["count"], 1)
        self.assertEqual(payload["assets"]["sampled"][0]["path"], "Assets/Scripts/Existing.cs")

    def test_workflow_create_behaviour_creates_script_and_attaches_component(self) -> None:
        result = self.run_cli("--json", "workflow", "create-behaviour", "ProbeBehaviour")
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["className"], "ProbeBehaviour")
        self.assertEqual(payload["scriptPath"], "Assets/Scripts/Codex/ProbeBehaviour.cs")
        self.assertTrue(payload["script"]["success"])
        self.assertTrue(payload["component"]["success"])
        self.assertEqual(payload["properties"]["component"], "ProbeBehaviour")
        self.assertTrue(payload["editorState"]["sceneDirty"])

    def test_workflow_audit_advanced_reports_probe_results_and_cleans_up(self) -> None:
        from cli_anything.unity_mcp.unity_mcp_cli import cli as unity_cli

        runner = CliRunner()
        env = os.environ.copy()
        env["CLI_ANYTHING_UNITY_MCP_MEMORY_DIR"] = str(self.tmpdir / "memory")
        result = runner.invoke(
            unity_cli,
            [
                "--host",
                "127.0.0.1",
                "--default-port",
                str(self.port),
                "--port-range-start",
                str(self.port),
                "--port-range-end",
                str(self.port),
                "--registry-path",
                str(self.registry_path),
                "--session-path",
                str(self.session_path),
                "--json",
                "workflow",
                "audit-advanced",
                "--timeout",
                "5",
                "--interval",
                "0.1",
            ],
            env=env,
            catch_exceptions=False,
        )
        if result.exit_code != 0:
            self.fail(f"CLI failed.\nOUTPUT:\n{result.output}")
        payload = json.loads(result.output.strip())

        self.assertGreaterEqual(payload["summary"]["totalProbes"], 18)
        self.assertEqual(payload["summary"]["failed"], 0)
        self.assertTrue(payload["cleanup"]["sceneReset"]["success"])
        self.assertFalse(payload["after"]["editorState"]["sceneDirty"])
        self.assertTrue(any(probe["tool"] == "unity_memory_status" for probe in payload["probes"]))
        self.assertTrue(any(probe["tool"] == "unity_graphics_renderer_info" for probe in payload["probes"]))
        self.assertTrue(any(probe["tool"] == "unity_physics_raycast" for probe in payload["probes"]))
        self.assertTrue(any(probe["tool"] == "unity_ui_create_canvas" for probe in payload["probes"]))
        self.assertTrue(any(probe["tool"] == "unity_audio_info" for probe in payload["probes"]))
        self.assertTrue(any(probe["tool"] == "unity_animation_create_controller" for probe in payload["probes"]))
        self.assertTrue(any(probe["tool"] == "unity_shadergraph_create" for probe in payload["probes"]))
        self.assertTrue(any(probe["tool"] == "unity_terrain_create" for probe in payload["probes"]))
        self.assertTrue(any(probe["tool"] == "unity_navmesh_info" for probe in payload["probes"]))

    def test_workflow_wire_reference_sets_scene_object_reference(self) -> None:
        self.run_cli("--json", "workflow", "create-behaviour", "ReferenceHolder", "--object-name", "Holder")
        self.run_cli(
            "--json",
            "tool",
            "unity_gameobject_create",
            "--param",
            "name=Target",
            "--param",
            "primitiveType=Empty",
        )

        result = self.run_cli(
            "--json",
            "workflow",
            "wire-reference",
            "Holder",
            "ReferenceHolder",
            "TargetRef",
            "--reference-object",
            "Target",
        )
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["result"]["success"])
        self.assertEqual(payload["result"]["referenceName"], "Target")
        self.assertEqual(
            self.server.gameobjects["Holder"]["component_data"]["ReferenceHolder"]["TargetRef"]["name"],
            "Target",
        )

    def test_workflow_create_prefab_saves_and_instantiates(self) -> None:
        self.run_cli(
            "--json",
            "tool",
            "unity_gameobject_create",
            "--param",
            "name=EnemyRoot",
            "--param",
            "primitiveType=Empty",
        )

        result = self.run_cli(
            "--json",
            "workflow",
            "create-prefab",
            "EnemyRoot",
            "--instantiate",
            "--instance-name",
            "EnemyClone",
        )
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["prefab"]["success"])
        self.assertEqual(payload["savePath"], "Assets/Prefabs/EnemyRoot.prefab")
        self.assertEqual(payload["instance"]["name"], "EnemyClone")

    def test_workflow_create_sandbox_scene_restores_original_scene_by_default(self) -> None:
        result = self.run_cli("--json", "workflow", "create-sandbox-scene")
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["success"])
        self.assertEqual(payload["sceneName"], "Demo_Sandbox")
        self.assertEqual(payload["path"], "Assets/Scenes/Demo_Sandbox.unity")
        self.assertTrue(payload["reopenedOriginal"])
        self.assertFalse(payload["keptOpen"])
        self.assertEqual(payload["editorState"]["activeScene"], "MainScene")
        self.assertIn("Assets/Scenes/Demo_Sandbox.unity", self.server.scene_assets)
        self.assertEqual(self.server.active_scene_name, "MainScene")

    def test_workflow_create_sandbox_scene_can_leave_sandbox_open_in_custom_folder(self) -> None:
        result = self.run_cli(
            "--json",
            "workflow",
            "create-sandbox-scene",
            "--name",
            "GameplayLab",
            "--folder",
            "Assets/Scenes/Sandboxes",
            "--open",
        )
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["success"])
        self.assertEqual(payload["sceneName"], "GameplayLab")
        self.assertEqual(payload["path"], "Assets/Scenes/Sandboxes/GameplayLab.unity")
        self.assertFalse(payload["reopenedOriginal"])
        self.assertTrue(payload["keptOpen"])
        self.assertEqual(payload["editorState"]["activeScene"], "GameplayLab")
        self.assertEqual(self.server.active_scene_name, "GameplayLab")
        self.assertIn("Assets/Scenes/Sandboxes/GameplayLab.unity", self.server.scene_assets)

    def test_workflow_quality_fix_apply_runs_sandbox_fix(self) -> None:
        result = self.run_cli(
            "--json",
            "workflow",
            "quality-fix",
            "--lens",
            "director",
            "--fix",
            "sandbox-scene",
            "--apply",
        )
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["available"])
        self.assertTrue(payload["applyResult"]["applied"])
        self.assertEqual(payload["applyResult"]["mode"], "workflow")
        self.assertEqual(payload["applyResult"]["result"]["sceneName"], "Demo_Sandbox")
        self.assertTrue(payload["applyResult"]["result"]["reopenedOriginal"])
        self.assertIn("Assets/Scenes/Demo_Sandbox.unity", self.server.scene_assets)
        self.assertEqual(self.server.active_scene_name, "MainScene")

    def test_workflow_quality_fix_apply_adds_canvas_scaler(self) -> None:
        self.server._register_gameobject(
            "HUDCanvas",
            components=["Transform", "RectTransform", "Canvas", "GraphicRaycaster"],
        )

        result = self.run_cli(
            "--json",
            "workflow",
            "quality-fix",
            "--lens",
            "ui",
            "--fix",
            "ui-canvas-scaler",
            "--apply",
        )
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["available"])
        self.assertTrue(payload["applyResult"]["applied"])
        self.assertEqual(payload["applyResult"]["mode"], "workflow")
        self.assertEqual(payload["applyResult"]["result"]["updatedCount"], 1)
        self.assertIn("CanvasScaler", self.server.gameobjects["HUDCanvas"]["components"])

    def test_workflow_quality_fix_apply_adds_graphic_raycaster(self) -> None:
        self.server._register_gameobject(
            "HUDCanvas",
            components=["Transform", "RectTransform", "Canvas", "CanvasScaler"],
        )

        result = self.run_cli(
            "--json",
            "workflow",
            "quality-fix",
            "--lens",
            "ui",
            "--fix",
            "ui-graphic-raycaster",
            "--apply",
        )
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["available"])
        self.assertTrue(payload["applyResult"]["applied"])
        self.assertEqual(payload["applyResult"]["mode"], "workflow")
        self.assertEqual(payload["applyResult"]["result"]["updatedCount"], 1)
        self.assertIn("GraphicRaycaster", self.server.gameobjects["HUDCanvas"]["components"])

    def test_workflow_quality_fix_apply_adds_event_system(self) -> None:
        self.server._register_gameobject(
            "HUDCanvas",
            components=["Transform", "RectTransform", "Canvas", "CanvasScaler", "GraphicRaycaster"],
        )

        result = self.run_cli(
            "--json",
            "workflow",
            "quality-fix",
            "--lens",
            "systems",
            "--fix",
            "event-system",
            "--apply",
        )
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["available"])
        self.assertTrue(payload["applyResult"]["applied"])
        self.assertEqual(payload["applyResult"]["mode"], "workflow")
        self.assertEqual(payload["applyResult"]["result"]["updatedCount"], 1)
        self.assertEqual(payload["applyResult"]["result"]["moduleType"], "StandaloneInputModule")
        self.assertIn("EventSystem", self.server.gameobjects)
        self.assertIn("EventSystem", self.server.gameobjects["EventSystem"]["components"])
        self.assertIn("StandaloneInputModule", self.server.gameobjects["EventSystem"]["components"])

    def test_workflow_quality_fix_apply_repairs_existing_event_system_module(self) -> None:
        self.server._register_gameobject(
            "HUDCanvas",
            components=["Transform", "RectTransform", "Canvas", "CanvasScaler", "GraphicRaycaster"],
        )
        self.server._register_gameobject(
            "EventSystem",
            components=["Transform", "EventSystem"],
        )

        result = self.run_cli(
            "--json",
            "workflow",
            "quality-fix",
            "--lens",
            "systems",
            "--fix",
            "event-system",
            "--apply",
        )
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["available"])
        self.assertTrue(payload["applyResult"]["applied"])
        self.assertEqual(payload["applyResult"]["mode"], "workflow")
        self.assertEqual(payload["applyResult"]["result"]["updatedCount"], 1)
        self.assertEqual(payload["applyResult"]["result"]["moduleType"], "StandaloneInputModule")
        self.assertIn("StandaloneInputModule", self.server.gameobjects["EventSystem"]["components"])

    def test_workflow_quality_fix_apply_dedupes_extra_event_system_components(self) -> None:
        self.server._register_gameobject(
            "HUDCanvas",
            components=["Transform", "RectTransform", "Canvas", "CanvasScaler", "GraphicRaycaster"],
        )
        self.server._register_gameobject(
            "EventSystem",
            components=["Transform", "EventSystem", "StandaloneInputModule"],
        )
        self.server._register_gameobject(
            "UIRoot/DuplicateEventSystem",
            components=["Transform", "EventSystem", "StandaloneInputModule"],
        )

        result = self.run_cli(
            "--json",
            "workflow",
            "quality-fix",
            "--lens",
            "systems",
            "--fix",
            "event-system",
            "--apply",
        )
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["available"])
        self.assertTrue(payload["applyResult"]["applied"])
        self.assertEqual(payload["applyResult"]["mode"], "workflow")
        self.assertEqual(payload["applyResult"]["result"]["updatedCount"], 1)
        self.assertEqual(payload["applyResult"]["result"]["duplicateRemovedCount"], 1)
        self.assertNotIn("EventSystem", self.server.gameobjects["UIRoot/DuplicateEventSystem"]["components"])
        self.assertNotIn(
            "StandaloneInputModule",
            self.server.gameobjects["UIRoot/DuplicateEventSystem"]["components"],
        )

    def test_workflow_quality_fix_apply_normalizes_primary_event_system_module(self) -> None:
        self.server._register_gameobject(
            "HUDCanvas",
            components=["Transform", "RectTransform", "Canvas", "CanvasScaler", "GraphicRaycaster"],
        )
        self.server._register_gameobject(
            "EventSystem",
            components=["Transform", "EventSystem", "StandaloneInputModule", "InputSystemUIInputModule"],
        )

        result = self.run_cli(
            "--json",
            "workflow",
            "quality-fix",
            "--lens",
            "systems",
            "--fix",
            "event-system",
            "--apply",
        )
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["available"])
        self.assertTrue(payload["applyResult"]["applied"])
        self.assertEqual(payload["applyResult"]["mode"], "workflow")
        self.assertEqual(payload["applyResult"]["result"]["updatedCount"], 1)
        self.assertEqual(payload["applyResult"]["result"]["moduleType"], "StandaloneInputModule")
        self.assertIn("StandaloneInputModule", self.server.gameobjects["EventSystem"]["components"])
        self.assertNotIn("InputSystemUIInputModule", self.server.gameobjects["EventSystem"]["components"])

    def test_workflow_quality_fix_apply_repairs_audio_listener_setup(self) -> None:
        self.server._register_gameobject(
            "Main Camera",
            components=["Transform", "Camera", "AudioListener"],
        )
        self.server._register_gameobject(
            "UICamera",
            components=["Transform", "Camera", "AudioListener"],
        )

        result = self.run_cli(
            "--json",
            "workflow",
            "quality-fix",
            "--lens",
            "systems",
            "--fix",
            "audio-listener",
            "--apply",
        )
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["available"])
        self.assertTrue(payload["applyResult"]["applied"])
        self.assertEqual(payload["applyResult"]["mode"], "workflow")
        self.assertEqual(payload["applyResult"]["result"]["updatedCount"], 1)
        self.assertIn("AudioListener", self.server.gameobjects["Main Camera"]["components"])
        self.assertNotIn("AudioListener", self.server.gameobjects["UICamera"]["components"])

    def test_workflow_quality_fix_apply_cleans_disposable_probe_objects(self) -> None:
        self.server._register_gameobject(
            "Main Camera",
            components=["Transform", "Camera", "AudioListener"],
        )
        self.server._register_gameobject(
            "StandaloneProbe",
            components=["Transform"],
        )
        self.server._register_gameobject(
            "DebugFixture",
            components=["Transform"],
        )

        result = self.run_cli(
            "--json",
            "workflow",
            "quality-fix",
            "--lens",
            "systems",
            "--fix",
            "disposable-cleanup",
            "--apply",
        )
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["available"])
        self.assertTrue(payload["applyResult"]["applied"])
        self.assertEqual(payload["applyResult"]["mode"], "workflow")
        self.assertEqual(payload["applyResult"]["result"]["updatedCount"], 2)
        self.assertEqual(payload["applyResult"]["result"]["removedCount"], 2)
        self.assertIn("StandaloneProbe", payload["applyResult"]["result"]["removedPaths"])
        self.assertIn("DebugFixture", payload["applyResult"]["result"]["removedPaths"])
        self.assertNotIn("StandaloneProbe", self.server.gameobjects)
        self.assertNotIn("DebugFixture", self.server.gameobjects)

    def test_workflow_quality_fix_apply_adds_character_controller_to_likely_player(self) -> None:
        self.server._register_gameobject(
            "Main Camera",
            components=["Transform", "Camera", "AudioListener"],
        )
        self.server._register_gameobject(
            "PlayerAvatar",
            components=["Transform", "CapsuleCollider"],
        )

        result = self.run_cli(
            "--json",
            "workflow",
            "quality-fix",
            "--lens",
            "physics",
            "--fix",
            "player-character-controller",
            "--apply",
        )
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["available"])
        self.assertTrue(payload["applyResult"]["applied"])
        self.assertEqual(payload["applyResult"]["mode"], "workflow")
        self.assertEqual(payload["applyResult"]["result"]["updatedCount"], 1)
        self.assertEqual(payload["applyResult"]["result"]["targetPath"], "PlayerAvatar")
        self.assertIn("CharacterController", self.server.gameobjects["PlayerAvatar"]["components"])

    def test_workflow_quality_fix_apply_repairs_texture_importers(self) -> None:
        project = self.tmpdir / "DemoProject"
        textures = project / "Assets" / "Textures"
        ui = project / "Assets" / "UI"
        textures.mkdir(parents=True, exist_ok=True)
        ui.mkdir(parents=True, exist_ok=True)

        normal_path = textures / "rock_normal.png"
        sprite_path = ui / "ability_icon.png"
        normal_path.write_bytes(b"fake-png")
        sprite_path.write_bytes(b"fake-png")
        (project / "Assets" / "Textures" / "rock_normal.png.meta").write_text(
            "\n".join(
                [
                    "fileFormatVersion: 2",
                    "TextureImporter:",
                    "  textureType: 0",
                ]
            ),
            encoding="utf-8",
        )
        (project / "Assets" / "UI" / "ability_icon.png.meta").write_text(
            "\n".join(
                [
                    "fileFormatVersion: 2",
                    "TextureImporter:",
                    "  textureType: 0",
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_cli(
            "--json",
            "workflow",
            "quality-fix",
            "--lens",
            "tech-art",
            "--fix",
            "texture-imports",
            "--apply",
            str(project),
        )
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["available"])
        self.assertTrue(payload["applyResult"]["applied"])
        self.assertEqual(payload["applyResult"]["result"]["updatedCount"], 2)
        self.assertEqual(payload["applyResult"]["result"]["normalMapCount"], 1)
        self.assertEqual(payload["applyResult"]["result"]["spriteCount"], 1)
        self.assertEqual(
            self.server.texture_imports["Assets/Textures/rock_normal.png"]["textureType"],
            "NormalMap",
        )
        self.assertEqual(
            self.server.texture_imports["Assets/UI/ability_icon.png"]["textureType"],
            "Sprite",
        )

    def test_workflow_quality_fix_apply_creates_animation_controller(self) -> None:
        result = self.run_cli(
            "--json",
            "workflow",
            "quality-fix",
            "--lens",
            "animation",
            "--fix",
            "controller-scaffold",
            "--apply",
        )
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["available"])
        self.assertTrue(payload["applyResult"]["applied"])
        self.assertEqual(payload["applyResult"]["mode"], "workflow")
        controller_path = payload["applyResult"]["result"]["path"]
        self.assertTrue(controller_path.endswith("_Auto.controller"))
        self.assertIn(controller_path, self.server.animation_controllers)

    def test_workflow_quality_fix_apply_wires_animation_controller_to_animator(self) -> None:
        self.server._register_gameobject(
            "Hero",
            components=["Transform", "Animator"],
        )

        result = self.run_cli(
            "--json",
            "workflow",
            "quality-fix",
            "--lens",
            "animation",
            "--fix",
            "controller-wireup",
            "--apply",
        )
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["available"])
        self.assertTrue(payload["applyResult"]["applied"])
        self.assertEqual(payload["applyResult"]["mode"], "workflow")
        wireup_result = payload["applyResult"]["result"]
        controller_path = wireup_result["controllerPath"]
        self.assertTrue(controller_path.endswith("_Auto.controller"))
        self.assertTrue(str(wireup_result["targetGameObjectPath"]).endswith("Hero"))
        self.assertIn(controller_path, self.server.animation_controllers)
        self.assertEqual(
            self.server.gameobjects["Hero"]["animatorController"],
            controller_path,
        )

    def test_workflow_quality_fix_apply_writes_test_scaffold_and_improves_director_audit(self) -> None:
        project = self.tmpdir / "DemoProject"
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

        apply_result = self.run_cli(
            "--json",
            "workflow",
            "quality-fix",
            "--lens",
            "director",
            "--fix",
            "test-scaffold",
            "--apply",
            str(project),
        )
        apply_payload = json.loads(apply_result.stdout.strip())

        self.assertTrue(apply_payload["available"])
        self.assertTrue(apply_payload["applyResult"]["applied"])
        self.assertEqual(apply_payload["applyResult"]["result"]["writeCount"], 2)

        audit_result = self.run_cli(
            "--json",
            "workflow",
            "expert-audit",
            "--lens",
            "director",
            str(project),
        )
        audit_payload = json.loads(audit_result.stdout.strip())
        titles = {item["title"] for item in audit_payload["findings"]}

        self.assertNotIn("No test coverage detected", titles)
        self.assertIn("Missing project guidance", titles)

    def test_workflow_improve_project_applies_safe_project_and_scene_repairs(self) -> None:
        project = self.tmpdir / "DemoProject"
        (project / "Assets" / "Scripts").mkdir(parents=True, exist_ok=True)
        (project / "Packages").mkdir(parents=True, exist_ok=True)
        (project / "Assets" / "Scripts" / "Player.cs").write_text(
            "public class Player {}",
            encoding="utf-8",
        )
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
        self.server.project_name = "DemoProject"
        self.server.project_path = str(project).replace("\\", "/")
        self.server._register_gameobject(
            "Main Camera",
            components=["Transform", "Camera"],
        )
        self.server._register_gameobject(
            "HUDCanvas",
            components=["Transform", "RectTransform", "Canvas"],
        )
        self.server._register_gameobject(
            "PlayerAvatar",
            components=["Transform", "CapsuleCollider"],
        )
        self.server._register_gameobject(
            "StandaloneProbe",
            components=["Transform"],
        )

        result = self.run_cli(
            "--json",
            "workflow",
            "improve-project",
            "--port",
            str(self.port),
            str(project),
            timeout=40,
        )
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["available"])
        self.assertTrue(payload["liveUnityAvailable"])
        self.assertGreater(payload["appliedCount"], 0)
        self.assertEqual(payload["skippedCount"], 0)
        self.assertIsNotNone(payload["baselineScore"])
        self.assertIsNotNone(payload["finalScore"])
        self.assertGreater(payload["finalScore"], payload["baselineScore"])
        self.assertTrue(payload["projectChanged"])
        self.assertTrue(payload["sceneChanged"])

        applied_fixes = {item["fix"] for item in payload["applied"]}
        self.assertTrue(
            {
                "guidance",
                "sandbox-scene",
                "disposable-cleanup",
                "audio-listener",
                "event-system",
                "ui-canvas-scaler",
                "ui-graphic-raycaster",
                "player-character-controller",
                "test-scaffold",
            }.issubset(applied_fixes)
        )
        self.assertTrue((project / "AGENTS.md").exists())
        self.assertTrue((project / "Assets" / "MCP" / "Context" / "ProjectSummary.md").exists())
        self.assertTrue((project / "Assets" / "Tests" / "EditMode" / "DemoProjectSmokeTests.cs").exists())
        self.assertIn("Assets/Scenes/DemoProject_Sandbox.unity", self.server.scene_assets)
        self.assertIn("AudioListener", self.server.gameobjects["Main Camera"]["components"])
        self.assertIn("CanvasScaler", self.server.gameobjects["HUDCanvas"]["components"])
        self.assertIn("GraphicRaycaster", self.server.gameobjects["HUDCanvas"]["components"])
        self.assertIn("CharacterController", self.server.gameobjects["PlayerAvatar"]["components"])
        self.assertNotIn("StandaloneProbe", self.server.gameobjects)
        self.assertIn("EventSystem", self.server.gameobjects)
        self.assertIn("InputSystemUIInputModule", self.server.gameobjects["EventSystem"]["components"])

    def test_workflow_expert_audit_systems_reports_live_scene_hygiene_findings(self) -> None:
        self.server._register_gameobject(
            "MainCamera",
            components=["Transform", "Camera", "AudioListener"],
        )
        self.server._register_gameobject(
            "SpectatorCamera",
            components=["Transform", "Camera", "AudioListener"],
        )
        self.server._register_gameobject(
            "HUDCanvas",
            components=["Transform", "RectTransform", "Canvas", "CanvasScaler"],
        )
        self.server._register_gameobject(
            "Player",
            components=["Transform"],
        )
        self.server._register_gameobject(
            "StandalonePrefabProbe",
            components=["Transform"],
        )

        result = self.run_cli(
            "--json",
            "workflow",
            "expert-audit",
            "--lens",
            "systems",
        )
        payload = json.loads(result.stdout.strip())

        self.assertTrue(payload["available"])
        titles = {item["title"] for item in payload["findings"]}
        self.assertIn("Multiple AudioListeners in scene", titles)
        self.assertIn("Canvas present without EventSystem", titles)
        self.assertIn("Disposable probe/demo objects still present", titles)

    def test_workflow_validate_scene_reports_summary(self) -> None:
        self.server.gameobjects["Player"] = {
            "instanceId": 1,
            "components": ["Transform", "PlayerController"],
            "component_data": {"PlayerController": {"Label": "Player", "Count": 1}},
        }
        self.server.missing_references.append(
            {
                "gameObject": "Player",
                "path": "Player",
                "component": "PlayerController",
                "property": "Target",
                "issue": "Missing object reference",
            }
        )

        result = self.run_cli("--json", "workflow", "validate-scene", "--include-hierarchy")
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["summary"]["missingReferenceCount"], 1)
        self.assertEqual(payload["summary"]["totalGameObjects"], 1)
        self.assertIn("stats", payload)
        self.assertIn("hierarchy", payload)
        self.assertEqual(payload["missingRefTracking"]["newIssues"][0]["gameObject"], "Player")
        self.assertEqual(payload["missingRefTracking"]["totalTracked"], 1)

        recurring_result = self.run_cli("--json", "workflow", "validate-scene")
        recurring_payload = json.loads(recurring_result.stdout.strip())
        self.assertEqual(
            recurring_payload["missingRefTracking"]["recurringIssues"][0]["seenCount"],
            2,
        )
        self.assertEqual(recurring_payload["recurringMissingRefs"][0]["gameObject"], "Player")
        recurring_warnings = recurring_payload.get("warnings", [])
        self.assertTrue(
            any("Recurring missing references detected" in warning for warning in recurring_warnings)
        )

        self.server.missing_references.clear()
        resolved_result = self.run_cli("--json", "workflow", "validate-scene")
        resolved_payload = json.loads(resolved_result.stdout.strip())
        self.assertEqual(resolved_payload["missingRefTracking"]["resolvedIssues"][0]["gameObject"], "Player")
        self.assertEqual(resolved_payload["missingRefTracking"]["totalTracked"], 0)

    def test_workflow_inspect_emits_specific_trace_wording(self) -> None:
        self.run_cli(
            "--json",
            "--agent-id",
            "agent-alpha",
            "workflow",
            "inspect",
            "--asset-folder",
            "Assets/Scripts",
            "--asset-limit",
            "7",
            "--hierarchy-depth",
            "3",
            "--hierarchy-nodes",
            "12",
        )

        result = self.run_cli(
            "--json",
            "debug",
            "trace",
            "--tail",
            "10",
            "--agent-id",
            "agent-alpha",
        )
        payload = json.loads(result.stdout.strip())
        entries = [entry for entry in payload["entries"] if entry.get("commandPath") == "workflow inspect"]

        self.assertTrue(entries)
        self.assertTrue(
            any(
                entry.get("activity")
                == "inspecting Unity project (assets from Assets/Scripts; sample 7 assets; hierarchy depth 3, max 12 nodes)"
                for entry in entries
            )
        )

        trace_calls = [code for code in self.server.execute_code_calls if "[CLI-TRACE]" in code]
        self.assertTrue(
            any(
                "[CLI-TRACE] agent-alpha: Inspecting Unity project (assets from Assets/Scripts; sample 7 assets; hierarchy depth 3, max 12 nodes)"
                in code
                for code in trace_calls
            )
        )
        self.assertTrue(
            any(
                "[CLI-TRACE] agent-alpha: Checking project info" in code
                or "[CLI-TRACE] agent-alpha: Checking editor state" in code
                or "[CLI-TRACE] agent-alpha: Listing assets in Assets/Scripts" in code
                for code in trace_calls
            )
        )

        progress_entries = [entry for entry in payload["entries"] if entry.get("command") == "cli/progress"]
        self.assertTrue(progress_entries)
        self.assertTrue(
            any(entry.get("summary") == "Checking project info" for entry in progress_entries)
        )
        self.assertTrue(
            any("Inspecting scene hierarchy (depth 3, max 12 nodes)" == entry.get("summary") for entry in progress_entries)
        )
