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
import re
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
        env_override = os.environ.get("CLI_ANYTHING_UNITY_MCP_MEMORY_DIR")
        self._root = Path(store_root) if store_root else _default_memory_root()
        self._fallback_root = _workspace_memory_root()
        self._allow_fallback = allow_fallback and store_root is None and not env_override
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

    def summarize_for_selection(self, max_fixes: int = 5, max_recurring: int = 5) -> Optional[Dict[str, Any]]:
        """Return a compact, side-effect-free memory summary for `select` output."""
        stats = self.stats()
        total_entries = int(stats.get("totalEntries") or 0)
        if total_entries <= 0:
            return None

        summary: Dict[str, Any] = {
            "totalEntries": total_entries,
            "byCategory": stats.get("byCategory", {}),
        }

        structure = {
            key: value
            for key, value in self.get_all_structure().items()
            if key and not key.startswith("_")
        }
        if structure:
            summary["structure"] = structure

        data = self._load()
        fixes = [
            entry
            for entry in data["entries"].values()
            if entry.get("category") == CATEGORY_FIX
        ]
        fixes.sort(key=lambda entry: entry.get("updated", ""), reverse=True)
        fix_limit = max(0, int(max_fixes))
        if fix_limit and fixes:
            summary["knownFixes"] = [
                {
                    "pattern": entry.get("key", ""),
                    "fixCommand": entry.get("content", {}).get("fixCommand", ""),
                    "context": entry.get("content", {}).get("context", ""),
                }
                for entry in fixes[:fix_limit]
            ]

        recurring_limit = max(0, int(max_recurring))
        if recurring_limit:
            recurring = self.get_recurring_missing_refs(min_seen=2)[:recurring_limit]
            if recurring:
                summary["recurringMissingRefs"] = recurring

        return summary

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

    # ── Recurring issue tracking ─────────────────────────────────────────────

    def record_missing_references(
        self,
        results: List[Dict[str, Any]],
        scene_name: str,
    ) -> Dict[str, Any]:
        """Record missing references from a validate-scene run and flag repeat offenders.

        Each missing-ref result is keyed by its GameObject path + issue text.
        If the same issue appears across multiple runs, its ``seen_count``
        increments and it gets flagged as ``recurring``.

        Returns a summary dict with ``newIssues``, ``recurringIssues``, and
        ``resolvedIssues`` (issues that were present last time but gone now).
        """
        data = self._load()
        tracker_key = f"{CATEGORY_PATTERN}:_missing_refs_tracker"
        tracker = data["entries"].get(tracker_key, {}).get("content", {}).get("value", {})

        # Build a set of current issue keys.
        current_issues: Dict[str, Dict[str, Any]] = {}
        for result in results:
            if not isinstance(result, dict):
                continue
            go_path = result.get("path") or result.get("gameObject") or "unknown"
            issue = result.get("issue") or result.get("message") or "missing reference"
            component = result.get("component") or ""
            issue_key = f"{go_path}|{component}|{issue}"
            current_issues[issue_key] = {
                "gameObject": go_path,
                "component": component,
                "issue": issue,
                "scene": scene_name,
            }

        new_issues: List[Dict[str, Any]] = []
        recurring_issues: List[Dict[str, Any]] = []
        resolved_issues: List[Dict[str, Any]] = []

        # Classify current issues.
        for issue_key, issue_info in current_issues.items():
            prev = tracker.get(issue_key)
            if prev:
                seen_count = prev.get("seen_count", 1) + 1
                first_seen = prev.get("first_seen", self._now_iso())
                tracker[issue_key] = {
                    **issue_info,
                    "seen_count": seen_count,
                    "first_seen": first_seen,
                    "last_seen": self._now_iso(),
                }
                recurring_issues.append({**issue_info, "seenCount": seen_count, "firstSeen": first_seen})
            else:
                tracker[issue_key] = {
                    **issue_info,
                    "seen_count": 1,
                    "first_seen": self._now_iso(),
                    "last_seen": self._now_iso(),
                }
                new_issues.append(issue_info)

        # Detect resolved issues (were tracked before but not in current set).
        for issue_key, prev_info in list(tracker.items()):
            if issue_key not in current_issues:
                resolved_issues.append({
                    "gameObject": prev_info.get("gameObject", ""),
                    "component": prev_info.get("component", ""),
                    "issue": prev_info.get("issue", ""),
                    "scene": prev_info.get("scene", ""),
                    "seenCount": prev_info.get("seen_count", 1),
                })
                del tracker[issue_key]

        # Persist the updated tracker.
        self.save(
            CATEGORY_PATTERN,
            "_missing_refs_tracker",
            {"value": tracker},
        )

        return {
            "newIssues": new_issues,
            "recurringIssues": recurring_issues,
            "resolvedIssues": resolved_issues,
            "totalTracked": len(tracker),
        }

    def summarize_for_selection(
        self,
        max_fixes: int = 5,
        max_recurring: int = 5,
    ) -> Optional[Dict[str, Any]]:
        """Build a compact memory summary suitable for the ``select`` command.

        Args:
            max_fixes: Maximum number of known fixes to include.
            max_recurring: Maximum number of recurring missing refs to include.

        Returns ``None`` if memory is empty so the caller can skip output.
        """
        stats = self.stats()
        if stats.get("totalEntries", 0) == 0:
            return None

        summary: Dict[str, Any] = {
            "totalEntries": stats["totalEntries"],
            "byCategory": stats.get("byCategory", {}),
        }

        # Cached structure (skip internal keys).
        structure = self.get_all_structure()
        public_structure = {k: v for k, v in structure.items() if not k.startswith("_")}
        if public_structure:
            summary["structure"] = public_structure

        # Known fixes.
        fixes = self.recall(category=CATEGORY_FIX, limit=max_fixes)
        if fixes:
            summary["knownFixes"] = [
                {
                    "pattern": f.get("key", ""),
                    "fixCommand": f.get("content", {}).get("fixCommand", ""),
                    "context": f.get("content", {}).get("context", ""),
                }
                for f in fixes
            ]

        # Recurring missing refs.
        recurring = self.get_recurring_missing_refs(min_seen=2)
        if recurring:
            summary["recurringMissingRefs"] = recurring[:max_recurring]

        return summary

    def get_recurring_missing_refs(self, min_seen: int = 2) -> List[Dict[str, Any]]:
        """Return missing references that have been seen at least ``min_seen`` times."""
        data = self._load()
        tracker_key = f"{CATEGORY_PATTERN}:_missing_refs_tracker"
        tracker = data["entries"].get(tracker_key, {}).get("content", {}).get("value", {})
        results = []
        for issue_key, info in tracker.items():
            if info.get("seen_count", 1) >= min_seen:
                results.append({
                    "gameObject": info.get("gameObject", ""),
                    "component": info.get("component", ""),
                    "issue": info.get("issue", ""),
                    "scene": info.get("scene", ""),
                    "seenCount": info.get("seen_count", 1),
                    "firstSeen": info.get("first_seen", ""),
                    "lastSeen": info.get("last_seen", ""),
                })
        results.sort(key=lambda r: r["seenCount"], reverse=True)
        return results

    @staticmethod
    def _parse_compilation_issue(entry: Dict[str, Any]) -> Dict[str, Any] | None:
        message = str(entry.get("message") or "").strip()
        if not message:
            return None

        location_match = re.match(
            r"^(?P<file>.+?)\((?P<line>\d+),(?P<column>\d+)\):\s*error\s+(?P<code>CS\d+):\s*(?P<detail>.+)$",
            message,
        )
        if location_match:
            file_path = location_match.group("file").strip()
            code = location_match.group("code").strip()
            detail = location_match.group("detail").strip()
            return {
                "key": f"{code}|{file_path}|{detail}",
                "code": code,
                "file": file_path,
                "message": detail,
                "location": f"{file_path} line {location_match.group('line')}",
            }

        code_match = re.search(r"\berror\s+(CS\d+):\s*(.+)$", message)
        if code_match:
            code = code_match.group(1).strip()
            detail = code_match.group(2).strip()
            return {
                "key": f"{code}|{detail}",
                "code": code,
                "file": "",
                "message": detail,
                "location": "",
            }
        return None

    def _record_pattern_tracker(
        self,
        tracker_name: str,
        current_issues: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        data = self._load()
        tracker_key = f"{CATEGORY_PATTERN}:{tracker_name}"
        tracker = data["entries"].get(tracker_key, {}).get("content", {}).get("value", {})

        new_issues: List[Dict[str, Any]] = []
        recurring_issues: List[Dict[str, Any]] = []
        resolved_issues: List[Dict[str, Any]] = []

        for issue_key, issue_info in current_issues.items():
            prev = tracker.get(issue_key)
            if prev:
                seen_count = prev.get("seen_count", 1) + 1
                first_seen = prev.get("first_seen", self._now_iso())
                tracker[issue_key] = {
                    **issue_info,
                    "seen_count": seen_count,
                    "first_seen": first_seen,
                    "last_seen": self._now_iso(),
                }
                recurring_issues.append({**issue_info, "seenCount": seen_count, "firstSeen": first_seen})
            else:
                tracker[issue_key] = {
                    **issue_info,
                    "seen_count": 1,
                    "first_seen": self._now_iso(),
                    "last_seen": self._now_iso(),
                }
                new_issues.append(issue_info)

        for issue_key, prev_info in list(tracker.items()):
            if issue_key not in current_issues:
                resolved_issues.append({
                    **{
                        key: value
                        for key, value in prev_info.items()
                        if key not in {"seen_count", "first_seen", "last_seen"}
                    },
                    "seenCount": prev_info.get("seen_count", 1),
                    "firstSeen": prev_info.get("first_seen", ""),
                    "lastSeen": prev_info.get("last_seen", ""),
                })
                del tracker[issue_key]

        self.save(CATEGORY_PATTERN, tracker_name, {"value": tracker})
        return {
            "newIssues": new_issues,
            "recurringIssues": recurring_issues,
            "resolvedIssues": resolved_issues,
            "totalTracked": len(tracker),
        }

    def record_compilation_errors(
        self,
        entries: List[Dict[str, Any]],
        scene_name: str,
    ) -> Dict[str, Any]:
        current_issues: Dict[str, Dict[str, Any]] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            parsed = self._parse_compilation_issue(entry)
            if not parsed:
                continue
            current_issues[parsed["key"]] = {
                "code": parsed["code"],
                "file": parsed["file"],
                "message": parsed["message"],
                "location": parsed["location"],
                "scene": scene_name,
            }
        return self._record_pattern_tracker("_compilation_errors_tracker", current_issues)

    def get_recurring_compilation_errors(self, min_seen: int = 2) -> List[Dict[str, Any]]:
        data = self._load()
        tracker_key = f"{CATEGORY_PATTERN}:_compilation_errors_tracker"
        tracker = data["entries"].get(tracker_key, {}).get("content", {}).get("value", {})
        results = []
        for info in tracker.values():
            if info.get("seen_count", 1) >= min_seen:
                results.append({
                    "code": info.get("code", ""),
                    "file": info.get("file", ""),
                    "message": info.get("message", ""),
                    "location": info.get("location", ""),
                    "scene": info.get("scene", ""),
                    "seenCount": info.get("seen_count", 1),
                    "firstSeen": info.get("first_seen", ""),
                    "lastSeen": info.get("last_seen", ""),
                })
        results.sort(key=lambda item: (-int(item.get("seenCount", 0)), item.get("code", ""), item.get("file", "")))
        return results

    def record_operational_signals(
        self,
        signals: List[Dict[str, Any]],
        scene_name: str,
    ) -> Dict[str, Any]:
        current_issues: Dict[str, Dict[str, Any]] = {}
        for signal in signals:
            if not isinstance(signal, dict):
                continue
            kind = str(signal.get("kind") or "").strip().lower()
            key = str(signal.get("key") or "").strip()
            if not kind or not key:
                continue
            current_issues[f"{kind}|{key}"] = {
                "kind": kind,
                "key": key,
                "title": str(signal.get("title") or key).strip(),
                "detail": str(signal.get("detail") or "").strip(),
                "scene": scene_name,
                "evidence": dict(signal.get("evidence") or {}),
            }
        return self._record_pattern_tracker("_operational_signals_tracker", current_issues)

    def get_recurring_operational_signals(self, min_seen: int = 2) -> List[Dict[str, Any]]:
        data = self._load()
        tracker_key = f"{CATEGORY_PATTERN}:_operational_signals_tracker"
        tracker = data["entries"].get(tracker_key, {}).get("content", {}).get("value", {})
        results = []
        for info in tracker.values():
            if info.get("seen_count", 1) >= min_seen:
                results.append({
                    "kind": info.get("kind", ""),
                    "key": info.get("key", ""),
                    "title": info.get("title", ""),
                    "detail": info.get("detail", ""),
                    "scene": info.get("scene", ""),
                    "evidence": info.get("evidence", {}),
                    "seenCount": info.get("seen_count", 1),
                    "firstSeen": info.get("first_seen", ""),
                    "lastSeen": info.get("last_seen", ""),
                })
        results.sort(key=lambda item: (-int(item.get("seenCount", 0)), item.get("kind", ""), item.get("key", "")))
        return results

    def record_queue_snapshot(
        self,
        queue: Dict[str, Any],
        scene_name: str,
        *,
        max_samples: int = 20,
    ) -> Dict[str, Any]:
        data = self._load()
        tracker_key = f"{CATEGORY_PATTERN}:_queue_samples"
        samples = list(
            data["entries"].get(tracker_key, {}).get("content", {}).get("value", []) or []
        )
        samples.append(
            {
                "timestamp": self._now_iso(),
                "scene": scene_name,
                "totalQueued": int(queue.get("totalQueued") or 0),
                "activeAgents": int(queue.get("activeAgents") or 0),
            }
        )
        if max_samples > 0 and len(samples) > max_samples:
            samples = samples[-max_samples:]
        self.save(CATEGORY_PATTERN, "_queue_samples", {"value": samples})
        return self.get_queue_trend_summary()

    def get_queue_trend_summary(
        self,
        *,
        min_stalled_samples: int = 3,
    ) -> Dict[str, Any]:
        data = self._load()
        tracker_key = f"{CATEGORY_PATTERN}:_queue_samples"
        samples = list(
            data["entries"].get(tracker_key, {}).get("content", {}).get("value", []) or []
        )
        if not samples:
            return {
                "status": "no-history",
                "sampleCount": 0,
                "backlogSamples": 0,
                "activeSamples": 0,
                "peakQueued": 0,
                "peakActiveAgents": 0,
                "latestTotalQueued": 0,
                "latestActiveAgents": 0,
                "summary": "No queue history recorded yet.",
            }

        normalized_samples = [
            {
                "timestamp": str(sample.get("timestamp") or ""),
                "scene": str(sample.get("scene") or ""),
                "totalQueued": int(sample.get("totalQueued") or 0),
                "activeAgents": int(sample.get("activeAgents") or 0),
            }
            for sample in samples
            if isinstance(sample, dict)
        ]
        latest = normalized_samples[-1]
        backlog_samples = [
            sample for sample in normalized_samples if int(sample.get("totalQueued") or 0) > 0
        ]
        active_samples = [
            sample for sample in normalized_samples if int(sample.get("activeAgents") or 0) > 0
        ]

        trailing_backlog_samples: list[Dict[str, Any]] = []
        for sample in reversed(normalized_samples):
            if int(sample.get("totalQueued") or 0) <= 0:
                break
            trailing_backlog_samples.append(sample)
        trailing_backlog_samples.reverse()

        is_stalled = (
            len(trailing_backlog_samples) >= max(1, int(min_stalled_samples))
            and len(
                {
                    (
                        int(sample.get("totalQueued") or 0),
                        int(sample.get("activeAgents") or 0),
                    )
                    for sample in trailing_backlog_samples
                }
            )
            == 1
        )

        if is_stalled:
            status = "stalled-backlog-suspected"
            summary = "Queue backlog has stayed non-zero with the same shape across repeated samples."
        elif len(trailing_backlog_samples) >= max(1, int(min_stalled_samples)):
            status = "persistent-backlog"
            summary = "Queue backlog has stayed non-zero across repeated samples."
        elif backlog_samples:
            status = "intermittent-backlog"
            summary = "Queue backlog has appeared in recent samples, but it is not persisting every run."
        elif active_samples:
            status = "active-workers-observed"
            summary = "Queue backlog is clear, but active Unity workers were seen in recent samples."
        else:
            status = "clear"
            summary = "Recent queue samples stayed clear."

        return {
            "status": status,
            "sampleCount": len(normalized_samples),
            "backlogSamples": len(backlog_samples),
            "activeSamples": len(active_samples),
            "peakQueued": max(int(sample.get("totalQueued") or 0) for sample in normalized_samples),
            "peakActiveAgents": max(int(sample.get("activeAgents") or 0) for sample in normalized_samples),
            "latestTotalQueued": int(latest.get("totalQueued") or 0),
            "latestActiveAgents": int(latest.get("activeAgents") or 0),
            "latestTimestamp": str(latest.get("timestamp") or ""),
            "latestScene": str(latest.get("scene") or ""),
            "consecutiveBacklogSamples": len(trailing_backlog_samples),
            "summary": summary,
            "recentSamples": normalized_samples[-5:],
        }


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
