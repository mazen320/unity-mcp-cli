"""File-based IPC transport for Unity communication.

Provides a zero-config alternative to the HTTP bridge. Commands are exchanged
as JSON files through a ``.umcp/`` directory inside the Unity project root:

    ProjectRoot/.umcp/
        inbox/      <- CLI writes command files here
        outbox/     <- Unity writes response files here
        ping.json   <- Unity refreshes this with project info

The Unity side polls ``inbox/`` on the main thread via
``EditorApplication.update``, so every command executes on Unity's main thread
automatically — no queue system needed, no ``GetBool`` threading errors.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class FileIPCError(RuntimeError):
    """Base error for file IPC transport."""


class FileIPCConnectionError(FileIPCError):
    """Raised when the Unity project's .umcp directory is missing or stale."""


class FileIPCTimeoutError(FileIPCError):
    """Raised when a command response doesn't arrive in time."""


# How long a ping.json file can be before we consider Unity "not running"
_PING_STALENESS_SECONDS = 10.0

# Atomic write: write to .tmp, rename to .json
_TMP_SUFFIX = ".tmp"


def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON atomically — temp file then rename to avoid partial reads."""
    tmp = path.with_suffix(_TMP_SUFFIX)
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _safe_read_json(path: Path) -> Optional[dict]:
    """Read a JSON file, returning None on any failure."""
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


class FileIPCClient:
    """Sends commands to Unity via file-based IPC.

    Mirrors the key methods of ``UnityMCPClient`` so the backend can
    delegate to either transport transparently.
    """

    def __init__(
        self,
        project_path: str | Path,
        poll_interval: float = 0.05,
        timeout: float = 30.0,
        agent_id: str = "cli-anything-unity-mcp",
    ) -> None:
        self.project_path = Path(project_path)
        self.umcp_root = self.project_path / ".umcp"
        self.inbox = self.umcp_root / "inbox"
        self.outbox = self.umcp_root / "outbox"
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.agent_id = agent_id

    # ── directory setup ──────────────────────────────────────────────────

    def ensure_dirs(self) -> None:
        """Create .umcp/inbox and .umcp/outbox if they don't exist."""
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.outbox.mkdir(parents=True, exist_ok=True)

    # ── ping / discovery ─────────────────────────────────────────────────

    def ping(self, timeout: float = 3.0) -> Dict[str, Any]:
        """Read the ping.json heartbeat file.

        Returns the project info dict if Unity is alive and the ping file
        is fresh enough, otherwise raises ``FileIPCConnectionError``.
        """
        ping_file = self.umcp_root / "ping.json"
        if not ping_file.exists():
            raise FileIPCConnectionError(
                f"No .umcp/ping.json found in {self.project_path}"
            )

        data = _safe_read_json(ping_file)
        if data is None:
            raise FileIPCConnectionError(
                f"Could not read .umcp/ping.json in {self.project_path}"
            )

        # Check freshness — Unity refreshes this every ~2 seconds
        last_heartbeat = data.get("lastHeartbeat")
        if last_heartbeat:
            try:
                heartbeat_time = datetime.fromisoformat(last_heartbeat)
                now = datetime.now(timezone.utc)
                if heartbeat_time.tzinfo is None:
                    heartbeat_time = heartbeat_time.replace(tzinfo=timezone.utc)
                age = (now - heartbeat_time).total_seconds()
                if age > _PING_STALENESS_SECONDS:
                    raise FileIPCConnectionError(
                        f"Unity heartbeat is {age:.1f}s stale in {self.project_path} "
                        f"(last: {last_heartbeat})"
                    )
            except (ValueError, TypeError):
                pass  # can't parse timestamp — allow it

        data.setdefault("status", "ok")
        data.setdefault("transport", "file-ipc")
        return data

    def is_alive(self, timeout: float = 3.0) -> bool:
        """Return True if Unity is reachable via file IPC."""
        try:
            self.ping(timeout=timeout)
            return True
        except FileIPCError:
            return False

    # ── command execution ────────────────────────────────────────────────

    def call_route(
        self,
        route: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Send a route command and wait for the response.

        1. Write a command JSON file to inbox/
        2. Poll outbox/ for a response file with the same ID
        3. Return the result or raise on error/timeout
        """
        self.ensure_dirs()

        cmd_id = str(uuid.uuid4())
        effective_timeout = timeout if timeout is not None else self.timeout

        command = {
            "id": cmd_id,
            "route": route,
            # Unity's JsonUtility cannot deserialize arbitrary object fields into
            # CommandData, so send params as a raw JSON string for the editor side.
            "params": json.dumps(params or {}, separators=(",", ":"), ensure_ascii=True),
            "agentId": self.agent_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Write command atomically
        cmd_file = self.inbox / f"{cmd_id}.json"
        _atomic_write(cmd_file, command)

        # Poll for response
        response_file = self.outbox / f"{cmd_id}.json"
        deadline = time.monotonic() + effective_timeout

        try:
            while time.monotonic() < deadline:
                if response_file.exists():
                    response = _safe_read_json(response_file)
                    # Clean up response file
                    try:
                        response_file.unlink()
                    except OSError:
                        pass

                    if response is None:
                        raise FileIPCError(
                            f"Corrupted response file for route {route} (id: {cmd_id})"
                        )

                    if response.get("error"):
                        raise FileIPCError(
                            f"Unity returned error for route {route}: {response['error']}"
                        )

                    return response.get("result", response)

                time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            # Clean up command file if we're interrupted
            self._cleanup_command(cmd_file)
            raise

        # Timeout — clean up the stale command
        self._cleanup_command(cmd_file)
        raise FileIPCTimeoutError(
            f"File IPC timeout after {effective_timeout:.1f}s waiting for "
            f"route {route} (id: {cmd_id})"
        )

    def get_api(
        self,
        api_path: str,
        query: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Emulate a GET API call via file IPC.

        Sends a command with ``_method: "GET"`` so the Unity side knows
        to treat it as a read-only query.
        """
        params = dict(query or {})
        params["_method"] = "GET"
        return self.call_route(api_path, params=params, timeout=timeout)

    @staticmethod
    def _cleanup_command(cmd_file: Path) -> None:
        try:
            if cmd_file.exists():
                cmd_file.unlink()
        except OSError:
            pass

    # ── stale file cleanup ───────────────────────────────────────────────

    def cleanup_stale(self, max_age_seconds: float = 60.0) -> int:
        """Remove command/response files older than *max_age_seconds*.

        Returns the number of files cleaned up.  Safe to call periodically.
        """
        cleaned = 0
        now = time.time()
        for folder in (self.inbox, self.outbox):
            if not folder.is_dir():
                continue
            for f in folder.iterdir():
                if f.suffix not in (".json", _TMP_SUFFIX):
                    continue
                try:
                    if now - f.stat().st_mtime > max_age_seconds:
                        f.unlink()
                        cleaned += 1
                except OSError:
                    pass
        return cleaned


# ── Context injector ─────────────────────────────────────────────────────────

class ContextInjector:
    """Fetches rich Unity project context once per session and caches it.

    Call ``get()`` to retrieve the full context dict.
    Call ``as_system_prompt()`` to get a compact string suitable for injecting
    into an AI system prompt or MCP ``initialize`` instructions.
    """

    def __init__(self, client: "FileIPCClient") -> None:
        self._client = client
        self._context: Optional[dict] = None
        self._context_is_full = False

    def _safe_route(self, route: str, params: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
        try:
            payload = self._client.call_route(route, params or {})
        except FileIPCError:
            return None
        return payload if isinstance(payload, dict) else None

    def _enrich_full_context(self, context: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(context.get("editorState"), dict):
            editor_state = self._safe_route("editor/state")
            if editor_state:
                context["editorState"] = editor_state

        if "hierarchy" not in context or context.get("hierarchy") is None:
            hierarchy = self._safe_route("scene/hierarchy")
            if hierarchy:
                context["hierarchy"] = hierarchy

        scene = context.get("scene")
        editor_state = context.get("editorState")
        if isinstance(scene, dict) and isinstance(editor_state, dict):
            if not editor_state.get("activeScene") and scene.get("name"):
                editor_state["activeScene"] = scene.get("name")
            if not editor_state.get("activeScenePath") and scene.get("path"):
                editor_state["activeScenePath"] = scene.get("path")
            if "sceneDirty" not in editor_state and "isDirty" in scene:
                editor_state["sceneDirty"] = scene.get("isDirty")

        return context

    def get(self, *, force: bool = False, full: bool = False) -> Dict[str, Any]:
        """Return cached project context, fetching from Unity if needed."""
        needs_refresh = self._context is None or force or (full and not self._context_is_full)
        if needs_refresh:
            try:
                self._context = self._client.call_route("context", {"full": full})
                if full and isinstance(self._context, dict):
                    self._context = self._enrich_full_context(self._context)
                self._context_is_full = bool(full)
            except FileIPCError:
                self._context = {}
                self._context_is_full = False
        return self._context

    def invalidate(self) -> None:
        """Clear the cache so the next ``get()`` re-fetches from Unity."""
        self._context = None
        self._context_is_full = False

    def as_system_prompt(self, *, full: bool = False) -> str:
        """Return a compact system-prompt block describing the Unity project."""
        ctx = self.get(full=full)
        if not ctx:
            return "## Unity Project Context\n(not connected)"

        scene = ctx.get("scene") or {}
        asset_counts = ctx.get("assetCounts") or {}
        packages = ctx.get("packages") or []
        compile_errors = ctx.get("compileErrors") or []
        console_errors = ctx.get("recentConsoleErrors") or []
        tags = ctx.get("tags") or []
        scripts = ctx.get("scripts") or []

        lines = [
            "## Unity Project Context",
            f"Project: {ctx.get('projectName', '?')}  |  Unity {ctx.get('unityVersion', '?')}  |  {ctx.get('renderPipeline', '?')}  |  {ctx.get('platform', '?')}",
            f"Scene: {scene.get('name', '?')}  ({scene.get('objectCount', '?')} objects, roots: {', '.join(scene.get('rootObjects') or [])})",
            f"Assets: {ctx.get('scriptCount', 0)} scripts | {asset_counts.get('prefabs', 0)} prefabs | {asset_counts.get('materials', 0)} materials | {asset_counts.get('textures', 0)} textures | {asset_counts.get('scenes', 0)} scenes",
        ]

        if scripts:
            script_names = [s.get("name", "") for s in scripts[:30]]
            lines.append(f"Scripts: {', '.join(script_names)}" + (" ..." if len(scripts) > 30 else ""))

        if packages:
            pkg_names = [p.get("name", "").replace("com.unity.", "") for p in packages[:10]]
            lines.append(f"Packages: {', '.join(pkg_names)}")

        if tags:
            lines.append(f"Tags: {', '.join(str(t) for t in tags[:15])}")

        if ctx.get("isCompiling"):
            lines.append("⚠ Currently compiling...")

        if compile_errors:
            lines.append(f"⛔ COMPILE ERRORS ({len(compile_errors)}):")
            for err in compile_errors[:3]:
                msg = err.get("message", "") if isinstance(err, dict) else str(err)
                lines.append(f"  • {msg[:120]}")

        if console_errors and not compile_errors:
            msg = console_errors[0].get("message", "") if isinstance(console_errors[0], dict) else str(console_errors[0])
            lines.append(f"Recent error: {msg[:120]}")

        if full:
            legacy_context = ctx.get("legacyContext") or []
            if legacy_context:
                lines.append("")
                lines.append("## Project Guidance")
                for entry in legacy_context[:4]:
                    category = str(entry.get("category") or "Context").strip()
                    content = " ".join(str(entry.get("content") or "").split())
                    if not content:
                        continue
                    lines.append(f"{category}: {content[:400]}" + ("..." if len(content) > 400 else ""))

        return "\n".join(lines)


# ── Discovery helper ─────────────────────────────────────────────────────────

def discover_file_ipc_instances(
    search_paths: Optional[List[str | Path]] = None,
) -> List[Dict[str, Any]]:
    """Find Unity projects that have an active .umcp file IPC bridge.

    *search_paths* is a list of Unity project root directories to check.
    Each path is probed for ``.umcp/ping.json`` — if it exists and is fresh,
    the project is returned as a discovered instance.

    Returns a list of instance dicts compatible with the HTTP discovery
    format (including ``transport: "file-ipc"``).
    """
    instances: List[Dict[str, Any]] = []
    if not search_paths:
        return instances

    for project_path in search_paths:
        project_path = Path(project_path)
        client = FileIPCClient(project_path)
        try:
            ping_data = client.ping()
        except FileIPCError:
            continue

        instance = {
            "port": None,  # no port for file IPC
            "projectName": ping_data.get("projectName", project_path.name),
            "projectPath": str(ping_data.get("projectPath", project_path)),
            "unityVersion": ping_data.get("unityVersion", "unknown"),
            "platform": ping_data.get("platform", "unknown"),
            "isClone": ping_data.get("isClone", False),
            "cloneIndex": ping_data.get("cloneIndex", -1),
            "processId": ping_data.get("processId"),
            "source": "file-ipc",
            "transport": "file-ipc",
        }
        instances.append(instance)

    return instances
