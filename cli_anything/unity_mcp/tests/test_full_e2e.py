from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn, TCPServer
from urllib.parse import parse_qs, urlparse
import uuid

PNG_1X1_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO2p7QAAAABJRU5ErkJggg=="


def get_cli_command() -> list[str]:
    override = os.environ.get("CLI_ANYTHING_UNITY_MCP_BIN")
    if override:
        return [override]
    for name in ("cli-anything-unity-mcp.exe", "cli-anything-unity-mcp"):
        found = shutil.which(name)
        if found:
            return [found]
    return [sys.executable, "-m", "cli_anything.unity_mcp"]


def get_mcp_command() -> list[str]:
    override = os.environ.get("CLI_ANYTHING_UNITY_MCP_MCP_BIN")
    if override:
        return [override]
    for name in ("cli-anything-unity-mcp-mcp.exe", "cli-anything-unity-mcp-mcp"):
        found = shutil.which(name)
        if found:
            return [found]
    return [sys.executable, "-m", "cli_anything.unity_mcp.mcp_server"]


class MockBridgeServer(ThreadingMixIn, TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int]) -> None:
        super().__init__(server_address, MockBridgeHandler)
        self.tickets: dict[int, dict] = {}
        self.ticket_counter = 0
        self.project_name = "Demo"
        self.project_path = "C:/Projects/Demo"
        self.unity_version = "6000.0.0f1"
        self.reset_state()

    def next_ticket(self) -> int:
        self.ticket_counter += 1
        return self.ticket_counter

    def reset_state(self) -> None:
        self.active_scene_name = "MainScene"
        self.active_scene_path = "Assets/Scenes/MainScene.unity"
        self.scene_dirty = False
        self.is_playing = False
        self.execute_code_calls = []
        self.gameobjects = {}
        self.scripts = {}
        self.prefabs = {}
        self.materials = {}
        self.ui_elements = {}
        self.lighting_environment = {}
        self.animation_clips = {}
        self.animation_controllers = {}
        self.terrains = {}
        self.missing_references = []
        self._shadergraphs: dict = {}
        self._selection: list = []
        self._playerprefs: dict = {}
        self._input_assets: dict = {}
        self._scriptable_objects: dict = {}
        self._editorprefs: dict = {}
        self._spriteatlases: dict = {}
        self._mppm = {
            "activeScenario": None,
            "running": False,
            "scenarios": [
                {
                    "path": "Assets/CLIAnythingFixtures/MPPM/TwoPlayers.mppm",
                    "name": "TwoPlayers",
                    "playerCount": 2,
                }
            ],
        }

    def _resolve_gameobject_name(self, payload: dict) -> str | None:
        raw_name = (
            payload.get("gameObjectPath")
            or payload.get("objectPath")
            or payload.get("path")
            or payload.get("name")
        )
        if raw_name in self.gameobjects:
            return str(raw_name)
        if isinstance(raw_name, str) and "/" in raw_name:
            tail_name = raw_name.split("/")[-1]
            if tail_name in self.gameobjects:
                return tail_name
        return raw_name

    @staticmethod
    def _vec3(value: dict | None = None, *, default: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> dict:
        if not isinstance(value, dict):
            return {"x": float(default[0]), "y": float(default[1]), "z": float(default[2])}
        return {
            "x": float(value.get("x", default[0])),
            "y": float(value.get("y", default[1])),
            "z": float(value.get("z", default[2])),
        }

    @staticmethod
    def _deep_clone(value: dict | list | None) -> dict | list | None:
        if value is None:
            return None
        return json.loads(json.dumps(value))

    def _child_names(self, parent_name: str) -> list[str]:
        return [name for name, go in self.gameobjects.items() if go.get("parent") == parent_name]

    def _hierarchy_path(self, name: str) -> str:
        go = self.gameobjects[name]
        parent = go.get("parent")
        if parent and parent in self.gameobjects:
            return f"{self._hierarchy_path(parent)}/{name}"
        return name

    def _delete_gameobject_recursive(self, name: str) -> list[str]:
        deleted: list[str] = []
        for child_name in list(self._child_names(name)):
            deleted.extend(self._delete_gameobject_recursive(child_name))
        if name in self.gameobjects:
            self.gameobjects.pop(name, None)
            deleted.append(name)
        return deleted

    def _register_gameobject(
        self,
        name: str,
        *,
        components: list[str] | None = None,
        parent: str | None = None,
        position: dict | None = None,
        rotation: dict | None = None,
        scale: dict | None = None,
        primitive_type: str = "Empty",
        component_data: dict | None = None,
    ) -> None:
        self.gameobjects[name] = {
            "instanceId": len(self.gameobjects) + 1,
            "components": list(components or ["Transform"]),
            "component_data": self._deep_clone(component_data) or {},
            "position": self._vec3(position),
            "rotation": self._vec3(rotation),
            "scale": self._vec3(scale, default=(1.0, 1.0, 1.0)),
            "parent": parent if parent in self.gameobjects else None,
            "primitiveType": primitive_type,
        }

    def _create_2d_sample_layout_from_code(self, code: str) -> dict | None:
        if "_Backdrop" not in code or "_Player" not in code:
            return None
        match = re.search(r'var rootName = "([^"]+)";', code or "")
        if not match:
            return None

        root_name = match.group(1)
        self._delete_gameobject_recursive(root_name)

        self._register_gameobject(root_name)
        self._register_gameobject(
            f"{root_name}_Backdrop",
            parent=root_name,
            components=["Transform", "SpriteRenderer"],
            scale={"x": 13.0, "y": 8.0, "z": 1.0},
        )
        self._register_gameobject(
            f"{root_name}_Floor",
            parent=root_name,
            components=["Transform", "SpriteRenderer"],
            position={"x": 0.0, "y": -2.25, "z": 0.0},
            scale={"x": 12.0, "y": 1.2, "z": 1.0},
        )
        self._register_gameobject(
            f"{root_name}_Lane",
            parent=root_name,
            components=["Transform", "SpriteRenderer"],
            position={"x": 0.0, "y": -1.1, "z": 0.0},
            scale={"x": 9.0, "y": 0.18, "z": 1.0},
        )
        self._register_gameobject(
            f"{root_name}_Player",
            parent=root_name,
            components=["Transform", "SpriteRenderer"],
            position={"x": -2.4, "y": -0.35, "z": 0.0},
            scale={"x": 1.35, "y": 2.1, "z": 1.0},
        )
        self._register_gameobject(
            f"{root_name}_PlayerAccent",
            parent=f"{root_name}_Player",
            components=["Transform", "SpriteRenderer"],
            position={"x": 0.0, "y": 0.25, "z": 0.0},
            scale={"x": 0.65, "y": 0.55, "z": 1.0},
        )
        self._register_gameobject(
            f"{root_name}_Beacon",
            parent=root_name,
            components=["Transform", "SpriteRenderer"],
            position={"x": 2.6, "y": 0.15, "z": 0.0},
            rotation={"x": 0.0, "y": 0.0, "z": 45.0},
            scale={"x": 1.35, "y": 1.35, "z": 1.0},
        )
        self._register_gameobject(
            f"{root_name}_BeaconGlow",
            parent=root_name,
            components=["Transform", "SpriteRenderer"],
            position={"x": 2.6, "y": 0.15, "z": 0.0},
            scale={"x": 2.3, "y": 2.3, "z": 1.0},
        )
        self._register_gameobject(
            f"{root_name}_Observer",
            parent=root_name,
            position={"x": 0.0, "y": 0.0, "z": -10.0},
        )
        self.scene_dirty = True
        return {
            "success": True,
            "mode": "2d",
            "created": [
                root_name,
                f"{root_name}_Backdrop",
                f"{root_name}_Floor",
                f"{root_name}_Lane",
                f"{root_name}_Player",
                f"{root_name}_Beacon",
                f"{root_name}_Observer",
            ],
        }

    def _create_3d_fps_scene_from_code(self, code: str) -> dict | None:
        if "CLI_ANYTHING_FPS_SCENE" not in (code or ""):
            return None

        def _extract(name: str) -> str | None:
            match = re.search(rf'var {name} = "([^"]+)";', code or "")
            return match.group(1) if match else None

        root_name = _extract("rootName")
        scene_path = _extract("scenePath")
        floor_material_path = _extract("floorMaterialPath")
        wall_material_path = _extract("wallMaterialPath")
        trim_material_path = _extract("trimMaterialPath")
        accent_material_path = _extract("accentMaterialPath")
        sky_material_path = _extract("skyMaterialPath")
        if not root_name or not scene_path:
            return None

        self.active_scene_path = scene_path
        self.active_scene_name = Path(scene_path).stem
        self.gameobjects = {}
        self.materials = {
            path: {"path": path, "shader": "Standard"}
            for path in [
                floor_material_path,
                wall_material_path,
                trim_material_path,
                accent_material_path,
                sky_material_path,
            ]
            if path
        }

        environment_name = f"{root_name}_Environment"
        player_name = f"{root_name}_Player"
        camera_name = "MainCamera"
        hud_name = f"{root_name}_HUD"

        self._register_gameobject(root_name)
        self._register_gameobject(environment_name, parent=root_name)
        self._register_gameobject(
            f"{root_name}_Floor",
            parent=environment_name,
            components=["Transform", "MeshFilter", "BoxCollider", "MeshRenderer"],
            scale={"x": 28.0, "y": 1.0, "z": 28.0},
        )
        for wall_name, position, scale in [
            (f"{root_name}_NorthWall", {"x": 0.0, "y": 2.2, "z": 14.0}, {"x": 28.0, "y": 4.4, "z": 1.0}),
            (f"{root_name}_SouthWall", {"x": 0.0, "y": 2.2, "z": -14.0}, {"x": 28.0, "y": 4.4, "z": 1.0}),
            (f"{root_name}_EastWall", {"x": 14.0, "y": 2.2, "z": 0.0}, {"x": 1.0, "y": 4.4, "z": 28.0}),
            (f"{root_name}_WestWall", {"x": -14.0, "y": 2.2, "z": 0.0}, {"x": 1.0, "y": 4.4, "z": 28.0}),
        ]:
            self._register_gameobject(
                wall_name,
                parent=environment_name,
                components=["Transform", "MeshFilter", "BoxCollider", "MeshRenderer"],
                position=position,
                scale=scale,
            )
        for prop_name in [
            f"{root_name}_LaneStrip",
            f"{root_name}_Platform",
            f"{root_name}_CoverA",
            f"{root_name}_CoverB",
            f"{root_name}_CoverC",
            f"{root_name}_ColumnNW",
            f"{root_name}_ColumnNE",
            f"{root_name}_ColumnSW",
            f"{root_name}_ColumnSE",
        ]:
            self._register_gameobject(
                prop_name,
                parent=environment_name,
                components=["Transform", "MeshFilter", "BoxCollider", "MeshRenderer"],
            )
        for beacon_name in [f"{root_name}_BeaconA", f"{root_name}_BeaconB"]:
            self._register_gameobject(beacon_name, parent=environment_name)
            self._register_gameobject(
                f"{beacon_name}_Base",
                parent=beacon_name,
                components=["Transform", "MeshFilter", "CapsuleCollider", "MeshRenderer"],
            )
            self._register_gameobject(
                f"{beacon_name}_Core",
                parent=beacon_name,
                components=["Transform", "MeshFilter", "SphereCollider", "MeshRenderer"],
            )
            self._register_gameobject(
                f"{beacon_name}_Light",
                parent=beacon_name,
                components=["Transform", "Light"],
            )

        self._register_gameobject(
            player_name,
            parent=root_name,
            components=["Transform", "CharacterController"],
            position={"x": 0.0, "y": 1.05, "z": -10.5},
        )
        self._register_gameobject(
            camera_name,
            parent=player_name,
            components=["Transform", "Camera", "AudioListener"],
            position={"x": 0.0, "y": 0.72, "z": 0.0},
        )
        self._register_gameobject(f"{root_name}_Weapon", parent=camera_name)
        self._register_gameobject(
            f"{root_name}_WeaponBody",
            parent=f"{root_name}_Weapon",
            components=["Transform", "MeshFilter", "BoxCollider", "MeshRenderer"],
        )
        self._register_gameobject(
            f"{root_name}_WeaponCore",
            parent=f"{root_name}_Weapon",
            components=["Transform", "MeshFilter", "CapsuleCollider", "MeshRenderer"],
        )
        self._register_gameobject(
            f"{root_name}_Sun",
            parent=root_name,
            components=["Transform", "Light"],
        )
        self._register_gameobject(
            hud_name,
            parent=root_name,
            components=["Transform", "RectTransform", "Canvas", "CanvasScaler", "GraphicRaycaster"],
        )
        for ui_name in [
            f"{root_name}_ObjectivePanel",
            f"{root_name}_StatusPanel",
            f"{root_name}_Reticle",
        ]:
            self._register_gameobject(
                ui_name,
                parent=hud_name,
                components=["Transform", "RectTransform"],
            )
        for ui_name in [
            f"{root_name}_ObjectiveHeader",
            f"{root_name}_ObjectiveBody",
            f"{root_name}_ObjectiveAccent",
            f"{root_name}_HealthLabel",
            f"{root_name}_AmmoLabel",
            f"{root_name}_TipLabel",
            f"{root_name}_ReticleTop",
            f"{root_name}_ReticleBottom",
            f"{root_name}_ReticleLeft",
            f"{root_name}_ReticleRight",
        ]:
            parent_name = (
                f"{root_name}_ObjectivePanel"
                if "Objective" in ui_name
                else f"{root_name}_StatusPanel"
                if any(label in ui_name for label in ["Health", "Ammo", "Tip"])
                else f"{root_name}_Reticle"
            )
            self._register_gameobject(
                ui_name,
                parent=parent_name,
                components=["Transform", "RectTransform"],
            )
        self.scene_dirty = False

        return {
            "success": True,
            "mode": "3d-fps",
            "scenePath": scene_path,
            "root": root_name,
            "player": player_name,
            "camera": camera_name,
            "hud": hud_name,
            "materials": [path for path in self.materials],
            "created": [name for name in self.gameobjects],
        }

    def _create_bird_pov_scene_from_code(self, code: str) -> dict | None:
        if "CLI_ANYTHING_BIRD_POV_SCENE" not in (code or ""):
            return None

        def _extract(name: str) -> str | None:
            match = re.search(rf'var {name} = "([^"]+)";', code or "")
            return match.group(1) if match else None

        root_name = _extract("rootName")
        scene_path = _extract("scenePath")
        controller_class_name = _extract("controllerClassName")
        pig_class_name = _extract("pigClassName")
        material_paths = [
            _extract("groundMaterialPath"),
            _extract("perchMaterialPath"),
            _extract("birdMaterialPath"),
            _extract("pigMaterialPath"),
            _extract("blockMaterialPath"),
            _extract("skyMaterialPath"),
        ]
        if not root_name or not scene_path:
            return None

        self.active_scene_path = scene_path
        self.active_scene_name = Path(scene_path).stem
        self.gameobjects = {}
        self.materials = {
            path: {"path": path, "shader": "Standard"}
            for path in material_paths
            if path
        }

        environment_name = f"{root_name}_Environment"
        bird_name = f"{root_name}_Bird"
        camera_name = "MainCamera"
        pig_name = f"{root_name}_TowerA_Pig"

        self._register_gameobject(root_name)
        self._register_gameobject(environment_name, parent=root_name)
        self._register_gameobject(
            f"{root_name}_Ground",
            parent=environment_name,
            components=["Transform", "MeshFilter", "BoxCollider", "MeshRenderer"],
        )
        self._register_gameobject(
            f"{root_name}_LaunchBase",
            parent=environment_name,
            components=["Transform", "MeshFilter", "BoxCollider", "MeshRenderer"],
        )
        self._register_gameobject(f"{root_name}_TowerA", parent=environment_name)
        self._register_gameobject(f"{root_name}_TowerB", parent=environment_name)
        self._register_gameobject(f"{root_name}_TowerC", parent=environment_name)
        self._register_gameobject(
            pig_name,
            parent=f"{root_name}_TowerA",
            components=["Transform", "MeshFilter", "SphereCollider", "MeshRenderer", "Rigidbody", pig_class_name or "PigTarget"],
            position={"x": -4.5, "y": 3.15, "z": 8.5},
        )
        self._register_gameobject(
            f"{root_name}_TowerB_Pig",
            parent=f"{root_name}_TowerB",
            components=["Transform", "MeshFilter", "SphereCollider", "MeshRenderer", "Rigidbody", pig_class_name or "PigTarget"],
            position={"x": 0.0, "y": 3.15, "z": 10.0},
        )
        self._register_gameobject(
            f"{root_name}_TowerC_Pig",
            parent=f"{root_name}_TowerC",
            components=["Transform", "MeshFilter", "SphereCollider", "MeshRenderer", "Rigidbody", pig_class_name or "PigTarget"],
            position={"x": 4.5, "y": 3.15, "z": 7.8},
        )
        self._register_gameobject(
            bird_name,
            parent=root_name,
            components=["Transform", "Rigidbody", "SphereCollider", controller_class_name or "BirdController"],
            position={"x": 0.0, "y": 1.32, "z": -12.45},
        )
        self._register_gameobject(
            camera_name,
            parent=bird_name,
            components=["Transform", "Camera", "AudioListener"],
            position={"x": 0.0, "y": 0.10, "z": 0.20},
        )
        self._register_gameobject(
            f"{root_name}_Sun",
            parent=root_name,
            components=["Transform", "Light"],
        )
        self._register_gameobject(
            f"{root_name}_FillLight",
            parent=root_name,
            components=["Transform", "Light"],
        )
        self.scene_dirty = False

        return {
            "success": True,
            "mode": "bird-pov",
            "scenePath": scene_path,
            "root": root_name,
            "bird": bird_name,
            "camera": camera_name,
            "pigs": 3,
            "materials": [path for path in self.materials],
            "created": [name for name in self.gameobjects],
        }

    @staticmethod
    def _primitive_components(primitive_type: str) -> list[str]:
        primitive = (primitive_type or "Empty").lower()
        mapping = {
            "empty": ["Transform"],
            "plane": ["Transform", "MeshFilter", "MeshCollider", "MeshRenderer"],
            "sphere": ["Transform", "MeshFilter", "SphereCollider", "MeshRenderer"],
            "capsule": ["Transform", "MeshFilter", "CapsuleCollider", "MeshRenderer"],
            "cube": ["Transform", "MeshFilter", "BoxCollider", "MeshRenderer"],
            "cylinder": ["Transform", "MeshFilter", "CapsuleCollider", "MeshRenderer"],
            "quad": ["Transform", "MeshFilter", "MeshRenderer"],
        }
        return list(mapping.get(primitive, ["Transform"]))

    def _component_properties(self, gameobject_name: str, component_type: str) -> list[dict]:
        component = self.gameobjects[gameobject_name]["component_data"].setdefault(
            component_type,
            {"Label": component_type, "Count": 1},
        )
        properties = [
            {
                "name": "Label",
                "displayName": "Label",
                "type": "String",
                "value": component["Label"],
                "editable": True,
            },
            {
                "name": "Count",
                "displayName": "Count",
                "type": "Integer",
                "value": component["Count"],
                "editable": True,
            },
        ]
        for key, value in component.items():
            if key in {"Label", "Count"}:
                continue
            properties.append(
                {
                    "name": key,
                    "displayName": key,
                    "type": "ObjectReference",
                    "value": value,
                    "editable": True,
                }
            )
        return properties

    def _gameobject_info(self, name: str) -> dict:
        go = self.gameobjects[name]
        children = self._child_names(name)
        hierarchy_path = self._hierarchy_path(name)
        position = self._vec3(go.get("position"))
        rotation = self._vec3(go.get("rotation"))
        scale = self._vec3(go.get("scale"), default=(1.0, 1.0, 1.0))
        return {
            "name": name,
            "instanceId": go["instanceId"],
            "active": True,
            "activeInHierarchy": True,
            "isStatic": False,
            "tag": "Untagged",
            "layer": "Default",
            "layerIndex": 0,
            "position": dict(position),
            "localPosition": dict(position),
            "rotation": dict(rotation),
            "localRotation": dict(rotation),
            "scale": dict(scale),
            "lossyScale": dict(scale),
            "components": [
                {"type": component_type, "fullType": component_type, "enabled": True}
                for component_type in go["components"]
            ],
            "children": children,
            "childCount": len(children),
            "parent": go.get("parent"),
            "hierarchyPath": hierarchy_path,
        }

    def route_result(self, route: str, payload: dict) -> dict:
        if route == "project/info":
            return {
                "projectName": self.project_name,
                "projectPath": self.project_path,
                "unityVersion": self.unity_version,
                "isCompiling": False,
            }
        if route == "editor/state":
            return {
                "isPlaying": self.is_playing,
                "isPlayingOrWillChangePlaymode": False,
                "activeScene": self.active_scene_name,
                "projectPath": self.project_path,
                "sceneDirty": self.scene_dirty,
            }
        if route == "scene/info":
            root_objects = [name for name, go in self.gameobjects.items() if not go.get("parent")]
            return {
                "activeScene": self.active_scene_name,
                "sceneCount": 1,
                "scenes": [
                    {
                        "name": self.active_scene_name,
                        "path": self.active_scene_path,
                        "isDirty": self.scene_dirty,
                        "isLoaded": True,
                        "rootObjectCount": len(root_objects),
                        "rootObjects": root_objects,
                        "buildIndex": 0,
                    }
                ],
            }
        if route == "scene/hierarchy":
            max_nodes = int(payload.get("maxNodes", 5000))
            hierarchy = []
            for index, (name, go) in enumerate(self.gameobjects.items()):
                if index >= max_nodes:
                    break
                hierarchy.append(
                    {
                        "name": name,
                        "instanceId": go["instanceId"],
                        "active": True,
                        "tag": "Untagged",
                        "layer": "Default",
                        "components": list(go["components"]),
                        "position": self._vec3(go.get("position")),
                        "parent": go.get("parent"),
                        "hierarchyPath": self._hierarchy_path(name),
                    }
                )
            return {
                "scene": self.active_scene_name,
                "hierarchy": hierarchy,
                "totalSceneObjects": len(self.gameobjects),
                "returnedNodes": len(hierarchy),
                "maxNodes": max_nodes,
            }
        if route == "scene/save":
            self.scene_dirty = False
            return {"success": True, "scene": self.active_scene_name, "path": self.active_scene_path}
        if route == "scene/new":
            name = str(payload.get("name") or "Untitled")
            self.active_scene_name = name
            self.active_scene_path = f"Assets/Scenes/{name}.unity"
            self.scene_dirty = False
            self.gameobjects = {}
            return {"success": True, "sceneName": name, "name": name, "path": self.active_scene_path}
        if route == "scene/open":
            path = payload.get("path") or self.active_scene_path
            discard_unsaved = bool(payload.get("discardUnsaved"))
            save_if_dirty = bool(payload.get("saveIfDirty"))
            force_reload = bool(payload.get("forceReload"))
            same_scene = path == self.active_scene_path
            if same_scene and self.scene_dirty and not discard_unsaved and not save_if_dirty and not force_reload:
                return {
                    "success": True,
                    "name": self.active_scene_name,
                    "path": self.active_scene_path,
                    "alreadyOpen": True,
                    "sceneDirty": True,
                    "requiresDecision": True,
                    "message": "Scene is already open and dirty.",
                }
            self.active_scene_path = path
            self.active_scene_name = Path(path).stem
            self.scene_dirty = False
            return {"success": True, "name": self.active_scene_name, "path": self.active_scene_path}
        if route == "asset/list":
            folder = payload.get("folder", "Assets")
            search = str(payload.get("search") or "")
            assets = []
            for path in sorted(self.scripts):
                if not path.startswith(folder):
                    continue
                if search and search.lower() not in path.lower():
                    continue
                assets.append(
                    {
                        "path": path,
                        "name": Path(path).name,
                        "type": "MonoScript",
                        "guid": f"guid-{Path(path).stem}",
                        "isFolder": False,
                    }
                )
            for path in sorted(self.prefabs):
                if not path.startswith(folder):
                    continue
                if search and search.lower() not in path.lower():
                    continue
                assets.append(
                    {
                        "path": path,
                        "name": Path(path).name,
                        "type": "GameObject",
                        "guid": f"guid-{Path(path).stem}",
                        "isFolder": False,
                    }
                )
            return {"folder": folder, "count": len(assets), "assets": assets}
        if route == "asset/delete":
            path = payload.get("path")
            deleted = path in self.scripts or path in self.prefabs
            self.scripts.pop(path, None)
            self.prefabs.pop(path, None)
            return {"success": deleted, "path": path}
        if route == "script/create":
            path = payload["path"]
            content = payload["content"]
            self.scripts[path] = content
            return {"success": True, "path": path, "size": len(content)}
        if route == "script/update":
            path = payload["path"]
            if path not in self.scripts:
                return {"error": f"File not found: {path}"}
            content = payload["content"]
            self.scripts[path] = content
            return {"success": True, "path": path, "size": len(content)}
        if route == "script/read":
            path = payload["path"]
            if path not in self.scripts:
                return {"error": f"File not found: {path}"}
            content = self.scripts[path]
            return {"path": path, "content": content, "lines": len(content.splitlines()), "size": len(content)}
        if route == "gameobject/create":
            name = str(payload.get("name") or "New GameObject")
            parent = payload.get("parent")
            primitive_type = str(payload.get("primitiveType") or "Empty")
            self.gameobjects[name] = {
                "instanceId": len(self.gameobjects) + 1,
                "components": self._primitive_components(primitive_type),
                "component_data": {},
                "position": self._vec3(payload.get("position")),
                "rotation": self._vec3(payload.get("rotation")),
                "scale": self._vec3(payload.get("scale"), default=(1.0, 1.0, 1.0)),
                "parent": parent if parent in self.gameobjects else None,
                "primitiveType": primitive_type,
            }
            self.scene_dirty = True
            return {
                "success": True,
                "name": name,
                "instanceId": self.gameobjects[name]["instanceId"],
                "parent": self.gameobjects[name]["parent"],
                "position": dict(self.gameobjects[name]["position"]),
                "rotation": dict(self.gameobjects[name]["rotation"]),
                "scale": dict(self.gameobjects[name]["scale"]),
            }
        if route == "gameobject/info":
            name = self._resolve_gameobject_name(payload)
            if name not in self.gameobjects:
                return {"error": "GameObject not found"}
            return self._gameobject_info(name)
        if route == "gameobject/delete":
            name = self._resolve_gameobject_name(payload)
            if name not in self.gameobjects:
                return {"error": "GameObject not found"}
            deleted_names = self._delete_gameobject_recursive(name)
            self.scene_dirty = True
            return {"success": True, "deleted": name, "deletedObjects": deleted_names}
        if route == "gameobject/set-transform":
            name = self._resolve_gameobject_name(payload)
            if name not in self.gameobjects:
                return {"error": "GameObject not found"}
            go = self.gameobjects[name]
            if "position" in payload:
                go["position"] = self._vec3(payload.get("position"))
            if "rotation" in payload:
                go["rotation"] = self._vec3(payload.get("rotation"))
            if "scale" in payload:
                go["scale"] = self._vec3(payload.get("scale"), default=(1.0, 1.0, 1.0))
            self.scene_dirty = True
            return {
                "success": True,
                "name": name,
                "position": dict(go["position"]),
                "rotation": dict(go["rotation"]),
                "scale": dict(go["scale"]),
            }
        if route == "component/add":
            name = self._resolve_gameobject_name(payload)
            if name not in self.gameobjects:
                return {"error": "GameObject not found"}
            component_type = str(payload.get("componentType") or "")
            if not component_type:
                return {"error": "componentType is required"}
            if component_type not in self.gameobjects[name]["components"]:
                self.gameobjects[name]["components"].append(component_type)
            self._component_properties(name, component_type)
            self.scene_dirty = True
            return {"success": True, "gameObject": name, "component": component_type, "fullType": component_type}
        if route == "component/get-properties":
            name = self._resolve_gameobject_name(payload)
            if name not in self.gameobjects:
                return {"error": "GameObject not found"}
            component_type = str(payload.get("componentType") or "")
            if component_type not in self.gameobjects[name]["components"]:
                return {"error": f"Component '{component_type}' not found on {name}"}
            return {
                "gameObject": name,
                "component": component_type,
                "properties": self._component_properties(name, component_type),
            }
        if route == "component/set-property":
            name = self._resolve_gameobject_name(payload)
            if name not in self.gameobjects:
                return {"error": "GameObject not found"}
            component_type = str(payload.get("componentType") or "")
            property_name = str(payload.get("propertyName") or "")
            if component_type not in self.gameobjects[name]["components"]:
                return {"error": f"Component '{component_type}' not found on {name}"}
            self.gameobjects[name]["component_data"].setdefault(component_type, {"Label": component_type, "Count": 1})[property_name] = payload.get("value")
            self.scene_dirty = True
            return {"success": True, "gameObject": name, "component": component_type, "property": property_name}
        if route == "component/set-reference":
            name = self._resolve_gameobject_name(payload)
            if name not in self.gameobjects:
                return {"error": "GameObject not found"}
            component_type = str(payload.get("componentType") or "")
            property_name = str(payload.get("propertyName") or "")
            if component_type not in self.gameobjects[name]["components"]:
                return {"error": f"Component '{component_type}' not found on {name}"}
            component_state = self.gameobjects[name]["component_data"].setdefault(component_type, {"Label": component_type, "Count": 1})
            if payload.get("clear"):
                component_state[property_name] = None
                return {"success": True, "gameObject": name, "property": property_name, "reference": "null (cleared)"}
            if payload.get("assetPath"):
                asset_path = str(payload["assetPath"])
                if asset_path not in self.scripts and asset_path not in self.prefabs:
                    return {"error": f"Asset not found at '{asset_path}'"}
                reference = {"name": Path(asset_path).stem, "type": "Asset", "assetPath": asset_path}
                component_state[property_name] = reference
                self.scene_dirty = True
                return {"success": True, "gameObject": name, "component": component_type, "property": property_name, "referenceName": Path(asset_path).stem, "referenceType": "Asset"}
            reference_name = self._resolve_gameobject_name({"gameObjectPath": payload.get("referenceGameObject")})
            if reference_name not in self.gameobjects:
                return {"error": f"GameObject '{reference_name}' not found in scene"}
            reference = {"name": reference_name, "type": payload.get("referenceComponentType") or "GameObject", "path": reference_name}
            component_state[property_name] = reference
            self.scene_dirty = True
            return {"success": True, "gameObject": name, "component": component_type, "property": property_name, "referenceName": reference_name, "referenceType": reference['type']}
        if route == "asset/create-prefab":
            source_name = self._resolve_gameobject_name(payload)
            if source_name not in self.gameobjects:
                return {"error": "GameObject not found"}
            save_path = str(payload.get("savePath") or "")
            if not save_path:
                return {"error": "savePath is required"}
            self.prefabs[save_path] = {
                "name": source_name,
                "components": list(self.gameobjects[source_name]["components"]),
                "component_data": self._deep_clone(self.gameobjects[source_name]["component_data"]),
                "position": self._vec3(self.gameobjects[source_name].get("position")),
                "rotation": self._vec3(self.gameobjects[source_name].get("rotation")),
                "scale": self._vec3(self.gameobjects[source_name].get("scale"), default=(1.0, 1.0, 1.0)),
                "primitiveType": self.gameobjects[source_name].get("primitiveType", "Empty"),
            }
            return {"success": True, "path": save_path, "name": source_name}
        if route == "asset/instantiate-prefab":
            prefab_path = str(payload.get("prefabPath") or "")
            if prefab_path not in self.prefabs:
                return {"error": f"Prefab not found at {prefab_path}"}
            instance_name = str(payload.get("name") or f"{self.prefabs[prefab_path]['name']}(Clone)")
            prefab = self.prefabs[prefab_path]
            parent_name = self._resolve_gameobject_name({"gameObjectPath": payload.get("parent")})
            self.gameobjects[instance_name] = {
                "instanceId": len(self.gameobjects) + 1,
                "components": list(prefab["components"]),
                "component_data": self._deep_clone(prefab["component_data"]),
                "position": self._vec3(payload.get("position"), default=(
                    prefab["position"]["x"],
                    prefab["position"]["y"],
                    prefab["position"]["z"],
                )),
                "rotation": self._vec3(payload.get("rotation"), default=(
                    prefab["rotation"]["x"],
                    prefab["rotation"]["y"],
                    prefab["rotation"]["z"],
                )),
                "scale": self._vec3(payload.get("scale"), default=(
                    prefab["scale"]["x"],
                    prefab["scale"]["y"],
                    prefab["scale"]["z"],
                )),
                "parent": parent_name if parent_name in self.gameobjects else None,
                "primitiveType": prefab.get("primitiveType", "Empty"),
            }
            self.scene_dirty = True
            return {
                "success": True,
                "name": instance_name,
                "instanceId": self.gameobjects[instance_name]["instanceId"],
                "parent": self.gameobjects[instance_name]["parent"],
                "position": dict(self.gameobjects[instance_name]["position"]),
            }
        if route == "search/missing-references":
            limit = int(payload.get("limit", 50))
            results = self.missing_references[:limit]
            response = {
                "scope": "scene",
                "totalFound": len(self.missing_references),
                "returned": len(results),
                "limit": limit,
                "results": results,
            }
            if len(self.missing_references) > limit:
                response["truncated"] = True
            return response
        if route == "console/log":
            requested_type = str(payload.get("type") or "all").lower()
            limit = int(payload.get("count", 20))
            entries = [
                {
                    "message": "Sample info log",
                    "type": "info",
                    "timestamp": "00:00:01.000",
                    "stackTrace": "",
                },
                {
                    "message": "Sample warning log",
                    "type": "warning",
                    "timestamp": "00:00:02.000",
                    "stackTrace": "",
                },
                {
                    "message": "Sample error log",
                    "type": "error",
                    "timestamp": "00:00:03.000",
                    "stackTrace": "Example.StackTrace()",
                },
            ]
            if requested_type != "all":
                entries = [entry for entry in entries if entry["type"] == requested_type]
            entries = entries[:limit]
            return {
                "count": len(entries),
                "entries": entries,
            }
        if route in {"scene/stats", "search/scene-stats"}:
            total_components = sum(len(go["components"]) for go in self.gameobjects.values())
            component_counts: dict[str, int] = {}
            for go in self.gameobjects.values():
                for component in go["components"]:
                    component_counts[component] = component_counts.get(component, 0) + 1
            return {
                "sceneName": self.active_scene_name,
                "totalGameObjects": len(self.gameobjects),
                "totalComponents": total_components,
                "totalMeshes": 0,
                "totalVertices": 0,
                "totalTriangles": 0,
                "totalLights": 0,
                "totalCameras": 0,
                "totalColliders": 0,
                "totalRigidbodies": 0,
                "topComponents": [
                    {"type": component, "count": count}
                    for component, count in sorted(component_counts.items())
                ],
            }
        if route == "profiler/memory-status":
            return {
                "memoryProfilerPackageInstalled": False,
                "availableCommands": [
                    "profiler/memory-status",
                    "profiler/memory-breakdown",
                    "profiler/memory-top-assets",
                ],
                "quickSummary": {
                    "totalAllocatedMB": 256.0,
                    "totalReservedMB": 320.0,
                    "gfxDriverMB": 32.0,
                },
            }
        if route == "graphics/lighting-summary":
            lights = [
                {"name": name, "type": "Directional", "intensity": 1.0}
                for name, go in self.gameobjects.items()
                if "Light" in go["components"] or name.lower().startswith("light")
            ]
            return {"lightCount": len(lights), "lights": lights}
        if route == "sceneview/info":
            return {
                "pivot": {"x": 0.0, "y": 0.0, "z": 0.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "size": 10.0,
                "orthographic": True,
                "is2D": True,
                "drawGizmos": True,
            }
        if route == "settings/quality":
            return {
                "currentLevel": 0,
                "currentName": "Very Low",
                "levels": [
                    {"index": 0, "name": "Very Low", "isCurrent": True},
                    {"index": 1, "name": "Low", "isCurrent": False},
                ],
                "pixelLightCount": 0,
                "shadows": "Disable",
                "antiAliasing": 0,
                "vSyncCount": 0,
                "lodBias": 0.3,
            }
        if route == "settings/time":
            return {
                "timeScale": 1.0,
                "fixedDeltaTime": 0.02,
                "maximumDeltaTime": 0.3333333,
            }
        if route == "graphics/game-capture":
            return {
                "success": True,
                "base64": PNG_1X1_BASE64,
                "width": int(payload.get("width") or 512),
                "height": int(payload.get("height") or 512),
                "cameraName": "Main Camera",
            }
        if route == "graphics/scene-capture":
            return {
                "success": True,
                "base64": PNG_1X1_BASE64,
                "width": int(payload.get("width") or 512),
                "height": int(payload.get("height") or 512),
            }
        if route == "profiler/stats":
            mesh_objects = sum(1 for go in self.gameobjects.values() if "MeshRenderer" in go["components"])
            return {
                "drawCalls": mesh_objects,
                "batches": mesh_objects,
                "triangles": mesh_objects * 128,
                "vertices": mesh_objects * 256,
                "setPassCalls": mesh_objects,
                "frameTimeMs": 16.6,
            }
        # ── Profiler additional routes ────────────────────────────────────
        if route == "profiler/enable":
            enabled = bool(payload.get("enabled", True))
            return {"success": True, "enabled": enabled}
        if route == "profiler/analyze":
            return {"success": True, "frames": 60, "avgFrameTimeMs": 16.6, "peakFrameTimeMs": 33.2, "bottleneck": "Rendering"}
        if route == "profiler/frame-data":
            frame = int(payload.get("frame") or 0)
            return {"frame": frame, "frameTimeMs": 16.6, "renderTimeMs": 8.2, "scriptTimeMs": 2.1, "physicsTimeMs": 1.0}
        if route == "profiler/memory":
            return {"totalMB": 256.0, "usedMB": 128.0, "reservedMB": 200.0, "gcAllocMB": 0.5}
        if route == "profiler/memory-breakdown":
            return {"totalMB": 256.0, "textures": 64.0, "meshes": 32.0, "scripts": 12.0, "audio": 8.0, "other": 140.0}
        if route == "profiler/memory-snapshot":
            return {"success": True, "snapshotPath": "Temp/MemorySnapshot.snap", "totalMB": 256.0}
        if route == "profiler/memory-top-assets":
            return {"count": 3, "assets": [{"name": "MainTexture", "sizeMB": 32.0, "type": "Texture2D"}, {"name": "MainMesh", "sizeMB": 12.0, "type": "Mesh"}, {"name": "AudioClip", "sizeMB": 8.0, "type": "AudioClip"}]}
        # ── Debugger routes ──────────────────────────────────────────────
        if route == "debugger/enable":
            enabled = bool(payload.get("enabled", True))
            return {"success": True, "enabled": enabled}
        if route == "debugger/events":
            limit = int(payload.get("limit") or 20)
            return {"count": 0, "events": [], "limit": limit}
        if route == "debugger/event-details":
            event_id = str(payload.get("eventId") or "")
            return {"eventId": event_id, "details": {}, "stackTrace": ""}
        # ── EditorPrefs routes ───────────────────────────────────────────
        if route == "editorprefs/get":
            key = str(payload.get("key") or "")
            return {"key": key, "value": self._editorprefs.get(key), "exists": key in self._editorprefs}
        if route == "editorprefs/set":
            key = str(payload.get("key") or "")
            value = payload.get("value")
            self._editorprefs[key] = value
            return {"success": True, "key": key, "value": value}
        if route == "editorprefs/delete":
            key = str(payload.get("key") or "")
            existed = key in self._editorprefs
            self._editorprefs.pop(key, None)
            return {"success": True, "key": key, "deleted": existed}
        # ── Audio additional routes ──────────────────────────────────────
        if route == "audio/create-source":
            go_path = str(payload.get("gameObjectPath") or "")
            clip_path = str(payload.get("clipPath") or "")
            self.gameobjects.setdefault(go_path, {"name": go_path, "components": []}).setdefault("components", [])
            if "AudioSource" not in self.gameobjects[go_path]["components"]:
                self.gameobjects[go_path]["components"].append("AudioSource")
            return {"success": True, "gameObjectPath": go_path, "clipPath": clip_path}
        if route == "audio/set-global":
            return {"success": True, "volume": float(payload.get("volume", 1.0)), "pause": bool(payload.get("pause", False))}
        # ── Console clear route ──────────────────────────────────────────
        if route == "console/clear":
            return {"success": True}
        # ── Screenshot routes ────────────────────────────────────────────
        if route == "screenshot/game":
            path = str(payload.get("path") or "Temp/screenshot_game.png")
            return {"success": True, "path": path, "width": int(payload.get("width") or 1920), "height": int(payload.get("height") or 1080)}
        if route == "screenshot/scene":
            path = str(payload.get("path") or "Temp/screenshot_scene.png")
            return {"success": True, "path": path, "width": int(payload.get("width") or 1920), "height": int(payload.get("height") or 1080)}
        # ── Testing additional routes ────────────────────────────────────
        if route == "testing/run-tests":
            mode = str(payload.get("mode") or "EditMode")
            job_id = f"test-job-{mode.lower()}-001"
            return {"success": True, "jobId": job_id, "mode": mode, "status": "Running"}
        if route == "testing/get-job":
            job_id = str(payload.get("jobId") or "")
            return {"jobId": job_id, "status": "Completed", "passed": 1, "failed": 0, "skipped": 0, "results": []}
        # ── Undo additional routes ───────────────────────────────────────
        if route == "undo/clear":
            return {"success": True}
        if route == "undo/history":
            return {"count": 0, "entries": []}
        if route == "undo/redo":
            return {"success": True}
        # ── VFX routes ───────────────────────────────────────────────────
        if route == "shadergraph/list-vfx":
            return {"count": 0, "vfxGraphs": []}
        if route == "shadergraph/open-vfx":
            path = str(payload.get("path") or "")
            return {"success": True, "path": path}
        # ── Component additional routes ──────────────────────────────────
        if route == "component/get-referenceable":
            go_path = str(payload.get("gameObjectPath") or "")
            component = str(payload.get("component") or "")
            return {"gameObjectPath": go_path, "component": component, "referenceableFields": [{"name": "target", "type": "Transform"}, {"name": "renderer", "type": "Renderer"}]}
        if route == "component/batch-wire":
            pairs = payload.get("pairs") or []
            return {"success": True, "wired": len(pairs), "failed": 0}
        if route == "component/remove":
            go_path = str(payload.get("gameObjectPath") or payload.get("objectPath") or "")
            component = str(payload.get("component") or "")
            comps = self.gameobjects.get(go_path, {}).get("components", [])
            removed = component in comps
            if removed:
                comps.remove(component)
            self.scene_dirty = True
            return {"success": True, "gameObjectPath": go_path, "component": component, "removed": removed}
        # ── GameObject additional routes ─────────────────────────────────
        if route == "prefab/duplicate":
            go_path = str(payload.get("gameObjectPath") or payload.get("path") or "")
            new_name = str(payload.get("name") or f"{go_path}_Copy")
            original = self.gameobjects.get(go_path, {})
            self.gameobjects[new_name] = {**original, "name": new_name}
            self.scene_dirty = True
            return {"success": True, "originalPath": go_path, "duplicatePath": new_name}
        if route == "prefab/reparent":
            go_path = str(payload.get("gameObjectPath") or payload.get("path") or "")
            parent_path = payload.get("parentPath")
            self.scene_dirty = True
            return {"success": True, "gameObjectPath": go_path, "parentPath": parent_path}
        if route == "prefab/set-active":
            go_path = str(payload.get("gameObjectPath") or payload.get("path") or "")
            active = bool(payload.get("active", True))
            if go_path in self.gameobjects:
                self.gameobjects[go_path]["active"] = active
            self.scene_dirty = True
            return {"success": True, "gameObjectPath": go_path, "active": active}
        if route == "prefab/set-object-reference":
            go_path = str(payload.get("gameObjectPath") or "")
            component = str(payload.get("component") or "")
            prop = str(payload.get("propertyName") or "")
            ref_path = payload.get("referencePath")
            return {"success": True, "gameObjectPath": go_path, "component": component, "propertyName": prop, "referencePath": ref_path}
        # ── Asset additional routes ──────────────────────────────────────
        if route == "asset/import":
            asset_path = str(payload.get("path") or "")
            return {"success": True, "path": asset_path, "importedAt": "2026-04-10T00:00:00Z"}
        if route == "asset/create-material":
            path = str(payload.get("path") or "Assets/Materials/NewMaterial.mat")
            shader = str(payload.get("shader") or "Standard")
            self.materials[path] = {"path": path, "shader": shader}
            return {"success": True, "path": path, "shader": shader}
        # ── Build route ──────────────────────────────────────────────────
        if route == "build/start":
            target = str(payload.get("target") or "StandaloneWindows64")
            return {"success": True, "target": target, "buildPath": str(payload.get("buildPath") or f"Builds/{target}"), "status": "Started"}
        # ── Ping ─────────────────────────────────────────────────────────
        if route == "ping":
            return {"status": "ok", "unityVersion": "6000.4.0f1", "projectName": "Demo", "port": self.port}
        # ── Execute menu item ────────────────────────────────────────────
        if route == "editor/execute-menu-item":
            menu_item = str(payload.get("menuItem") or "")
            return {"success": True, "menuItem": menu_item}
        # ── Renderer set-material ────────────────────────────────────────
        if route == "renderer/set-material":
            go_path = str(payload.get("gameObjectPath") or payload.get("objectPath") or "")
            mat_path = str(payload.get("materialPath") or "")
            return {"success": True, "gameObjectPath": go_path, "materialPath": mat_path}
        # ── SceneView set-camera ─────────────────────────────────────────
        if route == "sceneview/set-camera":
            return {"success": True, "position": payload.get("position", {"x": 0, "y": 0, "z": -10}), "rotation": payload.get("rotation", {"x": 0, "y": 0, "z": 0, "w": 1})}
        # ── Context ──────────────────────────────────────────────────────
        if route == "context":
            return {"projectPath": "C:/Projects/Demo", "unityVersion": "6000.4.0f1", "platform": "StandaloneWindows64", "renderPipeline": "UniversalRP"}
        # ── MPPM / scenario routes ───────────────────────────────────────
        if route == "scenario/info":
            return {
                "available": True,
                "package": "Unity Multiplayer Play Mode",
                "scenarioCount": len(self._mppm["scenarios"]),
                "activeScenario": self._mppm["activeScenario"],
            }
        if route == "scenario/list":
            return {
                "count": len(self._mppm["scenarios"]),
                "scenarios": self._deep_clone(self._mppm["scenarios"]),
                "activeScenario": self._mppm["activeScenario"],
            }
        if route == "scenario/status":
            active_path = self._mppm["activeScenario"]
            active = next((item for item in self._mppm["scenarios"] if item["path"] == active_path), None)
            return {
                "running": self._mppm["running"],
                "activeScenario": active_path,
                "playerCount": active["playerCount"] if active else 0,
            }
        if route == "scenario/activate":
            scenario_path = str(payload.get("path") or self._mppm["scenarios"][0]["path"])
            if not any(item["path"] == scenario_path for item in self._mppm["scenarios"]):
                self._mppm["scenarios"].append(
                    {
                        "path": scenario_path,
                        "name": Path(scenario_path).stem,
                        "playerCount": int(payload.get("playerCount", 2)),
                    }
                )
            self._mppm["activeScenario"] = scenario_path
            return {"success": True, "activeScenario": scenario_path}
        if route == "scenario/start":
            if not self._mppm["activeScenario"]:
                self._mppm["activeScenario"] = self._mppm["scenarios"][0]["path"]
            self._mppm["running"] = True
            return {"success": True, "running": True, "activeScenario": self._mppm["activeScenario"]}
        if route == "scenario/stop":
            self._mppm["running"] = False
            return {"success": True, "running": False, "activeScenario": self._mppm["activeScenario"]}
        if route == "testing/list-tests":
            mode = str(payload.get("mode") or "EditMode")
            return {
                "mode": mode,
                "count": 1,
                "tests": [
                    {
                        "name": f"Example{mode}Test",
                        "fullName": f"Demo.Tests.Example{mode}Test",
                        "category": mode,
                    }
                ],
            }
        if route == "graphics/renderer-info":
            name = self._resolve_gameobject_name(payload)
            if name not in self.gameobjects:
                return {"error": "GameObject not found"}
            if "MeshRenderer" not in self.gameobjects[name]["components"]:
                return {"error": "Renderer not found"}
            return {
                "objectPath": self._hierarchy_path(name),
                "rendererType": "MeshRenderer",
                "materials": [{"name": "Default-Material", "shader": "Standard"}],
                "mesh": {"name": f"{name}Mesh"},
                "bounds": {"center": self._vec3(), "size": self._vec3(default=(1.0, 1.0, 1.0))},
            }
        if route == "graphics/mesh-info":
            name = self._resolve_gameobject_name(payload)
            if name and name in self.gameobjects:
                return {
                    "objectPath": self._hierarchy_path(name),
                    "meshName": f"{name}Mesh",
                    "vertexCount": 256,
                    "triangleCount": 128,
                    "subMeshCount": 1,
                }
            asset_path = payload.get("assetPath")
            if asset_path:
                return {
                    "assetPath": asset_path,
                    "meshName": Path(str(asset_path)).stem,
                    "vertexCount": 256,
                    "triangleCount": 128,
                    "subMeshCount": 1,
                }
            return {"error": "objectPath or assetPath is required"}
        if route == "graphics/material-info":
            name = self._resolve_gameobject_name(payload)
            if name and name in self.gameobjects:
                return {
                    "objectPath": self._hierarchy_path(name),
                    "materialName": "Default-Material",
                    "shaderName": "Standard",
                    "renderQueue": 2000,
                    "keywords": [],
                }
            asset_path = payload.get("assetPath")
            if asset_path:
                return {
                    "assetPath": asset_path,
                    "materialName": Path(str(asset_path)).stem,
                    "shaderName": self.materials.get(str(asset_path), {}).get("shader", "Standard"),
                    "renderQueue": 2000,
                    "keywords": [],
                }
            return {"error": "objectPath or assetPath is required"}
        if route == "physics/raycast":
            origin = self._vec3(payload.get("origin"))
            direction = self._vec3(payload.get("direction"), default=(0.0, -1.0, 0.0))
            hit_name = next(
                (
                    name
                    for name, go in self.gameobjects.items()
                    if "Collider" in " ".join(go["components"])
                ),
                None,
            )
            if hit_name is None:
                return {"hit": False}
            return {
                "hit": True,
                "objectName": hit_name,
                "distance": 1.0,
                "point": {"x": origin["x"], "y": origin["y"] - 1.0, "z": origin["z"]},
                "normal": {"x": -direction["x"], "y": -direction["y"], "z": -direction["z"]},
            }
        if route == "ui/create-canvas":
            name = str(payload.get("name") or "Canvas")
            self._register_gameobject(name, components=["Transform", "Canvas", "CanvasScaler", "GraphicRaycaster"])
            self.ui_elements[name] = {"type": "canvas", "renderMode": payload.get("renderMode", "overlay")}
            self.scene_dirty = True
            return {"success": True, "name": name, "path": name, "type": "canvas"}
        if route == "ui/create-element":
            element_type = str(payload.get("type") or "text").lower()
            name = str(payload.get("name") or f"{element_type.title()}Element")
            parent = str(payload.get("parent") or "")
            if not parent:
                parent = next((key for key, value in self.ui_elements.items() if value.get("type") == "canvas"), "")
            components_by_type = {
                "text": ["Transform", "RectTransform", "Text"],
                "image": ["Transform", "RectTransform", "Image"],
                "button": ["Transform", "RectTransform", "Button", "Image"],
                "panel": ["Transform", "RectTransform", "Image"],
            }
            self._register_gameobject(
                name,
                parent=parent if parent in self.gameobjects else None,
                components=components_by_type.get(element_type, ["Transform", "RectTransform"]),
            )
            self.ui_elements[name] = {
                "type": element_type,
                "parent": parent,
                "text": payload.get("label", ""),
                "anchoredPosition": self._deep_clone(payload.get("anchoredPosition")) or {"x": 0, "y": 0},
                "sizeDelta": self._deep_clone(payload.get("sizeDelta")) or {"x": 160, "y": 40},
            }
            self.scene_dirty = True
            return {"success": True, "name": name, "path": self._hierarchy_path(name), "type": element_type}
        if route == "ui/set-text":
            path = str(payload.get("path") or "")
            name = path.split("/")[-1]
            if name not in self.ui_elements:
                return {"error": "UI text element not found"}
            self.ui_elements[name].update({
                "text": payload.get("text", ""),
                "fontSize": payload.get("fontSize"),
                "alignment": payload.get("alignment"),
                "color": self._deep_clone(payload.get("color")),
            })
            self.scene_dirty = True
            return {"success": True, "path": path, "text": self.ui_elements[name]["text"]}
        if route == "ui/set-image":
            path = str(payload.get("path") or "")
            name = path.split("/")[-1]
            if name not in self.ui_elements:
                return {"error": "UI image element not found"}
            self.ui_elements[name].update({
                "color": self._deep_clone(payload.get("color")),
                "sprite": payload.get("sprite"),
                "imageType": payload.get("imageType"),
                "raycastTarget": payload.get("raycastTarget"),
            })
            self.scene_dirty = True
            return {"success": True, "path": path, "image": self.ui_elements[name]}
        if route == "ui/info":
            return {
                "canvasCount": sum(1 for item in self.ui_elements.values() if item.get("type") == "canvas"),
                "elementCount": sum(1 for item in self.ui_elements.values() if item.get("type") != "canvas"),
                "elements": self._deep_clone(self.ui_elements),
            }
        if route == "lighting/create-light-probe-group":
            name = str(payload.get("name") or "LightProbeGroup")
            self._register_gameobject(name, components=["Transform", "LightProbeGroup"], position=payload.get("position"))
            self.scene_dirty = True
            return {"success": True, "name": name, "probeCount": 4}
        if route == "lighting/create-reflection-probe":
            name = str(payload.get("name") or "ReflectionProbe")
            self._register_gameobject(name, components=["Transform", "ReflectionProbe"], position=payload.get("position"))
            return {
                "success": True,
                "name": name,
                "size": self._deep_clone(payload.get("size")) or {"x": 10, "y": 10, "z": 10},
                "resolution": int(payload.get("resolution") or 128),
                "mode": payload.get("mode") or "Baked",
            }
        if route == "lighting/set-environment":
            self.lighting_environment.update(self._deep_clone(payload) or {})
            self.scene_dirty = True
            return {"success": True, "environment": dict(self.lighting_environment)}
        if route == "animation/create-clip":
            path = str(payload.get("path") or "Assets/Clip.anim")
            self.animation_clips[path] = {
                "path": path,
                "loop": bool(payload.get("loop")),
                "frameRate": float(payload.get("frameRate") or 60),
                "events": [],
                "curves": {},
            }
            return {"success": True, "path": path}
        if route == "animation/create-controller":
            path = str(payload.get("path") or "Assets/Controller.controller")
            self.animation_controllers[path] = {"path": path, "parameters": [], "transitions": [], "states": []}
            return {"success": True, "path": path}
        if route == "animation/set-clip-curve":
            clip_path = str(payload.get("clipPath") or "")
            if clip_path not in self.animation_clips:
                self.animation_clips[clip_path] = {"path": clip_path, "events": [], "curves": {}}
            property_name = str(payload.get("propertyName") or "")
            type_name = str(payload.get("type") or payload.get("typeName") or "Transform")
            self.animation_clips[clip_path].setdefault("curves", {})[f"{type_name}:{property_name}"] = list(payload.get("keyframes") or [])
            return {"success": True, "clipPath": clip_path, "propertyName": property_name}
        if route == "animation/add-event":
            clip_path = str(payload.get("clipPath") or "")
            if clip_path not in self.animation_clips:
                return {"error": "Animation clip not found"}
            event = {
                "functionName": payload.get("functionName"),
                "time": float(payload.get("time") or 0),
                "stringParameter": payload.get("stringParameter"),
                "intParameter": payload.get("intParameter"),
                "floatParameter": payload.get("floatParameter"),
            }
            self.animation_clips[clip_path].setdefault("events", []).append(event)
            return {"success": True, "clipPath": clip_path, "event": event}
        if route == "animation/get-events":
            clip_path = str(payload.get("clipPath") or "")
            return {"clipPath": clip_path, "events": list(self.animation_clips.get(clip_path, {}).get("events", []))}
        if route == "animation/get-curve-keyframes":
            clip_path = str(payload.get("clipPath") or "")
            property_name = str(payload.get("propertyName") or "")
            type_name = str(payload.get("typeName") or payload.get("type") or "Transform")
            keyframes = self.animation_clips.get(clip_path, {}).get("curves", {}).get(f"{type_name}:{property_name}", [])
            return {"clipPath": clip_path, "propertyName": property_name, "typeName": type_name, "keyframes": list(keyframes)}
        if route == "animation/clip-info":
            path = str(payload.get("path") or "")
            clip = self.animation_clips.get(path)
            if not clip:
                return {"error": "Animation clip not found"}
            return {
                "path": path,
                "frameRate": clip.get("frameRate", 60),
                "loop": bool(clip.get("loop")),
                "eventCount": len(clip.get("events", [])),
                "curveCount": len(clip.get("curves", {})),
            }
        if route == "animation/add-parameter":
            controller_path = str(payload.get("controllerPath") or "")
            controller = self.animation_controllers.setdefault(controller_path, {"path": controller_path, "parameters": [], "transitions": [], "states": []})
            parameter = {
                "name": payload.get("parameterName"),
                "type": payload.get("parameterType"),
                "defaultValue": payload.get("defaultValue"),
            }
            controller.setdefault("parameters", []).append(parameter)
            return {"success": True, "controllerPath": controller_path, "parameter": parameter}
        if route == "animation/add-transition":
            controller_path = str(payload.get("controllerPath") or "")
            controller = self.animation_controllers.setdefault(controller_path, {"path": controller_path, "parameters": [], "transitions": [], "states": []})
            transition = {
                "sourceState": payload.get("sourceState"),
                "destinationState": payload.get("destinationState"),
                "duration": payload.get("duration"),
                "conditions": self._deep_clone(payload.get("conditions")) or [],
            }
            controller.setdefault("transitions", []).append(transition)
            return {"success": True, "controllerPath": controller_path, "transition": transition}
        if route == "terrain/create":
            name = str(payload.get("name") or "Terrain")
            self._register_gameobject(name, components=["Transform", "Terrain", "TerrainCollider"], position=payload.get("position"))
            self.terrains[name] = {
                "name": name,
                "width": float(payload.get("width") or 128),
                "length": float(payload.get("length") or 128),
                "height": float(payload.get("height") or 60),
                "trees": [],
            }
            self.scene_dirty = True
            return {"success": True, "name": name, "dataPath": payload.get("dataPath")}
        if route == "terrain/list":
            return {"count": len(self.terrains), "terrains": list(self.terrains.values())}
        if route == "terrain/get-heights-region":
            width = int(payload.get("width") or 1)
            height = int(payload.get("height") or 1)
            return {"width": width, "height": height, "heights": [[0.0 for _ in range(width)] for _ in range(height)]}
        if route == "terrain/get-steepness":
            return {"worldX": float(payload.get("worldX") or 0), "worldZ": float(payload.get("worldZ") or 0), "steepness": 0.0}
        if route == "terrain/get-tree-instances":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            limit = int(payload.get("limit") or 20)
            trees = list(self.terrains.get(name, {}).get("trees", []))[:limit]
            return {"name": name, "count": len(trees), "trees": trees}
        # ── Terrain mutation routes ──────────────────────────────────────
        if route == "terrain/set-settings":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            if name in self.terrains:
                for k in ("width", "length", "height", "heightmapResolution", "detailResolution"):
                    if k in payload:
                        self.terrains[name][k] = payload[k]
            self.scene_dirty = True
            return {"success": True, "name": name}
        if route == "terrain/set-height":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            self.scene_dirty = True
            return {"success": True, "name": name, "worldX": payload.get("worldX", 0), "worldZ": payload.get("worldZ", 0), "height": payload.get("height", 0)}
        if route == "terrain/set-heights-region":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            self.scene_dirty = True
            heights = payload.get("heights") or [[0.0]]
            return {"success": True, "name": name, "samplesWritten": len(heights) * len(heights[0]) if heights and isinstance(heights[0], list) else 0}
        if route == "terrain/raise-lower":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            self.scene_dirty = True
            return {"success": True, "name": name, "worldX": payload.get("worldX", 0), "worldZ": payload.get("worldZ", 0)}
        if route == "terrain/flatten":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            self.scene_dirty = True
            return {"success": True, "name": name, "height": float(payload.get("height") or 0)}
        if route == "terrain/smooth":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            self.scene_dirty = True
            return {"success": True, "name": name, "passes": int(payload.get("passes") or 1)}
        if route == "terrain/noise":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            self.scene_dirty = True
            return {"success": True, "name": name, "scale": float(payload.get("scale") or 1.0)}
        if route == "terrain/add-layer":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            layer = {"texturePath": str(payload.get("texturePath") or ""), "index": len(self.terrains.get(name, {}).get("layers", []))}
            self.terrains.setdefault(name, {"name": name}).setdefault("layers", []).append(layer)
            self.scene_dirty = True
            return {"success": True, "name": name, "layerIndex": layer["index"]}
        if route == "terrain/remove-layer":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            idx = int(payload.get("layerIndex") or 0)
            layers = self.terrains.get(name, {}).get("layers", [])
            removed = layers.pop(idx) if idx < len(layers) else None
            self.scene_dirty = True
            return {"success": True, "name": name, "removed": removed is not None}
        if route == "terrain/fill-layer":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            self.scene_dirty = True
            return {"success": True, "name": name, "layerIndex": int(payload.get("layerIndex") or 0)}
        if route == "terrain/paint-layer":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            self.scene_dirty = True
            return {"success": True, "name": name, "worldX": payload.get("worldX", 0), "worldZ": payload.get("worldZ", 0), "layerIndex": payload.get("layerIndex", 0)}
        if route == "terrain/add-detail-prototype":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            idx = len(self.terrains.get(name, {}).get("details", []))
            self.terrains.setdefault(name, {"name": name}).setdefault("details", []).append({"texturePath": payload.get("texturePath"), "index": idx})
            self.scene_dirty = True
            return {"success": True, "name": name, "prototypeIndex": idx}
        if route == "terrain/add-tree-prototype":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            idx = len(self.terrains.get(name, {}).get("treePrototypes", []))
            self.terrains.setdefault(name, {"name": name}).setdefault("treePrototypes", []).append({"prefabPath": str(payload.get("prefabPath") or ""), "index": idx})
            self.scene_dirty = True
            return {"success": True, "name": name, "prototypeIndex": idx}
        if route == "terrain/remove-tree-prototype":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            idx = int(payload.get("prototypeIndex") or 0)
            protos = self.terrains.get(name, {}).get("treePrototypes", [])
            removed = protos.pop(idx) if idx < len(protos) else None
            self.scene_dirty = True
            return {"success": True, "name": name, "removed": removed is not None}
        if route == "terrain/place-trees":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            count = int(payload.get("count") or 1)
            placed = [{"prototypeIndex": 0, "worldX": i * 5.0, "worldZ": 0.0} for i in range(count)]
            self.terrains.setdefault(name, {"name": name}).setdefault("trees", []).extend(placed)
            self.scene_dirty = True
            return {"success": True, "name": name, "treesPlaced": count}
        if route == "terrain/clear-trees":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            removed_count = len(self.terrains.get(name, {}).get("trees", []))
            self.terrains.setdefault(name, {"name": name})["trees"] = []
            self.scene_dirty = True
            return {"success": True, "name": name, "treesRemoved": removed_count}
        if route == "terrain/paint-detail":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            self.scene_dirty = True
            return {"success": True, "name": name, "worldX": payload.get("worldX", 0), "worldZ": payload.get("worldZ", 0)}
        if route == "terrain/scatter-detail":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            count = int(payload.get("count") or 10)
            self.scene_dirty = True
            return {"success": True, "name": name, "detailsPlaced": count}
        if route == "terrain/clear-detail":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            self.scene_dirty = True
            return {"success": True, "name": name, "prototypeIndex": payload.get("prototypeIndex", 0)}
        if route == "terrain/set-neighbors":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            self.scene_dirty = True
            return {"success": True, "name": name, "neighborsSet": sum(1 for k in ("left", "right", "top", "bottom") if payload.get(k))}
        if route == "terrain/set-holes":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            self.scene_dirty = True
            holes = payload.get("holes") or []
            return {"success": True, "name": name, "holesSet": len(holes)}
        if route == "terrain/resize":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            if name in self.terrains:
                if "width" in payload:
                    self.terrains[name]["width"] = float(payload["width"])
                if "length" in payload:
                    self.terrains[name]["length"] = float(payload["length"])
                if "height" in payload:
                    self.terrains[name]["height"] = float(payload["height"])
            self.scene_dirty = True
            return {"success": True, "name": name}
        if route == "terrain/create-grid":
            count_x = int(payload.get("countX") or 2)
            count_z = int(payload.get("countZ") or 2)
            created = []
            for xi in range(count_x):
                for zi in range(count_z):
                    gname = f"Terrain_{xi}_{zi}"
                    self.terrains[gname] = {"name": gname, "width": float(payload.get("width") or 128), "length": float(payload.get("length") or 128), "height": float(payload.get("height") or 60), "trees": []}
                    created.append(gname)
            self.scene_dirty = True
            return {"success": True, "count": len(created), "terrains": created}
        if route == "terrain/export-heightmap":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            out_path = str(payload.get("outputPath") or f"Assets/{name}_heightmap.png")
            return {"success": True, "name": name, "outputPath": out_path, "format": payload.get("format", "PNG")}
        if route == "terrain/import-heightmap":
            name = str(payload.get("name") or next(iter(self.terrains), ""))
            self.scene_dirty = True
            return {"success": True, "name": name, "imagePath": str(payload.get("imagePath") or "")}
        # ── Search routes (read-only) ────────────────────────────────────
        if route == "search/assets":
            query = str(payload.get("query") or payload.get("searchPattern") or "")
            sampled = [a for a in self.scripts if query.lower() in a.lower()] if query else list(self.scripts.keys())[:10]
            return {"query": query, "count": len(sampled), "results": [{"path": p, "type": "Script"} for p in sampled[:20]]}
        if route == "search/by-component":
            component = str(payload.get("component") or payload.get("componentType") or "")
            matches = [{"path": k, "components": [component]} for k in self.gameobjects if component in self.gameobjects[k].get("components", [])]
            return {"component": component, "count": len(matches), "results": matches}
        if route == "search/by-layer":
            layer = str(payload.get("layer") or payload.get("layerName") or "Default")
            matches = [{"path": k} for k in self.gameobjects]
            return {"layer": layer, "count": len(matches), "results": matches[:20]}
        if route == "search/by-name":
            name = str(payload.get("name") or payload.get("pattern") or "")
            matches = [{"path": k} for k in self.gameobjects if name.lower() in k.lower()]
            return {"name": name, "count": len(matches), "results": matches}
        if route == "search/by-shader":
            shader = str(payload.get("shader") or payload.get("shaderName") or "")
            return {"shader": shader, "count": 0, "results": []}
        if route == "search/by-tag":
            tag = str(payload.get("tag") or "Untagged")
            matches = [{"path": k} for k in self.gameobjects]
            return {"tag": tag, "count": len(matches), "results": matches[:20]}
        # ── Shader / ShaderGraph routes ──────────────────────────────────
        if route == "shadergraph/list-shaders":
            return {"count": 2, "shaders": [{"name": "Standard", "path": "Packages/com.unity.render-pipelines.universal/Shaders/Lit.shader"}, {"name": "Unlit", "path": "Packages/com.unity.render-pipelines.universal/Shaders/Unlit.shader"}]}
        if route == "shadergraph/get-properties":
            path = str(payload.get("shaderPath") or payload.get("path") or "")
            return {"path": path, "properties": [{"name": "_Color", "type": "Color", "defaultValue": [1, 1, 1, 1]}, {"name": "_MainTex", "type": "Texture2D"}]}
        if route == "shadergraph/get-node-types":
            return {"count": 3, "nodeTypes": [{"type": "AddNode", "category": "Math"}, {"type": "MultiplyNode", "category": "Math"}, {"type": "SampleTexture2DNode", "category": "Texture"}]}
        if route == "shadergraph/get-nodes":
            path = str(payload.get("path") or "")
            sg = self._shadergraphs.get(path, {})
            nodes = sg.get("nodes", [])
            return {"path": path, "count": len(nodes), "nodes": nodes}
        if route == "shadergraph/get-edges":
            path = str(payload.get("path") or "")
            sg = self._shadergraphs.get(path, {})
            edges = sg.get("edges", [])
            return {"path": path, "count": len(edges), "edges": edges}
        if route == "shadergraph/info":
            path = str(payload.get("path") or "")
            sg = self._shadergraphs.get(path, {})
            return {"path": path, "name": sg.get("name", path.rsplit("/", 1)[-1]), "nodeCount": len(sg.get("nodes", [])), "edgeCount": len(sg.get("edges", []))}
        if route == "shadergraph/list-subgraphs":
            path = str(payload.get("path") or "")
            return {"path": path, "count": 0, "subgraphs": []}
        if route == "shadergraph/open":
            path = str(payload.get("path") or "")
            return {"success": True, "path": path}
        if route == "shadergraph/add-node":
            path = str(payload.get("path") or "")
            node_type = str(payload.get("nodeType") or "")
            node_id = f"node_{len(self._shadergraphs.get(path, {}).get('nodes', []))}"
            sg = self._shadergraphs.setdefault(path, {"name": path, "nodes": [], "edges": []})
            node = {"id": node_id, "type": node_type, "position": payload.get("position", {"x": 0, "y": 0})}
            sg["nodes"].append(node)
            return {"success": True, "path": path, "node": node}
        if route == "shadergraph/remove-node":
            path = str(payload.get("path") or "")
            node_id = str(payload.get("nodeId") or "")
            sg = self._shadergraphs.get(path, {})
            before = len(sg.get("nodes", []))
            sg["nodes"] = [n for n in sg.get("nodes", []) if n.get("id") != node_id]
            return {"success": True, "path": path, "removed": before > len(sg["nodes"])}
        if route == "shadergraph/set-node-property":
            path = str(payload.get("path") or "")
            node_id = str(payload.get("nodeId") or "")
            prop = str(payload.get("property") or "")
            value = payload.get("value")
            for n in self._shadergraphs.get(path, {}).get("nodes", []):
                if n.get("id") == node_id:
                    n[prop] = value
            return {"success": True, "path": path, "nodeId": node_id, "property": prop, "value": value}
        if route == "shadergraph/connect":
            path = str(payload.get("path") or "")
            edge = {"from": payload.get("fromNode"), "fromPort": payload.get("fromPort"), "to": payload.get("toNode"), "toPort": payload.get("toPort")}
            self._shadergraphs.setdefault(path, {"name": path, "nodes": [], "edges": []})["edges"].append(edge)
            return {"success": True, "path": path, "edge": edge}
        if route == "shadergraph/disconnect":
            path = str(payload.get("path") or "")
            from_node = payload.get("fromNode")
            to_node = payload.get("toNode")
            sg = self._shadergraphs.get(path, {})
            before = len(sg.get("edges", []))
            sg["edges"] = [e for e in sg.get("edges", []) if not (e.get("from") == from_node and e.get("to") == to_node)]
            return {"success": True, "path": path, "removed": before - len(sg.get("edges", []))}
        # ── PlayerPrefs routes ──────────────────────────────────────────
        if route == "playerprefs/set":
            key = str(payload.get("key") or "")
            pref_type = str(payload.get("type") or "string").lower()
            value = payload.get("value")
            if pref_type == "int":
                value = int(value)
            elif pref_type == "float":
                value = float(value)
            self._playerprefs[key] = {"value": value, "type": pref_type}
            return {"success": True, "key": key, "value": value, "type": pref_type}
        if route == "playerprefs/get":
            key = str(payload.get("key") or "")
            entry = self._playerprefs.get(key)
            return {
                "key": key,
                "exists": entry is not None,
                "value": entry.get("value") if entry else None,
                "type": entry.get("type") if entry else str(payload.get("type") or "string").lower(),
            }
        if route == "playerprefs/delete":
            key = str(payload.get("key") or "")
            removed = key in self._playerprefs
            self._playerprefs.pop(key, None)
            return {"success": True, "key": key, "removed": removed}
        if route == "playerprefs/delete-all":
            deleted_count = len(self._playerprefs)
            self._playerprefs.clear()
            return {"success": True, "deletedCount": deleted_count}
        # ── Selection routes ─────────────────────────────────────────────
        if route == "selection/get":
            return {"count": len(self._selection), "paths": list(self._selection), "activePath": self._selection[0] if self._selection else None}
        if route == "selection/set":
            raw_paths = payload.get("paths")
            if isinstance(raw_paths, list):
                paths = [str(path) for path in raw_paths]
            elif payload.get("path"):
                paths = [str(payload.get("path"))]
            elif payload.get("instanceId") is not None:
                instance_id = int(payload.get("instanceId"))
                paths = [name for name, go in self.gameobjects.items() if go.get("instanceId") == instance_id]
            else:
                paths = []
            self._selection = list(paths)
            return {"success": True, "count": len(self._selection), "paths": self._selection, "activePath": self._selection[0] if self._selection else None}
        if route == "selection/find-by-type":
            type_name = str(payload.get("typeName") or payload.get("type") or "")
            matches = [{"path": k} for k, v in self.gameobjects.items() if type_name in v.get("components", [])]
            return {"typeName": type_name, "count": len(matches), "paths": [match["path"] for match in matches], "results": matches}
        if route == "selection/focus-scene-view":
            path = str(payload.get("path") or (self._selection[0] if self._selection else ""))
            if path:
                self._selection = [path]
            return {"success": True, "focused": True, "path": path}
        # ── ScriptableObject routes ──────────────────────────────────────
        if route == "scriptableobject/list-types":
            return {"count": 2, "types": [{"typeName": "GameSettings", "assembly": "Assembly-CSharp"}, {"typeName": "ItemDatabase", "assembly": "Assembly-CSharp"}]}
        if route == "scriptableobject/create":
            type_name = str(payload.get("typeName") or "")
            asset_path = str(payload.get("path") or f"Assets/{type_name}.asset")
            self._scriptable_objects[asset_path] = {"typeName": type_name, "path": asset_path, "fields": {}}
            return {"success": True, "typeName": type_name, "path": asset_path}
        if route == "scriptableobject/info":
            path = str(payload.get("path") or "")
            so = self._scriptable_objects.get(path, {})
            return {"path": path, "typeName": so.get("typeName", ""), "fields": so.get("fields", {})}
        if route == "scriptableobject/set-field":
            path = str(payload.get("path") or "")
            field = str(payload.get("fieldName") or "")
            value = payload.get("value")
            self._scriptable_objects.setdefault(path, {"typeName": "", "path": path, "fields": {}})["fields"][field] = value
            return {"success": True, "path": path, "fieldName": field, "value": value}
        # ── Settings routes ──────────────────────────────────────────────
        if route == "settings/physics":
            return {"gravity": {"x": 0, "y": -9.81, "z": 0}, "defaultContactOffset": 0.01, "sleepThreshold": 0.005, "queriesHitTriggers": True}
        if route == "settings/player":
            return {"companyName": "DefaultCompany", "productName": "Demo", "bundleVersion": "1.0", "scriptingBackend": "Mono"}
        if route == "settings/render-pipeline":
            return {"renderPipeline": "UniversalRP", "pipelineAssetPath": "Assets/Settings/URP.asset"}
        if route == "settings/set-physics":
            return {"success": True, "gravity": payload.get("gravity", {"x": 0, "y": -9.81, "z": 0})}
        if route == "settings/set-player":
            return {"success": True, "productName": payload.get("productName", "Demo")}
        if route == "settings/quality-level":
            level = payload.get("qualityLevel", 0)
            return {"success": True, "qualityLevel": level}
        if route == "settings/set-time":
            return {"success": True, "fixedDeltaTime": payload.get("fixedDeltaTime", 0.02), "timeScale": payload.get("timeScale", 1.0)}
        # ── Tag/Layer routes ─────────────────────────────────────────────
        if route == "taglayer/info":
            return {"tags": ["Untagged", "Respawn", "Finish", "Player"], "layers": ["Default", "TransparentFX", "Ignore Raycast", "Water", "UI"]}
        if route == "taglayer/add-tag":
            tag = str(payload.get("tag") or "")
            return {"success": True, "tag": tag}
        if route == "taglayer/set-tag":
            go_path = str(payload.get("gameObjectPath") or "")
            tag = str(payload.get("tag") or "Untagged")
            if go_path in self.gameobjects:
                self.gameobjects[go_path]["tag"] = tag
            return {"success": True, "gameObjectPath": go_path, "tag": tag}
        if route == "taglayer/set-layer":
            go_path = str(payload.get("gameObjectPath") or "")
            layer = str(payload.get("layer") or "Default")
            if go_path in self.gameobjects:
                self.gameobjects[go_path]["layer"] = layer
            return {"success": True, "gameObjectPath": go_path, "layer": layer}
        if route == "taglayer/set-static":
            go_path = str(payload.get("gameObjectPath") or "")
            is_static = bool(payload.get("isStatic", True))
            if go_path in self.gameobjects:
                self.gameobjects[go_path]["isStatic"] = is_static
            return {"success": True, "gameObjectPath": go_path, "isStatic": is_static}
        # ── Texture routes ───────────────────────────────────────────────
        if route == "texture/info":
            path = str(payload.get("path") or "")
            return {"path": path, "width": 512, "height": 512, "format": "RGBA32", "mipMapCount": 10, "isReadable": False, "textureType": "Default"}
        if route == "texture/reimport":
            path = str(payload.get("path") or "")
            return {"success": True, "path": path}
        if route == "texture/set-import":
            path = str(payload.get("path") or "")
            return {"success": True, "path": path, "textureType": payload.get("textureType", "Default"), "maxSize": payload.get("maxSize", 2048)}
        if route == "texture/set-normalmap":
            path = str(payload.get("path") or "")
            return {"success": True, "path": path, "textureType": "NormalMap"}
        if route == "texture/set-sprite":
            path = str(payload.get("path") or "")
            return {"success": True, "path": path, "textureType": "Sprite", "spritePivot": payload.get("pivot", {"x": 0.5, "y": 0.5})}
        # ── SpriteAtlas routes ──────────────────────────────────────────
        if route == "spriteatlas/create":
            path = str(payload.get("path") or "")
            atlas = {
                "path": path,
                "packables": [],
                "settings": {"includeInBuild": bool(payload.get("includeInBuild", True))},
            }
            self._spriteatlases[path] = atlas
            return {"success": True, "path": path, "includeInBuild": atlas["settings"]["includeInBuild"]}
        if route == "spriteatlas/list":
            folder = str(payload.get("folder") or "")
            atlases = [
                atlas
                for path, atlas in self._spriteatlases.items()
                if not folder or path.startswith(folder)
            ]
            return {"count": len(atlases), "atlases": list(atlases)}
        if route == "spriteatlas/info":
            path = str(payload.get("path") or "")
            atlas = self._spriteatlases.get(path, {"path": path, "packables": [], "settings": {}})
            return {
                "path": path,
                "exists": path in self._spriteatlases,
                "packableCount": len(atlas.get("packables", [])),
                "packables": list(atlas.get("packables", [])),
                "settings": dict(atlas.get("settings", {})),
            }
        if route == "spriteatlas/add":
            path = str(payload.get("path") or "")
            assets = list(payload.get("assetPaths") or [])
            if payload.get("assetPath"):
                assets.append(str(payload.get("assetPath")))
            atlas = self._spriteatlases.setdefault(path, {"path": path, "packables": [], "settings": {}})
            for asset_path in assets:
                if asset_path not in atlas["packables"]:
                    atlas["packables"].append(asset_path)
            return {"success": True, "path": path, "addedCount": len(assets), "packables": list(atlas["packables"])}
        if route == "spriteatlas/remove":
            path = str(payload.get("path") or "")
            assets = list(payload.get("assetPaths") or [])
            if payload.get("assetPath"):
                assets.append(str(payload.get("assetPath")))
            atlas = self._spriteatlases.setdefault(path, {"path": path, "packables": [], "settings": {}})
            before = len(atlas["packables"])
            atlas["packables"] = [asset_path for asset_path in atlas["packables"] if asset_path not in assets]
            return {"success": True, "path": path, "removedCount": before - len(atlas["packables"]), "packables": list(atlas["packables"])}
        if route == "spriteatlas/settings":
            path = str(payload.get("path") or "")
            atlas = self._spriteatlases.setdefault(path, {"path": path, "packables": [], "settings": {}})
            for key in ("includeInBuild", "enableRotation", "enableTightPacking", "padding", "readable", "generateMipMaps", "sRGB", "filterMode"):
                if key in payload:
                    atlas.setdefault("settings", {})[key] = payload[key]
            return {"success": True, "path": path, "settings": dict(atlas.get("settings", {}))}
        if route == "spriteatlas/delete":
            path = str(payload.get("path") or "")
            deleted = path in self._spriteatlases
            self._spriteatlases.pop(path, None)
            return {"success": True, "path": path, "deleted": deleted}
        # ── NavMesh routes ───────────────────────────────────────────────
        if route == "navigation/add-agent":
            go_path = str(payload.get("gameObjectPath") or "")
            return {"success": True, "gameObjectPath": go_path, "agentTypeId": 0, "speed": float(payload.get("speed") or 3.5)}
        if route == "navigation/add-obstacle":
            go_path = str(payload.get("gameObjectPath") or "")
            return {"success": True, "gameObjectPath": go_path, "shape": str(payload.get("shape") or "Box")}
        if route == "navigation/bake":
            return {"success": True, "triangleCount": 128, "area": 100.0}
        if route == "navigation/clear":
            return {"success": True}
        if route == "navigation/set-destination":
            go_path = str(payload.get("gameObjectPath") or "")
            dest = payload.get("destination") or {"x": 0, "y": 0, "z": 0}
            return {"success": True, "gameObjectPath": go_path, "destination": dest, "pathStatus": "Complete"}
        # ── Physics routes ───────────────────────────────────────────────
        if route == "physics/collision-matrix":
            return {"layers": [{"layer": 0, "name": "Default"}, {"layer": 5, "name": "UI"}], "matrix": {}}
        if route == "physics/overlap-box":
            center = payload.get("center") or {"x": 0, "y": 0, "z": 0}
            return {"center": center, "count": 0, "colliders": []}
        if route == "physics/overlap-sphere":
            center = payload.get("center") or {"x": 0, "y": 0, "z": 0}
            return {"center": center, "radius": float(payload.get("radius") or 1.0), "count": 0, "colliders": []}
        if route == "physics/set-collision-layer":
            layer_a = int(payload.get("layerA") or 0)
            layer_b = int(payload.get("layerB") or 0)
            ignore = bool(payload.get("ignore", False))
            return {"success": True, "layerA": layer_a, "layerB": layer_b, "ignore": ignore}
        if route == "physics/set-gravity":
            gravity = payload.get("gravity") or {"x": 0, "y": -9.81, "z": 0}
            return {"success": True, "gravity": gravity}
        # ── Graphics routes ──────────────────────────────────────────────
        if route == "graphics/asset-preview":
            path = str(payload.get("path") or "")
            return {"success": True, "path": path, "previewData": "", "width": int(payload.get("width") or 128), "height": int(payload.get("height") or 128)}
        if route == "graphics/prefab-render":
            path = str(payload.get("path") or "")
            return {"success": True, "path": path, "renderData": "", "width": int(payload.get("width") or 256), "height": int(payload.get("height") or 256)}
        if route == "graphics/texture-info":
            path = str(payload.get("path") or "")
            return {"path": path, "width": 1024, "height": 1024, "format": "DXT1", "mipMapCount": 11}
        # ── Packages routes ──────────────────────────────────────────────
        if route == "packages/list":
            return {"count": 2, "packages": [{"name": "com.unity.textmeshpro", "version": "3.0.6", "displayName": "TextMeshPro"}, {"name": "com.unity.ugui", "version": "1.0.0", "displayName": "Unity UI"}]}
        if route == "packages/info":
            pkg = str(payload.get("packageId") or payload.get("name") or "")
            return {"name": pkg, "displayName": pkg, "version": "1.0.0", "description": "Mock package", "dependencies": {}}
        if route == "packages/search":
            query = str(payload.get("query") or payload.get("search") or "")
            return {"query": query, "count": 1, "results": [{"name": "com.unity.mock-" + query.lower().replace(" ", "-"), "version": "1.0.0"}]}
        if route == "packages/add":
            pkg = str(payload.get("packageId") or payload.get("name") or "")
            return {"success": True, "packageId": pkg, "version": str(payload.get("version") or "latest")}
        if route == "packages/remove":
            pkg = str(payload.get("packageId") or payload.get("name") or "")
            return {"success": True, "packageId": pkg}
        # ── Input System routes ─────────────────────────────────────────
        if route == "input/create":
            path = str(payload.get("path") or "Assets/Input/Controls.inputactions")
            name = str(payload.get("name") or path.rsplit("/", 1)[-1].replace(".inputactions", ""))
            maps = {
                str(item.get("name") or "Player"): {"name": str(item.get("name") or "Player"), "actions": {}}
                for item in (payload.get("maps") or [])
                if isinstance(item, dict)
            }
            self._input_assets[path] = {"path": path, "name": name, "maps": maps}
            return {"success": True, "path": path, "name": name, "mapCount": len(maps)}
        if route == "input/info":
            path = str(payload.get("path") or "")
            asset = self._input_assets.get(path, {"path": path, "name": "", "maps": {}})
            action_count = sum(len(action_map.get("actions", {})) for action_map in asset.get("maps", {}).values())
            return {
                "path": path,
                "name": asset.get("name", ""),
                "mapCount": len(asset.get("maps", {})),
                "actionCount": action_count,
                "maps": list(asset.get("maps", {}).values()),
            }
        if route == "input/add-map":
            path = str(payload.get("path") or "")
            map_name = str(payload.get("mapName") or "")
            asset = self._input_assets.setdefault(path, {"path": path, "name": path.rsplit("/", 1)[-1], "maps": {}})
            asset.setdefault("maps", {}).setdefault(map_name, {"name": map_name, "actions": {}})
            return {"success": True, "path": path, "mapName": map_name}
        if route == "input/remove-map":
            path = str(payload.get("path") or "")
            map_name = str(payload.get("mapName") or "")
            maps = self._input_assets.setdefault(path, {"path": path, "name": "", "maps": {}}).setdefault("maps", {})
            removed = maps.pop(map_name, None) is not None
            return {"success": True, "path": path, "mapName": map_name, "removed": removed}
        if route == "input/add-action":
            path = str(payload.get("path") or "")
            map_name = str(payload.get("mapName") or "")
            action_name = str(payload.get("actionName") or "")
            asset = self._input_assets.setdefault(path, {"path": path, "name": path.rsplit("/", 1)[-1], "maps": {}})
            action_map = asset.setdefault("maps", {}).setdefault(map_name, {"name": map_name, "actions": {}})
            action = {
                "name": action_name,
                "actionType": str(payload.get("actionType") or "Value"),
                "expectedControlType": payload.get("expectedControlType"),
                "bindings": [],
            }
            action_map.setdefault("actions", {})[action_name] = action
            return {"success": True, "path": path, "mapName": map_name, "actionName": action_name, "action": action}
        if route == "input/remove-action":
            path = str(payload.get("path") or "")
            map_name = str(payload.get("mapName") or "")
            action_name = str(payload.get("actionName") or "")
            actions = self._input_assets.setdefault(path, {"path": path, "name": "", "maps": {}}).setdefault("maps", {}).setdefault(map_name, {"name": map_name, "actions": {}}).setdefault("actions", {})
            removed = actions.pop(action_name, None) is not None
            return {"success": True, "path": path, "mapName": map_name, "actionName": action_name, "removed": removed}
        if route == "input/add-binding":
            path = str(payload.get("path") or "")
            map_name = str(payload.get("mapName") or "")
            action_name = str(payload.get("actionName") or "")
            binding_path = str(payload.get("bindingPath") or "")
            action = self._input_assets.setdefault(path, {"path": path, "name": "", "maps": {}}).setdefault("maps", {}).setdefault(map_name, {"name": map_name, "actions": {}}).setdefault("actions", {}).setdefault(action_name, {"name": action_name, "bindings": []})
            binding = {"path": binding_path}
            action.setdefault("bindings", []).append(binding)
            return {"success": True, "path": path, "mapName": map_name, "actionName": action_name, "binding": binding}
        if route == "input/add-composite-binding":
            path = str(payload.get("path") or "")
            map_name = str(payload.get("mapName") or "")
            action_name = str(payload.get("actionName") or "")
            action = self._input_assets.setdefault(path, {"path": path, "name": "", "maps": {}}).setdefault("maps", {}).setdefault(map_name, {"name": map_name, "actions": {}}).setdefault("actions", {}).setdefault(action_name, {"name": action_name, "bindings": []})
            binding = {
                "compositeName": str(payload.get("compositeName") or ""),
                "compositeType": str(payload.get("compositeType") or "Composite"),
                "parts": list(payload.get("parts") or []),
            }
            action.setdefault("bindings", []).append(binding)
            return {"success": True, "path": path, "mapName": map_name, "actionName": action_name, "binding": binding}
        # ── Prefab routes ────────────────────────────────────────────────
        if route == "prefab/info":
            path = str(payload.get("path") or "")
            prefab = self.prefabs.get(path, {})
            return {"path": path, "name": prefab.get("name", path.rsplit("/", 1)[-1].replace(".prefab", "")), "componentCount": len(prefab.get("components", [])), "childCount": 0, "isVariant": False}
        if route == "prefab/apply-overrides":
            path = str(payload.get("prefabPath") or payload.get("path") or "")
            return {"success": True, "path": path, "overridesApplied": 1}
        if route == "prefab/revert-overrides":
            path = str(payload.get("prefabPath") or payload.get("path") or "")
            return {"success": True, "path": path, "overridesReverted": 1}
        if route == "prefab/create-variant":
            source = str(payload.get("sourcePath") or payload.get("path") or "")
            variant_path = str(payload.get("variantPath") or source.replace(".prefab", "Variant.prefab"))
            self.prefabs[variant_path] = {"name": variant_path.rsplit("/", 1)[-1].replace(".prefab", ""), "components": [], "isVariant": True, "basePath": source}
            return {"success": True, "variantPath": variant_path, "basePath": source}
        if route == "prefab/unpack":
            path = str(payload.get("prefabPath") or payload.get("path") or "")
            mode = str(payload.get("mode") or "root")
            return {"success": True, "path": path, "mode": mode, "unpackedCount": 1}
        if route == "prefab-asset/hierarchy":
            path = str(payload.get("path") or "")
            prefab = self.prefabs.get(path, {})
            return {"path": path, "name": prefab.get("name", "Root"), "children": [], "componentCount": len(prefab.get("components", []))}
        if route == "prefab-asset/get-properties":
            path = str(payload.get("path") or "")
            component = str(payload.get("component") or "Transform")
            return {"path": path, "component": component, "properties": {"localPosition": {"x": 0, "y": 0, "z": 0}}}
        if route == "prefab-asset/set-property":
            path = str(payload.get("path") or "")
            return {"success": True, "path": path, "property": payload.get("propertyName"), "value": payload.get("value")}
        if route == "prefab-asset/set-reference":
            path = str(payload.get("path") or "")
            return {"success": True, "path": path, "property": payload.get("propertyName"), "referencePath": payload.get("referencePath")}
        if route == "prefab-asset/add-component":
            path = str(payload.get("path") or "")
            component = str(payload.get("component") or "")
            self.prefabs.setdefault(path, {"name": path, "components": []}).setdefault("components", []).append(component)
            return {"success": True, "path": path, "component": component}
        if route == "prefab-asset/remove-component":
            path = str(payload.get("path") or "")
            component = str(payload.get("component") or "")
            comps = self.prefabs.get(path, {}).get("components", [])
            removed = component in comps
            if removed:
                comps.remove(component)
            return {"success": True, "path": path, "component": component, "removed": removed}
        if route == "prefab-asset/add-gameobject":
            path = str(payload.get("path") or "")
            child_name = str(payload.get("name") or "Child")
            return {"success": True, "path": path, "childName": child_name}
        if route == "prefab-asset/remove-gameobject":
            path = str(payload.get("path") or "")
            child_path = str(payload.get("childPath") or "")
            return {"success": True, "path": path, "childPath": child_path, "removed": True}
        if route == "prefab-asset/compare-variant":
            path = str(payload.get("path") or "")
            return {"path": path, "differences": [], "differenceCount": 0}
        if route == "prefab-asset/variant-info":
            path = str(payload.get("path") or "")
            prefab = self.prefabs.get(path, {})
            return {"path": path, "isVariant": prefab.get("isVariant", False), "basePath": prefab.get("basePath", ""), "overrideCount": 0}
        if route == "prefab-asset/apply-variant-override":
            path = str(payload.get("path") or "")
            return {"success": True, "path": path, "overridesApplied": 1}
        if route == "prefab-asset/revert-variant-override":
            path = str(payload.get("path") or "")
            return {"success": True, "path": path, "overridesReverted": 1}
        if route == "prefab-asset/transfer-variant-overrides":
            source = str(payload.get("sourcePath") or "")
            dest = str(payload.get("destinationPath") or "")
            return {"success": True, "sourcePath": source, "destinationPath": dest, "overridesTransferred": 1}
        # ── Asmdef routes ─────────────────────────────────────────────────
        if route == "asmdef/list":
            return {"count": 0, "asmdefs": []}
        if route == "asmdef/info":
            path = str(payload.get("path") or "")
            return {"path": path, "name": path.rsplit("/", 1)[-1].replace(".asmdef", ""), "references": [], "includePlatforms": [], "excludePlatforms": [], "allowUnsafeCode": False}
        if route == "asmdef/create":
            path = str(payload.get("path") or "Assets/NewAssembly.asmdef")
            name = str(payload.get("name") or path.rsplit("/", 1)[-1].replace(".asmdef", ""))
            return {"success": True, "path": path, "name": name}
        if route == "asmdef/create-ref":
            path = str(payload.get("path") or "Assets/NewAssemblyRef.asmref")
            return {"success": True, "path": path}
        if route == "asmdef/add-references":
            path = str(payload.get("path") or "")
            refs = payload.get("references") or []
            return {"success": True, "path": path, "referencesAdded": len(refs)}
        if route == "asmdef/remove-references":
            path = str(payload.get("path") or "")
            refs = payload.get("references") or []
            return {"success": True, "path": path, "referencesRemoved": len(refs)}
        if route == "asmdef/set-platforms":
            path = str(payload.get("path") or "")
            return {"success": True, "path": path, "includePlatforms": payload.get("includePlatforms", []), "excludePlatforms": payload.get("excludePlatforms", [])}
        if route == "asmdef/update-settings":
            path = str(payload.get("path") or "")
            return {"success": True, "path": path}
        # ── Particle routes ───────────────────────────────────────────────
        if route == "particle/create":
            name = str(payload.get("name") or "ParticleSystem")
            self._register_gameobject(name, components=["Transform", "ParticleSystem"], position=payload.get("position"))
            self.scene_dirty = True
            return {"success": True, "name": name, "gameObjectPath": name}
        if route == "particle/info":
            name = str(payload.get("name") or payload.get("gameObjectPath") or "")
            return {"name": name, "isPlaying": False, "particleCount": 0, "emission": {"rateOverTime": 10}, "main": {"duration": 5.0, "loop": True, "startLifetime": 5.0, "startSpeed": 5.0, "maxParticles": 1000}}
        if route == "particle/playback":
            name = str(payload.get("name") or payload.get("gameObjectPath") or "")
            action = str(payload.get("action") or "play")
            return {"success": True, "name": name, "action": action}
        if route == "particle/set-emission":
            name = str(payload.get("name") or payload.get("gameObjectPath") or "")
            return {"success": True, "name": name, "rateOverTime": payload.get("rateOverTime", 10), "rateOverDistance": payload.get("rateOverDistance", 0)}
        if route == "particle/set-main":
            name = str(payload.get("name") or payload.get("gameObjectPath") or "")
            return {"success": True, "name": name}
        if route == "particle/set-shape":
            name = str(payload.get("name") or payload.get("gameObjectPath") or "")
            shape = str(payload.get("shape") or "Sphere")
            return {"success": True, "name": name, "shape": shape}
        # ── LOD routes ────────────────────────────────────────────────────
        if route == "lod/create":
            name = str(payload.get("name") or payload.get("gameObjectPath") or "LODGroup")
            self._register_gameobject(name, components=["Transform", "LODGroup"])
            self.scene_dirty = True
            return {"success": True, "name": name, "lodCount": int(payload.get("lodCount") or 3)}
        if route == "lod/info":
            name = str(payload.get("name") or payload.get("gameObjectPath") or "")
            return {"name": name, "lodCount": 3, "lods": [{"level": 0, "screenRelativeHeight": 0.6}, {"level": 1, "screenRelativeHeight": 0.3}, {"level": 2, "screenRelativeHeight": 0.1}]}
        # ── Constraint routes ─────────────────────────────────────────────
        if route == "constraint/add":
            go_path = str(payload.get("gameObjectPath") or "")
            constraint_type = str(payload.get("constraintType") or "PositionConstraint")
            return {"success": True, "gameObjectPath": go_path, "constraintType": constraint_type, "sourceCount": len(payload.get("sources") or [])}
        if route == "constraint/info":
            go_path = str(payload.get("gameObjectPath") or "")
            return {"gameObjectPath": go_path, "constraints": []}
        # ── Animation mutation routes ────────────────────────────────────
        if route == "animation/get-blend-tree":
            controller_path = str(payload.get("controllerPath") or "")
            layer_index = int(payload.get("layerIndex") or 0)
            state_name = str(payload.get("stateName") or "")
            controller = self.animation_controllers.get(controller_path, {})
            states = controller.get("states", [])
            state = next((s for s in states if s.get("name") == state_name), None)
            return {"controllerPath": controller_path, "layerIndex": layer_index, "stateName": state_name, "blendTree": state.get("blendTree") if state else None}
        if route == "animation/add-keyframe":
            clip_path = str(payload.get("clipPath") or "")
            type_name = str(payload.get("typeName") or "")
            property_name = str(payload.get("propertyName") or "")
            keyframe = {"time": float(payload.get("time") or 0), "value": float(payload.get("value") or 0)}
            self.animation_clips.setdefault(clip_path, {"path": clip_path, "curves": {}, "events": []})
            self.animation_clips[clip_path].setdefault("curves", {}).setdefault(f"{type_name}:{property_name}", []).append(keyframe)
            return {"success": True, "clipPath": clip_path, "keyframe": keyframe}
        if route == "animation/remove-keyframe":
            clip_path = str(payload.get("clipPath") or "")
            type_name = str(payload.get("typeName") or "")
            property_name = str(payload.get("propertyName") or "")
            time = float(payload.get("time") or 0)
            curve_key = f"{type_name}:{property_name}"
            curves = self.animation_clips.get(clip_path, {}).get("curves", {})
            before = len(curves.get(curve_key, []))
            curves[curve_key] = [k for k in curves.get(curve_key, []) if k.get("time") != time]
            removed = before - len(curves.get(curve_key, []))
            return {"success": True, "clipPath": clip_path, "keyframesRemoved": removed}
        if route == "animation/remove-curve":
            clip_path = str(payload.get("clipPath") or "")
            type_name = str(payload.get("typeName") or "")
            property_name = str(payload.get("propertyName") or "")
            curve_key = f"{type_name}:{property_name}"
            removed = curve_key in self.animation_clips.get(clip_path, {}).get("curves", {})
            if removed:
                del self.animation_clips[clip_path]["curves"][curve_key]
            return {"success": True, "clipPath": clip_path, "curveRemoved": removed}
        if route == "animation/remove-event":
            clip_path = str(payload.get("clipPath") or "")
            time = float(payload.get("time") or 0)
            events_before = list(self.animation_clips.get(clip_path, {}).get("events", []))
            remaining = [e for e in events_before if e.get("time") != time]
            if clip_path in self.animation_clips:
                self.animation_clips[clip_path]["events"] = remaining
            return {"success": True, "clipPath": clip_path, "eventsRemoved": len(events_before) - len(remaining)}
        if route == "animation/remove-layer":
            controller_path = str(payload.get("controllerPath") or "")
            layer_index = int(payload.get("layerIndex") or 0)
            controller = self.animation_controllers.get(controller_path, {})
            layers = controller.get("layers", [])
            removed = layers.pop(layer_index) if layer_index < len(layers) else None
            return {"success": True, "controllerPath": controller_path, "layerRemoved": removed is not None}
        if route == "animation/remove-parameter":
            controller_path = str(payload.get("controllerPath") or "")
            param_name = str(payload.get("parameterName") or "")
            controller = self.animation_controllers.get(controller_path, {})
            params_before = list(controller.get("parameters", []))
            controller["parameters"] = [p for p in params_before if p.get("name") != param_name]
            removed_count = len(params_before) - len(controller["parameters"])
            return {"success": True, "controllerPath": controller_path, "parameterRemoved": removed_count > 0}
        if route == "animation/remove-state":
            controller_path = str(payload.get("controllerPath") or "")
            state_name = str(payload.get("stateName") or "")
            controller = self.animation_controllers.get(controller_path, {})
            states_before = list(controller.get("states", []))
            controller["states"] = [s for s in states_before if s.get("name") != state_name]
            removed_count = len(states_before) - len(controller.get("states", []))
            return {"success": True, "controllerPath": controller_path, "stateRemoved": removed_count > 0}
        if route == "animation/remove-transition":
            controller_path = str(payload.get("controllerPath") or "")
            source_state = payload.get("sourceState") or payload.get("fromState")
            dest_state = payload.get("destinationState") or payload.get("toState")
            controller = self.animation_controllers.get(controller_path, {})
            transitions_before = list(controller.get("transitions", []))
            def _transition_matches(t: dict) -> bool:
                dest_match = dest_state is None or t.get("destinationState") == dest_state
                src_match = source_state is None or t.get("sourceState") == source_state
                return dest_match and src_match
            controller["transitions"] = [t for t in transitions_before if not _transition_matches(t)]
            removed_count = len(transitions_before) - len(controller.get("transitions", []))
            return {"success": True, "controllerPath": controller_path, "transitionRemoved": removed_count > 0}
        if route == "animation/assign-controller":
            go_path = str(payload.get("gameObjectPath") or "")
            controller_path = str(payload.get("controllerPath") or "")
            go = self.gameobjects.get(go_path, {})
            go["animatorController"] = controller_path
            self.gameobjects[go_path] = go
            return {"success": True, "gameObjectPath": go_path, "controllerPath": controller_path}
        if route == "animation/create-blend-tree":
            controller_path = str(payload.get("controllerPath") or "")
            state_name = str(payload.get("stateName") or "BlendTreeState")
            blend_type = str(payload.get("blendType") or "Simple1D")
            controller = self.animation_controllers.setdefault(controller_path, {"path": controller_path, "parameters": [], "transitions": [], "states": []})
            blend_tree = {"blendType": blend_type, "parameter": payload.get("parameter", ""), "motions": []}
            state = {"name": state_name, "blendTree": blend_tree}
            controller.setdefault("states", []).append(state)
            return {"success": True, "controllerPath": controller_path, "stateName": state_name, "blendTree": blend_tree}
        if route == "animation/set-clip-settings":
            clip_path = str(payload.get("clipPath") or "")
            clip = self.animation_clips.setdefault(clip_path, {"path": clip_path, "curves": {}, "events": []})
            for k in ("loop", "frameRate", "wrapMode", "startTime", "stopTime"):
                if k in payload:
                    clip[k] = payload[k]
            return {"success": True, "clipPath": clip_path}
        if route == "compilation/errors":
            return {"count": 0, "isCompiling": False, "entries": []}
        if route == "agents/list":
            return {
                "count": 2,
                "agents": [
                    {
                        "agentId": "cli-anything-unity-mcp-builder",
                        "currentAction": "idle",
                        "queuedRequests": 0,
                        "completedRequests": 4,
                    },
                    {
                        "agentId": "cli-anything-unity-mcp-reviewer",
                        "currentAction": "inspect",
                        "queuedRequests": 1,
                        "completedRequests": 2,
                    },
                ],
            }
        if route == "agents/log":
            agent_id = str(payload.get("agentId") or "unknown-agent")
            return {
                "agentId": agent_id,
                "count": 2,
                "actions": [
                    {"timestamp": "2026-04-09T00:00:00Z", "action": "inspect", "status": "completed"},
                    {"timestamp": "2026-04-09T00:00:05Z", "action": "validate-scene", "status": "completed"},
                ],
            }
        if route == "editor/execute-code":
            code = str(payload.get("code") or "")
            self.execute_code_calls.append(code)
            generated_layout = self._create_2d_sample_layout_from_code(code)
            if generated_layout is not None:
                return generated_layout
            generated_bird_scene = self._create_bird_pov_scene_from_code(code)
            if generated_bird_scene is not None:
                return generated_bird_scene
            generated_fps_scene = self._create_3d_fps_scene_from_code(code)
            if generated_fps_scene is not None:
                return generated_fps_scene
            return {
                "success": True,
                "echo": code,
            }
        if route == "editor/play-mode":
            action = payload.get("action")
            if action == "play":
                self.is_playing = True
            elif action == "stop":
                self.is_playing = False
            return {
                "success": True,
                "action": action,
            }
        if route == "undo/perform":
            return {
                "success": True,
                "operation": "undo",
            }
        return {
            "ok": True,
            "route": route,
            "params": payload,
        }


class MockBridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/ping":
            self._write(
                200,
                {
                    "status": "ok",
                    "projectName": self.server.project_name,
                    "projectPath": self.server.project_path,
                    "unityVersion": self.server.unity_version,
                    "platform": "WindowsEditor",
                    "isClone": False,
                    "cloneIndex": -1,
                },
            )
            return
        if parsed.path == "/api/_meta/routes":
            self._write(
                200,
                {
                    "routes": [
                        "scene/info",
                        "project/info",
                        "scene/new",
                        "scene/open",
                        "scene/save",
                        "scene/hierarchy",
                        "asset/list",
                        "asset/delete",
                        "asset/create-prefab",
                        "asset/instantiate-prefab",
                        "script/create",
                        "script/read",
                        "script/update",
                        "gameobject/create",
                        "gameobject/info",
                        "gameobject/delete",
                        "gameobject/set-transform",
                        "component/add",
                        "component/get-properties",
                        "component/set-property",
                        "component/set-reference",
                        "search/missing-references",
                        "scene/stats",
                        "profiler/memory-status",
                        "graphics/lighting-summary",
                        "sceneview/info",
                        "settings/quality",
                        "settings/time",
                        "profiler/stats",
                        "testing/list-tests",
                        "graphics/renderer-info",
                        "graphics/mesh-info",
                        "graphics/material-info",
                        "physics/raycast",
                        "compilation/errors",
                        "agents/list",
                        "agents/log",
                        "editor/state",
                        "editor/play-mode",
                        "editor/execute-code",
                        "undo/perform",
                        "context",
                        "scenario/info",
                        "scenario/list",
                        "scenario/status",
                        "scenario/activate",
                        "scenario/start",
                        "scenario/stop",
                    ],
                    "totalRoutes": 46,
                },
            )
            return
        if parsed.path == "/api/context" or parsed.path.startswith("/api/context/"):
            category = parsed.path.removeprefix("/api/context/") if parsed.path.startswith("/api/context/") else None
            payload = {
                "projectPath": "C:/Projects/Demo",
                "unityVersion": "6000.4.0f1",
                "platform": "StandaloneWindows64",
                "renderPipeline": "UniversalRP",
            }
            if category:
                payload["category"] = category
            self._write(200, payload)
            return
        if parsed.path == "/api/queue/status":
            query = parse_qs(parsed.query)
            ticket_id = int(query["ticketId"][0])
            self._write(200, self.server.tickets[ticket_id])
            return
        if parsed.path == "/api/queue/info":
            self._write(200, {"queued": 0, "activeAgents": 1})
            return
        self._write(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        payload = json.loads(raw) if raw else {}
        parsed = urlparse(self.path)

        if parsed.path == "/api/queue/submit":
            route = payload["apiPath"]
            inner_payload = json.loads(payload.get("body", "{}"))
            ticket_id = self.server.next_ticket()
            self.server.tickets[ticket_id] = {
                "ticketId": ticket_id,
                "status": "Completed",
                "result": self.server.route_result(route, inner_payload),
            }
            self._write(
                202,
                {
                    "ticketId": ticket_id,
                    "status": "Queued",
                    "queuePosition": 0,
                    "agentId": payload.get("agentId", "test-agent"),
                },
            )
            return

        route = parsed.path[len("/api/") :]
        self._write(200, self.server.route_result(route, payload))

    def _write(self, status_code: int, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class FullE2ETests(unittest.TestCase):
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

    def run_cli(self, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
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
            timeout=20,
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

    def test_instances_and_select_persist_session(self) -> None:
        result = self.run_cli("--json", "instances")
        payload = json.loads(result.stdout.strip())
        self.assertEqual(payload["totalCount"], 1)
        self.assertEqual(payload["instances"][0]["port"], self.port)

        select_result = self.run_cli("--json", "select", str(self.port))
        selection = json.loads(select_result.stdout.strip())
        self.assertTrue(selection["success"])
        session = json.loads(self.session_path.read_text(encoding="utf-8"))
        self.assertEqual(session["selected_port"], self.port)

    def test_select_surfaces_cached_project_memory(self) -> None:
        self.run_cli("--json", "select", str(self.port))
        self.run_cli("--json", "memory", "remember", "structure", "render_pipeline", "URP")
        self.run_cli("--json", "memory", "remember", "structure", "_internal_note", "hidden")
        self.run_cli(
            "--json",
            "memory",
            "remember-fix",
            "CS0246",
            "cli-anything-unity-mcp --json debug doctor",
            "--context",
            "Missing namespace or package.",
        )

        select_result = self.run_cli("--json", "select", str(self.port))
        payload = json.loads(select_result.stdout.strip())

        self.assertTrue(payload["success"])
        self.assertEqual(payload["memory"]["totalEntries"], 3)
        self.assertEqual(payload["memory"]["structure"]["render_pipeline"], "URP")
        self.assertNotIn("_internal_note", payload["memory"]["structure"])
        self.assertEqual(payload["memory"]["knownFixes"][0]["pattern"], "CS0246")
        self.assertEqual(
            payload["memory"]["knownFixes"][0]["fixCommand"],
            "cli-anything-unity-mcp --json debug doctor",
        )

    def test_agent_profile_commands_persist_and_expose_current_resolution(self) -> None:
        save_result = self.run_cli(
            "--json",
            "agent",
            "save",
            "reviewer",
            "--agent-id",
            "cli-anything-unity-mcp-reviewer",
            "--role",
            "reviewer",
            "--description",
            "Optional sidecar reviewer",
        )
        save_payload = json.loads(save_result.stdout.strip())
        self.assertTrue(save_payload["success"])
        self.assertEqual(save_payload["profile"]["agent_id"], "cli-anything-unity-mcp-reviewer")
        self.assertEqual(save_payload["selectedProfile"], "reviewer")

        list_result = self.run_cli("--json", "agent", "list")
        list_payload = json.loads(list_result.stdout.strip())
        self.assertEqual(list_payload["count"], 1)
        self.assertTrue(list_payload["profiles"][0]["isSelected"])

        current_result = self.run_cli("--json", "agent", "current")
        current_payload = json.loads(current_result.stdout.strip())
        self.assertEqual(current_payload["resolved"]["agentId"], "cli-anything-unity-mcp-reviewer")
        self.assertEqual(current_payload["resolved"]["profile"]["role"], "reviewer")
        self.assertEqual(current_payload["resolved"]["source"], "profile")

        status_result = self.run_cli("--json", "status")
        status_payload = json.loads(status_result.stdout.strip())
        self.assertEqual(status_payload["agent"]["agentId"], "cli-anything-unity-mcp-reviewer")
        self.assertEqual(status_payload["agent"]["profile"]["name"], "reviewer")

    def test_agent_sessions_and_logs_proxy_live_agent_routes(self) -> None:
        sessions_result = self.run_cli("--json", "agent", "sessions")
        sessions_payload = json.loads(sessions_result.stdout.strip())
        self.assertEqual(sessions_payload["count"], 2)
        self.assertEqual(sessions_payload["agents"][1]["agentId"], "cli-anything-unity-mcp-reviewer")

        log_result = self.run_cli("--json", "agent", "log", "cli-anything-unity-mcp-reviewer")
        log_payload = json.loads(log_result.stdout.strip())
        self.assertEqual(log_payload["agentId"], "cli-anything-unity-mcp-reviewer")
        self.assertEqual(log_payload["count"], 2)

    def test_agent_watch_samples_queue_sessions_logs_and_snapshot_summary(self) -> None:
        result = self.run_cli(
            "--json",
            "agent",
            "watch",
            "--iterations",
            "2",
            "--interval",
            "0",
            "--console-count",
            "10",
            "--watch-agent-id",
            "cli-anything-unity-mcp-reviewer",
        )
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["title"], "Unity Agent Watch")
        self.assertEqual(payload["watch"]["iterations"], 2)
        self.assertEqual(payload["watch"]["watchedAgentId"], "cli-anything-unity-mcp-reviewer")
        self.assertEqual(len(payload["samples"]), 2)
        self.assertEqual(payload["latest"]["queue"]["activeAgents"], 1)
        self.assertEqual(payload["latest"]["sessions"]["count"], 2)
        self.assertEqual(payload["latest"]["agentLog"]["count"], 2)
        self.assertEqual(payload["latest"]["summary"]["consoleEntryCount"], 3)

    def test_tool_command_and_default_repl_work(self) -> None:
        tool_result = self.run_cli(
            "--json",
            "tool",
            "unity_execute_code",
            "--params",
            "{\"code\":\"return 1;\"}",
        )
        payload = json.loads(tool_result.stdout.strip())
        self.assertTrue(payload["success"])
        self.assertEqual(payload["echo"], "return 1;")

        repl_result = self.run_cli("--json", input_text="scene-info\nquit\n")
        self.assertIn("Unity MCP CLI REPL", repl_result.stdout)
        self.assertIn("MainScene", repl_result.stdout)

    def test_debug_snapshot_combines_console_compilation_scene_and_queue_state(self) -> None:
        result = self.run_cli(
            "--json",
            "debug",
            "snapshot",
            "--console-count",
            "10",
            "--include-hierarchy",
        )
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["summary"]["projectName"], "Demo")
        self.assertEqual(payload["summary"]["consoleEntryCount"], 3)
        self.assertEqual(payload["summary"]["consoleHighestSeverity"], "error")
        self.assertEqual(payload["summary"]["compilationIssueCount"], 0)
        self.assertEqual(payload["queue"]["activeAgents"], 1)
        self.assertEqual(payload["consoleSummary"]["countsByType"]["warning"], 1)
        self.assertEqual(payload["console"]["entries"][2]["type"], "error")
        self.assertIn("hierarchy", payload)

    def test_debug_template_returns_recommended_commands(self) -> None:
        result = self.run_cli("--json", "debug", "template")
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["title"], "Unity CLI Debug Template")
        self.assertGreaterEqual(len(payload["recommendedCommands"]), 4)
        self.assertTrue(any("debug bridge" in command for command in payload["recommendedCommands"]))
        self.assertTrue(any("debug snapshot" in command for command in payload["recommendedCommands"]))
        self.assertIn("snapshotCommand", payload["reportTemplate"])

    def test_debug_bridge_reports_registry_discovery_and_recent_history(self) -> None:
        self.run_cli("--json", "scene-info")

        result = self.run_cli("--json", "debug", "bridge")
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["title"], "Unity Bridge Diagnostics")
        self.assertEqual(payload["summary"]["assessment"], "healthy")
        self.assertEqual(payload["summary"]["connectionMode"], "registry-backed")
        self.assertTrue(payload["summary"]["canReachUnity"])
        self.assertEqual(payload["summary"]["registryEntryCount"], 1)
        self.assertEqual(payload["summary"]["discoveredInstanceCount"], 1)
        self.assertEqual(payload["summary"]["respondingPortCount"], 1)
        self.assertEqual(payload["summary"]["selectedPort"], self.port)
        self.assertTrue(any(check["port"] == self.port and check["status"] == "ok" for check in payload["portChecks"]))
        self.assertGreaterEqual(len(payload["recentCommands"]), 1)
        self.assertTrue(any("debug doctor" in command for command in payload["recommendedCommands"]))
        self.assertIn("agent", payload)

    def test_debug_editor_log_reads_tail_and_filters_lines(self) -> None:
        editor_log = self.tmpdir / "Editor.log"
        editor_log.write_text(
            "\n".join(
                [
                    "Booting Unity editor",
                    "[AB-UMCP] Registered instance on port 7892 in registry.",
                    "Importing assets",
                    "[AB-UMCP] Server started on port 7892",
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_cli(
            "--json",
            "debug",
            "editor-log",
            "--path",
            str(editor_log),
            "--tail",
            "5",
            "--ab-umcp-only",
        )
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["title"], "Unity Editor Log")
        self.assertEqual(payload["summary"]["status"], "ok")
        self.assertEqual(payload["summary"]["matchedCount"], 2)
        self.assertEqual(payload["summary"]["returnedCount"], 2)
        self.assertEqual(len(payload["lines"]), 2)
        self.assertTrue(all("[AB-UMCP]" in line for line in payload["lines"]))
        self.assertEqual(payload["entries"][0]["lineNumber"], 2)
        self.assertTrue(payload["entries"][0]["matched"])
        self.assertIn("agent", payload)

    def test_debug_editor_log_context_includes_surrounding_reload_lines(self) -> None:
        editor_log = self.tmpdir / "Editor.log"
        editor_log.write_text(
            "\n".join(
                [
                    "Reloading assemblies after forced synchronous recompile.",
                    "Begin MonoManager ReloadAssembly",
                    "[AB-UMCP] Unregistered instance (port 7892) from registry.",
                    "[AB-UMCP] Server stopped",
                    "Refreshing native plugins compatible for Editor in 2.16 ms, found 4 plugins.",
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_cli(
            "--json",
            "debug",
            "editor-log",
            "--path",
            str(editor_log),
            "--tail",
            "10",
            "--ab-umcp-only",
            "--context",
            "1",
        )
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["summary"]["status"], "ok")
        self.assertEqual(payload["summary"]["context"], 1)
        self.assertEqual(payload["summary"]["matchedCount"], 2)
        self.assertEqual(payload["summary"]["returnedCount"], 4)
        self.assertEqual(
            [entry["lineNumber"] for entry in payload["entries"]],
            [2, 3, 4, 5],
        )
        self.assertEqual(payload["entries"][0]["text"], "Begin MonoManager ReloadAssembly")
        self.assertFalse(payload["entries"][0]["matched"])
        self.assertTrue(payload["entries"][1]["matched"])
        self.assertTrue(payload["entries"][2]["matched"])
        self.assertFalse(payload["entries"][3]["matched"])

    def test_debug_editor_log_follow_streams_plain_text_tail(self) -> None:
        editor_log = self.tmpdir / "Editor.log"
        editor_log.write_text(
            "\n".join(
                [
                    "Booting Unity editor",
                    "[AB-UMCP] Registered instance on port 7892 in registry.",
                    "Importing assets",
                    "[AB-UMCP] Server started on port 7892",
                ]
            ),
            encoding="utf-8",
        )

        result = self.run_cli(
            "debug",
            "editor-log",
            "--path",
            str(editor_log),
            "--tail",
            "5",
            "--ab-umcp-only",
            "--follow",
            "--duration",
            "0.05",
            "--poll-interval",
            "0.01",
        )

        self.assertIn("[AB-UMCP] Registered instance on port 7892 in registry.", result.stdout)
        self.assertIn("[AB-UMCP] Server started on port 7892", result.stdout)

    def test_debug_trace_reports_recent_command_status_and_filters(self) -> None:
        self.run_cli("--json", "scene-info")
        self.run_cli("--json", "console", "--count", "5")

        result = self.run_cli(
            "--json",
            "debug",
            "trace",
            "--tail",
            "5",
            "--command-contains",
            "scene",
        )
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["title"], "Unity CLI Trace")
        self.assertGreaterEqual(payload["count"], 1)
        self.assertTrue(all("scene" in entry["command"] for entry in payload["entries"]))
        self.assertTrue(all(entry["status"] == "ok" for entry in payload["entries"]))
        self.assertTrue(all("durationMs" in entry for entry in payload["entries"]))
        self.assertTrue(all("summary" in entry for entry in payload["entries"]))
        self.assertTrue(all(entry.get("commandPath") == "scene-info" for entry in payload["entries"]))
        self.assertTrue(all(entry.get("activity") == "inspecting scene info" for entry in payload["entries"]))
        self.assertTrue(all(entry.get("actor") for entry in payload["entries"]))
        self.assertTrue(all(entry.get("commandKind") == "route" for entry in payload["entries"]))
        self.assertTrue(all(entry.get("category") == "scene" for entry in payload["entries"]))
        self.assertTrue(all(entry.get("routeName") == "scene/info" for entry in payload["entries"]))
        self.assertTrue(all(entry.get("toolName") == "unity_scene_info" for entry in payload["entries"]))
        self.assertTrue(any("Inspecting scene" in str(entry["summary"]) for entry in payload["entries"]))
        self.assertIn("agent", payload)

    def test_debug_trace_can_filter_entries_by_agent_id(self) -> None:
        self.run_cli("--json", "--agent-id", "agent-alpha", "scene-info")
        self.run_cli("--json", "--agent-id", "agent-beta", "console", "--count", "5")

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

        self.assertGreaterEqual(payload["count"], 1)
        self.assertTrue(all(entry.get("agentId") == "agent-alpha" for entry in payload["entries"]))
        self.assertTrue(all(entry.get("actor") == "agent-alpha" for entry in payload["entries"]))
        self.assertTrue(all(entry.get("commandPath") == "scene-info" for entry in payload["entries"]))
        self.assertTrue(all(entry.get("activity") == "inspecting scene info" for entry in payload["entries"]))
        self.assertTrue(all(entry.get("category") == "scene" for entry in payload["entries"]))
        self.assertTrue(all(entry.get("routeName") == "scene/info" for entry in payload["entries"]))
        self.assertTrue(all(entry.get("toolName") == "unity_scene_info" for entry in payload["entries"]))

    def test_debug_trace_can_filter_entries_by_category_route_and_tool(self) -> None:
        self.run_cli("--json", "--agent-id", "agent-alpha", "scene-info")
        self.run_cli("--json", "--agent-id", "agent-alpha", "console", "--count", "5")

        category_result = self.run_cli(
            "--json",
            "debug",
            "trace",
            "--tail",
            "10",
            "--category",
            "scene",
            "--agent-id",
            "agent-alpha",
        )
        category_payload = json.loads(category_result.stdout.strip())

        self.assertGreaterEqual(category_payload["count"], 1)
        self.assertTrue(all(entry.get("category") == "scene" for entry in category_payload["entries"]))
        self.assertTrue(all(entry.get("routeName") == "scene/info" for entry in category_payload["entries"]))
        self.assertEqual(category_payload["filters"]["category"], "scene")

        route_result = self.run_cli(
            "--json",
            "debug",
            "trace",
            "--tail",
            "10",
            "--route",
            "scene/info",
            "--agent-id",
            "agent-alpha",
        )
        route_payload = json.loads(route_result.stdout.strip())

        self.assertGreaterEqual(route_payload["count"], 1)
        self.assertTrue(all(entry.get("routeName") == "scene/info" for entry in route_payload["entries"]))
        self.assertTrue(all(entry.get("toolName") == "unity_scene_info" for entry in route_payload["entries"]))
        self.assertEqual(route_payload["filters"]["route"], "scene/info")

        tool_result = self.run_cli(
            "--json",
            "debug",
            "trace",
            "--tail",
            "10",
            "--tool",
            "unity_scene_info",
            "--agent-id",
            "agent-alpha",
        )
        tool_payload = json.loads(tool_result.stdout.strip())

        self.assertGreaterEqual(tool_payload["count"], 1)
        self.assertTrue(all(entry.get("toolName") == "unity_scene_info" for entry in tool_payload["entries"]))
        self.assertTrue(all(entry.get("routeName") == "scene/info" for entry in tool_payload["entries"]))
        self.assertEqual(tool_payload["filters"]["tool"], "unity_scene_info")

    def test_debug_trace_summary_groups_recent_activity(self) -> None:
        self.run_cli("--json", "--agent-id", "agent-alpha", "scene-info")
        self.run_cli("--json", "--agent-id", "agent-alpha", "scene-info")
        self.run_cli("--json", "--agent-id", "agent-alpha", "console", "--count", "5")

        result = self.run_cli(
            "--json",
            "debug",
            "trace",
            "--summary",
            "--tail",
            "12",
            "--agent-id",
            "agent-alpha",
        )
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["title"], "Unity CLI Trace Summary")
        self.assertTrue(payload["filters"]["summary"])
        self.assertGreaterEqual(payload["groupCount"], 2)
        self.assertNotIn("entries", payload)
        self.assertIn("groups", payload)
        self.assertEqual(payload["problemCount"], 0)
        self.assertEqual(payload["problemGroups"], [])
        self.assertEqual(payload["recommendedCommands"], [])

        scene_group = next(group for group in payload["groups"] if group.get("routeName") == "scene/info")
        self.assertEqual(scene_group["category"], "scene")
        self.assertEqual(scene_group["toolName"], "unity_scene_info")
        self.assertGreaterEqual(scene_group["count"], 2)
        self.assertEqual(scene_group["lastStatus"], "ok")
        self.assertIsNotNone(scene_group["averageDurationMs"])
        self.assertIsNone(scene_group["diagnosis"])
        self.assertTrue(
            any("debug trace --route scene/info" in command for command in scene_group["suggestedNextCommands"])
        )

    def test_debug_trace_summary_renders_readable_plain_text(self) -> None:
        self.run_cli("--json", "--agent-id", "agent-alpha", "scene-info")
        self.run_cli("--json", "--agent-id", "agent-alpha", "console", "--count", "5")

        result = self.run_cli(
            "debug",
            "trace",
            "--summary",
            "--tail",
            "12",
            "--agent-id",
            "agent-alpha",
        )

        self.assertIn("Unity CLI Trace Summary", result.stdout)
        self.assertIn("No current failing groups.", result.stdout)
        self.assertIn("Recent Groups", result.stdout)
        self.assertIn("Inspecting scene info", result.stdout)
        self.assertIn("route scene/info", result.stdout)

    def test_debug_trace_summary_surfaces_problem_groups_and_next_commands(self) -> None:
        self.run_cli("--json", "select", str(self.port))
        error_result = subprocess.run(
            [
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
                "--json",
                "route",
                "scene/info",
                "--port",
                str(self.port + 5),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertNotEqual(error_result.returncode, 0)
        self.assertIn("Could not reach Unity bridge", error_result.stderr)

        summary_result = self.run_cli(
            "--json",
            "debug",
            "trace",
            "--summary",
            "--tail",
            "12",
            "--status",
            "error",
        )
        payload = json.loads(summary_result.stdout.strip())

        self.assertGreaterEqual(payload["problemCount"], 1)
        self.assertTrue(payload["recommendedCommands"])
        self.assertTrue(any("workflow inspect --port" in command for command in payload["recommendedCommands"]))
        self.assertTrue(any("debug doctor --recent-commands 8 --port" in command for command in payload["recommendedCommands"]))

        problem_group = next(group for group in payload["problemGroups"] if group.get("routeName") == "scene/info")
        self.assertEqual(problem_group["category"], "scene")
        self.assertEqual(problem_group["lastStatus"], "error")
        self.assertEqual(problem_group["errorCount"], 1)
        self.assertEqual(problem_group["diagnosis"], "Scene inspection or mutation failed recently.")
        self.assertTrue(
            any("debug trace --route scene/info" in command for command in problem_group["suggestedNextCommands"])
        )

    def test_debug_trace_summary_problem_plain_text_highlights_next_steps(self) -> None:
        self.run_cli("--json", "select", str(self.port))
        subprocess.run(
            [
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
                "--json",
                "route",
                "scene/info",
                "--port",
                str(self.port + 5),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )

        result = self.run_cli(
            "debug",
            "trace",
            "--summary",
            "--tail",
            "12",
            "--status",
            "error",
        )

        self.assertIn("Current Problems", result.stdout)
        self.assertIn("Scene inspection or mutation failed recently.", result.stdout)
        self.assertIn("Suggested Next Commands", result.stdout)
        self.assertIn("cli-anything-unity-mcp --json debug doctor --recent-commands 8 --port", result.stdout)

    def test_normal_command_emits_automatic_unity_trace_breadcrumbs(self) -> None:
        self.run_cli("--json", "--agent-id", "agent-alpha", "scene-info")

        trace_calls = [code for code in self.server.execute_code_calls if "[CLI-TRACE]" in code]

        self.assertGreaterEqual(len(trace_calls), 2)
        self.assertTrue(any("[CLI-TRACE] agent-alpha: Inspecting scene info" in code for code in trace_calls))
        self.assertTrue(any("[CLI-TRACE] agent-alpha: Finished inspecting scene info" in code for code in trace_calls))

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

    def test_internal_metadata_commands_do_not_emit_automatic_unity_trace_breadcrumbs(self) -> None:
        before = len([code for code in self.server.execute_code_calls if "[CLI-TRACE]" in code])

        self.run_cli("--json", "tool-template", "unity_scene_stats")

        after = len([code for code in self.server.execute_code_calls if "[CLI-TRACE]" in code])
        self.assertEqual(after, before)

    def test_debug_settings_can_disable_and_reenable_unity_console_breadcrumbs(self) -> None:
        disable_result = self.run_cli(
            "--json",
            "debug",
            "settings",
            "--no-unity-console-breadcrumbs",
            "--dashboard-console-count",
            "55",
        )
        disable_payload = json.loads(disable_result.stdout.strip())

        self.assertFalse(disable_payload["preferences"]["unityConsoleBreadcrumbs"])
        self.assertEqual(disable_payload["preferences"]["dashboardConsoleCount"], 55)
        self.assertEqual(disable_payload["updated"], ["dashboardConsoleCount", "unityConsoleBreadcrumbs"])

        before = len([code for code in self.server.execute_code_calls if "[CLI-TRACE]" in code])
        self.run_cli("--json", "--agent-id", "agent-alpha", "scene-info")
        after = len([code for code in self.server.execute_code_calls if "[CLI-TRACE]" in code])
        self.assertEqual(after, before)

        enable_result = self.run_cli(
            "--json",
            "debug",
            "settings",
            "--unity-console-breadcrumbs",
        )
        enable_payload = json.loads(enable_result.stdout.strip())

        self.assertTrue(enable_payload["preferences"]["unityConsoleBreadcrumbs"])
        self.assertEqual(enable_payload["preferences"]["dashboardConsoleCount"], 55)

        self.run_cli("--json", "--agent-id", "agent-alpha", "scene-info")
        final = len([code for code in self.server.execute_code_calls if "[CLI-TRACE]" in code])
        self.assertGreater(final, after)

    def test_debug_breadcrumb_emits_unity_trace_marker(self) -> None:
        result = self.run_cli(
            "--json",
            "debug",
            "breadcrumb",
            "hello from codex",
            "--level",
            "warning",
        )
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["title"], "Unity CLI Breadcrumb")
        self.assertEqual(payload["message"], "hello from codex")
        self.assertEqual(payload["level"], "warning")
        self.assertIn("[CLI-TRACE] hello from codex", payload["result"]["echo"])

    def test_debug_doctor_summarizes_problems_and_recent_commands(self) -> None:
        self.server.missing_references = [
            {
                "gameObject": "BrokenThing",
                "path": "MainScene/BrokenThing",
                "issue": "Missing script (component is null)",
                "componentIndex": 1,
            }
        ]
        self.server.is_playing = True
        self.run_cli("--json", "scene-info")

        result = self.run_cli(
            "--json",
            "debug",
            "doctor",
            "--recent-commands",
            "5",
        )
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["title"], "Unity Debug Doctor")
        self.assertEqual(payload["summary"]["assessment"], "error")
        self.assertGreaterEqual(payload["summary"]["findingCount"], 3)
        self.assertTrue(any(item["title"] == "Missing References" for item in payload["findings"]))
        self.assertTrue(any(item["title"] == "Unity Console Issues" for item in payload["findings"]))
        self.assertTrue(any(item["title"] == "Editor Still In Play Mode" for item in payload["findings"]))
        self.assertGreaterEqual(len(payload["recentCommands"]), 1)
        self.assertTrue(any("play stop" in command for command in payload["recommendedCommands"]))
        self.assertIn("snapshot", payload)

    def test_debug_watch_samples_summary_over_time(self) -> None:
        result = self.run_cli(
            "--json",
            "debug",
            "watch",
            "--iterations",
            "2",
            "--interval",
            "0",
            "--console-count",
            "10",
        )
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["title"], "Unity Debug Watch")
        self.assertEqual(payload["watch"]["iterations"], 2)
        self.assertEqual(len(payload["samples"]), 2)
        self.assertEqual(payload["latest"]["summary"]["consoleEntryCount"], 3)
        self.assertEqual(payload["latest"]["consoleSummary"]["highestSeverity"], "error")
        self.assertEqual(payload["latest"]["queue"]["activeAgents"], 1)

    def test_debug_trace_follow_streams_local_history_without_json(self) -> None:
        self.run_cli("--json", "--agent-id", "agent-alpha", "scene-info")

        result = self.run_cli(
            "debug",
            "trace",
            "--follow",
            "--history",
            "--duration",
            "0.15",
            "--tail",
            "6",
            "--agent-id",
            "agent-alpha",
        )

        self.assertIn("Watching Unity CLI trace.", result.stdout)
        self.assertIn("Inspecting scene info", result.stdout)
        self.assertIn("category scene", result.stdout)
        self.assertIn("route scene/info", result.stdout)
        self.assertIn("tool unity_scene_info", result.stdout)

    def test_debug_trace_follow_is_new_only_by_default(self) -> None:
        self.run_cli("--json", "--agent-id", "agent-alpha", "scene-info")

        result = self.run_cli(
            "debug",
            "trace",
            "--follow",
            "--duration",
            "0.15",
            "--tail",
            "6",
            "--agent-id",
            "agent-alpha",
        )

        self.assertIn("Watching Unity CLI trace.", result.stdout)
        self.assertNotIn("Inspecting scene info", result.stdout)

    def test_debug_trace_follow_rejects_json_mode(self) -> None:
        result = subprocess.run(
            [
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
                "--json",
                "debug",
                "trace",
                "--follow",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--follow is only supported without --json.", result.stderr)

    def test_debug_trace_follow_rejects_summary_mode(self) -> None:
        result = subprocess.run(
            [
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
                "debug",
                "trace",
                "--follow",
                "--summary",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--summary cannot be combined with --follow.", result.stderr)

    def test_debug_capture_saves_game_and_scene_images(self) -> None:
        output_dir = self.tmpdir / "captures"
        output_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(output_dir, ignore_errors=True))

        result = self.run_cli(
            "--json",
            "debug",
            "capture",
            "--kind",
            "both",
            "--width",
            "320",
            "--height",
            "180",
            "--label",
            "visual-check",
            "--output-dir",
            str(output_dir),
        )
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["title"], "Unity Debug Capture")
        self.assertEqual(payload["capture"]["kind"], "both")
        self.assertEqual(payload["capture"]["label"], "visual-check")
        self.assertTrue(payload["captures"]["game"]["success"])
        self.assertTrue(payload["captures"]["scene"]["success"])
        self.assertTrue(Path(payload["captures"]["game"]["path"]).exists())
        self.assertTrue(Path(payload["captures"]["scene"]["path"]).exists())

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
        result = self.run_cli(
            "--json",
            "workflow",
            "audit-advanced",
            "--timeout",
            "5",
            "--interval",
            "0.1",
        )
        payload = json.loads(result.stdout.strip())

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

    def test_tool_catalog_and_meta_tools_work(self) -> None:
        self.server.gameobjects["TerrainRoot"] = {
            "instanceId": 1,
            "components": ["Transform"],
            "component_data": {},
        }

        catalog_result = self.run_cli("--json", "advanced-tools", "--category", "terrain")
        catalog_payload = json.loads(catalog_result.stdout.strip())
        self.assertEqual(catalog_payload["category"], "terrain")
        self.assertTrue(any(tool["name"] == "unity_terrain_list" for tool in catalog_payload["tools"]))

        info_result = self.run_cli("--json", "tool-info", "unity_scene_stats")
        info_payload = json.loads(info_result.stdout.strip())
        self.assertEqual(info_payload["resolvedRoute"], "search/scene-stats")

        list_instances_result = self.run_cli("--json", "tool", "unity_list_instances")
        list_instances_payload = json.loads(list_instances_result.stdout.strip())
        self.assertEqual(list_instances_payload["totalCount"], 1)

        select_result = self.run_cli(
            "--json",
            "tool",
            "unity_select_instance",
            "--params",
            json.dumps({"port": self.port}),
        )
        select_payload = json.loads(select_result.stdout.strip())
        self.assertTrue(select_payload["success"])
        self.assertEqual(select_payload["instance"]["port"], self.port)

        list_advanced_result = self.run_cli(
            "--json",
            "tool",
            "unity_list_advanced_tools",
            "--params",
            "{\"category\":\"terrain\"}",
        )
        list_advanced_payload = json.loads(list_advanced_result.stdout.strip())
        self.assertEqual(list_advanced_payload["category"], "terrain")

        advanced_tool_result = self.run_cli(
            "--json",
            "tool",
            "unity_advanced_tool",
            "--params",
            "{\"tool\":\"unity_scene_stats\",\"params\":{}}",
        )
        advanced_payload = json.loads(advanced_tool_result.stdout.strip())
        self.assertEqual(advanced_payload["sceneName"], "MainScene")
        self.assertEqual(advanced_payload["totalGameObjects"], 1)

        console_tool_result = self.run_cli("--json", "tool", "unity_console_log", "--params", "{\"count\":1}")
        console_tool_payload = json.loads(console_tool_result.stdout.strip())
        self.assertGreaterEqual(console_tool_payload["count"], 1)

        agents_tool_result = self.run_cli("--json", "tool", "unity_agents_list")
        agents_tool_payload = json.loads(agents_tool_result.stdout.strip())
        self.assertGreaterEqual(agents_tool_payload["count"], 1)

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
        transition = call_tool(
            "unity_animation_add_transition",
            {"controllerPath": controller_path, "destinationState": "Idle", "duration": 0.2},
        )
        self.assertEqual(clip["path"], clip_path)
        self.assertEqual(controller["path"], controller_path)
        self.assertEqual(curve["propertyName"], "localPosition.x")
        self.assertEqual(event["event"]["functionName"], "OnMockEvent")
        self.assertEqual(events["events"][0]["functionName"], "OnMockEvent")
        self.assertEqual(len(keyframes["keyframes"]), 2)
        self.assertEqual(clip_info["eventCount"], 1)
        self.assertEqual(parameter["parameter"]["name"], "Speed")
        self.assertEqual(transition["transition"]["destinationState"], "Idle")

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
        remove_trans = call_tool("unity_animation_remove_transition", {"controllerPath": controller_path, "destinationState": "Idle"})
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
        remove_layer = call_tool("unity_animation_remove_layer", {"controllerPath": controller_path, "layerIndex": 0})
        self.assertFalse(remove_layer["layerRemoved"])  # no layers added yet, so nothing to remove

        # ── Prefab mock coverage ─────────────────────────────────────────
        prefab_path = "Assets/MockOnly/MockPrefab.prefab"
        variant_path = "Assets/MockOnly/MockPrefabVariant.prefab"
        # seed the prefab store so prefab/info, hierarchy, etc. find it
        self.server.prefabs[prefab_path] = {"name": "MockPrefab", "components": ["Transform", "BoxCollider"], "isVariant": False}
        prefab_info = call_tool("unity_prefab_info", {"path": prefab_path})
        self.assertEqual(prefab_info["name"], "MockPrefab")
        self.assertFalse(prefab_info["isVariant"])
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

    def test_tool_coverage_command_reports_live_tested_summary(self) -> None:
        summary_result = self.run_cli("--json", "tool-coverage", "--summary")
        category_result = self.run_cli("--json", "tool-coverage", "--category", "terrain")
        next_batch_result = self.run_cli(
            "--json",
            "tool-coverage",
            "--category",
            "amplify",
            "--status",
            "deferred",
            "--summary",
            "--next-batch",
            "2",
        )
        fixture_plan_result = self.run_cli(
            "--json",
            "tool-coverage",
            "--status",
            "deferred",
            "--summary",
            "--fixture-plan",
        )
        support_plan_result = self.run_cli(
            "--json",
            "tool-coverage",
            "--status",
            "unsupported",
            "--summary",
            "--support-plan",
        )
        handoff_plan_result = self.run_cli(
            "--json",
            "tool-coverage",
            "--summary",
            "--handoff-plan",
        )

        summary_payload = json.loads(summary_result.stdout.strip())
        category_payload = json.loads(category_result.stdout.strip())
        next_batch_payload = json.loads(next_batch_result.stdout.strip())
        fixture_plan_payload = json.loads(fixture_plan_result.stdout.strip())
        support_plan_payload = json.loads(support_plan_result.stdout.strip())
        handoff_plan_payload = json.loads(handoff_plan_result.stdout.strip())

        self.assertIn("summary", summary_payload)
        self.assertGreater(summary_payload["summary"]["countsByStatus"]["live-tested"], 0)
        self.assertTrue(any(tool["name"] == "unity_terrain_create" for tool in category_payload["tools"]))
        terrain_create = next(
            tool for tool in category_payload["tools"] if tool["name"] == "unity_terrain_create"
        )
        self.assertEqual(terrain_create["coverageStatus"], "live-tested")
        self.assertNotIn("tools", next_batch_payload)
        self.assertEqual(next_batch_payload["summary"]["filters"]["nextBatchLimit"], 2)
        self.assertGreaterEqual(len(next_batch_payload["nextBatch"]), 1)
        self.assertLessEqual(len(next_batch_payload["nextBatch"]), 2)
        self.assertEqual(next_batch_payload["nextBatch"][0]["coverageStatus"], "deferred")
        self.assertIn("handoffPrompt", next_batch_payload["nextBatch"][0])
        fixture_plans = {plan["category"]: plan for plan in fixture_plan_payload["fixturePlans"]}
        self.assertEqual(sorted(fixture_plans), ["amplify", "uma"])
        self.assertEqual(fixture_plans["amplify"]["package"], "Amplify Shader Editor")
        self.assertIn("unity_amplify_status", fixture_plans["amplify"]["preflight"])
        self.assertIn("--next-batch 10", fixture_plans["amplify"]["recommendedCommands"][0])
        support_plans = {plan["category"]: plan for plan in support_plan_payload["supportPlans"]}
        self.assertEqual(sorted(support_plans), ["hub"])
        self.assertEqual(support_plans["hub"]["coverageBlocker"], "unity-hub-integration")
        self.assertIn("unity_hub_list_editors", {tool["name"] for tool in support_plans["hub"]["tools"]})
        handoff_tracks = {track["name"]: track for track in handoff_plan_payload["handoffPlan"]["tracks"]}
        self.assertEqual(handoff_plan_payload["handoffPlan"]["remainingToolCount"], 44)
        self.assertEqual(sorted(handoff_tracks), ["optional-package-live-audits", "unity-hub-backend"])
        self.assertIn("--fixture-plan", handoff_tracks["optional-package-live-audits"]["nextCommand"])
        self.assertIn("--support-plan", handoff_tracks["unity-hub-backend"]["nextCommand"])

    def test_mcp_server_lists_tools_and_executes_curated_calls(self) -> None:
        process = self.start_mcp_server()

        tools_result = self.call_mcp(process, 2, "tools/list")
        tool_names = {tool["name"] for tool in tools_result["tools"]}
        self.assertIn("unity_tool_call", tool_names)
        self.assertIn("unity_audit_advanced", tool_names)
        self.assertNotIn("unity_build_sample", tool_names)
        self.assertNotIn("unity_build_fps_sample", tool_names)

        instances_result = self.call_mcp(process, 3, "tools/call", {"name": "unity_instances"})
        self.assertFalse(instances_result["isError"])
        self.assertEqual(instances_result["structuredContent"]["totalCount"], 1)

        inspect_result = self.call_mcp(
            process,
            4,
            "tools/call",
            {"name": "unity_inspect", "arguments": {"assetLimit": 5}},
        )
        self.assertFalse(inspect_result["isError"])
        self.assertEqual(inspect_result["structuredContent"]["summary"]["projectName"], "Demo")

        tool_call_result = self.call_mcp(
            process,
            5,
            "tools/call",
            {
                "name": "unity_tool_call",
                "arguments": {
                    "toolName": "unity_execute_code",
                    "params": {"code": "return 1;"},
                },
            },
        )
        self.assertFalse(tool_call_result["isError"])
        self.assertTrue(tool_call_result["structuredContent"]["success"])
        self.assertEqual(tool_call_result["structuredContent"]["echo"], "return 1;")

    def test_mcp_server_curated_tool_matrix_covers_workflow_surface(self) -> None:
        process = self.start_mcp_server()

        select_result = self.call_mcp(
            process,
            10,
            "tools/call",
            {"name": "unity_select_instance", "arguments": {"port": self.port}},
        )
        self.assertFalse(select_result["isError"])
        self.assertEqual(select_result["structuredContent"]["instance"]["port"], self.port)

        console_result = self.call_mcp(
            process,
            11,
            "tools/call",
            {"name": "unity_console", "arguments": {"count": 5}},
        )
        self.assertFalse(console_result["isError"])
        self.assertEqual(console_result["structuredContent"]["count"], 3)
        self.assertEqual(console_result["structuredContent"]["entries"][0]["type"], "info")

        validate_result = self.call_mcp(
            process,
            12,
            "tools/call",
            {"name": "unity_validate_scene", "arguments": {"includeHierarchy": True}},
        )
        self.assertFalse(validate_result["isError"])
        self.assertIn("summary", validate_result["structuredContent"])
        self.assertIn("hierarchy", validate_result["structuredContent"])

        create_holder_result = self.call_mcp(
            process,
            13,
            "tools/call",
            {
                "name": "unity_create_behaviour",
                "arguments": {
                    "name": "ReferenceHolder",
                    "objectName": "McpHolder",
                    "folder": "Assets/McpPass",
                },
            },
        )
        self.assertFalse(create_holder_result["isError"])
        self.assertEqual(create_holder_result["structuredContent"]["className"], "ReferenceHolder")

        create_target_result = self.call_mcp(
            process,
            14,
            "tools/call",
            {
                "name": "unity_tool_call",
                "arguments": {
                    "toolName": "unity_gameobject_create",
                    "params": {"name": "McpTarget", "primitiveType": "Empty"},
                },
            },
        )
        self.assertFalse(create_target_result["isError"])
        self.assertEqual(create_target_result["structuredContent"]["name"], "McpTarget")

        wire_result = self.call_mcp(
            process,
            15,
            "tools/call",
            {
                "name": "unity_wire_reference",
                "arguments": {
                    "targetObject": "McpHolder",
                    "componentType": "ReferenceHolder",
                    "propertyName": "TargetRef",
                    "referenceObject": "McpTarget",
                },
            },
        )
        self.assertFalse(wire_result["isError"])
        self.assertEqual(wire_result["structuredContent"]["result"]["referenceName"], "McpTarget")

        prefab_result = self.call_mcp(
            process,
            16,
            "tools/call",
            {
                "name": "unity_create_prefab",
                "arguments": {
                    "gameObject": "McpTarget",
                    "instantiate": True,
                    "instanceName": "McpClone",
                },
            },
        )
        self.assertFalse(prefab_result["isError"])
        self.assertEqual(prefab_result["structuredContent"]["instance"]["name"], "McpClone")

        advanced_tools_result = self.call_mcp(
            process,
            17,
            "tools/call",
            {"name": "unity_advanced_tools", "arguments": {"category": "terrain"}},
        )
        self.assertFalse(advanced_tools_result["isError"])
        self.assertEqual(advanced_tools_result["structuredContent"]["category"], "terrain")

        tool_info_result = self.call_mcp(
            process,
            18,
            "tools/call",
            {"name": "unity_tool_info", "arguments": {"toolName": "unity_scene_stats"}},
        )
        self.assertFalse(tool_info_result["isError"])
        self.assertEqual(tool_info_result["structuredContent"]["resolvedRoute"], "search/scene-stats")

        scene_stats_result = self.call_mcp(
            process,
            19,
            "tools/call",
            {
                "name": "unity_tool_call",
                "arguments": {
                    "toolName": "unity_scene_stats",
                    "params": {},
                },
            },
        )
        self.assertFalse(scene_stats_result["isError"])
        self.assertEqual(scene_stats_result["structuredContent"]["sceneName"], "MainScene")

        audit_result = self.call_mcp(
            process,
            20,
            "tools/call",
            {
                "name": "unity_audit_advanced",
                "arguments": {
                    "categories": ["graphics", "physics", "settings"],
                    "saveIfDirtyStart": True,
                },
            },
        )
        self.assertFalse(audit_result["isError"])
        self.assertEqual(audit_result["structuredContent"]["summary"]["failed"], 0)

        play_result = self.call_mcp(
            process,
            21,
            "tools/call",
            {"name": "unity_play", "arguments": {"action": "play", "wait": True}},
        )
        self.assertFalse(play_result["isError"])
        self.assertTrue(play_result["structuredContent"]["state"]["isPlaying"])

        stop_result = self.call_mcp(
            process,
            22,
            "tools/call",
            {"name": "unity_play", "arguments": {"action": "stop", "wait": True}},
        )
        self.assertFalse(stop_result["isError"])
        self.assertFalse(stop_result["structuredContent"]["state"]["isPlaying"])

        reset_result = self.call_mcp(
            process,
            23,
            "tools/call",
            {"name": "unity_reset_scene", "arguments": {"discardUnsaved": True}},
        )
        self.assertFalse(reset_result["isError"])
        self.assertTrue(reset_result["structuredContent"]["result"]["success"])
