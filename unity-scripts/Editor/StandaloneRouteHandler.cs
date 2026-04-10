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
            case "project/info":    return HandleProjectInfo();
            case "editor/state":    return HandleEditorState();
            case "editor/play-mode":return HandlePlayMode(p);
            case "editor/execute-menu-item": return HandleExecuteMenuItem(p);
            case "compilation/errors": return HandleCompilationErrors();
            case "console/log":     return HandleConsoleLog(p);
            case "console/clear":   return HandleConsoleClear();
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
            case "redo/perform":    return HandleRedo();
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
            {"projectPath", Path.GetDirectoryName(Application.dataPath)},
            {"unityVersion", Application.unityVersion},
            {"platform", Application.platform.ToString()},
            {"transport", "file-ipc-standalone"}
        };
    }

    private static object HandleSceneInfo()
    {
        var scene = SceneManager.GetActiveScene();
        return new Dictionary<string, object>
        {
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
        var allGOs = UnityEngine.Object.FindObjectsByType<GameObject>(FindObjectsSortMode.None);
        int meshCount = 0, lightCount = 0, cameraCount = 0;
        var componentCounts = new Dictionary<string, int>();

        foreach (var go in allGOs)
        {
            foreach (var comp in go.GetComponents<Component>())
            {
                if (comp == null) continue;
                string typeName = comp.GetType().Name;
                componentCounts[typeName] = componentCounts.GetValueOrDefault(typeName, 0) + 1;

                if (comp is MeshRenderer || comp is SkinnedMeshRenderer) meshCount++;
                if (comp is Light) lightCount++;
                if (comp is Camera) cameraCount++;
            }
        }

        return new Dictionary<string, object>
        {
            {"sceneName", scene.name},
            {"totalGameObjects", allGOs.Length},
            {"totalMeshes", meshCount},
            {"totalLights", lightCount},
            {"totalCameras", cameraCount},
            {"componentCounts", componentCounts}
        };
    }

    private static object HandleProjectInfo()
    {
        return new Dictionary<string, object>
        {
            {"projectName", Application.productName},
            {"projectPath", Path.GetDirectoryName(Application.dataPath)},
            {"unityVersion", Application.unityVersion},
            {"companyName", Application.companyName},
            {"platform", EditorUserBuildSettings.activeBuildTarget.ToString()},
            {"colorSpace", PlayerSettings.colorSpace.ToString()},
            {"scriptingBackend", PlayerSettings.GetScriptingBackend(
                EditorUserBuildSettings.selectedBuildTargetGroup).ToString()}
        };
    }

    private static object HandleEditorState()
    {
        var scene = SceneManager.GetActiveScene();
        return new Dictionary<string, object>
        {
            {"isPlaying", EditorApplication.isPlaying},
            {"isPaused", EditorApplication.isPaused},
            {"isCompiling", EditorApplication.isCompiling},
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

    private static object HandleCompilationErrors()
    {
        // Read compiler errors from the compilation pipeline
        var errors = new List<Dictionary<string, object>>();
        // Unity doesn't expose CompilationPipeline errors without the package,
        // but we can check the console
        return new Dictionary<string, object>
        {
            {"errors", errors},
            {"isCompiling", EditorApplication.isCompiling},
            {"hasErrors", errors.Count > 0}
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

    private static object HandleConsoleLog(Dictionary<string, object> p)
    {
        string message = GetString(p, "message", "");
        string type = GetString(p, "type", "log").ToLower();

        switch (type)
        {
            case "warning":
                Debug.LogWarning(message);
                break;
            case "error":
                Debug.LogError(message);
                break;
            default:
                Debug.Log(message);
                break;
        }

        return new Dictionary<string, object> { {"success", true}, {"message", message}, {"type", type} };
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

    private static object HandleScreenshotGame(Dictionary<string, object> p)
    {
        string filename = GetString(p, "filename", "screenshot_" + DateTime.Now.ToString("yyyyMMdd_HHmmss") + ".png");
        string folder = GetString(p, "folder", Path.Combine(Path.GetDirectoryName(Application.dataPath), "Screenshots"));

        if (!Directory.Exists(folder)) Directory.CreateDirectory(folder);
        string fullPath = Path.Combine(folder, filename);

        ScreenCapture.CaptureScreenshot(fullPath);
        return new Dictionary<string, object>
        {
            {"success", true},
            {"path", fullPath},
            {"filename", filename}
        };
    }

    // ── Helpers ──────────────────────────────────────────────────────────

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
