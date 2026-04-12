from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional


def get_default_developer_profiles_path() -> Path:
    env_override = os.environ.get("CLI_ANYTHING_UNITY_MCP_DEVELOPER_PROFILES")
    if env_override:
        return Path(env_override)
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "CLIAnything" / "unity-mcp-developer-profiles.json"
    return Path.home() / ".local" / "state" / "cli-anything-unity-mcp" / "developer-profiles.json"


def get_workspace_fallback_developer_profiles_path() -> Path:
    return Path.cwd() / ".cli-anything-unity-mcp" / "developer-profiles.json"


def derive_developer_profiles_path(session_path: Path) -> Path:
    return session_path.with_name("developer-profiles.json")


@dataclass
class DeveloperProfile:
    name: str
    description: str
    planning_mode: str
    verbosity: str
    token_strategy: str
    focus: str
    instructions: List[str] = field(default_factory=list)
    recommended_skills: List[str] = field(default_factory=list)
    built_in: bool = True


@dataclass
class DeveloperProfileState:
    selected_profile: Optional[str] = None
    profiles: List[DeveloperProfile] = field(default_factory=list)


_BUILTIN_PROFILE_TEMPLATES: tuple[DeveloperProfile, ...] = (
    DeveloperProfile(
        name="normal",
        description="Balanced day-to-day CLI development with concise explanations and steady verification.",
        planning_mode="balanced",
        verbosity="standard",
        token_strategy="balanced",
        focus="general implementation and debugging",
        instructions=[
            "Inspect the current project state before making changes.",
            "Keep explanations concise, but include the why when a change is non-obvious.",
            "Prefer shipping a tested fix over describing a hypothetical one.",
        ],
        recommended_skills=["cli-anything"],
    ),
    DeveloperProfile(
        name="builder",
        description="Action-first shipping mode for feature work, scaffolding, and end-to-end delivery.",
        planning_mode="action-first",
        verbosity="concise",
        token_strategy="efficient",
        focus="implementation momentum and fast verification",
        instructions=[
            "Bias toward making the change instead of over-planning.",
            "Use focused verification after each meaningful implementation step.",
            "Keep the user moving with short progress updates and concrete next actions.",
        ],
        recommended_skills=["cli-anything"],
    ),
    DeveloperProfile(
        name="director",
        description="Project-direction mode for scene critique, priorities, and presentation quality.",
        planning_mode="direction-first",
        verbosity="concise",
        token_strategy="balanced",
        focus="overall quality, direction, and priorities",
        instructions=[
            "Lead with the strongest priorities and avoid generic praise.",
            "Use project evidence, captures, and scene stats to support critiques.",
            "Recommend the smallest next steps that improve overall quality fast.",
        ],
        recommended_skills=["cli-anything"],
    ),
    DeveloperProfile(
        name="animator",
        description="Animation pipeline mode for rigs, avatars, clips, and controllers.",
        planning_mode="pipeline-first",
        verbosity="concise",
        token_strategy="balanced",
        focus="animation import, controller, and rig quality",
        instructions=[
            "Call out rig type, avatar, and controller gaps directly.",
            "Prefer concrete import and controller recommendations over vague animation advice.",
        ],
        recommended_skills=["cli-anything"],
    ),
    DeveloperProfile(
        name="tech-artist",
        description="Technical-art mode for materials, shaders, textures, VFX usage, and render-pipeline sanity.",
        planning_mode="pipeline-first",
        verbosity="concise",
        token_strategy="balanced",
        focus="technical art quality and asset consistency",
        instructions=[
            "Prefer renderer, material, and import evidence over generic art feedback.",
            "Call out pipeline mismatches and asset setup issues clearly.",
        ],
        recommended_skills=["cli-anything"],
    ),
    DeveloperProfile(
        name="ui-designer",
        description="UI and HUD quality mode for Canvas structure, scaling, readability, and hierarchy clarity.",
        planning_mode="clarity-first",
        verbosity="concise",
        token_strategy="balanced",
        focus="ui readability, hierarchy, and scaling behavior",
        instructions=[
            "Look for CanvasScaler, anchors, layering, and readability issues first.",
            "Prefer concrete HUD and layout fixes over vague UX language.",
        ],
        recommended_skills=["cli-anything"],
    ),
    DeveloperProfile(
        name="level-designer",
        description="Level readability mode for composition, density, flow, and encounter-space clarity.",
        planning_mode="clarity-first",
        verbosity="concise",
        token_strategy="balanced",
        focus="scene composition, readability, and authored space",
        instructions=[
            "Focus on traversal readability, density, and focal structure.",
            "Call out flatness, clutter, and weak composition directly.",
        ],
        recommended_skills=["cli-anything"],
    ),
    DeveloperProfile(
        name="systems",
        description="Unity systems mode for scene architecture, playability hooks, runtime hygiene, and testability.",
        planning_mode="systems-first",
        verbosity="concise",
        token_strategy="balanced",
        focus="scene architecture, runtime hygiene, and reusable gameplay foundations",
        instructions=[
            "Look for playable entry points, scene hygiene, and runtime setup gaps first.",
            "Prefer concrete scene-architecture and systems findings over genre-specific advice.",
            "Call out probe leftovers, missing sandbox coverage, and core Unity setup mistakes directly.",
        ],
        recommended_skills=["cli-anything"],
    ),
    DeveloperProfile(
        name="review",
        description="Risk-first reviewer mode for bugs, regressions, testing gaps, and production safety.",
        planning_mode="risk-first",
        verbosity="concise",
        token_strategy="efficient",
        focus="bugs, regressions, edge cases, and missing tests",
        instructions=[
            "Lead with findings before summaries.",
            "Look for behavioral regressions, hidden assumptions, and missing verification.",
            "Prefer the smallest fix that closes real risk cleanly.",
        ],
        recommended_skills=["caveman-review"],
    ),
    DeveloperProfile(
        name="caveman",
        description="Ultra-compressed low-token mode with blunt, high-signal communication.",
        planning_mode="minimal",
        verbosity="terse",
        token_strategy="aggressive-saver",
        focus="token efficiency and terse execution updates",
        instructions=[
            "Use short, high-signal language.",
            "Cut filler and keep only actionable technical detail.",
            "Still verify important changes even when reporting tersely.",
        ],
        recommended_skills=["caveman", "caveman-commit", "caveman-review"],
    ),
)


def iter_builtin_developer_profiles() -> List[DeveloperProfile]:
    return [DeveloperProfile(**asdict(profile)) for profile in _BUILTIN_PROFILE_TEMPLATES]


class DeveloperProfileStore:
    def __init__(self, path: Path | None = None) -> None:
        env_override = os.environ.get("CLI_ANYTHING_UNITY_MCP_DEVELOPER_PROFILES")
        self.path = Path(path) if path else get_default_developer_profiles_path()
        self.fallback_path = get_workspace_fallback_developer_profiles_path()
        self.allow_fallback = path is None and not env_override

    def load(self) -> DeveloperProfileState:
        data = self._read_state_file(self.path)
        if data is None and self.allow_fallback and self.fallback_path != self.path:
            data = self._read_state_file(self.fallback_path)
        selected_profile = None if data is None else data.get("selected_profile") or data.get("selectedProfile")
        profiles = iter_builtin_developer_profiles()
        profiles.sort(key=lambda item: item.name.lower())
        return DeveloperProfileState(
            selected_profile=selected_profile,
            profiles=profiles,
        )

    def save(self, state: DeveloperProfileState) -> DeveloperProfileState:
        serialized = json.dumps(
            {
                "selected_profile": state.selected_profile,
            },
            indent=2,
        )
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(serialized, encoding="utf-8")
            return self.load()
        except PermissionError:
            if not self.allow_fallback or self.fallback_path == self.path:
                raise
        except OSError:
            if not self.allow_fallback or self.fallback_path == self.path:
                raise

        self.fallback_path.parent.mkdir(parents=True, exist_ok=True)
        self.fallback_path.write_text(serialized, encoding="utf-8")
        return self.load()

    def list_profiles(self) -> DeveloperProfileState:
        return self.load()

    def get_profile(self, name: str | None) -> DeveloperProfile | None:
        lowered = str(name or "").strip().lower()
        if not lowered:
            return None
        state = self.load()
        for profile in state.profiles:
            if profile.name.lower() == lowered:
                return profile
        return None

    def default_profile(self) -> DeveloperProfile:
        profile = self.get_profile("normal")
        if profile is None:
            raise RuntimeError("Built-in developer profile `normal` is missing.")
        return profile

    def select_profile(self, name: str) -> DeveloperProfileState:
        profile = self.get_profile(name)
        if profile is None:
            raise ValueError(f"Developer profile `{name}` was not found.")
        return self.save(DeveloperProfileState(selected_profile=profile.name))

    def clear_selection(self) -> DeveloperProfileState:
        return self.save(DeveloperProfileState(selected_profile=None))

    @staticmethod
    def _read_state_file(path: Path) -> dict | None:
        try:
            raw = path.read_text(encoding="utf-8")
            return json.loads(raw)
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, OSError):
            return None
