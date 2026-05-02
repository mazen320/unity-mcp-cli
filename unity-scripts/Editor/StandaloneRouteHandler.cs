/*
 * StandaloneRouteHandler.cs — Core Unity routes without the full MCP plugin
 *
 * This handles ~20 essential routes that the CLI uses most often.
 * When the full optional Unity MCP plugin is installed,
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
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEditor.Animations;
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
        route = (route ?? string.Empty).Trim();
        var p = string.IsNullOrEmpty(paramsJson) ? new Dictionary<string, object>() : MiniJson.Deserialize(paramsJson);

        switch (route)
        {
            case "ping":            return HandlePing();
            case "scene/info":      return HandleSceneInfo();
            case "scene/hierarchy": return HandleSceneHierarchy(p);
            case "scene/save":      return HandleSceneSave();
            case "scene/new":       return HandleSceneNew(p);
            case "scene/create-sandbox": return HandleSceneCreateSandbox(p);
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
            case "search/assets":   return HandleSearchAssets(p);
            case "search/by-component": return HandleSearchByComponent(p);
            case "search/by-layer": return HandleSearchByLayer(p);
            case "search/by-name":  return HandleSearchByName(p);
            case "search/by-tag":   return HandleSearchByTag(p);
            case "search/missing-references": return HandleMissingReferences(p);
            case "selection/get":   return HandleSelectionGet();
            case "selection/set":   return HandleSelectionSet(p);
            case "selection/find-by-type": return HandleSelectionFindByType(p);
            case "selection/focus-scene-view": return HandleSelectionFocusSceneView(p);
            case "gameobject/create": return HandleGameObjectCreate(p);
            case "gameobject/delete": return HandleGameObjectDelete(p);
            case "gameobject/info": return HandleGameObjectInfo(p);
            case "gameobject/set-active": return HandleGameObjectSetActive(p);
            case "gameobject/set-transform": return HandleSetTransform(p);
            case "component/add":   return HandleComponentAdd(p);
            case "component/get-properties": return HandleComponentGetProperties(p);
            case "asset/list":      return HandleAssetList(p);
            case "animation/create-clip": return HandleAnimationCreateClip(p);
            case "animation/create-controller": return HandleAnimationCreateController(p);
            case "animation/assign-controller": return HandleAnimationAssignController(p);
            case "animation/clip-info": return HandleAnimationClipInfo(p);
            case "animation/controller-info": return HandleAnimationControllerInfo(p);
            case "animation/add-parameter": return HandleAnimationAddParameter(p);
            case "animation/add-state": return HandleAnimationAddState(p);
            case "animation/set-default-state": return HandleAnimationSetDefaultState(p);
            case "animation/add-transition": return HandleAnimationAddTransition(p);
            case "animation/remove-transition": return HandleAnimationRemoveTransition(p);
            case "script/create":   return HandleScriptCreate(p);
            case "script/read":     return HandleScriptRead(p);
            case "script/update":   return HandleScriptUpdate(p);
            case "script/list":     return HandleScriptList(p);
            case "script/delete":   return HandleScriptDelete(p);
            case "undo/perform":    return HandleUndo();
            case "undo/redo":       return HandleRedo();
            case "redo/perform":    return HandleRedo();
            case "graphics/game-capture": return HandleGraphicsGameCapture(p);
            case "graphics/scene-capture": return HandleGraphicsSceneCapture(p);
            case "screenshot/game": return HandleScreenshotGame(p);
            // ── New Phase 2 routes ───────────────────────────────────────
            case "component/set-property":  return HandleComponentSetProperty(p);
            case "component/remove":        return HandleComponentRemove(p);
            case "component/list":          return HandleComponentList(p);
            case "component/wire-reference":return HandleComponentWireReference(p);
            case "gameobject/duplicate":    return HandleGameObjectDuplicate(p);
            case "gameobject/reparent":     return HandleGameObjectReparent(p);
            case "gameobject/find":         return HandleGameObjectFind(p);
            case "gameobject/rename":       return HandleGameObjectRename(p);
            case "gameobject/set-tag":      return HandleGameObjectSetTag(p);
            case "gameobject/set-layer":    return HandleGameObjectSetLayer(p);
            case "material/create":         return HandleMaterialCreate(p);
            case "material/set-property":   return HandleMaterialSetProperty(p);
            case "material/get-properties": return HandleMaterialGetProperties(p);
            case "material/assign":         return HandleMaterialAssign(p);
            case "material/list":           return HandleMaterialList(p);
            case "asset/create-material":   return HandleMaterialCreate(p);
            case "prefab/save":             return HandlePrefabSave(p);
            case "prefab/instantiate":      return HandlePrefabInstantiate(p);
            case "prefab/info":             return HandlePrefabInfo(p);
            case "prefab/list":             return HandlePrefabList(p);
            case "asset/create-prefab":     return HandlePrefabSave(p);
            case "asset/instantiate-prefab":return HandlePrefabInstantiate(p);
            case "renderer/set-material":   return HandleMaterialAssign(p);
            case "graphics/material-info":  return HandleGraphicsMaterialInfo(p);
            case "graphics/renderer-info":  return HandleGraphicsRendererInfo(p);
            case "physics/set-gravity":     return HandlePhysicsSetGravity(p);
            case "physics/set-rigidbody":   return HandlePhysicsSetRigidbody(p);
            case "physics/set-collider":    return HandlePhysicsSetCollider(p);
            case "lighting/set-ambient":    return HandleLightingSetAmbient(p);
            case "lighting/set-sun":        return HandleLightingSetSun(p);
            case "asset/create-folder":     return HandleAssetCreateFolder(p);
            case "asset/move":              return HandleAssetMove(p);
            case "asset/delete":            return HandleAssetDelete(p);
            case "tag/add":                 return HandleTagAdd(p);
            case "layer/add":               return HandleLayerAdd(p);
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
        if (string.IsNullOrEmpty(scene.path))
            return new ErrorResult { error = "Active scene has no saved path. Create it with scene/new and a name first." };
        if (!EditorSceneManager.SaveScene(scene))
            return new ErrorResult { error = "Failed to save active scene at " + scene.path };
        return new Dictionary<string, object>
        {
            {"success", true},
            {"scene", scene.name},
            {"path", scene.path}
        };
    }

    private static object HandleSceneNew(Dictionary<string, object> p)
    {
        var activeScene = SceneManager.GetActiveScene();
        bool saveIfDirty = GetBool(p, "saveIfDirty", false);
        bool discardUnsaved = GetBool(p, "discardUnsaved", false);
        if (saveIfDirty && discardUnsaved)
            return new ErrorResult { error = "Choose either saveIfDirty or discardUnsaved, not both." };
        if (activeScene.isDirty)
        {
            if (discardUnsaved)
            {
            }
            else if (saveIfDirty)
            {
                if (string.IsNullOrEmpty(activeScene.path))
                    return new ErrorResult { error = "Active scene is dirty and unsaved. Save it first or pass discardUnsaved." };
                if (!EditorSceneManager.SaveScene(activeScene))
                    return new ErrorResult { error = "Failed to save the active scene before creating a new scene." };
            }
            else
            {
                return new ErrorResult { error = "Active scene has unsaved changes. Pass saveIfDirty or discardUnsaved." };
            }
        }

        string folder = GetString(p, "folder", "Assets/Scenes").Replace("\\", "/").Trim().TrimEnd('/');
        if (string.IsNullOrEmpty(folder))
            folder = "Assets/Scenes";
        if (!folder.StartsWith("Assets", StringComparison.OrdinalIgnoreCase))
            return new ErrorResult { error = "Scene folder must live under Assets/." };

        string name = SanitizeAssetName(GetString(p, "name", "Untitled"), "Untitled");
        string requestedPath = folder + "/" + name + ".unity";
        string relativePath = AssetDatabase.GenerateUniqueAssetPath(requestedPath);
        string projectRoot = Path.GetDirectoryName(Application.dataPath);
        string fullPath = Path.Combine(projectRoot, relativePath.Replace("/", Path.DirectorySeparatorChar.ToString()));
        string targetDirectory = Path.GetDirectoryName(fullPath);
        if (!string.IsNullOrEmpty(targetDirectory))
            Directory.CreateDirectory(targetDirectory);

        var scene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
        if (!EditorSceneManager.SaveScene(scene, relativePath))
            return new ErrorResult { error = "Failed to save new scene at " + relativePath };
        scene = SceneManager.GetActiveScene();
        return new Dictionary<string, object>
        {
            {"success", true},
            {"sceneName", scene.name},
            {"name", scene.name},
            {"requestedName", name},
            {"path", scene.path}
        };
    }

    private static object HandleSceneCreateSandbox(Dictionary<string, object> p)
    {
        string folder = GetString(p, "folder", "Assets/Scenes").Replace("\\", "/").Trim().TrimEnd('/');
        if (string.IsNullOrEmpty(folder))
            folder = "Assets/Scenes";
        if (!folder.StartsWith("Assets", StringComparison.OrdinalIgnoreCase))
            return new ErrorResult { error = "Sandbox scene folder must live under Assets/." };

        bool leaveOpen = GetBool(p, "open", false);
        bool saveIfDirty = GetBool(p, "saveIfDirty", false);
        bool discardUnsaved = GetBool(p, "discardUnsaved", false);
        if (saveIfDirty && discardUnsaved)
            return new ErrorResult { error = "Choose either saveIfDirty or discardUnsaved, not both." };

        var activeScene = SceneManager.GetActiveScene();
        string originalPath = activeScene.path ?? "";
        string originalName = activeScene.name ?? "";

        if (activeScene.isDirty)
        {
            if (discardUnsaved)
            {
            }
            else if (saveIfDirty)
            {
                if (string.IsNullOrEmpty(activeScene.path))
                    return new ErrorResult { error = "Active scene is dirty and unsaved. Save it first or pass discardUnsaved." };
                if (!EditorSceneManager.SaveScene(activeScene))
                    return new ErrorResult { error = "Failed to save the active scene before creating the sandbox scene." };
            }
            else
            {
                return new ErrorResult { error = "Active scene has unsaved changes. Pass saveIfDirty or discardUnsaved." };
            }
        }

        string requestedName = GetString(p, "name", "");
        if (string.IsNullOrWhiteSpace(requestedName))
        {
            requestedName = new string((Application.productName ?? "Project")
                .Where(ch => char.IsLetterOrDigit(ch) || ch == '_')
                .ToArray());
            if (string.IsNullOrWhiteSpace(requestedName))
                requestedName = "Project";
            requestedName += "_Sandbox";
        }

        requestedName = new string(requestedName
            .Where(ch => char.IsLetterOrDigit(ch) || ch == '_' || ch == '-')
            .ToArray());
        if (string.IsNullOrWhiteSpace(requestedName))
            requestedName = "Sandbox";

        string relativePath = folder + "/" + requestedName + ".unity";
        string projectRoot = Path.GetDirectoryName(Application.dataPath);
        string fullPath = Path.Combine(projectRoot, relativePath.Replace("/", Path.DirectorySeparatorChar.ToString()));
        string targetDirectory = Path.GetDirectoryName(fullPath);
        if (!string.IsNullOrEmpty(targetDirectory))
            Directory.CreateDirectory(targetDirectory);

        bool existed = File.Exists(fullPath);
        Scene sandboxScene;
        if (existed)
        {
            sandboxScene = EditorSceneManager.OpenScene(relativePath, OpenSceneMode.Single);
        }
        else
        {
            sandboxScene = EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);
            if (!EditorSceneManager.SaveScene(sandboxScene, relativePath))
                return new ErrorResult { error = "Failed to save sandbox scene at " + relativePath };
        }

        bool reopenedOriginal = false;
        bool keptOpen = true;
        string activeSceneName = sandboxScene.name;

        if (!leaveOpen && !string.IsNullOrEmpty(originalPath))
        {
            Scene reopened = EditorSceneManager.OpenScene(originalPath, OpenSceneMode.Single);
            reopenedOriginal = true;
            keptOpen = false;
            activeSceneName = reopened.name;
        }

        return new Dictionary<string, object>
        {
            {"success", true},
            {"sceneName", requestedName},
            {"path", relativePath},
            {"folder", folder},
            {"existed", existed},
            {"reopenedOriginal", reopenedOriginal},
            {"keptOpen", keptOpen},
            {"originalSceneName", originalName},
            {"originalScenePath", originalPath},
            {"activeSceneName", activeSceneName},
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
        bool full = GetBool(p, "full", false);
        string projectRoot = Path.GetDirectoryName(Application.dataPath);
        var scene = SceneManager.GetActiveScene();

        // ── Scene summary ────────────────────────────────────────────────
        var allGOs = EnumerateSceneGameObjects(scene).ToList();
        var rootNames = scene.GetRootGameObjects()
            .Select(go => go.name)
            .Take(20)
            .ToList();

        var sceneInfo = new Dictionary<string, object>
        {
            {"name", scene.name},
            {"path", scene.path},
            {"isDirty", scene.isDirty},
            {"objectCount", allGOs.Count},
            {"rootObjectCount", scene.rootCount},
            {"rootObjects", rootNames},
        };

        // ── Scripts ──────────────────────────────────────────────────────
        var scriptGuids = AssetDatabase.FindAssets("t:MonoScript", new[] {"Assets"});
        var scripts = scriptGuids
            .Select(guid => AssetDatabase.GUIDToAssetPath(guid))
            .Where(path => path.EndsWith(".cs", StringComparison.OrdinalIgnoreCase)
                        && !path.Contains("/Editor/")
                        && !path.Contains(".generated."))
            .OrderBy(path => path)
            .Take(200)
            .Select(path => new Dictionary<string, object>
            {
                {"name", Path.GetFileNameWithoutExtension(path)},
                {"path", path}
            })
            .ToList<object>();

        var allScriptGuids = AssetDatabase.FindAssets("t:MonoScript", new[] {"Assets"});

        // ── Asset counts ─────────────────────────────────────────────────
        var assetCounts = new Dictionary<string, object>
        {
            {"scripts",   AssetDatabase.FindAssets("t:MonoScript",        new[]{"Assets"}).Length},
            {"prefabs",   AssetDatabase.FindAssets("t:Prefab",            new[]{"Assets"}).Length},
            {"materials", AssetDatabase.FindAssets("t:Material",          new[]{"Assets"}).Length},
            {"scenes",    AssetDatabase.FindAssets("t:SceneAsset",        new[]{"Assets"}).Length},
            {"textures",  AssetDatabase.FindAssets("t:Texture",           new[]{"Assets"}).Length},
            {"models",    AssetDatabase.FindAssets("t:Model",             new[]{"Assets"}).Length},
            {"animations",AssetDatabase.FindAssets("t:AnimationClip",     new[]{"Assets"}).Length},
            {"audio",     AssetDatabase.FindAssets("t:AudioClip",         new[]{"Assets"}).Length},
        };

        // ── Packages ─────────────────────────────────────────────────────
        var packages = new List<object>();
        try
        {
            string manifestPath = Path.Combine(projectRoot, "Packages", "manifest.json");
            if (File.Exists(manifestPath))
            {
                string manifestText = File.ReadAllText(manifestPath);
                var manifest = MiniJson.Deserialize(manifestText);
                if (manifest.TryGetValue("dependencies", out object deps) && deps is Dictionary<string, object> depsDict)
                {
                    foreach (var kv in depsDict)
                    {
                        // Skip built-in modules and 2D packages unless asking for full
                        if (!full && (kv.Key.StartsWith("com.unity.modules.") || kv.Key.StartsWith("com.unity.2d.")))
                            continue;
                        packages.Add(new Dictionary<string, object> { {"name", kv.Key}, {"version", kv.Value?.ToString() ?? ""} });
                    }
                }
            }
        }
        catch { }

        // ── Compile errors ───────────────────────────────────────────────
        var compileErrors = new List<object>();
        try
        {
            var filteredErrors = ReadEditorLogTail(300)
                .Where(line => LooksLikeCompilationError(line))
                .Take(10)
                .Select(line => (object)new Dictionary<string, object>
                {
                    {"message", line.Trim()},
                    {"type", "error"}
                })
                .ToList();
            compileErrors = filteredErrors;
        }
        catch { }

        // ── Tags & layers ────────────────────────────────────────────────
        var tags = new List<object>();
        var layers = new List<object>();
        try
        {
            foreach (var tag in UnityEditorInternal.InternalEditorUtility.tags)
                tags.Add(tag);
            foreach (var layer in UnityEditorInternal.InternalEditorUtility.layers)
                layers.Add(layer);
        }
        catch { }

        // ── Recent console errors (captured by FileIPCBridge) ────────────
        var recentConsoleErrors = new List<object>();
        // FileIPCBridge captures logs — expose via shared static if available
        try
        {
            var bridgeType = typeof(FileIPCBridge);
            var logsField = bridgeType.GetField("_recentErrors",
                BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public);
            if (logsField != null && logsField.GetValue(null) is List<Dictionary<string,object>> bridgeLogs)
            {
                recentConsoleErrors = bridgeLogs.Take(5).Cast<object>().ToList();
            }
        }
        catch { }

        // ── Legacy MCP context files (kept for backwards compat) ─────────
        string contextFullPath = Path.Combine(projectRoot, "Assets", "MCP", "Context");
        var legacyCategories = new List<object>();
        if (full && Directory.Exists(contextFullPath))
        {
            try
            {
                var files = Directory.GetFiles(contextFullPath, "*", SearchOption.AllDirectories)
                    .Where(f => !f.EndsWith(".meta", StringComparison.OrdinalIgnoreCase))
                    .OrderBy(f => f, StringComparer.OrdinalIgnoreCase);
                foreach (string filePath in files)
                {
                    legacyCategories.Add(new Dictionary<string, object>
                    {
                        {"category", Path.GetFileNameWithoutExtension(filePath)},
                        {"content", File.ReadAllText(filePath)},
                    });
                }
            }
            catch { }
        }

        // ── Assemble result ───────────────────────────────────────────────
        var result = new Dictionary<string, object>
        {
            {"projectName",      Application.productName},
            {"unityVersion",     Application.unityVersion},
            {"renderPipeline",   GetRenderPipelineName()},
            {"platform",         EditorUserBuildSettings.activeBuildTarget.ToString()},
            {"projectPath",      projectRoot},
            {"isCompiling",      EditorApplication.isCompiling},
            {"isPlaying",        EditorApplication.isPlaying},
            {"scene",            sceneInfo},
            {"scripts",          scripts},
            {"scriptCount",      allScriptGuids.Length},
            {"assetCounts",      assetCounts},
            {"packages",         packages},
            {"compileErrors",    compileErrors},
            {"recentConsoleErrors", recentConsoleErrors},
            {"tags",             tags},
            {"layers",           layers},
        };

        if (full && legacyCategories.Count > 0)
            result["legacyContext"] = legacyCategories;

        return result;
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
            {"isUpdating", EditorApplication.isUpdating},
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

    private static object HandleSearchAssets(Dictionary<string, object> p)
    {
        string query = GetString(p, "query", GetString(p, "searchPattern", ""));
        string assetType = GetString(p, "type", GetString(p, "assetType", ""));
        string folder = GetString(p, "folder", GetString(p, "path", ""));
        int maxResults = Math.Max(1, GetInt(p, "maxResults", GetInt(p, "limit", 20)));

        string filter = string.IsNullOrWhiteSpace(query) ? string.Empty : query.Trim();
        if (!string.IsNullOrWhiteSpace(assetType))
            filter = string.IsNullOrWhiteSpace(filter) ? $"t:{assetType}" : $"{filter} t:{assetType}";

        string[] folders = string.IsNullOrWhiteSpace(folder) ? null : new[] { folder.Replace("\\", "/") };
        var guids = AssetDatabase.FindAssets(filter, folders);
        var results = new List<Dictionary<string, object>>();

        foreach (string guid in guids.Take(maxResults))
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            Type mainType = AssetDatabase.GetMainAssetTypeAtPath(path);
            results.Add(new Dictionary<string, object>
            {
                {"guid", guid},
                {"path", path},
                {"name", Path.GetFileNameWithoutExtension(path)},
                {"type", mainType != null ? mainType.Name : "Unknown"},
            });
        }

        return new Dictionary<string, object>
        {
            {"query", query},
            {"type", assetType},
            {"folder", folder},
            {"count", results.Count},
            {"totalFound", guids.Length},
            {"results", results}
        };
    }

    private static object HandleSearchByComponent(Dictionary<string, object> p)
    {
        string componentType = GetString(p, "componentType", GetString(p, "component", ""));
        if (string.IsNullOrWhiteSpace(componentType))
            return new ErrorResult { error = "componentType is required." };

        Type component = FindComponentType(componentType);
        if (component == null)
            return new ErrorResult { error = "Component type not found: " + componentType };

        bool includeInactive = GetBool(p, "includeInactive", false);
        int limit = Math.Max(1, GetInt(p, "limit", 50));
        var results = new List<Dictionary<string, object>>();

        foreach (GameObject go in EnumerateSceneGameObjects(SceneManager.GetActiveScene()))
        {
            if (!includeInactive && !go.activeInHierarchy)
                continue;
            if (go.GetComponent(component) == null)
                continue;

            results.Add(BuildGameObjectResult(go));
            if (results.Count >= limit)
                break;
        }

        return new Dictionary<string, object>
        {
            {"component", componentType},
            {"count", results.Count},
            {"results", results}
        };
    }

    private static object HandleSearchByLayer(Dictionary<string, object> p)
    {
        string requestedLayer = GetString(p, "layer", GetString(p, "layerName", "Default"));
        int layerIndex;
        if (!int.TryParse(requestedLayer, out layerIndex))
        {
            layerIndex = LayerMask.NameToLayer(requestedLayer);
        }

        if (layerIndex < 0 || layerIndex > 31)
            return new ErrorResult { error = "Layer not found: " + requestedLayer };

        bool includeInactive = GetBool(p, "includeInactive", false);
        int limit = Math.Max(1, GetInt(p, "limit", 50));
        var results = new List<Dictionary<string, object>>();

        foreach (GameObject go in EnumerateSceneGameObjects(SceneManager.GetActiveScene()))
        {
            if (!includeInactive && !go.activeInHierarchy)
                continue;
            if (go.layer != layerIndex)
                continue;

            results.Add(BuildGameObjectResult(go));
            if (results.Count >= limit)
                break;
        }

        return new Dictionary<string, object>
        {
            {"layer", LayerMask.LayerToName(layerIndex)},
            {"layerIndex", layerIndex},
            {"count", results.Count},
            {"results", results}
        };
    }

    private static object HandleSearchByName(Dictionary<string, object> p)
    {
        string pattern = GetString(p, "name", GetString(p, "pattern", ""));
        if (string.IsNullOrWhiteSpace(pattern))
            return new ErrorResult { error = "name or pattern is required." };

        bool includeInactive = GetBool(p, "includeInactive", false);
        bool useRegex = GetBool(p, "regex", false);
        int limit = Math.Max(1, GetInt(p, "limit", 50));
        Regex regex = null;

        if (useRegex)
        {
            try
            {
                regex = new Regex(pattern, RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
            }
            catch (ArgumentException ex)
            {
                return new ErrorResult { error = "Invalid regex pattern: " + ex.Message };
            }
        }

        var results = new List<Dictionary<string, object>>();
        foreach (GameObject go in EnumerateSceneGameObjects(SceneManager.GetActiveScene()))
        {
            if (!includeInactive && !go.activeInHierarchy)
                continue;

            string path = GetPath(go);
            bool matches = regex != null
                ? regex.IsMatch(go.name) || regex.IsMatch(path)
                : go.name.IndexOf(pattern, StringComparison.OrdinalIgnoreCase) >= 0
                    || path.IndexOf(pattern, StringComparison.OrdinalIgnoreCase) >= 0;
            if (!matches)
                continue;

            results.Add(BuildGameObjectResult(go));
            if (results.Count >= limit)
                break;
        }

        return new Dictionary<string, object>
        {
            {"name", pattern},
            {"regex", useRegex},
            {"count", results.Count},
            {"results", results}
        };
    }

    private static object HandleSearchByTag(Dictionary<string, object> p)
    {
        string tag = GetString(p, "tag", "");
        if (string.IsNullOrWhiteSpace(tag))
            return new ErrorResult { error = "tag is required." };

        bool includeInactive = GetBool(p, "includeInactive", false);
        int limit = Math.Max(1, GetInt(p, "limit", 50));
        var results = new List<Dictionary<string, object>>();

        foreach (GameObject go in EnumerateSceneGameObjects(SceneManager.GetActiveScene()))
        {
            if (!includeInactive && !go.activeInHierarchy)
                continue;

            bool matches;
            try
            {
                matches = go.CompareTag(tag);
            }
            catch
            {
                matches = string.Equals(go.tag, tag, StringComparison.OrdinalIgnoreCase);
            }

            if (!matches)
                continue;

            results.Add(BuildGameObjectResult(go));
            if (results.Count >= limit)
                break;
        }

        return new Dictionary<string, object>
        {
            {"tag", tag},
            {"count", results.Count},
            {"results", results}
        };
    }

    private static object HandleSelectionGet()
    {
        GameObject[] selected = Selection.gameObjects
            .Where(go => go != null && go.scene.IsValid())
            .ToArray();

        return BuildSelectionPayload(selected);
    }

    private static object HandleSelectionSet(Dictionary<string, object> p)
    {
        var targets = new List<GameObject>();

        if (p != null && p.TryGetValue("paths", out object rawPaths) && rawPaths is IEnumerable<object> pathValues)
        {
            foreach (object value in pathValues)
            {
                GameObject go = FindGameObject(value != null ? value.ToString() : "");
                if (go != null && !targets.Contains(go))
                    targets.Add(go);
            }
        }

        string singlePath = GetString(p, "path", "");
        if (string.IsNullOrWhiteSpace(singlePath))
            singlePath = GetString(p, "gameObjectPath", "");
        if (!string.IsNullOrWhiteSpace(singlePath))
        {
            GameObject go = FindGameObject(singlePath);
            if (go != null && !targets.Contains(go))
                targets.Add(go);
        }

        if (p != null && p.TryGetValue("instanceId", out object rawInstanceId) && rawInstanceId != null)
        {
            GameObject go = FindGameObject(Convert.ToInt32(rawInstanceId));
            if (go != null && !targets.Contains(go))
                targets.Add(go);
        }

        if (targets.Count == 0)
            return new ErrorResult { error = "No valid selection targets were found." };

        Selection.objects = targets.Cast<UnityEngine.Object>().ToArray();
        Selection.activeGameObject = targets[0];
        EditorGUIUtility.PingObject(targets[0]);
        return BuildSelectionPayload(targets.ToArray(), success: true);
    }

    private static object HandleSelectionFindByType(Dictionary<string, object> p)
    {
        string typeName = GetString(p, "typeName", GetString(p, "type", ""));
        if (string.IsNullOrWhiteSpace(typeName))
            return new ErrorResult { error = "typeName is required." };

        Type component = FindComponentType(typeName);
        if (component == null)
            return new ErrorResult { error = "Component type not found: " + typeName };

        bool includeInactive = GetBool(p, "includeInactive", false);
        int limit = Math.Max(1, GetInt(p, "limit", 50));
        var results = new List<Dictionary<string, object>>();

        foreach (GameObject go in EnumerateSceneGameObjects(SceneManager.GetActiveScene()))
        {
            if (!includeInactive && !go.activeInHierarchy)
                continue;
            if (go.GetComponent(component) == null)
                continue;

            results.Add(BuildGameObjectResult(go));
            if (results.Count >= limit)
                break;
        }

        return new Dictionary<string, object>
        {
            {"typeName", typeName},
            {"count", results.Count},
            {"paths", results.Select(result => result["path"]).ToArray()},
            {"results", results}
        };
    }

    private static object HandleSelectionFocusSceneView(Dictionary<string, object> p)
    {
        SceneView sceneView = SceneView.lastActiveSceneView ?? SceneView.sceneViews.OfType<SceneView>().FirstOrDefault();
        if (sceneView == null)
            return new ErrorResult { error = "No Scene view is available." };

        GameObject target = null;
        string path = GetString(p, "path", GetString(p, "gameObjectPath", ""));
        if (!string.IsNullOrWhiteSpace(path))
            target = FindGameObject(path);
        else if (p != null && p.TryGetValue("instanceId", out object rawInstanceId) && rawInstanceId != null)
            target = FindGameObject(Convert.ToInt32(rawInstanceId));
        else if (Selection.activeGameObject != null)
            target = Selection.activeGameObject;

        bool appliedViewChange = false;
        if (p != null && p.TryGetValue("pivot", out object rawPivot))
        {
            sceneView.pivot = ParseVec3(rawPivot);
            appliedViewChange = true;
        }
        else if (p != null && p.TryGetValue("position", out object rawPosition))
        {
            sceneView.pivot = ParseVec3(rawPosition);
            appliedViewChange = true;
        }

        if (p != null && p.TryGetValue("rotation", out object rawRotation))
        {
            sceneView.rotation = Quaternion.Euler(ParseVec3(rawRotation));
            appliedViewChange = true;
        }

        if (p != null && p.TryGetValue("size", out object rawSize) && rawSize != null)
        {
            sceneView.size = Math.Max(0.01f, Convert.ToSingle(rawSize));
            appliedViewChange = true;
        }

        if (p != null && p.ContainsKey("orthographic"))
        {
            sceneView.orthographic = GetBool(p, "orthographic", sceneView.orthographic);
            appliedViewChange = true;
        }

        if (target != null)
        {
            Selection.activeGameObject = target;
            sceneView.Frame(new Bounds(target.transform.position, Vector3.one), false);
            appliedViewChange = true;
            path = GetPath(target);
        }

        if (!appliedViewChange)
            return new ErrorResult { error = "No Scene view target or camera parameters were provided." };

        sceneView.Repaint();

        return new Dictionary<string, object>
        {
            {"success", true},
            {"focused", target != null},
            {"path", path},
            {"instanceId", target != null ? target.GetInstanceID() : 0},
            {"pivot", Vec3Dict(sceneView.pivot)},
            {"rotation", Vec3Dict(sceneView.rotation.eulerAngles)},
            {"size", sceneView.size},
            {"orthographic", sceneView.orthographic}
        };
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
        // Accept multiple param name variants so plan-generated, Python and HTTP callers all work.
        string goPath = GetString(p, "gameObjectPath",
                        GetString(p, "path",
                        GetString(p, "gameObject",
                        GetString(p, "name", ""))));
        string componentType = GetString(p, "componentType",
                               GetString(p, "type",
                               GetString(p, "component", "")));
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

    private static object HandleAnimationCreateController(Dictionary<string, object> p)
    {
        string assetPath = GetString(p, "path", "Assets/Animations/Generated/Standalone_Auto.controller")
            .Replace("\\", "/")
            .Trim();

        if (string.IsNullOrEmpty(assetPath))
            return new ErrorResult { error = "path is required" };
        if (!assetPath.StartsWith("Assets/", StringComparison.OrdinalIgnoreCase))
            return new ErrorResult { error = "Animator Controller path must live under Assets/." };
        if (!assetPath.EndsWith(".controller", StringComparison.OrdinalIgnoreCase))
            return new ErrorResult { error = "Animator Controller path must end with .controller" };

        string folder = Path.GetDirectoryName(assetPath)?.Replace("\\", "/") ?? "Assets/Animations/Generated";
        EnsureAssetFolder(folder);

        var existing = AssetDatabase.LoadAssetAtPath<AnimatorController>(assetPath);
        if (existing != null)
        {
            Debug.Log("[FileIPC] animation/create-controller reused " + assetPath);
            return new Dictionary<string, object>
            {
                {"success", true},
                {"path", assetPath},
                {"created", false},
                {"alreadyExists", true}
            };
        }

        var controller = AnimatorController.CreateAnimatorControllerAtPath(assetPath);
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();
        Debug.Log("[FileIPC] animation/create-controller created " + assetPath);

        return new Dictionary<string, object>
        {
            {"success", controller != null},
            {"path", assetPath},
            {"created", controller != null},
            {"alreadyExists", false}
        };
    }

    private static object HandleAnimationCreateClip(Dictionary<string, object> p)
    {
        string assetPath = GetString(p, "path", "Assets/Animations/Generated/Standalone_Auto.anim")
            .Replace("\\", "/")
            .Trim();
        if (string.IsNullOrEmpty(assetPath))
            return new ErrorResult { error = "path is required" };
        if (!assetPath.StartsWith("Assets/", StringComparison.OrdinalIgnoreCase))
            return new ErrorResult { error = "Animation Clip path must live under Assets/." };
        if (!assetPath.EndsWith(".anim", StringComparison.OrdinalIgnoreCase))
            return new ErrorResult { error = "Animation Clip path must end with .anim" };

        string folder = Path.GetDirectoryName(assetPath)?.Replace("\\", "/") ?? "Assets/Animations/Generated";
        EnsureAssetFolder(folder);

        float frameRate = GetFloat(p, "frameRate", 60f);
        bool loop = GetBool(p, "loop", false);

        var existing = AssetDatabase.LoadAssetAtPath<AnimationClip>(assetPath);
        if (existing != null)
        {
            existing.frameRate = frameRate;
            SetAnimationClipLoop(existing, loop);
            EditorUtility.SetDirty(existing);
            AssetDatabase.SaveAssets();
            Debug.Log("[FileIPC] animation/create-clip reused " + assetPath);
            return new Dictionary<string, object>
            {
                {"success", true},
                {"path", assetPath},
                {"created", false},
                {"alreadyExists", true},
                {"frameRate", existing.frameRate},
                {"loop", GetAnimationClipLoop(existing)}
            };
        }

        var clip = new AnimationClip
        {
            frameRate = frameRate
        };
        SetAnimationClipLoop(clip, loop);
        AssetDatabase.CreateAsset(clip, assetPath);
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();
        Debug.Log("[FileIPC] animation/create-clip created " + assetPath);

        return new Dictionary<string, object>
        {
            {"success", true},
            {"path", assetPath},
            {"created", true},
            {"alreadyExists", false},
            {"frameRate", clip.frameRate},
            {"loop", GetAnimationClipLoop(clip)}
        };
    }

    private static object HandleAnimationAssignController(Dictionary<string, object> p)
    {
        string targetPath = GetString(p, "gameObjectPath", GetString(p, "path", "")).Trim();
        string controllerPath = GetString(p, "controllerPath", "").Replace("\\", "/").Trim();

        GameObject go = null;
        if (p != null && p.TryGetValue("instanceId", out object rawInstanceId) && rawInstanceId != null)
            go = FindGameObject(Convert.ToInt32(rawInstanceId));
        if (go == null && !string.IsNullOrEmpty(targetPath))
            go = FindGameObject(targetPath);

        if (go == null)
            return new ErrorResult { error = "GameObject not found for Animator assignment: " + targetPath };
        if (string.IsNullOrEmpty(controllerPath))
            return new ErrorResult { error = "controllerPath is required" };

        var controller = AssetDatabase.LoadAssetAtPath<RuntimeAnimatorController>(controllerPath);
        if (controller == null)
            return new ErrorResult { error = "Animator Controller not found: " + controllerPath };

        var animator = go.GetComponent<Animator>();
        bool addedAnimator = false;
        if (animator == null)
        {
            animator = Undo.AddComponent<Animator>(go);
            addedAnimator = true;
        }

        Undo.RecordObject(animator, "Assign Animator Controller");
        animator.runtimeAnimatorController = controller;
        EditorUtility.SetDirty(animator);
        Debug.Log("[FileIPC] animation/assign-controller " + controllerPath + " -> " + GetPath(go));

        return new Dictionary<string, object>
        {
            {"success", true},
            {"gameObjectPath", GetPath(go)},
            {"controllerPath", controllerPath},
            {"addedAnimator", addedAnimator}
        };
    }

    private static object HandleAnimationClipInfo(Dictionary<string, object> p)
    {
        string assetPath = GetString(p, "path", "").Replace("\\", "/").Trim();
        if (string.IsNullOrEmpty(assetPath))
            return new ErrorResult { error = "path is required" };

        var clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(assetPath);
        if (clip == null)
            return new ErrorResult { error = "Animation Clip not found: " + assetPath };

        var curveBindings = AnimationUtility.GetCurveBindings(clip);
        var objectCurveBindings = AnimationUtility.GetObjectReferenceCurveBindings(clip);
        var events = AnimationUtility.GetAnimationEvents(clip);

        return new Dictionary<string, object>
        {
            {"path", assetPath},
            {"name", clip.name},
            {"length", clip.length},
            {"frameRate", clip.frameRate},
            {"loop", GetAnimationClipLoop(clip)},
            {"eventCount", events != null ? events.Length : 0},
            {"curveCount", (curveBindings != null ? curveBindings.Length : 0) + (objectCurveBindings != null ? objectCurveBindings.Length : 0)}
        };
    }

    private static object HandleAnimationControllerInfo(Dictionary<string, object> p)
    {
        string assetPath = GetString(p, "path", "").Replace("\\", "/").Trim();
        if (string.IsNullOrEmpty(assetPath))
            return new ErrorResult { error = "path is required" };

        var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(assetPath);
        if (controller == null)
            return new ErrorResult { error = "Animator Controller not found: " + assetPath };

        int transitionCount = 0;
        int anyStateTransitionCount = 0;
        int entryTransitionCount = 0;
        int stateCount = 0;
        var layers = new List<Dictionary<string, object>>();
        foreach (var layer in controller.layers)
        {
            var stateMachine = layer.stateMachine;
            int layerStateCount = stateMachine != null ? stateMachine.states.Length : 0;
            int anyStateCount = stateMachine != null ? stateMachine.anyStateTransitions.Length : 0;
            int entryCount = stateMachine != null ? stateMachine.entryTransitions.Length : 0;
            int layerTransitions = anyStateCount + entryCount;
            var stateSummaries = new List<Dictionary<string, object>>();
            if (stateMachine != null)
            {
                foreach (var childState in stateMachine.states)
                {
                    var state = childState.state;
                    if (state == null)
                        continue;

                    var transitions = state.transitions.Select(transition => BuildAnimatorTransitionSummary(transition)).ToList();
                    layerTransitions += state.transitions.Length;
                    stateSummaries.Add(new Dictionary<string, object>
                    {
                        {"name", state.name},
                        {"clipPath", state.motion != null ? AssetDatabase.GetAssetPath(state.motion) : string.Empty},
                        {"speed", state.speed},
                        {"hasMotion", state.motion != null},
                        {"isDefault", stateMachine.defaultState == state},
                        {"transitionCount", state.transitions.Length},
                        {"transitions", transitions}
                    });
                }
            }
            transitionCount += layerTransitions;
            anyStateTransitionCount += anyStateCount;
            entryTransitionCount += entryCount;
            stateCount += layerStateCount;
            layers.Add(new Dictionary<string, object>
            {
                {"name", layer.name},
                {"index", layers.Count},
                {"stateCount", layerStateCount},
                {"transitionCount", layerTransitions},
                {"defaultState", stateMachine != null && stateMachine.defaultState != null ? stateMachine.defaultState.name : null},
                {"anyStateTransitionCount", anyStateCount},
                {"entryTransitionCount", entryCount},
                {"states", stateSummaries}
            });
        }

        return new Dictionary<string, object>
        {
            {"path", assetPath},
            {"name", controller.name},
            {"layerCount", controller.layers.Length},
            {"parameterCount", controller.parameters.Length},
            {"transitionCount", transitionCount},
            {"stateCount", stateCount},
            {"defaultState", layers.Count == 1 ? layers[0]["defaultState"] : null},
            {"anyStateTransitionCount", anyStateTransitionCount},
            {"entryTransitionCount", entryTransitionCount},
            {"parameters", controller.parameters.Select(parameter => new Dictionary<string, object>
            {
                {"name", parameter.name},
                {"type", parameter.type.ToString()},
                {"defaultFloat", parameter.defaultFloat},
                {"defaultInt", parameter.defaultInt},
                {"defaultBool", parameter.defaultBool}
            }).ToList()},
            {"layers", layers}
        };
    }

    private static object HandleAnimationSetDefaultState(Dictionary<string, object> p)
    {
        string controllerPath = GetString(p, "controllerPath", "").Replace("\\", "/").Trim();
        string stateName = GetString(p, "stateName", "").Trim();
        int layerIndex = GetInt(p, "layerIndex", 0);

        if (string.IsNullOrEmpty(controllerPath))
            return new ErrorResult { error = "controllerPath is required" };
        if (string.IsNullOrEmpty(stateName))
            return new ErrorResult { error = "stateName is required" };

        var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(controllerPath);
        if (controller == null)
            return new ErrorResult { error = "Animator Controller not found: " + controllerPath };
        if (layerIndex < 0 || layerIndex >= controller.layers.Length)
            return new ErrorResult { error = "layerIndex is out of range" };

        var stateMachine = controller.layers[layerIndex].stateMachine;
        if (stateMachine == null)
            return new ErrorResult { error = "Animator Controller layer has no state machine" };

        var state = FindAnimatorState(stateMachine, stateName);
        if (state == null)
            return new ErrorResult { error = "State not found: " + stateName };

        string previousDefaultState = stateMachine.defaultState != null ? stateMachine.defaultState.name : null;
        bool alreadyDefault = stateMachine.defaultState == state;
        stateMachine.defaultState = state;

        EditorUtility.SetDirty(controller);
        AssetDatabase.SaveAssets();
        Debug.Log("[FileIPC] animation/set-default-state " + stateName + " -> " + controllerPath);

        return new Dictionary<string, object>
        {
            {"success", true},
            {"controllerPath", controllerPath},
            {"layerIndex", layerIndex},
            {"defaultState", state.name},
            {"previousDefaultState", previousDefaultState},
            {"alreadyDefault", alreadyDefault}
        };
    }

    private static object HandleAnimationAddParameter(Dictionary<string, object> p)
    {
        string controllerPath = GetString(p, "controllerPath", "").Replace("\\", "/").Trim();
        string parameterName = GetString(p, "parameterName", "").Trim();
        string parameterType = GetString(p, "parameterType", "Float").Trim();
        if (string.IsNullOrEmpty(controllerPath))
            return new ErrorResult { error = "controllerPath is required" };
        if (string.IsNullOrEmpty(parameterName))
            return new ErrorResult { error = "parameterName is required" };

        var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(controllerPath);
        if (controller == null)
            return new ErrorResult { error = "Animator Controller not found: " + controllerPath };

        AnimatorControllerParameterType resolvedType;
        if (!Enum.TryParse(parameterType, true, out resolvedType))
            return new ErrorResult { error = "Unsupported parameterType: " + parameterType };

        var existing = controller.parameters.FirstOrDefault(parameter => parameter.name == parameterName);
        if (existing != null)
        {
            return new Dictionary<string, object>
            {
                {"success", true},
                {"controllerPath", controllerPath},
                {"alreadyExists", true},
                {"parameter", new Dictionary<string, object>
                    {
                        {"name", existing.name},
                        {"type", existing.type.ToString()},
                        {"defaultValue", ReadAnimatorParameterDefault(existing)}
                    }
                }
            };
        }

        controller.AddParameter(parameterName, resolvedType);
        var parameter = controller.parameters.FirstOrDefault(item => item.name == parameterName);
        if (parameter != null && p != null && p.TryGetValue("defaultValue", out object defaultValue) && defaultValue != null)
            ApplyAnimatorParameterDefault(controller, parameterName, parameter.type, defaultValue);
        AssetDatabase.SaveAssets();

        parameter = controller.parameters.FirstOrDefault(item => item.name == parameterName);
        return new Dictionary<string, object>
        {
            {"success", true},
            {"controllerPath", controllerPath},
            {"alreadyExists", false},
            {"parameter", new Dictionary<string, object>
                {
                    {"name", parameter != null ? parameter.name : parameterName},
                    {"type", parameter != null ? parameter.type.ToString() : resolvedType.ToString()},
                    {"defaultValue", parameter != null ? ReadAnimatorParameterDefault(parameter) : null}
                }
            }
        };
    }

    private static object HandleAnimationAddState(Dictionary<string, object> p)
    {
        string controllerPath = GetString(p, "controllerPath", "").Replace("\\", "/").Trim();
        string stateName = GetString(p, "stateName", "").Trim();
        int layerIndex = GetInt(p, "layerIndex", 0);
        string clipPath = GetString(p, "clipPath", "").Replace("\\", "/").Trim();
        float speed = GetFloat(p, "speed", 1f);
        bool isDefault = GetBool(p, "isDefault", false);

        if (string.IsNullOrEmpty(controllerPath))
            return new ErrorResult { error = "controllerPath is required" };
        if (string.IsNullOrEmpty(stateName))
            return new ErrorResult { error = "stateName is required" };

        var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(controllerPath);
        if (controller == null)
            return new ErrorResult { error = "Animator Controller not found: " + controllerPath };
        if (layerIndex < 0 || layerIndex >= controller.layers.Length)
            return new ErrorResult { error = "layerIndex is out of range" };

        var stateMachine = controller.layers[layerIndex].stateMachine;
        if (stateMachine == null)
            return new ErrorResult { error = "Animator Controller layer has no state machine" };

        var existing = stateMachine.states.FirstOrDefault(child => child.state != null && child.state.name == stateName).state;
        if (existing != null)
        {
            return new Dictionary<string, object>
            {
                {"success", true},
                {"controllerPath", controllerPath},
                {"alreadyExists", true},
                {"state", new Dictionary<string, object>
                    {
                        {"name", existing.name},
                        {"speed", existing.speed},
                        {"clipPath", AssetDatabase.GetAssetPath(existing.motion)},
                        {"isDefault", stateMachine.defaultState == existing}
                    }
                }
            };
        }

        var state = stateMachine.AddState(stateName);
        state.speed = speed;
        if (!string.IsNullOrEmpty(clipPath))
        {
            var clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(clipPath);
            if (clip == null)
                return new ErrorResult { error = "Animation Clip not found: " + clipPath };
            state.motion = clip;
        }
        if (isDefault)
            stateMachine.defaultState = state;

        EditorUtility.SetDirty(controller);
        AssetDatabase.SaveAssets();
        Debug.Log("[FileIPC] animation/add-state " + stateName + " -> " + controllerPath);

        return new Dictionary<string, object>
        {
            {"success", true},
            {"controllerPath", controllerPath},
            {"alreadyExists", false},
            {"state", new Dictionary<string, object>
                {
                    {"name", state.name},
                    {"speed", state.speed},
                    {"clipPath", AssetDatabase.GetAssetPath(state.motion)},
                    {"isDefault", stateMachine.defaultState == state}
                }
            }
        };
    }

    private static object HandleAnimationAddTransition(Dictionary<string, object> p)
    {
        string controllerPath = GetString(p, "controllerPath", "").Replace("\\", "/").Trim();
        string sourceStateName = GetString(p, "sourceState", "").Trim();
        string destinationStateName = GetString(p, "destinationState", "").Trim();
        int layerIndex = GetInt(p, "layerIndex", 0);
        bool fromAnyState = GetBool(p, "fromAnyState", false);
        bool allowSelfTransition = GetBool(p, "allowSelfTransition", false);
        bool hasExitTime = GetBool(p, "hasExitTime", false);
        float exitTime = GetFloat(p, "exitTime", 0f);
        float duration = GetFloat(p, "duration", 0.1f);
        float offset = GetFloat(p, "offset", 0f);
        bool hasFixedDuration = GetBool(p, "hasFixedDuration", true);

        if (string.IsNullOrEmpty(controllerPath))
            return new ErrorResult { error = "controllerPath is required" };
        if (string.IsNullOrEmpty(destinationStateName))
            return new ErrorResult { error = "destinationState is required" };

        var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(controllerPath);
        if (controller == null)
            return new ErrorResult { error = "Animator Controller not found: " + controllerPath };
        if (layerIndex < 0 || layerIndex >= controller.layers.Length)
            return new ErrorResult { error = "layerIndex is out of range" };

        var stateMachine = controller.layers[layerIndex].stateMachine;
        if (stateMachine == null)
            return new ErrorResult { error = "Animator Controller layer has no state machine" };

        var destinationState = stateMachine.states.FirstOrDefault(child => child.state != null && child.state.name == destinationStateName).state;
        if (destinationState == null)
            return new ErrorResult { error = "Destination state not found: " + destinationStateName };

        AnimatorStateTransition transition;
        if (fromAnyState)
        {
            transition = stateMachine.AddAnyStateTransition(destinationState);
        }
        else
        {
            if (string.IsNullOrEmpty(sourceStateName))
                return new ErrorResult { error = "sourceState is required unless fromAnyState is true" };

            var sourceState = stateMachine.states.FirstOrDefault(child => child.state != null && child.state.name == sourceStateName).state;
            if (sourceState == null)
                return new ErrorResult { error = "Source state not found: " + sourceStateName };
            if (!allowSelfTransition && sourceState == destinationState)
                return new ErrorResult { error = "Self-transition is not allowed unless allowSelfTransition is true" };
            transition = sourceState.AddTransition(destinationState);
        }

        transition.hasExitTime = hasExitTime;
        transition.exitTime = exitTime;
        transition.duration = duration;
        transition.offset = offset;
        transition.hasFixedDuration = hasFixedDuration;

        if (p != null && p.TryGetValue("conditions", out object rawConditions) && rawConditions is IEnumerable<object> conditions)
        {
            foreach (object rawCondition in conditions)
            {
                if (!(rawCondition is Dictionary<string, object> condition))
                    continue;
                string parameter = GetString(condition, "parameter", "").Trim();
                string mode = GetString(condition, "mode", "").Trim();
                float threshold = GetFloat(condition, "threshold", 0f);
                AnimatorConditionMode resolvedMode;
                if (string.IsNullOrEmpty(parameter) || !TryParseAnimatorConditionMode(mode, out resolvedMode))
                    continue;
                transition.AddCondition(resolvedMode, threshold, parameter);
            }
        }

        EditorUtility.SetDirty(controller);
        AssetDatabase.SaveAssets();
        Debug.Log("[FileIPC] animation/add-transition " + destinationStateName + " -> " + controllerPath);

        return new Dictionary<string, object>
        {
            {"success", true},
            {"controllerPath", controllerPath},
            {"transition", new Dictionary<string, object>
                {
                    {"sourceState", fromAnyState ? null : sourceStateName},
                    {"destinationState", destinationStateName},
                    {"fromAnyState", fromAnyState},
                    {"duration", transition.duration},
                    {"conditions", transition.conditions.Select(condition => new Dictionary<string, object>
                        {
                            {"parameter", condition.parameter},
                            {"mode", condition.mode.ToString()},
                            {"threshold", condition.threshold}
                        }).ToList()
                    }
                }
            }
        };
    }

    private static object HandleAnimationRemoveTransition(Dictionary<string, object> p)
    {
        string controllerPath = GetString(p, "controllerPath", "").Replace("\\", "/").Trim();
        string sourceStateName = GetString(p, "sourceState", GetString(p, "fromState", "")).Trim();
        string destinationStateName = GetString(p, "destinationState", GetString(p, "toState", "")).Trim();
        int layerIndex = GetInt(p, "layerIndex", 0);
        bool fromAnyState = GetBool(p, "fromAnyState", false);

        if (string.IsNullOrEmpty(controllerPath))
            return new ErrorResult { error = "controllerPath is required" };

        var controller = AssetDatabase.LoadAssetAtPath<AnimatorController>(controllerPath);
        if (controller == null)
            return new ErrorResult { error = "Animator Controller not found: " + controllerPath };
        if (layerIndex < 0 || layerIndex >= controller.layers.Length)
            return new ErrorResult { error = "layerIndex is out of range" };

        var stateMachine = controller.layers[layerIndex].stateMachine;
        if (stateMachine == null)
            return new ErrorResult { error = "Animator Controller layer has no state machine" };

        int removedCount = 0;
        bool MatchesDestination(AnimatorState state)
        {
            return string.IsNullOrEmpty(destinationStateName) || (state != null && state.name == destinationStateName);
        }

        bool MatchesSource(AnimatorState state)
        {
            return string.IsNullOrEmpty(sourceStateName) || (state != null && state.name == sourceStateName);
        }

        if (fromAnyState || string.IsNullOrEmpty(sourceStateName))
        {
            foreach (var transition in stateMachine.anyStateTransitions.ToArray())
            {
                if (!MatchesDestination(transition.destinationState))
                    continue;
                stateMachine.RemoveAnyStateTransition(transition);
                removedCount += 1;
            }
        }

        foreach (var childState in stateMachine.states)
        {
            var sourceState = childState.state;
            if (sourceState == null || !MatchesSource(sourceState))
                continue;

            foreach (var transition in sourceState.transitions.ToArray())
            {
                if (!MatchesDestination(transition.destinationState))
                    continue;
                sourceState.RemoveTransition(transition);
                removedCount += 1;
            }
        }

        EditorUtility.SetDirty(controller);
        AssetDatabase.SaveAssets();

        return new Dictionary<string, object>
        {
            {"success", true},
            {"controllerPath", controllerPath},
            {"transitionRemoved", removedCount > 0},
            {"removedCount", removedCount}
        };
    }

    private static AnimatorState FindAnimatorState(AnimatorStateMachine stateMachine, string stateName)
    {
        if (stateMachine == null || string.IsNullOrEmpty(stateName))
            return null;

        return stateMachine.states.FirstOrDefault(child => child.state != null && child.state.name == stateName).state;
    }

    private static Dictionary<string, object> BuildAnimatorTransitionSummary(AnimatorStateTransition transition)
    {
        return new Dictionary<string, object>
        {
            {"destinationState", transition != null && transition.destinationState != null ? transition.destinationState.name : null},
            {"duration", transition != null ? transition.duration : 0f},
            {"conditions", transition != null
                ? transition.conditions.Select(condition => new Dictionary<string, object>
                    {
                        {"parameter", condition.parameter},
                        {"mode", condition.mode.ToString()},
                        {"threshold", condition.threshold}
                    }).ToList()
                : new List<Dictionary<string, object>>()
            }
        };
    }

    // Debounce AssetDatabase.Refresh so rapid script writes during verify-and-fix
    // loops don't stack multiple domain reloads (which was contributing to
    // runaway editor memory during agent flows).
    private static DateTime _lastAssetRefreshUtc = DateTime.MinValue;
    private const double _minRefreshSpacingSeconds = 1.5;

    private static void RequestAssetRefresh()
    {
        // Skip the refresh entirely if Unity is already compiling or updating —
        // it will pick up the new file on the current pass.
        if (EditorApplication.isCompiling || EditorApplication.isUpdating)
            return;

        double since = (DateTime.UtcNow - _lastAssetRefreshUtc).TotalSeconds;
        if (since < _minRefreshSpacingSeconds)
            return;

        _lastAssetRefreshUtc = DateTime.UtcNow;
        AssetDatabase.Refresh();
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

        // Skip identical-content rewrites entirely — otherwise a verify loop
        // that reads back the same bytes would still trigger a Refresh pass.
        bool existingMatches = false;
        try
        {
            if (File.Exists(fullPath))
            {
                string existing = File.ReadAllText(fullPath);
                existingMatches = string.Equals(existing, content, StringComparison.Ordinal);
            }
        }
        catch { /* fall through and just write */ }

        if (!existingMatches)
        {
            File.WriteAllText(fullPath, content);
            RequestAssetRefresh();
        }

        return new Dictionary<string, object>
        {
            {"success", true},
            {"path", assetPath},
            {"unchanged", existingMatches}
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

    private static void EnsureAssetFolder(string folder)
    {
        folder = (folder ?? "Assets").Replace("\\", "/").Trim().TrimEnd('/');
        if (string.IsNullOrEmpty(folder) || string.Equals(folder, "Assets", StringComparison.OrdinalIgnoreCase))
            return;
        if (AssetDatabase.IsValidFolder(folder))
            return;

        string[] segments = folder.Split(new[] { '/' }, StringSplitOptions.RemoveEmptyEntries);
        string current = segments.Length > 0 ? segments[0] : "Assets";
        for (int i = 1; i < segments.Length; i++)
        {
            string next = current + "/" + segments[i];
            if (!AssetDatabase.IsValidFolder(next))
                AssetDatabase.CreateFolder(current, segments[i]);
            current = next;
        }
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

    private static Dictionary<string, object> BuildGameObjectResult(GameObject go)
    {
        return new Dictionary<string, object>
        {
            {"name", go.name},
            {"path", GetPath(go)},
            {"instanceId", go.GetInstanceID()},
            {"active", go.activeSelf},
            {"activeInHierarchy", go.activeInHierarchy},
            {"tag", go.tag},
            {"layer", go.layer},
            {"layerName", LayerMask.LayerToName(go.layer)},
            {"isStatic", go.isStatic},
            {"components", go.GetComponents<Component>().Where(c => c != null).Select(c => c.GetType().Name).ToArray()},
        };
    }

    private static Dictionary<string, object> BuildSelectionPayload(GameObject[] selected, bool success = true)
    {
        GameObject active = selected.FirstOrDefault();
        return new Dictionary<string, object>
        {
            {"success", success},
            {"count", selected.Length},
            {"paths", selected.Select(GetPath).ToArray()},
            {"activePath", active != null ? GetPath(active) : null},
            {"activeInstanceId", active != null ? active.GetInstanceID() : 0},
            {"results", selected.Select(BuildGameObjectResult).ToArray()}
        };
    }

    private static GameObject FindGameObject(int instanceId)
    {
        UnityEngine.Object obj = EditorUtility.InstanceIDToObject(instanceId);
        if (obj is GameObject go)
            return go;
        if (obj is Component component)
            return component.gameObject;

        foreach (GameObject candidate in Resources.FindObjectsOfTypeAll<GameObject>())
        {
            if (candidate != null && candidate.GetInstanceID() == instanceId && candidate.scene.IsValid())
                return candidate;
        }

        return null;
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

    private static string SanitizeAssetName(string value, string fallback)
    {
        string cleaned = new string((value ?? "")
            .Where(ch => char.IsLetterOrDigit(ch) || ch == '_' || ch == '-' || ch == ' ')
            .ToArray()).Trim();
        if (string.IsNullOrWhiteSpace(cleaned))
            cleaned = fallback;
        return cleaned;
    }

    private static float GetFloat(Dictionary<string, object> p, string key, float defaultValue)
    {
        if (p != null && p.TryGetValue(key, out object val))
        {
            if (val is double d) return (float)d;
            if (val is float f) return f;
            if (val is long l) return l;
            if (val is int i) return i;
            if (float.TryParse(val?.ToString(), out float parsed)) return parsed;
        }
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

    private static void SetAnimationClipLoop(AnimationClip clip, bool loop)
    {
        if (clip == null)
            return;

        try
        {
            var serializedObject = new SerializedObject(clip);
            var settings = serializedObject.FindProperty("m_AnimationClipSettings");
            var loopProp = settings != null ? settings.FindPropertyRelative("m_LoopTime") : null;
            if (loopProp != null)
            {
                loopProp.boolValue = loop;
                serializedObject.ApplyModifiedPropertiesWithoutUndo();
            }
        }
        catch
        {
        }
    }

    private static bool GetAnimationClipLoop(AnimationClip clip)
    {
        if (clip == null)
            return false;

        try
        {
            var serializedObject = new SerializedObject(clip);
            var settings = serializedObject.FindProperty("m_AnimationClipSettings");
            var loopProp = settings != null ? settings.FindPropertyRelative("m_LoopTime") : null;
            if (loopProp != null)
                return loopProp.boolValue;
        }
        catch
        {
        }

        return false;
    }

    private static object ReadAnimatorParameterDefault(AnimatorControllerParameter parameter)
    {
        switch (parameter.type)
        {
            case AnimatorControllerParameterType.Float:
                return parameter.defaultFloat;
            case AnimatorControllerParameterType.Int:
                return parameter.defaultInt;
            case AnimatorControllerParameterType.Bool:
            case AnimatorControllerParameterType.Trigger:
                return parameter.defaultBool;
            default:
                return null;
        }
    }

    private static void ApplyAnimatorParameterDefault(
        AnimatorController controller,
        string parameterName,
        AnimatorControllerParameterType parameterType,
        object defaultValue)
    {
        if (controller == null || string.IsNullOrEmpty(parameterName))
            return;

        try
        {
            var parameters = controller.parameters;
            for (int index = 0; index < parameters.Length; index++)
            {
                if (parameters[index].name != parameterName)
                    continue;

                switch (parameterType)
                {
                    case AnimatorControllerParameterType.Float:
                        parameters[index].defaultFloat = Convert.ToSingle(defaultValue);
                        break;
                    case AnimatorControllerParameterType.Int:
                        parameters[index].defaultInt = Convert.ToInt32(defaultValue);
                        break;
                    case AnimatorControllerParameterType.Bool:
                    case AnimatorControllerParameterType.Trigger:
                        parameters[index].defaultBool = Convert.ToBoolean(defaultValue);
                        break;
                }
                controller.parameters = parameters;
                return;
            }
        }
        catch
        {
        }
    }

    private static bool TryParseAnimatorConditionMode(string value, out AnimatorConditionMode mode)
    {
        switch ((value ?? string.Empty).Trim().ToLowerInvariant())
        {
            case "if":
                mode = AnimatorConditionMode.If;
                return true;
            case "ifnot":
                mode = AnimatorConditionMode.IfNot;
                return true;
            case "greater":
                mode = AnimatorConditionMode.Greater;
                return true;
            case "less":
                mode = AnimatorConditionMode.Less;
                return true;
            case "equals":
                mode = AnimatorConditionMode.Equals;
                return true;
            case "notequal":
                mode = AnimatorConditionMode.NotEqual;
                return true;
            default:
                mode = default;
                return false;
        }
    }

    private static Dictionary<string, object> Vec3Dict(Vector3 v)
    {
        return new Dictionary<string, object> { {"x", v.x}, {"y", v.y}, {"z", v.z} };
    }

    private static Dictionary<string, object> Vec3(Vector3 v)
    {
        return new Dictionary<string, object> { {"x", v.x}, {"y", v.y}, {"z", v.z} };
    }

    private static Dictionary<string, object> Vec4(Vector4 v)
    {
        return new Dictionary<string, object> { {"x", v.x}, {"y", v.y}, {"z", v.z}, {"w", v.w} };
    }

    private static Dictionary<string, object> ColorPayload(Color c)
    {
        return new Dictionary<string, object> { {"r", c.r}, {"g", c.g}, {"b", c.b}, {"a", c.a} };
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

    // Cache resolved component types so attach-retry loops don't re-scan every
    // loaded assembly on each attempt (which allocates hundreds of Type[] arrays
    // per call and contributed to editor memory pressure during long sessions).
    // Domain reloads wipe this dictionary automatically via static reinit.
    private static readonly Dictionary<string, Type> _componentTypeCache = new Dictionary<string, Type>(StringComparer.Ordinal);
    private static int _componentTypeCacheMisses;

    private static Type FindComponentType(string name)
    {
        if (string.IsNullOrEmpty(name)) return null;
        if (_componentTypeCache.TryGetValue(name, out Type cached))
            return cached;  // may be null — intentional negative cache

        Type resolved = ResolveComponentType(name);
        // Only negative-cache names we've looked up more than a few times to
        // give newly-compiled user scripts a chance to show up after a reload.
        if (resolved != null)
        {
            _componentTypeCache[name] = resolved;
        }
        else
        {
            _componentTypeCacheMisses++;
            // Flush negative cache periodically so newly compiled types become visible.
            if (_componentTypeCacheMisses >= 32)
            {
                _componentTypeCache.Clear();
                _componentTypeCacheMisses = 0;
            }
        }
        return resolved;
    }

    private static Type ResolveComponentType(string name)
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
            Type[] types;
            try
            {
                types = asm.GetTypes();
            }
            catch (ReflectionTypeLoadException ex)
            {
                types = ex.Types.Where(t => t != null).ToArray();
            }
            catch
            {
                continue;
            }

            foreach (var type in types)
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

    public static object DeserializeAny(string json)
    {
        if (string.IsNullOrEmpty(json)) return null;
        int index = 0;
        return ParseValue(json, ref index);
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

    // ══════════════════════════════════════════════════════════════════════
    // Phase 2 — New Route Handlers
    // ══════════════════════════════════════════════════════════════════════

    // ── Script routes ────────────────────────────────────────────────────

    private static object HandleScriptUpdate(Dictionary<string, object> p)
    {
        string assetPath = GetString(p, "path", "");
        string content   = GetString(p, "content", "");
        if (string.IsNullOrEmpty(assetPath))
            return new ErrorResult { error = "`path` is required (e.g. Assets/Scripts/Player.cs)" };
        if (!assetPath.StartsWith("Assets/", StringComparison.OrdinalIgnoreCase))
            return new ErrorResult { error = "`path` must start with Assets/" };

        string fullPath = Path.GetFullPath(Path.Combine(Application.dataPath, "..", assetPath));
        Directory.CreateDirectory(Path.GetDirectoryName(fullPath));
        File.WriteAllText(fullPath, content, Encoding.UTF8);
        AssetDatabase.ImportAsset(assetPath, ImportAssetOptions.ForceUpdate);
        return new Dictionary<string, object> { {"success", true}, {"path", assetPath} };
    }

    private static object HandleScriptList(Dictionary<string, object> p)
    {
        string folder = GetString(p, "folder", "Assets");
        bool includeEditor = GetBool(p, "includeEditor", false);
        var guids = AssetDatabase.FindAssets("t:MonoScript", new[] { folder });
        var scripts = guids
            .Select(g => AssetDatabase.GUIDToAssetPath(g))
            .Where(path => path.EndsWith(".cs", StringComparison.OrdinalIgnoreCase)
                        && (includeEditor || !path.Contains("/Editor/")))
            .OrderBy(path => path)
            .Select(path => (object)new Dictionary<string, object>
            {
                {"name", Path.GetFileNameWithoutExtension(path)},
                {"path", path}
            })
            .ToList();
        return new Dictionary<string, object> { {"count", scripts.Count}, {"scripts", scripts} };
    }

    private static object HandleScriptDelete(Dictionary<string, object> p)
    {
        string assetPath = GetString(p, "path", "");
        if (string.IsNullOrEmpty(assetPath))
            return new ErrorResult { error = "`path` is required" };
        if (!AssetDatabase.DeleteAsset(assetPath))
            return new ErrorResult { error = "Failed to delete " + assetPath };
        return new Dictionary<string, object> { {"success", true}, {"path", assetPath} };
    }

    // ── Component routes ─────────────────────────────────────────────────

    private static object HandleComponentSetProperty(Dictionary<string, object> p)
    {
        string goPath    = GetString(p, "gameObject", "");
        string compType  = GetString(p, "component", "");
        string fieldName = GetString(p, "property", "");
        object value     = p.ContainsKey("value") ? p["value"] : null;

        var go = FindGameObject(goPath);
        if (go == null) return new ErrorResult { error = "GameObject not found: " + goPath };

        Component comp = go.GetComponents<Component>()
            .FirstOrDefault(c => c != null &&
                (c.GetType().Name == compType || c.GetType().FullName == compType));
        if (comp == null) return new ErrorResult { error = "Component not found: " + compType };

        var type  = comp.GetType();
        var field = type.GetField(fieldName,
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        if (field != null)
        {
            try { field.SetValue(comp, ConvertValue(value, field.FieldType)); }
            catch (Exception ex) { return new ErrorResult { error = "Failed to set field: " + ex.Message }; }
            EditorUtility.SetDirty(comp);
            return new Dictionary<string, object> { {"success", true}, {"property", fieldName} };
        }
        var prop = type.GetProperty(fieldName,
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        if (prop != null && prop.CanWrite)
        {
            try { prop.SetValue(comp, ConvertValue(value, prop.PropertyType)); }
            catch (Exception ex) { return new ErrorResult { error = "Failed to set property: " + ex.Message }; }
            EditorUtility.SetDirty(comp);
            return new Dictionary<string, object> { {"success", true}, {"property", fieldName} };
        }
        return new ErrorResult { error = $"Field/property '{fieldName}' not found on {compType}" };
    }

    private static object HandleComponentRemove(Dictionary<string, object> p)
    {
        string goPath   = GetString(p, "gameObject", "");
        string compType = GetString(p, "component", "");
        var go = FindGameObject(goPath);
        if (go == null) return new ErrorResult { error = "GameObject not found: " + goPath };
        var comp = go.GetComponents<Component>()
            .FirstOrDefault(c => c != null &&
                (c.GetType().Name == compType || c.GetType().FullName == compType));
        if (comp == null) return new ErrorResult { error = "Component not found: " + compType };
        Undo.DestroyObjectImmediate(comp);
        return new Dictionary<string, object> { {"success", true}, {"removed", compType} };
    }

    private static object HandleComponentList(Dictionary<string, object> p)
    {
        string goPath = GetString(p, "gameObject", "");
        var go = FindGameObject(goPath);
        if (go == null) return new ErrorResult { error = "GameObject not found: " + goPath };
        var comps = go.GetComponents<Component>()
            .Where(c => c != null)
            .Select(c =>
            {
                var fields = c.GetType()
                    .GetFields(BindingFlags.Instance | BindingFlags.Public)
                    .Take(20)
                    .Select(f => new Dictionary<string, object>
                    {
                        {"name", f.Name},
                        {"type", f.FieldType.Name},
                        {"value", SafeFieldValue(f.GetValue(c))}
                    })
                    .ToList<object>();
                return (object)new Dictionary<string, object>
                {
                    {"type", c.GetType().Name},
                    {"fields", fields}
                };
            })
            .ToList();
        return new Dictionary<string, object> { {"gameObject", go.name}, {"components", comps} };
    }

    private static object HandleComponentWireReference(Dictionary<string, object> p)
    {
        string goPath    = GetString(p, "gameObject", "");
        string compType  = GetString(p, "component", "");
        string fieldName = GetString(p, "field", "");
        string targetPath = GetString(p, "target", "");   // GO path or asset path

        var go = FindGameObject(goPath);
        if (go == null) return new ErrorResult { error = "GameObject not found: " + goPath };
        var comp = go.GetComponents<Component>()
            .FirstOrDefault(c => c != null &&
                (c.GetType().Name == compType || c.GetType().FullName == compType));
        if (comp == null) return new ErrorResult { error = "Component not found: " + compType };

        var field = comp.GetType().GetField(fieldName,
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        if (field == null) return new ErrorResult { error = "Field not found: " + fieldName };

        // Try scene object first, then asset
        UnityEngine.Object targetObj = FindGameObject(targetPath) as UnityEngine.Object
            ?? AssetDatabase.LoadAssetAtPath(targetPath, field.FieldType);
        if (targetObj == null)
            return new ErrorResult { error = "Target not found: " + targetPath };

        field.SetValue(comp, targetObj);
        EditorUtility.SetDirty(comp);
        return new Dictionary<string, object> { {"success", true}, {"field", fieldName} };
    }

    // ── GameObject extended routes ───────────────────────────────────────

    private static object HandleGameObjectDuplicate(Dictionary<string, object> p)
    {
        string goPath = GetString(p, "gameObject", "");
        string newName = GetString(p, "name", "");
        var go = FindGameObject(goPath);
        if (go == null) return new ErrorResult { error = "GameObject not found: " + goPath };
        var duplicate = UnityEngine.Object.Instantiate(go, go.transform.parent);
        duplicate.name = string.IsNullOrEmpty(newName) ? go.name + "_Copy" : newName;
        Undo.RegisterCreatedObjectUndo(duplicate, "Duplicate " + go.name);
        return new Dictionary<string, object>
        {
            {"success", true},
            {"name", duplicate.name},
            {"instanceId", duplicate.GetInstanceID()},
            {"path", GetPath(duplicate)}
        };
    }

    private static object HandleGameObjectReparent(Dictionary<string, object> p)
    {
        string goPath     = GetString(p, "gameObject", "");
        string parentPath = GetString(p, "parent", "");   // empty = make root
        var go = FindGameObject(goPath);
        if (go == null) return new ErrorResult { error = "GameObject not found: " + goPath };

        Transform newParent = null;
        if (!string.IsNullOrEmpty(parentPath))
        {
            var parentGo = FindGameObject(parentPath);
            if (parentGo == null) return new ErrorResult { error = "Parent not found: " + parentPath };
            newParent = parentGo.transform;
        }
        Undo.SetTransformParent(go.transform, newParent, "Reparent " + go.name);
        return new Dictionary<string, object>
        {
            {"success", true},
            {"gameObject", go.name},
            {"newParent", newParent != null ? newParent.name : "(root)"}
        };
    }

    private static object HandleGameObjectFind(Dictionary<string, object> p)
    {
        string name = GetString(p, "name", "");
        string path = GetString(p, "path", "");
        string query = !string.IsNullOrEmpty(path) ? path : name;
        if (string.IsNullOrEmpty(query))
            return new ErrorResult { error = "Provide `name` or `path`" };
        var go = FindGameObject(query);
        if (go == null) return new ErrorResult { error = "Not found: " + query };
        return HandleGameObjectInfo(new Dictionary<string, object> { {"name", GetPath(go)} });
    }

    private static object HandleGameObjectRename(Dictionary<string, object> p)
    {
        string goPath = GetString(p, "gameObject", "");
        string newName = GetString(p, "name", "");
        if (string.IsNullOrEmpty(newName)) return new ErrorResult { error = "`name` is required" };
        var go = FindGameObject(goPath);
        if (go == null) return new ErrorResult { error = "GameObject not found: " + goPath };
        Undo.RecordObject(go, "Rename " + go.name);
        go.name = newName;
        EditorUtility.SetDirty(go);
        return new Dictionary<string, object> { {"success", true}, {"name", newName} };
    }

    private static object HandleGameObjectSetTag(Dictionary<string, object> p)
    {
        string goPath = GetString(p, "gameObject", "");
        string tag    = GetString(p, "tag", "Untagged");
        var go = FindGameObject(goPath);
        if (go == null) return new ErrorResult { error = "GameObject not found: " + goPath };
        Undo.RecordObject(go, "Set Tag");
        go.tag = tag;
        EditorUtility.SetDirty(go);
        return new Dictionary<string, object> { {"success", true}, {"tag", tag} };
    }

    private static object HandleGameObjectSetLayer(Dictionary<string, object> p)
    {
        string goPath = GetString(p, "gameObject", "");
        var go = FindGameObject(goPath);
        if (go == null) return new ErrorResult { error = "GameObject not found: " + goPath };
        Undo.RecordObject(go, "Set Layer");
        if (p.ContainsKey("layerName"))
        {
            int idx = LayerMask.NameToLayer(GetString(p, "layerName", "Default"));
            if (idx < 0) return new ErrorResult { error = "Layer not found: " + GetString(p, "layerName", "") };
            go.layer = idx;
        }
        else
        {
            go.layer = GetInt(p, "layer", 0);
        }
        EditorUtility.SetDirty(go);
        return new Dictionary<string, object> { {"success", true}, {"layer", go.layer} };
    }

    // ── Material routes ──────────────────────────────────────────────────

    private static object HandleMaterialCreate(Dictionary<string, object> p)
    {
        string requestedPath = GetString(p, "path", "").Replace("\\", "/").Trim();
        string name   = GetString(p, "name", "NewMaterial");
        string folder = GetString(p, "folder", "Assets/Materials");
        string shader = GetString(p, "shader", "Universal Render Pipeline/Lit");
        string assetPath = requestedPath;

        if (string.IsNullOrEmpty(assetPath))
        {
            assetPath = folder.TrimEnd('/') + "/" + name + ".mat";
        }
        else
        {
            assetPath = assetPath.Replace("\\", "/");
            name = Path.GetFileNameWithoutExtension(assetPath);
            string requestedFolder = Path.GetDirectoryName(assetPath);
            folder = string.IsNullOrEmpty(requestedFolder) ? "Assets" : requestedFolder.Replace("\\", "/");
        }

        EnsureAssetFolder(folder);
        var foundShader = Shader.Find(shader) ?? Shader.Find("Standard");
        if (foundShader == null) return new ErrorResult { error = "Shader not found: " + shader };
        var mat = new Material(foundShader) { name = name };
        AssetDatabase.CreateAsset(mat, assetPath);
        AssetDatabase.SaveAssets();
        return new Dictionary<string, object>
        {
            {"success", true},
            {"path", assetPath},
            {"name", name},
            {"shader", mat.shader != null ? mat.shader.name : shader}
        };
    }

    private static object HandleMaterialSetProperty(Dictionary<string, object> p)
    {
        string assetPath = GetString(p, "path", "");
        string propName  = GetString(p, "property", "");
        var mat = AssetDatabase.LoadAssetAtPath<Material>(assetPath);
        if (mat == null) return new ErrorResult { error = "Material not found: " + assetPath };

        if (p.ContainsKey("color"))
        {
            var c = p["color"] as Dictionary<string, object>;
            if (c != null)
            {
                float r = (float)Convert.ToDouble(c.ContainsKey("r") ? c["r"] : 1.0);
                float g = (float)Convert.ToDouble(c.ContainsKey("g") ? c["g"] : 1.0);
                float b = (float)Convert.ToDouble(c.ContainsKey("b") ? c["b"] : 1.0);
                float a = (float)Convert.ToDouble(c.ContainsKey("a") ? c["a"] : 1.0);
                mat.SetColor(propName, new Color(r, g, b, a));
            }
        }
        else if (p.ContainsKey("texture"))
        {
            string texPath = GetString(p, "texture", "");
            var tex = AssetDatabase.LoadAssetAtPath<Texture>(texPath);
            if (tex == null) return new ErrorResult { error = "Texture not found: " + texPath };
            mat.SetTexture(propName, tex);
        }
        else if (p.ContainsKey("value"))
        {
            mat.SetFloat(propName, GetFloat(p, "value", 0f));
        }
        else
        {
            return new ErrorResult { error = "Provide `color`, `texture`, or `value`" };
        }
        EditorUtility.SetDirty(mat);
        AssetDatabase.SaveAssets();
        return new Dictionary<string, object> { {"success", true}, {"property", propName} };
    }

    private static object HandleMaterialGetProperties(Dictionary<string, object> p)
    {
        string assetPath = GetString(p, "path", "");
        var mat = AssetDatabase.LoadAssetAtPath<Material>(assetPath);
        if (mat == null) return new ErrorResult { error = "Material not found: " + assetPath };
        var props = new List<object>();
        if (mat.shader != null)
        {
            int count = UnityEditor.ShaderUtil.GetPropertyCount(mat.shader);
            for (int i = 0; i < count; i++)
            {
                var propType = UnityEditor.ShaderUtil.GetPropertyType(mat.shader, i);
                props.Add(new Dictionary<string, object>
                {
                    {"name", UnityEditor.ShaderUtil.GetPropertyName(mat.shader, i)},
                    {"type", propType.ToString()},
                    {"description", UnityEditor.ShaderUtil.GetPropertyDescription(mat.shader, i)}
                });
            }
        }
        return new Dictionary<string, object>
        {
            {"path", assetPath},
            {"shader", mat.shader?.name ?? "none"},
            {"properties", props}
        };
    }

    private static object HandleMaterialAssign(Dictionary<string, object> p)
    {
        string goPath    = GetString(p, "gameObject", GetString(p, "gameObjectPath", GetString(p, "objectPath", GetString(p, "path", ""))));
        string matPath   = GetString(p, "material", GetString(p, "materialPath", ""));
        int    slotIndex = GetInt(p, "slot", GetInt(p, "materialIndex", 0));
        var go = FindGameObject(goPath);
        if (go == null) return new ErrorResult { error = "GameObject not found: " + goPath };
        var renderer = go.GetComponent<Renderer>();
        if (renderer == null) return new ErrorResult { error = "No Renderer on " + goPath };
        var mat = AssetDatabase.LoadAssetAtPath<Material>(matPath);
        if (mat == null) return new ErrorResult { error = "Material not found: " + matPath };
        Undo.RecordObject(renderer, "Assign Material");
        var mats = renderer.sharedMaterials;
        if (slotIndex >= mats.Length)
            System.Array.Resize(ref mats, slotIndex + 1);
        mats[slotIndex] = mat;
        renderer.sharedMaterials = mats;
        EditorUtility.SetDirty(renderer);
        return new Dictionary<string, object>
        {
            {"success", true},
            {"gameObjectPath", GetPath(go)},
            {"material", matPath},
            {"materialPath", matPath},
            {"slot", slotIndex},
            {"materialIndex", slotIndex}
        };
    }

    private static object HandleMaterialList(Dictionary<string, object> p)
    {
        string folder = GetString(p, "folder", "Assets");
        var guids = AssetDatabase.FindAssets("t:Material", new[] { folder });
        var mats = guids
            .Select(g => AssetDatabase.GUIDToAssetPath(g))
            .OrderBy(x => x)
            .Select(path => (object)new Dictionary<string, object>
            {
                {"name", Path.GetFileNameWithoutExtension(path)},
                {"path", path}
            })
            .ToList();
        return new Dictionary<string, object> { {"count", mats.Count}, {"materials", mats} };
    }

    // ── Prefab routes ─────────────────────────────────────────────────────

    private static object HandlePrefabSave(Dictionary<string, object> p)
    {
        string goPath    = GetString(p, "gameObject", GetString(p, "gameObjectPath", GetString(p, "path", "")));
        string savePath  = GetString(p, "savePath", GetString(p, "path", ""));        // e.g. Assets/Prefabs/Player.prefab
        bool   overwrite = GetBool(p, "overwrite", false);

        var go = FindGameObject(goPath);
        if (go == null) return new ErrorResult { error = "GameObject not found: " + goPath };
        if (string.IsNullOrEmpty(savePath))
            savePath = "Assets/Prefabs/" + go.name + ".prefab";
        EnsureAssetFolder(Path.GetDirectoryName(savePath).Replace("\\", "/"));

        if (!overwrite && AssetDatabase.LoadAssetAtPath<GameObject>(savePath) != null)
            return new ErrorResult { error = "Prefab already exists. Pass `overwrite: true` to replace." };

        bool success;
        PrefabUtility.SaveAsPrefabAsset(go, savePath, out success);
        if (!success) return new ErrorResult { error = "PrefabUtility.SaveAsPrefabAsset failed" };
        return new Dictionary<string, object>
        {
            {"success", true},
            {"path", savePath},
            {"savePath", savePath},
            {"gameObjectPath", GetPath(go)},
            {"name", go.name}
        };
    }

    private static object HandlePrefabInstantiate(Dictionary<string, object> p)
    {
        string prefabPath  = GetString(p, "prefabPath", GetString(p, "path", ""));
        string name        = GetString(p, "name", "");
        string parentPath  = GetString(p, "parent", "");

        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
        if (prefab == null) return new ErrorResult { error = "Prefab not found: " + prefabPath };

        Transform parent = null;
        if (!string.IsNullOrEmpty(parentPath))
        {
            var parentGo = FindGameObject(parentPath);
            if (parentGo == null) return new ErrorResult { error = "Parent not found: " + parentPath };
            parent = parentGo.transform;
        }

        var instance = (GameObject)PrefabUtility.InstantiatePrefab(prefab, parent);
        if (!string.IsNullOrEmpty(name)) instance.name = name;

        // Apply position if provided
        if (p.ContainsKey("position"))
        {
            var pos = p["position"] as Dictionary<string, object>;
            if (pos != null)
                instance.transform.localPosition = new Vector3(
                    (float)Convert.ToDouble(pos.ContainsKey("x") ? pos["x"] : 0.0),
                    (float)Convert.ToDouble(pos.ContainsKey("y") ? pos["y"] : 0.0),
                    (float)Convert.ToDouble(pos.ContainsKey("z") ? pos["z"] : 0.0));
        }
        Undo.RegisterCreatedObjectUndo(instance, "Instantiate " + prefab.name);
        return new Dictionary<string, object>
        {
            {"success", true},
            {"name", instance.name},
            {"instanceId", instance.GetInstanceID()},
            {"path", GetPath(instance)},
            {"gameObjectPath", GetPath(instance)},
            {"prefabPath", prefabPath}
        };
    }

    private static object HandlePrefabInfo(Dictionary<string, object> p)
    {
        string assetPath = GetString(p, "assetPath", "").Replace("\\", "/").Trim();
        string path = GetString(p, "path", "").Trim();
        int instanceId = GetInt(p, "instanceId", 0);

        if (string.IsNullOrEmpty(assetPath) && path.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
            assetPath = path.Replace("\\", "/");

        if (!string.IsNullOrEmpty(assetPath))
        {
            var prefabAsset = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
            if (prefabAsset == null) return new ErrorResult { error = "Prefab not found: " + assetPath };
            var comps = prefabAsset.GetComponents<Component>()
                .Where(c => c != null)
                .Select(c => c.GetType().Name)
                .ToList<object>();
            var assetType = PrefabUtility.GetPrefabAssetType(prefabAsset);
            return new Dictionary<string, object>
            {
                {"name", prefabAsset.name},
                {"path", assetPath},
                {"assetPath", assetPath},
                {"components", comps},
                {"componentCount", comps.Count},
                {"childCount", prefabAsset.transform.childCount},
                {"isInstance", false},
                {"isVariant", assetType == PrefabAssetType.Variant},
                {"prefabAssetType", assetType.ToString()}
            };
        }

        GameObject instance = instanceId != 0 ? FindGameObject(instanceId) : FindGameObject(path);
        if (instance == null) return new ErrorResult { error = "Prefab instance not found: " + (instanceId != 0 ? instanceId.ToString() : path) };

        var instanceComponents = instance.GetComponents<Component>()
            .Where(c => c != null)
            .Select(c => c.GetType().Name)
            .ToList<object>();
        var sourcePrefab = PrefabUtility.GetCorrespondingObjectFromSource(instance);
        string sourcePath = sourcePrefab != null ? AssetDatabase.GetAssetPath(sourcePrefab) : "";
        var assetTypeForInstance = PrefabUtility.GetPrefabAssetType(instance);
        var instanceStatus = PrefabUtility.GetPrefabInstanceStatus(instance);

        return new Dictionary<string, object>
        {
            {"name", instance.name},
            {"path", GetPath(instance)},
            {"assetPath", sourcePath},
            {"components", instanceComponents},
            {"componentCount", instanceComponents.Count},
            {"childCount", instance.transform.childCount},
            {"instanceId", instance.GetInstanceID()},
            {"isInstance", PrefabUtility.IsPartOfPrefabInstance(instance)},
            {"isVariant", assetTypeForInstance == PrefabAssetType.Variant},
            {"prefabAssetType", assetTypeForInstance.ToString()},
            {"prefabInstanceStatus", instanceStatus.ToString()}
        };
    }

    private static object HandlePrefabList(Dictionary<string, object> p)
    {
        string folder = GetString(p, "folder", "Assets");
        var guids = AssetDatabase.FindAssets("t:Prefab", new[] { folder });
        var prefabs = guids
            .Select(g => AssetDatabase.GUIDToAssetPath(g))
            .OrderBy(x => x)
            .Select(path => (object)new Dictionary<string, object>
            {
                {"name", Path.GetFileNameWithoutExtension(path)},
                {"path", path}
            })
            .ToList();
        return new Dictionary<string, object> { {"count", prefabs.Count}, {"prefabs", prefabs} };
    }

    private static object HandleGraphicsRendererInfo(Dictionary<string, object> p)
    {
        string objectPath = GetString(p, "gameObjectPath", GetString(p, "objectPath", GetString(p, "path", "")));
        var go = FindGameObject(objectPath);
        if (go == null) return new ErrorResult { error = "GameObject not found: " + objectPath };

        var renderer = go.GetComponent<Renderer>();
        if (renderer == null) return new ErrorResult { error = "Renderer not found on " + GetPath(go) };

        var materials = new List<object>();
        for (int index = 0; index < renderer.sharedMaterials.Length; index++)
        {
            var material = renderer.sharedMaterials[index];
            if (material == null)
                continue;
            materials.Add(new Dictionary<string, object>
            {
                {"name", material.name},
                {"path", AssetDatabase.GetAssetPath(material)},
                {"shaderName", material.shader != null ? material.shader.name : ""},
                {"materialIndex", index}
            });
        }

        var payload = new Dictionary<string, object>
        {
            {"objectPath", GetPath(go)},
            {"gameObjectPath", GetPath(go)},
            {"rendererType", renderer.GetType().Name},
            {"materials", materials},
            {"materialCount", materials.Count},
            {"shadowCastingMode", renderer.shadowCastingMode.ToString()},
            {"receiveShadows", renderer.receiveShadows},
            {"sortingLayerId", renderer.sortingLayerID},
            {"sortingLayerName", SortingLayer.IDToName(renderer.sortingLayerID)},
            {"sortingOrder", renderer.sortingOrder},
            {"lightmapIndex", renderer.lightmapIndex},
            {"bounds", new Dictionary<string, object>
                {
                    {"center", Vec3(renderer.bounds.center)},
                    {"size", Vec3(renderer.bounds.size)}
                }
            }
        };

        if (renderer is MeshRenderer || renderer is SkinnedMeshRenderer)
        {
            var filter = go.GetComponent<MeshFilter>();
            Mesh mesh = filter != null ? filter.sharedMesh : null;
            if (mesh == null && renderer is SkinnedMeshRenderer skinned)
                mesh = skinned.sharedMesh;

            payload["mesh"] = mesh != null
                ? new Dictionary<string, object>
                {
                    {"name", mesh.name},
                    {"vertexCount", mesh.vertexCount},
                    {"subMeshCount", mesh.subMeshCount}
                }
                : null;
        }

        return payload;
    }

    private static object HandleGraphicsMaterialInfo(Dictionary<string, object> p)
    {
        string assetPath = GetString(p, "assetPath", GetString(p, "path", "")).Replace("\\", "/").Trim();
        string objectPath = GetString(p, "gameObjectPath", GetString(p, "objectPath", ""));
        int materialIndex = GetInt(p, "materialIndex", 0);

        Material material = null;
        string resolvedObjectPath = "";

        if (!string.IsNullOrEmpty(objectPath))
        {
            var go = FindGameObject(objectPath);
            if (go == null) return new ErrorResult { error = "GameObject not found: " + objectPath };
            var renderer = go.GetComponent<Renderer>();
            if (renderer == null) return new ErrorResult { error = "Renderer not found on " + GetPath(go) };
            if (materialIndex < 0 || materialIndex >= renderer.sharedMaterials.Length)
                return new ErrorResult { error = "Material index out of range: " + materialIndex };

            material = renderer.sharedMaterials[materialIndex];
            resolvedObjectPath = GetPath(go);
            if (material == null)
                return new ErrorResult { error = "Material slot is empty at index " + materialIndex };
            if (string.IsNullOrEmpty(assetPath))
                assetPath = AssetDatabase.GetAssetPath(material);
        }
        else
        {
            if (string.IsNullOrEmpty(assetPath))
                return new ErrorResult { error = "assetPath or gameObjectPath is required" };
            material = AssetDatabase.LoadAssetAtPath<Material>(assetPath);
            if (material == null) return new ErrorResult { error = "Material not found: " + assetPath };
        }

        var properties = new List<object>();
        Shader shader = material.shader;
        if (shader != null)
        {
            int count = UnityEditor.ShaderUtil.GetPropertyCount(shader);
            for (int index = 0; index < count; index++)
            {
                string propertyName = UnityEditor.ShaderUtil.GetPropertyName(shader, index);
                var propertyType = UnityEditor.ShaderUtil.GetPropertyType(shader, index).ToString();
                var entry = new Dictionary<string, object>
                {
                    {"name", propertyName},
                    {"type", propertyType},
                    {"description", UnityEditor.ShaderUtil.GetPropertyDescription(shader, index)}
                };

                if (propertyType == "Color")
                    entry["value"] = ColorPayload(material.GetColor(propertyName));
                else if (propertyType == "Float" || propertyType == "Range")
                    entry["value"] = material.GetFloat(propertyName);
                else if (propertyType == "Vector")
                    entry["value"] = Vec4(material.GetVector(propertyName));
                else if (propertyType == "TexEnv")
                {
                    var texture = material.GetTexture(propertyName);
                    entry["value"] = texture != null
                        ? new Dictionary<string, object>
                        {
                            {"name", texture.name},
                            {"path", AssetDatabase.GetAssetPath(texture)}
                        }
                        : null;
                }

                properties.Add(entry);
            }
        }

        return new Dictionary<string, object>
        {
            {"assetPath", assetPath},
            {"objectPath", string.IsNullOrEmpty(resolvedObjectPath) ? null : resolvedObjectPath},
            {"materialIndex", materialIndex},
            {"materialName", material.name},
            {"shaderName", shader != null ? shader.name : ""},
            {"renderQueue", material.renderQueue},
            {"keywords", material.shaderKeywords != null ? material.shaderKeywords.ToArray() : new string[0]},
            {"keywordCount", material.shaderKeywords != null ? material.shaderKeywords.Length : 0},
            {"properties", properties}
        };
    }

    // ── Physics routes ───────────────────────────────────────────────────

    private static object HandlePhysicsSetGravity(Dictionary<string, object> p)
    {
        float y = GetFloat(p, "y", Physics.gravity.y);
        Physics.gravity = new Vector3(Physics.gravity.x, y, Physics.gravity.z);
        return new Dictionary<string, object>
        {
            {"success", true},
            {"gravity", new Dictionary<string, object>
                {
                    {"x", Physics.gravity.x},
                    {"y", Physics.gravity.y},
                    {"z", Physics.gravity.z},
                }
            }
        };
    }

    private static object HandlePhysicsSetRigidbody(Dictionary<string, object> p)
    {
        string goPath = GetString(p, "gameObject", "");
        var go = FindGameObject(goPath);
        if (go == null) return new ErrorResult { error = "GameObject not found: " + goPath };

        var rb = go.GetComponent<Rigidbody>();
        bool created = false;
        if (rb == null) { rb = Undo.AddComponent<Rigidbody>(go); created = true; }

        Undo.RecordObject(rb, "Set Rigidbody");
        if (p.ContainsKey("mass"))        rb.mass        = GetFloat(p, "mass", 1f);
        if (p.ContainsKey("drag"))        rb.linearDamping        = GetFloat(p, "drag", 0f);
        if (p.ContainsKey("angularDrag")) rb.angularDamping = GetFloat(p, "angularDrag", 0.05f);
        if (p.ContainsKey("isKinematic")) rb.isKinematic = GetBool(p, "isKinematic", false);
        if (p.ContainsKey("useGravity"))  rb.useGravity  = GetBool(p, "useGravity", true);
        EditorUtility.SetDirty(rb);
        return new Dictionary<string, object>
        {
            {"success", true},
            {"created", created},
            {"mass", rb.mass},
            {"isKinematic", rb.isKinematic},
            {"useGravity", rb.useGravity}
        };
    }

    private static object HandlePhysicsSetCollider(Dictionary<string, object> p)
    {
        string goPath    = GetString(p, "gameObject", "");
        string colliderType = GetString(p, "type", "box").ToLower(); // box|sphere|capsule
        var go = FindGameObject(goPath);
        if (go == null) return new ErrorResult { error = "GameObject not found: " + goPath };

        // Remove existing colliders if requested
        if (GetBool(p, "replace", false))
            foreach (var c in go.GetComponents<Collider>())
                Undo.DestroyObjectImmediate(c);

        bool isTrigger = GetBool(p, "isTrigger", false);
        Collider col;
        switch (colliderType)
        {
            case "sphere":
            {
                var sc = go.GetComponent<SphereCollider>() ?? Undo.AddComponent<SphereCollider>(go);
                sc.radius = GetFloat(p, "radius", 0.5f);
                sc.isTrigger = isTrigger;
                col = sc;
                break;
            }
            case "capsule":
            {
                var cc = go.GetComponent<CapsuleCollider>() ?? Undo.AddComponent<CapsuleCollider>(go);
                cc.radius = GetFloat(p, "radius", 0.5f);
                cc.height = GetFloat(p, "height", 2f);
                cc.isTrigger = isTrigger;
                col = cc;
                break;
            }
            default:
            {
                var bc = go.GetComponent<BoxCollider>() ?? Undo.AddComponent<BoxCollider>(go);
                bc.isTrigger = isTrigger;
                col = bc;
                break;
            }
        }
        EditorUtility.SetDirty(col);
        return new Dictionary<string, object>
        {
            {"success", true},
            {"type", colliderType},
            {"isTrigger", isTrigger}
        };
    }

    // ── Lighting routes ──────────────────────────────────────────────────

    private static object HandleLightingSetAmbient(Dictionary<string, object> p)
    {
        var col = p["color"] as Dictionary<string, object>;
        if (col == null) return new ErrorResult { error = "`color` object required" };
        float r = (float)Convert.ToDouble(col.ContainsKey("r") ? col["r"] : 0.2);
        float g = (float)Convert.ToDouble(col.ContainsKey("g") ? col["g"] : 0.2);
        float b = (float)Convert.ToDouble(col.ContainsKey("b") ? col["b"] : 0.2);
        RenderSettings.ambientLight = new Color(r, g, b);
        RenderSettings.ambientIntensity = GetFloat(p, "intensity", 1f);
        return new Dictionary<string, object> { {"success", true} };
    }

    private static object HandleLightingSetSun(Dictionary<string, object> p)
    {
        // Find first directional light or create one
        var lights = UnityEngine.Object.FindObjectsByType<Light>(FindObjectsSortMode.None);
        Light sun = System.Array.Find(lights, l => l.type == LightType.Directional);
        if (sun == null)
        {
            var go = new GameObject("Directional Light");
            sun = go.AddComponent<Light>();
            sun.type = LightType.Directional;
            Undo.RegisterCreatedObjectUndo(go, "Create Sun");
        }
        Undo.RecordObject(sun, "Set Sun");
        if (p.ContainsKey("intensity")) sun.intensity = GetFloat(p, "intensity", 1f);
        if (p.ContainsKey("color"))
        {
            var col = p["color"] as Dictionary<string, object>;
            if (col != null)
                sun.color = new Color(
                    (float)Convert.ToDouble(col.ContainsKey("r") ? col["r"] : 1.0),
                    (float)Convert.ToDouble(col.ContainsKey("g") ? col["g"] : 0.96),
                    (float)Convert.ToDouble(col.ContainsKey("b") ? col["b"] : 0.84));
        }
        if (p.ContainsKey("rotation"))
        {
            var rot = p["rotation"] as Dictionary<string, object>;
            if (rot != null)
                sun.transform.rotation = Quaternion.Euler(
                    (float)Convert.ToDouble(rot.ContainsKey("x") ? rot["x"] : 50.0),
                    (float)Convert.ToDouble(rot.ContainsKey("y") ? rot["y"] : -30.0),
                    (float)Convert.ToDouble(rot.ContainsKey("z") ? rot["z"] : 0.0));
        }
        EditorUtility.SetDirty(sun);
        return new Dictionary<string, object> { {"success", true}, {"gameObject", sun.gameObject.name} };
    }

    // ── Asset management routes ──────────────────────────────────────────

    private static object HandleAssetCreateFolder(Dictionary<string, object> p)
    {
        string folder = GetString(p, "path", "");
        if (string.IsNullOrEmpty(folder)) return new ErrorResult { error = "`path` is required" };
        EnsureAssetFolder(folder);
        AssetDatabase.Refresh();
        return new Dictionary<string, object> { {"success", true}, {"path", folder} };
    }

    private static object HandleAssetMove(Dictionary<string, object> p)
    {
        string from = GetString(p, "from", "");
        string to   = GetString(p, "to", "");
        if (string.IsNullOrEmpty(from) || string.IsNullOrEmpty(to))
            return new ErrorResult { error = "`from` and `to` are required" };
        string error = AssetDatabase.MoveAsset(from, to);
        if (!string.IsNullOrEmpty(error)) return new ErrorResult { error = error };
        return new Dictionary<string, object> { {"success", true}, {"from", from}, {"to", to} };
    }

    private static object HandleAssetDelete(Dictionary<string, object> p)
    {
        string assetPath = GetString(p, "path", "");
        if (string.IsNullOrEmpty(assetPath)) return new ErrorResult { error = "`path` is required" };
        if (!AssetDatabase.DeleteAsset(assetPath))
            return new ErrorResult { error = "Failed to delete: " + assetPath };
        return new Dictionary<string, object> { {"success", true}, {"path", assetPath} };
    }

    // ── Project settings routes ──────────────────────────────────────────

    private static object HandleTagAdd(Dictionary<string, object> p)
    {
        string tag = GetString(p, "tag", "");
        if (string.IsNullOrEmpty(tag)) return new ErrorResult { error = "`tag` is required" };
        var tagManager = new SerializedObject(AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(
            "ProjectSettings/TagManager.asset"));
        var tagsProp = tagManager.FindProperty("tags");
        // Check if already exists
        for (int i = 0; i < tagsProp.arraySize; i++)
            if (tagsProp.GetArrayElementAtIndex(i).stringValue == tag)
                return new Dictionary<string, object> { {"success", true}, {"tag", tag}, {"alreadyExists", true} };
        tagsProp.InsertArrayElementAtIndex(tagsProp.arraySize);
        tagsProp.GetArrayElementAtIndex(tagsProp.arraySize - 1).stringValue = tag;
        tagManager.ApplyModifiedProperties();
        return new Dictionary<string, object> { {"success", true}, {"tag", tag} };
    }

    private static object HandleLayerAdd(Dictionary<string, object> p)
    {
        string layerName = GetString(p, "layer", "");
        if (string.IsNullOrEmpty(layerName)) return new ErrorResult { error = "`layer` is required" };
        var tagManager = new SerializedObject(AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(
            "ProjectSettings/TagManager.asset"));
        var layersProp = tagManager.FindProperty("layers");
        // User layers start at index 8
        for (int i = 8; i < layersProp.arraySize; i++)
        {
            var elem = layersProp.GetArrayElementAtIndex(i);
            if (elem.stringValue == layerName)
                return new Dictionary<string, object> { {"success", true}, {"layer", layerName}, {"alreadyExists", true} };
            if (string.IsNullOrEmpty(elem.stringValue))
            {
                elem.stringValue = layerName;
                tagManager.ApplyModifiedProperties();
                return new Dictionary<string, object> { {"success", true}, {"layer", layerName}, {"index", i} };
            }
        }
        return new ErrorResult { error = "No empty layer slots available (max 32 layers)" };
    }

    // ── Reflection helpers ────────────────────────────────────────────────

    private static object ConvertValue(object value, Type targetType)
    {
        if (value == null) return targetType.IsValueType ? Activator.CreateInstance(targetType) : null;
        if (targetType == typeof(float))   return Convert.ToSingle(value);
        if (targetType == typeof(int))     return Convert.ToInt32(value);
        if (targetType == typeof(bool))    return Convert.ToBoolean(value);
        if (targetType == typeof(string))  return value.ToString();
        if (targetType == typeof(double))  return Convert.ToDouble(value);
        return Convert.ChangeType(value, targetType);
    }

    private static object SafeFieldValue(object value)
    {
        if (value == null) return null;
        if (value is float f)   return f;
        if (value is int i)     return i;
        if (value is bool b)    return b;
        if (value is string s)  return s;
        if (value is double d)  return d;
        if (value is Vector3 v) return new Dictionary<string, object> { {"x", v.x}, {"y", v.y}, {"z", v.z} };
        if (value is Color c)   return new Dictionary<string, object> { {"r", c.r}, {"g", c.g}, {"b", c.b}, {"a", c.a} };
        return value.ToString();
    }
}
