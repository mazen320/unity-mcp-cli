from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ..core.client import UnityMCPClient, UnityMCPClientError, UnityMCPConnectionError
from ..core.routes import iter_known_tools, route_to_tool_name, tool_name_to_route
from ..core.schema_templates import summarize_schema
from ..core.session import SessionState, SessionStore
from ..core.tool_catalog import get_upstream_tool, iter_upstream_tools
from ..core.tool_coverage import build_tool_coverage_matrix


def get_default_registry_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "UnityMCP" / "instances.json"
    return Path.home() / ".local" / "share" / "UnityMCP" / "instances.json"


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
    ) -> None:
        self.client = client or UnityMCPClient()
        self.session_store = session_store or SessionStore()
        self.registry_path = Path(registry_path) if registry_path else get_default_registry_path()
        self.default_port = default_port
        self.port_range_start = port_range_start
        self.port_range_end = port_range_end

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
        resolved_port = self.resolve_port(explicit_port=port, allow_default=True)
        payload = self.client.ping(resolved_port, timeout=3.0)
        payload["port"] = resolved_port
        return payload

    def get_routes(self, port: Optional[int] = None) -> Dict[str, Any]:
        resolved_port = self.resolve_port(explicit_port=port, allow_default=False)
        routes = self.client.get_api(resolved_port, "_meta/routes")
        self.session_store.record_command("_meta/routes", {}, resolved_port)
        return routes

    def get_context(self, category: str | None = None, port: Optional[int] = None) -> Dict[str, Any]:
        resolved_port = self.resolve_port(explicit_port=port, allow_default=False)
        api_path = "context"
        if category:
            api_path = f"context/{quote(category)}"
        payload = self.client.get_api(resolved_port, api_path)
        self.session_store.record_command(api_path, {}, resolved_port)
        return payload

    def get_queue_info(self, port: Optional[int] = None) -> Dict[str, Any]:
        resolved_port = self.resolve_port(explicit_port=port, allow_default=False)
        payload = self.client.get_queue_info(resolved_port)
        self.session_store.record_command("queue/info", {}, resolved_port)
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
        resolved_port = self.resolve_port(explicit_port=port, allow_default=False)
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
        if include_hierarchy:
            payload["hierarchy"] = self.call_route_with_recovery(
                "scene/hierarchy",
                params={"maxDepth": 2, "maxNodes": 40},
                port=resolved_port,
                recovery_timeout=10.0,
            )
        return payload

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
    ) -> Dict[str, Any]:
        return build_tool_coverage_matrix(
            category=category,
            status=status,
            search=search,
            include_unsupported=include_unsupported,
            summary_only=summary_only,
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

    def call_route(
        self,
        route: str,
        params: Optional[Dict[str, Any]] = None,
        port: Optional[int] = None,
        use_get: bool = False,
        use_queue: Optional[bool] = None,
        record_history: bool = True,
    ) -> Any:
        resolved_port = self.resolve_port(explicit_port=port, allow_default=False)
        payload = params or {}
        if use_get:
            result = self.client.get_api(resolved_port, route, query=payload or None)
        else:
            try:
                result = self.client.call_route(resolved_port, route, payload, use_queue=use_queue)
            except TypeError:
                result = self.client.call_route(resolved_port, route, payload)
        if record_history and route not in self.NON_HISTORY_ROUTES:
            self.session_store.record_command(route, payload, resolved_port)
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
        use_get = route in {"context", "queue/status"}
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

        if state.selected_port and any(inst["port"] == state.selected_port for inst in instances):
            return state.selected_port

        if len(instances) == 1:
            self.session_store.update_selection(instances[0])
            return instances[0]["port"]

        if len(instances) > 1:
            labels = ", ".join(
                f"{instance['projectName']}:{instance['port']}" for instance in instances
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

    def discover_instances(self) -> List[Dict[str, Any]]:
        instances_by_port: Dict[int, Dict[str, Any]] = {}

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

        return [instances_by_port[port] for port in sorted(instances_by_port)]

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

    def _read_registry_entries(self) -> List[Dict[str, Any]]:
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (json.JSONDecodeError, OSError):
            return []
        return [entry for entry in data if isinstance(entry, dict)]

    def _safe_ping(self, port: int) -> Dict[str, Any] | None:
        try:
            return self.client.ping(port, timeout=0.5)
        except (UnityMCPClientError, socket.timeout):
            return None

    def _normalize_instance(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        port = self._coerce_int(payload.get("port")) or self.default_port
        clone_index = self._coerce_int(payload.get("cloneIndex"), default=-1)
        return {
            "port": port,
            "projectName": payload.get("projectName")
            or payload.get("project")
            or f"Unity Editor ({port})",
            "projectPath": payload.get("projectPath") or "",
            "unityVersion": payload.get("unityVersion") or payload.get("version") or "",
            "platform": payload.get("platform") or "",
            "isClone": bool(payload.get("isClone")),
            "cloneIndex": clone_index,
            "processId": self._coerce_int(payload.get("processId")),
            "source": payload.get("source") or "unknown",
        }

    @staticmethod
    def _coerce_int(value: Any, default: int | None = None) -> int | None:
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
