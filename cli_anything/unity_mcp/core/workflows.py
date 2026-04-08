from __future__ import annotations

import posixpath
import re
import time
from datetime import UTC, datetime
from typing import Any, Callable, Dict


def wait_for_result(
    fetch_value: Callable[[], Dict[str, Any]],
    predicate: Callable[[Dict[str, Any]], bool],
    timeout: float = 20.0,
    interval: float = 0.25,
) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_value: Dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last_value = fetch_value()
        if predicate(last_value):
            return last_value
        time.sleep(interval)
    return last_value or fetch_value()


def wait_for_editor_state(
    fetch_state: Callable[[], Dict[str, Any]],
    predicate: Callable[[Dict[str, Any]], bool],
    timeout: float = 20.0,
    interval: float = 0.25,
) -> Dict[str, Any]:
    return wait_for_result(fetch_state, predicate, timeout=timeout, interval=interval)


def wait_for_compilation(
    fetch_status: Callable[[], Dict[str, Any]],
    timeout: float = 30.0,
    interval: float = 0.5,
) -> Dict[str, Any]:
    return wait_for_result(
        fetch_status,
        lambda status: not bool((status or {}).get("isCompiling")),
        timeout=timeout,
        interval=interval,
    )


def sanitize_csharp_identifier(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "", value or "")
    if not cleaned:
        raise ValueError("A non-empty C# identifier is required.")
    if cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned


def normalize_asset_folder(value: str | None, default: str = "Assets/Scripts") -> str:
    folder = (value or default).replace("\\", "/").strip()
    if not folder:
        folder = default
    folder = folder.strip("/")
    if not folder.lower().startswith("assets"):
        folder = f"Assets/{folder}"
    return folder.rstrip("/")


def build_asset_path(folder: str | None, leaf_name: str, extension: str = ".cs") -> str:
    normalized_folder = normalize_asset_folder(folder)
    suffix = extension if leaf_name.endswith(extension) else f"{leaf_name}{extension}"
    return posixpath.join(normalized_folder, suffix)


def get_active_scene_path(scene_info: Dict[str, Any]) -> str:
    active_name = str(scene_info.get("activeScene") or "")
    scenes = scene_info.get("scenes") or []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        if scene.get("name") == active_name and scene.get("path"):
            return str(scene["path"])
    for scene in scenes:
        if isinstance(scene, dict) and scene.get("path"):
            return str(scene["path"])
    raise ValueError("Could not determine the active scene path from Unity.")


def build_behaviour_script(class_name: str, namespace: str | None = None) -> str:
    header = "using UnityEngine;\n\n"
    body = (
        f"public class {class_name} : MonoBehaviour\n"
        "{\n"
        f"    public string Label = \"{class_name}\";\n"
        "    public int Count = 1;\n"
        "}\n"
    )
    if namespace:
        return (
            header
            + f"namespace {namespace}\n"
            + "{\n"
            + f"    public class {class_name} : MonoBehaviour\n"
            + "    {\n"
            + f"        public string Label = \"{class_name}\";\n"
            + "        public int Count = 1;\n"
            + "    }\n"
            + "}\n"
        )
    return header + body


def build_demo_spin_script(class_name: str) -> str:
    return (
        "using UnityEngine;\n\n"
        f"public class {class_name} : MonoBehaviour\n"
        "{\n"
        "    public Vector3 Axis = new Vector3(0f, 1f, 0f);\n"
        "    public float Speed = 90f;\n\n"
        "    private void Update()\n"
        "    {\n"
        "        transform.Rotate(Axis, Speed * Time.deltaTime, Space.World);\n"
        "    }\n"
        "}\n"
    )


def build_demo_bob_script(class_name: str) -> str:
    return (
        "using UnityEngine;\n\n"
        f"public class {class_name} : MonoBehaviour\n"
        "{\n"
        "    public float Height = 0.35f;\n"
        "    public float Speed = 2f;\n\n"
        "    private Vector3 _basePosition;\n\n"
        "    private void Awake()\n"
        "    {\n"
        "        _basePosition = transform.position;\n"
        "    }\n\n"
        "    private void Update()\n"
        "    {\n"
        "        float offset = Mathf.Sin(Time.time * Speed) * Height;\n"
        "        transform.position = _basePosition + new Vector3(0f, offset, 0f);\n"
        "    }\n"
        "}\n"
    )


def build_demo_follow_script(class_name: str) -> str:
    return (
        "using UnityEngine;\n\n"
        f"public class {class_name} : MonoBehaviour\n"
        "{\n"
        "    public Transform Target;\n"
        "    public Vector3 Offset = new Vector3(0f, 5f, -8f);\n\n"
        "    private void LateUpdate()\n"
        "    {\n"
        "        if (Target == null)\n"
        "        {\n"
        "            return;\n"
        "        }\n\n"
        "        transform.position = Target.position + Offset;\n"
        "        transform.LookAt(Target.position);\n"
        "    }\n"
        "}\n"
    )


def vec3(x: float, y: float, z: float) -> Dict[str, float]:
    return {"x": float(x), "y": float(y), "z": float(z)}


def workflow_error_message(payload: Any) -> str | None:
    if isinstance(payload, dict):
        error = payload.get("error")
        if error:
            return str(error)
        if payload.get("success") is False:
            message = payload.get("message")
            return str(message) if message else "Operation returned success=false."
    return None


def require_workflow_success(payload: Any, action: str) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{action} failed: unexpected response shape.")
    error = workflow_error_message(payload)
    if error:
        raise ValueError(f"{action} failed: {error}")
    return payload


def unique_probe_name(prefix: str) -> str:
    return f"{sanitize_csharp_identifier(prefix)}_{datetime.now(UTC).strftime('%H%M%S')}"
