/*
 * CliAnythingWindow.cs — Unity Editor panel for cli-anything-unity-mcp
 *
 * Open via:  Window → CLI Anything
 *
 * Three tabs:
 *   Scene     — live hierarchy tree, click to select & inspect
 *   Inspector — transform editor + component list for selected object
 *   Actions   — one-click buttons for common scene tasks
 *
 * Everything runs directly via Unity APIs on the main thread.
 * No file IPC or network calls; expensive scene queries refresh on editor events.
 */

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

public class CliAnythingWindow : EditorWindow
{
    // ── Window lifecycle ─────────────────────────────────────────────────

    [MenuItem("Window/CLI Anything", priority = 9000)]
    public static void Open()
    {
        var window = GetWindow<CliAnythingWindow>("CLI Anything");
        window.minSize = new Vector2(460, 320);
        window.Show();
    }

    // ── State ────────────────────────────────────────────────────────────

    private int _tab = 0;
    private static readonly string[] TabLabels = { "  Scene  ", "  Inspector  ", "  Actions  " };

    // Scene tab
    private Vector2 _hierarchyScroll;
    private string _searchQuery = "";
    private GameObject _selected;
    private readonly HashSet<GameObject> _expanded = new HashSet<GameObject>();
    private bool _hierarchyDirty = true;
    private List<GameObject> _roots = new List<GameObject>();
    private readonly List<GameObject> _searchResults = new List<GameObject>();
    private string _cachedSearchQuery = null;
    private int _sceneObjectCount;

    // Inspector tab
    private Vector2 _inspectorScroll;
    private string _newComponentName = "";
    private bool _showTransform = true;
    private bool _showComponents = true;
    private bool _showChildren = true;

    // Actions tab
    private Vector2 _actionsScroll;
    private string _newObjectName = "New GameObject";
    private string _scriptName = "MyScript";
    private string _scriptFolder = "Assets/Scripts";
    private bool _showCreateObject = true;
    private bool _showSceneTools = true;
    private bool _showScriptTools = false;
    private bool _showPlayMode = true;
    private bool _statsDirty = true;
    private int _statObjects;
    private int _statCameras;
    private int _statLights;
    private int _statColliders;
    private int _statRigidbodies;

    // Styles (lazy-init)
    private GUIStyle _headerStyle;
    private GUIStyle _subHeaderStyle;
    private GUIStyle _selectedRowStyle;
    private GUIStyle _rowStyle;
    private GUIStyle _tagStyle;
    private GUIStyle _sectionStyle;
    private GUIStyle _bigButtonStyle;
    private GUIStyle _labelBoldStyle;
    private bool _stylesReady;

    // ── Unity callbacks ──────────────────────────────────────────────────

    private void OnEnable()
    {
        EditorApplication.hierarchyChanged += MarkDirty;
        Selection.selectionChanged += OnSelectionChanged;
        titleContent = new GUIContent("CLI Anything", EditorGUIUtility.IconContent("d_UnityEditor.ConsoleWindow").image);
    }

    private void OnDisable()
    {
        EditorApplication.hierarchyChanged -= MarkDirty;
        Selection.selectionChanged -= OnSelectionChanged;
    }

    private void MarkDirty()
    {
        _hierarchyDirty = true;
        _statsDirty = true;
        _cachedSearchQuery = null;
    }

    private void OnSelectionChanged()
    {
        if (Selection.activeGameObject != null)
        {
            _selected = Selection.activeGameObject;
            if (_tab == 0) _tab = 1;  // auto-switch to inspector
        }
        Repaint();
    }

    private void OnGUI()
    {
        EnsureStyles();
        DrawHeader();
        DrawTabs();

        switch (_tab)
        {
            case 0: DrawSceneTab();     break;
            case 1: DrawInspectorTab(); break;
            case 2: DrawActionsTab();   break;
        }
    }

    // ── Header ───────────────────────────────────────────────────────────

    private void DrawHeader()
    {
        var scene = SceneManager.GetActiveScene();
        string sceneName = string.IsNullOrEmpty(scene.name) ? "Untitled" : scene.name;
        string dirty = scene.isDirty ? "  ●" : "";

        EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);

        GUILayout.Label("Scene: " + sceneName + dirty, _labelBoldStyle, GUILayout.ExpandWidth(true));

        // Play / Pause / Stop
        GUI.backgroundColor = EditorApplication.isPlaying ? new Color(0.3f, 0.7f, 0.3f) : Color.white;
        if (GUILayout.Button(EditorApplication.isPlaying ? "Stop" : "Play", EditorStyles.toolbarButton, GUILayout.Width(65)))
            EditorApplication.isPlaying = !EditorApplication.isPlaying;
        GUI.backgroundColor = Color.white;

        if (GUILayout.Button("Save", EditorStyles.toolbarButton, GUILayout.Width(58)))
        {
            EditorSceneManager.SaveScene(scene);
            ShowNotification(new GUIContent("Scene saved"));
        }

        if (GUILayout.Button("Refresh", EditorStyles.toolbarButton, GUILayout.Width(58)))
            MarkDirty();

        EditorGUILayout.EndHorizontal();
    }

    // ── Tabs ─────────────────────────────────────────────────────────────

    private void DrawTabs()
    {
        _tab = GUILayout.Toolbar(_tab, TabLabels, EditorStyles.toolbarButton, GUILayout.Height(24));
        GUILayout.Space(2);
    }

    // ── Scene Tab ────────────────────────────────────────────────────────

    private void DrawSceneTab()
    {
        // Search bar
        EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);
        GUILayout.Label("Search", GUILayout.Width(48));
        string newSearch = EditorGUILayout.TextField(_searchQuery, EditorStyles.toolbarSearchField);
        if (newSearch != _searchQuery) { _searchQuery = newSearch; _cachedSearchQuery = null; }
        if (GUILayout.Button("Clear", EditorStyles.toolbarButton, GUILayout.Width(44)))
        { _searchQuery = ""; _cachedSearchQuery = null; }

        if (_hierarchyDirty)
            RefreshHierarchyCache();

        GUILayout.FlexibleSpace();
        GUILayout.Label(_sceneObjectCount + " objects", EditorStyles.miniLabel);
        EditorGUILayout.EndHorizontal();

        _hierarchyScroll = EditorGUILayout.BeginScrollView(_hierarchyScroll);

        bool searching = !string.IsNullOrEmpty(_searchQuery);
        if (searching)
        {
            DrawSearchResults();
        }
        else
        {
            foreach (var root in _roots)
                DrawHierarchyNode(root, 0);
        }

        EditorGUILayout.EndScrollView();

        // Footer hint
        EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);
        GUILayout.Label("Click to select  |  foldout to expand  |  Double-click to focus", EditorStyles.miniLabel);
        EditorGUILayout.EndHorizontal();
    }

    private void DrawSearchResults()
    {
        if (_cachedSearchQuery != _searchQuery)
            RefreshSearchResults();
        foreach (var go in _searchResults)
            DrawFlatRow(go);
    }

    private void DrawFlatRow(GameObject go)
    {
        bool isSel = go == _selected;
        var style = isSel ? _selectedRowStyle : _rowStyle;
        Rect row = GUILayoutUtility.GetRect(GUIContent.none, style, GUILayout.Height(20));

        if (Event.current.type == EventType.MouseDown && row.Contains(Event.current.mousePosition))
        {
            SelectObject(go);
            if (Event.current.clickCount == 2) SceneView.FrameLastActiveSceneView();
            Event.current.Use();
        }

        if (Event.current.type == EventType.Repaint)
        {
            style.Draw(row, false, isSel, isSel, false);
            var iconRect = new Rect(row.x + 4, row.y + 2, 16, 16);
            GUI.DrawTexture(iconRect, EditorGUIUtility.IconContent("GameObject Icon").image);
            var labelRect = new Rect(row.x + 24, row.y, row.width - 28, row.height);
            var label = new GUIContent(go.name + "  ");
            EditorStyles.label.Draw(labelRect, label, false, false, isSel, false);

            // Component tags
            float tagX = row.xMax - 4;
            DrawComponentTags(go, row, ref tagX);

            // Inactive badge
            if (!go.activeSelf)
            {
                var badgeStyle = _tagStyle;
                var badgeContent = new GUIContent("off");
                var badgeSize = badgeStyle.CalcSize(badgeContent);
                tagX -= badgeSize.x + 2;
                GUI.color = new Color(0.5f, 0.5f, 0.5f);
                badgeStyle.Draw(new Rect(tagX, row.y + 3, badgeSize.x, row.height - 6), badgeContent, false, false, false, false);
                GUI.color = Color.white;
            }
        }
    }

    private void DrawHierarchyNode(GameObject go, int depth)
    {
        bool hasChildren = go.transform.childCount > 0;
        bool isExpanded = _expanded.Contains(go);
        bool isSel = go == _selected;
        var style = isSel ? _selectedRowStyle : _rowStyle;

        Rect row = GUILayoutUtility.GetRect(GUIContent.none, style, GUILayout.Height(20));
        float indent = depth * 14f + 4f;
        var foldRect = new Rect(row.x + indent, row.y, 16, row.height);

        if (Event.current.type == EventType.MouseDown && hasChildren && foldRect.Contains(Event.current.mousePosition))
        {
            if (isExpanded) _expanded.Remove(go); else _expanded.Add(go);
            Event.current.Use();
        }
        else if (Event.current.type == EventType.MouseDown && row.Contains(Event.current.mousePosition))
        {
            if (Event.current.clickCount == 2)
            {
                SelectObject(go);
                SceneView.FrameLastActiveSceneView();
            }
            else
            {
                SelectObject(go);
            }
            Event.current.Use();
        }

        if (Event.current.type == EventType.Repaint)
        {
            style.Draw(row, false, isSel, isSel, false);

            // Expand arrow
            if (hasChildren)
            {
                var arrowRect = new Rect(row.x + indent, row.y + 4, 12, 12);
                GUI.Label(arrowRect, isExpanded ? "▾" : "▸", EditorStyles.miniLabel);
            }

            // Icon
            var iconRect = new Rect(row.x + indent + 14, row.y + 2, 16, 16);
            var icon = EditorGUIUtility.ObjectContent(go, typeof(GameObject)).image;
            if (icon != null) GUI.DrawTexture(iconRect, icon);

            // Name
            GUI.color = go.activeSelf ? Color.white : new Color(0.6f, 0.6f, 0.6f);
            var labelRect = new Rect(row.x + indent + 32, row.y, row.width - indent - 36, row.height);
            EditorStyles.label.Draw(labelRect, go.name, false, false, isSel, false);
            GUI.color = Color.white;

            // Component tags on right
            float tagX = row.xMax - 4;
            DrawComponentTags(go, row, ref tagX);
        }

        if (isExpanded && hasChildren)
        {
            for (int i = 0; i < go.transform.childCount; i++)
                DrawHierarchyNode(go.transform.GetChild(i).gameObject, depth + 1);
        }
    }

    private void DrawComponentTags(GameObject go, Rect row, ref float tagX)
    {
        // Show small badges for notable components
        string[] notable = { "Camera", "Light", "Rigidbody", "Collider", "AudioSource", "Canvas", "Animator", "CharacterController", "NavMeshAgent" };
        foreach (string n in notable)
        {
            var comp = go.GetComponent(n);
            if (comp == null) continue;
            var content = new GUIContent(n.Length > 6 ? n.Substring(0, 5) + "…" : n);
            var size = _tagStyle.CalcSize(content);
            tagX -= size.x + 3;
            GUI.color = TagColor(n);
            _tagStyle.Draw(new Rect(tagX, row.y + 3, size.x, row.height - 6), content, false, false, false, false);
            GUI.color = Color.white;
        }
    }

    private Color TagColor(string compName)
    {
        switch (compName)
        {
            case "Camera":             return new Color(0.3f, 0.6f, 1.0f, 0.85f);
            case "Light":              return new Color(1.0f, 0.85f, 0.2f, 0.85f);
            case "Rigidbody":          return new Color(0.7f, 0.4f, 1.0f, 0.85f);
            case "AudioSource":        return new Color(0.3f, 0.85f, 0.7f, 0.85f);
            case "Canvas":             return new Color(0.85f, 0.4f, 0.4f, 0.85f);
            case "Animator":           return new Color(0.9f, 0.6f, 0.2f, 0.85f);
            case "CharacterController":return new Color(0.4f, 0.8f, 0.4f, 0.85f);
            case "NavMeshAgent":       return new Color(0.4f, 0.7f, 0.9f, 0.85f);
            default:                   return new Color(0.5f, 0.5f, 0.5f, 0.6f);
        }
    }

    // ── Inspector Tab ────────────────────────────────────────────────────

    private void DrawInspectorTab()
    {
        if (_selected == null)
        {
            GUILayout.FlexibleSpace();
            EditorGUILayout.BeginHorizontal();
            GUILayout.FlexibleSpace();
            GUILayout.Label("Select an object in the Scene tab\nor click one in Unity's Hierarchy.", EditorStyles.centeredGreyMiniLabel);
            GUILayout.FlexibleSpace();
            EditorGUILayout.EndHorizontal();
            GUILayout.FlexibleSpace();
            return;
        }

        _inspectorScroll = EditorGUILayout.BeginScrollView(_inspectorScroll);

        // Object header
        EditorGUILayout.BeginHorizontal(_sectionStyle);
        bool active = EditorGUILayout.Toggle(_selected.activeSelf, GUILayout.Width(18));
        if (active != _selected.activeSelf)
        {
            Undo.RecordObject(_selected, "Toggle Active");
            _selected.SetActive(active);
            MarkDirty();
        }

        EditorGUI.BeginChangeCheck();
        string newName = EditorGUILayout.TextField(_selected.name, _headerStyle);
        if (EditorGUI.EndChangeCheck())
        {
            Undo.RecordObject(_selected, "Rename GameObject");
            _selected.name = newName;
            MarkDirty();
        }
        if (GUILayout.Button("Select in Editor", EditorStyles.miniButton, GUILayout.Width(105)))
            Selection.activeGameObject = _selected;
        if (GUILayout.Button("Focus", EditorStyles.miniButton, GUILayout.Width(46)))
        { Selection.activeGameObject = _selected; SceneView.FrameLastActiveSceneView(); }
        EditorGUILayout.EndHorizontal();

        GUILayout.Space(4);

        // Tag / Layer
        EditorGUILayout.BeginHorizontal();
        GUILayout.Label("Tag", GUILayout.Width(34));
        EditorGUI.BeginChangeCheck();
        string newTag = EditorGUILayout.TagField(_selected.tag);
        if (EditorGUI.EndChangeCheck())
        {
            Undo.RecordObject(_selected, "Change Tag");
            _selected.tag = newTag;
        }
        GUILayout.Space(8);
        GUILayout.Label("Layer", GUILayout.Width(38));
        EditorGUI.BeginChangeCheck();
        int newLayer = EditorGUILayout.LayerField(_selected.layer);
        if (EditorGUI.EndChangeCheck())
        {
            Undo.RecordObject(_selected, "Change Layer");
            _selected.layer = newLayer;
        }
        EditorGUILayout.EndHorizontal();

        GUILayout.Space(6);

        // Transform
        _showTransform = DrawSectionHeader("Transform", _showTransform);
        if (_showTransform)
        {
            var t = _selected.transform;
            EditorGUI.BeginChangeCheck();
            Vector3 pos = EditorGUILayout.Vector3Field("Position", t.position);
            Vector3 rot = EditorGUILayout.Vector3Field("Rotation", t.eulerAngles);
            Vector3 scl = EditorGUILayout.Vector3Field("Scale", t.localScale);
            if (EditorGUI.EndChangeCheck())
            {
                Undo.RecordObject(t, "Transform Change");
                t.position = pos;
                t.eulerAngles = rot;
                t.localScale = scl;
            }

            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("Reset Position", EditorStyles.miniButton))
            { Undo.RecordObject(t, "Reset Position"); t.localPosition = Vector3.zero; }
            if (GUILayout.Button("Reset Rotation", EditorStyles.miniButton))
            { Undo.RecordObject(t, "Reset Rotation"); t.localEulerAngles = Vector3.zero; }
            if (GUILayout.Button("Reset Scale", EditorStyles.miniButton))
            { Undo.RecordObject(t, "Reset Scale"); t.localScale = Vector3.one; }
            EditorGUILayout.EndHorizontal();
        }

        GUILayout.Space(6);

        // Components
        var components = _selected.GetComponents<Component>().Where(c => c != null && !(c is Transform)).ToArray();
        _showComponents = DrawSectionHeader($"Components  ({components.Length})", _showComponents);
        if (_showComponents)
        {
            foreach (var comp in components)
            {
                EditorGUILayout.BeginHorizontal(EditorStyles.helpBox);
                var icon = EditorGUIUtility.ObjectContent(comp, comp.GetType()).image;
                if (icon != null) GUILayout.Label(new GUIContent(icon), GUILayout.Width(18), GUILayout.Height(18));
                GUILayout.Label(comp.GetType().Name, _labelBoldStyle);
                GUILayout.FlexibleSpace();

                // Enable toggle for Behaviour components
                if (comp is Behaviour beh)
                {
                    EditorGUI.BeginChangeCheck();
                    bool enabled = EditorGUILayout.Toggle(beh.enabled, GUILayout.Width(16));
                    if (EditorGUI.EndChangeCheck())
                    {
                        Undo.RecordObject(beh, "Toggle Component");
                        beh.enabled = enabled;
                    }
                }

                if (GUILayout.Button("⋯", EditorStyles.miniButton, GUILayout.Width(24)))
                {
                    var menu = new GenericMenu();
                    menu.AddItem(new GUIContent("Remove Component"), false, () =>
                    {
                        Undo.DestroyObjectImmediate(comp);
                        MarkDirty();
                        Repaint();
                    });
                    menu.ShowAsContext();
                }
                EditorGUILayout.EndHorizontal();
            }

            GUILayout.Space(4);
            EditorGUILayout.BeginHorizontal();
            _newComponentName = EditorGUILayout.TextField(_newComponentName, EditorStyles.toolbarSearchField);
            if (GUILayout.Button("Add Component", EditorStyles.miniButton, GUILayout.Width(100)))
            {
                if (!string.IsNullOrEmpty(_newComponentName))
                    TryAddComponent(_selected, _newComponentName);
            }
            EditorGUILayout.EndHorizontal();
        }

        GUILayout.Space(6);

        // Children quick view
        if (_selected.transform.childCount > 0)
        {
            _showChildren = DrawSectionHeader($"Children  ({_selected.transform.childCount})", _showChildren);
            if (_showChildren)
            {
                for (int i = 0; i < _selected.transform.childCount; i++)
                {
                    var child = _selected.transform.GetChild(i).gameObject;
                    EditorGUILayout.BeginHorizontal();
                    GUILayout.Space(8);
                    GUI.color = child.activeSelf ? Color.white : new Color(0.6f, 0.6f, 0.6f);
                    if (GUILayout.Button(child.name, EditorStyles.miniButton))
                        SelectObject(child);
                    GUI.color = Color.white;
                    EditorGUILayout.EndHorizontal();
                }
            }
        }

        GUILayout.Space(6);

        // Danger zone
        EditorGUILayout.BeginHorizontal();
        GUI.backgroundColor = new Color(0.9f, 0.3f, 0.3f);
        if (GUILayout.Button("Delete Object", EditorStyles.miniButton))
        {
            if (EditorUtility.DisplayDialog("Delete Object",
                $"Delete '{_selected.name}'? This can be undone.", "Delete", "Cancel"))
            {
                Undo.DestroyObjectImmediate(_selected);
                _selected = null;
                MarkDirty();
            }
        }
        GUI.backgroundColor = Color.white;
        if (GUILayout.Button("Duplicate", EditorStyles.miniButton))
        {
            var copy = Instantiate(_selected);
            copy.name = _selected.name + "_Copy";
            Undo.RegisterCreatedObjectUndo(copy, "Duplicate");
            MarkDirty();
            SelectObject(copy);
        }
        EditorGUILayout.EndHorizontal();

        EditorGUILayout.EndScrollView();
    }

    // ── Actions Tab ──────────────────────────────────────────────────────

    private void DrawActionsTab()
    {
        _actionsScroll = EditorGUILayout.BeginScrollView(_actionsScroll);

        // Play Mode
        _showPlayMode = DrawSectionHeader("Play Mode", _showPlayMode);
        if (_showPlayMode)
        {
            EditorGUILayout.BeginHorizontal();
            GUI.backgroundColor = EditorApplication.isPlaying ? new Color(0.3f, 0.8f, 0.3f) : Color.white;
            if (GUILayout.Button(EditorApplication.isPlaying ? "Stop Play Mode" : "Enter Play Mode", _bigButtonStyle, GUILayout.Height(34)))
                EditorApplication.isPlaying = !EditorApplication.isPlaying;
            GUI.backgroundColor = Color.white;
            EditorGUILayout.EndHorizontal();

            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("Pause / Resume", EditorStyles.miniButton))
                EditorApplication.isPaused = !EditorApplication.isPaused;
            if (GUILayout.Button("Step Frame", EditorStyles.miniButton))
                EditorApplication.Step();
            EditorGUILayout.EndHorizontal();
            GUILayout.Space(4);
        }

        // Scene Tools
        _showSceneTools = DrawSectionHeader("Scene", _showSceneTools);
        if (_showSceneTools)
        {
            var scene = SceneManager.GetActiveScene();
            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("Save Scene", _bigButtonStyle, GUILayout.Height(30)))
            { EditorSceneManager.SaveScene(scene); ShowNotification(new GUIContent("Saved")); }
            if (GUILayout.Button("Reload Scene", _bigButtonStyle, GUILayout.Height(30)))
            { if (EditorUtility.DisplayDialog("Reload Scene", "Discard unsaved changes and reload?", "Reload", "Cancel"))
                EditorSceneManager.OpenScene(scene.path); }
            EditorGUILayout.EndHorizontal();

            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("Clear Console", EditorStyles.miniButton))
            {
                var logEntries = Type.GetType("UnityEditor.LogEntries, UnityEditor");
                logEntries?.GetMethod("Clear", System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.Public)?.Invoke(null, null);
            }
            if (GUILayout.Button("Refresh Assets", EditorStyles.miniButton))
                AssetDatabase.Refresh();
            if (GUILayout.Button("Run Tests", EditorStyles.miniButton))
                EditorApplication.ExecuteMenuItem("Window/General/Test Runner");
            EditorGUILayout.EndHorizontal();
            GUILayout.Space(4);
        }

        // Create Object
        _showCreateObject = DrawSectionHeader("Create Object", _showCreateObject);
        if (_showCreateObject)
        {
            EditorGUILayout.BeginHorizontal();
            GUILayout.Label("Name", GUILayout.Width(38));
            _newObjectName = EditorGUILayout.TextField(_newObjectName);
            EditorGUILayout.EndHorizontal();

            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("Empty", EditorStyles.miniButton)) CreateObject(_newObjectName, null);
            if (GUILayout.Button("Cube", EditorStyles.miniButton))  CreatePrimitive(_newObjectName, PrimitiveType.Cube);
            if (GUILayout.Button("Sphere", EditorStyles.miniButton)) CreatePrimitive(_newObjectName, PrimitiveType.Sphere);
            if (GUILayout.Button("Capsule", EditorStyles.miniButton)) CreatePrimitive(_newObjectName, PrimitiveType.Capsule);
            if (GUILayout.Button("Plane", EditorStyles.miniButton)) CreatePrimitive(_newObjectName, PrimitiveType.Plane);
            if (GUILayout.Button("Camera", EditorStyles.miniButton)) CreateObject(_newObjectName, typeof(Camera));
            if (GUILayout.Button("Light", EditorStyles.miniButton)) CreateObject(_newObjectName, typeof(Light));
            EditorGUILayout.EndHorizontal();

            if (_selected != null)
            {
                EditorGUILayout.BeginHorizontal();
                GUILayout.Label("Parent new object under selected:", EditorStyles.miniLabel);
                if (GUILayout.Button("Create as Child", EditorStyles.miniButton, GUILayout.Width(110)))
                    CreateObjectUnder(_newObjectName, _selected);
                EditorGUILayout.EndHorizontal();
            }
            GUILayout.Space(4);
        }

        // Script Tools
        _showScriptTools = DrawSectionHeader("Create Script", _showScriptTools);
        if (_showScriptTools)
        {
            EditorGUILayout.BeginHorizontal();
            GUILayout.Label("Name", GUILayout.Width(38));
            _scriptName = EditorGUILayout.TextField(_scriptName);
            EditorGUILayout.EndHorizontal();

            EditorGUILayout.BeginHorizontal();
            GUILayout.Label("Folder", GUILayout.Width(38));
            _scriptFolder = EditorGUILayout.TextField(_scriptFolder);
            if (GUILayout.Button("Browse", EditorStyles.miniButton, GUILayout.Width(52)))
            {
                string picked = EditorUtility.OpenFolderPanel("Script Folder", _scriptFolder, "");
                if (!string.IsNullOrEmpty(picked) && picked.StartsWith(Application.dataPath))
                    _scriptFolder = "Assets" + picked.Substring(Application.dataPath.Length);
            }
            EditorGUILayout.EndHorizontal();

            if (GUILayout.Button("Create MonoBehaviour Script", _bigButtonStyle, GUILayout.Height(28)))
                CreateScript(_scriptName, _scriptFolder, "MonoBehaviour");
            if (GUILayout.Button("Create ScriptableObject Script", EditorStyles.miniButton))
                CreateScript(_scriptName, _scriptFolder, "ScriptableObject");
            GUILayout.Space(4);
        }

        // Scene Stats
        GUILayout.Space(2);
        EditorGUILayout.LabelField("", GUI.skin.horizontalSlider);
        DrawSceneStats();

        EditorGUILayout.EndScrollView();
    }

    private void DrawSceneStats()
    {
        if (_statsDirty)
            RefreshSceneStats();

        EditorGUILayout.LabelField("Scene Stats", EditorStyles.boldLabel);
        EditorGUILayout.BeginHorizontal();
        DrawStatBox("Objects",   _statObjects.ToString());
        DrawStatBox("Cameras",   _statCameras.ToString());
        DrawStatBox("Lights",    _statLights.ToString());
        DrawStatBox("Colliders", _statColliders.ToString());
        DrawStatBox("Rigidbodies", _statRigidbodies.ToString());
        EditorGUILayout.EndHorizontal();
    }

    private void DrawStatBox(string label, string value)
    {
        EditorGUILayout.BeginVertical(EditorStyles.helpBox, GUILayout.MinWidth(60));
        GUILayout.Label(value, _headerStyle);
        GUILayout.Label(label, EditorStyles.centeredGreyMiniLabel);
        EditorGUILayout.EndVertical();
    }

    // ── Helpers ──────────────────────────────────────────────────────────

    private bool DrawSectionHeader(string title, bool expanded)
    {
        EditorGUILayout.BeginHorizontal(_sectionStyle);
        GUILayout.Label(expanded ? "▾" : "▸", GUILayout.Width(14));
        bool clicked = GUILayout.Button(title, EditorStyles.boldLabel, GUILayout.ExpandWidth(true));
        EditorGUILayout.EndHorizontal();
        if (clicked || GUILayoutUtility.GetLastRect().Contains(Event.current.mousePosition) && Event.current.type == EventType.MouseDown)
            return !expanded;
        return expanded;
    }

    private void SelectObject(GameObject go)
    {
        _selected = go;
        Selection.activeGameObject = go;
        Repaint();
    }

    private void RefreshHierarchyCache()
    {
        _roots = SceneManager.GetActiveScene().GetRootGameObjects().ToList();
        _sceneObjectCount = FindObjectsByType<GameObject>(FindObjectsSortMode.None).Length;
        _hierarchyDirty = false;
        _cachedSearchQuery = null;
    }

    private void RefreshSearchResults()
    {
        _searchResults.Clear();
        _cachedSearchQuery = _searchQuery;
        if (string.IsNullOrWhiteSpace(_searchQuery))
            return;

        string query = _searchQuery.Trim();
        _searchResults.AddRange(
            FindObjectsByType<GameObject>(FindObjectsSortMode.None)
                .Where(g => g.name.IndexOf(query, StringComparison.OrdinalIgnoreCase) >= 0)
                .OrderBy(g => g.name)
        );
    }

    private void RefreshSceneStats()
    {
        _statObjects = FindObjectsByType<GameObject>(FindObjectsSortMode.None).Length;
        _statCameras = FindObjectsByType<Camera>(FindObjectsSortMode.None).Length;
        _statLights = FindObjectsByType<Light>(FindObjectsSortMode.None).Length;
        _statColliders = FindObjectsByType<Collider>(FindObjectsSortMode.None).Length;
        _statRigidbodies = FindObjectsByType<Rigidbody>(FindObjectsSortMode.None).Length;
        _statsDirty = false;
    }

    private void CreateObject(string name, Type componentType)
    {
        var go = new GameObject(name);
        if (componentType != null) go.AddComponent(componentType);
        Undo.RegisterCreatedObjectUndo(go, "Create " + name);
        MarkDirty();
        SelectObject(go);
    }

    private void CreateObjectUnder(string name, GameObject parent)
    {
        var go = new GameObject(name);
        go.transform.SetParent(parent.transform, false);
        Undo.RegisterCreatedObjectUndo(go, "Create " + name);
        MarkDirty();
        SelectObject(go);
    }

    private void CreatePrimitive(string name, PrimitiveType type)
    {
        var go = GameObject.CreatePrimitive(type);
        go.name = name;
        Undo.RegisterCreatedObjectUndo(go, "Create " + name);
        MarkDirty();
        SelectObject(go);
    }

    private void CreateScript(string name, string folder, string baseClass)
    {
        if (string.IsNullOrEmpty(name)) { EditorUtility.DisplayDialog("Error", "Script name is required.", "OK"); return; }

        string cleanName = System.Text.RegularExpressions.Regex.Replace(name, @"[^a-zA-Z0-9_]", "");
        if (string.IsNullOrEmpty(cleanName)) { EditorUtility.DisplayDialog("Error", "Invalid script name.", "OK"); return; }

        string projectRoot = Directory.GetParent(Application.dataPath)?.FullName ?? Application.dataPath;
        string fullFolder = Path.Combine(projectRoot, folder);
        if (!Directory.Exists(fullFolder)) Directory.CreateDirectory(fullFolder);

        string path = Path.Combine(fullFolder, cleanName + ".cs");
        if (File.Exists(path) && !EditorUtility.DisplayDialog("File Exists", $"{cleanName}.cs already exists. Overwrite?", "Overwrite", "Cancel"))
            return;

        string template = baseClass == "MonoBehaviour"
            ? $"using UnityEngine;\n\npublic class {cleanName} : MonoBehaviour\n{{\n    void Start()\n    {{\n        \n    }}\n\n    void Update()\n    {{\n        \n    }}\n}}\n"
            : $"using UnityEngine;\n\n[CreateAssetMenu(fileName = \"{cleanName}\", menuName = \"ScriptableObjects/{cleanName}\")]\npublic class {cleanName} : ScriptableObject\n{{\n    \n}}\n";

        File.WriteAllText(path, template);
        AssetDatabase.Refresh();
        var asset = AssetDatabase.LoadAssetAtPath<MonoScript>(folder + "/" + cleanName + ".cs");
        if (asset != null) Selection.activeObject = asset;
        ShowNotification(new GUIContent($"{cleanName}.cs created"));
    }

    private void TryAddComponent(GameObject go, string typeName)
    {
        var type = AppDomain.CurrentDomain.GetAssemblies()
            .SelectMany(a => { try { return a.GetTypes(); } catch { return new Type[0]; } })
            .FirstOrDefault(t => t.Name.Equals(typeName, StringComparison.OrdinalIgnoreCase)
                              && typeof(Component).IsAssignableFrom(t));

        if (type != null)
        {
            Undo.AddComponent(go, type);
            _newComponentName = "";
            MarkDirty();
            ShowNotification(new GUIContent($"Added {type.Name}"));
        }
        else
        {
            ShowNotification(new GUIContent($"Type '{typeName}' not found"));
        }
    }

    // ── Style init ───────────────────────────────────────────────────────

    private void EnsureStyles()
    {
        if (_stylesReady) return;
        _stylesReady = true;

        _headerStyle = new GUIStyle(EditorStyles.boldLabel)
        {
            fontSize = 13,
            alignment = TextAnchor.MiddleLeft,
        };

        _subHeaderStyle = new GUIStyle(EditorStyles.label)
        {
            fontSize = 11,
            normal = { textColor = new Color(0.6f, 0.6f, 0.6f) }
        };

        _labelBoldStyle = new GUIStyle(EditorStyles.boldLabel)
        {
            alignment = TextAnchor.MiddleLeft,
        };

        _rowStyle = new GUIStyle("CN EntryBackEven")
        {
            padding = new RectOffset(2, 2, 0, 0),
        };

        _selectedRowStyle = new GUIStyle("CN EntryBackOdd")
        {
            padding = new RectOffset(2, 2, 0, 0),
            normal = { background = MakeTex(1, 1, new Color(0.17f, 0.36f, 0.53f, 0.8f)) }
        };

        _tagStyle = new GUIStyle(EditorStyles.centeredGreyMiniLabel)
        {
            fontSize = 9,
            padding = new RectOffset(3, 3, 1, 1),
            normal = { background = MakeTex(1, 1, new Color(0.3f, 0.3f, 0.3f, 0.5f)) }
        };

        _sectionStyle = new GUIStyle(EditorStyles.toolbar)
        {
            fixedHeight = 0,
            stretchHeight = false,
            padding = new RectOffset(4, 4, 3, 3),
        };

        _bigButtonStyle = new GUIStyle(GUI.skin.button)
        {
            fontSize = 12,
            fontStyle = FontStyle.Bold,
        };
    }

    private static Texture2D MakeTex(int w, int h, Color col)
    {
        var tex = new Texture2D(w, h);
        tex.SetPixel(0, 0, col);
        tex.Apply();
        return tex;
    }
}
