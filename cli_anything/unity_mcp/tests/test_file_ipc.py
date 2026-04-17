"""Tests for core/file_ipc.py — FileIPCClient, discovery, ping, roundtrip, backend integration."""
from __future__ import annotations

import json
import os
import shutil
import time
import unittest
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

from cli_anything.unity_mcp.core.client import UnityMCPClientError, UnityMCPConnectionError, UnityMCPHTTPError
from cli_anything.unity_mcp.core.file_ipc import (
    ContextInjector,
    FileIPCClient,
    FileIPCConnectionError,
    FileIPCError,
    FileIPCTimeoutError,
    _atomic_write,
    _safe_read_json,
    discover_file_ipc_instances,
)
from cli_anything.unity_mcp.core.session import SessionState, SessionStore
from cli_anything.unity_mcp.utils.unity_mcp_backend import (
    BackendSelectionError,
    UnityMCPBackend,
)


class FakeClient:
    def __init__(self, pings: dict[int, dict]) -> None:
        self.pings = pings
        self.use_queue = True

    def ping(self, port: int, timeout: float | None = None) -> dict:
        if port not in self.pings:
            raise UnityMCPClientError("bridge unavailable")
        return self.pings[port]


class RebindingClient(FakeClient):
    def __init__(self, pings: dict[int, dict]) -> None:
        super().__init__(pings)
        self.route_calls: list[int] = []

    def call_route(self, port: int, route: str, params: dict | None = None) -> dict:
        self.route_calls.append(port)
        if port == 7890:
            raise UnityMCPConnectionError("old port is unavailable")
        return {"success": True, "route": route, "port": port, "params": params or {}}


class CatalogClient(FakeClient):
    def __init__(self, pings: dict[int, dict]) -> None:
        super().__init__(pings)
        self.calls: list[tuple[str, int, dict]] = []

    def call_route(self, port: int, route: str, params: dict | None = None) -> dict:
        self.calls.append((route, port, params or {}))
        return {"success": True, "route": route, "port": port, "params": params or {}}


class ErrorRouteClient(FakeClient):
    def call_route(self, port: int, route: str, params: dict | None = None) -> dict:
        raise UnityMCPClientError(f"route failed: {route}")


class ContextFallbackClient(FakeClient):
    def __init__(self, pings: dict[int, dict]) -> None:
        super().__init__(pings)
        self.route_calls: list[tuple[int, str, dict]] = []
        self.get_calls: list[tuple[int, str]] = []

    def call_route(self, port: int, route: str, params: dict | None = None) -> dict:
        self.route_calls.append((port, route, params or {}))
        raise UnityMCPHTTPError(404, "not found")

    def get_api(self, port: int, api_path: str, query: dict | None = None, timeout: float | None = None) -> dict:
        self.get_calls.append((port, api_path))
        return {"projectPath": "C:/Projects/Demo", "apiPath": api_path}


class ContextQueueUnknownClient(FakeClient):
    def __init__(self, pings: dict[int, dict]) -> None:
        super().__init__(pings)
        self.route_calls: list[tuple[int, str, dict]] = []
        self.get_calls: list[tuple[int, str]] = []

    def call_route(self, port: int, route: str, params: dict | None = None) -> dict:
        self.route_calls.append((port, route, params or {}))
        if route == "context":
            return {"error": "Unknown API endpoint: context"}
        if route == "editor/execute-code":
            return {
                "success": True,
                "result": {
                    "enabled": True,
                    "contextPath": "Assets/MCP/Context",
                    "fileCount": 1,
                    "categories": [
                        {
                            "category": "Architecture",
                            "content": "Main-thread-safe context.",
                        }
                    ],
                },
            }
        return {"error": f"Unexpected route: {route}"}

    def get_api(self, port: int, api_path: str, query: dict | None = None, timeout: float | None = None) -> dict:
        self.get_calls.append((port, api_path))
        raise AssertionError("context queue fallback should not use direct GET when execute-code works")


class RebindingBackend(UnityMCPBackend):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.discovery_calls = 0

    def discover_instances(self) -> list[dict]:
        self.discovery_calls += 1
        if self.discovery_calls < 2:
            return []
        return [
            {
                "port": 7891,
                "projectName": "Demo",
                "projectPath": "C:/Projects/Demo",
                "unityVersion": "6000.0.0f1",
                "platform": "WindowsEditor",
                "isClone": False,
                "cloneIndex": -1,
                "processId": 1234,
                "source": "portscan",
            }
        ]


class FileIPCTests(unittest.TestCase):

    def test_file_ipc_client_ping_raises_when_no_umcp_dir(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            client = FileIPCClient(tmpdir)
            with self.assertRaises(FileIPCConnectionError):
                client.ping()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_file_ipc_client_ping_reads_heartbeat(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            umcp = tmpdir / ".umcp"
            umcp.mkdir()
            from datetime import datetime, timezone
            ping_data = {
                "status": "ok",
                "projectName": "TestProject",
                "projectPath": str(tmpdir),
                "unityVersion": "6000.4.0f1",
                "platform": "WindowsEditor",
                "lastHeartbeat": datetime.now(timezone.utc).isoformat(),
                "transport": "file-ipc",
            }
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            client = FileIPCClient(tmpdir)
            result = client.ping()
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["projectName"], "TestProject")
            self.assertEqual(result["transport"], "file-ipc")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_file_ipc_client_ping_rejects_stale_heartbeat(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            umcp = tmpdir / ".umcp"
            umcp.mkdir()
            from datetime import datetime, timezone, timedelta
            stale_time = datetime.now(timezone.utc) - timedelta(seconds=30)
            ping_data = {
                "status": "ok",
                "projectName": "StaleProject",
                "lastHeartbeat": stale_time.isoformat(),
            }
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            client = FileIPCClient(tmpdir)
            with self.assertRaises(FileIPCConnectionError):
                client.ping()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_file_ipc_client_call_route_roundtrip(self) -> None:
        """Simulate Unity responding to a file IPC command."""
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            client = FileIPCClient(tmpdir, poll_interval=0.01, timeout=2.0)
            client.ensure_dirs()

            import threading
            captured: dict[str, Any] = {}

            def fake_unity_responder():
                """Watch inbox, write response to outbox."""
                import time as _time
                deadline = _time.monotonic() + 2.0
                while _time.monotonic() < deadline:
                    inbox = tmpdir / ".umcp" / "inbox"
                    if inbox.exists():
                        for f in inbox.iterdir():
                            if f.suffix == ".json":
                                cmd = json.loads(f.read_text())
                                captured.update(cmd)
                                f.unlink()
                                response = {
                                    "id": cmd["id"],
                                    "result": {
                                        "success": True,
                                        "route": cmd["route"],
                                        "echo": json.loads(cmd.get("params") or "{}"),
                                    },
                                }
                                outbox = tmpdir / ".umcp" / "outbox"
                                outbox.mkdir(parents=True, exist_ok=True)
                                resp_path = outbox / f"{cmd['id']}.json"
                                resp_path.write_text(json.dumps(response))
                                return
                    _time.sleep(0.01)

            responder = threading.Thread(target=fake_unity_responder, daemon=True)
            responder.start()

            result = client.call_route("scene/info", params={"key": "value"})
            self.assertTrue(result["success"])
            self.assertEqual(result["route"], "scene/info")
            self.assertEqual(result["echo"]["key"], "value")
            self.assertIsInstance(captured["params"], str)

            responder.join(timeout=2.0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_file_ipc_client_timeout_raises(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            client = FileIPCClient(tmpdir, poll_interval=0.01, timeout=0.05)
            client.ensure_dirs()

            with self.assertRaises(FileIPCTimeoutError):
                client.call_route("scene/info")

            # Command file should have been cleaned up on timeout
            inbox_files = list((tmpdir / ".umcp" / "inbox").iterdir())
            self.assertEqual(len(inbox_files), 0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_file_ipc_discovery_finds_active_project(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            umcp = tmpdir / ".umcp"
            umcp.mkdir()
            from datetime import datetime, timezone
            ping_data = {
                "status": "ok",
                "projectName": "DiscoverMe",
                "projectPath": str(tmpdir),
                "unityVersion": "6000.4.0f1",
                "lastHeartbeat": datetime.now(timezone.utc).isoformat(),
            }
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            instances = discover_file_ipc_instances([tmpdir])
            self.assertEqual(len(instances), 1)
            self.assertEqual(instances[0]["projectName"], "DiscoverMe")
            self.assertEqual(instances[0]["transport"], "file-ipc")
            self.assertIsNone(instances[0]["port"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_file_ipc_discovery_skips_stale_project(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            umcp = tmpdir / ".umcp"
            umcp.mkdir()
            from datetime import datetime, timezone, timedelta
            stale = datetime.now(timezone.utc) - timedelta(seconds=60)
            ping_data = {"status": "ok", "lastHeartbeat": stale.isoformat()}
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            instances = discover_file_ipc_instances([tmpdir])
            self.assertEqual(len(instances), 0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_file_ipc_cleanup_removes_stale_files(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            client = FileIPCClient(tmpdir)
            client.ensure_dirs()

            # Create old files
            old_file = tmpdir / ".umcp" / "inbox" / "old-command.json"
            old_file.write_text('{"id":"old"}')
            # Backdate the file
            import time
            old_time = time.time() - 120
            os.utime(old_file, (old_time, old_time))

            # Create recent file
            new_file = tmpdir / ".umcp" / "inbox" / "new-command.json"
            new_file.write_text('{"id":"new"}')

            cleaned = client.cleanup_stale(max_age_seconds=60.0)
            self.assertEqual(cleaned, 1)
            self.assertFalse(old_file.exists())
            self.assertTrue(new_file.exists())
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_backend_discovers_file_ipc_instances(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            # Set up a file IPC project
            umcp = tmpdir / "MyProject" / ".umcp"
            umcp.mkdir(parents=True)
            from datetime import datetime, timezone
            ping_data = {
                "status": "ok",
                "projectName": "MyProject",
                "projectPath": str(tmpdir / "MyProject"),
                "unityVersion": "6000.4.0f1",
                "lastHeartbeat": datetime.now(timezone.utc).isoformat(),
                "transport": "file-ipc",
            }
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            # Create backend with file transport only (skip HTTP)
            fake_client = FakeClient(pings={})
            session_path = tmpdir / "session.json"
            backend = UnityMCPBackend(
                client=fake_client,
                session_store=SessionStore(session_path),
                registry_path=tmpdir / "instances.json",
                transport="file",
                file_ipc_paths=[tmpdir / "MyProject"],
            )

            instances = backend.discover_instances()
            self.assertEqual(len(instances), 1)
            self.assertEqual(instances[0]["projectName"], "MyProject")
            self.assertEqual(instances[0]["transport"], "file-ipc")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_backend_file_ipc_ping_and_queue_info_do_not_use_http(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        umcp = project / ".umcp"
        umcp.mkdir(parents=True, exist_ok=True)
        try:
            from datetime import datetime, timezone

            ping_data = {
                "status": "ok",
                "projectName": "MyProject",
                "projectPath": str(project),
                "unityVersion": "6000.4.0f1",
                "lastHeartbeat": datetime.now(timezone.utc).isoformat(),
                "transport": "file-ipc",
            }
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            session_store = SessionStore(tmpdir / "session.json")
            session_store.save(
                SessionState(
                    selected_port=None,
                    selected_instance={
                        "projectName": "MyProject",
                        "projectPath": str(project),
                        "port": None,
                        "transport": "file-ipc",
                    },
                    history=[],
                )
            )
            backend = UnityMCPBackend(
                client=FakeClient(pings={}),
                session_store=session_store,
                registry_path=tmpdir / "instances.json",
                transport="file",
                file_ipc_paths=[project],
            )
            backend.set_runtime_context(agent_id="agent-file-ipc")

            ping = backend.ping()
            self.assertEqual(ping["projectName"], "MyProject")
            self.assertEqual(ping["transport"], "file-ipc")
            self.assertIsNone(ping["port"])

            with patch.object(
                FileIPCClient,
                "call_route",
                return_value={
                    "transport": "file-ipc",
                    "queueSupported": False,
                    "activeAgents": 1,
                    "totalQueued": 0,
                    "agentId": "agent-file-ipc",
                    "message": "File IPC executes each request on Unity's main thread from .umcp/inbox; no Unity queue is required.",
                },
            ) as call_route:
                queue = backend.get_queue_info()
            self.assertFalse(queue["queueSupported"])
            self.assertEqual(queue["transport"], "file-ipc")
            self.assertEqual(queue["activeAgents"], 1)
            self.assertEqual(queue["totalQueued"], 0)
            self.assertEqual(queue["agentId"], "agent-file-ipc")
            self.assertIn("no Unity queue is required", queue["message"])
            call_route.assert_called_once_with("queue/info", timeout=1.0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_ping_auto_selects_single_file_ipc_instance_when_none_is_selected(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        umcp = project / ".umcp"
        umcp.mkdir(parents=True, exist_ok=True)
        try:
            from datetime import datetime, timezone

            ping_data = {
                "status": "ok",
                "projectName": "MyProject",
                "projectPath": str(project),
                "unityVersion": "6000.4.0f1",
                "lastHeartbeat": datetime.now(timezone.utc).isoformat(),
                "transport": "file-ipc",
            }
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            backend = UnityMCPBackend(
                client=FakeClient(pings={}),
                session_store=SessionStore(tmpdir / "session.json"),
                registry_path=tmpdir / "instances.json",
                transport="file",
                file_ipc_paths=[project],
            )

            result = backend.ping()

            self.assertEqual(result["projectName"], "MyProject")
            self.assertEqual(result["transport"], "file-ipc")
            state = backend.session_store.load()
            self.assertEqual((state.selected_instance or {}).get("projectPath"), str(project))
            self.assertEqual((state.selected_instance or {}).get("transport"), "file-ipc")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_emit_unity_breadcrumb_uses_file_ipc_route_when_selected_instance_is_file_transport(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        umcp = project / ".umcp"
        umcp.mkdir(parents=True, exist_ok=True)
        try:
            from datetime import datetime, timezone

            ping_data = {
                "status": "ok",
                "projectName": "MyProject",
                "projectPath": str(project),
                "unityVersion": "6000.4.0f1",
                "lastHeartbeat": datetime.now(timezone.utc).isoformat(),
                "transport": "file-ipc",
            }
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            session_store = SessionStore(tmpdir / "session.json")
            session_store.save(
                SessionState(
                    selected_port=None,
                    selected_instance={
                        "projectName": "MyProject",
                        "projectPath": str(project),
                        "port": None,
                        "transport": "file-ipc",
                    },
                    history=[],
                )
            )
            backend = UnityMCPBackend(
                client=FakeClient(pings={}),
                session_store=session_store,
                registry_path=tmpdir / "instances.json",
                transport="file",
                file_ipc_paths=[project],
            )

            with patch.object(
                FileIPCClient,
                "call_route",
                return_value={"success": True, "level": "info", "message": "hello"},
            ) as call_route:
                result = backend.emit_unity_breadcrumb("hello")

            self.assertTrue(result["success"])
            call_route.assert_called_once_with(
                "debug/breadcrumb",
                params={"message": "hello", "level": "info"},
            )
            history = backend.get_history()
            self.assertEqual(history[-1]["command"], "debug/breadcrumb")
            self.assertEqual(history[-1]["transport"], "file-ipc")
            self.assertEqual(history[-1]["status"], "ok")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_get_context_uses_file_ipc_route_when_selected_instance_is_file_transport(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        umcp = project / ".umcp"
        umcp.mkdir(parents=True, exist_ok=True)
        try:
            from datetime import datetime, timezone

            ping_data = {
                "status": "ok",
                "projectName": "MyProject",
                "projectPath": str(project),
                "unityVersion": "6000.4.0f1",
                "lastHeartbeat": datetime.now(timezone.utc).isoformat(),
                "transport": "file-ipc",
            }
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            session_store = SessionStore(tmpdir / "session.json")
            session_store.save(
                SessionState(
                    selected_port=None,
                    selected_instance={
                        "projectName": "MyProject",
                        "projectPath": str(project),
                        "port": None,
                        "transport": "file-ipc",
                    },
                    history=[],
                )
            )
            backend = UnityMCPBackend(
                client=FakeClient(pings={}),
                session_store=session_store,
                registry_path=tmpdir / "instances.json",
                transport="file",
                file_ipc_paths=[project],
            )

            with patch.object(
                FileIPCClient,
                "call_route",
                return_value={"projectPath": str(project), "renderPipeline": "builtin"},
            ) as call_route:
                result = backend.get_context()

            self.assertEqual(result["projectPath"], str(project))
            call_route.assert_called_once_with("context", params={})
            history = backend.get_history()
            self.assertEqual(history[-1]["command"], "context")
            self.assertEqual(history[-1]["transport"], "file-ipc")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_record_progress_uses_file_ipc_breadcrumb_without_fake_port_zero(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        umcp = project / ".umcp"
        umcp.mkdir(parents=True, exist_ok=True)
        try:
            from datetime import datetime, timezone

            ping_data = {
                "status": "ok",
                "projectName": "MyProject",
                "projectPath": str(project),
                "unityVersion": "6000.4.0f1",
                "lastHeartbeat": datetime.now(timezone.utc).isoformat(),
                "transport": "file-ipc",
            }
            (umcp / "ping.json").write_text(json.dumps(ping_data))

            session_store = SessionStore(tmpdir / "session.json")
            session_store.save(
                SessionState(
                    selected_port=None,
                    selected_instance={
                        "projectName": "MyProject",
                        "projectPath": str(project),
                        "port": None,
                        "transport": "file-ipc",
                    },
                    history=[],
                )
            )
            backend = UnityMCPBackend(
                client=FakeClient(pings={}),
                session_store=session_store,
                registry_path=tmpdir / "instances.json",
                transport="file",
                file_ipc_paths=[project],
            )

            with patch.object(backend, "emit_unity_breadcrumb", return_value={"success": True}) as emit_breadcrumb:
                backend.record_progress("Checking project info")

            emit_breadcrumb.assert_called_once()
            self.assertIsNone(emit_breadcrumb.call_args.kwargs["port"])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_agent_loop_prefers_backend_file_ipc_resolver(self) -> None:
        from cli_anything.unity_mcp.commands.agent_loop_cmd import _resolve_file_ipc_client

        sentinel = object()

        class BackendStub:
            def _resolve_file_ipc_client(self) -> object:
                return sentinel

        client = _resolve_file_ipc_client(BackendStub())
        self.assertIs(client, sentinel)

    def test_agent_loop_falls_back_to_selected_instance_project_path(self) -> None:
        from cli_anything.unity_mcp.commands.agent_loop_cmd import _resolve_file_ipc_client

        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        project = tmpdir / "MyProject"
        umcp = project / ".umcp"
        umcp.mkdir(parents=True, exist_ok=True)
        try:
            session_store = SessionStore(tmpdir / "session.json")
            session_store.save(
                SessionState(
                    selected_port=None,
                    selected_instance={
                        "projectName": "MyProject",
                        "projectPath": str(project),
                        "port": None,
                        "transport": "file-ipc",
                    },
                    history=[],
                )
            )

            class BackendStub:
                def __init__(self, store: SessionStore) -> None:
                    self.session_store = store

            with patch.object(FileIPCClient, "is_alive", return_value=True):
                client = _resolve_file_ipc_client(BackendStub(session_store))

            self.assertIsInstance(client, FileIPCClient)
            self.assertEqual(client.project_path, project)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_context_injector_refetches_for_full_context(self) -> None:
        class ClientStub:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, Any]]] = []

            def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                self.calls.append((route, params))
                return {"mode": "full" if params.get("full") else "summary"}

        client = ClientStub()
        injector = ContextInjector(client)  # type: ignore[arg-type]

        summary = injector.get()
        full = injector.get(full=True)

        self.assertEqual(summary["mode"], "summary")
        self.assertEqual(full["mode"], "full")
        self.assertEqual(
            client.calls,
            [
                ("context", {"full": False}),
                ("context", {"full": True}),
                ("editor/state", {}),
                ("scene/hierarchy", {}),
            ],
        )

    def test_context_injector_enriches_shallow_full_context(self) -> None:
        class ClientStub:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, Any]]] = []

            def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                self.calls.append((route, params))
                if route == "context":
                    return {
                        "projectName": "OutsideTheBox",
                        "scene": {"name": "CodexFpsShowcase"},
                    }
                if route == "editor/state":
                    return {"activeScene": "CodexFpsShowcase", "isPlaying": False}
                if route == "scene/hierarchy":
                    return {"sceneName": "CodexFpsShowcase", "nodes": [{"name": "Player"}]}
                raise AssertionError(f"unexpected route: {route}")

        client = ClientStub()
        injector = ContextInjector(client)  # type: ignore[arg-type]

        full = injector.get(full=True)

        self.assertEqual(full["editorState"]["activeScene"], "CodexFpsShowcase")
        self.assertEqual(full["hierarchy"]["sceneName"], "CodexFpsShowcase")
        self.assertEqual(full["hierarchy"]["nodes"][0]["name"], "Player")
        self.assertEqual(
            client.calls,
            [
                ("context", {"full": True}),
                ("editor/state", {}),
                ("scene/hierarchy", {}),
            ],
        )

    def test_context_injector_ignores_enrichment_route_failures(self) -> None:
        class ClientStub:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, Any]]] = []

            def call_route(self, route: str, params: dict[str, Any]) -> dict[str, Any]:
                self.calls.append((route, params))
                if route == "context":
                    return {"projectName": "OutsideTheBox"}
                raise FileIPCError(f"missing route: {route}")

        client = ClientStub()
        injector = ContextInjector(client)  # type: ignore[arg-type]

        full = injector.get(full=True)

        self.assertEqual(full["projectName"], "OutsideTheBox")
        self.assertNotIn("editorState", full)
        self.assertNotIn("hierarchy", full)
        self.assertEqual(
            client.calls,
            [
                ("context", {"full": True}),
                ("editor/state", {}),
                ("scene/hierarchy", {}),
            ],
        )
