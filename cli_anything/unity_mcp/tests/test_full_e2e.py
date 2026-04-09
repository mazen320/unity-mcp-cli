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
        self.gameobjects = {}
        self.scripts = {}
        self.prefabs = {}
        self.materials = {}
        self.missing_references = []

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
            self.active_scene_name = "Untitled"
            self.active_scene_path = "Assets/Scenes/Untitled.unity"
            self.scene_dirty = False
            self.gameobjects = {}
            return {"success": True, "name": self.active_scene_name, "path": self.active_scene_path}
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
                    {"timestamp": "2026-04-09T00:00:05Z", "action": "build-sample", "status": "completed"},
                ],
            }
        if route == "editor/execute-code":
            generated_layout = self._create_2d_sample_layout_from_code(str(payload.get("code") or ""))
            if generated_layout is not None:
                return generated_layout
            generated_fps_scene = self._create_3d_fps_scene_from_code(str(payload.get("code") or ""))
            if generated_fps_scene is not None:
                return generated_fps_scene
            return {
                "success": True,
                "echo": payload.get("code"),
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
                    ],
                    "totalRoutes": 39,
                },
            )
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
        result = subprocess.run(
            command,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=20,
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
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
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
        self.assertIn("debug snapshot", payload["recommendedCommands"][1])
        self.assertIn("snapshotCommand", payload["reportTemplate"])

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

    def test_workflow_smoke_test_cleans_up_after_itself(self) -> None:
        result = self.run_cli(
            "--json",
            "workflow",
            "smoke-test",
            "--prefix",
            "SmokeProbe",
            "--folder",
            "Assets/Tests",
            "--timeout",
            "5",
            "--interval",
            "0.1",
        )
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["before"]["scenePath"], "Assets/Scenes/MainScene.unity")
        self.assertTrue(payload["cleanup"]["sceneReset"]["success"])
        self.assertTrue(payload["cleanup"]["script"]["success"])
        self.assertTrue(payload["cleanup"]["gameObject"]["success"])
        self.assertFalse(payload["after"]["editorState"]["sceneDirty"])
        self.assertFalse(payload["after"]["editorState"]["isPlaying"])

    def test_workflow_build_sample_creates_and_cleans_up_demo_slice(self) -> None:
        result = self.run_cli(
            "--json",
            "workflow",
            "build-sample",
            "--name",
            "ArenaProbe",
            "--cleanup",
            "--timeout",
            "5",
            "--interval",
            "0.1",
        )
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["summary"]["sampleId"], "ArenaProbe")
        self.assertEqual(payload["summary"]["captureMode"], "both")
        self.assertEqual(payload["validation"]["stats"]["totalGameObjects"], 6)
        self.assertEqual(payload["objects"]["beaconClone"]["name"], "ArenaProbe_BeaconClone")
        self.assertEqual(payload["objects"]["beaconClone"]["position"]["x"], -4.0)
        self.assertEqual(payload["wiring"]["observerTarget"]["referenceName"], "ArenaProbe_Player")
        self.assertTrue(payload["captures"]["game"]["success"])
        self.assertTrue(payload["captures"]["scene"]["success"])
        self.assertTrue(Path(payload["captures"]["game"]["path"]).exists())
        self.assertTrue(Path(payload["captures"]["scene"]["path"]).exists())
        self.assertTrue(payload["playMode"]["enter"]["state"]["isPlaying"])
        self.assertTrue(payload["cleanup"]["sceneReset"]["success"])
        self.assertEqual(len(payload["cleanup"]["assets"]), 4)
        self.assertFalse(payload["after"]["editorState"]["sceneDirty"])

    def test_workflow_build_sample_auto_detects_2d_scene_and_uses_hierarchy_paths(self) -> None:
        self.server._register_gameobject(
            "Global Light 2D",
            components=["Transform", "Light2D"],
        )

        result = self.run_cli(
            "--json",
            "workflow",
            "build-sample",
            "--name",
            "Arena2D",
            "--cleanup",
            "--no-play-check",
            "--timeout",
            "5",
            "--interval",
            "0.1",
        )
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["summary"]["visualMode"], "2d")
        self.assertTrue(payload["captures"]["game"]["success"])
        self.assertTrue(payload["captures"]["scene"]["success"])
        self.assertEqual(payload["objects"]["floor"]["hierarchyPath"], "Arena2D/Arena2D_Floor")
        self.assertEqual(payload["objects"]["beaconClone"]["position"]["x"], -4.8)
        self.assertEqual(payload["wiring"]["observerTarget"]["referenceName"], "Arena2D_Player")
        self.assertGreaterEqual(payload["validation"]["stats"]["totalGameObjects"], 10)
        self.assertTrue(payload["cleanup"]["sceneReset"]["success"])
        self.assertFalse(payload["after"]["editorState"]["sceneDirty"])

    def test_workflow_build_fps_sample_creates_new_scene_with_captures(self) -> None:
        result = self.run_cli(
            "--json",
            "workflow",
            "build-fps-sample",
            "--name",
            "ArenaFps",
            "--scene-path",
            "Assets/Scenes/ArenaFps.unity",
            "--verify-level",
            "deep",
            "--capture-width",
            "320",
            "--capture-height",
            "180",
            "--timeout",
            "5",
            "--interval",
            "0.1",
        )
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["summary"]["sampleId"], "ArenaFps")
        self.assertEqual(payload["summary"]["scenePath"], "Assets/Scenes/ArenaFps.unity")
        self.assertTrue(payload["summary"]["sceneCreated"])
        self.assertEqual(payload["validation"]["scene"]["activeScene"], "ArenaFps")
        self.assertEqual(payload["objects"]["player"]["hierarchyPath"], "ArenaFps/ArenaFps_Player")
        self.assertEqual(payload["objects"]["camera"]["hierarchyPath"], "ArenaFps/ArenaFps_Player/MainCamera")
        self.assertEqual(payload["objects"]["hud"]["hierarchyPath"], "ArenaFps/ArenaFps_HUD")
        self.assertEqual(payload["validation"]["floorMaterial"]["materialName"], "ArenaFpsFloor")
        self.assertTrue(payload["captures"]["game"]["success"])
        self.assertTrue(payload["captures"]["scene"]["success"])
        self.assertTrue(payload["playMode"]["enter"]["state"]["isPlaying"])
        self.assertFalse(payload["after"]["editorState"]["sceneDirty"])

    def test_workflow_build_fps_sample_quick_mode_reuses_unchanged_script(self) -> None:
        self.run_cli(
            "--json",
            "workflow",
            "build-fps-sample",
            "--name",
            "ArenaFpsFast",
            "--scene-path",
            "Assets/Scenes/ArenaFpsFast.unity",
            "--verify-level",
            "quick",
            "--timeout",
            "5",
            "--interval",
            "0.1",
        )

        result = self.run_cli(
            "--json",
            "workflow",
            "build-fps-sample",
            "--name",
            "ArenaFpsFast",
            "--scene-path",
            "Assets/Scenes/ArenaFpsFast.unity",
            "--verify-level",
            "quick",
            "--timeout",
            "5",
            "--interval",
            "0.1",
        )
        payload = json.loads(result.stdout.strip())

        self.assertEqual(payload["summary"]["verifyLevel"], "quick")
        self.assertEqual(payload["summary"]["captureMode"], "none")
        self.assertFalse(payload["summary"]["playCheckRequested"])
        self.assertEqual(payload["script"]["status"], "unchanged")
        self.assertTrue(payload["script"]["skippedWrite"])
        self.assertTrue(payload["compilation"]["skipped"])
        self.assertEqual(payload["captures"], {})
        self.assertNotIn("playMode", payload)
        self.assertEqual(set(payload["validation"].keys()), {"scene", "editorState"})
        self.assertFalse(payload["after"]["editorState"]["sceneDirty"])

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

    def test_tool_coverage_command_reports_live_tested_summary(self) -> None:
        summary_result = self.run_cli("--json", "tool-coverage", "--summary")
        category_result = self.run_cli("--json", "tool-coverage", "--category", "terrain")

        summary_payload = json.loads(summary_result.stdout.strip())
        category_payload = json.loads(category_result.stdout.strip())

        self.assertIn("summary", summary_payload)
        self.assertGreater(summary_payload["summary"]["countsByStatus"]["live-tested"], 0)
        self.assertTrue(any(tool["name"] == "unity_terrain_create" for tool in category_payload["tools"]))
        terrain_create = next(
            tool for tool in category_payload["tools"] if tool["name"] == "unity_terrain_create"
        )
        self.assertEqual(terrain_create["coverageStatus"], "live-tested")

    def test_workflow_scaffold_test_project_creates_disposable_unity_project(self) -> None:
        project_path = self.tmpdir / "UnityMcpCliSmokeProject"
        plugin_path = self.tmpdir / "unity-mcp-plugin"
        plugin_path.mkdir(parents=True, exist_ok=True)
        (plugin_path / "package.json").write_text(
            json.dumps({"name": "com.anklebreaker.unity-mcp", "version": "2.26.0"}),
            encoding="utf-8",
        )

        result = self.run_cli(
            "--json",
            "workflow",
            "scaffold-test-project",
            "--project-path",
            str(project_path),
            "--plugin-source",
            "local",
            "--plugin-path",
            str(plugin_path),
        )

        payload = json.loads(result.stdout.strip())
        self.assertEqual(payload["pluginSource"], "local")
        self.assertEqual(payload["starterScenePath"], "Assets/Scenes/CodexCliSmoke.unity")
        self.assertTrue((project_path / "Packages" / "manifest.json").exists())
        self.assertTrue((project_path / "ProjectSettings" / "ProjectVersion.txt").exists())
        self.assertTrue((project_path / "Assets" / "Editor" / "CodexCliTestProjectBootstrap.cs").exists())
        self.assertTrue((project_path / "CLI_TEST_COMMANDS.md").exists())

        manifest = json.loads((project_path / "Packages" / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("com.anklebreaker.unity-mcp", manifest["dependencies"])
        self.assertTrue(str(manifest["dependencies"]["com.anklebreaker.unity-mcp"]).startswith("file:"))

        bootstrap = (project_path / "Assets" / "Editor" / "CodexCliTestProjectBootstrap.cs").read_text(
            encoding="utf-8"
        )
        self.assertIn("CodexCliSmoke.unity", bootstrap)
        self.assertIn("SmokeCube", bootstrap)

    def test_mcp_server_lists_tools_and_executes_curated_calls(self) -> None:
        process = self.start_mcp_server()

        tools_result = self.call_mcp(process, 2, "tools/list")
        tool_names = {tool["name"] for tool in tools_result["tools"]}
        self.assertIn("unity_build_sample", tool_names)
        self.assertIn("unity_build_fps_sample", tool_names)
        self.assertIn("unity_tool_call", tool_names)

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

        build_result = self.call_mcp(
            process,
            5,
            "tools/call",
            {
                "name": "unity_build_sample",
                "arguments": {
                    "name": "McpProbeArena",
                    "cleanup": True,
                    "capture": "none",
                    "playCheck": False,
                },
            },
        )
        self.assertFalse(build_result["isError"])
        self.assertEqual(build_result["structuredContent"]["summary"]["sampleName"], "McpProbeArena")

        tool_call_result = self.call_mcp(
            process,
            6,
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

        build_sample_result = self.call_mcp(
            process,
            20,
            "tools/call",
            {
                "name": "unity_build_sample",
                "arguments": {
                    "name": "McpMatrixArena",
                    "cleanup": True,
                    "capture": "none",
                    "playCheck": False,
                    "saveIfDirtyStart": True,
                },
            },
        )
        self.assertFalse(build_sample_result["isError"])
        self.assertEqual(build_sample_result["structuredContent"]["summary"]["sampleName"], "McpMatrixArena")

        build_fps_result = self.call_mcp(
            process,
            21,
            "tools/call",
            {
                "name": "unity_build_fps_sample",
                "arguments": {
                    "name": "McpFpsMatrix",
                    "scenePath": "Assets/Scenes/McpFpsMatrix.unity",
                    "folder": "Assets/McpPass/FPS",
                    "replace": True,
                    "verifyLevel": "quick",
                    "playCheck": False,
                    "capture": "none",
                },
            },
        )
        self.assertFalse(build_fps_result["isError"])
        self.assertEqual(build_fps_result["structuredContent"]["summary"]["verifyLevel"], "quick")

        audit_result = self.call_mcp(
            process,
            22,
            "tools/call",
            {
                "name": "unity_audit_advanced",
                "arguments": {
                    "categories": ["graphics", "physics", "settings"],
                },
            },
        )
        self.assertFalse(audit_result["isError"])
        self.assertEqual(audit_result["structuredContent"]["summary"]["failed"], 0)

        play_result = self.call_mcp(
            process,
            23,
            "tools/call",
            {"name": "unity_play", "arguments": {"action": "play", "wait": True}},
        )
        self.assertFalse(play_result["isError"])
        self.assertTrue(play_result["structuredContent"]["state"]["isPlaying"])

        stop_result = self.call_mcp(
            process,
            24,
            "tools/call",
            {"name": "unity_play", "arguments": {"action": "stop", "wait": True}},
        )
        self.assertFalse(stop_result["isError"])
        self.assertFalse(stop_result["structuredContent"]["state"]["isPlaying"])

        reset_result = self.call_mcp(
            process,
            25,
            "tools/call",
            {"name": "unity_reset_scene", "arguments": {"discardUnsaved": True}},
        )
        self.assertFalse(reset_result["isError"])
        self.assertTrue(reset_result["structuredContent"]["result"]["success"])
