"""Project-level persistent memory for the Unity MCP CLI.

Stores learned patterns, fixes, and structure info per Unity project so the
CLI gets smarter over time without repeating the same discovery work.

Storage: a single JSON file per project, keyed by a hash of the project path.
  Windows: %LOCALAPPDATA%/CLIAnything/memory/<project_id>.json
  Linux:   ~/.local/state/cli-anything-unity-mcp/memory/<project_id>.json
  Fallback: .cli-anything-unity-mcp/memory/<project_id>.json
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Categories ────────────────────────────────────────────────────────────────
CATEGORY_FIX = "fix"          # error pattern → fix that worked
CATEGORY_PATTERN = "pattern"  # recurring project behaviour worth remembering
CATEGORY_STRUCTURE = "structure"  # project layout (pipelines, paths, packages)
CATEGORY_PREFERENCE = "preference"  # user/agent preferences for this project

ALL_CATEGORIES = {CATEGORY_FIX, CATEGORY_PATTERN, CATEGORY_STRUCTURE, CATEGORY_PREFERENCE}


def _default_memory_root() -> Path:
    env_override = os.environ.get("CLI_ANYTHING_UNITY_MCP_MEMORY_DIR")
    if env_override:
        return Path(env_override)
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "CLIAnything" / "memory"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CLIAnything" / "memory"
    return Path.home() / ".local" / "state" / "cli-anything-unity-mcp" / "memory"


def _workspace_memory_root() -> Path:
    return Path.cwd() / ".cli-anything-unity-mcp" / "memory"


def _project_id(project_path: str) -> str:
    """Stable 8-char hex ID derived from the project path."""
    return hashlib.sha256(project_path.encode("utf-8")).hexdigest()[:8]


class ProjectMemory:
    """Persistent memory store for a single Unity project."""

    def __init__(
        self,
        project_path: str,
        store_root: Optional[Path] = None,
        allow_fallback: bool = True,
    ) -> None:
        self.project_path = project_path
        self.project_id = _project_id(project_path)
        self._root = Path(store_root) if store_root else _default_memory_root()
        self._fallback_root = _workspace_memory_root()
        self._allow_fallback = allow_fallback
        self._store_path = self._root / f"{self.project_id}.json"
        self._fallback_path = self._fallback_root / f"{self.project_id}.json"
        self._data: Dict[str, Any] | None = None  # lazy-loaded cache

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _load(self) -> Dict[str, Any]:
        if self._data is not None:
            return self._data
        data = self._read_file(self._store_path)
        if data is None and self._allow_fallback:
            data = self._read_file(self._fallback_path)
        if data is None:
            data = {"projectPath": self.project_path, "entries": {}}
        self._data = data
        return self._data

    def _flush(self) -> None:
        serialized = json.dumps(self._data, indent=2, ensure_ascii=False)
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            self._store_path.write_text(serialized, encoding="utf-8")
            return
        except (PermissionError, OSError):
            if not self._allow_fallback:
                raise
        self._fallback_path.parent.mkdir(parents=True, exist_ok=True)
        self._fallback_path.write_text(serialized, encoding="utf-8")

    @staticmethod
    def _read_file(path: Path) -> Dict[str, Any] | None:
        try:
            raw = path.read_text(encoding="utf-8")
            return json.loads(raw)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── Core read/write ───────────────────────────────────────────────────────

    def save(
        self,
        category: str,
        key: str,
        content: Dict[str, Any],
        *,
        overwrite: bool = True,
    ) -> None:
        """Save a memory entry.

        Args:
            category: One of fix / pattern / structure / preference.
            key:      Unique identifier within the category.
            content:  Arbitrary dict of memory data.
            overwrite: If False, skip if an entry with this key already exists.
        """
        data = self._load()
        entry_key = f"{category}:{key}"
        existing = data["entries"].get(entry_key)
        if existing and not overwrite:
            return
        data["entries"][entry_key] = {
            "category": category,
            "key": key,
            "content": content,
            "created": existing["created"] if existing else self._now_iso(),
            "updated": self._now_iso(),
            "hit_count": existing.get("hit_count", 0) if existing else 0,
        }
        self._flush()

    def recall(
        self,
        category: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return matching entries, sorted by recency (updated desc).

        Args:
            category: Filter to a specific category.
            search:   Case-insensitive substring match against the JSON dump.
            limit:    Max entries to return.
        """
        data = self._load()
        results = []
        for entry in data["entries"].values():
            if category and entry.get("category") != category:
                continue
            if search and search.lower() not in json.dumps(entry).lower():
                continue
            results.append(entry)

        results.sort(key=lambda e: e.get("updated", ""), reverse=True)
        # bump hit counts
        keys_seen = {f"{e['category']}:{e['key']}" for e in results[:limit]}
        for k in keys_seen:
            if k in data["entries"]:
                data["entries"][k]["hit_count"] = data["entries"][k].get("hit_count", 0) + 1
        if keys_seen:
            self._flush()
        return results[:limit]

    def forget(
        self,
        category: Optional[str] = None,
        key: Optional[str] = None,
    ) -> int:
        """Delete entries. Returns count deleted.

        - forget(category="fix") → delete all fixes
        - forget(category="fix", key="CS0246") → delete one fix
        - forget() → clear everything
        """
        data = self._load()
        to_delete = []
        for entry_key, entry in data["entries"].items():
            if category and entry.get("category") != category:
                continue
            if key and entry.get("key") != key:
                continue
            to_delete.append(entry_key)
        for k in to_delete:
            del data["entries"][k]
        if to_delete:
            self._flush()
        return len(to_delete)

    def stats(self) -> Dict[str, Any]:
        """Return a summary of what's stored for this project."""
        data = self._load()
        by_category: Dict[str, int] = {}
        most_used: List[Dict[str, Any]] = []
        for entry in data["entries"].values():
            cat = entry.get("category", "unknown")
            by_category[cat] = by_category.get(cat, 0) + 1
            most_used.append({"key": entry.get("key"), "category": cat, "hits": entry.get("hit_count", 0)})
        most_used.sort(key=lambda e: e["hits"], reverse=True)
        return {
            "projectPath": self.project_path,
            "projectId": self.project_id,
            "totalEntries": len(data["entries"]),
            "byCategory": by_category,
            "mostUsed": most_used[:5],
            "storePath": str(self._store_path),
        }

    # ── Typed helpers ─────────────────────────────────────────────────────────

    def remember_fix(
        self,
        error_pattern: str,
        fix_command: str,
        context: str = "",
        *,
        overwrite: bool = True,
    ) -> None:
        """Remember that fix_command resolved a specific error pattern."""
        self.save(
            CATEGORY_FIX,
            error_pattern,
            {"errorPattern": error_pattern, "fixCommand": fix_command, "context": context},
            overwrite=overwrite,
        )

    def remember_structure(self, key: str, value: Any) -> None:
        """Cache a project structure detail (pipeline, paths, packages, etc.)."""
        self.save(CATEGORY_STRUCTURE, key, {"value": value})

    def remember_pattern(self, key: str, description: str, detail: str = "") -> None:
        """Record a recurring project-level pattern worth flagging in future."""
        self.save(CATEGORY_PATTERN, key, {"description": description, "detail": detail})

    def suggest_fix(self, error_text: str) -> List[Dict[str, Any]]:
        """Given error text, return known fixes whose pattern appears in it."""
        fixes = self.recall(category=CATEGORY_FIX)
        return [
            f for f in fixes
            if f["content"].get("errorPattern", "").lower() in error_text.lower()
        ]

    def get_structure(self, key: str) -> Any:
        """Return a single cached structure value, or None if not stored."""
        data = self._load()
        entry = data["entries"].get(f"{CATEGORY_STRUCTURE}:{key}")
        if entry is None:
            return None
        return entry.get("content", {}).get("value")

    def get_all_structure(self) -> Dict[str, Any]:
        """Return all cached structure facts as a flat dict."""
        data = self._load()
        result: Dict[str, Any] = {}
        for entry_key, entry in data["entries"].items():
            if entry.get("category") == CATEGORY_STRUCTURE:
                result[entry.get("key", "")] = entry.get("content", {}).get("value")
        return result

    # ── Doctor state tracking ──────────────────────────────────────────────────

    def save_doctor_state(self, findings: List[Dict[str, Any]], timestamp: str) -> None:
        """Persist the last doctor finding set so the next run can diff against it."""
        self.save(
            CATEGORY_STRUCTURE,
            "_last_doctor_state",
            {
                "value": {
                    "findings": [
                        {"title": f.get("title", ""), "severity": f.get("severity", "")}
                        for f in findings
                        if f.get("title") != "Healthy Snapshot"
                    ],
                    "timestamp": timestamp,
                }
            },
        )

    def get_last_doctor_state(self) -> Optional[Dict[str, Any]]:
        """Return the last saved doctor state, or None."""
        return self.get_structure("_last_doctor_state")


# ── Factory ───────────────────────────────────────────────────────────────────

def memory_for_session(session_state: Any, store_root: Optional[Path] = None) -> Optional[ProjectMemory]:
    """Create a ProjectMemory for the currently selected Unity project.

    Returns None if no instance is selected or the project path is unknown.
    """
    instance = getattr(session_state, "selected_instance", None)
    if not isinstance(instance, dict):
        return None
    project_path = instance.get("projectPath") or instance.get("projectName")
    if not project_path:
        return None
    return ProjectMemory(project_path=project_path, store_root=store_root)
