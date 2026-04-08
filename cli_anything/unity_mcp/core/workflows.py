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


def escape_csharp_string(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def build_demo_fps_controller_script(class_name: str) -> str:
    return (
        "using UnityEngine;\n"
        "#if ENABLE_INPUT_SYSTEM\n"
        "using UnityEngine.InputSystem;\n"
        "#endif\n\n"
        "[RequireComponent(typeof(CharacterController))]\n"
        f"public class {class_name} : MonoBehaviour\n"
        "{\n"
        "    public float MoveSpeed = 6.5f;\n"
        "    public float SprintSpeed = 9.25f;\n"
        "    public float LookSensitivity = 1.8f;\n"
        "    public float GamepadLookSpeed = 180f;\n"
        "    public float Gravity = -24f;\n"
        "    public float JumpHeight = 1.1f;\n"
        "    public float MaxPitch = 82f;\n"
        "    public Transform CameraRoot;\n\n"
        "    private CharacterController _controller;\n"
        "    private float _pitch;\n"
        "    private float _verticalVelocity;\n\n"
        "    private void Awake()\n"
        "    {\n"
        "        _controller = GetComponent<CharacterController>();\n"
        "        if (CameraRoot == null)\n"
        "        {\n"
        "            var cameraComponent = GetComponentInChildren<Camera>();\n"
        "            CameraRoot = cameraComponent != null ? cameraComponent.transform : null;\n"
        "        }\n"
        "        Cursor.lockState = CursorLockMode.Locked;\n"
        "        Cursor.visible = false;\n"
        "    }\n\n"
        "    private void OnDisable()\n"
        "    {\n"
        "        Cursor.lockState = CursorLockMode.None;\n"
        "        Cursor.visible = true;\n"
        "    }\n\n"
        "    private void Update()\n"
        "    {\n"
        "        Look(ReadLookInput());\n"
        "        Move();\n"
        "    }\n\n"
        "    private void Look(Vector2 lookInput)\n"
        "    {\n"
        "        float mouseX = lookInput.x * LookSensitivity;\n"
        "        float mouseY = lookInput.y * LookSensitivity;\n"
        "        transform.Rotate(Vector3.up * mouseX, Space.Self);\n"
        "        if (CameraRoot == null)\n"
        "        {\n"
        "            return;\n"
        "        }\n"
        "        _pitch = Mathf.Clamp(_pitch - mouseY, -MaxPitch, MaxPitch);\n"
        "        CameraRoot.localRotation = Quaternion.Euler(_pitch, 0f, 0f);\n"
        "    }\n\n"
        "    private void Move()\n"
        "    {\n"
        "        Vector2 input = ReadMoveInput();\n"
        "        Vector3 wishDirection = (transform.right * input.x + transform.forward * input.y).normalized;\n"
        "        float targetSpeed = IsSprintPressed() ? SprintSpeed : MoveSpeed;\n"
        "        if (_controller.isGrounded && _verticalVelocity < 0f)\n"
        "        {\n"
        "            _verticalVelocity = -2f;\n"
        "        }\n"
        "        if (_controller.isGrounded && WasJumpPressedThisFrame())\n"
        "        {\n"
        "            _verticalVelocity = Mathf.Sqrt(JumpHeight * -2f * Gravity);\n"
        "        }\n"
        "        _verticalVelocity += Gravity * Time.deltaTime;\n"
        "        Vector3 velocity = wishDirection * targetSpeed;\n"
        "        velocity.y = _verticalVelocity;\n"
        "        _controller.Move(velocity * Time.deltaTime);\n"
        "    }\n\n"
        "    private Vector2 ReadMoveInput()\n"
        "    {\n"
        "#if ENABLE_INPUT_SYSTEM\n"
        "        Vector2 input = Vector2.zero;\n"
        "        var keyboard = Keyboard.current;\n"
        "        if (keyboard != null)\n"
        "        {\n"
        "            if (keyboard.aKey.isPressed)\n"
        "            {\n"
        "                input.x -= 1f;\n"
        "            }\n"
        "            if (keyboard.dKey.isPressed)\n"
        "            {\n"
        "                input.x += 1f;\n"
        "            }\n"
        "            if (keyboard.sKey.isPressed)\n"
        "            {\n"
        "                input.y -= 1f;\n"
        "            }\n"
        "            if (keyboard.wKey.isPressed)\n"
        "            {\n"
        "                input.y += 1f;\n"
        "            }\n"
        "        }\n"
        "        var gamepad = Gamepad.current;\n"
        "        if (gamepad != null)\n"
        "        {\n"
        "            Vector2 stick = gamepad.leftStick.ReadValue();\n"
        "            if (stick.sqrMagnitude > input.sqrMagnitude)\n"
        "            {\n"
        "                input = stick;\n"
        "            }\n"
        "        }\n"
        "        return Vector2.ClampMagnitude(input, 1f);\n"
        "#else\n"
        "        return Vector2.ClampMagnitude(new Vector2(Input.GetAxisRaw(\"Horizontal\"), Input.GetAxisRaw(\"Vertical\")), 1f);\n"
        "#endif\n"
        "    }\n\n"
        "    private Vector2 ReadLookInput()\n"
        "    {\n"
        "#if ENABLE_INPUT_SYSTEM\n"
        "        Vector2 input = Vector2.zero;\n"
        "        var mouse = Mouse.current;\n"
        "        if (mouse != null)\n"
        "        {\n"
        "            input += mouse.delta.ReadValue();\n"
        "        }\n"
        "        var gamepad = Gamepad.current;\n"
        "        if (gamepad != null)\n"
        "        {\n"
        "            input += gamepad.rightStick.ReadValue() * (GamepadLookSpeed * Time.deltaTime);\n"
        "        }\n"
        "        return input;\n"
        "#else\n"
        "        return new Vector2(Input.GetAxisRaw(\"Mouse X\"), Input.GetAxisRaw(\"Mouse Y\"));\n"
        "#endif\n"
        "    }\n\n"
        "    private bool IsSprintPressed()\n"
        "    {\n"
        "#if ENABLE_INPUT_SYSTEM\n"
        "        var keyboard = Keyboard.current;\n"
        "        bool keyboardPressed = keyboard != null && (keyboard.leftShiftKey.isPressed || keyboard.rightShiftKey.isPressed);\n"
        "        bool gamepadPressed = Gamepad.current != null && Gamepad.current.leftStickButton.isPressed;\n"
        "        return keyboardPressed || gamepadPressed;\n"
        "#else\n"
        "        return Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift);\n"
        "#endif\n"
        "    }\n\n"
        "    private bool WasJumpPressedThisFrame()\n"
        "    {\n"
        "#if ENABLE_INPUT_SYSTEM\n"
        "        var keyboard = Keyboard.current;\n"
        "        bool keyboardPressed = keyboard != null && keyboard.spaceKey.wasPressedThisFrame;\n"
        "        bool gamepadPressed = Gamepad.current != null && Gamepad.current.buttonSouth.wasPressedThisFrame;\n"
        "        return keyboardPressed || gamepadPressed;\n"
        "#else\n"
        "        return Input.GetButtonDown(\"Jump\");\n"
        "#endif\n"
        "    }\n"
        "}\n"
    )


def build_3d_fps_sample_scene_code(
    root_name: str,
    scene_path: str,
    *,
    replace_existing: bool,
    floor_material_path: str,
    wall_material_path: str,
    trim_material_path: str,
    accent_material_path: str,
    sky_material_path: str,
) -> str:
    template = """
// CLI_ANYTHING_FPS_SCENE
var rootName = "__ROOT_NAME__";
var scenePath = "__SCENE_PATH__";
var replaceExisting = __REPLACE_EXISTING__;
var floorMaterialPath = "__FLOOR_MATERIAL_PATH__";
var wallMaterialPath = "__WALL_MATERIAL_PATH__";
var trimMaterialPath = "__TRIM_MATERIAL_PATH__";
var accentMaterialPath = "__ACCENT_MATERIAL_PATH__";
var skyMaterialPath = "__SKY_MATERIAL_PATH__";

string NormalizeAssetPath(string value)
{
    return (value ?? string.Empty).Replace("\\\\", "/");
}

void EnsureFolder(string folderPath)
{
    folderPath = NormalizeAssetPath(folderPath);
    if (string.IsNullOrEmpty(folderPath) || folderPath == "Assets" || UnityEditor.AssetDatabase.IsValidFolder(folderPath))
    {
        return;
    }

    var parent = NormalizeAssetPath(System.IO.Path.GetDirectoryName(folderPath));
    var leaf = System.IO.Path.GetFileName(folderPath);
    if (!UnityEditor.AssetDatabase.IsValidFolder(parent))
    {
        EnsureFolder(parent);
    }

    if (!UnityEditor.AssetDatabase.IsValidFolder(folderPath))
    {
        UnityEditor.AssetDatabase.CreateFolder(parent, leaf);
    }
}

UnityEngine.Shader FindShader(params string[] names)
{
    foreach (var shaderName in names)
    {
        if (string.IsNullOrEmpty(shaderName))
        {
            continue;
        }

        var shader = UnityEngine.Shader.Find(shaderName);
        if (shader != null)
        {
            return shader;
        }
    }

    return null;
}

void SetColor(UnityEngine.Material material, UnityEngine.Color value, params string[] properties)
{
    foreach (var property in properties)
    {
        if (material.HasProperty(property))
        {
            material.SetColor(property, value);
        }
    }
}

void SetFloat(UnityEngine.Material material, float value, params string[] properties)
{
    foreach (var property in properties)
    {
        if (material.HasProperty(property))
        {
            material.SetFloat(property, value);
        }
    }
}

UnityEngine.Material CreateSurfaceMaterial(
    string path,
    string name,
    UnityEngine.Color baseColor,
    UnityEngine.Color emissionColor,
    float smoothness,
    float metallic
)
{
    path = NormalizeAssetPath(path);
    EnsureFolder(System.IO.Path.GetDirectoryName(path));

    var existing = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Material>(path);
    if (existing != null)
    {
        if (replaceExisting)
        {
            UnityEditor.AssetDatabase.DeleteAsset(path);
        }
        else
        {
            return existing;
        }
    }

    var shader = FindShader(
        "Universal Render Pipeline/Lit",
        "HDRP/Lit",
        "Standard"
    );
    if (shader == null)
    {
        return null;
    }

    var material = new UnityEngine.Material(shader);
    material.name = name;
    SetColor(material, baseColor, "_BaseColor", "_Color");
    SetFloat(material, metallic, "_Metallic");
    SetFloat(material, smoothness, "_Smoothness", "_Glossiness");
    if (emissionColor.maxColorComponent > 0.0001f)
    {
        material.EnableKeyword("_EMISSION");
        SetColor(material, emissionColor, "_EmissionColor");
        material.globalIlluminationFlags = UnityEngine.MaterialGlobalIlluminationFlags.RealtimeEmissive;
    }

    UnityEditor.AssetDatabase.CreateAsset(material, path);
    return material;
}

UnityEngine.Material CreateSkyboxMaterial(string path)
{
    path = NormalizeAssetPath(path);
    EnsureFolder(System.IO.Path.GetDirectoryName(path));

    var existing = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEngine.Material>(path);
    if (existing != null)
    {
        if (replaceExisting)
        {
            UnityEditor.AssetDatabase.DeleteAsset(path);
        }
        else
        {
            return existing;
        }
    }

    var shader = FindShader("Skybox/Procedural");
    if (shader == null)
    {
        return null;
    }

    var material = new UnityEngine.Material(shader);
    material.name = "FPSShowcaseSky";
    SetColor(material, new UnityEngine.Color(0.18f, 0.32f, 0.50f, 1f), "_SkyTint");
    SetColor(material, new UnityEngine.Color(0.05f, 0.06f, 0.09f, 1f), "_GroundColor");
    SetFloat(material, 0.42f, "_AtmosphereThickness");
    SetFloat(material, 1.1f, "_Exposure");
    SetFloat(material, 1.2f, "_SunSize");
    UnityEditor.AssetDatabase.CreateAsset(material, path);
    return material;
}

UnityEngine.GameObject CreatePrimitiveNode(
    string name,
    UnityEngine.PrimitiveType primitiveType,
    UnityEngine.Transform parent,
    UnityEngine.Vector3 localPosition,
    UnityEngine.Vector3 localScale,
    UnityEngine.Vector3 localEulerAngles,
    UnityEngine.Material material
)
{
    var go = UnityEngine.GameObject.CreatePrimitive(primitiveType);
    go.name = name;
    go.transform.SetParent(parent, false);
    go.transform.localPosition = localPosition;
    go.transform.localScale = localScale;
    go.transform.localRotation = UnityEngine.Quaternion.Euler(localEulerAngles);
    var renderer = go.GetComponent<UnityEngine.Renderer>();
    if (renderer != null && material != null)
    {
        renderer.sharedMaterial = material;
    }

    return go;
}

UnityEngine.Font GetBuiltinFont()
{
    var legacy = UnityEngine.Resources.GetBuiltinResource<UnityEngine.Font>("LegacyRuntime.ttf");
    if (legacy != null)
    {
        return legacy;
    }

    return null;
}

UnityEngine.GameObject CreateUiNode(
    string name,
    UnityEngine.Transform parent,
    UnityEngine.Vector2 anchorMin,
    UnityEngine.Vector2 anchorMax,
    UnityEngine.Vector2 pivot,
    UnityEngine.Vector2 anchoredPosition,
    UnityEngine.Vector2 sizeDelta
)
{
    var go = new UnityEngine.GameObject(name, typeof(UnityEngine.RectTransform));
    go.transform.SetParent(parent, false);
    var rect = go.GetComponent<UnityEngine.RectTransform>();
    rect.anchorMin = anchorMin;
    rect.anchorMax = anchorMax;
    rect.pivot = pivot;
    rect.anchoredPosition = anchoredPosition;
    rect.sizeDelta = sizeDelta;
    return go;
}

UnityEngine.UI.Text CreateTextNode(
    string name,
    UnityEngine.Transform parent,
    UnityEngine.Vector2 anchorMin,
    UnityEngine.Vector2 anchorMax,
    UnityEngine.Vector2 pivot,
    UnityEngine.Vector2 anchoredPosition,
    UnityEngine.Vector2 sizeDelta,
    string text,
    int fontSize,
    UnityEngine.Color color,
    UnityEngine.TextAnchor alignment,
    UnityEngine.Font font
)
{
    var go = CreateUiNode(name, parent, anchorMin, anchorMax, pivot, anchoredPosition, sizeDelta);
    var label = go.AddComponent<UnityEngine.UI.Text>();
    label.font = font;
    label.text = text;
    label.fontSize = fontSize;
    label.alignment = alignment;
    label.color = color;
    label.horizontalOverflow = UnityEngine.HorizontalWrapMode.Wrap;
    label.verticalOverflow = UnityEngine.VerticalWrapMode.Overflow;
    return label;
}

var existingScene = UnityEditor.AssetDatabase.LoadAssetAtPath<UnityEditor.SceneAsset>(scenePath);
if (existingScene != null && !replaceExisting)
{
    return new
    {
        success = false,
        error = "Scene already exists. Rerun with --replace to rebuild it."
    };
}

EnsureFolder(System.IO.Path.GetDirectoryName(scenePath));
if (existingScene != null && replaceExisting)
{
    UnityEditor.AssetDatabase.DeleteAsset(scenePath);
}

var scene = UnityEditor.SceneManagement.EditorSceneManager.NewScene(
    UnityEditor.SceneManagement.NewSceneSetup.EmptyScene,
    UnityEditor.SceneManagement.NewSceneMode.Single
);

var floorMaterial = CreateSurfaceMaterial(
    floorMaterialPath,
    "FPSFloor",
    new UnityEngine.Color(0.14f, 0.16f, 0.20f, 1f),
    new UnityEngine.Color(0f, 0f, 0f, 1f),
    0.65f,
    0.15f
);
var wallMaterial = CreateSurfaceMaterial(
    wallMaterialPath,
    "FPSWall",
    new UnityEngine.Color(0.33f, 0.36f, 0.41f, 1f),
    new UnityEngine.Color(0f, 0f, 0f, 1f),
    0.48f,
    0.04f
);
var trimMaterial = CreateSurfaceMaterial(
    trimMaterialPath,
    "FPSTrim",
    new UnityEngine.Color(0.56f, 0.31f, 0.18f, 1f),
    new UnityEngine.Color(0.03f, 0.01f, 0f, 1f),
    0.72f,
    0.28f
);
var accentMaterial = CreateSurfaceMaterial(
    accentMaterialPath,
    "FPSAccent",
    new UnityEngine.Color(0.22f, 0.86f, 1.00f, 1f),
    new UnityEngine.Color(0.10f, 0.40f, 0.55f, 1f),
    0.78f,
    0.06f
);
var skyMaterial = CreateSkyboxMaterial(skyMaterialPath);

UnityEngine.RenderSettings.fog = true;
UnityEngine.RenderSettings.fogMode = UnityEngine.FogMode.ExponentialSquared;
UnityEngine.RenderSettings.fogDensity = 0.01f;
UnityEngine.RenderSettings.fogColor = new UnityEngine.Color(0.07f, 0.09f, 0.14f, 1f);
UnityEngine.RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Trilight;
UnityEngine.RenderSettings.ambientSkyColor = new UnityEngine.Color(0.20f, 0.26f, 0.34f, 1f);
UnityEngine.RenderSettings.ambientEquatorColor = new UnityEngine.Color(0.11f, 0.12f, 0.16f, 1f);
UnityEngine.RenderSettings.ambientGroundColor = new UnityEngine.Color(0.04f, 0.04f, 0.05f, 1f);
if (skyMaterial != null)
{
    UnityEngine.RenderSettings.skybox = skyMaterial;
}

var root = new UnityEngine.GameObject(rootName);
var environment = new UnityEngine.GameObject(rootName + "_Environment");
environment.transform.SetParent(root.transform, false);

var floor = CreatePrimitiveNode(
    rootName + "_Floor",
    UnityEngine.PrimitiveType.Cube,
    environment.transform,
    new UnityEngine.Vector3(0f, -0.5f, 0f),
    new UnityEngine.Vector3(28f, 1f, 28f),
    UnityEngine.Vector3.zero,
    floorMaterial
);
var northWall = CreatePrimitiveNode(
    rootName + "_NorthWall",
    UnityEngine.PrimitiveType.Cube,
    environment.transform,
    new UnityEngine.Vector3(0f, 2.2f, 14f),
    new UnityEngine.Vector3(28f, 4.4f, 1f),
    UnityEngine.Vector3.zero,
    wallMaterial
);
var southWall = CreatePrimitiveNode(
    rootName + "_SouthWall",
    UnityEngine.PrimitiveType.Cube,
    environment.transform,
    new UnityEngine.Vector3(0f, 2.2f, -14f),
    new UnityEngine.Vector3(28f, 4.4f, 1f),
    UnityEngine.Vector3.zero,
    wallMaterial
);
var eastWall = CreatePrimitiveNode(
    rootName + "_EastWall",
    UnityEngine.PrimitiveType.Cube,
    environment.transform,
    new UnityEngine.Vector3(14f, 2.2f, 0f),
    new UnityEngine.Vector3(1f, 4.4f, 28f),
    UnityEngine.Vector3.zero,
    wallMaterial
);
var westWall = CreatePrimitiveNode(
    rootName + "_WestWall",
    UnityEngine.PrimitiveType.Cube,
    environment.transform,
    new UnityEngine.Vector3(-14f, 2.2f, 0f),
    new UnityEngine.Vector3(1f, 4.4f, 28f),
    UnityEngine.Vector3.zero,
    wallMaterial
);
var lane = CreatePrimitiveNode(
    rootName + "_LaneStrip",
    UnityEngine.PrimitiveType.Cube,
    environment.transform,
    new UnityEngine.Vector3(0f, 0.01f, 1.2f),
    new UnityEngine.Vector3(4f, 0.02f, 18f),
    UnityEngine.Vector3.zero,
    accentMaterial
);
var platform = CreatePrimitiveNode(
    rootName + "_Platform",
    UnityEngine.PrimitiveType.Cube,
    environment.transform,
    new UnityEngine.Vector3(0f, 0.4f, 6.8f),
    new UnityEngine.Vector3(6f, 0.8f, 4f),
    UnityEngine.Vector3.zero,
    trimMaterial
);
var coverA = CreatePrimitiveNode(
    rootName + "_CoverA",
    UnityEngine.PrimitiveType.Cube,
    environment.transform,
    new UnityEngine.Vector3(-4.8f, 0.7f, 1.8f),
    new UnityEngine.Vector3(2.8f, 1.4f, 1.2f),
    UnityEngine.Vector3.zero,
    wallMaterial
);
var coverB = CreatePrimitiveNode(
    rootName + "_CoverB",
    UnityEngine.PrimitiveType.Cube,
    environment.transform,
    new UnityEngine.Vector3(4.9f, 0.7f, 0.5f),
    new UnityEngine.Vector3(2.4f, 1.4f, 1.2f),
    UnityEngine.Vector3.zero,
    wallMaterial
);
var coverC = CreatePrimitiveNode(
    rootName + "_CoverC",
    UnityEngine.PrimitiveType.Cube,
    environment.transform,
    new UnityEngine.Vector3(0f, 0.95f, -3.8f),
    new UnityEngine.Vector3(1.6f, 1.9f, 1.6f),
    UnityEngine.Vector3.zero,
    trimMaterial
);

var columns = new []
{
    CreatePrimitiveNode(rootName + "_ColumnNW", UnityEngine.PrimitiveType.Cube, environment.transform, new UnityEngine.Vector3(-10.5f, 2f, 9f), new UnityEngine.Vector3(1.4f, 4f, 1.4f), UnityEngine.Vector3.zero, trimMaterial),
    CreatePrimitiveNode(rootName + "_ColumnNE", UnityEngine.PrimitiveType.Cube, environment.transform, new UnityEngine.Vector3(10.5f, 2f, 9f), new UnityEngine.Vector3(1.4f, 4f, 1.4f), UnityEngine.Vector3.zero, trimMaterial),
    CreatePrimitiveNode(rootName + "_ColumnSW", UnityEngine.PrimitiveType.Cube, environment.transform, new UnityEngine.Vector3(-10.5f, 2f, -9f), new UnityEngine.Vector3(1.4f, 4f, 1.4f), UnityEngine.Vector3.zero, trimMaterial),
    CreatePrimitiveNode(rootName + "_ColumnSE", UnityEngine.PrimitiveType.Cube, environment.transform, new UnityEngine.Vector3(10.5f, 2f, -9f), new UnityEngine.Vector3(1.4f, 4f, 1.4f), UnityEngine.Vector3.zero, trimMaterial),
};

UnityEngine.GameObject CreateBeacon(string name, UnityEngine.Vector3 position)
{
    var beaconRoot = new UnityEngine.GameObject(name);
    beaconRoot.transform.SetParent(environment.transform, false);
    beaconRoot.transform.localPosition = position;

    var baseNode = CreatePrimitiveNode(
        name + "_Base",
        UnityEngine.PrimitiveType.Cylinder,
        beaconRoot.transform,
        new UnityEngine.Vector3(0f, 0.5f, 0f),
        new UnityEngine.Vector3(1.1f, 0.5f, 1.1f),
        UnityEngine.Vector3.zero,
        trimMaterial
    );
    var coreNode = CreatePrimitiveNode(
        name + "_Core",
        UnityEngine.PrimitiveType.Sphere,
        beaconRoot.transform,
        new UnityEngine.Vector3(0f, 1.7f, 0f),
        new UnityEngine.Vector3(1.0f, 1.0f, 1.0f),
        UnityEngine.Vector3.zero,
        accentMaterial
    );
    var lightGo = new UnityEngine.GameObject(name + "_Light");
    lightGo.transform.SetParent(beaconRoot.transform, false);
    lightGo.transform.localPosition = new UnityEngine.Vector3(0f, 1.8f, 0f);
    var pointLight = lightGo.AddComponent<UnityEngine.Light>();
    pointLight.type = UnityEngine.LightType.Point;
    pointLight.range = 10f;
    pointLight.intensity = 12f;
    pointLight.color = new UnityEngine.Color(0.20f, 0.86f, 1.0f, 1f);
    pointLight.shadows = UnityEngine.LightShadows.Soft;
    return beaconRoot;
}

var beaconA = CreateBeacon(rootName + "_BeaconA", new UnityEngine.Vector3(-7.5f, 0f, 9.5f));
var beaconB = CreateBeacon(rootName + "_BeaconB", new UnityEngine.Vector3(7.5f, 0f, 9.5f));

var player = new UnityEngine.GameObject(rootName + "_Player");
player.transform.SetParent(root.transform, false);
player.transform.localPosition = new UnityEngine.Vector3(0f, 1.05f, -10.5f);
player.transform.localRotation = UnityEngine.Quaternion.identity;
var controller = player.AddComponent<UnityEngine.CharacterController>();
controller.center = new UnityEngine.Vector3(0f, 0.9f, 0f);
controller.height = 1.8f;
controller.radius = 0.35f;
controller.stepOffset = 0.35f;
controller.slopeLimit = 50f;

var cameraGo = new UnityEngine.GameObject("MainCamera");
cameraGo.transform.SetParent(player.transform, false);
cameraGo.transform.localPosition = new UnityEngine.Vector3(0f, 0.72f, 0f);
cameraGo.transform.localRotation = UnityEngine.Quaternion.identity;
cameraGo.tag = "MainCamera";
var cameraComponent = cameraGo.AddComponent<UnityEngine.Camera>();
cameraComponent.fieldOfView = 78f;
cameraComponent.nearClipPlane = 0.03f;
cameraComponent.farClipPlane = 200f;
cameraComponent.clearFlags = UnityEngine.CameraClearFlags.Skybox;
cameraGo.AddComponent<UnityEngine.AudioListener>();

var weaponRoot = new UnityEngine.GameObject(rootName + "_Weapon");
weaponRoot.transform.SetParent(cameraGo.transform, false);
weaponRoot.transform.localPosition = new UnityEngine.Vector3(0.34f, -0.34f, 0.72f);
weaponRoot.transform.localRotation = UnityEngine.Quaternion.Euler(8f, -12f, 0f);
var weaponBody = CreatePrimitiveNode(
    rootName + "_WeaponBody",
    UnityEngine.PrimitiveType.Cube,
    weaponRoot.transform,
    new UnityEngine.Vector3(0f, 0f, 0f),
    new UnityEngine.Vector3(0.22f, 0.16f, 0.52f),
    UnityEngine.Vector3.zero,
    trimMaterial
);
var weaponCore = CreatePrimitiveNode(
    rootName + "_WeaponCore",
    UnityEngine.PrimitiveType.Cylinder,
    weaponRoot.transform,
    new UnityEngine.Vector3(0.07f, 0.01f, 0.28f),
    new UnityEngine.Vector3(0.05f, 0.24f, 0.05f),
    new UnityEngine.Vector3(90f, 0f, 0f),
    accentMaterial
);

var font = GetBuiltinFont();
var hudRoot = new UnityEngine.GameObject(rootName + "_HUD");
hudRoot.transform.SetParent(root.transform, false);
var canvas = hudRoot.AddComponent<UnityEngine.Canvas>();
canvas.renderMode = UnityEngine.RenderMode.ScreenSpaceOverlay;
canvas.sortingOrder = 100;
var scaler = hudRoot.AddComponent<UnityEngine.UI.CanvasScaler>();
scaler.uiScaleMode = UnityEngine.UI.CanvasScaler.ScaleMode.ScaleWithScreenSize;
scaler.referenceResolution = new UnityEngine.Vector2(1920f, 1080f);
scaler.matchWidthOrHeight = 0.5f;
hudRoot.AddComponent<UnityEngine.UI.GraphicRaycaster>();

var objectivePanel = CreateUiNode(
    rootName + "_ObjectivePanel",
    hudRoot.transform,
    new UnityEngine.Vector2(0f, 1f),
    new UnityEngine.Vector2(0f, 1f),
    new UnityEngine.Vector2(0f, 1f),
    new UnityEngine.Vector2(42f, -42f),
    new UnityEngine.Vector2(430f, 138f)
);
var objectivePanelImage = objectivePanel.AddComponent<UnityEngine.UI.Image>();
objectivePanelImage.color = new UnityEngine.Color(0.04f, 0.06f, 0.09f, 0.82f);

CreateTextNode(
    rootName + "_ObjectiveHeader",
    objectivePanel.transform,
    new UnityEngine.Vector2(0f, 1f),
    new UnityEngine.Vector2(0f, 1f),
    new UnityEngine.Vector2(0f, 1f),
    new UnityEngine.Vector2(18f, -16f),
    new UnityEngine.Vector2(390f, 28f),
    "CODEX RANGE // FPS SAMPLE",
    24,
    new UnityEngine.Color(0.92f, 0.97f, 1f, 1f),
    UnityEngine.TextAnchor.UpperLeft,
    font
);
CreateTextNode(
    rootName + "_ObjectiveBody",
    objectivePanel.transform,
    new UnityEngine.Vector2(0f, 1f),
    new UnityEngine.Vector2(0f, 1f),
    new UnityEngine.Vector2(0f, 1f),
    new UnityEngine.Vector2(18f, -52f),
    new UnityEngine.Vector2(390f, 64f),
    "Objective: move through the lane, push the platform, and line up on the cyan beacons.",
    18,
    new UnityEngine.Color(0.69f, 0.78f, 0.88f, 1f),
    UnityEngine.TextAnchor.UpperLeft,
    font
);
var objectiveAccent = CreateUiNode(
    rootName + "_ObjectiveAccent",
    objectivePanel.transform,
    new UnityEngine.Vector2(1f, 0f),
    new UnityEngine.Vector2(1f, 1f),
    new UnityEngine.Vector2(1f, 0.5f),
    new UnityEngine.Vector2(-10f, 0f),
    new UnityEngine.Vector2(6f, -20f)
);
var objectiveAccentImage = objectiveAccent.AddComponent<UnityEngine.UI.Image>();
objectiveAccentImage.color = new UnityEngine.Color(0.22f, 0.86f, 1f, 0.95f);

var statusPanel = CreateUiNode(
    rootName + "_StatusPanel",
    hudRoot.transform,
    new UnityEngine.Vector2(0f, 0f),
    new UnityEngine.Vector2(0f, 0f),
    new UnityEngine.Vector2(0f, 0f),
    new UnityEngine.Vector2(42f, 42f),
    new UnityEngine.Vector2(320f, 120f)
);
var statusPanelImage = statusPanel.AddComponent<UnityEngine.UI.Image>();
statusPanelImage.color = new UnityEngine.Color(0.05f, 0.06f, 0.08f, 0.78f);

CreateTextNode(
    rootName + "_HealthLabel",
    statusPanel.transform,
    new UnityEngine.Vector2(0f, 1f),
    new UnityEngine.Vector2(0f, 1f),
    new UnityEngine.Vector2(0f, 1f),
    new UnityEngine.Vector2(18f, -18f),
    new UnityEngine.Vector2(280f, 30f),
    "HEALTH   100",
    22,
    new UnityEngine.Color(0.96f, 0.96f, 0.98f, 1f),
    UnityEngine.TextAnchor.UpperLeft,
    font
);
CreateTextNode(
    rootName + "_AmmoLabel",
    statusPanel.transform,
    new UnityEngine.Vector2(0f, 1f),
    new UnityEngine.Vector2(0f, 1f),
    new UnityEngine.Vector2(0f, 1f),
    new UnityEngine.Vector2(18f, -54f),
    new UnityEngine.Vector2(280f, 30f),
    "AMMO     24 / 96",
    22,
    new UnityEngine.Color(0.96f, 0.96f, 0.98f, 1f),
    UnityEngine.TextAnchor.UpperLeft,
    font
);
CreateTextNode(
    rootName + "_TipLabel",
    statusPanel.transform,
    new UnityEngine.Vector2(0f, 0f),
    new UnityEngine.Vector2(1f, 0f),
    new UnityEngine.Vector2(0.5f, 0f),
    new UnityEngine.Vector2(0f, 16f),
    new UnityEngine.Vector2(-24f, 26f),
    "WASD move  |  Mouse look  |  Shift sprint  |  Space jump",
    16,
    new UnityEngine.Color(0.58f, 0.74f, 0.86f, 1f),
    UnityEngine.TextAnchor.MiddleCenter,
    font
);

var reticleRoot = CreateUiNode(
    rootName + "_Reticle",
    hudRoot.transform,
    new UnityEngine.Vector2(0.5f, 0.5f),
    new UnityEngine.Vector2(0.5f, 0.5f),
    new UnityEngine.Vector2(0.5f, 0.5f),
    UnityEngine.Vector2.zero,
    new UnityEngine.Vector2(32f, 32f)
);

foreach (var reticlePart in new[]
{
    new { Name = "Top", Position = new UnityEngine.Vector2(0f, 8f), Size = new UnityEngine.Vector2(3f, 10f) },
    new { Name = "Bottom", Position = new UnityEngine.Vector2(0f, -8f), Size = new UnityEngine.Vector2(3f, 10f) },
    new { Name = "Left", Position = new UnityEngine.Vector2(-8f, 0f), Size = new UnityEngine.Vector2(10f, 3f) },
    new { Name = "Right", Position = new UnityEngine.Vector2(8f, 0f), Size = new UnityEngine.Vector2(10f, 3f) },
})
{
    var segment = CreateUiNode(
        rootName + "_Reticle" + reticlePart.Name,
        reticleRoot.transform,
        new UnityEngine.Vector2(0.5f, 0.5f),
        new UnityEngine.Vector2(0.5f, 0.5f),
        new UnityEngine.Vector2(0.5f, 0.5f),
        reticlePart.Position,
        reticlePart.Size
    );
    var segmentImage = segment.AddComponent<UnityEngine.UI.Image>();
    segmentImage.color = new UnityEngine.Color(0.22f, 0.86f, 1f, 0.96f);
}

var sun = new UnityEngine.GameObject(rootName + "_Sun");
sun.transform.SetParent(root.transform, false);
sun.transform.rotation = UnityEngine.Quaternion.Euler(50f, -32f, 0f);
var sunLight = sun.AddComponent<UnityEngine.Light>();
sunLight.type = UnityEngine.LightType.Directional;
sunLight.color = new UnityEngine.Color(1f, 0.94f, 0.84f, 1f);
sunLight.intensity = 1.2f;
sunLight.shadows = UnityEngine.LightShadows.Soft;

var sceneView = UnityEditor.SceneView.lastActiveSceneView;
if (sceneView != null)
{
    sceneView.in2DMode = false;
    sceneView.orthographic = false;
    sceneView.LookAtDirect(
        new UnityEngine.Vector3(0f, 2f, 0f),
        UnityEngine.Quaternion.Euler(22f, 135f, 0f),
        31f
    );
}

UnityEditor.Selection.activeGameObject = player;
UnityEditor.AssetDatabase.SaveAssets();
UnityEditor.AssetDatabase.Refresh();

var saved = UnityEditor.SceneManagement.EditorSceneManager.SaveScene(scene, scenePath);
if (!saved)
{
    return new
    {
        success = false,
        error = "Failed to save the generated FPS scene."
    };
}

return new
{
    success = true,
    mode = "3d-fps",
    scenePath = scenePath,
    root = root.name,
    player = player.name,
    camera = cameraGo.name,
    materials = new[]
    {
        floorMaterialPath,
        wallMaterialPath,
        trimMaterialPath,
        accentMaterialPath,
        skyMaterialPath
    },
    created = new[]
    {
        root.name,
        environment.name,
        floor.name,
        northWall.name,
        southWall.name,
        eastWall.name,
        westWall.name,
        player.name,
        cameraGo.name,
        hudRoot.name,
        sun.name,
        beaconA.name,
        beaconB.name
    }
};
""".strip()

    return (
        template.replace("__ROOT_NAME__", escape_csharp_string(root_name))
        .replace("__SCENE_PATH__", escape_csharp_string(scene_path))
        .replace("__REPLACE_EXISTING__", "true" if replace_existing else "false")
        .replace("__FLOOR_MATERIAL_PATH__", escape_csharp_string(floor_material_path))
        .replace("__WALL_MATERIAL_PATH__", escape_csharp_string(wall_material_path))
        .replace("__TRIM_MATERIAL_PATH__", escape_csharp_string(trim_material_path))
        .replace("__ACCENT_MATERIAL_PATH__", escape_csharp_string(accent_material_path))
        .replace("__SKY_MATERIAL_PATH__", escape_csharp_string(sky_material_path))
    )


def build_2d_sample_layout_code(root_name: str) -> str:
    return f"""
var rootName = "{root_name}";
var existing = UnityEngine.GameObject.Find(rootName);
if (existing != null)
{{
    UnityEditor.Undo.DestroyObjectImmediate(existing);
}}

var mainCamera = UnityEngine.Object.FindFirstObjectByType<UnityEngine.Camera>();
if (mainCamera != null)
{{
    mainCamera.orthographic = true;
    mainCamera.orthographicSize = 5.5f;
    mainCamera.clearFlags = UnityEngine.CameraClearFlags.SolidColor;
    mainCamera.backgroundColor = new UnityEngine.Color(0.05f, 0.07f, 0.11f, 1f);
    mainCamera.transform.position = new UnityEngine.Vector3(0f, 0f, -10f);
}}

var root = new UnityEngine.GameObject(rootName);
UnityEditor.Undo.RegisterCreatedObjectUndo(root, "Create 2D sample root");

var sprite = UnityEngine.Sprite.Create(
    UnityEngine.Texture2D.whiteTexture,
    new UnityEngine.Rect(0f, 0f, 1f, 1f),
    new UnityEngine.Vector2(0.5f, 0.5f),
    1f
);

UnityEngine.GameObject CreateSpriteNode(
    string name,
    UnityEngine.Vector3 localPosition,
    UnityEngine.Vector3 localScale,
    UnityEngine.Color color,
    int sortingOrder,
    float zRotation = 0f)
{{
    var go = new UnityEngine.GameObject(name);
    UnityEditor.Undo.RegisterCreatedObjectUndo(go, "Create " + name);
    go.transform.SetParent(root.transform, false);
    go.transform.localPosition = localPosition;
    go.transform.localScale = localScale;
    go.transform.localRotation = UnityEngine.Quaternion.Euler(0f, 0f, zRotation);

    var renderer = go.AddComponent<UnityEngine.SpriteRenderer>();
    renderer.sprite = sprite;
    renderer.color = color;
    renderer.sortingOrder = sortingOrder;
    return go;
}}

var backdrop = CreateSpriteNode(
    rootName + "_Backdrop",
    new UnityEngine.Vector3(0f, 0f, 0f),
    new UnityEngine.Vector3(13f, 8f, 1f),
    new UnityEngine.Color(0.09f, 0.12f, 0.19f, 1f),
    -20
);
var skyGlow = CreateSpriteNode(
    rootName + "_SkyGlow",
    new UnityEngine.Vector3(2.3f, 1.4f, 0f),
    new UnityEngine.Vector3(6.0f, 4.8f, 1f),
    new UnityEngine.Color(0.25f, 0.40f, 0.78f, 0.18f),
    -19
);
var ridge = CreateSpriteNode(
    rootName + "_Ridge",
    new UnityEngine.Vector3(-1.1f, -0.45f, 0f),
    new UnityEngine.Vector3(10.5f, 2.4f, 1f),
    new UnityEngine.Color(0.15f, 0.19f, 0.29f, 0.95f),
    -12,
    -3f
);
var floor = CreateSpriteNode(
    rootName + "_Floor",
    new UnityEngine.Vector3(0f, -2.25f, 0f),
    new UnityEngine.Vector3(12f, 1.2f, 1f),
    new UnityEngine.Color(0.20f, 0.24f, 0.34f, 1f),
    -10
);
var lane = CreateSpriteNode(
    rootName + "_Lane",
    new UnityEngine.Vector3(0f, -1.1f, 0f),
    new UnityEngine.Vector3(9f, 0.18f, 1f),
    new UnityEngine.Color(0.23f, 0.76f, 0.93f, 0.26f),
    -5
);
var playerShadow = CreateSpriteNode(
    rootName + "_PlayerShadow",
    new UnityEngine.Vector3(-2.4f, -1.5f, 0f),
    new UnityEngine.Vector3(1.85f, 0.24f, 1f),
    new UnityEngine.Color(0.01f, 0.02f, 0.04f, 0.48f),
    8
);

var player = CreateSpriteNode(
    rootName + "_Player",
    new UnityEngine.Vector3(-2.4f, -0.35f, 0f),
    new UnityEngine.Vector3(1.35f, 2.1f, 1f),
    new UnityEngine.Color(1.00f, 0.47f, 0.34f, 1f),
    20
);
var playerAccent = CreateSpriteNode(
    rootName + "_PlayerAccent",
    new UnityEngine.Vector3(-2.4f, 0.55f, 0f),
    new UnityEngine.Vector3(0.65f, 0.55f, 1f),
    new UnityEngine.Color(1.00f, 0.86f, 0.52f, 0.95f),
    21
);
playerAccent.transform.SetParent(player.transform, true);
playerAccent.transform.localPosition = new UnityEngine.Vector3(0f, 0.25f, 0f);

var beaconShadow = CreateSpriteNode(
    rootName + "_BeaconShadow",
    new UnityEngine.Vector3(2.6f, -1.46f, 0f),
    new UnityEngine.Vector3(1.45f, 0.24f, 1f),
    new UnityEngine.Color(0.01f, 0.02f, 0.04f, 0.45f),
    8
);
var beacon = CreateSpriteNode(
    rootName + "_Beacon",
    new UnityEngine.Vector3(2.6f, 0.15f, 0f),
    new UnityEngine.Vector3(1.35f, 1.35f, 1f),
    new UnityEngine.Color(1.00f, 0.88f, 0.35f, 1f),
    30,
    45f
);
var beaconGlow = CreateSpriteNode(
    rootName + "_BeaconGlow",
    new UnityEngine.Vector3(2.6f, 0.15f, 0f),
    new UnityEngine.Vector3(2.3f, 2.3f, 1f),
    new UnityEngine.Color(0.98f, 0.83f, 0.28f, 0.18f),
    15
);
var beaconCore = CreateSpriteNode(
    rootName + "_BeaconCore",
    new UnityEngine.Vector3(2.6f, 0.15f, 0f),
    new UnityEngine.Vector3(0.5f, 0.5f, 1f),
    new UnityEngine.Color(1.00f, 0.96f, 0.80f, 0.94f),
    31,
    45f
);

var observer = new UnityEngine.GameObject(rootName + "_Observer");
UnityEditor.Undo.RegisterCreatedObjectUndo(observer, "Create observer");
observer.transform.SetParent(root.transform, false);
observer.transform.localPosition = new UnityEngine.Vector3(0f, 0f, -10f);

return new
{{
    success = true,
    mode = "2d",
    created = new []
    {{
        root.name,
        backdrop.name,
        floor.name,
        lane.name,
        player.name,
        beacon.name,
        observer.name
    }}
}};
""".strip()


def build_2d_sample_clone_repair_code(clone_name: str) -> str:
    return f"""
var clone = UnityEngine.GameObject.Find("{clone_name}");
if (clone == null)
{{
    return new
    {{
        success = false,
        error = "Clone not found."
    }};
}}

var renderer = clone.GetComponent<UnityEngine.SpriteRenderer>();
if (renderer == null)
{{
    renderer = clone.AddComponent<UnityEngine.SpriteRenderer>();
}}

if (renderer.sprite == null)
{{
    renderer.sprite = UnityEngine.Sprite.Create(
        UnityEngine.Texture2D.whiteTexture,
        new UnityEngine.Rect(0f, 0f, 1f, 1f),
        new UnityEngine.Vector2(0.5f, 0.5f),
        1f
    );
}}

renderer.color = new UnityEngine.Color(1.00f, 0.88f, 0.35f, 1f);
renderer.sortingOrder = 30;

return new
{{
    success = true,
    clone = clone.name,
    repairedSprite = renderer.sprite != null
}};
""".strip()


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
