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
from ..core.session import SessionState, SessionStore


def get_default_registry_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "UnityMCP" / "instances.json"
    return Path.home() / ".local" / "share" / "UnityMCP" / "instances.json"


class BackendSelectionError(RuntimeError):
    """Raised when an instance needs to be selected before continuing."""


class UnityMCPBackend:
    NON_HISTORY_ROUTES = {"ping", "_meta/routes", "queue/info"}

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

    def call_route_with_recovery(
        self,
        route: str,
        params: Optional[Dict[str, Any]] = None,
        port: Optional[int] = None,
        use_get: bool = False,
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
        record_history: bool = True,
    ) -> Any:
        resolved_port = self.resolve_port(explicit_port=port, allow_default=False)
        payload = params or {}
        if use_get:
            result = self.client.get_api(resolved_port, route, query=payload or None)
        else:
            result = self.client.call_route(resolved_port, route, payload)
        if record_history and route not in self.NON_HISTORY_ROUTES:
            self.session_store.record_command(route, payload, resolved_port)
        return result

    def call_tool(
        self,
        tool_name: str,
        params: Optional[Dict[str, Any]] = None,
        port: Optional[int] = None,
    ) -> Any:
        route = tool_name_to_route(tool_name)
        return self.call_route(route, params=params, port=port)

    def known_tools(self, category: str | None = None) -> List[Dict[str, str]]:
        return iter_known_tools(category=category)

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
