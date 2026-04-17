"""Tests verifying mock-only route coverage against MockBridgeHandler."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import unittest
import uuid
from pathlib import Path

from .mock_bridge import MockBridgeServer, MockBridgeHandler, get_cli_command, get_mcp_command, PNG_1X1_BASE64


class MockRouteTests(unittest.TestCase):

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

    def test_mock_only_advanced_routes_work_against_mock_bridge(self) -> None:
        def call_tool(tool_name: str, params: dict | None = None) -> dict:
            args = ["--json", "tool", tool_name]
            if params is not None:
                args.extend(["--params", json.dumps(params)])
            result = self.run_cli(*args)
            return json.loads(result.stdout.strip())

        canvas = call_tool("unity_ui_create_canvas", {"name": "MockCanvas", "renderMode": "overlay"})
        self.assertEqual(canvas["name"], "MockCanvas")
        text_element = call_tool(
            "unity_ui_create_element",
            {"type": "text", "name": "MockLabel", "parent": "MockCanvas"},
        )
        image_element = call_tool(
            "unity_ui_create_element",
            {"type": "image", "name": "MockImage", "parent": "MockCanvas"},
        )
        updated_text = call_tool(
            "unity_ui_set_text",
            {"path": "MockCanvas/MockLabel", "text": "Mock coverage", "fontSize": 24},
        )
        updated_image = call_tool(
            "unity_ui_set_image",
            {"path": "MockCanvas/MockImage", "color": {"r": 0.2, "g": 0.5, "b": 0.9, "a": 1.0}},
        )
        self.assertEqual(text_element["type"], "text")
        self.assertEqual(image_element["type"], "image")
        self.assertEqual(updated_text["text"], "Mock coverage")
        self.assertEqual(updated_image["image"]["color"]["b"], 0.9)

        environment = call_tool(
            "unity_lighting_set_environment",
            {"ambientMode": "Flat", "ambientIntensity": 0.75, "fogEnabled": True},
        )
        light_probe_group = call_tool("unity_lighting_create_light_probe_group", {"name": "MockLightProbes"})
        reflection_probe = call_tool(
            "unity_lighting_create_reflection_probe",
            {"name": "MockReflection", "resolution": 128, "mode": "Realtime"},
        )
        self.assertEqual(environment["environment"]["ambientMode"], "Flat")
        self.assertEqual(light_probe_group["probeCount"], 4)
        self.assertEqual(reflection_probe["mode"], "Realtime")

        clip_path = "Assets/MockOnly/MockClip.anim"
        controller_path = "Assets/MockOnly/Mock.controller"
        clip = call_tool("unity_animation_create_clip", {"path": clip_path, "loop": True, "frameRate": 30})
        controller = call_tool("unity_animation_create_controller", {"path": controller_path})
        curve = call_tool(
            "unity_animation_set_clip_curve",
            {
                "clipPath": clip_path,
                "propertyName": "localPosition.x",
                "type": "Transform",
                "keyframes": [{"time": 0, "value": 0}, {"time": 1, "value": 2}],
            },
        )
        event = call_tool(
            "unity_animation_add_event",
            {"clipPath": clip_path, "functionName": "OnMockEvent", "time": 0.5},
        )
        events = call_tool("unity_animation_get_events", {"clipPath": clip_path})
        keyframes = call_tool(
            "unity_animation_get_curve_keyframes",
            {"clipPath": clip_path, "propertyName": "localPosition.x", "typeName": "Transform"},
        )
        clip_info = call_tool("unity_animation_clip_info", {"path": clip_path})
        parameter = call_tool(
            "unity_animation_add_parameter",
            {"controllerPath": controller_path, "parameterName": "Speed", "parameterType": "Float"},
        )
        state = call_tool(
            "unity_animation_add_state",
            {
                "controllerPath": controller_path,
                "stateName": "Idle",
                "clipPath": clip_path,
                "speed": 1.0,
                "isDefault": True,
            },
        )
        run_state = call_tool(
            "unity_animation_add_state",
            {
                "controllerPath": controller_path,
                "stateName": "Run",
                "clipPath": clip_path,
                "speed": 1.25,
                "isDefault": False,
            },
        )
        transition = call_tool(
            "unity_animation_add_transition",
            {
                "controllerPath": controller_path,
                "sourceState": "Idle",
                "destinationState": "Run",
                "duration": 0.2,
            },
        )
        controller_info = call_tool("unity_animation_controller_info", {"path": controller_path})
        set_default = call_tool(
            "unity_animation_set_default_state",
            {
                "controllerPath": controller_path,
                "stateName": "Run",
            },
        )
        controller_info_after = call_tool("unity_animation_controller_info", {"path": controller_path})
        self.assertEqual(clip["path"], clip_path)
        self.assertEqual(controller["path"], controller_path)
        self.assertEqual(curve["propertyName"], "localPosition.x")
        self.assertEqual(event["event"]["functionName"], "OnMockEvent")
        self.assertEqual(events["events"][0]["functionName"], "OnMockEvent")
        self.assertEqual(len(keyframes["keyframes"]), 2)
        self.assertEqual(clip_info["eventCount"], 1)
        self.assertEqual(parameter["parameter"]["name"], "Speed")
        self.assertEqual(state["state"]["name"], "Idle")
        self.assertEqual(run_state["state"]["name"], "Run")
        self.assertEqual(transition["transition"]["destinationState"], "Run")
        self.assertEqual(controller_info["path"], controller_path)
        self.assertEqual(controller_info["parameterCount"], 1)
        self.assertEqual(controller_info["transitionCount"], 1)
        self.assertEqual(controller_info["stateCount"], 2)
        self.assertEqual(controller_info["layers"][0]["defaultState"], "Idle")
        self.assertEqual(controller_info["layers"][0]["anyStateTransitionCount"], 0)
        self.assertEqual(controller_info["layers"][0]["entryTransitionCount"], 0)
        self.assertEqual(controller_info["layers"][0]["states"][0]["name"], "Idle")
        self.assertTrue(controller_info["layers"][0]["states"][0]["isDefault"])
        self.assertEqual(controller_info["layers"][0]["states"][0]["transitionCount"], 1)
        self.assertEqual(controller_info["layers"][0]["states"][1]["name"], "Run")
        self.assertFalse(controller_info["layers"][0]["states"][1]["isDefault"])
        self.assertEqual(set_default["defaultState"], "Run")
        self.assertEqual(set_default["previousDefaultState"], "Idle")
        self.assertEqual(controller_info_after["layers"][0]["defaultState"], "Run")
        self.assertFalse(controller_info_after["layers"][0]["states"][0]["isDefault"])
        self.assertTrue(controller_info_after["layers"][0]["states"][1]["isDefault"])

        terrain = call_tool(
            "unity_terrain_create",
            {"name": "MockTerrain", "width": 64, "length": 64, "height": 20},
        )
        terrain_list = call_tool("unity_terrain_list")
        heights = call_tool(
            "unity_terrain_get_heights_region",
            {"name": "MockTerrain", "xBase": 0, "yBase": 0, "width": 2, "height": 2},
        )
        steepness = call_tool("unity_terrain_get_steepness", {"name": "MockTerrain", "worldX": 4, "worldZ": 4})
        trees = call_tool("unity_terrain_get_tree_instances", {"name": "MockTerrain", "limit": 5})
        self.assertEqual(terrain["name"], "MockTerrain")
        self.assertEqual(terrain_list["terrains"][0]["name"], "MockTerrain")
        self.assertEqual(heights["heights"], [[0.0, 0.0], [0.0, 0.0]])
        self.assertEqual(steepness["steepness"], 0.0)
        self.assertEqual(trees["count"], 0)

        # ── New terrain mutation mock coverage ──────────────────────────
        settings = call_tool("unity_terrain_set_settings", {"name": "MockTerrain", "width": 200, "length": 200})
        self.assertTrue(settings["success"])
        set_height = call_tool("unity_terrain_set_height", {"name": "MockTerrain", "worldX": 10, "worldZ": 10, "height": 5.0})
        self.assertTrue(set_height["success"])
        set_region = call_tool("unity_terrain_set_heights_region", {"name": "MockTerrain", "xBase": 0, "yBase": 0, "heights": [[0.2, 0.3]]})
        self.assertTrue(set_region["success"])
        self.assertEqual(set_region["samplesWritten"], 2)
        raise_lower = call_tool("unity_terrain_raise_lower", {"name": "MockTerrain", "worldX": 5, "worldZ": 5, "amount": 1.0})
        self.assertTrue(raise_lower["success"])
        flatten = call_tool("unity_terrain_flatten", {"name": "MockTerrain", "height": 0.5})
        self.assertTrue(flatten["success"])
        smooth = call_tool("unity_terrain_smooth", {"name": "MockTerrain", "passes": 2})
        self.assertEqual(smooth["passes"], 2)
        noise = call_tool("unity_terrain_noise", {"name": "MockTerrain", "scale": 50.0})
        self.assertTrue(noise["success"])
        add_layer = call_tool("unity_terrain_add_layer", {"name": "MockTerrain", "texturePath": "Assets/Grass.png"})
        self.assertTrue(add_layer["success"])
        self.assertEqual(add_layer["layerIndex"], 0)
        fill_layer = call_tool("unity_terrain_fill_layer", {"name": "MockTerrain", "layerIndex": 0})
        self.assertTrue(fill_layer["success"])
        paint_layer = call_tool("unity_terrain_paint_layer", {"name": "MockTerrain", "worldX": 10, "worldZ": 10, "layerIndex": 0})
        self.assertTrue(paint_layer["success"])
        remove_layer = call_tool("unity_terrain_remove_layer", {"name": "MockTerrain", "layerIndex": 0})
        self.assertTrue(remove_layer["success"])
        add_detail = call_tool("unity_terrain_add_detail_prototype", {"name": "MockTerrain", "texturePath": "Assets/Grass.png"})
        self.assertTrue(add_detail["success"])
        self.assertEqual(add_detail["prototypeIndex"], 0)
        add_tree_proto = call_tool("unity_terrain_add_tree_prototype", {"name": "MockTerrain", "prefabPath": "Assets/Oak.prefab"})
        self.assertEqual(add_tree_proto["prototypeIndex"], 0)
        place_trees = call_tool("unity_terrain_place_trees", {"name": "MockTerrain", "prototypeIndex": 0, "count": 3})
        self.assertEqual(place_trees["treesPlaced"], 3)
        clear_trees = call_tool("unity_terrain_clear_trees", {"name": "MockTerrain"})
        self.assertEqual(clear_trees["treesRemoved"], 3)
        remove_tree_proto = call_tool("unity_terrain_remove_tree_prototype", {"name": "MockTerrain", "prototypeIndex": 0})
        self.assertTrue(remove_tree_proto["success"])
        scatter_detail = call_tool("unity_terrain_scatter_detail", {"name": "MockTerrain", "prototypeIndex": 0, "count": 5})
        self.assertEqual(scatter_detail["detailsPlaced"], 5)
        paint_detail = call_tool("unity_terrain_paint_detail", {"name": "MockTerrain", "worldX": 5, "worldZ": 5, "prototypeIndex": 0})
        self.assertTrue(paint_detail["success"])
        clear_detail = call_tool("unity_terrain_clear_detail", {"name": "MockTerrain", "prototypeIndex": 0})
        self.assertTrue(clear_detail["success"])
        set_neighbors = call_tool("unity_terrain_set_neighbors", {"name": "MockTerrain", "left": "Terrain_0_0"})
        self.assertEqual(set_neighbors["neighborsSet"], 1)
        set_holes = call_tool("unity_terrain_set_holes", {"name": "MockTerrain", "holes": [[True, False]]})
        self.assertEqual(set_holes["holesSet"], 1)
        resize = call_tool("unity_terrain_resize", {"name": "MockTerrain", "width": 256, "length": 256, "height": 100})
        self.assertTrue(resize["success"])
        create_grid = call_tool("unity_terrain_create_grid", {"countX": 2, "countZ": 2, "width": 64, "length": 64, "height": 30})
        self.assertEqual(create_grid["count"], 4)
        export_hm = call_tool("unity_terrain_export_heightmap", {"name": "MockTerrain", "outputPath": "Assets/hm.png"})
        self.assertEqual(export_hm["outputPath"], "Assets/hm.png")
        import_hm = call_tool("unity_terrain_import_heightmap", {"name": "MockTerrain", "imagePath": "Assets/hm.png"})
        self.assertTrue(import_hm["success"])

        # ── New animation mock coverage ──────────────────────────────────
        anim_go = call_tool("unity_gameobject_create", {"name": "AnimGO", "primitiveType": "Empty"})
        assign = call_tool("unity_animation_assign_controller", {"gameObjectPath": "AnimGO", "controllerPath": controller_path})
        self.assertTrue(assign["success"])
        self.assertEqual(assign["controllerPath"], controller_path)
        set_settings = call_tool("unity_animation_set_clip_settings", {"clipPath": clip_path, "loop": False, "frameRate": 60})
        self.assertTrue(set_settings["success"])
        add_kf = call_tool("unity_animation_add_keyframe", {"clipPath": clip_path, "typeName": "Transform", "propertyName": "localScale.x", "time": 0.5, "value": 2.0})
        self.assertTrue(add_kf["success"])
        remove_kf = call_tool("unity_animation_remove_keyframe", {"clipPath": clip_path, "typeName": "Transform", "propertyName": "localScale.x", "time": 0.5})
        self.assertEqual(remove_kf["keyframesRemoved"], 1)
        remove_curve = call_tool("unity_animation_remove_curve", {"clipPath": clip_path, "typeName": "Transform", "propertyName": "localPosition.x"})
        self.assertTrue(remove_curve["curveRemoved"])
        remove_event = call_tool("unity_animation_remove_event", {"clipPath": clip_path, "time": 0.5})
        self.assertEqual(remove_event["eventsRemoved"], 1)
        remove_param = call_tool("unity_animation_remove_parameter", {"controllerPath": controller_path, "parameterName": "Speed"})
        self.assertTrue(remove_param["parameterRemoved"])
        remove_trans = call_tool("unity_animation_remove_transition", {"controllerPath": controller_path, "destinationState": "Run"})
        self.assertTrue(remove_trans["transitionRemoved"])
        blend_tree = call_tool("unity_animation_create_blend_tree", {"controllerPath": controller_path, "stateName": "LocomotionBlend", "blendType": "Simple1D", "parameter": "Speed"})
        self.assertTrue(blend_tree["success"])
        self.assertEqual(blend_tree["stateName"], "LocomotionBlend")
        get_blend = call_tool("unity_animation_get_blend_tree", {"controllerPath": controller_path, "layerIndex": 0, "stateName": "LocomotionBlend"})
        self.assertEqual(get_blend["stateName"], "LocomotionBlend")
        self.assertEqual(get_blend["blendTree"]["blendType"], "Simple1D")
        # remove-layer and remove-state require a layer/state to exist first
        remove_state = call_tool("unity_animation_remove_state", {"controllerPath": controller_path, "stateName": "LocomotionBlend"})
        self.assertTrue(remove_state["stateRemoved"])

    def test_mock_bridge_rejects_animation_self_transition(self) -> None:
        def call_tool(tool_name: str, params: dict | None = None) -> dict:
            args = ["--json", "tool", tool_name]
            if params is not None:
                args.extend(["--params", json.dumps(params)])
            result = self.run_cli(*args)
            return json.loads(result.stdout.strip())

        controller_path = "Assets/MockOnly/SelfTransition.controller"
        clip_path = "Assets/MockOnly/SelfTransition.anim"
        call_tool("unity_animation_create_clip", {"path": clip_path, "loop": True, "frameRate": 30})
        call_tool("unity_animation_create_controller", {"path": controller_path})
        call_tool(
            "unity_animation_add_state",
            {
                "controllerPath": controller_path,
                "stateName": "Idle",
                "clipPath": clip_path,
                "speed": 1.0,
                "isDefault": True,
            },
        )

        transition = call_tool(
            "unity_animation_add_transition",
            {
                "controllerPath": controller_path,
                "sourceState": "Idle",
                "destinationState": "Idle",
                "duration": 0.2,
            },
        )

        self.assertIn("error", transition)
        self.assertIn("Self-transition", transition["error"])
        remove_layer = call_tool("unity_animation_remove_layer", {"controllerPath": controller_path, "layerIndex": 0})
        self.assertFalse(remove_layer["layerRemoved"])  # no layers added yet, so nothing to remove

    def test_mock_bridge_extended_mock_coverage(self) -> None:
        catalog_path = Path(__file__).resolve().parents[1] / "data" / "upstream_tool_catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        tool_routes = {
            str(item.get("name") or ""): str(item.get("route") or "")
            for item in catalog.get("tools", [])
            if item.get("route")
        }
        tool_routes.update(
            {
                "unity_mppm_info": "scenario/info",
                "unity_mppm_list_scenarios": "scenario/list",
                "unity_mppm_status": "scenario/status",
                "unity_mppm_activate_scenario": "scenario/activate",
                "unity_mppm_start": "scenario/start",
                "unity_mppm_stop": "scenario/stop",
            }
        )

        def call_tool(tool_name: str, params: dict | None = None) -> dict:
            route = tool_routes.get(tool_name)
            if not route:
                self.fail(f"Tool route not found for `{tool_name}`.")
            return self.server.route_result(route, params or {})

        # ── Prefab mock coverage ─────────────────────────────────────────
        prefab_path = "Assets/MockOnly/MockPrefab.prefab"
        variant_path = "Assets/MockOnly/MockPrefabVariant.prefab"
        # seed the prefab store so prefab/info, hierarchy, etc. find it
        self.server.prefabs[prefab_path] = {"name": "MockPrefab", "components": ["Transform", "BoxCollider"], "isVariant": False}
        prefab_info = call_tool("unity_prefab_info", {"assetPath": prefab_path})
        self.assertEqual(prefab_info["name"], "MockPrefab")
        self.assertFalse(prefab_info["isVariant"])
        self.assertFalse(prefab_info["isInstance"])
        self.server.gameobjects["MockPrefabInstance"] = {
            "name": "MockPrefabInstance",
            "components": ["Transform", "MeshRenderer"],
            "prefabAssetPath": prefab_path,
        }
        prefab_instance_info = call_tool("unity_prefab_info", {"path": "MockPrefabInstance"})
        self.assertEqual(prefab_instance_info["name"], "MockPrefabInstance")
        self.assertTrue(prefab_instance_info["isInstance"])
        self.assertEqual(prefab_instance_info["assetPath"], prefab_path)
        hierarchy = call_tool("unity_prefab_get_hierarchy", {"path": prefab_path})
        self.assertEqual(hierarchy["name"], "MockPrefab")
        props = call_tool("unity_prefab_get_properties", {"path": prefab_path, "component": "BoxCollider"})
        self.assertEqual(props["component"], "BoxCollider")
        set_prop = call_tool("unity_prefab_set_property", {"path": prefab_path, "propertyName": "isTrigger", "value": True})
        self.assertTrue(set_prop["success"])
        set_ref = call_tool("unity_prefab_set_reference", {"path": prefab_path, "propertyName": "target", "referencePath": "Assets/Other.prefab"})
        self.assertTrue(set_ref["success"])
        add_comp = call_tool("unity_prefab_add_component", {"path": prefab_path, "component": "Rigidbody"})
        self.assertTrue(add_comp["success"])
        remove_comp = call_tool("unity_prefab_remove_component", {"path": prefab_path, "component": "Rigidbody"})
        self.assertTrue(remove_comp["removed"])
        add_go = call_tool("unity_prefab_add_gameobject", {"path": prefab_path, "name": "ChildNode"})
        self.assertEqual(add_go["childName"], "ChildNode")
        remove_go = call_tool("unity_prefab_remove_gameobject", {"path": prefab_path, "childPath": "MockPrefab/ChildNode"})
        self.assertTrue(remove_go["removed"])
        apply_ov = call_tool("unity_prefab_apply_overrides", {"prefabPath": prefab_path})
        self.assertTrue(apply_ov["success"])
        revert_ov = call_tool("unity_prefab_revert_overrides", {"prefabPath": prefab_path})
        self.assertTrue(revert_ov["success"])
        create_var = call_tool("unity_prefab_create_variant", {"sourcePath": prefab_path, "variantPath": variant_path})
        self.assertEqual(create_var["variantPath"], variant_path)
        var_info = call_tool("unity_prefab_variant_info", {"path": variant_path})
        self.assertTrue(var_info["isVariant"])
        compare = call_tool("unity_prefab_compare_variant", {"path": variant_path})
        self.assertEqual(compare["differenceCount"], 0)
        apply_var_ov = call_tool("unity_prefab_apply_variant_override", {"path": variant_path})
        self.assertTrue(apply_var_ov["success"])
        revert_var_ov = call_tool("unity_prefab_revert_variant_override", {"path": variant_path})
        self.assertTrue(revert_var_ov["success"])
        transfer = call_tool("unity_prefab_transfer_variant_overrides", {"sourcePath": prefab_path, "destinationPath": variant_path})
        self.assertEqual(transfer["overridesTransferred"], 1)
        unpack = call_tool("unity_prefab_unpack", {"prefabPath": prefab_path, "mode": "completely"})
        self.assertTrue(unpack["success"])

        # ── Asmdef mock coverage ─────────────────────────────────────────
        asmdef_path = "Assets/MockOnly/MockAssembly.asmdef"
        asmdef_list = call_tool("unity_asmdef_list")
        self.assertIn("asmdefs", asmdef_list)
        asmdef_create = call_tool("unity_asmdef_create", {"path": asmdef_path, "name": "MockAssembly"})
        self.assertTrue(asmdef_create["success"])
        self.assertEqual(asmdef_create["name"], "MockAssembly")
        asmdef_info = call_tool("unity_asmdef_info", {"path": asmdef_path})
        self.assertEqual(asmdef_info["name"], "MockAssembly")
        asmdef_ref = call_tool("unity_asmdef_create_ref", {"path": "Assets/MockOnly/MockAssembly.asmref"})
        self.assertTrue(asmdef_ref["success"])
        add_refs = call_tool("unity_asmdef_add_references", {"path": asmdef_path, "references": ["Unity.TextMeshPro"]})
        self.assertEqual(add_refs["referencesAdded"], 1)
        remove_refs = call_tool("unity_asmdef_remove_references", {"path": asmdef_path, "references": ["Unity.TextMeshPro"]})
        self.assertEqual(remove_refs["referencesRemoved"], 1)
        set_platforms = call_tool("unity_asmdef_set_platforms", {"path": asmdef_path, "includePlatforms": ["Editor"]})
        self.assertTrue(set_platforms["success"])
        self.assertIn("Editor", set_platforms["includePlatforms"])
        update_settings = call_tool("unity_asmdef_update_settings", {"path": asmdef_path, "allowUnsafeCode": True})
        self.assertTrue(update_settings["success"])

        # ── Particle mock coverage ───────────────────────────────────────
        particle_create = call_tool("unity_particle_create", {"name": "MockParticles", "position": {"x": 0, "y": 1, "z": 0}})
        self.assertTrue(particle_create["success"])
        self.assertEqual(particle_create["name"], "MockParticles")
        particle_info = call_tool("unity_particle_info", {"name": "MockParticles"})
        self.assertFalse(particle_info["isPlaying"])
        particle_play = call_tool("unity_particle_playback", {"name": "MockParticles", "action": "play"})
        self.assertEqual(particle_play["action"], "play")
        set_emission = call_tool("unity_particle_set_emission", {"name": "MockParticles", "rateOverTime": 50})
        self.assertEqual(set_emission["rateOverTime"], 50)
        set_main = call_tool("unity_particle_set_main", {"name": "MockParticles", "duration": 3.0, "loop": False})
        self.assertTrue(set_main["success"])
        set_shape = call_tool("unity_particle_set_shape", {"name": "MockParticles", "shape": "Cone"})
        self.assertEqual(set_shape["shape"], "Cone")

        # ── LOD mock coverage ────────────────────────────────────────────
        lod_create = call_tool("unity_lod_create", {"name": "MockLOD", "lodCount": 3})
        self.assertTrue(lod_create["success"])
        self.assertEqual(lod_create["lodCount"], 3)
        lod_info = call_tool("unity_lod_info", {"name": "MockLOD"})
        self.assertEqual(lod_info["lodCount"], 3)
        self.assertEqual(len(lod_info["lods"]), 3)

        # ── Constraint mock coverage ─────────────────────────────────────
        constraint_add = call_tool("unity_constraint_add", {"gameObjectPath": "MockLOD", "constraintType": "LookAtConstraint", "sources": [{"path": "Camera"}]})
        self.assertTrue(constraint_add["success"])
        self.assertEqual(constraint_add["constraintType"], "LookAtConstraint")
        self.assertEqual(constraint_add["sourceCount"], 1)
        constraint_info = call_tool("unity_constraint_info", {"gameObjectPath": "MockLOD"})
        self.assertIn("constraints", constraint_info)

        # ── Search mock coverage ─────────────────────────────────────────
        self.server.scripts["Assets/Scripts/PlayerController.cs"] = "public class PlayerController {}"
        self.server.gameobjects["Player"] = {"name": "Player", "components": ["Transform", "PlayerController"], "tag": "Player", "layer": "Default"}
        search_assets = call_tool("unity_search_assets", {"query": "PlayerController"})
        self.assertGreater(search_assets["count"], 0)
        by_component = call_tool("unity_search_by_component", {"component": "PlayerController"})
        self.assertGreater(by_component["count"], 0)
        by_layer = call_tool("unity_search_by_layer", {"layer": "Default"})
        self.assertGreaterEqual(by_layer["count"], 0)
        by_name = call_tool("unity_search_by_name", {"name": "Player"})
        self.assertGreater(by_name["count"], 0)
        by_shader = call_tool("unity_search_by_shader", {"shader": "Standard"})
        self.assertIn("results", by_shader)
        by_tag = call_tool("unity_search_by_tag", {"tag": "Player"})
        self.assertIn("results", by_tag)

        # ── Shader / ShaderGraph mock coverage ───────────────────────────
        sg_path = "Assets/MockOnly/MockGraph.shadergraph"
        shader_list = call_tool("unity_shader_list")
        self.assertGreater(shader_list["count"], 0)
        shader_props = call_tool("unity_shader_get_properties", {"shaderPath": "Packages/com.unity.render-pipelines.universal/Shaders/Lit.shader"})
        self.assertIn("properties", shader_props)
        sg_node_types = call_tool("unity_shadergraph_get_node_types")
        self.assertGreater(sg_node_types["count"], 0)
        sg_add = call_tool("unity_shadergraph_add_node", {"path": sg_path, "nodeType": "AddNode", "position": {"x": 100, "y": 200}})
        self.assertTrue(sg_add["success"])
        node_id = sg_add["node"]["id"]
        sg_nodes = call_tool("unity_shadergraph_get_nodes", {"path": sg_path})
        self.assertEqual(sg_nodes["count"], 1)
        sg_connect = call_tool("unity_shadergraph_connect", {"path": sg_path, "fromNode": node_id, "fromPort": "Out", "toNode": "master", "toPort": "Color"})
        self.assertTrue(sg_connect["success"])
        sg_edges = call_tool("unity_shadergraph_get_edges", {"path": sg_path})
        self.assertEqual(sg_edges["count"], 1)
        sg_set_prop = call_tool("unity_shadergraph_set_node_property", {"path": sg_path, "nodeId": node_id, "property": "value", "value": 1.5})
        self.assertTrue(sg_set_prop["success"])
        sg_info = call_tool("unity_shadergraph_info", {"path": sg_path})
        self.assertEqual(sg_info["nodeCount"], 1)
        sg_subgraphs = call_tool("unity_shadergraph_list_subgraphs", {"path": sg_path})
        self.assertEqual(sg_subgraphs["count"], 0)
        sg_open = call_tool("unity_shadergraph_open", {"path": sg_path})
        self.assertTrue(sg_open["success"])
        sg_disconnect = call_tool("unity_shadergraph_disconnect", {"path": sg_path, "fromNode": node_id, "toNode": "master"})
        self.assertEqual(sg_disconnect["removed"], 1)
        sg_remove = call_tool("unity_shadergraph_remove_node", {"path": sg_path, "nodeId": node_id})
        self.assertTrue(sg_remove["removed"])

        # ── Selection mock coverage ──────────────────────────────────────
        sel_set = call_tool("unity_selection_set", {"paths": ["Player", "MockLOD"]})
        self.assertEqual(sel_set["count"], 2)
        sel_get = call_tool("unity_selection_get")
        self.assertEqual(sel_get["count"], 2)
        find_by_type = call_tool("unity_selection_find_by_type", {"typeName": "PlayerController"})
        self.assertIn("results", find_by_type)
        focus = call_tool("unity_selection_focus_scene_view", {"path": "Player"})
        self.assertTrue(focus["success"])

        # ── ScriptableObject mock coverage ───────────────────────────────
        so_types = call_tool("unity_scriptableobject_list_types")
        self.assertGreater(so_types["count"], 0)
        so_create = call_tool("unity_scriptableobject_create", {"typeName": "GameSettings", "path": "Assets/Data/GameSettings.asset"})
        self.assertTrue(so_create["success"])
        self.assertEqual(so_create["typeName"], "GameSettings")
        so_info = call_tool("unity_scriptableobject_info", {"path": "Assets/Data/GameSettings.asset"})
        self.assertEqual(so_info["typeName"], "GameSettings")
        so_set = call_tool("unity_scriptableobject_set_field", {"path": "Assets/Data/GameSettings.asset", "fieldName": "maxHealth", "value": 100})
        self.assertTrue(so_set["success"])
        self.assertEqual(so_set["value"], 100)

        # ── Settings mock coverage ───────────────────────────────────────
        physics_settings = call_tool("unity_settings_physics")
        self.assertIn("gravity", physics_settings)
        player_settings = call_tool("unity_settings_player")
        self.assertIn("productName", player_settings)
        render_settings = call_tool("unity_settings_render_pipeline")
        self.assertIn("renderPipeline", render_settings)
        set_physics = call_tool("unity_settings_set_physics", {"gravity": {"x": 0, "y": -15.0, "z": 0}})
        self.assertTrue(set_physics["success"])
        set_player = call_tool("unity_settings_set_player", {"productName": "MockGame"})
        self.assertTrue(set_player["success"])
        self.assertEqual(set_player["productName"], "MockGame")
        set_quality = call_tool("unity_settings_set_quality_level", {"qualityLevel": 2})
        self.assertTrue(set_quality["success"])
        self.assertEqual(set_quality["qualityLevel"], 2)
        set_time = call_tool("unity_settings_set_time", {"fixedDeltaTime": 0.01, "timeScale": 0.5})
        self.assertTrue(set_time["success"])
        self.assertEqual(set_time["timeScale"], 0.5)

        # ── PlayerPrefs mock coverage ────────────────────────────────────
        pref_set = call_tool("unity_playerprefs_set", {"key": "mock.volume", "value": 7, "type": "int"})
        self.assertTrue(pref_set["success"])
        self.assertEqual(pref_set["type"], "int")
        pref_get = call_tool("unity_playerprefs_get", {"key": "mock.volume", "type": "int"})
        self.assertTrue(pref_get["exists"])
        self.assertEqual(pref_get["value"], 7)
        pref_delete = call_tool("unity_playerprefs_delete", {"key": "mock.volume"})
        self.assertTrue(pref_delete["removed"])
        call_tool("unity_playerprefs_set", {"key": "mock.name", "value": "Codex", "type": "string"})
        pref_delete_all = call_tool("unity_playerprefs_delete_all")
        self.assertEqual(pref_delete_all["deletedCount"], 1)

        # ── Tag/Layer mock coverage ──────────────────────────────────────
        tl_info = call_tool("unity_taglayer_info")
        self.assertIn("tags", tl_info)
        self.assertIn("layers", tl_info)
        tl_add = call_tool("unity_taglayer_add_tag", {"tag": "Enemy"})
        self.assertTrue(tl_add["success"])
        tl_set_tag = call_tool("unity_taglayer_set_tag", {"gameObjectPath": "Player", "tag": "Player"})
        self.assertEqual(tl_set_tag["tag"], "Player")
        tl_set_layer = call_tool("unity_taglayer_set_layer", {"gameObjectPath": "Player", "layer": "Default"})
        self.assertEqual(tl_set_layer["layer"], "Default")
        tl_set_static = call_tool("unity_taglayer_set_static", {"gameObjectPath": "Player", "isStatic": True})
        self.assertTrue(tl_set_static["isStatic"])

        # ── Texture mock coverage ────────────────────────────────────────
        tex_path = "Assets/Textures/MockTex.png"
        tex_info = call_tool("unity_texture_info", {"path": tex_path})
        self.assertEqual(tex_info["width"], 512)
        tex_reimport = call_tool("unity_texture_reimport", {"path": tex_path})
        self.assertTrue(tex_reimport["success"])
        tex_set_import = call_tool("unity_texture_set_import", {"path": tex_path, "textureType": "Sprite", "maxSize": 1024})
        self.assertEqual(tex_set_import["textureType"], "Sprite")
        tex_normalmap = call_tool("unity_texture_set_normalmap", {"path": tex_path})
        self.assertEqual(tex_normalmap["textureType"], "NormalMap")
        tex_sprite = call_tool("unity_texture_set_sprite", {"path": tex_path, "pivot": {"x": 0.5, "y": 0.5}})
        self.assertEqual(tex_sprite["textureType"], "Sprite")

        # ── SpriteAtlas mock coverage ────────────────────────────────────
        atlas_path = "Assets/Atlases/MockAtlas.spriteatlas"
        atlas_create = call_tool("unity_spriteatlas_create", {"path": atlas_path, "includeInBuild": True})
        self.assertTrue(atlas_create["success"])
        atlas_add = call_tool("unity_spriteatlas_add", {"path": atlas_path, "assetPath": tex_path})
        self.assertEqual(atlas_add["addedCount"], 1)
        atlas_info = call_tool("unity_spriteatlas_info", {"path": atlas_path})
        self.assertTrue(atlas_info["exists"])
        self.assertEqual(atlas_info["packableCount"], 1)
        atlas_settings = call_tool("unity_spriteatlas_settings", {"path": atlas_path, "padding": 4, "enableRotation": False})
        self.assertEqual(atlas_settings["settings"]["padding"], 4)
        atlas_list = call_tool("unity_spriteatlas_list", {"folder": "Assets/Atlases"})
        self.assertEqual(atlas_list["count"], 1)
        atlas_remove = call_tool("unity_spriteatlas_remove", {"path": atlas_path, "assetPath": tex_path})
        self.assertEqual(atlas_remove["removedCount"], 1)
        atlas_delete = call_tool("unity_spriteatlas_delete", {"path": atlas_path})
        self.assertTrue(atlas_delete["deleted"])

        # ── NavMesh mock coverage ────────────────────────────────────────
        nm_agent = call_tool("unity_navmesh_add_agent", {"gameObjectPath": "Player", "speed": 5.0})
        self.assertTrue(nm_agent["success"])
        self.assertEqual(nm_agent["speed"], 5.0)
        nm_obstacle = call_tool("unity_navmesh_add_obstacle", {"gameObjectPath": "MockLOD", "shape": "Capsule"})
        self.assertTrue(nm_obstacle["success"])
        nm_bake = call_tool("unity_navmesh_bake")
        self.assertTrue(nm_bake["success"])
        self.assertGreater(nm_bake["triangleCount"], 0)
        nm_dest = call_tool("unity_navmesh_set_destination", {"gameObjectPath": "Player", "destination": {"x": 10, "y": 0, "z": 10}})
        self.assertEqual(nm_dest["pathStatus"], "Complete")
        nm_clear = call_tool("unity_navmesh_clear")
        self.assertTrue(nm_clear["success"])

        # ── Physics mock coverage ────────────────────────────────────────
        col_matrix = call_tool("unity_physics_collision_matrix")
        self.assertIn("layers", col_matrix)
        overlap_box = call_tool("unity_physics_overlap_box", {"center": {"x": 0, "y": 0, "z": 0}, "halfExtents": {"x": 1, "y": 1, "z": 1}})
        self.assertIn("colliders", overlap_box)
        overlap_sphere = call_tool("unity_physics_overlap_sphere", {"center": {"x": 0, "y": 0, "z": 0}, "radius": 2.0})
        self.assertEqual(overlap_sphere["radius"], 2.0)
        set_col_layer = call_tool("unity_physics_set_collision_layer", {"layerA": 0, "layerB": 8, "ignore": True})
        self.assertTrue(set_col_layer["success"])
        self.assertTrue(set_col_layer["ignore"])
        set_gravity = call_tool("unity_physics_set_gravity", {"gravity": {"x": 0, "y": -20.0, "z": 0}})
        self.assertTrue(set_gravity["success"])
        self.assertEqual(set_gravity["gravity"]["y"], -20.0)

        # ── Graphics extra mock coverage ─────────────────────────────────
        asset_preview = call_tool("unity_graphics_asset_preview", {"path": prefab_path, "width": 64, "height": 64})
        self.assertTrue(asset_preview["success"])
        self.assertEqual(asset_preview["width"], 64)
        prefab_render = call_tool("unity_graphics_prefab_render", {"path": prefab_path, "width": 128, "height": 128})
        self.assertTrue(prefab_render["success"])
        tex_info_g = call_tool("unity_graphics_texture_info", {"path": tex_path})
        self.assertEqual(tex_info_g["width"], 1024)

        # ── Packages mock coverage ───────────────────────────────────────
        pkg_list = call_tool("unity_packages_list")
        self.assertGreater(pkg_list["count"], 0)
        pkg_info = call_tool("unity_packages_info", {"packageId": "com.unity.textmeshpro"})
        self.assertEqual(pkg_info["name"], "com.unity.textmeshpro")
        pkg_search = call_tool("unity_packages_search", {"query": "cinemachine"})
        self.assertGreater(pkg_search["count"], 0)
        pkg_add = call_tool("unity_packages_add", {"packageId": "com.unity.cinemachine", "version": "2.9.0"})
        self.assertTrue(pkg_add["success"])
        pkg_remove = call_tool("unity_packages_remove", {"packageId": "com.unity.cinemachine"})
        self.assertTrue(pkg_remove["success"])

        # ── Profiler + memory mock coverage ─────────────────────────────
        prof_enable = call_tool("unity_profiler_enable", {"enabled": True})
        self.assertTrue(prof_enable["success"])
        prof_analyze = call_tool("unity_profiler_analyze")
        self.assertEqual(prof_analyze["bottleneck"], "Rendering")
        prof_frame = call_tool("unity_profiler_frame_data", {"frame": 5})
        self.assertEqual(prof_frame["frame"], 5)
        prof_mem = call_tool("unity_profiler_memory")
        self.assertIn("totalMB", prof_mem)
        mem_breakdown = call_tool("unity_memory_breakdown")
        self.assertIn("textures", mem_breakdown)
        mem_snapshot = call_tool("unity_memory_snapshot")
        self.assertTrue(mem_snapshot["success"])
        mem_top = call_tool("unity_memory_top_assets")
        self.assertEqual(mem_top["count"], 3)

        # ── Debugger mock coverage ───────────────────────────────────────
        dbg_enable = call_tool("unity_debugger_enable", {"enabled": True})
        self.assertTrue(dbg_enable["success"])
        dbg_events = call_tool("unity_debugger_events", {"limit": 10})
        self.assertEqual(dbg_events["count"], 0)
        dbg_detail = call_tool("unity_debugger_event_details", {"eventId": "evt-001"})
        self.assertEqual(dbg_detail["eventId"], "evt-001")

        # ── EditorPrefs mock coverage ────────────────────────────────────
        ep_set = call_tool("unity_editorprefs_set", {"key": "MockPref", "value": 42})
        self.assertTrue(ep_set["success"])
        ep_get = call_tool("unity_editorprefs_get", {"key": "MockPref"})
        self.assertTrue(ep_get["exists"])
        self.assertEqual(ep_get["value"], 42)
        ep_del = call_tool("unity_editorprefs_delete", {"key": "MockPref"})
        self.assertTrue(ep_del["deleted"])

        # ── Audio additional mock coverage ───────────────────────────────
        audio_src = call_tool("unity_audio_create_source", {"gameObjectPath": "Player", "clipPath": "Assets/Audio/Jump.wav"})
        self.assertTrue(audio_src["success"])
        audio_global = call_tool("unity_audio_set_global", {"volume": 0.5, "pause": False})
        self.assertTrue(audio_global["success"])
        self.assertEqual(audio_global["volume"], 0.5)

        # ── Console clear mock coverage ──────────────────────────────────
        console_clear = call_tool("unity_console_clear")
        self.assertTrue(console_clear["success"])

        # ── Screenshot mock coverage ─────────────────────────────────────
        ss_game = call_tool("unity_screenshot_game", {"path": "Temp/game.png", "width": 1280, "height": 720})
        self.assertTrue(ss_game["success"])
        self.assertEqual(ss_game["width"], 1280)
        ss_scene = call_tool("unity_screenshot_scene", {"path": "Temp/scene.png"})
        self.assertTrue(ss_scene["success"])

        # ── Testing additional mock coverage ─────────────────────────────
        run_tests = call_tool("unity_testing_run_tests", {"mode": "EditMode"})
        self.assertTrue(run_tests["success"])
        job_id = run_tests["jobId"]
        get_job = call_tool("unity_testing_get_job", {"jobId": job_id})
        self.assertEqual(get_job["status"], "Completed")
        self.assertEqual(get_job["failed"], 0)

        # ── Undo additional mock coverage ────────────────────────────────
        undo_hist = call_tool("unity_undo_history")
        self.assertIn("entries", undo_hist)
        undo_clear = call_tool("unity_undo_clear")
        self.assertTrue(undo_clear["success"])
        redo = call_tool("unity_redo")
        self.assertTrue(redo["success"])

        # ── VFX mock coverage ────────────────────────────────────────────
        vfx_list = call_tool("unity_vfx_list")
        self.assertEqual(vfx_list["count"], 0)
        vfx_open = call_tool("unity_vfx_open", {"path": "Assets/VFX/MockVFX.vfx"})
        self.assertTrue(vfx_open["success"])

        # ── MPPM mock coverage ───────────────────────────────────────────
        mppm_info = call_tool("unity_mppm_info")
        self.assertTrue(mppm_info["available"])
        mppm_list = call_tool("unity_mppm_list_scenarios")
        self.assertEqual(mppm_list["count"], 1)
        mppm_activate = call_tool("unity_mppm_activate_scenario", {"path": "Assets/CLIAnythingFixtures/MPPM/TwoPlayers.mppm"})
        self.assertTrue(mppm_activate["success"])
        mppm_start = call_tool("unity_mppm_start")
        self.assertTrue(mppm_start["running"])
        mppm_status = call_tool("unity_mppm_status")
        self.assertEqual(mppm_status["playerCount"], 2)
        mppm_stop = call_tool("unity_mppm_stop")
        self.assertFalse(mppm_stop["running"])

        # ── Component additional mock coverage ───────────────────────────
        comp_refs = call_tool("unity_component_get_referenceable", {"gameObjectPath": "Player", "component": "PlayerController"})
        self.assertIn("referenceableFields", comp_refs)
        batch_wire = call_tool("unity_component_batch_wire", {"pairs": [{"source": "Player", "target": "MockLOD", "property": "target"}]})
        self.assertEqual(batch_wire["wired"], 1)
        comp_remove = call_tool("unity_component_remove", {"gameObjectPath": "Player", "component": "AudioSource"})
        self.assertTrue(comp_remove["success"])

        # ── GameObject additional mock coverage ──────────────────────────
        go_dup = call_tool("unity_gameobject_duplicate", {"gameObjectPath": "Player"})
        self.assertTrue(go_dup["success"])
        self.assertIn("_Copy", go_dup["duplicatePath"])
        go_reparent = call_tool("unity_gameobject_reparent", {"gameObjectPath": "Player", "parentPath": "MockLOD"})
        self.assertTrue(go_reparent["success"])
        go_set_active = call_tool("unity_gameobject_set_active", {"gameObjectPath": "Player", "active": False})
        self.assertFalse(go_set_active["active"])

        # ── Agent log mock coverage ──────────────────────────────────────
        agent_log = call_tool("unity_agent_log", {"agentId": "cli-test", "limit": 5})
        self.assertIn("agentId", agent_log)

        # ── Asset + material + build mock coverage ────────────────────────
        asset_import = call_tool("unity_asset_import", {"path": "Assets/Textures/MockTex.png"})
        self.assertTrue(asset_import["success"])
        mat_create = call_tool("unity_material_create", {"path": "Assets/Materials/MockMat.mat", "shader": "Universal Render Pipeline/Lit"})
        self.assertTrue(mat_create["success"])
        build_start = call_tool("unity_build", {"target": "StandaloneWindows64", "buildPath": "Builds/Windows"})
        self.assertTrue(build_start["success"])
        self.assertEqual(build_start["target"], "StandaloneWindows64")

        # ── Execute menu item + renderer + scene + sceneview + context ───
        exec_menu = call_tool("unity_execute_menu_item", {"menuItem": "File/Save Project"})
        self.assertTrue(exec_menu["success"])
        set_mat = call_tool("unity_renderer_set_material", {"gameObjectPath": "Player", "materialPath": "Assets/Materials/MockMat.mat"})
        self.assertTrue(set_mat["success"])
        scene_new = call_tool("unity_scene_new", {"name": "TestScene"})
        self.assertTrue(scene_new["success"])
        self.assertEqual(scene_new["sceneName"], "TestScene")
        sv_cam = call_tool("unity_sceneview_set_camera", {"position": {"x": 0, "y": 5, "z": -10}})
        self.assertTrue(sv_cam["success"])
        ctx = call_tool("unity_get_project_context")
        self.assertIn("projectPath", ctx)

        # ── Input System mock coverage ───────────────────────────────────
        input_path = "Assets/MockOnly/MockControls.inputactions"
        input_create = call_tool("unity_input_create", {"path": input_path, "name": "MockControls"})
        self.assertTrue(input_create["success"])
        input_add_map = call_tool("unity_input_add_map", {"path": input_path, "mapName": "Player"})
        self.assertTrue(input_add_map["success"])
        input_add_action = call_tool(
            "unity_input_add_action",
            {"path": input_path, "mapName": "Player", "actionName": "Jump", "actionType": "Button", "expectedControlType": "Button"},
        )
        self.assertEqual(input_add_action["action"]["actionType"], "Button")
        input_add_binding = call_tool(
            "unity_input_add_binding",
            {"path": input_path, "mapName": "Player", "actionName": "Jump", "bindingPath": "<Keyboard>/space"},
        )
        self.assertEqual(input_add_binding["binding"]["path"], "<Keyboard>/space")
        input_add_composite = call_tool(
            "unity_input_add_composite_binding",
            {
                "path": input_path,
                "mapName": "Player",
                "actionName": "Move",
                "compositeName": "WASD",
                "compositeType": "2DVector",
                "parts": [{"name": "up", "path": "<Keyboard>/w"}],
            },
        )
        self.assertEqual(input_add_composite["binding"]["compositeName"], "WASD")
        input_info = call_tool("unity_input_info", {"path": input_path})
        self.assertEqual(input_info["mapCount"], 1)
        input_remove_action = call_tool("unity_input_remove_action", {"path": input_path, "mapName": "Player", "actionName": "Jump"})
        self.assertTrue(input_remove_action["removed"])
        input_remove_map = call_tool("unity_input_remove_map", {"path": input_path, "mapName": "Player"})
        self.assertTrue(input_remove_map["removed"])
