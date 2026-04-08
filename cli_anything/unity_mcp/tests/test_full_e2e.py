from __future__ import annotations

import json
import os
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


def get_cli_command() -> list[str]:
    override = os.environ.get("CLI_ANYTHING_UNITY_MCP_BIN")
    if override:
        return [override]
    for name in ("cli-anything-unity-mcp.exe", "cli-anything-unity-mcp"):
        found = shutil.which(name)
        if found:
            return [found]
    return [sys.executable, "-m", "cli_anything.unity_mcp"]


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
        self.missing_references = []

    def _resolve_gameobject_name(self, payload: dict) -> str | None:
        raw_name = payload.get("gameObjectPath") or payload.get("path") or payload.get("name")
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
            self.gameobjects[name] = {
                "instanceId": len(self.gameobjects) + 1,
                "components": ["Transform"],
                "component_data": {},
                "position": self._vec3(payload.get("position")),
                "rotation": self._vec3(payload.get("rotation")),
                "scale": self._vec3(payload.get("scale"), default=(1.0, 1.0, 1.0)),
                "parent": parent if parent in self.gameobjects else None,
                "primitiveType": str(payload.get("primitiveType") or "Empty"),
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
            reference_name = str(payload.get("referenceGameObject") or "")
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
                "parent": payload.get("parent") if payload.get("parent") in self.gameobjects else None,
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
        if route == "compilation/errors":
            return {"count": 0, "isCompiling": False, "entries": []}
        if route == "editor/execute-code":
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
                        "compilation/errors",
                        "editor/state",
                        "editor/play-mode",
                        "editor/execute-code",
                        "undo/perform",
                    ],
                    "totalRoutes": 25,
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
        self.assertEqual(payload["validation"]["stats"]["totalGameObjects"], 6)
        self.assertEqual(payload["objects"]["beaconClone"]["name"], "ArenaProbe_BeaconClone")
        self.assertEqual(payload["objects"]["beaconClone"]["position"]["x"], -4.0)
        self.assertEqual(payload["wiring"]["observerTarget"]["referenceName"], "ArenaProbe_Player")
        self.assertTrue(payload["playMode"]["enter"]["state"]["isPlaying"])
        self.assertTrue(payload["cleanup"]["sceneReset"]["success"])
        self.assertEqual(len(payload["cleanup"]["assets"]), 4)
        self.assertFalse(payload["after"]["editorState"]["sceneDirty"])

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
