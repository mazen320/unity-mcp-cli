from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


def get_default_agent_profiles_path() -> Path:
    env_override = os.environ.get("CLI_ANYTHING_UNITY_MCP_AGENT_PROFILES")
    if env_override:
        return Path(env_override)
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "CLIAnything" / "unity-mcp-agent-profiles.json"
    return Path.home() / ".local" / "state" / "cli-anything-unity-mcp" / "agent-profiles.json"


def get_workspace_fallback_agent_profiles_path() -> Path:
    return Path.cwd() / ".cli-anything-unity-mcp" / "agent-profiles.json"


def derive_agent_profiles_path(session_path: Path) -> Path:
    return session_path.with_name("agent-profiles.json")


@dataclass
class AgentProfile:
    name: str
    agent_id: str
    role: str = "custom"
    description: str = ""
    legacy: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class AgentProfileState:
    selected_profile: Optional[str] = None
    profiles: List[AgentProfile] = field(default_factory=list)


class AgentProfileStore:
    def __init__(self, path: Path | None = None) -> None:
        env_override = os.environ.get("CLI_ANYTHING_UNITY_MCP_AGENT_PROFILES")
        self.path = Path(path) if path else get_default_agent_profiles_path()
        self.fallback_path = get_workspace_fallback_agent_profiles_path()
        self.allow_fallback = path is None and not env_override

    def load(self) -> AgentProfileState:
        data = self._read_state_file(self.path)
        if data is None and self.allow_fallback and self.fallback_path != self.path:
            data = self._read_state_file(self.fallback_path)
        if data is None:
            return AgentProfileState()

        profiles = [
            AgentProfile(
                name=str(item.get("name") or ""),
                agent_id=str(item.get("agent_id") or item.get("agentId") or ""),
                role=str(item.get("role") or "custom"),
                description=str(item.get("description") or ""),
                legacy=bool(item.get("legacy")),
                created_at=str(item.get("created_at") or item.get("createdAt") or datetime.now(timezone.utc).isoformat()),
                updated_at=str(item.get("updated_at") or item.get("updatedAt") or datetime.now(timezone.utc).isoformat()),
            )
            for item in data.get("profiles", [])
            if item.get("name") and (item.get("agent_id") or item.get("agentId"))
        ]
        return AgentProfileState(
            selected_profile=data.get("selected_profile") or data.get("selectedProfile"),
            profiles=profiles,
        )

    def save(self, state: AgentProfileState) -> AgentProfileState:
        serialized = json.dumps(
            {
                "selected_profile": state.selected_profile,
                "profiles": [asdict(profile) for profile in state.profiles],
            },
            indent=2,
        )
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

    def list_profiles(self) -> AgentProfileState:
        state = self.load()
        state.profiles.sort(key=lambda item: item.name.lower())
        return state

    def get_profile(self, name: str) -> AgentProfile | None:
        lowered = name.strip().lower()
        if not lowered:
            return None
        state = self.load()
        for profile in state.profiles:
            if profile.name.lower() == lowered:
                return profile
        return None

    def upsert_profile(
        self,
        name: str,
        agent_id: str,
        role: str = "custom",
        description: str = "",
        legacy: bool = False,
        select: bool = True,
    ) -> AgentProfileState:
        normalized_name = name.strip()
        normalized_agent_id = agent_id.strip()
        if not normalized_name:
            raise ValueError("Profile name cannot be empty.")
        if not normalized_agent_id:
            raise ValueError("Agent ID cannot be empty.")

        now = datetime.now(timezone.utc).isoformat()
        state = self.load()
        updated = False
        for index, profile in enumerate(state.profiles):
            if profile.name.lower() == normalized_name.lower():
                state.profiles[index] = AgentProfile(
                    name=profile.name,
                    agent_id=normalized_agent_id,
                    role=role,
                    description=description,
                    legacy=legacy,
                    created_at=profile.created_at,
                    updated_at=now,
                )
                updated = True
                break
        if not updated:
            state.profiles.append(
                AgentProfile(
                    name=normalized_name,
                    agent_id=normalized_agent_id,
                    role=role,
                    description=description,
                    legacy=legacy,
                    created_at=now,
                    updated_at=now,
                )
            )
        if select:
            state.selected_profile = normalized_name
        return self.save(state)

    def select_profile(self, name: str) -> AgentProfileState:
        state = self.load()
        for profile in state.profiles:
            if profile.name.lower() == name.strip().lower():
                state.selected_profile = profile.name
                return self.save(state)
        raise ValueError(f"Agent profile `{name}` was not found.")

    def clear_selection(self) -> AgentProfileState:
        state = self.load()
        state.selected_profile = None
        return self.save(state)

    def remove_profile(self, name: str) -> AgentProfileState:
        state = self.load()
        before = len(state.profiles)
        state.profiles = [profile for profile in state.profiles if profile.name.lower() != name.strip().lower()]
        if len(state.profiles) == before:
            raise ValueError(f"Agent profile `{name}` was not found.")
        if state.selected_profile and state.selected_profile.lower() == name.strip().lower():
            state.selected_profile = None
        return self.save(state)

    @staticmethod
    def _read_state_file(path: Path) -> dict | None:
        try:
            raw = path.read_text(encoding="utf-8")
            return json.loads(raw)
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, OSError):
            return None
