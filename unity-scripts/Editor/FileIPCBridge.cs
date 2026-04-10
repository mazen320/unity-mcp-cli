/*
 * FileIPCBridge.cs — File-based IPC bridge for cli-anything-unity-mcp
 *
 * Drop this file into Assets/Editor/ in any Unity project.
 * It polls .umcp/inbox/ for command JSON files on the main thread
 * via EditorApplication.update, dispatches them to the existing
 * Unity MCP plugin routes (if installed), writes responses to
 * .umcp/outbox/, and refreshes a heartbeat in .umcp/ping.json.
 *
 * If the full Unity MCP plugin is NOT installed, this bridge
 * falls back to StandaloneRouteHandler for ~20 core routes.
 *
 * Zero network, zero port config, zero threading issues.
 * Everything runs on Unity's main thread automatically.
 */

using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using UnityEditor;
using UnityEngine;

[InitializeOnLoad]
public static class FileIPCBridge
{
    private static readonly string ProjectRoot;
    private static readonly string UmcpRoot;
    private static readonly string InboxPath;
    private static readonly string OutboxPath;
    private static readonly string PingPath;

    private static double _lastHeartbeat;
    private static double _lastPoll;

    // Poll inbox every 100ms, heartbeat every 2s
    private const double PollInterval = 0.1;
    private const double HeartbeatInterval = 2.0;
    private const string BridgeVersion = "standalone-first-v3";
    private const int MaxAgentActions = 200;

    // Cached reflection for plugin route dispatch
    private static MethodInfo _pluginDispatchMethod;
    private static bool _pluginChecked;
    private static readonly Dictionary<string, AgentSessionInfo> AgentSessions = new Dictionary<string, AgentSessionInfo>();
    private static readonly List<AgentActionInfo> AgentActions = new List<AgentActionInfo>();
    private static readonly HashSet<string> StandaloneOwnedRoutes = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "ping",
        "scene/info",
        "scene/hierarchy",
        "scene/save",
        "scene/new",
        "scene/stats",
        "search/scene-stats",
        "project/info",
        "context",
        "editor/state",
        "editor/play-mode",
        "editor/execute-menu-item",
        "debug/breadcrumb",
        "compilation/errors",
        "console/log",
        "console/clear",
        "search/missing-references",
        "gameobject/create",
        "gameobject/delete",
        "gameobject/info",
        "gameobject/set-active",
        "gameobject/set-transform",
        "component/add",
        "component/get-properties",
        "asset/list",
        "script/create",
        "script/read",
        "undo/perform",
        "undo/redo",
        "redo/perform",
        "graphics/game-capture",
        "graphics/scene-capture",
        "screenshot/game",
    };

    static FileIPCBridge()
    {
        ProjectRoot = Path.GetDirectoryName(Application.dataPath);
        UmcpRoot = Path.Combine(ProjectRoot, ".umcp");
        InboxPath = Path.Combine(UmcpRoot, "inbox");
        OutboxPath = Path.Combine(UmcpRoot, "outbox");
        PingPath = Path.Combine(UmcpRoot, "ping.json");

        Directory.CreateDirectory(InboxPath);
        Directory.CreateDirectory(OutboxPath);

        // Write initial heartbeat
        WriteHeartbeat();

        EditorApplication.update += Update;

        Debug.Log("[FileIPC] Bridge initialized at " + UmcpRoot + " (" + BridgeVersion + ")");
    }

    private static void Update()
    {
        double now = EditorApplication.timeSinceStartup;

        // Heartbeat refresh
        if (now - _lastHeartbeat >= HeartbeatInterval)
        {
            _lastHeartbeat = now;
            WriteHeartbeat();
        }

        // Poll inbox
        if (now - _lastPoll >= PollInterval)
        {
            _lastPoll = now;
            PollInbox();
        }
    }

    private static void WriteHeartbeat()
    {
        try
        {
            var ping = new PingData
            {
                status = "ok",
                projectName = Application.productName,
                projectPath = ProjectRoot,
                unityVersion = Application.unityVersion,
                platform = Application.platform.ToString(),
                processId = System.Diagnostics.Process.GetCurrentProcess().Id,
                lastHeartbeat = DateTime.UtcNow.ToString("o"),
                transport = "file-ipc"
            };

            string json = JsonUtility.ToJson(ping, false);
            string tmpPath = PingPath + ".tmp";
            File.WriteAllText(tmpPath, json);
            File.Move(tmpPath, PingPath);  // atomic on same volume
        }
        catch (IOException)
        {
            // Best effort — CLI may be reading the file
            try
            {
                var ping = new PingData
                {
                    status = "ok",
                    projectName = Application.productName,
                    projectPath = ProjectRoot,
                    unityVersion = Application.unityVersion,
                    platform = Application.platform.ToString(),
                    processId = System.Diagnostics.Process.GetCurrentProcess().Id,
                    lastHeartbeat = DateTime.UtcNow.ToString("o"),
                    transport = "file-ipc"
                };
                File.WriteAllText(PingPath, JsonUtility.ToJson(ping, false));
            }
            catch { }
        }
        catch (Exception ex)
        {
            Debug.LogWarning("[FileIPC] Heartbeat write failed: " + ex.Message);
        }
    }

    private static void PollInbox()
    {
        if (!Directory.Exists(InboxPath)) return;

        string[] files;
        try
        {
            files = Directory.GetFiles(InboxPath, "*.json");
        }
        catch (IOException)
        {
            return;
        }

        foreach (string filePath in files)
        {
            CommandData command = null;
            try
            {
                string raw = File.ReadAllText(filePath);
                File.Delete(filePath);

                command = JsonUtility.FromJson<CommandData>(raw);
                if (string.IsNullOrEmpty(command.id) || string.IsNullOrEmpty(command.route))
                {
                    Debug.LogWarning("[FileIPC] Skipping malformed command file: " + filePath);
                    continue;
                }

                string agentId = NormalizeAgentId(command.agentId);

                // Dispatch and write response
                BeginAgentCommand(agentId, command.route);
                object result = Dispatch(command.route, command.@params, agentId);
                CompleteAgentCommand(agentId, command.route, true, null);
                WriteResponse(command.id, result, null);
            }
            catch (Exception ex)
            {
                // Try to extract the command ID for the error response
                string cmdId = null;
                string route = "unknown";
                string agentId = "unknown-agent";
                try
                {
                    var parsed = command ?? JsonUtility.FromJson<CommandData>(File.Exists(filePath) ? File.ReadAllText(filePath) : "{}");
                    cmdId = parsed.id;
                    route = string.IsNullOrEmpty(parsed.route) ? route : parsed.route;
                    agentId = NormalizeAgentId(parsed.agentId);
                }
                catch { }

                CompleteAgentCommand(agentId, route, false, ex.Message);

                if (!string.IsNullOrEmpty(cmdId))
                {
                    WriteResponse(cmdId, null, ex.Message);
                }

                Debug.LogError("[FileIPC] Error processing command: " + ex.Message);
            }
        }
    }

    private static object Dispatch(string route, string paramsJson, string agentId)
    {
        if (route == "queue/info")
            return BuildQueueInfo(agentId);
        if (route == "agents/list")
            return BuildAgentList();
        if (route == "agents/log")
            return BuildAgentLog(paramsJson, agentId);
        if (StandaloneOwnedRoutes.Contains(route))
            return StandaloneRouteHandler.Handle(route, paramsJson);

        // Try the full Unity MCP plugin first (if installed)
        if (TryPluginDispatch(route, paramsJson, out object pluginResult))
        {
            if (!IsUnknownRouteResult(pluginResult))
                return pluginResult;
        }

        // Fall back to standalone route handler
        return StandaloneRouteHandler.Handle(route, paramsJson);
    }

    private static string NormalizeAgentId(string agentId)
    {
        return string.IsNullOrEmpty(agentId) ? "unknown-agent" : agentId;
    }

    private static void BeginAgentCommand(string agentId, string route)
    {
        var session = GetOrCreateAgentSession(agentId);
        session.lastActivity = DateTime.UtcNow.ToString("o");
        session.currentAction = route;
    }

    private static void CompleteAgentCommand(string agentId, string route, bool success, string error)
    {
        var session = GetOrCreateAgentSession(agentId);
        session.lastActivity = DateTime.UtcNow.ToString("o");
        session.currentAction = success ? "idle" : "error";
        session.totalActions += 1;
        if (success)
            session.completedRequests += 1;
        else
            session.failedRequests += 1;

        AgentActions.Add(new AgentActionInfo
        {
            agentId = agentId,
            route = route,
            status = success ? "ok" : "error",
            error = error ?? "",
            timestamp = session.lastActivity
        });

        while (AgentActions.Count > MaxAgentActions)
            AgentActions.RemoveAt(0);
    }

    private static AgentSessionInfo GetOrCreateAgentSession(string agentId)
    {
        agentId = NormalizeAgentId(agentId);
        if (!AgentSessions.TryGetValue(agentId, out AgentSessionInfo session))
        {
            string now = DateTime.UtcNow.ToString("o");
            session = new AgentSessionInfo
            {
                agentId = agentId,
                connectedAt = now,
                lastActivity = now,
                currentAction = "idle",
                transport = "file-ipc"
            };
            AgentSessions[agentId] = session;
        }
        return session;
    }

    private static object BuildQueueInfo(string agentId)
    {
        return new Dictionary<string, object>
        {
            {"transport", "file-ipc"},
            {"queueSupported", false},
            {"activeAgents", AgentSessions.Count},
            {"executingCount", 0},
            {"totalQueued", 0},
            {"queued", 0},
            {"agentId", NormalizeAgentId(agentId)},
            {"message", "File IPC executes each request on Unity's main thread from .umcp/inbox; no Unity queue is required."}
        };
    }

    private static object BuildAgentList()
    {
        var sessions = new List<Dictionary<string, object>>();
        foreach (var session in AgentSessions.Values)
        {
            sessions.Add(new Dictionary<string, object>
            {
                {"agentId", session.agentId},
                {"connectedAt", session.connectedAt},
                {"lastActivity", session.lastActivity},
                {"currentAction", session.currentAction},
                {"totalActions", session.totalActions},
                {"queuedRequests", 0},
                {"completedRequests", session.completedRequests},
                {"failedRequests", session.failedRequests},
                {"transport", session.transport}
            });
        }

        return new Dictionary<string, object>
        {
            {"transport", "file-ipc"},
            {"sessions", sessions},
            {"agents", sessions},
            {"count", sessions.Count}
        };
    }

    private static object BuildAgentLog(string paramsJson, string fallbackAgentId)
    {
        string agentId = NormalizeAgentId(fallbackAgentId);
        int limit = 100;
        try
        {
            var payload = MiniJson.Deserialize(paramsJson);
            if (payload.TryGetValue("agentId", out object requestedAgent) && requestedAgent != null)
                agentId = NormalizeAgentId(requestedAgent.ToString());
            if (payload.TryGetValue("limit", out object requestedLimit) && requestedLimit != null)
                int.TryParse(requestedLimit.ToString(), out limit);
        }
        catch { }
        if (limit <= 0) limit = 100;

        var actions = new List<Dictionary<string, object>>();
        for (int index = AgentActions.Count - 1; index >= 0 && actions.Count < limit; index--)
        {
            var action = AgentActions[index];
            if (action.agentId != agentId)
                continue;
            actions.Add(new Dictionary<string, object>
            {
                {"agentId", action.agentId},
                {"route", action.route},
                {"status", action.status},
                {"error", action.error},
                {"timestamp", action.timestamp}
            });
        }
        actions.Reverse();

        return new Dictionary<string, object>
        {
            {"transport", "file-ipc"},
            {"agentId", agentId},
            {"actions", actions},
            {"count", actions.Count}
        };
    }

    private static bool IsUnknownRouteResult(object result)
    {
        if (result == null) return false;
        if (result is string text)
            return text.IndexOf("Unknown route", StringComparison.OrdinalIgnoreCase) >= 0
                || text.IndexOf("Unknown API endpoint", StringComparison.OrdinalIgnoreCase) >= 0;

        if (result is Dictionary<string, object> dict)
        {
            if (dict.TryGetValue("unknownRoute", out object unknown) && IsTruthy(unknown))
                return true;
            if (dict.TryGetValue("error", out object error) && error != null)
                return IsUnknownRouteResult(error.ToString());
        }

        var type = result.GetType();
        foreach (string memberName in new[] { "unknownRoute", "UnknownRoute" })
        {
            var field = type.GetField(memberName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (field != null && IsTruthy(field.GetValue(result)))
                return true;
            var property = type.GetProperty(memberName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (property != null && property.CanRead && IsTruthy(property.GetValue(result, null)))
                return true;
        }

        foreach (string memberName in new[] { "error", "Error" })
        {
            var field = type.GetField(memberName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (field != null)
            {
                var value = field.GetValue(result);
                if (value != null && IsUnknownRouteResult(value.ToString()))
                    return true;
            }
            var property = type.GetProperty(memberName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (property != null && property.CanRead)
            {
                var value = property.GetValue(result, null);
                if (value != null && IsUnknownRouteResult(value.ToString()))
                    return true;
            }
        }

        return false;
    }

    private static bool IsTruthy(object value)
    {
        if (value is bool b) return b;
        if (value == null) return false;
        return bool.TryParse(value.ToString(), out bool parsed) && parsed;
    }

    private static bool TryPluginDispatch(string route, string paramsJson, out object result)
    {
        result = null;

        if (!_pluginChecked)
        {
            _pluginChecked = true;
            // Look for the MCP plugin's route dispatcher via reflection
            // Common class names in the AnkleBreaker Unity MCP plugin
            foreach (string typeName in new[]
            {
                "UnityMCP.Editor.MCPRouteDispatcher",
                "UnityMCP.Editor.RouteDispatcher",
                "MCPRouteDispatcher",
            })
            {
                var type = FindType(typeName);
                if (type == null) continue;

                // Look for a static method like HandleRoute(string route, string paramsJson)
                _pluginDispatchMethod = type.GetMethod(
                    "HandleRoute",
                    BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic,
                    null,
                    new[] { typeof(string), typeof(string) },
                    null
                );

                if (_pluginDispatchMethod != null)
                {
                    Debug.Log("[FileIPC] Found plugin route dispatcher: " + typeName);
                    break;
                }

                // Also try HandleRouteAsync or Dispatch
                _pluginDispatchMethod = type.GetMethod(
                    "Dispatch",
                    BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic,
                    null,
                    new[] { typeof(string), typeof(string) },
                    null
                );

                if (_pluginDispatchMethod != null)
                {
                    Debug.Log("[FileIPC] Found plugin dispatcher: " + typeName + ".Dispatch");
                    break;
                }
            }
        }

        if (_pluginDispatchMethod == null) return false;

        try
        {
            result = _pluginDispatchMethod.Invoke(null, new object[] { route, paramsJson });
            return result != null;
        }
        catch (TargetInvocationException ex)
        {
            Debug.LogWarning("[FileIPC] Plugin dispatch failed for " + route + ": " +
                             (ex.InnerException?.Message ?? ex.Message));
            return false;
        }
        catch (Exception ex)
        {
            Debug.LogWarning("[FileIPC] Plugin dispatch error: " + ex.Message);
            return false;
        }
    }

    private static void WriteResponse(string commandId, object result, string error)
    {
        try
        {
            string json;
            if (error != null)
            {
                json = "{\"id\":\"" + EscapeJson(commandId) + "\",\"error\":\"" + EscapeJson(error) + "\"}";
            }
            else
            {
                // Use MiniJson.Serialize so Dictionary<string,object> round-trips correctly.
                // JsonUtility.ToJson cannot serialize dictionaries and always returns {}.
                string resultJson = MiniJson.Serialize(result);
                json = "{\"id\":\"" + EscapeJson(commandId) + "\",\"result\":" + resultJson + "}";
            }

            string responsePath = Path.Combine(OutboxPath, commandId + ".json");
            string tmpPath = responsePath + ".tmp";
            File.WriteAllText(tmpPath, json);
            File.Move(tmpPath, responsePath);
        }
        catch (Exception ex)
        {
            Debug.LogError("[FileIPC] Failed to write response for " + commandId + ": " + ex.Message);
        }
    }

    private static string EscapeJson(string s)
    {
        if (s == null) return "";
        return s.Replace("\\", "\\\\").Replace("\"", "\\\"");
    }

    private static Type FindType(string fullName)
    {
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
        {
            var type = assembly.GetType(fullName, false);
            if (type != null) return type;
        }
        return null;
    }

    // ── JSON data classes ───────────────────────────────────────────────

    [Serializable]
    private class PingData
    {
        public string status;
        public string projectName;
        public string projectPath;
        public string unityVersion;
        public string platform;
        public int processId;
        public string lastHeartbeat;
        public string transport;
    }

    [Serializable]
    private class CommandData
    {
        public string id;
        public string route;
        public string @params;  // raw JSON string
        public string agentId;
        public string timestamp;
    }

    private class AgentSessionInfo
    {
        public string agentId;
        public string connectedAt;
        public string lastActivity;
        public string currentAction;
        public int totalActions;
        public int completedRequests;
        public int failedRequests;
        public string transport;
    }

    private class AgentActionInfo
    {
        public string agentId;
        public string route;
        public string status;
        public string error;
        public string timestamp;
    }

    [Serializable]
    private class ResponseError
    {
        public string id;
        public string error;
    }
}
