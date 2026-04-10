from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_default_session_path() -> Path:
    env_override = os.environ.get("CLI_ANYTHING_UNITY_MCP_SESSION")
    if env_override:
        return Path(env_override)
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "CLIAnything" / "unity-mcp-session.json"
    return Path.home() / ".local" / "state" / "cli-anything-unity-mcp" / "session.json"


def get_workspace_fallback_session_path() -> Path:
    return Path.cwd() / ".cli-anything-unity-mcp" / "session.json"


DEFAULT_DEBUG_PREFERENCES: Dict[str, Any] = {
    "unityConsoleBreadcrumbs": True,
    "dashboardAutoRefresh": False,
    "dashboardRefreshSeconds": 5.0,
    "dashboardConsoleCount": 20,
    "dashboardIssueLimit": 20,
    "dashboardIncludeHierarchy": False,
    "dashboardEditorLogTail": 40,
    "dashboardAbUmcpOnly": False,
}


def normalize_debug_preferences(values: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized = dict(DEFAULT_DEBUG_PREFERENCES)
    if not isinstance(values, dict):
        return normalized

    def _coerce_bool(key: str) -> None:
        if key in values:
            normalized[key] = bool(values.get(key))

    def _coerce_int(key: str, minimum: int) -> None:
        if key not in values:
            return
        try:
            normalized[key] = max(minimum, int(values.get(key)))
        except (TypeError, ValueError):
            return

    def _coerce_float(key: str, minimum: float) -> None:
        if key not in values:
            return
        try:
            normalized[key] = max(minimum, float(values.get(key)))
        except (TypeError, ValueError):
            return

    _coerce_bool("unityConsoleBreadcrumbs")
    _coerce_bool("dashboardAutoRefresh")
    _coerce_bool("dashboardIncludeHierarchy")
    _coerce_bool("dashboardAbUmcpOnly")
    _coerce_float("dashboardRefreshSeconds", 0.25)
    _coerce_int("dashboardConsoleCount", 1)
    _coerce_int("dashboardIssueLimit", 1)
    _coerce_int("dashboardEditorLogTail", 1)
    return normalized


@dataclass
class SessionState:
    selected_port: Optional[int] = None
    selected_instance: Optional[Dict[str, Any]] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    debug_preferences: Dict[str, Any] = field(
        default_factory=lambda: dict(DEFAULT_DEBUG_PREFERENCES)
    )


class SessionStore:
    def __init__(self, path: Path | None = None, max_history: int = 100) -> None:
        env_override = os.environ.get("CLI_ANYTHING_UNITY_MCP_SESSION")
        self.path = Path(path) if path else get_default_session_path()
        self.fallback_path = get_workspace_fallback_session_path()
        self.allow_fallback = path is None and not env_override
        self.max_history = max_history

    def load(self) -> SessionState:
        data = self._read_state_file(self.path)
        if data is None and self.allow_fallback and self.fallback_path != self.path:
            data = self._read_state_file(self.fallback_path)
        if data is None:
            return SessionState()

        return SessionState(
            selected_port=data.get("selected_port"),
            selected_instance=data.get("selected_instance"),
            history=data.get("history", []),
            debug_preferences=normalize_debug_preferences(data.get("debug_preferences")),
        )

    def save(self, state: SessionState) -> SessionState:
        serialized = json.dumps(asdict(state), indent=2)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(serialized, encoding="utf-8")
            return state
        except PermissionError:
            if not self.allow_fallback or self.fallback_path == self.path:
                raise
        except OSError:
            if not self.allow_fallback or self.fallback_path == self.path:
                raise

        self.fallback_path.parent.mkdir(parents=True, exist_ok=True)
        self.fallback_path.write_text(serialized, encoding="utf-8")
        return state

    def update_selection(self, instance: Dict[str, Any]) -> SessionState:
        state = self.load()
        state.selected_port = instance.get("port")
        state.selected_instance = instance
        return self.save(state)

    def clear_selection(self) -> SessionState:
        state = self.load()
        state.selected_port = None
        state.selected_instance = None
        return self.save(state)

    def record_command(
        self,
        command: str,
        args: Optional[Dict[str, Any]] = None,
        port: Optional[int] = None,
        status: str = "ok",
        duration_ms: float | None = None,
        error: str | None = None,
        transport: str | None = None,
        note: str | None = None,
        agent_id: str | None = None,
        agent_profile: str | None = None,
        command_path: str | None = None,
        activity: str | None = None,
    ) -> SessionState:
        entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": command,
            "args": args or {},
            "port": port,
            "status": status,
        }
        if duration_ms is not None:
            entry["durationMs"] = round(float(duration_ms), 3)
        if error:
            entry["error"] = error
        if transport:
            entry["transport"] = transport
        if note:
            entry["note"] = note
        if agent_id:
            entry["agentId"] = agent_id
        if agent_profile:
            entry["agentProfile"] = agent_profile
        if command_path:
            entry["commandPath"] = command_path
        if activity:
            entry["activity"] = activity

        state = self.load()
        state.history.append(entry)
        state.history = state.history[-self.max_history :]
        return self.save(state)

    def clear_history(self) -> SessionState:
        state = self.load()
        state.history = []
        return self.save(state)

    def get_debug_preferences(self) -> Dict[str, Any]:
        return dict(self.load().debug_preferences)

    def update_debug_preferences(self, **updates: Any) -> SessionState:
        state = self.load()
        merged = dict(state.debug_preferences)
        merged.update({key: value for key, value in updates.items() if value is not None})
        state.debug_preferences = normalize_debug_preferences(merged)
        return self.save(state)

    @staticmethod
    def _read_state_file(path: Path) -> Dict[str, Any] | None:
        try:
            raw = path.read_text(encoding="utf-8")
            return json.loads(raw)
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, OSError):
            return None
