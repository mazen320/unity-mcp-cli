"""agent_chat.py — File-IPC chat bridge.

Polls queued files under `.umcp/chat/user-inbox/` for messages sent from the
Unity EditorWindow Agent tab, processes them (runs File IPC routes or forwards
to the agentic loop), and writes conversation history to
`.umcp/chat/history.json` for the Unity panel to display.

Usage (run this as a background thread or subprocess alongside your agent):
    from .agent_chat import ChatBridge
    bridge = ChatBridge(project_path="/path/to/unity/project", file_client=client)
    bridge.run()   # blocks; Ctrl-C to stop
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .file_ipc import FileIPCClient, ContextInjector


# ── ChatBridge ────────────────────────────────────────────────────────────────

class ChatBridge:
    """Connects the Unity EditorWindow Agent tab to the Python agent loop.

    Polls ``.umcp/chat/user-inbox/`` for messages from Unity, dispatches
    them to the provided *handler* function (or the default simple handler),
    and writes history + status for the EditorWindow to display.
    """

    def __init__(
        self,
        project_path: str | Path,
        file_client: FileIPCClient,
        handler: Optional[Callable[[str, "ChatBridge"], None]] = None,
        poll_interval: float = 0.25,
    ) -> None:
        self.project_path = Path(project_path)
        self.client = file_client
        self.handler = handler or self._default_handler
        self.poll_interval = poll_interval

        self._umcp = self.project_path / ".umcp"
        self._chat_dir = self._umcp / "chat"
        self._inbox_dir = self._chat_dir / "user-inbox"
        self._legacy_inbox = self._chat_dir / "user-inbox.json"
        self._history_path = self._chat_dir / "history.json"
        self._status_path = self._umcp / "agent-status.json"

        self._history: List[Dict[str, Any]] = []
        self._context = ContextInjector(file_client)
        self._running = False
        self._status_state = "idle"
        self._status_current = 0
        self._status_total = 0
        self._status_action = ""
        self._last_status_write = 0.0
        self._status_heartbeat_interval = 2.0

    # ── Public API ────────────────────────────────────────────────────────

    def run(self) -> None:
        """Block and process messages until stopped."""
        self._running = True
        self._ensure_ready()

        while self._running:
            try:
                self.poll_once()
            except KeyboardInterrupt:
                break
            except Exception:
                pass
            time.sleep(self.poll_interval)

    def stop(self) -> None:
        self._running = False

    def poll_once(self) -> bool:
        """Process at most one pending chat message."""
        self._ensure_ready()
        msg = self._read_inbox()
        if not msg:
            self._heartbeat_status()
            return False
        self._process_message(msg)
        self._heartbeat_status(force=True)
        return True

    def append_message(
        self,
        role: str,
        content: str,
        steps: Optional[list] = None,
        *,
        message_id: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        """Add a message to history and persist it."""
        entry: Dict[str, Any] = {
            "role": role,
            "content": content,
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        }
        if message_id:
            entry["id"] = message_id
        if steps is not None:
            entry["steps"] = steps
        self._history.append(entry)
        self._write_history()

    def write_status(self, state: str, current: int, total: int, action: str) -> None:
        self._status_state = state
        self._status_current = current
        self._status_total = total
        self._status_action = action
        self._write_status(state, current, total, action)

    # ── Internal ──────────────────────────────────────────────────────────

    def _ensure_ready(self) -> None:
        self._chat_dir.mkdir(parents=True, exist_ok=True)
        self._inbox_dir.mkdir(parents=True, exist_ok=True)
        if not self._history:
            self._load_history()
        if not self._status_path.exists():
            self.write_status("idle", 0, 0, "")

    def _heartbeat_status(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last_status_write) < self._status_heartbeat_interval:
            return
        self._write_status(
            self._status_state,
            self._status_current,
            self._status_total,
            self._status_action,
        )

    def _read_inbox(self) -> Optional[Dict[str, Any]]:
        if self._inbox_dir.exists():
            for path in sorted(self._inbox_dir.glob("*.json")):
                try:
                    text = path.read_text(encoding="utf-8-sig")
                    path.unlink()
                    return json.loads(text)
                except Exception:
                    try:
                        path.unlink()
                    except Exception:
                        pass
        if not self._legacy_inbox.exists():
            return None
        try:
            text = self._legacy_inbox.read_text(encoding="utf-8-sig")
            self._legacy_inbox.unlink()
            return json.loads(text)
        except Exception:
            return None

    def _process_message(self, msg: Dict[str, Any]) -> None:
        content = msg.get("content", "").strip()
        if not content:
            return
        self.append_message(
            "user",
            content,
            message_id=str(msg.get("id") or "") or None,
            timestamp=str(msg.get("timestamp") or "") or None,
        )
        self.handler(content, self)

    def _default_handler(self, content: str, bridge: "ChatBridge") -> None:
        """Simple built-in handler: routes short commands to File IPC, else echoes."""
        low = content.lower()

        if low in ("context", "project context", "project info"):
            try:
                ctx = self._context.get(force=True)
                summary = self._context.as_system_prompt()
                bridge.append_message("ai", summary)
            except Exception as exc:
                bridge.append_message("ai", f"Error fetching context: {exc}")

        elif low in ("scene info", "scene", "scene/info"):
            try:
                result = self.client.call_route("scene/info", {})
                bridge.append_message("ai", json.dumps(result, indent=2))
            except Exception as exc:
                bridge.append_message("ai", f"Error: {exc}")

        elif low in ("list scripts", "scripts"):
            try:
                result = self.client.call_route("script/list", {})
                scripts = result.get("scripts", [])
                lines = [f"  • {s.get('name')} ({s.get('path')})" for s in scripts[:30]]
                bridge.append_message("ai", f"{result.get('count', 0)} scripts found:\n" + "\n".join(lines))
            except Exception as exc:
                bridge.append_message("ai", f"Error: {exc}")

        elif low in ("compile errors", "errors", "compilation errors"):
            try:
                result = self.client.call_route("compilation/errors", {})
                if result.get("hasErrors"):
                    msgs = [e.get("message", "") for e in (result.get("entries") or [])[:5]]
                    bridge.append_message("ai", f"{result['count']} compile errors:\n" + "\n".join(msgs))
                else:
                    bridge.append_message("ai", "No compile errors.")
            except Exception as exc:
                bridge.append_message("ai", f"Error: {exc}")

        elif low in ("save scene", "save"):
            try:
                result = self.client.call_route("scene/save", {})
                bridge.append_message("ai", f"Scene saved: {result.get('scene', '?')}")
            except Exception as exc:
                bridge.append_message("ai", f"Error: {exc}")

        elif low in ("hierarchy", "scene hierarchy"):
            try:
                result = self.client.call_route("scene/hierarchy", {"maxNodes": 100})
                nodes = result.get("nodes", [])
                lines = [f"  {'  '*0}• {n.get('name')} [{', '.join(n.get('components', [])[:3])}]"
                         for n in nodes[:20]]
                bridge.append_message("ai",
                    f"Scene: {result.get('sceneName')} ({result.get('totalTraversed')} objects)\n" + "\n".join(lines))
            except Exception as exc:
                bridge.append_message("ai", f"Error: {exc}")

        elif low.startswith("create "):
            # Simple create: "create Cube" or "create Sphere at 0 5 0"
            parts = low[7:].split()
            prim = parts[0].capitalize() if parts else "Cube"
            valid = {"Cube","Sphere","Capsule","Cylinder","Plane","Quad","Empty"}
            if prim not in valid:
                bridge.append_message("ai", f"Unknown primitive '{prim}'. Try: {', '.join(sorted(valid))}")
                return
            try:
                result = self.client.call_route("gameobject/create", {"name": prim, "primitiveType": prim})
                bridge.append_message("ai", f"Created {prim} '{result.get('name', prim)}'")
            except Exception as exc:
                bridge.append_message("ai", f"Error: {exc}")

        else:
            bridge.append_message("ai",
                f"I received: \"{content}\"\n\n"
                "Available quick commands: context, scene info, list scripts, compile errors, "
                "save scene, hierarchy, create <Primitive>\n\n"
                "For complex tasks, use the terminal:\n"
                "  workflow agent-loop --intent \"your intent here\""
            )

    def _load_history(self) -> None:
        if self._history_path.exists():
            try:
                self._history = json.loads(self._history_path.read_text(encoding="utf-8"))
            except Exception:
                self._history = []
        else:
            self._history = []

    def _write_history(self) -> None:
        try:
            self._chat_dir.mkdir(parents=True, exist_ok=True)
            tmp = self._history_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._history, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            tmp.replace(self._history_path)
        except Exception:
            pass

    def _write_status(self, state: str, current: int, total: int, action: str) -> None:
        try:
            self._status_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "state": state,
                "currentStep": current,
                "totalSteps": total,
                "currentAction": action,
                "pid": os.getpid(),
                "projectPath": str(self.project_path),
                "lastUpdated": datetime.now(timezone.utc).isoformat(),
            }
            tmp = self._status_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._status_path)
            self._last_status_write = time.monotonic()
        except Exception:
            pass
