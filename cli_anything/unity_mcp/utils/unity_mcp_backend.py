from __future__ import annotations

from collections import deque
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

from ..core.client import UnityMCPClient, UnityMCPClientError, UnityMCPConnectionError, UnityMCPHTTPError
from ..core.file_ipc import FileIPCClient, FileIPCError, FileIPCConnectionError, FileIPCTimeoutError
from ..core.routes import iter_known_tools, route_to_tool_name, tool_name_to_route
from ..core.schema_templates import summarize_schema
from ..core.session import SessionState, SessionStore, normalize_debug_preferences
from ..core.tool_catalog import get_upstream_tool, iter_upstream_tools
from ..core.tool_coverage import build_tool_coverage_matrix


def get_default_registry_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "UnityMCP" / "instances.json"
    return Path.home() / ".local" / "share" / "UnityMCP" / "instances.json"


def get_default_editor_log_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "Unity" / "Editor" / "Editor.log"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "Unity" / "Editor.log"
    return Path.home() / ".config" / "unity3d" / "Editor.log"


class BackendSelectionError(RuntimeError):
    """Raised when an instance needs to be selected before continuing."""


class UnityMCPBackend:
    NON_HISTORY_ROUTES = {"ping", "_meta/routes", "queue/info"}
    TOOL_PARAM_ALIASES: Dict[str, Dict[str, str]] = {
        "unity_graphics_renderer_info": {"objectPath": "gameObjectPath"},
        "unity_graphics_mesh_info": {"objectPath": "gameObjectPath"},
        "unity_graphics_material_info": {"objectPath": "gameObjectPath"},
    }

    def __init__(
        self,
        client: UnityMCPClient | None = None,
        session_store: SessionStore | None = None,
        registry_path: Path | None = None,
        default_port: int = 7890,
        port_range_start: int = 7890,
        port_range_end: int = 7899,
        transport: str = "auto",
        file_ipc_paths: List[str | Path] | None = None,
    ) -> None:
        self.client = client or UnityMCPClient()
        self.session_store = session_store or SessionStore()
        self.registry_path = Path(registry_path) if registry_path else get_default_registry_path()
        self.default_port = default_port
        self.port_range_start = port_range_start
        self.port_range_end = port_range_end
        self.transport = transport  # "auto", "http", "file"
        self.file_ipc_paths: List[Path] = [Path(p) for p in (file_ipc_paths or [])]
        self._file_ipc_clients: Dict[str, FileIPCClient] = {}
        self.runtime_agent_id: str | None = None
        self.runtime_agent_profile: str | None = None
        self.runtime_command_path: str | None = None
        self.runtime_activity: str | None = None

    def set_runtime_context(
        self,
        *,
        agent_id: str | None = None,
        agent_profile: str | None = None,
        command_path: str | None = None,
        activity: str | None = None,
    ) -> None:
        self.runtime_agent_id = agent_id
        self.runtime_agent_profile = agent_profile
        self.runtime_command_path = command_path
        self.runtime_activity = activity

    def _record_history(
        self,
        command: str,
        args: Optional[Dict[str, Any]],
        port: Optional[int],
        *,
        status: str = "ok",
        duration_ms: float | None = None,
        error: str | None = None,
        transport: str | None = None,
        note: str | None = None,
    ) -> None:
        self.session_store.record_command(
            command,
            args,
            port,
            status=status,
            duration_ms=duration_ms,
            error=error,
            transport=transport,
            note=note,
            agent_id=self.runtime_agent_id,
            agent_profile=self.runtime_agent_profile,
            command_path=self.runtime_command_path,
            activity=self.runtime_activity,
        )

    def record_progress(
        self,
        message: str,
        port: Optional[int] = None,
        *,
        phase: str | None = None,
        level: str = "info",
        emit_breadcrumb: bool = True,
        breadcrumb_message: str | None = None,
    ) -> Dict[str, Any]:
        resolved_port: int | None = None
        if port is not None:
            resolved_port = port
        else:
            try:
                resolved_port = self.resolve_port(explicit_port=None, allow_default=False)
            except BackendSelectionError:
                resolved_port = None

        if emit_breadcrumb and resolved_port is not None and self.should_emit_unity_breadcrumbs():
            self.emit_unity_breadcrumb(
                message=breadcrumb_message or message,
                port=resolved_port,
                level=level,
                record_history=False,
            )

        payload = {
            "message": message,
            "level": str(level or "info").lower(),
        }
        if phase:
            payload["phase"] = phase

        self._record_history(
            "cli/progress",
            payload,
            resolved_port,
            transport="local",
            note="CLI progress",
        )
        return payload

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        return (time.monotonic() - started_at) * 1000.0

    def get_debug_preferences(self) -> Dict[str, Any]:
        return self.session_store.get_debug_preferences()

    def update_debug_preferences(self, **updates: Any) -> Dict[str, Any]:
        state = self.session_store.update_debug_preferences(**updates)
        return dict(state.debug_preferences)

    def should_emit_unity_breadcrumbs(self) -> bool:
        preferences = self.get_debug_preferences()
        return bool(preferences.get("unityConsoleBreadcrumbs", True))

    def list_instances(self) -> Dict[str, Any]:
        state = self.session_store.load()
        instances = self.discover_instances()
        instances = self._reconcile_selection(state, instances)
        state = self.session_store.load()
        selected_port = state.selected_port
        selected_project = None
        if state.selected_instance:
            selected_project = state.selected_instance.get("projectName")

        result = {
            "instances": [
                {
                    **instance,
                    "isSelected": selected_port == instance["port"],
                }
                for instance in instances
            ],
            "totalCount": len(instances),
            "selectedPort": selected_port,
            "selectedProject": selected_project,
        }
        if not instances:
            result["message"] = (
                "No Unity Editor instances were discovered. Make sure Unity is running with the AB Unity MCP plugin."
            )
        elif selected_port:
            result["message"] = (
                f"Found {len(instances)} Unity instance(s). Current target: {selected_project} (port {selected_port})."
            )
        else:
            result["message"] = (
                f"Found {len(instances)} Unity instance(s). Use `select <port>` to choose a target."
            )
        return result

    def select_instance(self, port: int) -> Dict[str, Any]:
        instances = self.discover_instances()
        match = next((instance for instance in instances if instance["port"] == port), None)
        if not match:
            raise BackendSelectionError(
                f"No Unity instance was found on port {port}. Run `instances` to refresh discovery."
            )
        self.session_store.update_selection(match)
        return {
            "success": True,
            "message": f"Selected Unity instance {match['projectName']} on port {port}.",
            "instance": match,
        }

    def ping(self, port: Optional[int] = None) -> Dict[str, Any]:
        file_client = self._resolve_file_ipc_client() if port is None else None
        if file_client is not None:
            payload = file_client.ping(timeout=3.0)
            payload["port"] = None
            payload["transport"] = "file-ipc"
            return payload

        resolved_port = self.resolve_port(explicit_port=port, allow_default=True)
        payload = self.client.ping(resolved_port, timeout=3.0)
        payload["port"] = resolved_port
        return payload

    def get_routes(self, port: Optional[int] = None) -> Dict[str, Any]:
        resolved_port = self.resolve_port(explicit_port=port, allow_default=False)
        started_at = time.monotonic()
        try:
            routes = self.client.get_api(resolved_port, "_meta/routes")
        except Exception as exc:
            self._record_history(
                "_meta/routes",
                {},
                resolved_port,
                status="error",
                duration_ms=self._elapsed_ms(started_at),
                error=str(exc),
                transport="get",
            )
            raise
        self._record_history(
            "_meta/routes",
            {},
            resolved_port,
            duration_ms=self._elapsed_ms(started_at),
            transport="get",
        )
        return routes

    def get_context(self, category: str | None = None, port: Optional[int] = None) -> Dict[str, Any]:
        params = {"category": category} if category else {}
        file_client = self._resolve_file_ipc_client() if port is None else None
        if file_client is not None:
            return self._call_route_file_ipc(file_client, "context", params, record_history=True)

        resolved_port = self.resolve_port(explicit_port=port, allow_default=False)
        try:
            # Context can touch Unity APIs, so prefer the bridge queue/main-thread path.
            queued = self.call_route("context", params=params, port=resolved_port, use_queue=True)
        except UnityMCPHTTPError as exc:
            if exc.status_code != 404:
                raise
        else:
            if not self._is_unknown_api_endpoint(queued, route="context"):
                return queued

        try:
            return self._get_context_via_execute_code(category=category, port=resolved_port)
        except UnityMCPHTTPError as exc:
            if exc.status_code != 404:
                raise
            return self._get_context_direct(category=category, port=resolved_port)
        except UnityMCPClientError as exc:
            if not self._is_unknown_api_endpoint_text(str(exc), route="editor/execute-code"):
                raise
            return self._get_context_direct(category=category, port=resolved_port)

    @staticmethod
    def _is_unknown_api_endpoint(payload: Any, route: str | None = None) -> bool:
        if not isinstance(payload, dict):
            return False
        error = payload.get("error")
        if isinstance(error, str) and UnityMCPBackend._is_unknown_api_endpoint_text(error, route=route):
            return True
        nested = payload.get("result")
        return UnityMCPBackend._is_unknown_api_endpoint(nested, route=route)

    @staticmethod
    def _is_unknown_api_endpoint_text(message: str, route: str | None = None) -> bool:
        normalized = str(message or "")
        if "Unknown API endpoint" not in normalized:
            return False
        if route is None:
            return True
        return route in normalized

    def _get_context_via_execute_code(self, category: str | None = None, port: Optional[int] = None) -> Dict[str, Any]:
        resolved_port = self.resolve_port(explicit_port=port, allow_default=False)
        category_literal = "null" if category is None else json.dumps(category, ensure_ascii=True)
        result = self.call_route(
            tool_name_to_route("unity_execute_code"),
            params={
                "code": (
                    "return UnityMCP.Editor.MCPContextManager.GetContextResponse("
                    f"{category_literal}"
                    ");"
                )
            },
            port=resolved_port,
            use_queue=True,
        )
        if self._is_unknown_api_endpoint(result, route=tool_name_to_route("unity_execute_code")):
            raise UnityMCPHTTPError(404, "Unknown API endpoint: editor/execute-code", result)
        if isinstance(result, dict) and result.get("success") is True and isinstance(result.get("result"), dict):
            return result["result"]
        return result

    def _get_context_direct(self, category: str | None = None, port: Optional[int] = None) -> Dict[str, Any]:
        resolved_port = self.resolve_port(explicit_port=port, allow_default=False)
        api_path = "context"
        if category:
            api_path = f"context/{quote(category)}"
        started_at = time.monotonic()
        try:
            payload = self.client.get_api(resolved_port, api_path)
        except Exception as exc:
            self._record_history(
                api_path,
                {},
                resolved_port,
                status="error",
                duration_ms=self._elapsed_ms(started_at),
                error=str(exc),
                transport="get",
            )
            raise
        self._record_history(
            api_path,
            {},
            resolved_port,
            duration_ms=self._elapsed_ms(started_at),
            transport="get",
        )
        return payload

    def get_queue_info(self, port: Optional[int] = None) -> Dict[str, Any]:
        file_client = self._resolve_file_ipc_client() if port is None else None
        if file_client is not None:
            try:
                queue_payload = file_client.call_route("queue/info", timeout=1.0)
            except FileIPCError:
                queue_payload = None
            if isinstance(queue_payload, dict):
                queue_payload.setdefault("transport", "file-ipc")
                queue_payload.setdefault("queueSupported", False)
                queue_payload.setdefault(
                    "message",
                    "File IPC executes each request on Unity's main thread from .umcp/inbox; no Unity queue is required.",
                )
                return queue_payload
            return {
                "transport": "file-ipc",
                "queueSupported": False,
                "activeAgents": 0,
                "executingCount": 0,
                "totalQueued": 0,
                "queued": 0,
                "agentId": self.runtime_agent_id or getattr(self.client, "agent_id", None),
                "message": "File IPC executes each request on Unity's main thread from .umcp/inbox; no Unity queue is required.",
            }

        resolved_port = self.resolve_port(explicit_port=port, allow_default=False)
        started_at = time.monotonic()
        try:
            payload = self.client.get_queue_info(resolved_port)
        except Exception as exc:
            self._record_history(
                "queue/info",
                {},
                resolved_port,
                status="error",
                duration_ms=self._elapsed_ms(started_at),
                error=str(exc),
                transport="get",
            )
            raise
        self._record_history(
            "queue/info",
            {},
            resolved_port,
            duration_ms=self._elapsed_ms(started_at),
            transport="get",
        )
        return payload

    @staticmethod
    def _summarize_console_entries(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        counts = {
            "info": 0,
            "warning": 0,
            "error": 0,
            "other": 0,
        }
        latest_messages: List[str] = []
        stack_trace_count = 0
        highest_severity = "none"
        severity_order = {"none": 0, "info": 1, "warning": 2, "error": 3}
        type_aliases = {
            "log": "info",
            "message": "info",
            "warn": "warning",
            "exception": "error",
            "assert": "error",
        }

        for entry in entries:
            entry_type = str(entry.get("type") or "other").lower()
            entry_type = type_aliases.get(entry_type, entry_type)
            normalized = entry_type if entry_type in counts else "other"
            counts[normalized] += 1
            if entry.get("stackTrace"):
                stack_trace_count += 1
            message = str(entry.get("message") or "").strip()
            if message:
                latest_messages.append(message)
            if severity_order.get(normalized, 0) > severity_order.get(highest_severity, 0):
                highest_severity = normalized

        return {
            "countsByType": counts,
            "stackTraceCount": stack_trace_count,
            "highestSeverity": highest_severity,
            "latestMessages": latest_messages[:5],
        }

    def get_debug_snapshot(
        self,
        port: Optional[int] = None,
        console_count: int = 50,
        message_type: str | None = None,
        issue_limit: int = 20,
        include_hierarchy: bool = False,
    ) -> Dict[str, Any]:
        file_client = self._resolve_file_ipc_client() if port is None else None
        resolved_port = None if file_client is not None else self.resolve_port(explicit_port=port, allow_default=False)
        ping = self.ping(port=resolved_port)
        editor_state = self.call_route_with_recovery(
            "editor/state",
            port=resolved_port,
            recovery_timeout=10.0,
        )
        scene = self.call_route_with_recovery(
            "scene/info",
            port=resolved_port,
            recovery_timeout=10.0,
        )
        project = self.call_route_with_recovery(
            "project/info",
            port=resolved_port,
            recovery_timeout=10.0,
        )
        console_params = {"count": console_count}
        if message_type:
            console_params["type"] = message_type
        console = self.call_route_with_recovery(
            "console/log",
            params=console_params,
            port=resolved_port,
            recovery_timeout=10.0,
        )
        compilation = self.call_route_with_recovery(
            "compilation/errors",
            params={"count": issue_limit},
            port=resolved_port,
            recovery_timeout=10.0,
        )
        missing_references = self.call_route_with_recovery(
            "search/missing-references",
            params={"limit": issue_limit},
            port=resolved_port,
            recovery_timeout=10.0,
        )
        queue = self.get_queue_info(port=resolved_port)

        console_entries = list(console.get("entries") or [])
        console_summary = self._summarize_console_entries(console_entries)
        summary = {
            "port": resolved_port,
            "projectName": ping.get("projectName") or project.get("productName"),
            "activeScene": editor_state.get("activeScene") or scene.get("activeScene"),
            "sceneDirty": bool(editor_state.get("sceneDirty")),
            "isPlaying": bool(editor_state.get("isPlaying")),
            "isCompiling": bool(compilation.get("isCompiling")),
            "consoleEntryCount": int(console.get("count") or len(console_entries)),
            "consoleHighestSeverity": console_summary["highestSeverity"],
            "compilationIssueCount": int(compilation.get("count") or 0),
            "missingReferenceCount": int(missing_references.get("totalFound") or 0),
            "queueActiveAgents": int(queue.get("activeAgents") or queue.get("executingCount") or 0),
            "queueQueuedRequests": int(queue.get("totalQueued") or queue.get("queued") or 0),
        }

        payload: Dict[str, Any] = {
            "summary": summary,
            "ping": ping,
            "project": project,
            "editorState": editor_state,
            "scene": scene,
            "console": console,
            "consoleSummary": console_summary,
            "compilation": compilation,
            "missingReferences": missing_references,
            "queue": queue,
        }
        try:
            payload["cameraDiagnostics"] = self.get_camera_diagnostics(port=resolved_port)
        except Exception as exc:
            payload["cameraDiagnostics"] = {
                "error": str(exc),
            }
        if include_hierarchy:
            payload["hierarchy"] = self.call_route_with_recovery(
                "scene/hierarchy",
                params={"maxDepth": 2, "maxNodes": 40},
                port=resolved_port,
                recovery_timeout=10.0,
            )
        return payload

    def build_debug_dashboard_state(
        self,
        *,
        port: Optional[int] = None,
        console_count: int = 40,
        message_type: str = "all",
        issue_limit: int = 20,
        include_hierarchy: bool = False,
        editor_log_tail: int = 80,
        editor_log_contains: str | None = None,
        ab_umcp_only: bool = False,
        trace_tail: int = 20,
        history_formatter: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        active_port = self.resolve_port(explicit_port=port, allow_default=False)
        snapshot = self.get_debug_snapshot(
            port=active_port,
            console_count=console_count,
            message_type=message_type,
            issue_limit=issue_limit,
            include_hierarchy=include_hierarchy,
        )
        raw_history = self.get_history()
        recent_history = raw_history[-trace_tail:] if trace_tail > 0 else list(raw_history)
        rendered_history = (
            [history_formatter(entry) for entry in recent_history]
            if history_formatter is not None
            else list(recent_history)
        )
        editor_log = self.get_editor_log(
            tail=editor_log_tail,
            contains=editor_log_contains,
            ab_umcp_only=ab_umcp_only,
        )
        return {
            "title": "Unity Debug Dashboard",
            "generatedAt": time.time(),
            "preferences": normalize_debug_preferences(self.get_debug_preferences()),
            "snapshot": snapshot,
            "bridge": self.get_bridge_diagnostics(port=active_port),
            "editorLog": editor_log,
            "trace": {
                "tail": trace_tail,
                "entries": rendered_history,
                "rawEntries": recent_history,
            },
            "request": {
                "port": active_port,
                "consoleCount": console_count,
                "messageType": message_type,
                "issueLimit": issue_limit,
                "includeHierarchy": include_hierarchy,
                "editorLogTail": editor_log_tail,
                "editorLogContains": editor_log_contains,
                "abUmcpOnly": ab_umcp_only,
                "traceTail": trace_tail,
            },
        }

    def build_debug_dashboard_live_state(
        self,
        *,
        port: Optional[int] = None,
        console_count: int = 20,
        message_type: str = "all",
        trace_tail: int = 20,
        history_formatter: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        active_port = self.resolve_port(explicit_port=port, allow_default=False)
        ping = self.ping(port=active_port)
        editor_state = self.call_route_with_recovery(
            "editor/state",
            port=active_port,
            recovery_timeout=5.0,
        )
        console_params = {"count": console_count}
        if message_type:
            console_params["type"] = message_type
        console = self.call_route_with_recovery(
            "console/log",
            params=console_params,
            port=active_port,
            recovery_timeout=5.0,
        )
        queue = self.get_queue_info(port=active_port)
        console_entries = list(console.get("entries") or [])
        console_summary = self._summarize_console_entries(console_entries)
        raw_history = self.get_history()
        recent_history = raw_history[-trace_tail:] if trace_tail > 0 else list(raw_history)
        rendered_history = (
            [history_formatter(entry) for entry in recent_history]
            if history_formatter is not None
            else list(recent_history)
        )

        snapshot = {
            "summary": {
                "port": active_port,
                "projectName": ping.get("projectName"),
                "activeScene": editor_state.get("activeScene"),
                "sceneDirty": bool(editor_state.get("sceneDirty")),
                "isPlaying": bool(editor_state.get("isPlaying")),
                "isCompiling": bool(editor_state.get("isCompiling")),
                "consoleEntryCount": int(console.get("count") or len(console_entries)),
                "consoleHighestSeverity": console_summary["highestSeverity"],
                "queueActiveAgents": int(queue.get("activeAgents") or queue.get("executingCount") or 0),
                "queueQueuedRequests": int(queue.get("totalQueued") or queue.get("queued") or 0),
            },
            "ping": ping,
            "editorState": editor_state,
            "console": console,
            "consoleSummary": console_summary,
            "queue": queue,
        }

        return {
            "title": "Unity Debug Dashboard",
            "generatedAt": time.time(),
            "preferences": normalize_debug_preferences(self.get_debug_preferences()),
            "snapshot": snapshot,
            "trace": {
                "tail": trace_tail,
                "entries": rendered_history,
                "rawEntries": recent_history,
            },
            "request": {
                "port": active_port,
                "consoleCount": console_count,
                "messageType": message_type,
                "traceTail": trace_tail,
                "mode": "live",
            },
        }

    def get_camera_diagnostics(
        self,
        port: Optional[int] = None,
        camera_name: str = "MainCamera",
    ) -> Dict[str, Any]:
        resolved_port = self.resolve_port(explicit_port=port, allow_default=False)
        escaped_camera_name = json.dumps(camera_name)
        result = self.call_route_with_recovery(
            tool_name_to_route("unity_execute_code"),
            params={
                "code": (
                    f"var cam = UnityEngine.GameObject.Find({escaped_camera_name});"
                    " if (cam == null) return new { found = false, cameraName = \"MainCamera\" };"
                    " var camera = cam.GetComponent<UnityEngine.Camera>();"
                    " var cameraDataType = System.Type.GetType("
                    "\"UnityEngine.Rendering.Universal.UniversalAdditionalCameraData, Unity.RenderPipelines.Universal.Runtime\""
                    ");"
                    " object cameraData = cameraDataType != null ? cam.GetComponent(cameraDataType) : null;"
                    " string rendererName = \"none\";"
                    " if (cameraData != null) {"
                    "   var rendererProp = cameraDataType.GetProperty(\"scriptableRenderer\");"
                    "   var renderer = rendererProp != null ? rendererProp.GetValue(cameraData) : null;"
                    "   if (renderer != null) rendererName = renderer.ToString();"
                    " }"
                    " var pipeline = UnityEngine.Rendering.GraphicsSettings.currentRenderPipeline;"
                    " return new {"
                    "   found = true,"
                    "   cameraName = cam.name,"
                    "   clearFlags = camera != null ? camera.clearFlags.ToString() : \"none\","
                    "   orthographic = camera != null && camera.orthographic,"
                    "   backgroundColor = camera != null ? camera.backgroundColor.ToString() : \"none\","
                    "   rendererName = rendererName,"
                    "   pipeline = pipeline != null ? pipeline.name : \"builtin\""
                    " };"
                )
            },
            port=resolved_port,
            recovery_timeout=10.0,
        )
        if isinstance(result, dict):
            nested = result.get("result")
            if isinstance(nested, dict):
                return nested
            return result
        return {"result": result}

    def get_editor_log(
        self,
        path: Path | None = None,
        tail: int = 120,
        contains: str | None = None,
        ab_umcp_only: bool = False,
        context: int = 0,
    ) -> Dict[str, Any]:
        log_path = Path(path) if path else get_default_editor_log_path()
        max_lines = max(1, int(tail))
        context_lines = max(0, int(context))
        filters = []
        if contains:
            filters.append(str(contains))
        if ab_umcp_only:
            filters.append("[AB-UMCP]")

        summary: Dict[str, Any] = {
            "path": str(log_path),
            "status": "missing",
            "tail": max_lines,
            "context": context_lines,
            "filters": filters,
            "totalLinesScanned": 0,
            "matchedCount": 0,
            "returnedCount": 0,
        }

        try:
            with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                returned_entries: deque[dict[str, Any]] = deque(maxlen=max_lines)
                preceding_lines: deque[tuple[int, str]] = deque(maxlen=context_lines)
                include_until_line = 0
                last_emitted_line = 0

                def emit_entry(line_number: int, text: str, matched: bool) -> None:
                    nonlocal last_emitted_line
                    if line_number <= last_emitted_line and returned_entries:
                        latest = returned_entries[-1]
                        if latest.get("lineNumber") == line_number:
                            latest["matched"] = bool(latest.get("matched")) or matched
                        return
                    returned_entries.append(
                        {
                            "lineNumber": line_number,
                            "text": text,
                            "matched": matched,
                        }
                    )
                    last_emitted_line = line_number

                for line_number, raw_line in enumerate(handle, start=1):
                    line = raw_line.rstrip("\r\n")
                    summary["totalLinesScanned"] += 1
                    is_match = all(token in line for token in filters)

                    if not filters:
                        emit_entry(line_number, line, True)
                    elif context_lines <= 0:
                        if is_match:
                            summary["matchedCount"] += 1
                            emit_entry(line_number, line, True)
                    else:
                        if is_match:
                            summary["matchedCount"] += 1
                            for previous_line_number, previous_text in preceding_lines:
                                emit_entry(previous_line_number, previous_text, False)
                            emit_entry(line_number, line, True)
                            include_until_line = max(include_until_line, line_number + context_lines)
                        elif line_number <= include_until_line:
                            emit_entry(line_number, line, False)

                    if context_lines > 0:
                        preceding_lines.append((line_number, line))
        except FileNotFoundError:
            return {
                "title": "Unity Editor Log",
                "summary": summary,
                "lines": [],
                "entries": [],
            }
        except PermissionError as exc:
            summary["status"] = "access-denied"
            summary["error"] = str(exc)
            return {
                "title": "Unity Editor Log",
                "summary": summary,
                "lines": [],
                "entries": [],
            }
        except OSError as exc:
            summary["status"] = "error"
            summary["error"] = str(exc)
            return {
                "title": "Unity Editor Log",
                "summary": summary,
                "lines": [],
                "entries": [],
            }

        entries = list(returned_entries)
        lines = [str(entry.get("text") or "") for entry in entries]
        summary["status"] = "ok"
        summary["returnedCount"] = len(lines)

        if not filters:
            summary["matchedCount"] = summary["returnedCount"]

        return {
            "title": "Unity Editor Log",
            "summary": summary,
            "lines": lines,
            "entries": entries,
        }

    def iter_editor_log(
        self,
        path: Path | None = None,
        tail: int = 40,
        contains: str | None = None,
        ab_umcp_only: bool = False,
        duration: float | None = None,
        poll_interval: float = 0.5,
    ):
        if poll_interval <= 0:
            raise ValueError("poll_interval must be greater than 0.")

        payload = self.get_editor_log(
            path=path,
            tail=tail,
            contains=contains,
            ab_umcp_only=ab_umcp_only,
        )
        summary = payload.get("summary") or {}
        status = summary.get("status")
        log_path = Path(summary.get("path") or (path or get_default_editor_log_path()))

        if status == "missing":
            raise FileNotFoundError(f"Unity Editor.log was not found at `{log_path}`.")
        if status == "access-denied":
            raise PermissionError(summary.get("error") or f"Access was denied reading `{log_path}`.")
        if status != "ok":
            raise OSError(summary.get("error") or f"Could not read `{log_path}`.")

        filters: list[str] = []
        if contains:
            filters.append(str(contains))
        if ab_umcp_only:
            filters.append("[AB-UMCP]")

        for line in payload.get("lines") or []:
            yield line

        deadline = None if duration is None else (time.monotonic() + max(0.0, duration))
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(0, os.SEEK_END)
            while True:
                if deadline is not None and time.monotonic() >= deadline:
                    return
                position = handle.tell()
                raw_line = handle.readline()
                if not raw_line:
                    time.sleep(poll_interval)
                    handle.seek(position)
                    continue
                line = raw_line.rstrip("\r\n")
                if all(token in line for token in filters):
                    yield line

    def emit_unity_breadcrumb(
        self,
        message: str,
        port: Optional[int] = None,
        level: str = "info",
        *,
        record_history: bool = True,
        force: bool = False,
    ) -> Dict[str, Any]:
        normalized_level = str(level or "info").lower()
        if normalized_level not in {"info", "warning", "error"}:
            raise ValueError("level must be one of: info, warning, error.")
        if not force and not self.should_emit_unity_breadcrumbs():
            payload = {
                "success": False,
                "skipped": True,
                "reason": "unityConsoleBreadcrumbs disabled",
                "message": message,
                "level": normalized_level,
            }
            if record_history:
                self._record_history(
                    "debug/breadcrumb",
                    {"message": message, "level": normalized_level},
                    port,
                    transport="local",
                    note="Skipped Unity console breadcrumb",
                )
            return payload

        file_client = self._resolve_file_ipc_client() if port is None else None
        if file_client is not None:
            started_at = time.monotonic()
            try:
                result = self._call_route_file_ipc(
                    file_client,
                    "debug/breadcrumb",
                    {"message": message, "level": normalized_level},
                    record_history=False,
                )
            except Exception as exc:
                if record_history:
                    self._record_history(
                        "debug/breadcrumb",
                        {"message": message, "level": normalized_level},
                        None,
                        status="error",
                        duration_ms=self._elapsed_ms(started_at),
                        error=str(exc),
                        transport="file-ipc",
                        note="Emit Unity console breadcrumb",
                    )
                raise

            if record_history:
                self._record_history(
                    "debug/breadcrumb",
                    {"message": message, "level": normalized_level},
                    None,
                    duration_ms=self._elapsed_ms(started_at),
                    transport="file-ipc",
                    note="Emit Unity console breadcrumb",
                )
            return result

        resolved_port = self.resolve_port(explicit_port=port, allow_default=False)
        escaped_message = json.dumps(f"[CLI-TRACE] {message}")
        if normalized_level == "warning":
            logger_call = f"UnityEngine.Debug.LogWarning({escaped_message});"
            log_type = "UnityEngine.LogType.Warning"
        elif normalized_level == "error":
            logger_call = f"UnityEngine.Debug.LogError({escaped_message});"
            log_type = "UnityEngine.LogType.Error"
        else:
            logger_call = f"UnityEngine.Debug.Log({escaped_message});"
            log_type = "UnityEngine.LogType.Log"

        started_at = time.monotonic()
        try:
            result = self.call_route(
                tool_name_to_route("unity_execute_code"),
                params={
                    "code": (
                        f"var __cliTraceLogType = {log_type};\n"
                        f"var __cliTracePrevious = UnityEngine.Application.GetStackTraceLogType(__cliTraceLogType);\n"
                        "try\n"
                        "{\n"
                        "    UnityEngine.Application.SetStackTraceLogType(__cliTraceLogType, UnityEngine.StackTraceLogType.None);\n"
                        f"    {logger_call}\n"
                        "}\n"
                        "finally\n"
                        "{\n"
                        "    UnityEngine.Application.SetStackTraceLogType(__cliTraceLogType, __cliTracePrevious);\n"
                        "}\n"
                        f"return new {{ success = true, level = {json.dumps(normalized_level)}, message = {escaped_message} }};"
                    )
                },
                port=resolved_port,
                record_history=False,
            )
        except Exception as exc:
            if record_history:
                self._record_history(
                    "debug/breadcrumb",
                    {"message": message, "level": normalized_level},
                    resolved_port,
                    status="error",
                    duration_ms=self._elapsed_ms(started_at),
                    error=str(exc),
                    transport="tool",
                    note="Emit Unity console breadcrumb",
                )
            raise

        if record_history:
            self._record_history(
                "debug/breadcrumb",
                {"message": message, "level": normalized_level},
                resolved_port,
                duration_ms=self._elapsed_ms(started_at),
                transport="tool",
                note="Emit Unity console breadcrumb",
            )
        return result

    def get_bridge_diagnostics(
        self,
        port: Optional[int] = None,
        ping_timeout: float = 0.75,
    ) -> Dict[str, Any]:
        state = self.session_store.load()
        registry_snapshot = self._read_registry_snapshot()
        registry_entries = list(registry_snapshot.get("entries") or [])
        discovery = self.discover_instances()

        candidate_ports: set[int] = {self.default_port}
        candidate_ports.update(range(self.port_range_start, self.port_range_end + 1))
        if port is not None:
            candidate_ports.add(int(port))
        if state.selected_port is not None:
            candidate_ports.add(int(state.selected_port))
        for entry in registry_entries:
            entry_port = self._coerce_int(entry.get("port"))
            if entry_port is not None:
                candidate_ports.add(entry_port)

        checks: list[dict[str, Any]] = []
        responding_ports: list[int] = []
        registry_ports = {
            self._coerce_int(entry.get("port"))
            for entry in registry_entries
            if self._coerce_int(entry.get("port")) is not None
        }
        discovered_ports = {instance["port"] for instance in discovery}

        for candidate_port in sorted(candidate_ports):
            try:
                ping = self.client.ping(candidate_port, timeout=ping_timeout)
                checks.append(
                    {
                        "port": candidate_port,
                        "status": "ok",
                        "sourceHints": {
                            "selected": candidate_port == state.selected_port,
                            "registry": candidate_port in registry_ports,
                            "discovered": candidate_port in discovered_ports,
                            "default": candidate_port == self.default_port,
                        },
                        "projectName": ping.get("projectName"),
                        "projectPath": ping.get("projectPath"),
                        "unityVersion": ping.get("unityVersion"),
                        "platform": ping.get("platform"),
                    }
                )
                responding_ports.append(candidate_port)
            except UnityMCPClientError as exc:
                message = str(exc)
                lowered = message.lower()
                if "timed out" in lowered:
                    status = "timeout"
                elif "could not reach" in lowered or "actively refused" in lowered or "failed to respond" in lowered:
                    status = "unreachable"
                else:
                    status = "error"
                checks.append(
                    {
                        "port": candidate_port,
                        "status": status,
                        "sourceHints": {
                            "selected": candidate_port == state.selected_port,
                            "registry": candidate_port in registry_ports,
                            "discovered": candidate_port in discovered_ports,
                            "default": candidate_port == self.default_port,
                        },
                        "error": message,
                    }
                )

        preferred_port = port if port is not None else state.selected_port
        port_suffix = f" --port {preferred_port}" if preferred_port is not None else " --port <port>"

        recommended_commands: list[str] = []

        def add_command(command: str) -> None:
            if command not in recommended_commands:
                recommended_commands.append(command)

        findings: list[dict[str, Any]] = []
        if not responding_ports:
            findings.append(
                {
                    "severity": "error",
                    "title": "No Responding Unity Bridge Ports",
                    "detail": "No Unity bridge responded across the configured scan range.",
                }
            )
            add_command("cli-anything-unity-mcp instances")
        if state.selected_port is not None and state.selected_port not in responding_ports:
            findings.append(
                {
                    "severity": "warning",
                    "title": "Selected Port Is Not Responding",
                    "detail": f"The current session still points at port {state.selected_port}, but that port did not answer the latest bridge ping.",
                }
            )
            add_command("cli-anything-unity-mcp instances")
            if responding_ports:
                add_command(f"cli-anything-unity-mcp select {responding_ports[0]}")
        if registry_entries and not discovery:
            findings.append(
                {
                    "severity": "warning",
                    "title": "Registry Has Entries But Discovery Is Empty",
                    "detail": "The Unity registry still has instance entries, but none of them were confirmed as healthy live editors. The registry may be stale or Unity may have moved to a new bridge port.",
                }
            )
            add_command(f"cli-anything-unity-mcp --json debug bridge{port_suffix}")
        if discovery and registry_snapshot.get("status") == "access-denied":
            findings.append(
                {
                    "severity": "warning",
                    "title": "Registry File Access Denied",
                    "detail": "Unity is reachable, but the CLI cannot read the shared registry file because access was denied. The CLI can still operate by falling back to direct port scanning.",
                    "error": registry_snapshot.get("error"),
                }
            )
            add_command("cli-anything-unity-mcp instances")
        elif discovery and not registry_entries:
            findings.append(
                {
                    "severity": "warning",
                    "title": "Discovery Is Running Without Registry Entries",
                    "detail": "Unity editors answered direct port probes, but the shared registry file is empty or unreadable. The CLI can still operate by falling back to direct port scanning.",
                }
            )
            add_command("cli-anything-unity-mcp instances")
        if len(responding_ports) > 1:
            findings.append(
                {
                    "severity": "warning",
                    "title": "Multiple Responding Unity Editors",
                    "detail": f"Multiple Unity bridge ports responded: {', '.join(str(item) for item in responding_ports)}.",
                }
            )
            add_command("cli-anything-unity-mcp instances")

        assessment = "healthy"
        if any(item["severity"] == "error" for item in findings):
            assessment = "error"
        elif findings:
            assessment = "warning"

        connection_mode = "unreachable"
        if responding_ports:
            if registry_entries:
                connection_mode = "registry-backed"
            elif discovery:
                connection_mode = "portscan-fallback"
            else:
                connection_mode = "direct-port-probe"

        if responding_ports:
            add_command(f"cli-anything-unity-mcp --json debug snapshot --console-count 100 --include-hierarchy{port_suffix}")
            add_command(f"cli-anything-unity-mcp --json debug doctor --recent-commands 8{port_suffix}")

        return {
            "title": "Unity Bridge Diagnostics",
            "summary": {
                "assessment": assessment,
                "connectionMode": connection_mode,
                "canReachUnity": bool(responding_ports),
                "selectedPort": state.selected_port,
                "selectedProject": (state.selected_instance or {}).get("projectName"),
                "registryPath": str(self.registry_path),
                "registryStatus": registry_snapshot.get("status"),
                "registryError": registry_snapshot.get("error"),
                "registryEntryCount": len(registry_entries),
                "discoveredInstanceCount": len(discovery),
                "respondingPortCount": len(responding_ports),
                "defaultPort": self.default_port,
                "scanRange": {"start": self.port_range_start, "end": self.port_range_end},
            },
            "selectedInstance": state.selected_instance,
            "registry": registry_snapshot,
            "registryEntries": registry_entries,
            "instances": discovery,
            "portChecks": checks,
            "findings": findings,
            "recommendedCommands": recommended_commands,
        }

    def get_tool_info(self, tool_name: str, port: Optional[int] = None) -> Dict[str, Any]:
        tool = get_upstream_tool(tool_name)
        if tool is None:
            route = tool_name_to_route(tool_name)
            tool = {
                "name": tool_name,
                "description": "Derived from CLI route resolution rules.",
                "route": route,
                "category": route.split("/", 1)[0],
                "tier": "derived",
                "execution": "route",
                "unsupported": False,
                "inputSchema": {"type": "object", "properties": {}},
            }

        payload = dict(tool)
        route = payload.get("route")
        if route:
            payload["resolvedRoute"] = route
        payload.update(summarize_schema(payload.get("inputSchema")))
        if port is not None:
            try:
                live_routes = self.get_routes(port=port).get("routes", [])
                payload["liveAvailable"] = bool(route and route in live_routes)
            except (BackendSelectionError, UnityMCPClientError):
                payload["liveAvailable"] = False
        return payload

    def get_tool_template(
        self,
        tool_name: str,
        include_optional: bool = False,
        port: Optional[int] = None,
    ) -> Dict[str, Any]:
        info = self.get_tool_info(tool_name, port=port)
        template_key = "fullTemplate" if include_optional else "requiredTemplate"
        return {
            "name": info.get("name"),
            "route": info.get("resolvedRoute") or info.get("route"),
            "tier": info.get("tier"),
            "category": info.get("category"),
            "required": info.get("required", []),
            "optional": info.get("optional", []),
            "template": info.get(template_key, {}),
            "includeOptional": include_optional,
        }

    def list_upstream_tools(
        self,
        category: str | None = None,
        tier: str | None = None,
        search: str | None = None,
        include_unsupported: bool = False,
        port: Optional[int] = None,
        merge_live: bool = False,
    ) -> Dict[str, Any]:
        tools = iter_upstream_tools(
            category=category,
            tier=tier,
            search=search,
            include_unsupported=include_unsupported,
        )

        live_routes: List[str] = []
        dynamic_only: List[Dict[str, Any]] = []
        if merge_live:
            try:
                live_routes = list(self.get_routes(port=port).get("routes", []))
            except (BackendSelectionError, UnityMCPClientError):
                live_routes = []

            known_names = {tool["name"] for tool in tools}
            for route in sorted(live_routes):
                name = route_to_tool_name(route)
                if name in known_names:
                    continue
                dynamic_tool = {
                    "name": name,
                    "route": route,
                    "description": "Derived from the live Unity plugin route catalog.",
                    "tier": "dynamic",
                    "category": route.split("/", 1)[0],
                    "execution": "route",
                    "unsupported": False,
                    "inputSchema": {"type": "object", "properties": {}},
                    "liveAvailable": True,
                }
                if category and dynamic_tool["category"] != category.lower():
                    continue
                if tier and dynamic_tool["tier"] != tier.lower():
                    continue
                if search:
                    lowered = search.lower()
                    if lowered not in dynamic_tool["name"] and lowered not in dynamic_tool["description"].lower():
                        continue
                dynamic_only.append(dynamic_tool)

        live_route_set = set(live_routes)
        payload_tools: List[Dict[str, Any]] = []
        for tool in tools:
            item = dict(tool)
            route = item.get("route")
            if merge_live:
                item["liveAvailable"] = bool(route and route in live_route_set)
            payload_tools.append(item)
        payload_tools.extend(dynamic_only)
        payload_tools.sort(key=lambda item: str(item.get("name", "")))

        return {
            "tools": payload_tools,
            "totalCount": len(payload_tools),
            "filters": {
                "category": category,
                "tier": tier,
                "search": search,
                "includeUnsupported": include_unsupported,
                "mergeLive": merge_live,
            },
            "dynamicOnlyCount": len(dynamic_only),
        }

    def list_advanced_tools(
        self,
        category: str | None = None,
        search: str | None = None,
        port: Optional[int] = None,
        merge_live: bool = True,
    ) -> Dict[str, Any]:
        catalog = self.list_upstream_tools(
            category=category,
            tier="advanced",
            search=search,
            port=port,
            merge_live=merge_live,
        )
        tools = catalog["tools"]
        grouped: Dict[str, List[str]] = {}
        for tool in tools:
            tool_category = str(tool.get("category") or "misc")
            grouped.setdefault(tool_category, []).append(str(tool["name"]))

        if category:
            return {
                "category": category.lower(),
                "tools": tools,
                "totalCount": len(tools),
                "dynamicOnlyCount": catalog["dynamicOnlyCount"],
            }

        return {
            "totalAdvancedTools": len(tools),
            "dynamicTools": catalog["dynamicOnlyCount"],
            "categories": {key: sorted(value) for key, value in sorted(grouped.items())},
        }

    def get_tool_coverage(
        self,
        category: str | None = None,
        status: str | None = None,
        search: str | None = None,
        include_unsupported: bool = True,
        summary_only: bool = False,
        next_batch_limit: int = 0,
        fixture_plan: bool = False,
        support_plan: bool = False,
        handoff_plan: bool = False,
    ) -> Dict[str, Any]:
        return build_tool_coverage_matrix(
            category=category,
            status=status,
            search=search,
            include_unsupported=include_unsupported,
            summary_only=summary_only,
            next_batch_limit=next_batch_limit,
            fixture_plan=fixture_plan,
            support_plan=support_plan,
            handoff_plan=handoff_plan,
        )

    def call_route_with_recovery(
        self,
        route: str,
        params: Optional[Dict[str, Any]] = None,
        port: Optional[int] = None,
        use_get: bool = False,
        use_queue: Optional[bool] = None,
        record_history: bool = True,
        recovery_timeout: float = 15.0,
        recovery_interval: float = 0.5,
    ) -> Any:
        deadline = time.monotonic() + recovery_timeout
        last_exc: Exception | None = None

        while True:
            try:
                return self.call_route(
                    route,
                    params=params,
                    port=port,
                    use_get=use_get,
                    use_queue=use_queue,
                    record_history=record_history,
                )
            except (BackendSelectionError, UnityMCPConnectionError) as exc:
                last_exc = exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if last_exc:
                    raise last_exc
                raise BackendSelectionError("Unity instance recovery timed out.")
            try:
                self.wait_for_selected_instance(
                    timeout=min(recovery_interval, remaining),
                    interval=min(recovery_interval, remaining),
                )
            except BackendSelectionError:
                continue

    def _resolve_file_ipc_client(self) -> FileIPCClient | None:
        """If the selected instance uses file IPC, return its client."""
        state = self.session_store.load()
        inst = state.selected_instance
        if not inst:
            return None
        if inst.get("transport") != "file-ipc":
            return None
        project_path = inst.get("projectPath")
        if not project_path:
            return None
        return self._get_file_ipc_client(project_path)

    def call_route(
        self,
        route: str,
        params: Optional[Dict[str, Any]] = None,
        port: Optional[int] = None,
        use_get: bool = False,
        use_queue: Optional[bool] = None,
        record_history: bool = True,
    ) -> Any:
        # Check if the selected instance uses file IPC
        file_client = self._resolve_file_ipc_client() if port is None else None
        if file_client is not None:
            return self._call_route_file_ipc(file_client, route, params, record_history)

        resolved_port = self.resolve_port(explicit_port=port, allow_default=False)
        payload = params or {}
        transport = "get" if use_get else ("queue" if use_queue or (use_queue is None and self.client.use_queue) else "post")
        started_at = time.monotonic()
        try:
            if use_get:
                result = self.client.get_api(resolved_port, route, query=payload or None)
            else:
                try:
                    result = self.client.call_route(resolved_port, route, payload, use_queue=use_queue)
                except TypeError:
                    result = self.client.call_route(resolved_port, route, payload)
        except Exception as exc:
            if record_history and route not in self.NON_HISTORY_ROUTES:
                self._record_history(
                    route,
                    payload,
                    resolved_port,
                    status="error",
                    duration_ms=self._elapsed_ms(started_at),
                    error=str(exc),
                    transport=transport,
                )
            raise
        if record_history and route not in self.NON_HISTORY_ROUTES:
            self._record_history(
                route,
                payload,
                resolved_port,
                duration_ms=self._elapsed_ms(started_at),
                transport=transport,
            )
        return result

    def _call_route_file_ipc(
        self,
        file_client: FileIPCClient,
        route: str,
        params: Optional[Dict[str, Any]],
        record_history: bool,
    ) -> Any:
        """Execute a route via file IPC transport."""
        payload = params or {}
        started_at = time.monotonic()
        try:
            result = file_client.call_route(route, params=payload)
        except FileIPCError as exc:
            if record_history and route not in self.NON_HISTORY_ROUTES:
                self._record_history(
                    route,
                    payload,
                    None,
                    status="error",
                    duration_ms=self._elapsed_ms(started_at),
                    error=str(exc),
                    transport="file-ipc",
                )
            raise UnityMCPClientError(str(exc)) from exc
        if record_history and route not in self.NON_HISTORY_ROUTES:
            self._record_history(
                route,
                payload,
                None,
                duration_ms=self._elapsed_ms(started_at),
                transport="file-ipc",
            )
        return result

    def call_tool(
        self,
        tool_name: str,
        params: Optional[Dict[str, Any]] = None,
        port: Optional[int] = None,
        use_queue: Optional[bool] = None,
    ) -> Any:
        payload = dict(params or {})
        alias_map = self.TOOL_PARAM_ALIASES.get(tool_name, {})
        for source_key, target_key in alias_map.items():
            if source_key in payload and target_key not in payload:
                payload[target_key] = payload[source_key]

        if tool_name == "unity_list_instances":
            return self.list_instances()
        if tool_name == "unity_select_instance":
            if "port" not in payload:
                raise ValueError("unity_select_instance requires a numeric `port` parameter.")
            return self.select_instance(int(payload["port"]))
        if tool_name == "unity_get_project_context":
            category = payload.get("category")
            return self.get_context(category=str(category) if category else None, port=port)
        if tool_name == "unity_queue_info":
            return self.get_queue_info(port=port)
        if tool_name == "unity_queue_ticket_status":
            ticket_id = payload.get("ticketId", payload.get("ticket_id"))
            if ticket_id is None:
                raise ValueError("unity_queue_ticket_status requires `ticketId`.")
            resolved_port = self.resolve_port(explicit_port=port, allow_default=False)
            return self.client.get_api(resolved_port, "queue/status", query={"ticketId": ticket_id})
        if tool_name == "unity_list_advanced_tools":
            category = payload.get("category")
            search = payload.get("search")
            return self.list_advanced_tools(
                category=str(category) if category else None,
                search=str(search) if search else None,
                port=port,
                merge_live=True,
            )
        if tool_name == "unity_advanced_tool":
            nested_tool = payload.get("tool")
            nested_params = payload.get("params") or {}
            if not nested_tool:
                raise ValueError("unity_advanced_tool requires a `tool` parameter.")
            if not isinstance(nested_params, dict):
                raise ValueError("unity_advanced_tool expects `params` to be a JSON object.")
            return self.call_tool(str(nested_tool), params=nested_params, port=port)

        route = tool_name_to_route(tool_name)
        use_get = route in {"queue/status"}
        return self.call_route(route, params=payload, port=port, use_get=use_get, use_queue=use_queue)

    def known_tools(
        self,
        category: str | None = None,
        tier: str | None = None,
        search: str | None = None,
        include_unsupported: bool = False,
    ) -> List[Dict[str, str]]:
        return iter_known_tools(
            category=category,
            tier=tier,
            search=search,
            include_unsupported=include_unsupported,
        )

    def dynamic_tools(self, port: Optional[int] = None, category: str | None = None) -> List[Dict[str, str]]:
        routes_payload = self.get_routes(port=port)
        routes = routes_payload.get("routes", [])
        tools: List[Dict[str, str]] = []
        for route in sorted(routes):
            derived_category = route.split("/", 1)[0]
            if category and derived_category != category.lower():
                continue
            tools.append(
                {
                    "name": route_to_tool_name(route),
                    "route": route,
                    "description": "Derived from the live Unity plugin route catalog.",
                }
            )
        return tools

    def get_history(self) -> List[Dict[str, Any]]:
        return self.session_store.load().history

    def clear_history(self) -> SessionState:
        return self.session_store.clear_history()

    def resolve_port(
        self,
        explicit_port: Optional[int] = None,
        allow_default: bool = False,
    ) -> int:
        if explicit_port is not None:
            return explicit_port

        state = self.session_store.load()
        instances = self.discover_instances()
        instances = self._reconcile_selection(state, instances)
        state = self.session_store.load()

        # If a file-IPC instance is selected (no port), the caller should have
        # used _resolve_file_ipc_client() before calling resolve_port().
        # But we still return a sentinel to avoid crashing.
        if state.selected_instance and state.selected_instance.get("transport") == "file-ipc":
            # Return 0 as sentinel — call_route already bypasses this path for file IPC
            return 0

        if state.selected_port and any(inst["port"] == state.selected_port for inst in instances):
            return state.selected_port

        if len(instances) == 1:
            self.session_store.update_selection(instances[0])
            return instances[0]["port"]

        if len(instances) > 1:
            labels = ", ".join(
                f"{instance['projectName']}:{instance.get('port') or 'file-ipc'}" for instance in instances
            )
            raise BackendSelectionError(
                "Multiple Unity instances are running. Use `instances` and then `select <port>` first. "
                f"Available: {labels}"
            )

        if allow_default:
            return self.default_port

        if state.selected_port is not None:
            return state.selected_port

        raise BackendSelectionError(
            "No Unity instance is currently selected and none were auto-discovered."
        )

    def wait_for_selected_instance(
        self,
        timeout: float = 15.0,
        interval: float = 0.5,
    ) -> Dict[str, Any]:
        state = self.session_store.load()
        selected_instance = state.selected_instance or {}
        selected_path = selected_instance.get("projectPath")
        selected_port = state.selected_port
        deadline = time.monotonic() + timeout
        last_instances: List[Dict[str, Any]] = []

        while time.monotonic() < deadline:
            instances = self.discover_instances()
            last_instances = instances

            if selected_path:
                match = next(
                    (instance for instance in instances if instance.get("projectPath") == selected_path),
                    None,
                )
                if match:
                    self.session_store.update_selection(match)
                    return match

            if selected_port is not None:
                match = next((instance for instance in instances if instance["port"] == selected_port), None)
                if match:
                    self.session_store.update_selection(match)
                    return match

            if len(instances) == 1 and not selected_path:
                self.session_store.update_selection(instances[0])
                return instances[0]

            time.sleep(interval)

        if selected_path:
            raise BackendSelectionError(
                f"Timed out waiting for Unity instance recovery for project {selected_path}."
            )
        if selected_port is not None:
            raise BackendSelectionError(
                f"Timed out waiting for Unity instance recovery for port {selected_port}."
            )
        labels = ", ".join(f"{instance['projectName']}:{instance['port']}" for instance in last_instances)
        raise BackendSelectionError(
            "Timed out waiting for a Unity instance to become available."
            + (f" Available later: {labels}" if labels else "")
        )

    def _get_file_ipc_client(self, project_path: str | Path) -> FileIPCClient:
        """Get or create a FileIPCClient for a Unity project path."""
        key = str(project_path)
        if key not in self._file_ipc_clients:
            agent_id = getattr(self.client, "agent_id", "cli-anything-unity-mcp")
            self._file_ipc_clients[key] = FileIPCClient(
                project_path,
                agent_id=agent_id,
            )
        return self._file_ipc_clients[key]

    def _get_file_ipc_search_paths(self) -> List[Path]:
        """Build the list of project paths to check for file IPC bridges."""
        paths = list(self.file_ipc_paths)

        # Also check registry entries for project paths
        for entry in self._read_registry_entries():
            project_path = entry.get("projectPath")
            if project_path:
                p = Path(project_path)
                if p not in paths:
                    paths.append(p)

        # Check the selected instance's project path
        state = self.session_store.load()
        if state.selected_instance:
            project_path = state.selected_instance.get("projectPath")
            if project_path:
                p = Path(project_path)
                if p not in paths:
                    paths.append(p)

        return paths

    def _discover_file_ipc_instances(self) -> List[Dict[str, Any]]:
        """Discover Unity projects that have an active file IPC bridge."""
        if self.transport == "http":
            return []

        instances: List[Dict[str, Any]] = []
        for project_path in self._get_file_ipc_search_paths():
            ipc_client = self._get_file_ipc_client(project_path)
            try:
                ping_data = ipc_client.ping()
            except FileIPCError:
                continue

            instance = self._normalize_instance({
                **ping_data,
                "port": None,
                "source": "file-ipc",
                "transport": "file-ipc",
            })
            instance["transport"] = "file-ipc"
            instances.append(instance)

        return instances

    def discover_instances(self) -> List[Dict[str, Any]]:
        instances_by_port: Dict[int, Dict[str, Any]] = {}
        file_ipc_instances: List[Dict[str, Any]] = []

        # HTTP discovery (skip if transport is "file")
        if self.transport != "file":
            for entry in self._read_registry_entries():
                port = self._coerce_int(entry.get("port"))
                if not port:
                    continue
                info = self._safe_ping(port)
                if not info:
                    continue
                instances_by_port[port] = self._normalize_instance(
                    {**entry, **info, "port": port, "source": "registry"}
                )

            for port in range(self.port_range_start, self.port_range_end + 1):
                if port in instances_by_port:
                    continue
                info = self._safe_ping(port)
                if not info:
                    continue
                instances_by_port[port] = self._normalize_instance(
                    {**info, "port": port, "source": "portscan"}
                )

            if self.default_port not in instances_by_port:
                info = self._safe_ping(self.default_port)
                if info:
                    instances_by_port[self.default_port] = self._normalize_instance(
                        {**info, "port": self.default_port, "source": "default"}
                    )

        # File IPC discovery
        file_ipc_instances = self._discover_file_ipc_instances()

        # Merge — HTTP instances keyed by port, file IPC instances keyed by projectPath
        http_instances = [instances_by_port[port] for port in sorted(instances_by_port)]

        # Deduplicate: if a project is reachable via both HTTP and file IPC, prefer HTTP
        http_project_paths = {inst.get("projectPath") for inst in http_instances if inst.get("projectPath")}
        for ipc_inst in file_ipc_instances:
            if ipc_inst.get("projectPath") not in http_project_paths:
                http_instances.append(ipc_inst)

        return http_instances

    def _reconcile_selection(
        self,
        state: SessionState,
        instances: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not state.selected_port and not state.selected_instance:
            return instances

        selected_instance = state.selected_instance or {}
        selected_path = selected_instance.get("projectPath")

        if selected_path:
            for instance in instances:
                if instance.get("projectPath") == selected_path:
                    if instance["port"] != state.selected_port:
                        self.session_store.update_selection(instance)
                    return instances

        if any(instance["port"] == state.selected_port for instance in instances):
            return instances

        if not instances:
            return instances

        self.session_store.clear_selection()
        return instances

    def _read_registry_snapshot(self) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {
            "path": str(self.registry_path),
            "status": "missing",
            "error": None,
            "entries": [],
        }
        try:
            raw_text = self.registry_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return snapshot
        except PermissionError as exc:
            snapshot["status"] = "access-denied"
            snapshot["error"] = str(exc)
            return snapshot
        except OSError as exc:
            snapshot["status"] = "error"
            snapshot["error"] = str(exc)
            return snapshot

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            snapshot["status"] = "invalid-json"
            snapshot["error"] = str(exc)
            return snapshot

        snapshot["status"] = "ok"
        snapshot["entries"] = [entry for entry in data if isinstance(entry, dict)]
        return snapshot

    def _read_registry_entries(self) -> List[Dict[str, Any]]:
        try:
            snapshot = self._read_registry_snapshot()
        except Exception:
            return []
        return list(snapshot.get("entries") or [])

    def _safe_ping(self, port: int) -> Dict[str, Any] | None:
        try:
            return self.client.ping(port, timeout=0.5)
        except (UnityMCPClientError, socket.timeout):
            return None

    def _normalize_instance(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        port = self._coerce_int(payload.get("port")) or self.default_port
        clone_index = self._coerce_int(payload.get("cloneIndex"), default=-1)
        transport = payload.get("transport") or "http"
        label = (
            payload.get("projectName")
            or payload.get("project")
            or (f"Unity Editor ({port})" if port else "Unity Editor (file-ipc)")
        )
        result: Dict[str, Any] = {
            "port": port,
            "projectName": label,
            "projectPath": payload.get("projectPath") or "",
            "unityVersion": payload.get("unityVersion") or payload.get("version") or "",
            "platform": payload.get("platform") or "",
            "isClone": bool(payload.get("isClone")),
            "cloneIndex": clone_index,
            "processId": self._coerce_int(payload.get("processId")),
            "source": payload.get("source") or "unknown",
        }
        if transport != "http":
            result["transport"] = transport
        return result

    @staticmethod
    def _coerce_int(value: Any, default: int | None = None) -> int | None:
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
