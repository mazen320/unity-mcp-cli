from __future__ import annotations

import json
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .debug_doctor import build_debug_doctor_report


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _coerce_int(value: Any, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return default


@dataclass
class DashboardConfig:
    host: str = "127.0.0.1"
    port: int = 0
    unity_port: int | None = None
    open_browser: bool = True
    console_count: int = 20
    issue_limit: int = 20
    include_hierarchy: bool = False
    editor_log_tail: int = 40
    ab_umcp_only: bool = False
    trace_tail: int = 20
    message_type: str = "all"


@dataclass
class DashboardHandle:
    server: ThreadingHTTPServer
    thread: threading.Thread
    url: str
    host: str
    port: int
    browser_opened: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "host": self.host,
            "port": self.port,
            "browserOpened": self.browser_opened,
        }

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1.0)


def _dashboard_html() -> str:
    return r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Unity CLI Debug Dashboard</title>
  <style>
    :root {
      --bg: #0b1320;
      --panel: #132033;
      --panel-2: #18283d;
      --border: rgba(255,255,255,0.08);
      --text: #f5f7fb;
      --muted: #97a8c4;
      --good: #63d2a1;
      --warn: #f3c969;
      --bad: #ff7b7b;
      --accent: #6fd3ff;
      --shadow: 0 18px 40px rgba(0,0,0,0.28);
      --shell-pad: clamp(14px, 1.2vw, 22px);
      --radius: clamp(18px, 1vw, 24px);
      --gap: clamp(12px, 1vw, 18px);
      --font-body: clamp(14px, 0.18vw + 13px, 16px);
      --font-small: clamp(12px, 0.12vw + 11px, 13px);
      --font-panel: clamp(15px, 0.22vw + 14px, 18px);
      --font-title: clamp(24px, 1.25vw + 19px, 40px);
      --font-value: clamp(18px, 0.7vw + 15px, 28px);
      --font-mono: clamp(11px, 0.12vw + 10.5px, 13px);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Inter, sans-serif;
      font-size: var(--font-body);
      background:
        radial-gradient(circle at top right, rgba(111,211,255,0.14), transparent 32%),
        radial-gradient(circle at top left, rgba(99,210,161,0.08), transparent 24%),
        linear-gradient(180deg, #0a1018 0%, var(--bg) 100%);
      color: var(--text);
    }
    .shell {
      width: min(1480px, calc(100vw - clamp(14px, 2vw, 28px)));
      margin: 20px auto;
      padding: var(--shell-pad);
      border-radius: var(--radius);
      background: rgba(10, 16, 24, 0.82);
      backdrop-filter: blur(18px);
      box-shadow: var(--shadow);
      border: 1px solid rgba(255,255,255,0.06);
    }
    .topbar {
      display: flex;
      gap: var(--gap);
      align-items: flex-start;
      justify-content: space-between;
      margin-bottom: var(--gap);
    }
    .title h1 {
      margin: 0 0 6px;
      font-size: var(--font-title);
      line-height: 1.1;
      text-wrap: balance;
    }
    .title p {
      margin: 0;
      color: var(--muted);
      max-width: 720px;
      font-size: clamp(13px, 0.18vw + 12px, 16px);
      line-height: 1.55;
    }
    .toolbar {
      display: flex;
      gap: clamp(8px, 0.7vw, 10px);
      align-items: center;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    button, select, input {
      font: inherit;
      color: var(--text);
    }
    button {
      background: linear-gradient(180deg, #223a58 0%, #16253b 100%);
      border: 1px solid var(--border);
      padding: clamp(9px, 0.55vw, 11px) clamp(12px, 0.9vw, 15px);
      border-radius: 12px;
      cursor: pointer;
    }
    button:hover { filter: brightness(1.08); }
    .ghost {
      background: rgba(255,255,255,0.03);
    }
    .layout {
      display: grid;
      grid-template-columns: minmax(290px, 330px) minmax(0, 1fr);
      gap: var(--gap);
    }
    .panel {
      background: linear-gradient(180deg, var(--panel) 0%, var(--panel-2) 100%);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: clamp(14px, 1vw, 18px);
      min-height: 120px;
    }
    .panel h2 {
      margin: 0 0 12px;
      font-size: var(--font-panel);
      letter-spacing: 0.01em;
    }
    .stack {
      display: grid;
      gap: clamp(12px, 0.9vw, 14px);
    }
    .settings-grid {
      display: grid;
      gap: clamp(9px, 0.7vw, 12px);
    }
    .field {
      display: grid;
      gap: 6px;
    }
    .field label {
      color: var(--muted);
      font-size: var(--font-small);
    }
    .field input[type="number"], .field select, .field input[type="text"] {
      width: 100%;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.04);
      padding: clamp(9px, 0.55vw, 11px) clamp(11px, 0.7vw, 13px);
    }
    .checkbox {
      display: flex;
      align-items: center;
      gap: 10px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.03);
      border-radius: 12px;
      padding: clamp(9px, 0.55vw, 11px) clamp(11px, 0.7vw, 13px);
      line-height: 1.45;
    }
    .checkbox input {
      width: 18px;
      height: 18px;
      accent-color: var(--accent);
      flex: 0 0 auto;
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(185px, 100%), 1fr));
      gap: clamp(10px, 0.8vw, 12px);
      margin-bottom: var(--gap);
    }
    .card {
      padding: clamp(12px, 0.8vw, 15px);
      border-radius: 16px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.03);
      min-width: 0;
      overflow: hidden;
    }
    .card .label {
      color: var(--muted);
      font-size: var(--font-small);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .card .value {
      display: block;
      max-inline-size: 100%;
      margin-top: 8px;
      font-size: var(--font-value);
      font-weight: 650;
      line-height: 1.15;
      word-break: break-word;
      overflow-wrap: anywhere;
      text-wrap: pretty;
    }
    .status-good { color: var(--good); }
    .status-warn { color: var(--warn); }
    .status-bad { color: var(--bad); }
    .two-col {
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: var(--gap);
      margin-bottom: var(--gap);
    }
    .panel pre, .log {
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: Consolas, "SFMono-Regular", monospace;
      font-size: var(--font-mono);
      line-height: 1.5;
      color: #dce7fb;
      background: rgba(7,11,18,0.58);
      border: 1px solid rgba(255,255,255,0.04);
      border-radius: 14px;
      padding: clamp(10px, 0.8vw, 13px);
      max-height: 420px;
      overflow: auto;
    }
    .finding {
      border: 1px solid var(--border);
      border-left: 4px solid var(--accent);
      border-radius: 14px;
      padding: 12px;
      background: rgba(255,255,255,0.03);
      margin-bottom: 10px;
    }
    .finding.error { border-left-color: var(--bad); }
    .finding.warning { border-left-color: var(--warn); }
    .finding.info { border-left-color: var(--good); }
    .finding strong { display: block; margin-bottom: 6px; }
    .finding .detail { color: var(--muted); }
    .trace-item {
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 10px 12px;
      margin-bottom: 8px;
      background: rgba(255,255,255,0.03);
    }
    .trace-meta {
      color: var(--muted);
      font-size: var(--font-small);
      margin-bottom: 6px;
    }
    .inline-pills {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin: 8px 0 0;
    }
    .pill {
      border-radius: 999px;
      padding: 6px 10px;
      font-size: var(--font-small);
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.05);
      color: var(--muted);
    }
    .footer-note {
      margin-top: 10px;
      color: var(--muted);
      font-size: var(--font-small);
      line-height: 1.5;
    }
    @media (max-width: 1180px) {
      .layout { grid-template-columns: 1fr; }
      .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .two-col { grid-template-columns: 1fr; }
    }
    @media (max-width: 780px) {
      .shell {
        margin: 10px auto;
      }
      .topbar {
        flex-direction: column;
        align-items: stretch;
      }
      .toolbar {
        justify-content: flex-start;
      }
      .cards {
        grid-template-columns: 1fr;
      }
      button {
        width: 100%;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <div class="topbar">
      <div class="title">
        <h1>Unity CLI Debug Dashboard</h1>
        <p>Live view for bridge health, doctor findings, trace steps, Unity console state, and Editor.log details. This is a debugging surface for the CLI layer, not a sample scene viewer.</p>
      </div>
      <div class="toolbar">
        <button id="refresh-live">Live Refresh</button>
        <button id="refresh-now">Run Deep Check</button>
        <button id="save-settings" class="ghost">Save Settings</button>
        <span id="status-pill" class="pill">Loading…</span>
      </div>
    </div>
    <div class="layout">
      <div class="stack">
        <section class="panel">
          <h2>Dashboard Settings</h2>
          <div class="settings-grid">
            <div class="checkbox">
              <input id="auto-refresh" type="checkbox" checked>
              <label for="auto-refresh">Auto refresh live view</label>
            </div>
            <div class="field">
              <label for="refresh-seconds">Refresh interval (seconds)</label>
              <input id="refresh-seconds" type="number" min="1" step="0.5" value="5">
            </div>
            <div class="field">
              <label for="console-count">Unity console count</label>
              <input id="console-count" type="number" min="1" step="1" value="20">
            </div>
            <div class="field">
              <label for="issue-limit">Compilation / issue limit</label>
              <input id="issue-limit" type="number" min="1" step="1" value="20">
            </div>
            <div class="field">
              <label for="trace-tail">Trace tail length</label>
              <input id="trace-tail" type="number" min="1" step="1" value="20">
            </div>
            <div class="field">
              <label for="editor-log-tail">Editor.log tail</label>
              <input id="editor-log-tail" type="number" min="1" step="1" value="40">
            </div>
            <div class="field">
              <label for="message-type">Console severity</label>
              <select id="message-type">
                <option value="all">all</option>
                <option value="info">info</option>
                <option value="warning">warning</option>
                <option value="error">error</option>
              </select>
            </div>
            <div class="field">
              <label for="editor-log-contains">Editor.log contains</label>
              <input id="editor-log-contains" type="text" placeholder="Optional text filter">
            </div>
            <div class="checkbox">
              <input id="include-hierarchy" type="checkbox">
              <label for="include-hierarchy">Include hierarchy snapshot</label>
            </div>
            <div class="checkbox">
              <input id="ab-umcp-only" type="checkbox">
              <label for="ab-umcp-only">Editor.log AB-UMCP only</label>
            </div>
            <div class="checkbox">
              <input id="unity-console-breadcrumbs" type="checkbox">
              <label for="unity-console-breadcrumbs">Write CLI breadcrumbs into Unity Console / Editor.log</label>
            </div>
          </div>
          <div class="footer-note">Auto refresh only updates the lighter live view. Use deep check when you actually need bridge diagnostics, full Editor.log context, or heavier Unity inspection.</div>
        </section>
        <section class="panel">
          <h2>Bridge</h2>
          <div class="footer-note">Deep check only. Auto refresh stays lightweight so Unity does not hitch.</div>
          <pre id="bridge-json">Loading…</pre>
        </section>
      </div>
      <div>
        <section class="cards" id="summary-cards"></section>
        <section class="two-col">
          <div class="panel">
            <h2>Doctor Findings</h2>
            <div id="doctor-findings"></div>
          </div>
          <div class="panel">
            <h2>Recent Trace</h2>
            <div id="trace-entries"></div>
          </div>
        </section>
        <section class="two-col">
          <div class="panel">
            <h2>Unity Console</h2>
            <pre id="console-json">Loading…</pre>
          </div>
          <div class="panel">
            <h2>Editor.log</h2>
            <div class="footer-note">Deep check only. Auto refresh reuses the last deep log snapshot.</div>
            <pre id="editor-log">Loading…</pre>
          </div>
        </section>
      </div>
    </div>
  </div>
  <script>
    const qs = (id) => document.getElementById(id);
    let refreshTimer = null;
    let refreshInFlight = false;
    let currentState = null;

    function getSettings() {
      return {
        autoRefresh: qs("auto-refresh").checked,
        refreshSeconds: Number(qs("refresh-seconds").value || 5),
        consoleCount: Number(qs("console-count").value || 20),
        issueLimit: Number(qs("issue-limit").value || 20),
        traceTail: Number(qs("trace-tail").value || 20),
        editorLogTail: Number(qs("editor-log-tail").value || 40),
        messageType: qs("message-type").value || "all",
        editorLogContains: qs("editor-log-contains").value || "",
        includeHierarchy: qs("include-hierarchy").checked,
        abUmcpOnly: qs("ab-umcp-only").checked,
        unityConsoleBreadcrumbs: qs("unity-console-breadcrumbs").checked,
      };
    }

    function applyPreferences(preferences) {
      if (!preferences) return;
      qs("auto-refresh").checked = !!preferences.dashboardAutoRefresh;
      qs("refresh-seconds").value = preferences.dashboardRefreshSeconds ?? 5;
      qs("console-count").value = preferences.dashboardConsoleCount ?? 20;
      qs("issue-limit").value = preferences.dashboardIssueLimit ?? 20;
      qs("editor-log-tail").value = preferences.dashboardEditorLogTail ?? 40;
      qs("include-hierarchy").checked = !!preferences.dashboardIncludeHierarchy;
      qs("ab-umcp-only").checked = !!preferences.dashboardAbUmcpOnly;
      qs("unity-console-breadcrumbs").checked = !!preferences.unityConsoleBreadcrumbs;
    }

    function renderSummary(summary) {
      const cards = [
        ["Project", summary.projectName || "Unknown", ""],
        ["Scene", summary.activeScene || "Unknown", summary.sceneDirty ? "status-warn" : "status-good"],
        ["Assessment", summary.assessment || "unknown", summary.assessment === "error" ? "status-bad" : summary.assessment === "warning" ? "status-warn" : "status-good"],
        ["Console", String(summary.consoleEntryCount ?? 0), summary.consoleHighestSeverity === "error" ? "status-bad" : summary.consoleHighestSeverity === "warning" ? "status-warn" : "status-good"],
        ["Queue", String(summary.queueQueuedRequests ?? 0), (summary.queueQueuedRequests ?? 0) > 0 ? "status-warn" : "status-good"],
      ];
      qs("summary-cards").innerHTML = cards.map(([label, value, cls]) => `
        <div class="card">
          <div class="label">${label}</div>
          <div class="value ${cls}">${value}</div>
        </div>
      `).join("");
    }

    function renderFindings(doctor) {
      const findings = doctor?.findings || [];
      qs("doctor-findings").innerHTML = findings.map((finding) => `
        <div class="finding ${finding.severity || "info"}">
          <strong>${finding.title || "Finding"}</strong>
          <div class="detail">${finding.detail || ""}</div>
          ${(finding.command) ? `<div class="inline-pills"><span class="pill">${finding.command}</span></div>` : ""}
        </div>
      `).join("") || `<div class="finding info"><strong>Healthy Snapshot</strong><div class="detail">No current doctor findings.</div></div>`;
    }

    function renderTrace(entries) {
      qs("trace-entries").innerHTML = (entries || []).map((entry) => `
        <div class="trace-item">
          <div class="trace-meta">${entry.phase || "run"}${entry.target ? ` · ${entry.target}` : ""}${entry.amount ? ` · ${entry.amount}` : ""}</div>
          <div>${entry.summary || entry.command || "Trace entry"}</div>
        </div>
      `).join("") || `<div class="trace-item"><div>No trace entries yet.</div></div>`;
    }

    function renderConsole(consolePayload, consoleSummary) {
      const compact = {
        summary: consoleSummary,
        entries: consolePayload?.entries || [],
      };
      qs("console-json").textContent = JSON.stringify(compact, null, 2);
    }

    function renderBridge(bridge) {
      if (!bridge) {
        qs("bridge-json").textContent = "Run Deep Check to load bridge diagnostics.";
        return;
      }
      qs("bridge-json").textContent = JSON.stringify(bridge, null, 2);
    }

    function renderEditorLog(editorLog) {
      if (!editorLog) {
        qs("editor-log").textContent = "Run Deep Check to load Editor.log details.";
        return;
      }
      const entries = editorLog?.entries || [];
      qs("editor-log").textContent = entries.map((entry) => {
        const prefix = entry?.matched ? "*" : " ";
        return `${prefix} ${entry?.lineNumber ?? "?"}: ${entry?.text ?? ""}`;
      }).join("\n") || "No matching Editor.log entries.";
    }

    function updateStatus(text) {
      qs("status-pill").textContent = text;
    }

    async function loadSettings() {
      const response = await fetch("/api/settings");
      const payload = await response.json();
      applyPreferences(payload.preferences || {});
      qs("trace-tail").value = 20;
    }

    async function refreshState(mode = "live") {
      const settings = getSettings();
      const params = new URLSearchParams({
        consoleCount: String(settings.consoleCount),
        traceTail: String(settings.traceTail),
        messageType: settings.messageType,
      });
      if (mode === "deep") {
        params.set("issueLimit", String(settings.issueLimit));
        params.set("editorLogTail", String(settings.editorLogTail));
        params.set("includeHierarchy", String(settings.includeHierarchy));
        params.set("abUmcpOnly", String(settings.abUmcpOnly));
        if (settings.editorLogContains) {
          params.set("editorLogContains", settings.editorLogContains);
        }
      }
      updateStatus(mode === "deep" ? "Running deep check…" : "Refreshing live view…");
      const endpoint = mode === "deep" ? "/api/state" : "/api/live";
      const response = await fetch(`${endpoint}?${params.toString()}`);
      currentState = await response.json();
      renderSummary(currentState.doctor?.summary || currentState.snapshot?.summary || {});
      renderFindings(currentState.doctor);
      renderTrace(currentState.trace?.entries || []);
      renderConsole(currentState.snapshot?.console, currentState.snapshot?.consoleSummary);
      renderBridge(currentState.bridge || currentState.cached?.bridge || null);
      renderEditorLog(currentState.editorLog || currentState.cached?.editorLog || null);
      updateStatus(`${mode === "deep" ? "Deep check" : "Live view"} updated ${new Date().toLocaleTimeString()}`);
    }

    async function saveSettings() {
      const settings = getSettings();
      updateStatus("Saving settings…");
      const response = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          unityConsoleBreadcrumbs: settings.unityConsoleBreadcrumbs,
          dashboardAutoRefresh: settings.autoRefresh,
          dashboardRefreshSeconds: settings.refreshSeconds,
          dashboardConsoleCount: settings.consoleCount,
          dashboardIssueLimit: settings.issueLimit,
          dashboardIncludeHierarchy: settings.includeHierarchy,
          dashboardEditorLogTail: settings.editorLogTail,
          dashboardAbUmcpOnly: settings.abUmcpOnly,
        }),
      });
      const payload = await response.json();
      applyPreferences(payload.preferences || {});
      updateStatus("Settings saved");
      scheduleRefresh();
    }

    function scheduleRefresh() {
      if (refreshTimer) {
        clearTimeout(refreshTimer);
        refreshTimer = null;
      }
      const settings = getSettings();
      if (!settings.autoRefresh) {
        return;
      }
      const intervalMs = Math.max(1000, Number(settings.refreshSeconds || 5) * 1000);
      refreshTimer = setTimeout(async () => {
        if (!refreshInFlight) {
          refreshInFlight = true;
          try {
            await refreshState("live");
          } catch (error) {
            updateStatus(`Refresh failed: ${error}`);
          } finally {
            refreshInFlight = false;
          }
        }
        scheduleRefresh();
      }, intervalMs);
    }

    qs("refresh-live").addEventListener("click", () => {
      refreshState("live").catch((error) => updateStatus(`Refresh failed: ${error}`));
    });
    qs("refresh-now").addEventListener("click", () => {
      refreshState("deep").catch((error) => updateStatus(`Deep check failed: ${error}`));
    });
    qs("save-settings").addEventListener("click", () => {
      saveSettings().catch((error) => updateStatus(`Save failed: ${error}`));
    });
    ["auto-refresh", "refresh-seconds"].forEach((id) => {
      qs(id).addEventListener("change", scheduleRefresh);
    });

    loadSettings()
      .then(() => refreshState("live"))
      .then(scheduleRefresh)
      .catch((error) => updateStatus(`Startup failed: ${error}`));
  </script>
</body>
</html>
"""


def serve_debug_dashboard(
    *,
    backend: Any,
    config: DashboardConfig,
    history_formatter: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> DashboardHandle:
    html = _dashboard_html().encode("utf-8")
    settings_lock = threading.Lock()
    state_lock = threading.Lock()
    cached_deep_state: dict[str, Any] | None = None

    def _parse_query(query: dict[str, list[str]]) -> dict[str, Any]:
        preferences = backend.get_debug_preferences()
        return {
            "console_count": _coerce_int(
                (query.get("consoleCount") or [preferences.get("dashboardConsoleCount")])[0],
                int(preferences.get("dashboardConsoleCount", config.console_count)),
            ),
            "issue_limit": _coerce_int(
                (query.get("issueLimit") or [preferences.get("dashboardIssueLimit")])[0],
                int(preferences.get("dashboardIssueLimit", config.issue_limit)),
            ),
            "trace_tail": _coerce_int(
                (query.get("traceTail") or [config.trace_tail])[0],
                config.trace_tail,
            ),
            "editor_log_tail": _coerce_int(
                (query.get("editorLogTail") or [preferences.get("dashboardEditorLogTail")])[0],
                int(preferences.get("dashboardEditorLogTail", config.editor_log_tail)),
            ),
            "include_hierarchy": _coerce_bool(
                (query.get("includeHierarchy") or [preferences.get("dashboardIncludeHierarchy")])[0],
                bool(preferences.get("dashboardIncludeHierarchy", config.include_hierarchy)),
            ),
            "ab_umcp_only": _coerce_bool(
                (query.get("abUmcpOnly") or [preferences.get("dashboardAbUmcpOnly")])[0],
                bool(preferences.get("dashboardAbUmcpOnly", config.ab_umcp_only)),
            ),
            "message_type": (query.get("messageType") or [config.message_type])[0] or "all",
            "editor_log_contains": (query.get("editorLogContains") or [""])[0] or None,
        }

    def _build_state(query: dict[str, list[str]]) -> dict[str, Any]:
        nonlocal cached_deep_state
        options = _parse_query(query)
        state = backend.build_debug_dashboard_state(
            port=config.unity_port,
            console_count=options["console_count"],
            issue_limit=options["issue_limit"],
            include_hierarchy=options["include_hierarchy"],
            editor_log_tail=options["editor_log_tail"],
            editor_log_contains=options["editor_log_contains"],
            ab_umcp_only=options["ab_umcp_only"],
            trace_tail=options["trace_tail"],
            message_type=options["message_type"],
            history_formatter=history_formatter,
        )
        state["doctor"] = build_debug_doctor_report(
            state["snapshot"],
            state["trace"]["entries"],
            state["request"]["port"],
        )
        with state_lock:
            cached_deep_state = state
        return state

    def _build_live_state(query: dict[str, list[str]]) -> dict[str, Any]:
        options = _parse_query(query)
        state = backend.build_debug_dashboard_live_state(
            port=config.unity_port,
            console_count=options["console_count"],
            message_type=options["message_type"],
            trace_tail=options["trace_tail"],
            history_formatter=history_formatter,
        )
        state["doctor"] = build_debug_doctor_report(
            state["snapshot"],
            state["trace"]["entries"],
            state["request"]["port"],
        )
        with state_lock:
            if cached_deep_state is not None:
                state["cached"] = {
                    "bridge": cached_deep_state.get("bridge"),
                    "editorLog": cached_deep_state.get("editorLog"),
                    "generatedAt": cached_deep_state.get("generatedAt"),
                }
        return state

    class DashboardHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(html)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html()
                return
            if parsed.path == "/api/settings":
                self._send_json({"preferences": backend.get_debug_preferences()})
                return
            if parsed.path == "/api/state":
                try:
                    payload = _build_state(parse_qs(parsed.query))
                except Exception as exc:  # pragma: no cover - exercised live
                    self._send_json({"error": str(exc)}, status=500)
                    return
                self._send_json(payload)
                return
            if parsed.path == "/api/live":
                try:
                    payload = _build_live_state(parse_qs(parsed.query))
                except Exception as exc:  # pragma: no cover - exercised live
                    self._send_json({"error": str(exc)}, status=500)
                    return
                self._send_json(payload)
                return
            self._send_json({"error": "Not found"}, status=404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/settings":
                self._send_json({"error": "Not found"}, status=404)
                return
            content_length = _coerce_int(self.headers.get("Content-Length"), 0, minimum=0)
            raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                payload = json.loads(raw_body.decode("utf-8"))
            except json.JSONDecodeError:
                self._send_json({"error": "Invalid JSON body"}, status=400)
                return
            with settings_lock:
                preferences = backend.update_debug_preferences(**payload)
            self._send_json({"success": True, "preferences": preferences})

    server = ThreadingHTTPServer((config.host, config.port), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, name="unity-debug-dashboard", daemon=True)
    thread.start()
    url = f"http://{config.host}:{server.server_port}/"
    browser_opened = bool(config.open_browser)
    if browser_opened:
        webbrowser.open(url, new=1, autoraise=True)
    return DashboardHandle(
        server=server,
        thread=thread,
        url=url,
        host=config.host,
        port=server.server_port,
        browser_opened=browser_opened,
    )
