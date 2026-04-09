from __future__ import annotations

import json
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


def build_unity_test_project_manifest(plugin_reference: str) -> str:
    payload = {
        "dependencies": {
            "com.unity.inputsystem": "1.19.0",
            "com.unity.test-framework": "1.6.0",
            "com.unity.ugui": "2.0.0",
            "com.anklebreaker.unity-mcp": plugin_reference,
        }
    }
    return json.dumps(payload, indent=2, ensure_ascii=True) + "\n"


def build_unity_test_project_gitignore() -> str:
    return (
        "/Library/\n"
        "/Logs/\n"
        "/Temp/\n"
        "/Obj/\n"
        "/Build/\n"
        "/Builds/\n"
        "/UserSettings/\n"
        "/MemoryCaptures/\n"
        "/Recordings/\n"
        "*.csproj\n"
        "*.sln\n"
        "*.suo\n"
        "*.tmp\n"
        "*.user\n"
        "*.userprefs\n"
        "*.pidb\n"
        "*.booproj\n"
        "*.svd\n"
        "*.pdb\n"
        "*.mdb\n"
        "*.opendb\n"
        "*.VC.db\n"
        "*.DS_Store\n"
        ".vs/\n"
    )


def build_unity_test_project_bootstrap_script(
    project_label: str,
    scene_path: str = "Assets/Scenes/CodexCliSmoke.unity",
) -> str:
    scene_name = posixpath.splitext(posixpath.basename(scene_path))[0]
    safe_label = escape_csharp_string(project_label)
    safe_scene_path = escape_csharp_string(scene_path)
    safe_scene_name = escape_csharp_string(scene_name)
    return (
        "using System.IO;\n"
        "using UnityEditor;\n"
        "using UnityEditor.SceneManagement;\n"
        "using UnityEngine;\n"
        "using UnityEngine.SceneManagement;\n\n"
        "[InitializeOnLoad]\n"
        "public static class CodexCliTestProjectBootstrap\n"
        "{\n"
        f"    private const string ScenePath = \"{safe_scene_path}\";\n"
        f"    private const string SceneName = \"{safe_scene_name}\";\n"
        f"    private const string ProjectLabel = \"{safe_label}\";\n\n"
        "    static CodexCliTestProjectBootstrap()\n"
        "    {\n"
        "        EditorApplication.delayCall += EnsureStarterScene;\n"
        "    }\n\n"
        "    [MenuItem(\"Tools/Codex CLI Smoke/Reset Starter Scene\")]\n"
        "    public static void EnsureStarterScene()\n"
        "    {\n"
        "        EditorApplication.delayCall -= EnsureStarterScene;\n"
        "        EnsureFolder(\"Assets/Scenes\");\n"
        "        EnsureFolder(\"Assets/CodexCliSmoke\");\n"
        "        EnsureFolder(\"Assets/CodexCliSmoke/Materials\");\n"
        "        if (File.Exists(ScenePath))\n"
        "        {\n"
        "            return;\n"
        "        }\n\n"
        "        Scene scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);\n"
        "        scene.name = SceneName;\n\n"
        "        GameObject root = new GameObject(ProjectLabel + \"Root\");\n"
        "        GameObject floor = GameObject.CreatePrimitive(PrimitiveType.Cube);\n"
        "        floor.name = \"SmokeFloor\";\n"
        "        floor.transform.SetParent(root.transform);\n"
        "        floor.transform.position = new Vector3(0f, -0.5f, 0f);\n"
        "        floor.transform.localScale = new Vector3(8f, 1f, 8f);\n\n"
        "        GameObject cube = GameObject.CreatePrimitive(PrimitiveType.Cube);\n"
        "        cube.name = \"SmokeCube\";\n"
        "        cube.transform.SetParent(root.transform);\n"
        "        cube.transform.position = new Vector3(0f, 0.75f, 0f);\n\n"
        "        GameObject beacon = GameObject.CreatePrimitive(PrimitiveType.Sphere);\n"
        "        beacon.name = \"SmokeBeacon\";\n"
        "        beacon.transform.SetParent(root.transform);\n"
        "        beacon.transform.position = new Vector3(2.25f, 0.8f, 1.5f);\n"
        "        beacon.transform.localScale = new Vector3(0.85f, 0.85f, 0.85f);\n\n"
        "        Material floorMaterial = CreateMaterial(\n"
        "            \"Assets/CodexCliSmoke/Materials/SmokeFloor.mat\",\n"
        "            new Color(0.24f, 0.28f, 0.33f),\n"
        "            0.08f,\n"
        "            0.32f,\n"
        "            Color.black\n"
        "        );\n"
        "        Material cubeMaterial = CreateMaterial(\n"
        "            \"Assets/CodexCliSmoke/Materials/SmokeCube.mat\",\n"
        "            new Color(0.63f, 0.69f, 0.76f),\n"
        "            0.02f,\n"
        "            0.18f,\n"
        "            Color.black\n"
        "        );\n"
        "        Material beaconMaterial = CreateMaterial(\n"
        "            \"Assets/CodexCliSmoke/Materials/SmokeBeacon.mat\",\n"
        "            new Color(0.12f, 0.76f, 0.92f),\n"
        "            0.0f,\n"
        "            0.46f,\n"
        "            new Color(0.0f, 0.8f, 1.2f) * 0.7f\n"
        "        );\n"
        "        ApplyMaterial(floor, floorMaterial);\n"
        "        ApplyMaterial(cube, cubeMaterial);\n"
        "        ApplyMaterial(beacon, beaconMaterial);\n\n"
        "        Light directional = Object.FindObjectOfType<Light>();\n"
        "        if (directional != null)\n"
        "        {\n"
        "            directional.intensity = 0.95f;\n"
        "            directional.color = new Color(1f, 0.95f, 0.88f);\n"
        "            directional.transform.rotation = Quaternion.Euler(42f, -35f, 0f);\n"
        "        }\n\n"
        "        Camera mainCamera = Camera.main;\n"
        "        if (mainCamera != null)\n"
        "        {\n"
        "            mainCamera.orthographic = false;\n"
        "            mainCamera.orthographicSize = 5f;\n"
        "            mainCamera.fieldOfView = 60f;\n"
        "            mainCamera.clearFlags = CameraClearFlags.SolidColor;\n"
        "            mainCamera.backgroundColor = new Color(0.08f, 0.1f, 0.14f);\n"
        "            mainCamera.transform.position = new Vector3(0f, 3.2f, -7.5f);\n"
        "            mainCamera.transform.rotation = Quaternion.Euler(16f, 0f, 0f);\n"
        "        }\n\n"
        "        RenderSettings.ambientLight = new Color(0.36f, 0.39f, 0.44f);\n"
        "        RenderSettings.reflectionIntensity = 0.45f;\n\n"
        "        bool saved = EditorSceneManager.SaveScene(scene, ScenePath);\n"
        "        AssetDatabase.SaveAssets();\n"
        "        AssetDatabase.Refresh();\n"
        "        if (saved)\n"
        "        {\n"
        "            Debug.Log(\"[CodexCliSmoke] Created starter scene at \" + ScenePath);\n"
        "        }\n"
        "    }\n\n"
        "    private static void EnsureFolder(string assetPath)\n"
        "    {\n"
        "        if (AssetDatabase.IsValidFolder(assetPath))\n"
        "        {\n"
        "            return;\n"
        "        }\n"
        "        string[] parts = assetPath.Split('/');\n"
        "        string current = parts[0];\n"
        "        for (int i = 1; i < parts.Length; i++)\n"
        "        {\n"
        "            string next = current + \"/\" + parts[i];\n"
        "            if (!AssetDatabase.IsValidFolder(next))\n"
        "            {\n"
        "                AssetDatabase.CreateFolder(current, parts[i]);\n"
        "            }\n"
        "            current = next;\n"
        "        }\n"
        "    }\n\n"
        "    private static Material CreateMaterial(\n"
        "        string path,\n"
        "        Color albedo,\n"
        "        float metallic,\n"
        "        float smoothness,\n"
        "        Color emission\n"
        "    )\n"
        "    {\n"
        "        Material existing = AssetDatabase.LoadAssetAtPath<Material>(path);\n"
        "        if (existing != null)\n"
        "        {\n"
        "            ConfigureMaterial(existing, albedo, metallic, smoothness, emission);\n"
        "            EditorUtility.SetDirty(existing);\n"
        "            return existing;\n"
        "        }\n\n"
        "        Shader shader = Shader.Find(\"Universal Render Pipeline/Lit\") ?? Shader.Find(\"Standard\");\n"
        "        if (shader == null)\n"
        "        {\n"
        "            shader = Shader.Find(\"Sprites/Default\");\n"
        "        }\n"
        "        Material material = new Material(shader);\n"
        "        ConfigureMaterial(material, albedo, metallic, smoothness, emission);\n"
        "        AssetDatabase.CreateAsset(material, path);\n"
        "        return material;\n"
        "    }\n\n"
        "    private static void ConfigureMaterial(\n"
        "        Material material,\n"
        "        Color albedo,\n"
        "        float metallic,\n"
        "        float smoothness,\n"
        "        Color emission\n"
        "    )\n"
        "    {\n"
        "        SetColor(material, albedo, \"_BaseColor\", \"_Color\");\n"
        "        SetFloat(material, metallic, \"_Metallic\");\n"
        "        SetFloat(material, smoothness, \"_Smoothness\", \"_Glossiness\");\n"
        "        if (emission.maxColorComponent > 0f)\n"
        "        {\n"
        "            material.EnableKeyword(\"_EMISSION\");\n"
        "            SetColor(material, emission, \"_EmissionColor\");\n"
        "            material.globalIlluminationFlags = MaterialGlobalIlluminationFlags.RealtimeEmissive;\n"
        "        }\n"
        "        else\n"
        "        {\n"
        "            material.DisableKeyword(\"_EMISSION\");\n"
        "            SetColor(material, Color.black, \"_EmissionColor\");\n"
        "        }\n"
        "    }\n\n"
        "    private static void ApplyMaterial(GameObject target, Material material)\n"
        "    {\n"
        "        if (target == null || material == null)\n"
        "        {\n"
        "            return;\n"
        "        }\n"
        "        Renderer renderer = target.GetComponent<Renderer>();\n"
        "        if (renderer != null)\n"
        "        {\n"
        "            renderer.sharedMaterial = material;\n"
        "        }\n"
        "    }\n\n"
        "    private static void SetColor(Material material, Color value, params string[] properties)\n"
        "    {\n"
        "        foreach (string property in properties)\n"
        "        {\n"
        "            if (material.HasProperty(property))\n"
        "            {\n"
        "                material.SetColor(property, value);\n"
        "            }\n"
        "        }\n"
        "    }\n\n"
        "    private static void SetFloat(Material material, float value, params string[] properties)\n"
        "    {\n"
        "        foreach (string property in properties)\n"
        "        {\n"
        "            if (material.HasProperty(property))\n"
        "            {\n"
        "                material.SetFloat(property, value);\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )


def build_unity_test_project_readme(
    project_name: str,
    plugin_reference: str,
    scene_path: str = "Assets/Scenes/CodexCliSmoke.unity",
) -> str:
    return (
        f"# {project_name}\n\n"
        "This is a disposable Unity smoke project for `unity-mcp-cli`.\n\n"
        "## What It Includes\n\n"
        f"- local plugin reference: `{plugin_reference}`\n"
        f"- starter scene bootstrap: `{scene_path}`\n"
        "- an Editor bootstrap script that creates a simple floor/cube/beacon scene on first open\n\n"
        "## Open It\n\n"
        "1. Open this folder in Unity.\n"
        "2. Let Package Manager restore packages and compile scripts.\n"
        "3. Wait for the Unity console to show the AB Unity MCP bridge port.\n"
        "4. Run the CLI commands below from the `agent-harness` repo.\n\n"
        "## First Commands To Try\n\n"
        "```powershell\n"
        "cli-anything-unity-mcp instances\n"
        "cli-anything-unity-mcp select <port>\n"
        "cli-anything-unity-mcp --json workflow inspect --port <port>\n"
        "cli-anything-unity-mcp --json debug snapshot --console-count 100 --include-hierarchy --port <port>\n"
        "cli-anything-unity-mcp --json debug watch --iterations 2 --interval 0 --console-count 20 --port <port>\n"
        "cli-anything-unity-mcp --json agent watch --iterations 2 --interval 0 --port <port>\n"
        "cli-anything-unity-mcp --json workflow build-sample --name CliSmokeArena --cleanup --port <port>\n"
        "cli-anything-unity-mcp --json workflow build-fps-sample --name CliSmokeFps --replace --scene-path Assets/Scenes/CliSmokeFps.unity --verify-level quick --port <port>\n"
        "```\n\n"
        "## Notes\n\n"
        "- If the bridge port changes, rerun `instances` and `select`.\n"
        "- If something looks off, run `debug snapshot` first and inspect the Unity console.\n"
        "- This project is meant to be safe to rebuild and throw away.\n"
    )


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
        "    public float MouseSensitivity = 0.085f;\n"
        "    public float MinMouseSensitivity = 0.04f;\n"
        "    public float MaxMouseSensitivity = 0.20f;\n"
        "    public float MouseSensitivityStep = 0.01f;\n"
        "    public float GamepadLookSpeed = 160f;\n"
        "    public float Gravity = -24f;\n"
        "    public float JumpHeight = 1.1f;\n"
        "    public float MaxPitch = 82f;\n"
        "    public float FireRate = 6.5f;\n"
        "    public float ReloadDuration = 1.05f;\n"
        "    public float ShotRange = 120f;\n"
        "    public float ImpactForce = 18f;\n"
        "    public int MagazineSize = 24;\n"
        "    public int ReserveAmmo = 96;\n"
        "    public float HitMarkerDuration = 0.12f;\n"
        "    public LayerMask HitMask = Physics.DefaultRaycastLayers;\n"
        "    public Transform CameraRoot;\n\n"
        "    private CharacterController _controller;\n"
        "    private float _pitch;\n"
        "    private float _verticalVelocity;\n\n"
        "    private int _ammoInMagazine;\n"
        "    private int _targetsHit;\n"
        "    private int _totalTargets;\n"
        "    private float _nextShotTime;\n"
        "    private float _reloadCompleteAt;\n"
        "    private float _hitMarkerUntil;\n"
        "    private bool _isReloading;\n"
        "    private string _statusMessage = \"LMB fire  |  [ / ] sensitivity\";\n"
        "    private GUIStyle _headerStyle;\n"
        "    private GUIStyle _bodyStyle;\n"
        "    private GUIStyle _smallStyle;\n"
        "    private UnityEngine.UI.Text _objectiveText;\n"
        "    private UnityEngine.UI.Text _ammoText;\n"
        "    private UnityEngine.UI.Text _sensitivityText;\n"
        "    private UnityEngine.UI.Text _tipText;\n\n"
        "    private void Awake()\n"
        "    {\n"
        "        _controller = GetComponent<CharacterController>();\n"
        "        if (CameraRoot == null)\n"
        "        {\n"
        "            var cameraComponent = GetComponentInChildren<Camera>();\n"
        "            CameraRoot = cameraComponent != null ? cameraComponent.transform : null;\n"
        "        }\n"
        "        _ammoInMagazine = Mathf.Max(1, MagazineSize);\n"
        "        CacheHudReferences();\n"
        "        _totalTargets = CountReactiveTargets();\n"
        "        RefreshHud();\n"
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
        "        FinishReloadIfReady();\n"
        "        HandleCursorLock();\n"
        "        HandleSensitivityInput();\n"
        "        Look(ReadLookInput());\n"
        "        Move();\n"
        "        HandleFireInput();\n"
        "    }\n\n"
        "    private void Look(Vector2 lookInput)\n"
        "    {\n"
        "        float mouseX = lookInput.x * MouseSensitivity;\n"
        "        float mouseY = lookInput.y * MouseSensitivity;\n"
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
        "    private void HandleCursorLock()\n"
        "    {\n"
        "        if (WasUnlockPressedThisFrame())\n"
        "        {\n"
        "            Cursor.lockState = CursorLockMode.None;\n"
        "            Cursor.visible = true;\n"
        "            _statusMessage = \"Cursor released. Click the Game view to resume.\";\n"
        "            RefreshHud();\n"
        "            return;\n"
        "        }\n"
        "        if (Cursor.lockState != CursorLockMode.Locked && WasPrimaryPointerPressedThisFrame())\n"
        "        {\n"
        "            Cursor.lockState = CursorLockMode.Locked;\n"
        "            Cursor.visible = false;\n"
        "            _statusMessage = \"Tracking target lane.\";\n"
        "            RefreshHud();\n"
        "        }\n"
        "    }\n\n"
        "    private void HandleSensitivityInput()\n"
        "    {\n"
        "        float delta = 0f;\n"
        "        if (WasSensitivityDecreasePressedThisFrame())\n"
        "        {\n"
        "            delta -= MouseSensitivityStep;\n"
        "        }\n"
        "        if (WasSensitivityIncreasePressedThisFrame())\n"
        "        {\n"
        "            delta += MouseSensitivityStep;\n"
        "        }\n"
        "        if (Mathf.Abs(delta) < 0.0001f)\n"
        "        {\n"
        "            return;\n"
        "        }\n"
        "        MouseSensitivity = Mathf.Clamp(MouseSensitivity + delta, MinMouseSensitivity, MaxMouseSensitivity);\n"
        "        _statusMessage = $\"Sensitivity {MouseSensitivity:0.000}\";\n"
        "        RefreshHud();\n"
        "    }\n\n"
        "    private void HandleFireInput()\n"
        "    {\n"
        "        if (WasReloadPressedThisFrame())\n"
        "        {\n"
        "            StartReload();\n"
        "        }\n"
        "        if (IsFirePressed())\n"
        "        {\n"
        "            TryFireShot();\n"
        "        }\n"
        "    }\n\n"
        "    public bool FireDebugShot()\n"
        "    {\n"
        "        return TryFireShot();\n"
        "    }\n\n"
        "    private bool TryFireShot()\n"
        "    {\n"
        "        if (_isReloading || Time.time < _nextShotTime)\n"
        "        {\n"
        "            return false;\n"
        "        }\n"
        "        if (_ammoInMagazine <= 0)\n"
        "        {\n"
        "            if (ReserveAmmo > 0)\n"
        "            {\n"
        "                StartReload();\n"
        "            }\n"
        "            else\n"
        "            {\n"
        "                _statusMessage = \"Out of ammo.\";\n"
        "                RefreshHud();\n"
        "            }\n"
        "            return false;\n"
        "        }\n"
        "        _ammoInMagazine -= 1;\n"
        "        _nextShotTime = Time.time + (1f / Mathf.Max(0.01f, FireRate));\n"
        "        RefreshHud();\n"
        "        Vector3 origin = CameraRoot != null ? CameraRoot.position : transform.position + new Vector3(0f, 1.4f, 0f);\n"
        "        Vector3 direction = CameraRoot != null ? CameraRoot.forward : transform.forward;\n"
        "        RaycastHit hit;\n"
        "        if (Physics.Raycast(origin, direction, out hit, ShotRange, HitMask, QueryTriggerInteraction.Ignore))\n"
        "        {\n"
        "            HandleHit(hit, direction);\n"
        "            return true;\n"
        "        }\n"
        "        _statusMessage = \"Miss.\";\n"
        "        RefreshHud();\n"
        "        return true;\n"
        "    }\n\n"
        "    private void HandleHit(RaycastHit hit, Vector3 shotDirection)\n"
        "    {\n"
        "        if (hit.rigidbody != null)\n"
        "        {\n"
        "            hit.rigidbody.AddForceAtPosition(shotDirection * ImpactForce, hit.point, ForceMode.Impulse);\n"
        "        }\n"
        "        _hitMarkerUntil = Time.time + HitMarkerDuration;\n"
        "        var reactiveRoot = FindReactiveTargetRoot(hit.transform);\n"
        "        if (reactiveRoot != null && reactiveRoot.gameObject.activeSelf)\n"
        "        {\n"
        "            reactiveRoot.gameObject.SetActive(false);\n"
        "            _targetsHit += 1;\n"
        "            _statusMessage = $\"Tagged beacon {_targetsHit}/{Mathf.Max(1, _totalTargets)}.\";\n"
        "            RefreshHud();\n"
        "            return;\n"
        "        }\n"
        "        _statusMessage = $\"Hit {hit.collider.name}.\";\n"
        "        RefreshHud();\n"
        "    }\n\n"
        "    private void StartReload()\n"
        "    {\n"
        "        if (_isReloading || ReserveAmmo <= 0 || _ammoInMagazine >= MagazineSize)\n"
        "        {\n"
        "            return;\n"
        "        }\n"
        "        _isReloading = true;\n"
        "        _reloadCompleteAt = Time.time + Mathf.Max(0.15f, ReloadDuration);\n"
        "        _statusMessage = \"Reloading...\";\n"
        "        RefreshHud();\n"
        "    }\n\n"
        "    private void FinishReloadIfReady()\n"
        "    {\n"
        "        if (!_isReloading || Time.time < _reloadCompleteAt)\n"
        "        {\n"
        "            return;\n"
        "        }\n"
        "        int missing = Mathf.Max(0, MagazineSize - _ammoInMagazine);\n"
        "        int loaded = Mathf.Min(missing, ReserveAmmo);\n"
        "        _ammoInMagazine += loaded;\n"
        "        ReserveAmmo -= loaded;\n"
        "        _isReloading = false;\n"
        "        _statusMessage = loaded > 0 ? \"Reloaded.\" : \"No reserve ammo.\";\n"
        "        RefreshHud();\n"
        "    }\n\n"
        "    private void CacheHudReferences()\n"
        "    {\n"
        "        var root = transform.root;\n"
        "        _objectiveText = FindTextBySuffix(root, \"_ObjectiveBody\");\n"
        "        _ammoText = FindTextBySuffix(root, \"_AmmoLabel\");\n"
        "        _sensitivityText = FindTextBySuffix(root, \"_SensitivityLabel\");\n"
        "        _tipText = FindTextBySuffix(root, \"_TipLabel\");\n"
        "    }\n\n"
        "    private UnityEngine.UI.Text FindTextBySuffix(Transform root, string suffix)\n"
        "    {\n"
        "        if (root == null)\n"
        "        {\n"
        "            return null;\n"
        "        }\n"
        "        foreach (var node in root.GetComponentsInChildren<Transform>(true))\n"
        "        {\n"
        "            if (node.name.EndsWith(suffix))\n"
        "            {\n"
        "                return node.GetComponent<UnityEngine.UI.Text>();\n"
        "            }\n"
        "        }\n"
        "        return null;\n"
        "    }\n\n"
        "    private int CountReactiveTargets()\n"
        "    {\n"
        "        int count = 0;\n"
        "        foreach (var node in transform.root.GetComponentsInChildren<Transform>(true))\n"
        "        {\n"
        "            if (node.name.Contains(\"_Beacon\") && (node.parent == null || !node.parent.name.Contains(\"_Beacon\")))\n"
        "            {\n"
        "                count += 1;\n"
        "            }\n"
        "        }\n"
        "        return Mathf.Max(1, count);\n"
        "    }\n\n"
        "    private Transform FindReactiveTargetRoot(Transform current)\n"
        "    {\n"
        "        while (current != null)\n"
        "        {\n"
        "            if (current.name.Contains(\"_Beacon\"))\n"
        "            {\n"
        "                var top = current;\n"
        "                while (top.parent != null && top.parent.name.Contains(\"_Beacon\"))\n"
        "                {\n"
        "                    top = top.parent;\n"
        "                }\n"
        "                return top;\n"
        "            }\n"
        "            current = current.parent;\n"
        "        }\n"
        "        return null;\n"
        "    }\n\n"
        "    private void RefreshHud()\n"
        "    {\n"
        "        if (_objectiveText != null)\n"
        "        {\n"
        "            _objectiveText.text = _targetsHit >= _totalTargets\n"
        "                ? \"Objective complete: both cyan beacons are down.\"\n"
        "                : $\"Objective: tag the cyan beacons. Targets {_targetsHit}/{Mathf.Max(1, _totalTargets)}.\";\n"
        "        }\n"
        "        if (_ammoText != null)\n"
        "        {\n"
        "            _ammoText.text = _isReloading\n"
        "                ? $\"RELOAD   {_ammoInMagazine} / {ReserveAmmo}\"\n"
        "                : $\"AMMO     {_ammoInMagazine} / {ReserveAmmo}\";\n"
        "        }\n"
        "        if (_sensitivityText != null)\n"
        "        {\n"
        "            _sensitivityText.text = $\"SENS     {MouseSensitivity:0.000}  [ / ]\";\n"
        "        }\n"
        "        if (_tipText != null)\n"
        "        {\n"
        "            _tipText.text = \"LMB fire  |  R reload  |  [ / ] sens  |  Shift sprint  |  Esc free cursor\";\n"
        "        }\n"
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
        "        bool cursorLocked = Cursor.lockState == CursorLockMode.Locked;\n"
        "        var mouse = Mouse.current;\n"
        "        if (mouse != null && cursorLocked)\n"
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
        "        if (Cursor.lockState != CursorLockMode.Locked)\n"
        "        {\n"
        "            return Vector2.zero;\n"
        "        }\n"
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
        "    }\n\n"
        "    private bool IsFirePressed()\n"
        "    {\n"
        "#if ENABLE_INPUT_SYSTEM\n"
        "        bool mousePressed = Mouse.current != null && Mouse.current.leftButton.isPressed;\n"
        "        bool gamepadPressed = Gamepad.current != null && Gamepad.current.rightTrigger.ReadValue() > 0.35f;\n"
        "        return mousePressed || gamepadPressed;\n"
        "#else\n"
        "        return Input.GetMouseButton(0);\n"
        "#endif\n"
        "    }\n\n"
        "    private bool WasReloadPressedThisFrame()\n"
        "    {\n"
        "#if ENABLE_INPUT_SYSTEM\n"
        "        var keyboard = Keyboard.current;\n"
        "        bool keyboardPressed = keyboard != null && keyboard.rKey.wasPressedThisFrame;\n"
        "        bool gamepadPressed = Gamepad.current != null && Gamepad.current.buttonWest.wasPressedThisFrame;\n"
        "        return keyboardPressed || gamepadPressed;\n"
        "#else\n"
        "        return Input.GetKeyDown(KeyCode.R);\n"
        "#endif\n"
        "    }\n\n"
        "    private bool WasSensitivityDecreasePressedThisFrame()\n"
        "    {\n"
        "#if ENABLE_INPUT_SYSTEM\n"
        "        var keyboard = Keyboard.current;\n"
        "        return keyboard != null && (keyboard.leftBracketKey.wasPressedThisFrame || keyboard.minusKey.wasPressedThisFrame);\n"
        "#else\n"
        "        return Input.GetKeyDown(KeyCode.LeftBracket) || Input.GetKeyDown(KeyCode.Minus);\n"
        "#endif\n"
        "    }\n\n"
        "    private bool WasSensitivityIncreasePressedThisFrame()\n"
        "    {\n"
        "#if ENABLE_INPUT_SYSTEM\n"
        "        var keyboard = Keyboard.current;\n"
        "        return keyboard != null && (keyboard.rightBracketKey.wasPressedThisFrame || keyboard.equalsKey.wasPressedThisFrame);\n"
        "#else\n"
        "        return Input.GetKeyDown(KeyCode.RightBracket) || Input.GetKeyDown(KeyCode.Equals);\n"
        "#endif\n"
        "    }\n\n"
        "    private bool WasPrimaryPointerPressedThisFrame()\n"
        "    {\n"
        "#if ENABLE_INPUT_SYSTEM\n"
        "        return Mouse.current != null && Mouse.current.leftButton.wasPressedThisFrame;\n"
        "#else\n"
        "        return Input.GetMouseButtonDown(0);\n"
        "#endif\n"
        "    }\n\n"
        "    private bool WasUnlockPressedThisFrame()\n"
        "    {\n"
        "#if ENABLE_INPUT_SYSTEM\n"
        "        return Keyboard.current != null && Keyboard.current.escapeKey.wasPressedThisFrame;\n"
        "#else\n"
        "        return Input.GetKeyDown(KeyCode.Escape);\n"
        "#endif\n"
        "    }\n\n"
        "    private void EnsureGuiStyles()\n"
        "    {\n"
        "        if (_headerStyle != null && _bodyStyle != null && _smallStyle != null)\n"
        "        {\n"
        "            return;\n"
        "        }\n"
        "        _headerStyle = new GUIStyle(GUI.skin.label);\n"
        "        _headerStyle.fontSize = 20;\n"
        "        _headerStyle.fontStyle = FontStyle.Bold;\n"
        "        _headerStyle.normal.textColor = new Color(0.94f, 0.98f, 1f, 1f);\n"
        "        _bodyStyle = new GUIStyle(GUI.skin.label);\n"
        "        _bodyStyle.fontSize = 16;\n"
        "        _bodyStyle.wordWrap = true;\n"
        "        _bodyStyle.normal.textColor = new Color(0.76f, 0.84f, 0.92f, 1f);\n"
        "        _smallStyle = new GUIStyle(GUI.skin.label);\n"
        "        _smallStyle.fontSize = 15;\n"
        "        _smallStyle.normal.textColor = new Color(0.92f, 0.95f, 1f, 1f);\n"
        "    }\n\n"
        "    private void OnGUI()\n"
        "    {\n"
        "        float scale = Mathf.Clamp(Screen.height / 1080f, 0.85f, 1.15f);\n"
        "        if (_objectiveText == null || _ammoText == null || _sensitivityText == null)\n"
        "        {\n"
        "            EnsureGuiStyles();\n"
        "            DrawHudPanel(new Rect(24f * scale, 24f * scale, 430f * scale, 118f * scale), new Color(0.04f, 0.06f, 0.09f, 0.82f));\n"
        "            GUI.Label(new Rect(42f * scale, 38f * scale, 380f * scale, 28f * scale), \"CODEX RANGE // FPS STARTER\", _headerStyle);\n"
        "            GUI.Label(new Rect(42f * scale, 72f * scale, 380f * scale, 52f * scale), _targetsHit >= _totalTargets ? \"Tag complete: both cyan beacons are down.\" : $\"Tag the cyan beacons. Targets {_targetsHit}/{Mathf.Max(1, _totalTargets)}.\", _bodyStyle);\n"
        "            float panelHeight = 142f * scale;\n"
        "            float panelTop = Screen.height - panelHeight - (24f * scale);\n"
        "            DrawHudPanel(new Rect(24f * scale, panelTop, 370f * scale, panelHeight), new Color(0.05f, 0.06f, 0.08f, 0.80f));\n"
        "            GUI.Label(new Rect(42f * scale, panelTop + (18f * scale), 300f * scale, 24f * scale), _isReloading ? $\"RELOAD   {_ammoInMagazine} / {ReserveAmmo}\" : $\"AMMO     {_ammoInMagazine} / {ReserveAmmo}\", _smallStyle);\n"
        "            GUI.Label(new Rect(42f * scale, panelTop + (48f * scale), 300f * scale, 24f * scale), $\"SENS     {MouseSensitivity:0.000}  [ / ]\", _smallStyle);\n"
        "            GUI.Label(new Rect(42f * scale, panelTop + (78f * scale), 300f * scale, 24f * scale), _statusMessage, _smallStyle);\n"
        "            GUI.Label(new Rect(42f * scale, panelTop + (106f * scale), 312f * scale, 24f * scale), \"LMB fire  |  R reload  |  Shift sprint  |  Esc cursor\", _bodyStyle);\n"
        "        }\n"
        "        if (Time.time < _hitMarkerUntil)\n"
        "        {\n"
        "            DrawHitMarker(scale);\n"
        "        }\n"
        "    }\n\n"
        "    private void DrawHudPanel(Rect rect, Color color)\n"
        "    {\n"
        "        DrawSolidRect(rect, color);\n"
        "        DrawSolidRect(new Rect(rect.x, rect.y, rect.width, 3f), new Color(0.20f, 0.86f, 1f, 0.88f));\n"
        "    }\n\n"
        "    private void DrawCrosshair(float scale)\n"
        "    {\n"
        "        float cx = Screen.width * 0.5f;\n"
        "        float cy = Screen.height * 0.5f;\n"
        "        float gap = 8f * scale;\n"
        "        float arm = 12f * scale;\n"
        "        float thickness = 3f * scale;\n"
        "        DrawCrosshairArm(new Rect(cx - (thickness * 0.5f), cy - gap - arm, thickness, arm));\n"
        "        DrawCrosshairArm(new Rect(cx - (thickness * 0.5f), cy + gap, thickness, arm));\n"
        "        DrawCrosshairArm(new Rect(cx - gap - arm, cy - (thickness * 0.5f), arm, thickness));\n"
        "        DrawCrosshairArm(new Rect(cx + gap, cy - (thickness * 0.5f), arm, thickness));\n"
        "        DrawSolidRect(new Rect(cx - (4f * scale), cy - (4f * scale), 8f * scale, 8f * scale), new Color(0f, 0f, 0f, 0.78f));\n"
        "        DrawSolidRect(new Rect(cx - (2f * scale), cy - (2f * scale), 4f * scale, 4f * scale), new Color(0.98f, 1f, 1f, 1f));\n"
        "    }\n\n"
        "    private void DrawCrosshairArm(Rect rect)\n"
        "    {\n"
        "        DrawSolidRect(new Rect(rect.x - 2f, rect.y - 2f, rect.width + 4f, rect.height + 4f), new Color(0f, 0f, 0f, 0.72f));\n"
        "        DrawSolidRect(rect, new Color(0.92f, 0.98f, 1f, 1f));\n"
        "        DrawSolidRect(new Rect(rect.x + 1f, rect.y + 1f, Mathf.Max(1f, rect.width - 2f), Mathf.Max(1f, rect.height - 2f)), new Color(0.22f, 0.86f, 1f, 0.96f));\n"
        "    }\n\n"
        "    private void DrawHitMarker(float scale)\n"
        "    {\n"
        "        float cx = Screen.width * 0.5f;\n"
        "        float cy = Screen.height * 0.5f;\n"
        "        float size = 18f * scale;\n"
        "        float thickness = 3f * scale;\n"
        "        DrawSolidRect(new Rect(cx - size, cy - size, thickness, size), new Color(1f, 1f, 1f, 0.95f));\n"
        "        DrawSolidRect(new Rect(cx + size - thickness, cy - size, thickness, size), new Color(1f, 1f, 1f, 0.95f));\n"
        "        DrawSolidRect(new Rect(cx - size, cy + size - thickness, thickness, size), new Color(1f, 1f, 1f, 0.95f));\n"
        "        DrawSolidRect(new Rect(cx + size - thickness, cy + size - thickness, thickness, size), new Color(1f, 1f, 1f, 0.95f));\n"
        "    }\n\n"
        "    private void DrawSolidRect(Rect rect, Color color)\n"
        "    {\n"
        "        Color previous = GUI.color;\n"
        "        GUI.color = color;\n"
        "        GUI.DrawTexture(rect, Texture2D.whiteTexture);\n"
        "        GUI.color = previous;\n"
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
cameraComponent.orthographic = false;
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

int ignoreRaycastLayer = UnityEngine.LayerMask.NameToLayer("Ignore Raycast");
if (ignoreRaycastLayer < 0)
{
    ignoreRaycastLayer = 2;
}

var worldReticle = new UnityEngine.GameObject(rootName + "_WorldReticle");
worldReticle.transform.SetParent(cameraGo.transform, false);
worldReticle.transform.localPosition = new UnityEngine.Vector3(0f, 0f, 1.2f);
worldReticle.layer = ignoreRaycastLayer;

foreach (var worldReticlePart in new[]
{
    new { Name = "Top", Position = new UnityEngine.Vector3(0f, 0.06f, 0f), Scale = new UnityEngine.Vector3(0.012f, 0.08f, 0.012f) },
    new { Name = "Bottom", Position = new UnityEngine.Vector3(0f, -0.06f, 0f), Scale = new UnityEngine.Vector3(0.012f, 0.08f, 0.012f) },
    new { Name = "Left", Position = new UnityEngine.Vector3(-0.06f, 0f, 0f), Scale = new UnityEngine.Vector3(0.08f, 0.012f, 0.012f) },
    new { Name = "Right", Position = new UnityEngine.Vector3(0.06f, 0f, 0f), Scale = new UnityEngine.Vector3(0.08f, 0.012f, 0.012f) },
    new { Name = "Center", Position = UnityEngine.Vector3.zero, Scale = new UnityEngine.Vector3(0.018f, 0.018f, 0.012f) },
})
{
    var part = CreatePrimitiveNode(
        rootName + "_WorldReticle" + worldReticlePart.Name,
        UnityEngine.PrimitiveType.Cube,
        worldReticle.transform,
        worldReticlePart.Position,
        worldReticlePart.Scale,
        UnityEngine.Vector3.zero,
        accentMaterial
    );
    part.layer = ignoreRaycastLayer;
    var partCollider = part.GetComponent<UnityEngine.Collider>();
    if (partCollider != null)
    {
        UnityEngine.Object.DestroyImmediate(partCollider);
    }
}

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
    new UnityEngine.Vector2(360f, 152f)
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
    new UnityEngine.Vector2(300f, 30f),
    "AMMO     24 / 96",
    22,
    new UnityEngine.Color(0.96f, 0.96f, 0.98f, 1f),
    UnityEngine.TextAnchor.UpperLeft,
    font
);
CreateTextNode(
    rootName + "_SensitivityLabel",
    statusPanel.transform,
    new UnityEngine.Vector2(0f, 1f),
    new UnityEngine.Vector2(0f, 1f),
    new UnityEngine.Vector2(0f, 1f),
    new UnityEngine.Vector2(18f, -90f),
    new UnityEngine.Vector2(300f, 28f),
    "SENS     0.085  [ / ]",
    20,
    new UnityEngine.Color(0.82f, 0.91f, 0.97f, 1f),
    UnityEngine.TextAnchor.UpperLeft,
    font
);
CreateTextNode(
    rootName + "_TipLabel",
    statusPanel.transform,
    new UnityEngine.Vector2(0f, 0f),
    new UnityEngine.Vector2(1f, 0f),
    new UnityEngine.Vector2(0.5f, 0f),
    new UnityEngine.Vector2(0f, 14f),
    new UnityEngine.Vector2(-24f, 30f),
    "LMB fire  |  R reload  |  [ / ] sens  |  Shift sprint",
    15,
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
    new UnityEngine.Vector2(52f, 52f)
);

foreach (var reticlePart in new[]
{
    new { Name = "Top", Position = new UnityEngine.Vector2(0f, 11f), Size = new UnityEngine.Vector2(4f, 14f) },
    new { Name = "Bottom", Position = new UnityEngine.Vector2(0f, -11f), Size = new UnityEngine.Vector2(4f, 14f) },
    new { Name = "Left", Position = new UnityEngine.Vector2(-11f, 0f), Size = new UnityEngine.Vector2(14f, 4f) },
    new { Name = "Right", Position = new UnityEngine.Vector2(11f, 0f), Size = new UnityEngine.Vector2(14f, 4f) },
})
{
    var backdrop = CreateUiNode(
        rootName + "_ReticleBackdrop" + reticlePart.Name,
        reticleRoot.transform,
        new UnityEngine.Vector2(0.5f, 0.5f),
        new UnityEngine.Vector2(0.5f, 0.5f),
        new UnityEngine.Vector2(0.5f, 0.5f),
        reticlePart.Position,
        reticlePart.Size + new UnityEngine.Vector2(4f, 4f)
    );
    var backdropImage = backdrop.AddComponent<UnityEngine.UI.Image>();
    backdropImage.color = new UnityEngine.Color(0f, 0f, 0f, 0.74f);
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
    segmentImage.color = new UnityEngine.Color(0.96f, 0.99f, 1f, 1f);
}

var reticleCenterBackdrop = CreateUiNode(
    rootName + "_ReticleCenterBackdrop",
    reticleRoot.transform,
    new UnityEngine.Vector2(0.5f, 0.5f),
    new UnityEngine.Vector2(0.5f, 0.5f),
    new UnityEngine.Vector2(0.5f, 0.5f),
    UnityEngine.Vector2.zero,
    new UnityEngine.Vector2(10f, 10f)
);
reticleCenterBackdrop.AddComponent<UnityEngine.UI.Image>().color = new UnityEngine.Color(0f, 0f, 0f, 0.78f);

var reticleCenter = CreateUiNode(
    rootName + "_ReticleCenter",
    reticleRoot.transform,
    new UnityEngine.Vector2(0.5f, 0.5f),
    new UnityEngine.Vector2(0.5f, 0.5f),
    new UnityEngine.Vector2(0.5f, 0.5f),
    UnityEngine.Vector2.zero,
    new UnityEngine.Vector2(4f, 4f)
);
reticleCenter.AddComponent<UnityEngine.UI.Image>().color = new UnityEngine.Color(0.22f, 0.86f, 1f, 1f);
reticleRoot.SetActive(false);

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
