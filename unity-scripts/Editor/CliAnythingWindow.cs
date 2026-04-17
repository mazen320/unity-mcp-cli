/*
 * CliAnythingWindow.cs — Unity Editor panel for cli-anything-unity-mcp
 *
 * Open via:  Window → CLI Anything
 *
 * Six tabs:
 *   Overview  — Project dashboard: scene stats, health checks, quick actions, recent errors
 *   Scene     — live hierarchy tree, click to select & inspect
 *   Inspector — transform editor + component list for selected object
 *   Console   — captured Unity log output
 *   Actions   — one-click buttons for common scene tasks
 *   Bridge    — direct bridge state and route explorer
 *
 * Everything runs directly via Unity APIs on the main thread.
 * No file IPC or network calls; expensive scene queries refresh on editor events.
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
using UnityEngine.UI;

public class CliAnythingWindow : EditorWindow
{
    // ── Window lifecycle ─────────────────────────────────────────────────

    [MenuItem("Window/CLI Anything", priority = 9000)]
    public static void Open()
    {
        var window = GetWindow<CliAnythingWindow>("CLI Anything");
        window.minSize = new Vector2(520, 360);
        window.Show();
    }

    // ── State ────────────────────────────────────────────────────────────

    private int _tab = 0;
    private static readonly string[] TabLabels = { "  Overview  ", "  Agent  ", "  Scene  ", "  Inspector  ", "  Console  ", "  Actions  ", "  Bridge  " };

    // Overview tab
    private Vector2 _overviewScroll;
    private double  _overviewLastRefresh;
    private bool    _showOvScene   = true;
    private bool    _showOvHealth  = true;
    private bool    _showOvActions = true;
    private bool    _showOvErrors  = true;
    // cached stats (refreshed on demand)
    private string  _ovSceneName   = "";
    private int     _ovObjects, _ovScripts, _ovPrefabs, _ovMaterials, _ovTextures, _ovAudio;
    private bool    _ovSceneDirty;
    private bool    _ovCompileErrors;
    private int     _ovMissingRefs;

    // ── Agent tab ────────────────────────────────────────────────────────
    private Vector2 _agentChatScroll;
    private string  _agentInput = "";
    private bool    _agentConnected;
    private bool    _agentBridgeLive;
    private string  _agentProjectSummary = "";
    private readonly List<AgentChatMessage> _agentMessages = new List<AgentChatMessage>();
    private readonly List<AgentChatMessage> _agentPendingMessages = new List<AgentChatMessage>();
    private AgentStatus _agentStatus;
    private double  _agentLastRefresh;
    private const double AgentRefreshInterval = 0.5;
    private string  _agentUmcpRoot = "";   // path to .umcp/ folder
    private int     _agentQueuedMessageCount;
    private string  _agentStatusSummary = "";
    private bool    _showAgentBridgeSettings;
    private bool    _agentAutoStartOnSend = true;
    private string  _agentHarnessRoot = "";
    private string  _agentPythonLauncher = "";
    private string  _agentPreferredProvider = "auto";
    private string  _agentPreferredModel = "";
    private string  _agentLastLaunchCommand = "";
    private int     _agentBridgePid;
    private double  _agentLaunchPendingUntil;
    private static readonly string[] AgentProviderOptions = { "auto", "openai", "anthropic" };

    private const string AgentHarnessRootPrefKey   = "CliAnything.AgentBridge.HarnessRoot";
    private const string AgentPythonPrefKey        = "CliAnything.AgentBridge.PythonLauncher";
    private const string AgentAutoStartPrefKey     = "CliAnything.AgentBridge.AutoStartOnSend";
    private const string AgentLastLaunchPrefKey    = "CliAnything.AgentBridge.LastLaunchCommand";

    private struct AgentChatMessage
    {
        public string id;
        public string role;       // "user" | "ai" | "system"
        public string content;
        public Dictionary<string, object> metadata;
        public List<AgentStepInfo> steps;
        public string timestamp;
    }

    private struct AgentStepInfo
    {
        public int    stepNum;
        public int    totalSteps;
        public string description;
        public string status;     // "pending" | "running" | "ok" | "error" | "skipped"
    }

    private struct AgentStatus
    {
        public string state;        // "idle" | "planning" | "executing" | "done" | "error"
        public int    currentStep;
        public int    totalSteps;
        public string currentAction;
        public int    pid;
        public bool   llmAvailable;
        public string llmProvider;
        public string llmModel;
    }

    private struct AgentBridgeLauncher
    {
        public string executable;
        public string prefixArgs;
        public string displayName;
    }

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
    private readonly Dictionary<int, Editor> _componentEditors = new Dictionary<int, Editor>();
    private GameObject _lastInspectedGo;

    // Console tab
    private readonly List<ConsoleEntry> _consoleLogs = new List<ConsoleEntry>();
    private readonly object _consoleLogLock = new object();
    private const int MaxConsoleLogs = 500;
    private Vector2 _consoleScroll;
    private bool _consoleAutoScroll = true;
    private bool _consoleShowLog = true;
    private bool _consoleShowWarning = true;
    private bool _consoleShowError = true;
    private string _consoleSearch = "";
    private int _consoleSelectedLog = -1;
    private int _consoleTotalLog, _consoleTotalWarn, _consoleTotalError;
    private Vector2 _consoleStackScroll;

    private struct ConsoleEntry
    {
        public string message;
        public string stackTrace;
        public LogType type;
        public string time;
    }

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

    // Bridge tab
    private Vector2 _bridgeScroll;
    private string _routeInput = "ping";
    private string _routeParams = "{}";
    private string _routeResult = "";
    private bool _showHttpSection = true;
    private bool _showFileIpcSection = true;
    private bool _showRouteExplorer = true;
    private double _lastBridgeRefresh;
    private bool _bridgeRunning;
    private int _bridgePort;
    private string _fileIpcStatus = "Unknown";
    private string _fileIpcHeartbeat = "";

    // Styles (lazy-init)
    private GUIStyle _headerStyle;
    private GUIStyle _subHeaderStyle;
    private GUIStyle _selectedRowStyle;
    private GUIStyle _rowStyle;
    private GUIStyle _tagStyle;
    private GUIStyle _sectionStyle;
    private GUIStyle _bigButtonStyle;
    private GUIStyle _labelBoldStyle;
    private GUIStyle _agentUserBubbleStyle;
    private GUIStyle _agentAiBubbleStyle;
    private GUIStyle _agentSystemBubbleStyle;
    private GUIStyle _agentRoleStyle;
    private GUIStyle _agentTimestampStyle;
    private bool _stylesReady;

    // ── Unity callbacks ──────────────────────────────────────────────────

    private void OnEnable()
    {
        EditorApplication.hierarchyChanged += MarkDirty;
        Selection.selectionChanged += OnSelectionChanged;
        Application.logMessageReceivedThreaded += CaptureConsoleLog;
        titleContent = new GUIContent("CLI Anything", EditorGUIUtility.IconContent("d_UnityEditor.ConsoleWindow").image);
        LoadAgentBridgeSettings();
    }

    private void OnDisable()
    {
        EditorApplication.hierarchyChanged -= MarkDirty;
        Selection.selectionChanged -= OnSelectionChanged;
        Application.logMessageReceivedThreaded -= CaptureConsoleLog;
        CleanupComponentEditors();
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
            if (_tab == 1) _tab = 2;  // auto-switch to inspector from scene tab
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
            case 0: DrawAssistantTab(); break;
            case 1: DrawAgentTab();     break;
            case 2: DrawSceneTab();     break;
            case 3: DrawInspectorTab(); break;
            case 4: DrawConsoleTab();   break;
            case 5: DrawActionsTab();   break;
            case 6: DrawBridgeTab();    break;
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

        // Bridge status dots
        RefreshBridgeStatusIfStale();
        GUI.color = _bridgeRunning ? new Color(0.3f, 0.9f, 0.3f) : new Color(0.7f, 0.7f, 0.7f);
        GUILayout.Label("● HTTP", EditorStyles.miniLabel, GUILayout.Width(52));
        GUI.color = _fileIpcStatus == "Active" ? new Color(0.3f, 0.7f, 1f) : new Color(0.7f, 0.7f, 0.7f);
        GUILayout.Label("● IPC", EditorStyles.miniLabel, GUILayout.Width(42));
        GUI.color = Color.white;

        EditorGUILayout.EndHorizontal();
    }

    // ── Tabs ─────────────────────────────────────────────────────────────

    private void DrawTabs()
    {
        _tab = GUILayout.Toolbar(_tab, TabLabels, EditorStyles.toolbarButton, GUILayout.Height(24));
        GUILayout.Space(2);
    }

    // ── Agent Tab ────────────────────────────────────────────────────────

    private void UpdateAgentTab()
    {
        double now = EditorApplication.timeSinceStartup;
        if (now - _agentLastRefresh < AgentRefreshInterval) return;
        _agentLastRefresh = now;

        // Find .umcp root from project root
        if (string.IsNullOrEmpty(_agentUmcpRoot))
        {
            string projectRoot = Path.GetDirectoryName(Application.dataPath);
            _agentUmcpRoot = Path.Combine(projectRoot, ".umcp");
        }

        // Check connection via ping.json
        string pingPath = Path.Combine(_agentUmcpRoot, "ping.json");
        _agentConnected = File.Exists(pingPath) && (DateTime.UtcNow - File.GetLastWriteTimeUtc(pingPath)).TotalSeconds < 10.0;

        // Read agent-status.json
        string statusPath = Path.Combine(_agentUmcpRoot, "agent-status.json");
        _agentBridgeLive = false;
        _agentStatusSummary = "";
        if (File.Exists(statusPath))
        {
            try
            {
                string raw = File.ReadAllText(statusPath);
                var data = StandaloneRouteHandler.MiniJson.Deserialize(raw);
                _agentStatus = new AgentStatus
                {
                    state        = data.ContainsKey("state")         ? data["state"]?.ToString()        ?? "" : "",
                    currentStep  = data.ContainsKey("currentStep")   ? Convert.ToInt32(data["currentStep"])  : 0,
                    totalSteps   = data.ContainsKey("totalSteps")    ? Convert.ToInt32(data["totalSteps"])   : 0,
                    currentAction= data.ContainsKey("currentAction") ? data["currentAction"]?.ToString() ?? "" : "",
                    pid          = data.ContainsKey("pid")           ? Convert.ToInt32(data["pid"]) : 0,
                    llmAvailable = data.ContainsKey("llmAvailable")  && Convert.ToBoolean(data["llmAvailable"]),
                    llmProvider  = data.ContainsKey("llmProvider")   ? data["llmProvider"]?.ToString() ?? "" : "",
                    llmModel     = data.ContainsKey("llmModel")      ? data["llmModel"]?.ToString() ?? "" : "",
                };
                _agentBridgeLive = (DateTime.UtcNow - File.GetLastWriteTimeUtc(statusPath)).TotalSeconds < 30.0;
                _agentBridgePid = _agentStatus.pid;
                if (_agentBridgeLive)
                    _agentLaunchPendingUntil = 0;
                _agentStatusSummary = _agentBridgeLive
                    ? ("Chat bridge " + (_agentStatus.state == "" ? "ready" : _agentStatus.state) + (_agentBridgePid > 0 ? $" (PID {_agentBridgePid})" : ""))
                    : "Chat bridge stale";
            }
            catch { }
        }
        else
        {
            _agentStatus = new AgentStatus();
            _agentBridgePid = 0;
            _agentStatusSummary = "Chat bridge offline";
        }

        if (!_agentBridgeLive && _agentLaunchPendingUntil > now)
            _agentStatusSummary = "Starting chat bridge...";

        string inboxDir = Path.Combine(_agentUmcpRoot, "chat", "user-inbox");
        _agentQueuedMessageCount = 0;
        if (Directory.Exists(inboxDir))
        {
            try
            {
                _agentQueuedMessageCount = Directory.GetFiles(inboxDir, "*.json").Length;
            }
            catch { }
        }

        // Read chat history
        string historyPath = Path.Combine(_agentUmcpRoot, "chat", "history.json");
        if (File.Exists(historyPath))
        {
            try
            {
                string raw = File.ReadAllText(historyPath);
                var arr = StandaloneRouteHandler.MiniJson.DeserializeAny(raw) as List<object>;
                if (arr != null)
                {
                    var refreshedMessages = new List<AgentChatMessage>();
                    var seenIds = new HashSet<string>(StringComparer.Ordinal);
                    foreach (var item in arr)
                    {
                        if (item is Dictionary<string, object> d)
                        {
                            var msg = new AgentChatMessage
                            {
                                id        = d.ContainsKey("id")        ? d["id"]?.ToString()        ?? "" : "",
                                role      = d.ContainsKey("role")      ? d["role"]?.ToString()      ?? "" : "",
                                content   = d.ContainsKey("content")   ? d["content"]?.ToString()   ?? "" : "",
                                metadata  = d.ContainsKey("metadata")  ? d["metadata"] as Dictionary<string, object> : null,
                                timestamp = d.ContainsKey("timestamp") ? d["timestamp"]?.ToString() ?? "" : "",
                                steps     = new List<AgentStepInfo>(),
                            };
                            // Parse steps if present
                            if (d.ContainsKey("steps") && d["steps"] is List<object> stepList)
                            {
                                foreach (var stepObj in stepList)
                                {
                                    if (stepObj is Dictionary<string, object> sd)
                                    {
                                        msg.steps.Add(new AgentStepInfo
                                        {
                                            stepNum     = sd.ContainsKey("step")        ? Convert.ToInt32(sd["step"])        : 0,
                                            totalSteps  = sd.ContainsKey("totalSteps")  ? Convert.ToInt32(sd["totalSteps"])  : 0,
                                            description = sd.ContainsKey("description") ? sd["description"]?.ToString() ?? "" : "",
                                            status      = sd.ContainsKey("status")      ? sd["status"]?.ToString()      ?? "" : "",
                                        });
                                    }
                                }
                            }
                            refreshedMessages.Add(msg);
                            if (!string.IsNullOrEmpty(msg.id))
                                seenIds.Add(msg.id);
                        }
                    }

                    _agentPendingMessages.RemoveAll(msg => !string.IsNullOrEmpty(msg.id) && seenIds.Contains(msg.id));
                    refreshedMessages.AddRange(_agentPendingMessages);

                    _agentMessages.Clear();
                    _agentMessages.AddRange(refreshedMessages);
                }
            }
            catch { }
        }
        else
        {
            _agentMessages.Clear();
            _agentMessages.AddRange(_agentPendingMessages);
        }

        Repaint();
    }

    private void DrawAgentTab()
    {
        UpdateAgentTab();
        EnsureStyles();

        // ── Connection bar ────────────────────────────────────────────────
        EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);
        var connColor = _agentConnected ? new Color(0.3f, 0.9f, 0.4f) : new Color(0.9f, 0.3f, 0.3f);
        var prevColor = GUI.color;
        GUI.color = connColor;
        GUILayout.Label(_agentConnected ? "● Connected" : "● Disconnected", EditorStyles.miniLabel, GUILayout.Width(110));
        GUI.color = prevColor;

        var bridgeColor = _agentBridgeLive ? new Color(0.3f, 0.8f, 1f) : new Color(1f, 0.7f, 0.25f);
        GUI.color = bridgeColor;
        GUILayout.Label(_agentBridgeLive ? "● Chat Live" : "● Chat Off", EditorStyles.miniLabel, GUILayout.Width(90));
        GUI.color = prevColor;

        var llmColor = _agentStatus.llmAvailable ? new Color(0.35f, 0.85f, 0.55f) : new Color(1f, 0.65f, 0.25f);
        GUI.color = llmColor;
        string llmLabel = _agentStatus.llmAvailable && !string.IsNullOrEmpty(_agentStatus.llmProvider)
            ? $"● {_agentStatus.llmProvider}"
            : "● LLM Off";
        GUILayout.Label(llmLabel, EditorStyles.miniLabel, GUILayout.Width(90));
        if (_agentStatus.llmAvailable && !string.IsNullOrEmpty(_agentStatus.llmModel))
            GUILayout.Label(_agentStatus.llmModel, EditorStyles.miniLabel, GUILayout.Width(120));
        GUI.color = prevColor;

        if (_agentStatus.state == "executing" && _agentStatus.totalSteps > 0)
        {
            string progress = $"Step {_agentStatus.currentStep}/{_agentStatus.totalSteps}: {_agentStatus.currentAction}";
            GUILayout.Label(progress, EditorStyles.miniLabel);
        }
        else if (_agentStatus.state == "planning")
        {
            GUILayout.Label("Planning...", EditorStyles.miniLabel);
        }
        else if (!string.IsNullOrEmpty(_agentStatusSummary))
        {
            GUILayout.Label(_agentStatusSummary, EditorStyles.miniLabel);
        }
        else if (!string.IsNullOrEmpty(_agentProjectSummary))
        {
            GUILayout.Label(_agentProjectSummary, EditorStyles.miniLabel);
        }

        GUILayout.FlexibleSpace();
        if (_agentQueuedMessageCount > 0)
            GUILayout.Label($"Queued {_agentQueuedMessageCount}", EditorStyles.miniLabel, GUILayout.Width(70));
        using (new EditorGUI.DisabledScope(!_agentConnected))
        {
            if (!_agentBridgeLive)
            {
                using (new EditorGUI.DisabledScope(_agentLaunchPendingUntil > EditorApplication.timeSinceStartup))
                {
                    if (GUILayout.Button("Connect", EditorStyles.toolbarButton, GUILayout.Width(58)))
                        TryLaunchAgentBridge(true);
                }
            }
            else
            {
                GUILayout.Label(_agentBridgePid > 0 ? $"PID {_agentBridgePid}" : "Bridge running", EditorStyles.miniLabel, GUILayout.Width(78));
            }
        }
        if (GUILayout.Button(_showAgentBridgeSettings ? "Hide" : "Settings", EditorStyles.toolbarButton, GUILayout.Width(58)))
            _showAgentBridgeSettings = !_showAgentBridgeSettings;
        if (GUILayout.Button("Clear", EditorStyles.toolbarButton, GUILayout.Width(45)))
            ClearAgentChatHistory();
        if (GUILayout.Button("Refresh", EditorStyles.toolbarButton, GUILayout.Width(55)))
            _agentLastRefresh = 0;
        EditorGUILayout.EndHorizontal();

        if (_showAgentBridgeSettings)
            DrawAgentBridgeSettings();

        // ── Chat history ──────────────────────────────────────────────────
        float inputHeight = 128f;
        float settingsHeight = _showAgentBridgeSettings ? 176f : 0f;
        bool hasImproveProjectReport = TryGetLatestImproveProjectMessage(out var improveProjectMessage);
        float improveProjectHeight = hasImproveProjectReport ? 174f : 0f;
        float chatHeight = Mathf.Max(120f, position.height - 80f - inputHeight - settingsHeight - improveProjectHeight);

        if (hasImproveProjectReport)
        {
            DrawImproveProjectSummary(improveProjectMessage);
            EditorGUILayout.Space(4);
        }

        _agentChatScroll = EditorGUILayout.BeginScrollView(_agentChatScroll,
            GUILayout.Height(chatHeight));

        if (_agentMessages.Count == 0)
        {
            EditorGUILayout.Space(16);
            var centered = new GUIStyle(EditorStyles.label)
            {
                alignment = TextAnchor.MiddleCenter,
                wordWrap  = true,
                normal    = { textColor = new Color(0.5f, 0.5f, 0.5f) }
            };
            GUILayout.Label(
                !_agentConnected
                    ? "No IPC connection. Open Unity with FileIPCBridge.cs in Assets/Editor/."
                    : !_agentBridgeLive
                        ? "IPC is connected, but the chat bridge is offline. Click Connect, or send a message and let the panel auto-start it."
                        : "Chat bridge is live. Send a message below.",
                centered);
        }

        foreach (var msg in _agentMessages)
        {
            DrawAgentMessage(msg);
        }

        // Show live executing step if agent is running
        if (_agentStatus.state == "executing" && !string.IsNullOrEmpty(_agentStatus.currentAction))
        {
            EditorGUILayout.BeginHorizontal();
            GUILayout.Space(8);
            var runStyle = new GUIStyle(EditorStyles.helpBox)
            {
                normal = { textColor = new Color(0.4f, 0.8f, 1f) }
            };
            GUILayout.Label($"⟳  [{_agentStatus.currentStep}/{_agentStatus.totalSteps}] {_agentStatus.currentAction}", runStyle);
            EditorGUILayout.EndHorizontal();
            EditorGUILayout.Space(2);
        }

        EditorGUILayout.EndScrollView();

        // ── Input area ────────────────────────────────────────────────────
        EditorGUILayout.BeginVertical(EditorStyles.helpBox, GUILayout.MinHeight(96f));
        GUILayout.Label("Message", EditorStyles.miniLabel);
        EditorGUILayout.BeginHorizontal();
        GUI.SetNextControlName("AgentInput");
        _agentInput = EditorGUILayout.TextField(_agentInput, GUILayout.Height(24f), GUILayout.ExpandWidth(true));

        bool send = GUILayout.Button("Send", GUILayout.Width(60))
                 || (Event.current.type == EventType.KeyDown
                     && (Event.current.keyCode == KeyCode.Return || Event.current.keyCode == KeyCode.KeypadEnter)
                     && GUI.GetNameOfFocusedControl() == "AgentInput"
                     && !Event.current.shift);

        if (send && !string.IsNullOrWhiteSpace(_agentInput))
        {
            SendAgentMessage(_agentInput.Trim());
            _agentInput = "";
            GUI.FocusControl("AgentInput");
        }
        EditorGUILayout.EndHorizontal();

        // Quick-action buttons
        EditorGUILayout.BeginHorizontal();
        if (GUILayout.Button("improve project", EditorStyles.miniButton)) SendAgentMessage("improve project");
        if (GUILayout.Button("context", EditorStyles.miniButton)) SendAgentMessage("context");
        if (GUILayout.Button("scene info", EditorStyles.miniButton)) SendAgentMessage("scene info");
        if (GUILayout.Button("list scripts", EditorStyles.miniButton)) SendAgentMessage("list scripts");
        EditorGUILayout.EndHorizontal();
        EditorGUILayout.BeginHorizontal();
        if (GUILayout.Button("compile errors", EditorStyles.miniButton)) SendAgentMessage("compile errors");
        if (GUILayout.Button("save scene", EditorStyles.miniButton)) SendAgentMessage("save scene");
        EditorGUILayout.EndHorizontal();
        EditorGUILayout.EndVertical();
    }

    private void DrawAgentMessage(AgentChatMessage msg)
    {
        bool isUser = msg.role == "user";
        bool isAI   = msg.role == "ai" || msg.role == "assistant";

        EditorGUILayout.BeginHorizontal();
        if (isUser) GUILayout.FlexibleSpace();
        GUILayout.Space(isUser ? 0 : 8);

        var bubbleStyle = isUser ? _agentUserBubbleStyle : isAI ? _agentAiBubbleStyle : _agentSystemBubbleStyle;

        float maxWidth = position.width * 0.75f;
        GUILayout.BeginVertical(bubbleStyle, GUILayout.MaxWidth(maxWidth));

        EditorGUILayout.BeginHorizontal();
        GUILayout.Label(isUser ? "You" : isAI ? "Agent" : "System", _agentRoleStyle);
        GUILayout.FlexibleSpace();
        if (!string.IsNullOrEmpty(msg.timestamp))
            GUILayout.Label(FormatAgentTimestamp(msg.timestamp), _agentTimestampStyle);
        EditorGUILayout.EndHorizontal();

        GUILayout.Label(msg.content, bubbleStyle);

        // Steps
        if (msg.steps != null && msg.steps.Count > 0)
        {
            EditorGUILayout.Space(2);
            foreach (var step in msg.steps)
            {
                string icon = step.status == "ok" ? "✓"
                            : step.status == "error" ? "✗"
                            : step.status == "running" ? "⟳"
                            : step.status == "skipped" ? "–"
                            : "·";
                var stepColor = step.status == "ok"      ? new Color(0.4f, 0.9f, 0.4f)
                              : step.status == "error"   ? new Color(1f, 0.4f, 0.4f)
                              : step.status == "running" ? new Color(0.4f, 0.8f, 1f)
                              : new Color(0.5f, 0.5f, 0.5f);
                var prevC = GUI.color;
                GUI.color = stepColor;
                GUILayout.Label($"  {icon} [{step.stepNum}] {step.description}", EditorStyles.miniLabel);
                GUI.color = prevC;
            }
        }

        GUILayout.EndVertical();

        if (!isUser) GUILayout.FlexibleSpace();
        EditorGUILayout.EndHorizontal();
        EditorGUILayout.Space(3);
    }

    private bool TryGetLatestImproveProjectMessage(out AgentChatMessage message)
    {
        for (int index = _agentMessages.Count - 1; index >= 0; index--)
        {
            var candidate = _agentMessages[index];
            if (IsImproveProjectMessage(candidate))
            {
                message = candidate;
                return true;
            }
        }

        message = new AgentChatMessage();
        return false;
    }

    private static bool IsImproveProjectMessage(AgentChatMessage message)
    {
        if (message.metadata == null)
            return false;
        if (!message.metadata.TryGetValue("kind", out var kindValue))
            return false;
        return string.Equals(kindValue?.ToString(), "improve-project", StringComparison.OrdinalIgnoreCase);
    }

    private void DrawImproveProjectSummary(AgentChatMessage message)
    {
        var metadata = message.metadata;
        var payload = metadata != null && metadata.TryGetValue("payload", out var payloadValue)
            ? payloadValue as Dictionary<string, object>
            : null;
        string markdown = metadata != null && metadata.TryGetValue("markdown", out var markdownValue)
            ? markdownValue?.ToString() ?? ""
            : "";

        EditorGUILayout.BeginVertical(EditorStyles.helpBox);

        EditorGUILayout.BeginHorizontal();
        GUILayout.Label("Latest Improve Project", EditorStyles.boldLabel);
        GUILayout.FlexibleSpace();
        if (!string.IsNullOrEmpty(message.timestamp))
            GUILayout.Label(FormatAgentTimestamp(message.timestamp), EditorStyles.miniLabel, GUILayout.Width(120));
        using (new EditorGUI.DisabledScope(string.IsNullOrWhiteSpace(markdown)))
        {
            if (GUILayout.Button("Export Markdown", EditorStyles.miniButton, GUILayout.Width(110)))
                ExportImproveProjectMarkdown(markdown, message.timestamp);
        }
        if (GUILayout.Button("Run Again", EditorStyles.miniButton, GUILayout.Width(70)))
            SendAgentMessage("improve project");
        EditorGUILayout.EndHorizontal();

        double? baselineScore = GetDouble(payload, "baselineScore");
        double? finalScore = GetDouble(payload, "finalScore");
        double? scoreDelta = GetDouble(payload, "scoreDelta");
        if (baselineScore.HasValue && finalScore.HasValue)
        {
            if (!scoreDelta.HasValue)
                scoreDelta = finalScore.Value - baselineScore.Value;
            EditorGUILayout.LabelField(
                $"Quality score: {baselineScore.Value:0.0} -> {finalScore.Value:0.0} ({scoreDelta.Value:+0.0;-0.0;0.0})",
                EditorStyles.label
            );
        }
        else if (finalScore.HasValue)
        {
            EditorGUILayout.LabelField($"Quality score: {finalScore.Value:0.0}", EditorStyles.label);
        }
        else
        {
            EditorGUILayout.LabelField("Quality score: unavailable", EditorStyles.label);
        }

        int appliedCount = GetInt(payload, "appliedCount");
        int skippedCount = GetInt(payload, "skippedCount");
        bool liveUnityAvailable = GetBool(payload, "liveUnityAvailable");
        EditorGUILayout.LabelField(
            $"Applied: {appliedCount}   Skipped: {skippedCount}   Live Unity: {(liveUnityAvailable ? "yes" : "no")}",
            EditorStyles.miniLabel
        );

        DrawImproveProjectItems("Applied", GetList(payload, "applied"), preferSummary: true, maxItems: 3);
        DrawImproveProjectItems("Skipped", GetList(payload, "skipped"), preferSummary: false, maxItems: 2);

        EditorGUILayout.EndVertical();
    }

    private void DrawImproveProjectItems(string title, List<object> items, bool preferSummary, int maxItems)
    {
        if (items == null || items.Count == 0)
            return;

        EditorGUILayout.Space(2);
        GUILayout.Label(title, EditorStyles.miniBoldLabel);
        int shown = 0;
        foreach (var item in items)
        {
            if (shown >= maxItems)
                break;
            string line = DescribeImproveProjectItem(item, preferSummary);
            if (string.IsNullOrWhiteSpace(line))
                continue;
            GUILayout.Label("• " + line, EditorStyles.miniLabel);
            shown++;
        }

        int hidden = items.Count - shown;
        if (hidden > 0)
            GUILayout.Label($"+ {hidden} more", EditorStyles.miniLabel);
    }

    private static string DescribeImproveProjectItem(object item, bool preferSummary)
    {
        if (item is Dictionary<string, object> entry)
        {
            string primaryKey = preferSummary ? "summary" : "reason";
            if (entry.TryGetValue(primaryKey, out var primaryValue) && primaryValue != null)
                return primaryValue.ToString();
            if (entry.TryGetValue("summary", out var summaryValue) && summaryValue != null)
                return summaryValue.ToString();
            if (entry.TryGetValue("reason", out var reasonValue) && reasonValue != null)
                return reasonValue.ToString();
            if (entry.TryGetValue("fix", out var fixValue) && fixValue != null)
                return fixValue.ToString();
        }
        return item?.ToString() ?? "";
    }

    private void ExportImproveProjectMarkdown(string markdown, string timestamp)
    {
        try
        {
            string projectRoot = Path.GetDirectoryName(Application.dataPath) ?? "";
            string defaultName = "improve-project-report";
            if (!string.IsNullOrEmpty(timestamp))
            {
                string safeStamp = timestamp.Replace(":", "-").Replace("T", "_").Replace("Z", "");
                defaultName = "improve-project-" + safeStamp;
            }
            string path = EditorUtility.SaveFilePanel("Export Improve Project Report", projectRoot, defaultName, "md");
            if (string.IsNullOrEmpty(path))
                return;

            File.WriteAllText(path, markdown, new UTF8Encoding(false));
            _agentStatusSummary = "Exported improve-project markdown report.";
            ShowNotification(new GUIContent("Improve-project report exported"));
        }
        catch (Exception ex)
        {
            Debug.LogWarning("[Agent] Failed to export improve-project markdown: " + ex.Message);
        }
    }

    private static List<object> GetList(Dictionary<string, object> dict, string key)
    {
        if (dict == null || !dict.TryGetValue(key, out var value))
            return null;
        return value as List<object>;
    }

    private static double? GetDouble(Dictionary<string, object> dict, string key)
    {
        if (dict == null || !dict.TryGetValue(key, out var value) || value == null)
            return null;
        try
        {
            return Convert.ToDouble(value);
        }
        catch
        {
            return null;
        }
    }

    private static int GetInt(Dictionary<string, object> dict, string key)
    {
        if (dict == null || !dict.TryGetValue(key, out var value) || value == null)
            return 0;
        try
        {
            return Convert.ToInt32(value);
        }
        catch
        {
            return 0;
        }
    }

    private static bool GetBool(Dictionary<string, object> dict, string key)
    {
        if (dict == null || !dict.TryGetValue(key, out var value) || value == null)
            return false;
        try
        {
            return Convert.ToBoolean(value);
        }
        catch
        {
            return false;
        }
    }

    private void SendAgentMessage(string text)
    {
        // Write directly to a unique inbox file so the Python agent can drain a queue
        // without depending on Windows rename semantics.
        try
        {
            if (_agentConnected && !_agentBridgeLive && _agentAutoStartOnSend)
                TryLaunchAgentBridge(false);

            if (string.IsNullOrEmpty(_agentUmcpRoot))
            {
                _agentUmcpRoot = Path.Combine(Path.GetDirectoryName(Application.dataPath), ".umcp");
            }
            string chatDir = Path.Combine(_agentUmcpRoot, "chat");
            string inboxDir = Path.Combine(chatDir, "user-inbox");
            Directory.CreateDirectory(inboxDir);
            string messageId = Guid.NewGuid().ToString("N");
            string timestamp = DateTime.UtcNow.ToString("o");
            string json = "{\"id\":\"" + messageId + "\",\"role\":\"user\",\"content\":\"" + EscapeJsonString(text) + "\",\"timestamp\":\"" + timestamp + "\"}";
            WriteQueuedAgentInboxFile(inboxDir, json);

            // Optimistically add to local history for immediate feedback
            var pendingMessage = new AgentChatMessage
            {
                id        = messageId,
                role      = "user",
                content   = text,
                timestamp = timestamp,
                steps     = new List<AgentStepInfo>()
            };
            _agentPendingMessages.Add(pendingMessage);
            _agentMessages.Add(pendingMessage);
            _agentChatScroll = new Vector2(0, float.MaxValue);
            if (_agentConnected && !_agentBridgeLive)
                _agentStatusSummary = "Message queued. Waiting for chat bridge.";
            Repaint();
        }
        catch (Exception ex)
        {
            Debug.LogWarning("[Agent] Failed to write user message: " + ex.Message);
        }
    }

    private static void WriteQueuedAgentInboxFile(string inboxDir, string json)
    {
        var utf8NoBom = new UTF8Encoding(false);
        for (int attempt = 0; attempt < 8; attempt++)
        {
            string fileName = DateTime.UtcNow.ToString("yyyyMMddTHHmmssfffffff") + "-" + Guid.NewGuid().ToString("N") + ".json";
            string inboxPath = Path.Combine(inboxDir, fileName);
            try
            {
                using (var stream = new FileStream(inboxPath, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                using (var writer = new StreamWriter(stream, utf8NoBom))
                {
                    writer.Write(json);
                }
                return;
            }
            catch (IOException)
            {
                // Retry with a fresh unique path if Windows reports a collision.
            }
        }

        throw new IOException("Could not create a unique queued inbox file.");
    }

    private void ClearAgentChatHistory()
    {
        try
        {
            if (string.IsNullOrEmpty(_agentUmcpRoot))
            {
                _agentUmcpRoot = Path.Combine(Path.GetDirectoryName(Application.dataPath), ".umcp");
            }

            string historyPath = Path.Combine(_agentUmcpRoot, "chat", "history.json");
            if (File.Exists(historyPath))
                File.Delete(historyPath);

            _agentMessages.Clear();
            _agentPendingMessages.Clear();
            _agentChatScroll = Vector2.zero;
            Repaint();
        }
        catch (Exception ex)
        {
            Debug.LogWarning("[Agent] Failed to clear chat history: " + ex.Message);
        }
    }

    private void DrawAgentBridgeSettings()
    {
        EditorGUILayout.BeginVertical(EditorStyles.helpBox);
        EditorGUILayout.LabelField("Chat Bridge Settings", EditorStyles.boldLabel);

        EditorGUILayout.BeginHorizontal();
        GUILayout.Label("Harness Root", GUILayout.Width(88));
        _agentHarnessRoot = EditorGUILayout.TextField(_agentHarnessRoot);
        if (GUILayout.Button("Browse", EditorStyles.miniButton, GUILayout.Width(56)))
        {
            string picked = EditorUtility.OpenFolderPanel("agent-harness Root", _agentHarnessRoot, "");
            if (!string.IsNullOrEmpty(picked))
                _agentHarnessRoot = picked;
        }
        if (GUILayout.Button("Detect", EditorStyles.miniButton, GUILayout.Width(52)))
            _agentHarnessRoot = TryDiscoverHarnessRoot();
        EditorGUILayout.EndHorizontal();

        EditorGUILayout.BeginHorizontal();
        GUILayout.Label("Python", GUILayout.Width(88));
        _agentPythonLauncher = EditorGUILayout.TextField(_agentPythonLauncher);
        if (GUILayout.Button("Browse", EditorStyles.miniButton, GUILayout.Width(56)))
        {
            string initialDir = "";
            try
            {
                if (!string.IsNullOrWhiteSpace(_agentPythonLauncher))
                    initialDir = Path.GetDirectoryName(UnquotePath(_agentPythonLauncher)) ?? "";
            }
            catch { }
            string picked = EditorUtility.OpenFilePanel("Python Executable", initialDir, "exe");
            if (!string.IsNullOrEmpty(picked))
                _agentPythonLauncher = picked;
        }
        EditorGUILayout.EndHorizontal();

        int providerIndex = Array.IndexOf(AgentProviderOptions, string.IsNullOrEmpty(_agentPreferredProvider) ? "auto" : _agentPreferredProvider);
        if (providerIndex < 0) providerIndex = 0;
        EditorGUILayout.BeginHorizontal();
        GUILayout.Label("Provider", GUILayout.Width(88));
        providerIndex = EditorGUILayout.Popup(providerIndex, AgentProviderOptions);
        _agentPreferredProvider = AgentProviderOptions[Mathf.Clamp(providerIndex, 0, AgentProviderOptions.Length - 1)];
        EditorGUILayout.EndHorizontal();

        EditorGUILayout.BeginHorizontal();
        GUILayout.Label("Model", GUILayout.Width(88));
        _agentPreferredModel = EditorGUILayout.TextField(_agentPreferredModel);
        EditorGUILayout.EndHorizontal();

        _agentAutoStartOnSend = EditorGUILayout.ToggleLeft("Auto-start bridge when sending while offline", _agentAutoStartOnSend);
        EditorGUILayout.LabelField("Launcher examples: py -3.12, py -3.11, python, or a full python.exe path.", EditorStyles.miniLabel);
        EditorGUILayout.LabelField("Model examples: gpt-5-codex, gpt-5.4, gpt-5.4-mini, claude-haiku-4-5-20251001.", EditorStyles.miniLabel);

        EditorGUILayout.BeginHorizontal();
        if (GUILayout.Button("Save Settings", EditorStyles.miniButton, GUILayout.Width(92)))
            SaveAgentBridgeSettings();
        using (new EditorGUI.DisabledScope(!_agentConnected))
        {
            if (GUILayout.Button("Connect Now", EditorStyles.miniButton, GUILayout.Width(92)))
                TryLaunchAgentBridge(true);
        }
        EditorGUILayout.EndHorizontal();

        if (!string.IsNullOrEmpty(_agentLastLaunchCommand))
            EditorGUILayout.HelpBox("Last launch: " + _agentLastLaunchCommand, MessageType.None);

        EditorGUILayout.EndVertical();
    }

    private void LoadAgentBridgeSettings()
    {
        _agentHarnessRoot = EditorPrefs.GetString(AgentHarnessRootPrefKey, "");
        _agentPythonLauncher = EditorPrefs.GetString(AgentPythonPrefKey, "");
        _agentAutoStartOnSend = EditorPrefs.GetBool(AgentAutoStartPrefKey, true);
        _agentLastLaunchCommand = EditorPrefs.GetString(AgentLastLaunchPrefKey, "");

        if (string.IsNullOrWhiteSpace(_agentHarnessRoot) || !IsHarnessRootValid(_agentHarnessRoot))
            _agentHarnessRoot = TryDiscoverHarnessRoot();
        if (string.IsNullOrWhiteSpace(_agentPythonLauncher))
            _agentPythonLauncher = "py -3.12";
        LoadAgentModelConfig();
    }

    private void SaveAgentBridgeSettings()
    {
        EditorPrefs.SetString(AgentHarnessRootPrefKey, _agentHarnessRoot ?? "");
        EditorPrefs.SetString(AgentPythonPrefKey, _agentPythonLauncher ?? "");
        EditorPrefs.SetBool(AgentAutoStartPrefKey, _agentAutoStartOnSend);
        EditorPrefs.SetString(AgentLastLaunchPrefKey, _agentLastLaunchCommand ?? "");
        SaveAgentModelConfig();
    }

    private string GetAgentConfigPath()
    {
        string projectRoot = Path.GetDirectoryName(Application.dataPath);
        return Path.Combine(projectRoot, ".umcp", "agent-config.json");
    }

    private void LoadAgentModelConfig()
    {
        _agentPreferredProvider = "auto";
        _agentPreferredModel = "";
        string configPath = GetAgentConfigPath();
        if (!File.Exists(configPath))
            return;
        try
        {
            string raw = File.ReadAllText(configPath);
            var data = StandaloneRouteHandler.MiniJson.Deserialize(raw);
            _agentPreferredProvider = data.ContainsKey("preferredProvider")
                ? (data["preferredProvider"]?.ToString() ?? "auto").ToLowerInvariant()
                : "auto";
            _agentPreferredModel = data.ContainsKey("preferredModel")
                ? data["preferredModel"]?.ToString() ?? ""
                : "";
            if (Array.IndexOf(AgentProviderOptions, _agentPreferredProvider) < 0)
                _agentPreferredProvider = "auto";
        }
        catch { }
    }

    private void SaveAgentModelConfig()
    {
        try
        {
            string configPath = GetAgentConfigPath();
            Directory.CreateDirectory(Path.GetDirectoryName(configPath) ?? "");
            var payload = new Dictionary<string, object>
            {
                { "preferredProvider", string.IsNullOrWhiteSpace(_agentPreferredProvider) ? "auto" : _agentPreferredProvider },
                { "preferredModel", (_agentPreferredModel ?? "").Trim() },
            };
            File.WriteAllText(configPath, StandaloneRouteHandler.MiniJson.Serialize(payload));
        }
        catch (Exception ex)
        {
            Debug.LogWarning("[Agent] Failed to save agent-config.json: " + ex.Message);
        }
    }

    private bool TryLaunchAgentBridge(bool userInitiated)
    {
        double now = EditorApplication.timeSinceStartup;
        if (_agentBridgeLive)
            return true;
        if (_agentLaunchPendingUntil > now)
        {
            _agentStatusSummary = "Starting chat bridge...";
            return true;
        }

        if (!_agentConnected)
        {
            _agentStatusSummary = "File IPC is offline. Start Unity with FileIPCBridge first.";
            return false;
        }

        if (string.IsNullOrWhiteSpace(_agentHarnessRoot) || !IsHarnessRootValid(_agentHarnessRoot))
            _agentHarnessRoot = TryDiscoverHarnessRoot();

        if (string.IsNullOrWhiteSpace(_agentHarnessRoot) || !IsHarnessRootValid(_agentHarnessRoot))
        {
            _showAgentBridgeSettings = true;
            _agentStatusSummary = "Set Harness Root to the cli-anything agent-harness repo.";
            if (userInitiated)
                EditorUtility.DisplayDialog("Bridge Launch Failed", "The CLI harness root could not be detected. Set Harness Root in the Agent tab settings.", "OK");
            return false;
        }

        string projectRoot = Path.GetDirectoryName(Application.dataPath);
        string lastError = "";
        foreach (var launcher in BuildAgentBridgeLaunchers())
        {
            if (TryStartAgentBridgeProcess(launcher, projectRoot, out lastError))
            {
                _agentStatusSummary = "Starting chat bridge...";
                _agentLaunchPendingUntil = now + 5.0;
                _agentLastRefresh = 0;
                SaveAgentBridgeSettings();
                return true;
            }
        }

        _showAgentBridgeSettings = true;
        _agentStatusSummary = lastError;
        SaveAgentBridgeSettings();
        if (userInitiated)
            EditorUtility.DisplayDialog("Bridge Launch Failed", lastError, "OK");
        return false;
    }

    private List<AgentBridgeLauncher> BuildAgentBridgeLaunchers()
    {
        var launchers = new List<AgentBridgeLauncher>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        void AddLauncher(string command)
        {
            if (!TryParseLauncher(command, out string executable, out string prefixArgs))
                return;
            string key = executable + "|" + prefixArgs;
            if (!seen.Add(key))
                return;
            launchers.Add(new AgentBridgeLauncher
            {
                executable = executable,
                prefixArgs = prefixArgs,
                displayName = string.IsNullOrWhiteSpace(prefixArgs) ? executable : executable + " " + prefixArgs,
            });
        }

        AddLauncher(_agentPythonLauncher);
        AddLauncher("py -3.12");
        AddLauncher("py -3.11");
        AddLauncher("python");
        return launchers;
    }

    private bool TryStartAgentBridgeProcess(AgentBridgeLauncher launcher, string projectRoot, out string error)
    {
        error = "";
        try
        {
            string projectArg = QuoteArgument(projectRoot.Replace("\\", "/"));
            string args = string.IsNullOrWhiteSpace(launcher.prefixArgs)
                ? "-m cli_anything.unity_mcp workflow agent-chat " + projectArg
                : launcher.prefixArgs + " -m cli_anything.unity_mcp workflow agent-chat " + projectArg;

            var psi = new System.Diagnostics.ProcessStartInfo
            {
                FileName = launcher.executable,
                Arguments = args,
                WorkingDirectory = _agentHarnessRoot,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = System.Diagnostics.ProcessWindowStyle.Hidden,
            };

            string existingPythonPath = Environment.GetEnvironmentVariable("PYTHONPATH") ?? "";
            psi.EnvironmentVariables["PYTHONPATH"] = string.IsNullOrWhiteSpace(existingPythonPath)
                ? _agentHarnessRoot
                : _agentHarnessRoot + Path.PathSeparator + existingPythonPath;

            var process = System.Diagnostics.Process.Start(psi);
            if (process == null)
            {
                error = "Failed to start the chat bridge process.";
                return false;
            }

            bool exited = process.WaitForExit(1200);
            _agentLastLaunchCommand = launcher.displayName + " " + args;
            if (exited)
            {
                error = $"Chat bridge exited immediately using `{launcher.displayName}` (code {process.ExitCode}).";
                return false;
            }
            return true;
        }
        catch (Exception ex)
        {
            error = $"Failed to launch chat bridge via `{launcher.displayName}`: {ex.Message}";
            return false;
        }
    }

    private static bool TryParseLauncher(string command, out string executable, out string prefixArgs)
    {
        executable = "";
        prefixArgs = "";
        if (string.IsNullOrWhiteSpace(command))
            return false;

        command = command.Trim();
        if (command.StartsWith("\"", StringComparison.Ordinal))
        {
            int endQuote = command.IndexOf('"', 1);
            if (endQuote > 1)
            {
                executable = command.Substring(1, endQuote - 1);
                prefixArgs = command.Substring(endQuote + 1).Trim();
                return !string.IsNullOrWhiteSpace(executable);
            }
        }

        int split = command.IndexOf(' ');
        if (split > 0)
        {
            executable = command.Substring(0, split).Trim();
            prefixArgs = command.Substring(split + 1).Trim();
        }
        else
        {
            executable = command;
        }
        return !string.IsNullOrWhiteSpace(executable);
    }

    private static string QuoteArgument(string value)
    {
        return "\"" + (value ?? "").Replace("\"", "\\\"") + "\"";
    }

    private static string UnquotePath(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return "";
        value = value.Trim();
        if (value.Length >= 2 && value[0] == '"' && value[value.Length - 1] == '"')
            return value.Substring(1, value.Length - 2);
        return value;
    }

    private static bool IsHarnessRootValid(string root)
    {
        if (string.IsNullOrWhiteSpace(root) || !Directory.Exists(root))
            return false;
        return File.Exists(Path.Combine(root, "setup.py"))
            && File.Exists(Path.Combine(root, "cli_anything", "unity_mcp", "unity_mcp_cli.py"));
    }

    private static string TryDiscoverHarnessRoot()
    {
        foreach (string envVar in new[] { "CLI_ANYTHING_UNITY_MCP_HARNESS_ROOT", "CLI_ANYTHING_UNITY_MCP_ROOT" })
        {
            string value = Environment.GetEnvironmentVariable(envVar);
            if (IsHarnessRootValid(value))
                return value;
        }

        foreach (string root in EnumerateHarnessSearchRoots())
        {
            string found = FindHarnessRoot(root, 5);
            if (!string.IsNullOrEmpty(found))
                return found;
        }
        return "";
    }

    private static IEnumerable<string> EnumerateHarnessSearchRoots()
    {
        string desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        if (!string.IsNullOrWhiteSpace(desktop))
            yield return desktop;

        string userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        if (!string.IsNullOrWhiteSpace(userProfile))
        {
            string oneDriveDesktop = Path.Combine(userProfile, "OneDrive", "Desktop");
            if (Directory.Exists(oneDriveDesktop))
                yield return oneDriveDesktop;
        }
    }

    private static string FindHarnessRoot(string root, int depth)
    {
        if (string.IsNullOrWhiteSpace(root) || !Directory.Exists(root) || depth < 0)
            return "";
        if (IsHarnessRootValid(root))
            return root;
        if (depth == 0)
            return "";

        try
        {
            foreach (string dir in Directory.GetDirectories(root))
            {
                string name = Path.GetFileName(dir);
                if (string.IsNullOrEmpty(name)
                    || name.StartsWith(".", StringComparison.Ordinal)
                    || name.Equals("Library", StringComparison.OrdinalIgnoreCase)
                    || name.Equals("node_modules", StringComparison.OrdinalIgnoreCase)
                    || name.Equals("Packages", StringComparison.OrdinalIgnoreCase)
                    || name.Equals("Temp", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                string found = FindHarnessRoot(dir, depth - 1);
                if (!string.IsNullOrEmpty(found))
                    return found;
            }
        }
        catch { }
        return "";
    }

    private static string EscapeJsonString(string s)
    {
        if (s == null) return "";
        return s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n").Replace("\r", "\\r").Replace("\t", "\\t");
    }

    // ── Overview Tab ─────────────────────────────────────────────────────

    private void DrawAssistantTab()
    {
        // Toolbar
        EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);
        GUILayout.Label("  Project Overview", EditorStyles.boldLabel);
        GUILayout.FlexibleSpace();
        bool needsRefresh = EditorApplication.timeSinceStartup - _overviewLastRefresh > 5.0;
        if (needsRefresh) GUI.backgroundColor = new Color(1f, 0.85f, 0.3f);
        if (GUILayout.Button("Refresh", EditorStyles.toolbarButton, GUILayout.Width(58)))
            RefreshOverview();
        GUI.backgroundColor = Color.white;
        EditorGUILayout.EndHorizontal();

        _overviewScroll = EditorGUILayout.BeginScrollView(_overviewScroll);

        // ── Scene stats ──────────────────────────────────────────────────────
        _showOvScene = DrawSectionHeader("Scene  ·  " + (_ovSceneName == "" ? "—" : _ovSceneName) + (_ovSceneDirty ? "  *unsaved*" : ""), _showOvScene);
        if (_showOvScene)
        {
            EditorGUILayout.BeginHorizontal();
            DrawOvMetric("Objects",   _ovObjects.ToString());
            DrawOvMetric("Scripts",   _ovScripts.ToString());
            DrawOvMetric("Prefabs",   _ovPrefabs.ToString());
            DrawOvMetric("Materials", _ovMaterials.ToString());
            DrawOvMetric("Textures",  _ovTextures.ToString());
            DrawOvMetric("Audio",     _ovAudio.ToString());
            EditorGUILayout.EndHorizontal();
        }

        GUILayout.Space(4);

        // ── Health checks ────────────────────────────────────────────────────
        _showOvHealth = DrawSectionHeader("Health", _showOvHealth);
        if (_showOvHealth)
        {
            DrawOvCheck(!_ovCompileErrors, "Compilation",  _ovCompileErrors  ? "Errors detected — check Console tab" : "Clean");
            DrawOvCheck(_ovMissingRefs == 0, "Missing refs", _ovMissingRefs == 0 ? "None found" : _ovMissingRefs + " missing script reference(s)");
            DrawOvCheck(!_ovSceneDirty, "Scene saved",    _ovSceneDirty ? "Unsaved changes" : "Saved");
            DrawOvCheck(!EditorApplication.isCompiling, "Compiling",   EditorApplication.isCompiling ? "Compiling…" : "Idle");
        }

        GUILayout.Space(4);

        // ── Quick actions ────────────────────────────────────────────────────
        _showOvActions = DrawSectionHeader("Quick Actions", _showOvActions);
        if (_showOvActions)
        {
            // Play mode row
            EditorGUILayout.BeginHorizontal();
            GUI.backgroundColor = EditorApplication.isPlaying ? new Color(1f,0.4f,0.4f) : new Color(0.4f,1f,0.5f);
            if (GUILayout.Button(EditorApplication.isPlaying ? "■  Stop" : "▶  Play", GUILayout.Height(26)))
                EditorApplication.isPlaying = !EditorApplication.isPlaying;
            GUI.backgroundColor = EditorApplication.isPaused ? new Color(1f,0.85f,0.3f) : Color.white;
            if (GUILayout.Button("⏸  Pause", GUILayout.Height(26), GUILayout.Width(80)))
                EditorApplication.isPaused = !EditorApplication.isPaused;
            GUI.backgroundColor = Color.white;
            EditorGUILayout.EndHorizontal();

            GUILayout.Space(3);

            // Scene ops row
            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("💾  Save Scene", GUILayout.Height(24)))
            {
                if (!EditorApplication.isPlaying) EditorSceneManager.SaveOpenScenes();
            }
            if (GUILayout.Button("📷  Screenshot", GUILayout.Height(24)))
            {
                string dir = Path.Combine(Application.dataPath, "..", "Screenshots");
                Directory.CreateDirectory(dir);
                string file = Path.Combine(dir, "Screenshot_" + DateTime.Now.ToString("yyyyMMdd_HHmmss") + ".png");
                ScreenCapture.CaptureScreenshot(file);
                ShowNotification(new GUIContent("Saved: " + Path.GetFileName(file)));
            }
            if (GUILayout.Button("🎯  Focus", GUILayout.Height(24), GUILayout.Width(70)))
            {
                if (Selection.activeGameObject != null)
                    SceneView.lastActiveSceneView?.FrameSelected();
            }
            EditorGUILayout.EndHorizontal();

            GUILayout.Space(3);

            // Object creation row
            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("+ Empty",    GUILayout.Height(22))) { var g = new GameObject("GameObject"); GameObjectUtility.EnsureUniqueNameForSibling(g); Undo.RegisterCreatedObjectUndo(g, "Create Empty"); Selection.activeGameObject = g; MarkDirty(); }
            if (GUILayout.Button("+ Cube",     GUILayout.Height(22))) CreatePrimAndSelect(PrimitiveType.Cube);
            if (GUILayout.Button("+ Sphere",   GUILayout.Height(22))) CreatePrimAndSelect(PrimitiveType.Sphere);
            if (GUILayout.Button("+ Plane",    GUILayout.Height(22))) CreatePrimAndSelect(PrimitiveType.Plane);
            if (GUILayout.Button("+ Light",    GUILayout.Height(22))) { var g = new GameObject("Directional Light"); var l = g.AddComponent<Light>(); l.type = LightType.Directional; l.intensity = 1f; g.transform.rotation = Quaternion.Euler(50,-30,0); GameObjectUtility.EnsureUniqueNameForSibling(g); Undo.RegisterCreatedObjectUndo(g, "Create Light"); Selection.activeGameObject = g; MarkDirty(); }
            if (GUILayout.Button("+ Camera",   GUILayout.Height(22))) { var g = new GameObject("Camera"); g.AddComponent<Camera>(); g.AddComponent<AudioListener>(); GameObjectUtility.EnsureUniqueNameForSibling(g); Undo.RegisterCreatedObjectUndo(g, "Create Camera"); Selection.activeGameObject = g; MarkDirty(); }
            EditorGUILayout.EndHorizontal();

            GUILayout.Space(3);

            // Utility row
            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("Clear Console", GUILayout.Height(22)))
            {
                lock (_consoleLogLock) { _consoleLogs.Clear(); _consoleTotalLog = _consoleTotalWarn = _consoleTotalError = 0; }
                _consoleSelectedLog = -1;
                var le = AppDomain.CurrentDomain.GetAssemblies()
                    .Select(a => { try { return a.GetType("UnityEditor.LogEntries"); } catch { return null; } })
                    .FirstOrDefault(t => t != null);
                le?.GetMethod("Clear", BindingFlags.Static | BindingFlags.Public)?.Invoke(null, null);
                Repaint();
            }
            if (GUILayout.Button("Open Test Runner", GUILayout.Height(22)))
                EditorApplication.ExecuteMenuItem("Window/General/Test Runner");
            if (GUILayout.Button("Undo", GUILayout.Height(22), GUILayout.Width(48)))
                Undo.PerformUndo();
            if (GUILayout.Button("Redo", GUILayout.Height(22), GUILayout.Width(48)))
                Undo.PerformRedo();
            EditorGUILayout.EndHorizontal();
        }

        GUILayout.Space(4);

        // ── Recent errors (from Console tab) ────────────────────────────────
        _showOvErrors = DrawSectionHeader("Recent Errors  (" + _consoleTotalError + ")", _showOvErrors);
        if (_showOvErrors)
        {
            if (_consoleTotalError == 0)
            {
                EditorGUILayout.HelpBox("No errors this session.", MessageType.None);
            }
            else
            {
                lock (_consoleLogLock)
                {
                    var errors = _consoleLogs
                        .Where(l => l.type == LogType.Error || l.type == LogType.Exception)
                        .TakeLast(8).ToList();
                    foreach (var log in errors)
                    {
                        EditorGUILayout.BeginVertical(EditorStyles.helpBox);
                        EditorGUILayout.BeginHorizontal();
                        GUILayout.Label(log.time, EditorStyles.miniLabel, GUILayout.Width(54));
                        GUILayout.Label(log.message, EditorStyles.wordWrappedMiniLabel);
                        EditorGUILayout.EndHorizontal();
                        if (!string.IsNullOrEmpty(log.stackTrace))
                        {
                            string firstLine = log.stackTrace.Split('\n').FirstOrDefault()?.Trim() ?? "";
                            if (!string.IsNullOrEmpty(firstLine))
                                GUILayout.Label(firstLine, EditorStyles.miniLabel);
                        }
                        EditorGUILayout.EndVertical();
                    }
                }
            }
        }

        EditorGUILayout.EndScrollView();

        // Auto-refresh on first draw
        if (_overviewLastRefresh == 0) RefreshOverview();
    }

    private void DrawOvMetric(string label, string value)
    {
        EditorGUILayout.BeginVertical(EditorStyles.helpBox, GUILayout.MinWidth(72));
        GUILayout.Label(value, _subHeaderStyle ?? EditorStyles.boldLabel);
        GUILayout.Label(label, EditorStyles.centeredGreyMiniLabel);
        EditorGUILayout.EndVertical();
    }

    private void DrawOvCheck(bool ok, string label, string detail)
    {
        EditorGUILayout.BeginHorizontal(EditorStyles.helpBox);
        GUI.color = ok ? new Color(0.4f, 1f, 0.5f) : new Color(1f, 0.5f, 0.3f);
        GUILayout.Label(ok ? "✓" : "✗", GUILayout.Width(16));
        GUI.color = Color.white;
        GUILayout.Label(label, EditorStyles.miniLabel, GUILayout.Width(90));
        GUILayout.Label(detail, EditorStyles.wordWrappedMiniLabel);
        EditorGUILayout.EndHorizontal();
    }

    private void CreatePrimAndSelect(PrimitiveType type)
    {
        var go = GameObject.CreatePrimitive(type);
        GameObjectUtility.EnsureUniqueNameForSibling(go);
        Undo.RegisterCreatedObjectUndo(go, "Create " + type);
        Selection.activeGameObject = go;
        MarkDirty();
    }

    private void RefreshOverview()
    {
        _overviewLastRefresh = EditorApplication.timeSinceStartup;
        var scene = SceneManager.GetActiveScene();
        _ovSceneName  = string.IsNullOrEmpty(scene.name) ? "Untitled" : scene.name;
        _ovSceneDirty = scene.isDirty;

        // Count scene objects
        if (scene.isLoaded)
        {
            var roots = scene.GetRootGameObjects();
            int total = 0;
            var stack = new Stack<Transform>();
            foreach (var r in roots) stack.Push(r.transform);
            while (stack.Count > 0) { var t = stack.Pop(); total++; foreach (Transform c in t) stack.Push(c); }
            _ovObjects = total;
        }

        // Asset counts
        _ovScripts   = AssetDatabase.FindAssets("t:MonoScript",  new[] { "Assets" }).Length;
        _ovPrefabs   = AssetDatabase.FindAssets("t:Prefab",      new[] { "Assets" }).Length;
        _ovMaterials = AssetDatabase.FindAssets("t:Material",    new[] { "Assets" }).Length;
        _ovTextures  = AssetDatabase.FindAssets("t:Texture2D",   new[] { "Assets" }).Length;
        _ovAudio     = AssetDatabase.FindAssets("t:AudioClip",   new[] { "Assets" }).Length;

        // Compile errors
        _ovCompileErrors = _consoleTotalError > 0;

        // Missing references (check loaded scene GameObjects)
        _ovMissingRefs = 0;
        if (scene.isLoaded)
        {
            foreach (var go in Resources.FindObjectsOfTypeAll<GameObject>())
            {
                if (!go.scene.IsValid() || !go.scene.isLoaded) continue;
                foreach (var comp in go.GetComponents<Component>())
                    if (comp == null) _ovMissingRefs++;
            }
        }

        Repaint();
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

        // Rebuild editor cache when selection changes
        if (_selected != _lastInspectedGo)
        {
            CleanupComponentEditors();
            _lastInspectedGo = _selected;
        }

        // Transform — native editor
        _showTransform = DrawSectionHeader("Transform", _showTransform);
        if (_showTransform)
            DrawNativeComponentEditor(_selected.transform);

        GUILayout.Space(6);

        // Other components — native editors
        var components = _selected.GetComponents<Component>()
            .Where(c => c != null && !(c is Transform)).ToArray();
        _showComponents = DrawSectionHeader($"Components  ({components.Length})", _showComponents);
        if (_showComponents)
        {
            foreach (var comp in components)
            {
                // Component header row
                EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);
                var icon = EditorGUIUtility.ObjectContent(comp, comp.GetType()).image;
                if (icon != null) GUILayout.Label(new GUIContent(icon), GUILayout.Width(16), GUILayout.Height(16));
                GUILayout.Label(comp.GetType().Name, _labelBoldStyle);
                GUILayout.FlexibleSpace();

                if (comp is Behaviour beh)
                {
                    EditorGUI.BeginChangeCheck();
                    bool en = EditorGUILayout.Toggle(beh.enabled, GUILayout.Width(16));
                    if (EditorGUI.EndChangeCheck())
                    { Undo.RecordObject(beh, "Toggle Component"); beh.enabled = en; }
                }

                if (GUILayout.Button("⋯", EditorStyles.miniButton, GUILayout.Width(24)))
                {
                    var captured = comp;
                    var menu = new GenericMenu();
                    menu.AddItem(new GUIContent("Remove Component"), false, () =>
                    {
                        Undo.DestroyObjectImmediate(captured);
                        CleanupComponentEditors();
                        MarkDirty();
                        Repaint();
                    });
                    menu.AddItem(new GUIContent("Reset"), false, () =>
                    {
                        // Unity doesn't expose a direct reset; re-create editor to refresh
                        CleanupComponentEditors();
                        Repaint();
                    });
                    menu.ShowAsContext();
                }
                EditorGUILayout.EndHorizontal();

                // Full native property editor
                EditorGUILayout.BeginVertical(EditorStyles.helpBox);
                DrawNativeComponentEditor(comp);
                EditorGUILayout.EndVertical();
                GUILayout.Space(2);
            }

            GUILayout.Space(6);
            EditorGUILayout.BeginHorizontal();
            _newComponentName = EditorGUILayout.TextField(_newComponentName, EditorStyles.toolbarSearchField);
            if (GUILayout.Button("Add Component", EditorStyles.miniButton, GUILayout.Width(100)))
                if (!string.IsNullOrEmpty(_newComponentName))
                    TryAddComponent(_selected, _newComponentName);
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
        _sceneObjectCount = FindObjectsByType<GameObject>(FindObjectsInactive.Exclude).Length;
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
            FindObjectsByType<GameObject>(FindObjectsInactive.Exclude)
                .Where(g => g.name.IndexOf(query, StringComparison.OrdinalIgnoreCase) >= 0)
                .OrderBy(g => g.name)
        );
    }

    private void RefreshSceneStats()
    {
        _statObjects = FindObjectsByType<GameObject>(FindObjectsInactive.Exclude).Length;
        _statCameras = FindObjectsByType<Camera>(FindObjectsInactive.Exclude).Length;
        _statLights = FindObjectsByType<Light>(FindObjectsInactive.Exclude).Length;
        _statColliders = FindObjectsByType<Collider>(FindObjectsInactive.Exclude).Length;
        _statRigidbodies = FindObjectsByType<Rigidbody>(FindObjectsInactive.Exclude).Length;
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
            CleanupComponentEditors();
            MarkDirty();
            ShowNotification(new GUIContent($"Added {type.Name}"));
        }
        else
        {
            ShowNotification(new GUIContent($"Type '{typeName}' not found"));
        }
    }

    // ── Component editor cache ───────────────────────────────────────────

    private void CleanupComponentEditors()
    {
        foreach (var e in _componentEditors.Values)
            if (e != null) DestroyImmediate(e);
        _componentEditors.Clear();
    }

    private void DrawNativeComponentEditor(Component comp)
    {
        int id = comp.GetInstanceID();
        if (!_componentEditors.TryGetValue(id, out var editor) || editor == null)
        {
            editor = Editor.CreateEditor(comp);
            _componentEditors[id] = editor;
        }
        if (editor == null) return;
        EditorGUI.indentLevel++;
        try { editor.OnInspectorGUI(); }
        catch { /* suppress layout errors on first frame after selection change */ }
        EditorGUI.indentLevel--;
    }

    // ── Hierarchy context menu ───────────────────────────────────────────

    private void ShowHierarchyContextMenu(GameObject go)
    {
        var menu = new GenericMenu();
        menu.AddItem(new GUIContent("Inspect"), false, () => { _tab = 2; SelectObject(go); });
        menu.AddItem(new GUIContent("Focus in Scene View"), false, () =>
        {
            Selection.activeGameObject = go;
            SceneView.FrameLastActiveSceneView();
        });
        menu.AddSeparator("");
        menu.AddItem(new GUIContent("Duplicate"), false, () =>
        {
            var copy = Instantiate(go);
            copy.name = go.name + "_Copy";
            Undo.RegisterCreatedObjectUndo(copy, "Duplicate");
            MarkDirty();
            SelectObject(copy);
        });
        menu.AddItem(new GUIContent("Create Child"), false, () =>
        {
            var child = new GameObject("Child");
            child.transform.SetParent(go.transform, false);
            Undo.RegisterCreatedObjectUndo(child, "Create Child");
            MarkDirty();
            SelectObject(child);
        });
        menu.AddItem(new GUIContent("Toggle Active"), false, () =>
        {
            Undo.RecordObject(go, "Toggle Active");
            go.SetActive(!go.activeSelf);
        });
        menu.AddSeparator("");
        menu.AddItem(new GUIContent("Delete"), false, () =>
        {
            if (EditorUtility.DisplayDialog("Delete", $"Delete '{go.name}'?", "Delete", "Cancel"))
            {
                Undo.DestroyObjectImmediate(go);
                if (_selected == go) _selected = null;
                MarkDirty();
            }
        });
        menu.ShowAsContext();
    }

    // ── Console log capture ──────────────────────────────────────────────

    private void CaptureConsoleLog(string message, string stackTrace, LogType type)
    {
        lock (_consoleLogLock)
        {
            if (_consoleLogs.Count >= MaxConsoleLogs)
                _consoleLogs.RemoveAt(0);
            _consoleLogs.Add(new ConsoleEntry
            {
                message    = message,
                stackTrace = stackTrace,
                type       = type,
                time       = DateTime.Now.ToString("HH:mm:ss"),
            });
            switch (type)
            {
                case LogType.Warning:
                case LogType.Assert:
                    _consoleTotalWarn++;
                    break;
                case LogType.Error:
                case LogType.Exception:
                    _consoleTotalError++;
                    break;
                default:
                    _consoleTotalLog++;
                    break;
            }
        }
        Repaint();
    }

    // ── Console Tab ──────────────────────────────────────────────────────

    private void DrawConsoleTab()
    {
        // Toolbar
        EditorGUILayout.BeginHorizontal(EditorStyles.toolbar);

        if (GUILayout.Button("Clear", EditorStyles.toolbarButton, GUILayout.Width(44)))
        {
            lock (_consoleLogLock)
            {
                _consoleLogs.Clear();
                _consoleTotalLog = _consoleTotalWarn = _consoleTotalError = 0;
            }
            _consoleSelectedLog = -1;
        }

        GUILayout.Space(6);

        GUI.color = _consoleShowLog ? Color.white : new Color(0.6f, 0.6f, 0.6f);
        _consoleShowLog = GUILayout.Toggle(_consoleShowLog,
            $"Log  {_consoleTotalLog}", EditorStyles.toolbarButton, GUILayout.Width(68));

        GUI.color = _consoleShowWarning ? new Color(1f, 0.88f, 0.3f) : new Color(0.6f, 0.6f, 0.6f);
        _consoleShowWarning = GUILayout.Toggle(_consoleShowWarning,
            $"Warn  {_consoleTotalWarn}", EditorStyles.toolbarButton, GUILayout.Width(74));

        GUI.color = _consoleShowError ? new Color(1f, 0.45f, 0.45f) : new Color(0.6f, 0.6f, 0.6f);
        _consoleShowError = GUILayout.Toggle(_consoleShowError,
            $"Error  {_consoleTotalError}", EditorStyles.toolbarButton, GUILayout.Width(74));

        GUI.color = Color.white;
        GUILayout.FlexibleSpace();

        GUILayout.Label("Search", EditorStyles.miniLabel, GUILayout.Width(40));
        _consoleSearch = EditorGUILayout.TextField(_consoleSearch,
            EditorStyles.toolbarSearchField, GUILayout.Width(130));
        if (GUILayout.Button("✕", EditorStyles.toolbarButton, GUILayout.Width(20)))
            _consoleSearch = "";

        _consoleAutoScroll = GUILayout.Toggle(_consoleAutoScroll,
            "Auto-scroll", EditorStyles.toolbarButton, GUILayout.Width(78));

        EditorGUILayout.EndHorizontal();

        // Build visible list
        List<ConsoleEntry> snapshot;
        lock (_consoleLogLock) snapshot = new List<ConsoleEntry>(_consoleLogs);

        var visible = snapshot.Where(e =>
        {
            bool typeOk = (e.type == LogType.Log && _consoleShowLog)
                       || ((e.type == LogType.Warning || e.type == LogType.Assert) && _consoleShowWarning)
                       || ((e.type == LogType.Error   || e.type == LogType.Exception) && _consoleShowError);
            bool searchOk = string.IsNullOrEmpty(_consoleSearch)
                         || e.message.IndexOf(_consoleSearch, StringComparison.OrdinalIgnoreCase) >= 0;
            return typeOk && searchOk;
        }).ToList();

        if (visible.Count == 0 && snapshot.Count == 0)
        {
            GUILayout.FlexibleSpace();
            EditorGUILayout.BeginHorizontal(); GUILayout.FlexibleSpace();
            GUILayout.Label("No log entries yet.\nPlay the game or trigger editor actions to see output here.",
                EditorStyles.centeredGreyMiniLabel);
            GUILayout.FlexibleSpace(); EditorGUILayout.EndHorizontal();
            GUILayout.FlexibleSpace();
            return;
        }

        // Log list — top 65% of available height
        float listHeight = Mathf.Max(80, (position.height - 120) * 0.62f);
        _consoleScroll = EditorGUILayout.BeginScrollView(_consoleScroll, GUILayout.Height(listHeight));

        for (int i = 0; i < visible.Count; i++)
        {
            var entry  = visible[i];
            bool isSel = _consoleSelectedLog == i;
            var style  = isSel ? _selectedRowStyle : _rowStyle;

            Rect row = GUILayoutUtility.GetRect(GUIContent.none, style, GUILayout.Height(20));

            if (Event.current.type == EventType.MouseDown && row.Contains(Event.current.mousePosition))
            { _consoleSelectedLog = i; Event.current.Use(); }

            if (Event.current.type == EventType.Repaint)
            {
                style.Draw(row, false, isSel, isSel, false);

                // Type icon
                GUI.color = ConsoleEntryColor(entry.type);
                GUI.Label(new Rect(row.x + 3, row.y + 3, 14, 14), ConsoleEntryIcon(entry.type), EditorStyles.miniLabel);
                GUI.color = Color.white;

                // Timestamp
                GUI.Label(new Rect(row.x + 20, row.y, 62, row.height), entry.time, EditorStyles.miniLabel);

                // Message (single line, truncated)
                string msg = entry.message.Length > 300
                    ? entry.message.Substring(0, 297) + "…"
                    : entry.message;
                msg = msg.Replace("\n", " ↵ ");
                EditorStyles.label.Draw(
                    new Rect(row.x + 84, row.y, row.width - 88, row.height),
                    msg, false, false, isSel, false);
            }
        }

        if (_consoleAutoScroll && Event.current.type == EventType.Repaint)
            _consoleScroll.y = float.MaxValue;

        EditorGUILayout.EndScrollView();

        // Divider + detail pane
        EditorGUILayout.LabelField("", GUI.skin.horizontalSlider);

        if (_consoleSelectedLog >= 0 && _consoleSelectedLog < visible.Count)
        {
            var entry = visible[_consoleSelectedLog];

            EditorGUILayout.BeginHorizontal();
            GUI.color = ConsoleEntryColor(entry.type);
            GUILayout.Label(ConsoleEntryIcon(entry.type), GUILayout.Width(16));
            GUI.color = Color.white;
            GUILayout.Label(entry.message, EditorStyles.wordWrappedMiniLabel, GUILayout.ExpandWidth(true));
            if (GUILayout.Button("Copy", EditorStyles.miniButton, GUILayout.Width(40)))
                GUIUtility.systemCopyBuffer = entry.message + (string.IsNullOrEmpty(entry.stackTrace)
                    ? "" : "\n\n" + entry.stackTrace);
            EditorGUILayout.EndHorizontal();

            if (!string.IsNullOrEmpty(entry.stackTrace))
            {
                _consoleStackScroll = EditorGUILayout.BeginScrollView(
                    _consoleStackScroll, GUILayout.ExpandHeight(true));
                GUILayout.Label(entry.stackTrace, EditorStyles.miniLabel);
                EditorGUILayout.EndScrollView();
            }
        }
        else
        {
            GUILayout.Label("Select a log entry to see its stack trace.",
                EditorStyles.centeredGreyMiniLabel);
        }
    }

    private static Color ConsoleEntryColor(LogType t)
    {
        switch (t)
        {
            case LogType.Warning:
            case LogType.Assert:   return new Color(1f, 0.88f, 0.25f);
            case LogType.Error:
            case LogType.Exception: return new Color(1f, 0.42f, 0.42f);
            default:               return new Color(0.75f, 0.75f, 0.75f);
        }
    }

    private static string ConsoleEntryIcon(LogType t)
    {
        switch (t)
        {
            case LogType.Warning:
            case LogType.Assert:   return "⚠";
            case LogType.Error:
            case LogType.Exception: return "✕";
            default:               return "●";
        }
    }

    // ── Bridge Tab ───────────────────────────────────────────────────────

    private void DrawBridgeTab()
    {
        _bridgeScroll = EditorGUILayout.BeginScrollView(_bridgeScroll);
        RefreshBridgeStatusIfStale();

        // ── HTTP Bridge ──────────────────────────────────────────────────
        _showHttpSection = DrawSectionHeader("HTTP Bridge", _showHttpSection);
        if (_showHttpSection)
        {
            EditorGUILayout.BeginHorizontal(EditorStyles.helpBox);
            GUI.color = _bridgeRunning ? new Color(0.3f, 0.9f, 0.3f) : new Color(0.9f, 0.5f, 0.3f);
            GUILayout.Label(_bridgeRunning ? "● Running" : "○ Stopped", _labelBoldStyle, GUILayout.Width(86));
            GUI.color = Color.white;
            if (_bridgeRunning)
                GUILayout.Label("Port: " + _bridgePort, EditorStyles.miniLabel);
            GUILayout.FlexibleSpace();

            GUI.backgroundColor = _bridgeRunning ? new Color(0.9f, 0.4f, 0.3f) : new Color(0.3f, 0.8f, 0.3f);
            if (GUILayout.Button(_bridgeRunning ? "Stop Bridge" : "Start Bridge", EditorStyles.miniButton, GUILayout.Width(88)))
            {
                ToggleBridge(_bridgeRunning);
                _lastBridgeRefresh = 0; // force refresh next frame
            }
            GUI.backgroundColor = Color.white;
            EditorGUILayout.EndHorizontal();

            if (_bridgeRunning)
            {
                EditorGUILayout.BeginHorizontal();
                string url = "http://localhost:" + _bridgePort;
                EditorGUILayout.SelectableLabel(url, EditorStyles.textField, GUILayout.Height(18));
                if (GUILayout.Button("Copy", EditorStyles.miniButton, GUILayout.Width(40)))
                    GUIUtility.systemCopyBuffer = url;
                EditorGUILayout.EndHorizontal();
            }
            GUILayout.Space(4);
        }

        // ── File IPC ─────────────────────────────────────────────────────
        _showFileIpcSection = DrawSectionHeader("File IPC Bridge", _showFileIpcSection);
        if (_showFileIpcSection)
        {
            EditorGUILayout.BeginHorizontal(EditorStyles.helpBox);
            Color ipcColor = _fileIpcStatus == "Active"   ? new Color(0.3f, 0.7f, 1f)
                           : _fileIpcStatus == "Stale"    ? new Color(1f, 0.7f, 0.2f)
                                                          : new Color(0.6f, 0.6f, 0.6f);
            GUI.color = ipcColor;
            GUILayout.Label("● " + _fileIpcStatus, _labelBoldStyle, GUILayout.Width(80));
            GUI.color = Color.white;
            if (!string.IsNullOrEmpty(_fileIpcHeartbeat))
                GUILayout.Label("Last heartbeat: " + _fileIpcHeartbeat, EditorStyles.miniLabel);
            GUILayout.FlexibleSpace();
            EditorGUILayout.EndHorizontal();

            string pingPath = Path.Combine(
                Directory.GetParent(Application.dataPath)?.FullName ?? Application.dataPath,
                ".umcp", "ping.json");
            EditorGUILayout.BeginHorizontal();
            EditorGUILayout.SelectableLabel(pingPath, EditorStyles.miniTextField, GUILayout.Height(16));
            if (GUILayout.Button("Copy", EditorStyles.miniButton, GUILayout.Width(40)))
                GUIUtility.systemCopyBuffer = pingPath;
            EditorGUILayout.EndHorizontal();

            GUILayout.Space(4);
            EditorGUILayout.HelpBox(
                "Drop FileIPCBridge.cs + StandaloneRouteHandler.cs into Assets/Editor/ " +
                "and the bridge auto-starts. The CLI uses --transport file --file-ipc-path <ProjectRoot>.",
                MessageType.Info);
            GUILayout.Space(4);
        }

        // ── Route Explorer ───────────────────────────────────────────────
        _showRouteExplorer = DrawSectionHeader("Route Explorer", _showRouteExplorer);
        if (_showRouteExplorer)
        {
            // Quick-route buttons
            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("ping",         EditorStyles.miniButton)) SetRoute("ping",          "{}");
            if (GUILayout.Button("scene/info",   EditorStyles.miniButton)) SetRoute("scene/info",    "{}");
            if (GUILayout.Button("editor/state", EditorStyles.miniButton)) SetRoute("editor/state",  "{}");
            if (GUILayout.Button("project/info", EditorStyles.miniButton)) SetRoute("project/info",  "{}");
            EditorGUILayout.EndHorizontal();

            EditorGUILayout.BeginHorizontal();
            if (GUILayout.Button("scene/hierarchy",     EditorStyles.miniButton)) SetRoute("scene/hierarchy",     "{}");
            if (GUILayout.Button("scene/stats",         EditorStyles.miniButton)) SetRoute("scene/stats",         "{}");
            if (GUILayout.Button("compilation/errors",  EditorStyles.miniButton)) SetRoute("compilation/errors",  "{}");
            if (GUILayout.Button("asset/list",          EditorStyles.miniButton)) SetRoute("asset/list",          "{\"folder\":\"Assets\"}");
            EditorGUILayout.EndHorizontal();

            GUILayout.Space(4);

            // Route + Params inputs
            EditorGUILayout.BeginHorizontal();
            GUILayout.Label("Route", GUILayout.Width(42));
            _routeInput = EditorGUILayout.TextField(_routeInput);
            EditorGUILayout.EndHorizontal();

            EditorGUILayout.BeginHorizontal();
            GUILayout.Label("Params", GUILayout.Width(42));
            _routeParams = EditorGUILayout.TextField(_routeParams);
            EditorGUILayout.EndHorizontal();

            GUILayout.Space(4);

            EditorGUILayout.BeginHorizontal();
            GUI.backgroundColor = new Color(0.3f, 0.6f, 1f);
            if (GUILayout.Button("▶  Call Route", _bigButtonStyle, GUILayout.Height(28)))
                CallRouteExplorer();
            GUI.backgroundColor = Color.white;
            if (GUILayout.Button("Clear", EditorStyles.miniButton, GUILayout.Width(44)))
                _routeResult = "";
            EditorGUILayout.EndHorizontal();

            GUILayout.Space(4);

            if (!string.IsNullOrEmpty(_routeResult))
            {
                EditorGUILayout.BeginHorizontal(EditorStyles.helpBox);
                GUILayout.Label("Result", EditorStyles.miniLabel, GUILayout.Width(38));
                GUILayout.FlexibleSpace();
                if (GUILayout.Button("Copy", EditorStyles.miniButton, GUILayout.Width(40)))
                    GUIUtility.systemCopyBuffer = _routeResult;
                EditorGUILayout.EndHorizontal();

                float resultHeight = Mathf.Min(220, EditorStyles.wordWrappedMiniLabel.CalcHeight(
                    new GUIContent(_routeResult), EditorGUIUtility.currentViewWidth - 24));
                EditorGUILayout.SelectableLabel(_routeResult, EditorStyles.wordWrappedMiniLabel,
                    GUILayout.ExpandWidth(true), GUILayout.Height(resultHeight + 8));
            }
            GUILayout.Space(4);
        }

        EditorGUILayout.EndScrollView();
    }

    private void SetRoute(string route, string paramsJson)
    {
        _routeInput  = route;
        _routeParams = paramsJson;
        _routeResult = "";
    }

    private void CallRouteExplorer()
    {
        try
        {
            // Try StandaloneRouteHandler first (always available)
            var handlerType = Type.GetType("StandaloneRouteHandler") ??
                AppDomain.CurrentDomain.GetAssemblies()
                    .Select(a => { try { return a.GetType("StandaloneRouteHandler"); } catch { return null; } })
                    .FirstOrDefault(t => t != null);

            if (handlerType != null)
            {
                var handleMethod = handlerType.GetMethod("Handle",
                    BindingFlags.Public | BindingFlags.Static,
                    null, new[] { typeof(string), typeof(string) }, null);

                if (handleMethod != null)
                {
                    object result = handleMethod.Invoke(null, new object[] { _routeInput, _routeParams });
                    _routeResult = result != null ? SerializeResult(result) : "(null)";
                    return;
                }
            }

            _routeResult = "StandaloneRouteHandler not found. Make sure StandaloneRouteHandler.cs is in Assets/Editor/.";
        }
        catch (Exception ex)
        {
            _routeResult = "Error: " + (ex.InnerException?.Message ?? ex.Message);
        }
    }

    private static string SerializeResult(object obj)
    {
        if (obj is string s) return s;

        // Try StandaloneRouteHandler.MiniJson.Serialize if available
        var miniJsonType = AppDomain.CurrentDomain.GetAssemblies()
            .Select(a => { try { return a.GetType("StandaloneRouteHandler+MiniJson"); } catch { return null; } })
            .FirstOrDefault(t => t != null);

        if (miniJsonType != null)
        {
            var serializeMethod = miniJsonType.GetMethod("Serialize",
                BindingFlags.Public | BindingFlags.Static);
            if (serializeMethod != null)
            {
                try { return (string)serializeMethod.Invoke(null, new[] { obj }); }
                catch { /* fall through */ }
            }
        }

        return obj.ToString();
    }

    // ── Bridge reflection helpers ─────────────────────────────────────────

    private static Type FindBridgeType()
    {
        string[] candidates = { "UnityMCP.Editor.MCPBridgeServer", "MCPBridgeServer" };
        foreach (string name in candidates)
        {
            var t = Type.GetType(name) ??
                AppDomain.CurrentDomain.GetAssemblies()
                    .Select(a => { try { return a.GetType(name); } catch { return null; } })
                    .FirstOrDefault(t2 => t2 != null);
            if (t != null) return t;
        }
        return null;
    }

    private static bool BridgeIsRunning()
    {
        var t = FindBridgeType();
        if (t == null) return false;
        try
        {
            var prop = t.GetProperty("IsRunning", BindingFlags.Public | BindingFlags.Static);
            if (prop != null) return (bool)prop.GetValue(null);
            var field = t.GetField("IsRunning", BindingFlags.Public | BindingFlags.Static);
            if (field != null) return (bool)field.GetValue(null);
        }
        catch { }
        return false;
    }

    private static int BridgeActivePort()
    {
        var t = FindBridgeType();
        if (t == null) return 0;
        try
        {
            var prop = t.GetProperty("ActivePort", BindingFlags.Public | BindingFlags.Static);
            if (prop != null) return (int)prop.GetValue(null);
            var field = t.GetField("ActivePort", BindingFlags.Public | BindingFlags.Static);
            if (field != null) return (int)field.GetValue(null);
        }
        catch { }
        return 0;
    }

    private static void ToggleBridge(bool currentlyRunning)
    {
        var t = FindBridgeType();
        if (t == null)
        {
            EditorUtility.DisplayDialog("Bridge Not Found",
                "MCPBridgeServer type not found. Is the Unity MCP plugin installed?", "OK");
            return;
        }
        try
        {
            string methodName = currentlyRunning ? "Stop" : "Start";
            var method = t.GetMethod(methodName, BindingFlags.Public | BindingFlags.Static);
            method?.Invoke(null, null);
        }
        catch (Exception ex)
        {
            EditorUtility.DisplayDialog("Bridge Error", ex.InnerException?.Message ?? ex.Message, "OK");
        }
    }

    private void RefreshBridgeStatusIfStale()
    {
        double now = EditorApplication.timeSinceStartup;
        if (now - _lastBridgeRefresh < 2.0) return;
        _lastBridgeRefresh = now;

        _bridgeRunning = BridgeIsRunning();
        _bridgePort    = BridgeActivePort();

        // File IPC ping.json
        string projectRoot = Directory.GetParent(Application.dataPath)?.FullName ?? Application.dataPath;
        string pingPath = Path.Combine(projectRoot, ".umcp", "ping.json");
        try
        {
            if (!File.Exists(pingPath))
            {
                _fileIpcStatus = "Not found";
                _fileIpcHeartbeat = "";
                return;
            }
            string text = File.ReadAllText(pingPath);
            // Extract lastHeartbeat via simple string search (no JSON dependency)
            int hbIdx = text.IndexOf("\"lastHeartbeat\"", StringComparison.Ordinal);
            if (hbIdx < 0)
            {
                _fileIpcStatus = "Active";
                _fileIpcHeartbeat = "";
                return;
            }
            int colon = text.IndexOf(':', hbIdx);
            int q1    = text.IndexOf('"', colon);
            int q2    = text.IndexOf('"', q1 + 1);
            string hbStr = (q1 >= 0 && q2 > q1) ? text.Substring(q1 + 1, q2 - q1 - 1) : "";

            if (!string.IsNullOrEmpty(hbStr) && DateTime.TryParse(hbStr,
                null, System.Globalization.DateTimeStyles.RoundtripKind, out DateTime hbTime))
            {
                double ageSec = (DateTime.UtcNow - hbTime.ToUniversalTime()).TotalSeconds;
                _fileIpcStatus    = ageSec <= 10.0 ? "Active" : "Stale";
                _fileIpcHeartbeat = hbTime.ToLocalTime().ToString("HH:mm:ss") +
                                    (ageSec > 10 ? $"  ({(int)ageSec}s ago)" : "");
            }
            else
            {
                _fileIpcStatus = "Active";
                _fileIpcHeartbeat = "";
            }
        }
        catch
        {
            _fileIpcStatus = "Error";
            _fileIpcHeartbeat = "";
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

        _agentUserBubbleStyle = BuildAgentBubbleStyle(new Color(0.15f, 0.32f, 0.47f, 1f), new Color(0.94f, 0.97f, 1f));
        _agentAiBubbleStyle = BuildAgentBubbleStyle(new Color(0.22f, 0.22f, 0.22f, 1f), new Color(0.94f, 0.94f, 0.94f));
        _agentSystemBubbleStyle = BuildAgentBubbleStyle(new Color(0.18f, 0.18f, 0.18f, 1f), new Color(0.70f, 0.70f, 0.70f));

        _agentRoleStyle = new GUIStyle(EditorStyles.miniBoldLabel)
        {
            normal = { textColor = new Color(0.58f, 0.82f, 1f) }
        };

        _agentTimestampStyle = new GUIStyle(EditorStyles.miniLabel)
        {
            alignment = TextAnchor.MiddleRight,
            normal = { textColor = new Color(0.6f, 0.6f, 0.6f) }
        };
    }

    private GUIStyle BuildAgentBubbleStyle(Color background, Color foreground)
    {
        return new GUIStyle(EditorStyles.helpBox)
        {
            wordWrap = true,
            fontSize = 11,
            padding = new RectOffset(10, 10, 8, 8),
            margin = new RectOffset(6, 6, 4, 4),
            normal =
            {
                background = MakeTex(1, 1, background),
                textColor = foreground,
            }
        };
    }

    private static string FormatAgentTimestamp(string timestamp)
    {
        if (DateTime.TryParse(timestamp, out DateTime parsed))
            return parsed.ToLocalTime().ToString("HH:mm:ss");
        return timestamp;
    }

    private static Texture2D MakeTex(int w, int h, Color col)
    {
        var tex = new Texture2D(w, h);
        tex.SetPixel(0, 0, col);
        tex.Apply();
        return tex;
    }
}
