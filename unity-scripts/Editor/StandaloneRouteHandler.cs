/*
 * StandaloneRouteHandler.cs — Core Unity routes without the full MCP plugin
 *
 * This handles ~20 essential routes that the CLI uses most often.
 * When the full AnkleBreaker Unity MCP plugin is installed,
 * FileIPCBridge will dispatch to it first; this only runs as fallback.
 *
 * All execution happens on Unity's main thread (called from
 * EditorApplication.update via FileIPCBridge), so there are no
 * threading issues with EditorPrefs, AssetDatabase, etc.
 */

using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

public static class StandaloneRouteHandler
{
    /// <summary>
    /// Handle a route and return a serializable result object.
    /// Returns null if the route is not recognized.
    /// </summary>
    public static object Handle(string route, string paramsJson)
    {
        var p = string.IsNullOrEmpty(paramsJson) ? new Dictionary<string, object>() : MiniJson.Deserialize(paramsJson);

        switch (route)
        {
            case "ping":            return HandlePing();
            case "scene/info":      return HandleSceneInfo();
            case "scene/hierarchy": return HandleSceneHierarchy(p);
            case "scene/save":      return HandleSceneSave();
            case "scene/new":       return HandleSceneNew(p);
            case "scene/stats":     return HandleSceneStats();
            case "search/scene-stats": return HandleSceneStats();
            case "project/info":    return HandleProjectInfo();
            case "context":         return HandleContext(p);
            case "editor/state":    return HandleEditorState();
            case "editor/play-mode":return HandlePlayMode(p);
            case "editor/execute-menu-item": return HandleExecuteMenuItem(p);
            case "debug/breadcrumb": return HandleDebugBreadcrumb(p);
            case "compilation/errors": return HandleCompilationErrors(p);
            case "console/log":     return HandleConsoleLog(p);
            case "console/clear":   return HandleConsoleClear();
            case "search/missing-references": return HandleMissingReferences(p);
            case "gameobject/create": return HandleGameObjectCreate(p);
            case "gameobject/delete": return HandleGameObjectDelete(p);
            case "gameobject/info": return HandleGameObjectInfo(p);
            case "gameobject/set-active": return HandleGameObjectSetActive(p);
            case "gameobject/set-transform": return HandleSetTransform(p);
            case "component/add":   return HandleComponentAdd(p);
            case "component/get-properties": return HandleComponentGetProperties(p);
            case "asset/list":      return HandleAssetList(p);
            case "script/create":   return HandleScriptCreate(p);
            case "script/read":     return HandleScriptRead(p);
            case "undo/perform":    return HandleUndo();
            case "undo/redo":       return HandleRedo();
            case "redo/perform":    return HandleRedo();
            case "graphics/game-capture": return HandleGraphicsGameCapture(p);
            case "graphics/scene-capture": return HandleGraphicsSceneCapture(p);
            case "screenshot/game": return HandleScreenshotGame(p);
            default:
                return new ErrorResult { error = "Unknown route: " + route, unknownRoute = true };
        }
    }

    // ── Route Handlers ──────────────────────────────────────────────────

    private static object HandlePing()
    {
        return new Dictionary<string, object>
        {
            {"status", "ok"},
            {"projectName", Application.productName},
            {"productName", Application.productName},
            {"projectPath", Path.GetDirectoryName(Application.dataPath)},
            {"unityVersion", Application.unityVersion},
            {"platform", Application.platform.ToString()},
            {"renderPipeline", GetRenderPipelineName()},
            {"transport", "file-ipc-standalone"}
        };
    }

    private static object HandleSceneInfo()
    {
        var scene = SceneManager.GetActiveScene();
        return new Dictionary<string, object>
        {
            {"activeScene", scene.name},
            {"name", scene.name},
            {"path", scene.path},
            {"isDirty", scene.isDirty},
            {"rootCount", scene.rootCount},
            {"isLoaded", scene.isLoaded}
        };
    }

    private static object HandleSceneHierarchy(Dictionary<string, object> p)
    {
        int maxDepth = GetInt(p, "maxDepth", 10);
        int maxNodes = GetInt(p, "maxNodes", 500);
        var scene = SceneManager.GetActiveScene();
        var roots = scene.GetRootGameObjects();
        var nodes = new List<Dictionary<string, object>>();
        int count = 0;

        foreach (var root in roots)
        {
            if (count >= maxNodes) break;
            nodes.Add(BuildNode(root, 0, maxDepth, maxNodes, ref count));
        }

        return new Dictionary<string, object>
        {
            {"sceneName", scene.name},
            {"rootCount", roots.Length},
            {"nodes", nodes},
            {"totalTraversed", count}
        };
    }

    private static Dictionary<string, object> BuildNode(GameObject go, int depth, int maxDepth, int maxNodes, ref int count)
    {
        count++;
        var node = new Dictionary<string, object>
        {
            {"name", go.name},
            {"path", GetPath(go)},
            {"active", go.activeSelf},
            {"components", go.GetComponents<Component>()
                .Where(c => c != null)
                .Select(c => c.GetType().Name)
                .ToArray()},
            {"childCount", go.transform.childCount}
        };

        if (depth < maxDepth && go.transform.childCount > 0)
        {
            var children = new List<Dictionary<string, object>>();
            for (int i = 0; i < go.transform.childCount && count < maxNodes; i++)
            {
                children.Add(BuildNode(go.transform.GetChild(i).gameObject, depth + 1, maxDepth, maxNodes, ref count));
            }
            node["children"] = children;
        }

        return node;
    }

    private static object HandleSceneSave()
    {
        var scene = SceneManager.GetActiveScene();
        EditorSceneManager.SaveScene(scene);
        return new Dictionary<string, object>
        {
            {"success", true},
            {"scene", scene.name},
            {"path", scene.path}
        };
    }

    private static object HandleSceneNew(Dictionary<string, object> p)
    {
        string name = GetString(p, "name", "Untitled");
        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
        return new Dictionary<string, object>
        {
            {"success", true},
            {"sceneName", name},
            {"path", scene.path}
        };
    }

    private static object HandleSceneStats()
    {
        var scene = SceneManager.GetActiveScene();
        var allGOs = EnumerateSceneGameObjects(scene).ToList();
        int totalComponents = 0;
        int meshCount = 0;
        int totalVertices = 0;
        int totalTriangles = 0;
        int lightCount = 0;
        int cameraCount = 0;
        int colliderCount = 0;
        int rigidbodyCount = 0;
        var componentCounts = new Dictionary<string, int>();

        foreach (var go in allGOs)
        {
            foreach (var comp in go.GetComponents<Component>())
            {
                if (comp == null) continue;
                totalComponents++;
                string typeName = comp.GetType().Name;
                int existingCount;
                componentCounts.TryGetValue(typeName, out existingCount);
                componentCounts[typeName] = existingCount + 1;

                if (comp is MeshFilter meshFilter && meshFilter.sharedMesh != null)
                {
                    meshCount++;
                    totalVertices += meshFilter.sharedMesh.vertexCount;
                    totalTriangles += meshFilter.sharedMesh.triangles.Length / 3;
                }
                else if (comp is SkinnedMeshRenderer skinnedMeshRenderer && skinnedMeshRenderer.sharedMesh != null)
                {
                    meshCount++;
                    totalVertices += skinnedMeshRenderer.sharedMesh.vertexCount;
                    totalTriangles += skinnedMeshRenderer.sharedMesh.triangles.Length / 3;
                }
                if (comp is Light) lightCount++;
                if (comp is Camera) cameraCount++;
                if (comp is Collider) colliderCount++;
                if (comp is Rigidbody || comp is Rigidbody2D) rigidbodyCount++;
            }
        }

        return new Dictionary<string, object>
        {
            {"sceneName", scene.name},
            {"totalGameObjects", allGOs.Count},
            {"totalComponents", totalComponents},
            {"totalMeshes", meshCount},
            {"totalVertices", totalVertices},
            {"totalTriangles", totalTriangles},
            {"totalLights", lightCount},
            {"totalCameras", cameraCount},
            {"totalColliders", colliderCount},
            {"totalRigidbodies", rigidbodyCount},
            {"topComponents", componentCounts
                .OrderByDescending(pair => pair.Value)
                .ThenBy(pair => pair.Key, StringComparer.Ordinal)
                .Take(12)
                .Select(pair => new Dictionary<string, object>
                {
                    {"type", pair.Key},
                    {"count", pair.Value}
                })
                .ToList()}
        };
    }

    private static object HandleProjectInfo()
    {
        return new Dictionary<string, object>
        {
            {"productName", Application.productName},
            {"projectName", Application.productName},
            {"projectPath", Path.GetDirectoryName(Application.dataPath)},
            {"unityVersion", Application.unityVersion},
            {"companyName", Application.companyName},
            {"platform", EditorUserBuildSettings.activeBuildTarget.ToString()},
            {"colorSpace", PlayerSettings.colorSpace.ToString()},
            {"renderPipeline", GetRenderPipelineName()},
            {"scriptingBackend", PlayerSettings.GetScriptingBackend(
                UnityEditor.Build.NamedBuildTarget.FromBuildTargetGroup(
                    EditorUserBuildSettings.selectedBuildTargetGroup)).ToString()}
        };
    }

    private static object HandleContext(Dictionary<string, object> p)
    {
        string category = GetString(p, "category", "");
        string projectRoot = Path.GetDirectoryName(Application.dataPath);
        string contextAssetPath = "Assets/MCP/Context";
        string contextFullPath = Path.Combine(projectRoot, "Assets", "MCP", "Context");
        bool enabled = Directory.Exists(contextFullPath);
        var categoryPayloads = new List<Dictionary<string, object>>();

        if (enabled)
        {
            var files = Directory
                .GetFiles(contextFullPath, "*", SearchOption.AllDirectories)
                .Where(path => !path.EndsWith(".meta", StringComparison.OrdinalIgnoreCase))
                .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
                .ToList();

            foreach (string filePath in files)
            {
                string fileCategory = Path.GetFileNameWithoutExtension(filePath);
                if (!string.IsNullOrEmpty(category) && !fileCategory.Equals(category, StringComparison.OrdinalIgnoreCase))
                    continue;

                string relativePath = "Assets/" + filePath
                    .Substring(Application.dataPath.Length)
                    .TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                    .Replace(Path.DirectorySeparatorChar, '/');

                categoryPayloads.Add(new Dictionary<string, object>
                {
                    {"category", fileCategory},
                    {"path", relativePath},
                    {"content", File.ReadAllText(filePath)},
                });
            }
        }

        return new Dictionary<string, object>
        {
            {"enabled", enabled},
            {"projectPath", projectRoot},
            {"unityVersion", Application.unityVersion},
            {"platform", Application.platform.ToString()},
            {"renderPipeline", GetRenderPipelineName()},
            {"contextPath", contextAssetPath},
            {"fileCount", categoryPayloads.Count},
            {"categories", categoryPayloads},
        };
    }

    private static object HandleEditorState()
    {
        var scene = SceneManager.GetActiveScene();
        return new Dictionary<string, object>
        {
            {"isPlaying", EditorApplication.isPlaying},
            {"isPlayingOrWillChangePlaymode", EditorApplication.isPlayingOrWillChangePlaymode},
            {"isPaused", EditorApplication.isPaused},
            {"isCompiling", EditorApplication.isCompiling},
            {"unityVersion", Application.unityVersion},
            {"activeScene", scene.name},
            {"activeScenePath", scene.path},
            {"sceneDirty", scene.isDirty}
        };
    }

    private static object HandlePlayMode(Dictionary<string, object> p)
    {
        string action = GetString(p, "action", "toggle");
        switch (action.ToLower())
        {
            case "play":
            case "enter":
                EditorApplication.isPlaying = true;
                break;
            case "stop":
            case "exit":
                EditorApplication.isPlaying = false;
                break;
            case "pause":
                EditorApplication.isPaused = !EditorApplication.isPaused;
                break;
            default:
                EditorApplication.isPlaying = !EditorApplication.isPlaying;
                break;
        }
        return new Dictionary<string, object>
        {
            {"success", true},
            {"isPlaying", EditorApplication.isPlaying},
            {"isPaused", EditorApplication.isPaused}
        };
    }

    private static object HandleCompilationErrors(Dictionary<string, object> p)
    {
        int requestedCount = GetInt(p, "count", 20);
        var filteredErrors = ReadEditorLogTail(Math.Max(requestedCount * 20, 300))
            .Where(line => LooksLikeCompilationError(line))
            .ToList();
        var errors = filteredErrors
            .Skip(Math.Max(0, filteredErrors.Count - Math.Max(1, requestedCount)))
            .Select(line => new Dictionary<string, object>
            {
                {"message", line.Trim()},
                {"type", "error"},
                {"timestamp", ""},
                {"stackTrace", ""},
            })
            .ToList();

        return new Dictionary<string, object>
        {
            {"count", errors.Count},
            {"isCompiling", EditorApplication.isCompiling},
            {"hasErrors", errors.Count > 0},
            {"entries", errors}
        };
    }

    private static object HandleExecuteMenuItem(Dictionary<string, object> p)
    {
        string menuItem = GetString(p, "menuItem", GetString(p, "path", ""));
        if (string.IsNullOrWhiteSpace(menuItem))
            return new ErrorResult { error = "menuItem is required" };

        bool success = EditorApplication.ExecuteMenuItem(menuItem);
        return new Dictionary<string, object>
        {
            {"success", success},
            {"menuItem", menuItem}
        };
    }

    private static object HandleDebugBreadcrumb(Dictionary<string, object> p)
    {
        string message = GetString(p, "message", "");
        string level = GetString(p, "level", "info").ToLowerInvariant();
        if (string.IsNullOrWhiteSpace(message))
            return new ErrorResult { error = "message is required" };

        LogType logType = LogType.Log;
        switch (level)
        {
            case "warning":
                logType = LogType.Warning;
                break;
            case "error":
                logType = LogType.Error;
                break;
        }

        StackTraceLogType previous = Application.GetStackTraceLogType(logType);
        try
        {
            Application.SetStackTraceLogType(logType, StackTraceLogType.None);
            string prefixed = message.StartsWith("[CLI-TRACE]", StringComparison.Ordinal) ? message : "[CLI-TRACE] " + message;
            if (logType == LogType.Warning)
                Debug.LogWarning(prefixed);
            else if (logType == LogType.Error)
                Debug.LogError(prefixed);
            else
                Debug.Log(prefixed);
        }
        finally
        {
            Application.SetStackTraceLogType(logType, previous);
        }

        return new Dictionary<string, object>
        {
            {"success", true},
            {"message", message},
            {"level", level}
        };
    }

    private static object HandleConsoleLog(Dictionary<string, object> p)
    {
        string requestedType = GetString(p, "type", "all").ToLowerInvariant();
        int requestedCount = GetInt(p, "count", 20);

        var entries = ReadEditorLogTail(Math.Max(requestedCount * 10, 200))
            .Select((line, index) => new Dictionary<string, object>
            {
                {"message", line.Trim()},
                {"type", GuessLogType(line)},
                {"timestamp", ""},
                {"stackTrace", ""},
                {"lineNumber", index + 1},
            })
            .Where(entry =>
            {
                if (requestedType == "all")
                    return true;
                string type = entry["type"].ToString().ToLowerInvariant();
                return type == requestedType || (requestedType == "log" && type == "info");
            })
            .ToList();
        entries = entries
            .Skip(Math.Max(0, entries.Count - Math.Max(1, requestedCount)))
            .ToList();

        return new Dictionary<string, object>
        {
            {"count", entries.Count},
            {"entries", entries}
        };
    }

    private static object HandleConsoleClear()
    {
        // Clear console via reflection (no public API)
        var logEntries = Type.GetType("UnityEditor.LogEntries, UnityEditor");
        if (logEntries != null)
        {
            var clear = logEntries.GetMethod("Clear", System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.Public);
            clear?.Invoke(null, null);
        }
        return new Dictionary<string, object> { {"success", true} };
    }

    private static object HandleMissingReferences(Dictionary<string, object> p)
    {
        int limit = GetInt(p, "limit", 50);
        var results = new List<Dictionary<string, object>>();
        var scene = SceneManager.GetActiveScene();
        int totalFound = 0;
        bool truncated = false;

        foreach (var go in EnumerateSceneGameObjects(scene))
        {
            int missingScriptCount = GameObjectUtility.GetMonoBehavioursWithMissingScriptCount(go);
            if (missingScriptCount > 0)
            {
                totalFound++;
                if (results.Count < limit)
                {
                    results.Add(new Dictionary<string, object>
                    {
                        {"path", GetPath(go)},
                        {"gameObject", go.name},
                        {"component", "MonoBehaviour"},
                        {"issue", $"Missing script reference ({missingScriptCount})"},
                    });
                }
                else
                {
                    truncated = true;
                }
            }

            foreach (var component in go.GetComponents<Component>())
            {
                if (component == null)
                    continue;

                SerializedObject serializedObject;
                try
                {
                    serializedObject = new SerializedObject(component);
                }
                catch
                {
                    continue;
                }

                var iterator = serializedObject.GetIterator();
                bool enterChildren = true;
                while (iterator.NextVisible(enterChildren))
                {
                    enterChildren = false;
                    if (iterator.propertyType != SerializedPropertyType.ObjectReference)
                        continue;
                    if (iterator.objectReferenceValue != null || iterator.objectReferenceInstanceIDValue == 0)
                        continue;

                    totalFound++;
                    if (results.Count < limit)
                    {
                        results.Add(new Dictionary<string, object>
                        {
                            {"path", GetPath(go)},
                            {"gameObject", go.name},
                            {"component", component.GetType().Name},
                            {"property", iterator.propertyPath},
                            {"issue", "Missing object reference"},
                        });
                    }
                    else
                    {
                        truncated = true;
                    }
                }
            }
        }

        var payload = new Dictionary<string, object>
        {
            {"scope", "scene"},
            {"totalFound", totalFound},
            {"returned", results.Count},
            {"limit", limit},
            {"results", results}
        };
        if (truncated)
            payload["truncated"] = true;
        return payload;
    }

    private static object HandleGameObjectCreate(Dictionary<string, object> p)
    {
        string name = GetString(p, "name", "GameObject");
        string parentPath = GetString(p, "parent", null);

        var go = new GameObject(name);
        Undo.RegisterCreatedObjectUndo(go, "Create " + name);

        if (!string.IsNullOrEmpty(parentPath))
        {
            var parent = FindGameObject(parentPath);
            if (parent != null)
            {
                go.transform.SetParent(parent.transform, false);
            }
        }

        return new Dictionary<string, object>
        {
            {"success", true},
            {"name", go.name},
            {"path", GetPath(go)}
        };
    }

    private static object HandleGameObjectDelete(Dictionary<string, object> p)
    {
        string path = GetString(p, "gameObjectPath", GetString(p, "path", ""));
        var go = FindGameObject(path);
        if (go == null)
            return new ErrorResult { error = "GameObject not found: " + path };

        Undo.DestroyObjectImmediate(go);
        return new Dictionary<string, object> { {"success", true}, {"deleted", path} };
    }

    private static object HandleGameObjectInfo(Dictionary<string, object> p)
    {
        string path = GetString(p, "gameObjectPath", GetString(p, "path", ""));
        var go = FindGameObject(path);
        if (go == null)
            return new ErrorResult { error = "GameObject not found: " + path };

        var components = go.GetComponents<Component>()
            .Where(c => c != null)
            .Select(c => c.GetType().Name)
            .ToArray();

        var t = go.transform;
        return new Dictionary<string, object>
        {
            {"name", go.name},
            {"path", GetPath(go)},
            {"active", go.activeSelf},
            {"activeInHierarchy", go.activeInHierarchy},
            {"tag", go.tag},
            {"layer", go.layer},
            {"layerName", LayerMask.LayerToName(go.layer)},
            {"isStatic", go.isStatic},
            {"components", components},
            {"childCount", t.childCount},
            {"position", Vec3Dict(t.position)},
            {"rotation", Vec3Dict(t.eulerAngles)},
            {"scale", Vec3Dict(t.localScale)}
        };
    }

    private static object HandleGameObjectSetActive(Dictionary<string, object> p)
    {
        string path = GetString(p, "gameObjectPath", GetString(p, "path", ""));
        var go = FindGameObject(path);
        if (go == null)
            return new ErrorResult { error = "GameObject not found: " + path };

        bool active = GetBool(p, "active", true);
        Undo.RecordObject(go, "Set Active");
        go.SetActive(active);
        return new Dictionary<string, object>
        {
            {"success", true},
            {"path", GetPath(go)},
            {"active", go.activeSelf}
        };
    }

    private static object HandleSetTransform(Dictionary<string, object> p)
    {
        string path = GetString(p, "gameObjectPath", GetString(p, "path", ""));
        var go = FindGameObject(path);
        if (go == null)
            return new ErrorResult { error = "GameObject not found: " + path };

        var t = go.transform;
        Undo.RecordObject(t, "Set Transform");

        if (p.ContainsKey("position"))
            t.position = ParseVec3(p["position"]);
        if (p.ContainsKey("rotation"))
            t.eulerAngles = ParseVec3(p["rotation"]);
        if (p.ContainsKey("scale"))
            t.localScale = ParseVec3(p["scale"]);

        return new Dictionary<string, object>
        {
            {"success", true},
            {"path", GetPath(go)},
            {"position", Vec3Dict(t.position)},
            {"rotation", Vec3Dict(t.eulerAngles)},
            {"scale", Vec3Dict(t.localScale)}
        };
    }

    private static object HandleComponentAdd(Dictionary<string, object> p)
    {
        string goPath = GetString(p, "gameObjectPath", GetString(p, "path", ""));
        string componentType = GetString(p, "componentType", GetString(p, "type", ""));
        var go = FindGameObject(goPath);
        if (go == null)
            return new ErrorResult { error = "GameObject not found: " + goPath };

        var type = FindComponentType(componentType);
        if (type == null)
            return new ErrorResult { error = "Component type not found: " + componentType };

        var comp = Undo.AddComponent(go, type);
        return new Dictionary<string, object>
        {
            {"success", true},
            {"gameObjectPath", GetPath(go)},
            {"component", comp.GetType().Name}
        };
    }

    private static object HandleComponentGetProperties(Dictionary<string, object> p)
    {
        string goPath = GetString(p, "gameObjectPath", GetString(p, "path", ""));
        string componentType = GetString(p, "componentType", GetString(p, "type", ""));
        var go = FindGameObject(goPath);
        if (go == null)
            return new ErrorResult { error = "GameObject not found: " + goPath };

        var comp = go.GetComponent(componentType);
        if (comp == null)
            return new ErrorResult { error = "Component not found: " + componentType + " on " + goPath };

        var so = new SerializedObject(comp);
        var props = new List<Dictionary<string, object>>();
        var iterator = so.GetIterator();
        iterator.Next(true);

        do
        {
            props.Add(new Dictionary<string, object>
            {
                {"name", iterator.name},
                {"type", iterator.propertyType.ToString()},
                {"displayName", iterator.displayName},
                {"editable", iterator.editable}
            });
        } while (iterator.Next(false));

        return new Dictionary<string, object>
        {
            {"gameObjectPath", GetPath(go)},
            {"component", componentType},
            {"properties", props}
        };
    }

    private static object HandleAssetList(Dictionary<string, object> p)
    {
        string folder = GetString(p, "path", "Assets");
        string type = GetString(p, "type", null);

        string filter = type != null ? "t:" + type : "";
        var guids = AssetDatabase.FindAssets(filter, new[] { folder });
        var assets = guids.Take(200).Select(guid =>
        {
            string assetPath = AssetDatabase.GUIDToAssetPath(guid);
            return new Dictionary<string, object>
            {
                {"path", assetPath},
                {"name", Path.GetFileName(assetPath)},
                {"type", AssetDatabase.GetMainAssetTypeAtPath(assetPath)?.Name ?? "Unknown"}
            };
        }).ToList();

        return new Dictionary<string, object>
        {
            {"path", folder},
            {"count", assets.Count},
            {"totalFound", guids.Length},
            {"assets", assets}
        };
    }

    private static object HandleScriptCreate(Dictionary<string, object> p)
    {
        string assetPath = GetString(p, "path", "");
        string content = GetString(p, "content", "");

        if (string.IsNullOrEmpty(assetPath))
            return new ErrorResult { error = "path is required" };

        string fullPath = Path.Combine(Path.GetDirectoryName(Application.dataPath), assetPath);
        string dir = Path.GetDirectoryName(fullPath);
        if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);

        File.WriteAllText(fullPath, content);
        AssetDatabase.Refresh();

        return new Dictionary<string, object>
        {
            {"success", true},
            {"path", assetPath}
        };
    }

    private static object HandleScriptRead(Dictionary<string, object> p)
    {
        string assetPath = GetString(p, "path", "");
        string fullPath = Path.Combine(Path.GetDirectoryName(Application.dataPath), assetPath);

        if (!File.Exists(fullPath))
            return new ErrorResult { error = "File not found: " + assetPath };

        string content = File.ReadAllText(fullPath);
        return new Dictionary<string, object>
        {
            {"path", assetPath},
            {"content", content},
            {"lineCount", content.Split('\n').Length}
        };
    }

    private static object HandleUndo()
    {
        Undo.PerformUndo();
        return new Dictionary<string, object> { {"success", true}, {"action", "undo"} };
    }

    private static object HandleRedo()
    {
        Undo.PerformRedo();
        return new Dictionary<string, object> { {"success", true}, {"action", "redo"} };
    }

    private static object HandleGraphicsGameCapture(Dictionary<string, object> p)
    {
        int width = Math.Max(1, GetInt(p, "width", 512));
        int height = Math.Max(1, GetInt(p, "height", 512));
        Camera camera = Camera.main ?? UnityEngine.Object.FindObjectsByType<Camera>()
            .FirstOrDefault(cam => cam != null && cam.enabled && cam.gameObject.activeInHierarchy);

        if (camera == null)
            return new ErrorResult { error = "No enabled camera found for game capture." };

        return CaptureCamera(camera, width, height, includeCameraName: true);
    }

    private static object HandleGraphicsSceneCapture(Dictionary<string, object> p)
    {
        int width = Math.Max(1, GetInt(p, "width", 512));
        int height = Math.Max(1, GetInt(p, "height", 512));
        SceneView sceneView = SceneView.lastActiveSceneView ?? SceneView.sceneViews.OfType<SceneView>().FirstOrDefault();

        if (sceneView == null || sceneView.camera == null)
            return new ErrorResult { error = "No SceneView camera available for capture." };

        sceneView.Repaint();
        return CaptureCamera(sceneView.camera, width, height, includeCameraName: false);
    }

    private static object HandleScreenshotGame(Dictionary<string, object> p)
    {
        string filename = GetString(p, "filename", "screenshot_" + DateTime.Now.ToString("yyyyMMdd_HHmmss") + ".png");
        string folder = GetString(p, "folder", Path.Combine(Path.GetDirectoryName(Application.dataPath), "Screenshots"));

        if (!Directory.Exists(folder)) Directory.CreateDirectory(folder);
        string fullPath = Path.Combine(folder, filename);
        var capture = HandleGraphicsGameCapture(new Dictionary<string, object>
        {
            {"width", GetInt(p, "width", 1280)},
            {"height", GetInt(p, "height", 720)},
        }) as Dictionary<string, object>;
        if (capture == null || !capture.ContainsKey("base64"))
            return new ErrorResult { error = "Unable to capture game view." };

        File.WriteAllBytes(fullPath, Convert.FromBase64String(capture["base64"].ToString()));

        return new Dictionary<string, object>
        {
            {"success", true},
            {"path", fullPath},
            {"filename", filename}
        };
    }

    // ── Helpers ──────────────────────────────────────────────────────────

    private static string GetRenderPipelineName()
    {
        RenderPipelineAsset pipeline = GraphicsSettings.currentRenderPipeline;
        return pipeline != null ? pipeline.name : "builtin";
    }

    private static IEnumerable<GameObject> EnumerateSceneGameObjects(Scene scene)
    {
        foreach (var root in scene.GetRootGameObjects())
        {
            foreach (var go in EnumerateGameObjectTree(root))
                yield return go;
        }
    }

    private static IEnumerable<GameObject> EnumerateGameObjectTree(GameObject root)
    {
        yield return root;
        for (int i = 0; i < root.transform.childCount; i++)
        {
            foreach (var child in EnumerateGameObjectTree(root.transform.GetChild(i).gameObject))
                yield return child;
        }
    }

    private static List<string> ReadEditorLogTail(int maxLines)
    {
        string logPath = GetEditorLogPath();
        if (!File.Exists(logPath))
            return new List<string>();

        const int maxBytes = 262144;
        using (var stream = new FileStream(logPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
        {
            long length = stream.Length;
            int bytesToRead = (int)Math.Min(maxBytes, length);
            if (bytesToRead <= 0)
                return new List<string>();

            stream.Seek(-bytesToRead, SeekOrigin.End);
            byte[] buffer = new byte[bytesToRead];
            int read = stream.Read(buffer, 0, bytesToRead);
            string text = Encoding.UTF8.GetString(buffer, 0, read);
            var lines = text
                .Split(new[] { "\r\n", "\n" }, StringSplitOptions.None)
                .ToList();

            if (length > bytesToRead && lines.Count > 0)
                lines.RemoveAt(0);

            var filteredLines = lines
                .Where(line => !string.IsNullOrWhiteSpace(line))
                .ToList();

            return filteredLines
                .Skip(Math.Max(0, filteredLines.Count - Math.Max(1, maxLines)))
                .ToList();
        }
    }

    private static string GetEditorLogPath()
    {
#if UNITY_EDITOR_WIN
        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Unity",
            "Editor",
            "Editor.log");
#elif UNITY_EDITOR_OSX
        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Personal),
            "Library",
            "Logs",
            "Unity",
            "Editor.log");
#else
        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Personal),
            ".config",
            "unity3d",
            "Editor.log");
#endif
    }

    private static bool LooksLikeCompilationError(string line)
    {
        if (string.IsNullOrWhiteSpace(line))
            return false;

        string normalized = line.ToLowerInvariant();
        return normalized.Contains(" error cs")
            || normalized.Contains(": error ")
            || normalized.Contains("error cs")
            || normalized.Contains("all compiler errors have to be fixed")
            || (normalized.Contains(".cs(") && normalized.Contains("error"));
    }

    private static string GuessLogType(string line)
    {
        string normalized = (line ?? string.Empty).ToLowerInvariant();
        if (normalized.Contains("exception"))
            return "exception";
        if (normalized.Contains("error"))
            return "error";
        if (normalized.Contains("warning") || normalized.Contains("warn"))
            return "warning";
        return "info";
    }

    private static Dictionary<string, object> CaptureCamera(Camera camera, int width, int height, bool includeCameraName)
    {
        RenderTexture previousTarget = camera.targetTexture;
        RenderTexture previousActive = RenderTexture.active;
        var renderTexture = new RenderTexture(width, height, 24, RenderTextureFormat.ARGB32);
        var texture = new Texture2D(width, height, TextureFormat.RGB24, false);

        try
        {
            renderTexture.Create();
            camera.targetTexture = renderTexture;
            RenderTexture.active = renderTexture;
            camera.Render();
            texture.ReadPixels(new Rect(0, 0, width, height), 0, 0, false);
            texture.Apply(false, false);

            var payload = new Dictionary<string, object>
            {
                {"success", true},
                {"base64", Convert.ToBase64String(texture.EncodeToPNG())},
                {"width", width},
                {"height", height},
            };
            if (includeCameraName)
                payload["cameraName"] = camera.name;
            return payload;
        }
        finally
        {
            camera.targetTexture = previousTarget;
            RenderTexture.active = previousActive;
            UnityEngine.Object.DestroyImmediate(renderTexture);
            UnityEngine.Object.DestroyImmediate(texture);
        }
    }

    private static string GetPath(GameObject go)
    {
        var parts = new List<string>();
        var t = go.transform;
        while (t != null)
        {
            parts.Insert(0, t.name);
            t = t.parent;
        }
        return "/" + string.Join("/", parts);
    }

    private static GameObject FindGameObject(string path)
    {
        if (string.IsNullOrEmpty(path))
            return null;

        var activeMatch = GameObject.Find(path);
        if (activeMatch != null)
            return activeMatch;

        string normalized = path.Trim('/');
        foreach (var go in Resources.FindObjectsOfTypeAll<GameObject>())
        {
            if (go == null || !go.scene.IsValid())
                continue;
            if (GetPath(go).Trim('/') == normalized || go.name == path)
                return go;
        }
        return null;
    }

    private static string GetString(Dictionary<string, object> p, string key, string defaultValue)
    {
        if (p != null && p.TryGetValue(key, out object val) && val != null)
            return val.ToString();
        return defaultValue;
    }

    private static int GetInt(Dictionary<string, object> p, string key, int defaultValue)
    {
        if (p != null && p.TryGetValue(key, out object val))
        {
            if (val is double d) return (int)d;
            if (val is long l) return (int)l;
            if (val is int i) return i;
            if (int.TryParse(val?.ToString(), out int parsed)) return parsed;
        }
        return defaultValue;
    }

    private static bool GetBool(Dictionary<string, object> p, string key, bool defaultValue)
    {
        if (p != null && p.TryGetValue(key, out object val))
        {
            if (val is bool b) return b;
            if (bool.TryParse(val?.ToString(), out bool parsed)) return parsed;
        }
        return defaultValue;
    }

    private static Dictionary<string, object> Vec3Dict(Vector3 v)
    {
        return new Dictionary<string, object> { {"x", v.x}, {"y", v.y}, {"z", v.z} };
    }

    private static Vector3 ParseVec3(object obj)
    {
        if (obj is Dictionary<string, object> d)
        {
            float x = d.ContainsKey("x") ? Convert.ToSingle(d["x"]) : 0f;
            float y = d.ContainsKey("y") ? Convert.ToSingle(d["y"]) : 0f;
            float z = d.ContainsKey("z") ? Convert.ToSingle(d["z"]) : 0f;
            return new Vector3(x, y, z);
        }
        return Vector3.zero;
    }

    private static Type FindComponentType(string name)
    {
        // Try common Unity namespaces first
        foreach (string prefix in new[] { "UnityEngine.", "UnityEngine.UI.", "" })
        {
            var type = Type.GetType(prefix + name + ", UnityEngine") ??
                       Type.GetType(prefix + name + ", UnityEngine.UI");
            if (type != null && typeof(Component).IsAssignableFrom(type))
                return type;
        }

        // Search all loaded assemblies
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            foreach (var type in asm.GetTypes())
            {
                if (type.Name == name && typeof(Component).IsAssignableFrom(type))
                    return type;
            }
        }
        return null;
    }

    [Serializable]
    public class ErrorResult
    {
        public string error;
        public bool unknownRoute;
    }
}


/// <summary>
/// Minimal JSON parser that doesn't need Unity's JsonUtility (which can't handle Dictionary).
/// Handles the subset the CLI sends: objects, arrays, strings, numbers, booleans, null.
/// </summary>
public static class MiniJson
{
    // ── Serializer ───────────────────────────────────────────────────────

    /// <summary>Serialize any object to JSON. Handles Dictionary, List, array, primitives.</summary>
    public static string Serialize(object obj)
    {
        if (obj == null) return "null";

        if (obj is string s) return "\"" + EscapeString(s) + "\"";
        if (obj is bool b) return b ? "true" : "false";
        if (obj is int || obj is long || obj is short || obj is byte)
            return Convert.ToInt64(obj).ToString(System.Globalization.CultureInfo.InvariantCulture);
        if (obj is float || obj is double || obj is decimal)
            return Convert.ToDouble(obj).ToString("G", System.Globalization.CultureInfo.InvariantCulture);

        if (obj is IDictionary<string, object> dict)
        {
            var sb = new StringBuilder("{");
            bool first = true;
            foreach (var kvp in dict)
            {
                if (!first) sb.Append(',');
                sb.Append('"').Append(EscapeString(kvp.Key)).Append("\":").Append(Serialize(kvp.Value));
                first = false;
            }
            sb.Append('}');
            return sb.ToString();
        }

        if (obj is IEnumerable<object> list)
        {
            var sb = new StringBuilder("[");
            bool first = true;
            foreach (var item in list)
            {
                if (!first) sb.Append(',');
                sb.Append(Serialize(item));
                first = false;
            }
            sb.Append(']');
            return sb.ToString();
        }

        // Generic IEnumerable (string[], int[], etc.)
        if (obj is System.Collections.IEnumerable enumerable)
        {
            var sb = new StringBuilder("[");
            bool first = true;
            foreach (var item in enumerable)
            {
                if (!first) sb.Append(',');
                sb.Append(Serialize(item));
                first = false;
            }
            sb.Append(']');
            return sb.ToString();
        }

        var objectFields = obj.GetType().GetFields(BindingFlags.Instance | BindingFlags.Public);
        var objectProperties = obj.GetType()
            .GetProperties(BindingFlags.Instance | BindingFlags.Public)
            .Where(p => p.CanRead && p.GetIndexParameters().Length == 0)
            .ToArray();
        if (objectFields.Length > 0 || objectProperties.Length > 0)
        {
            var sb = new StringBuilder("{");
            bool first = true;
            foreach (var field in objectFields)
            {
                if (!first) sb.Append(',');
                sb.Append('"').Append(EscapeString(field.Name)).Append("\":").Append(Serialize(field.GetValue(obj)));
                first = false;
            }
            foreach (var property in objectProperties)
            {
                object value;
                try
                {
                    value = property.GetValue(obj, null);
                }
                catch
                {
                    continue;
                }
                if (!first) sb.Append(',');
                sb.Append('"').Append(EscapeString(property.Name)).Append("\":").Append(Serialize(value));
                first = false;
            }
            sb.Append('}');
            return sb.ToString();
        }

        // Fallback: ToString for numeric types we might have missed
        return "\"" + EscapeString(obj.ToString()) + "\"";
    }

    private static string EscapeString(string s)
    {
        if (s == null) return "";
        var sb = new StringBuilder(s.Length + 4);
        foreach (char c in s)
        {
            switch (c)
            {
                case '"':  sb.Append("\\\""); break;
                case '\\': sb.Append("\\\\"); break;
                case '\n': sb.Append("\\n");  break;
                case '\r': sb.Append("\\r");  break;
                case '\t': sb.Append("\\t");  break;
                default:
                    if (c < 0x20)
                        sb.Append(string.Format("\\u{0:x4}", (int)c));
                    else
                        sb.Append(c);
                    break;
            }
        }
        return sb.ToString();
    }

    // ── Deserializer ─────────────────────────────────────────────────────

    public static Dictionary<string, object> Deserialize(string json)
    {
        if (string.IsNullOrEmpty(json)) return new Dictionary<string, object>();
        int index = 0;
        var result = ParseValue(json, ref index);
        return result as Dictionary<string, object> ?? new Dictionary<string, object>();
    }

    private static object ParseValue(string json, ref int i)
    {
        SkipWhitespace(json, ref i);
        if (i >= json.Length) return null;

        switch (json[i])
        {
            case '{': return ParseObject(json, ref i);
            case '[': return ParseArray(json, ref i);
            case '"': return ParseString(json, ref i);
            case 't':
            case 'f': return ParseBool(json, ref i);
            case 'n': i += 4; return null;
            default:  return ParseNumber(json, ref i);
        }
    }

    private static Dictionary<string, object> ParseObject(string json, ref int i)
    {
        var dict = new Dictionary<string, object>();
        i++; // skip {
        SkipWhitespace(json, ref i);
        if (i < json.Length && json[i] == '}') { i++; return dict; }

        while (i < json.Length)
        {
            SkipWhitespace(json, ref i);
            string key = ParseString(json, ref i);
            SkipWhitespace(json, ref i);
            i++; // skip :
            dict[key] = ParseValue(json, ref i);
            SkipWhitespace(json, ref i);
            if (i < json.Length && json[i] == ',') { i++; continue; }
            if (i < json.Length && json[i] == '}') { i++; break; }
        }
        return dict;
    }

    private static List<object> ParseArray(string json, ref int i)
    {
        var list = new List<object>();
        i++; // skip [
        SkipWhitespace(json, ref i);
        if (i < json.Length && json[i] == ']') { i++; return list; }

        while (i < json.Length)
        {
            list.Add(ParseValue(json, ref i));
            SkipWhitespace(json, ref i);
            if (i < json.Length && json[i] == ',') { i++; continue; }
            if (i < json.Length && json[i] == ']') { i++; break; }
        }
        return list;
    }

    private static string ParseString(string json, ref int i)
    {
        i++; // skip opening "
        var sb = new StringBuilder();
        while (i < json.Length)
        {
            char c = json[i++];
            if (c == '"') break;
            if (c == '\\' && i < json.Length)
            {
                char esc = json[i++];
                switch (esc)
                {
                    case '"': sb.Append('"'); break;
                    case '\\': sb.Append('\\'); break;
                    case '/': sb.Append('/'); break;
                    case 'n': sb.Append('\n'); break;
                    case 'r': sb.Append('\r'); break;
                    case 't': sb.Append('\t'); break;
                    case 'u':
                        if (i + 4 <= json.Length)
                        {
                            sb.Append((char)Convert.ToInt32(json.Substring(i, 4), 16));
                            i += 4;
                        }
                        break;
                    default: sb.Append(esc); break;
                }
            }
            else
            {
                sb.Append(c);
            }
        }
        return sb.ToString();
    }

    private static double ParseNumber(string json, ref int i)
    {
        int start = i;
        while (i < json.Length && "0123456789.eE+-".IndexOf(json[i]) >= 0) i++;
        return double.Parse(json.Substring(start, i - start), System.Globalization.CultureInfo.InvariantCulture);
    }

    private static bool ParseBool(string json, ref int i)
    {
        if (json[i] == 't') { i += 4; return true; }
        i += 5; return false;
    }

    private static void SkipWhitespace(string json, ref int i)
    {
        while (i < json.Length && " \t\n\r".IndexOf(json[i]) >= 0) i++;
    }
}
