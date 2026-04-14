"""Tests for core/debug_doctor.py and error heuristics — CS codes, Unity runtime patterns, doctor integration."""
from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from cli_anything.unity_mcp.core.debug_doctor import build_debug_doctor_report
from cli_anything.unity_mcp.core.memory import ProjectMemory
from cli_anything.unity_mcp.core.client import UnityMCPClientError, UnityMCPConnectionError, UnityMCPHTTPError
from cli_anything.unity_mcp.core.session import SessionState, SessionStore
from cli_anything.unity_mcp.commands._shared import _format_cli_exception_message, _format_failed_route_hint
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


class HeuristicsTests(unittest.TestCase):

    def test_debug_doctor_report_prioritizes_missing_references_and_queue(self) -> None:
        snapshot = {
            "summary": {
                "port": 7892,
                "projectName": "Demo",
                "activeScene": "MainScene",
                "sceneDirty": True,
                "consoleEntryCount": 3,
            },
            "editorState": {
                "isPlaying": True,
                "isPlayingOrWillChangePlaymode": False,
                "isCompiling": False,
            },
            "console": {
                "entries": [
                    {"message": "Sample warning log", "type": "warning"},
                ]
            },
            "consoleSummary": {"highestSeverity": "warning"},
            "compilation": {"count": 0, "entries": []},
            "missingReferences": {
                "totalFound": 1,
                "results": [{"issue": "Missing script (component is null)", "path": "MainScene/BrokenThing"}],
            },
            "queue": {"totalQueued": 2, "activeAgents": 1},
        }

        report = build_debug_doctor_report(
            snapshot,
            [{"command": "workflow/inspect", "port": 7892}],
            7892,
        )

        self.assertEqual(report["title"], "Unity Debug Doctor")
        self.assertEqual(report["summary"]["assessment"], "error")
        self.assertEqual(report["summary"]["headline"], "Missing References")
        self.assertGreaterEqual(report["summary"]["findingCount"], 4)
        self.assertEqual(report["recentCommands"][0]["command"], "workflow/inspect")
        self.assertTrue(any(item["title"] == "Missing References" for item in report["findings"]))
        self.assertTrue(any(item["title"] == "Queued Requests Pending" for item in report["findings"]))
        self.assertTrue(any(item["title"] == "Active Unity Agents Running" for item in report["findings"]))
        self.assertIn("cli-anything-unity-mcp --json play stop --port 7892", report["recommendedCommands"])
        self.assertIn("cli-anything-unity-mcp --json agent queue --port 7892", report["recommendedCommands"])
        self.assertIn("cli-anything-unity-mcp --json agent sessions --port 7892", report["recommendedCommands"])

    def test_debug_doctor_distinguishes_backlog_without_active_agents(self) -> None:
        snapshot = {
            "summary": {"port": 7892, "consoleEntryCount": 0, "sceneDirty": False},
            "editorState": {"isPlaying": False, "isCompiling": False},
            "console": {"entries": []},
            "consoleSummary": {"highestSeverity": "info"},
            "compilation": {"count": 0, "entries": []},
            "missingReferences": {"totalFound": 0, "results": []},
            "queue": {"totalQueued": 3, "activeAgents": 0},
        }

        report = build_debug_doctor_report(snapshot, [], 7892)

        titles = [item["title"] for item in report["findings"]]
        self.assertIn("Queued Requests Pending", titles)
        self.assertNotIn("Active Unity Agents Running", titles)
        backlog = next(item for item in report["findings"] if item["title"] == "Queued Requests Pending")
        self.assertEqual(backlog["evidence"]["totalQueued"], 3)
        self.assertEqual(backlog["evidence"]["activeAgents"], 0)

    def test_debug_doctor_flags_skybox_camera_using_renderer2d(self) -> None:
        snapshot = {
            "summary": {
                "port": 7892,
                "consoleEntryCount": 0,
                "sceneDirty": False,
            },
            "editorState": {
                "isPlaying": False,
                "isPlayingOrWillChangePlaymode": False,
                "isCompiling": False,
            },
            "console": {"entries": []},
            "consoleSummary": {"highestSeverity": "info"},
            "compilation": {"count": 0, "entries": []},
            "missingReferences": {"totalFound": 0, "results": []},
            "queue": {"totalQueued": 0, "activeAgents": 0},
            "cameraDiagnostics": {
                "cameraName": "MainCamera",
                "clearFlags": "Skybox",
                "rendererName": "UnityEngine.Rendering.Universal.Renderer2D",
                "pipeline": "UniversalRP",
            },
        }

        report = build_debug_doctor_report(snapshot, [], 7892)

        self.assertEqual(report["summary"]["assessment"], "error")
        self.assertEqual(report["summary"]["headline"], "Skybox Blocked By 2D Renderer")
        self.assertTrue(
            any(item["title"] == "Skybox Blocked By 2D Renderer" for item in report["findings"])
        )
        self.assertIn(
            "cli-anything-unity-mcp --json debug capture --kind both --port 7892",
            report["recommendedCommands"],
        )

    def test_debug_doctor_enriches_compilation_errors_with_heuristics(self) -> None:
        snapshot = {
            "summary": {"port": 7892, "consoleEntryCount": 0, "sceneDirty": False},
            "editorState": {"isPlaying": False, "isCompiling": False},
            "console": {"entries": []},
            "consoleSummary": {"highestSeverity": "info"},
            "compilation": {
                "count": 2,
                "entries": [
                    {
                        "message": (
                            "Assets/Scripts/Player.cs(12,8): error CS0246: "
                            "The type or namespace name 'Foo' could not be found"
                        )
                    },
                    {
                        "message": (
                            "Assets/Scripts/Enemy.cs(18,20): error CS0103: "
                            "The name 'target' does not exist in the current context"
                        )
                    },
                ],
            },
            "missingReferences": {"totalFound": 0, "results": []},
            "queue": {"totalQueued": 0, "activeAgents": 0},
        }

        report = build_debug_doctor_report(snapshot, [], 7892)

        titles = [finding["title"] for finding in report["findings"]]
        self.assertIn("Compilation Issues", titles)
        self.assertIn("CS0246: Missing Type or Namespace", titles)
        self.assertIn("CS0103: Undefined Name in Scope", titles)
        self.assertEqual(report["compilationSummary"]["totalErrors"], 2)
        self.assertEqual(report["compilationSummary"]["uniqueErrorCodes"], ["CS0246", "CS0103"])
        self.assertIn("Assets/Scripts/Player.cs", report["compilationSummary"]["affectedFiles"])
        self.assertTrue(
            any(
                finding.get("evidence", {}).get("location") == "Assets/Scripts/Player.cs line 12"
                for finding in report["findings"]
            )
        )
        self.assertIn(
            "cli-anything-unity-mcp --json debug snapshot --console-count 50 --port 7892",
            report["recommendedCommands"],
        )

    def test_debug_doctor_enriches_runtime_console_patterns(self) -> None:
        snapshot = {
            "summary": {"port": 7892, "consoleEntryCount": 1, "sceneDirty": False},
            "editorState": {"isPlaying": False, "isCompiling": False},
            "console": {
                "entries": [
                    {
                        "type": "error",
                        "message": "NullReferenceException: Object reference not set to an instance of an object",
                    }
                ]
            },
            "consoleSummary": {"highestSeverity": "error"},
            "compilation": {"count": 0, "entries": []},
            "missingReferences": {"totalFound": 0, "results": []},
            "queue": {"totalQueued": 0, "activeAgents": 0},
        }

        report = build_debug_doctor_report(snapshot, [], 7892)

        null_ref = next(
            finding for finding in report["findings"] if finding["title"] == "NullReferenceException at Runtime"
        )
        self.assertTrue(null_ref["heuristic"])
        self.assertIn("serialized field", null_ref["detail"].lower())
        self.assertIn(
            "cli-anything-unity-mcp --json console --count 50 --type error --port 7892",
            report["recommendedCommands"],
        )

    def test_debug_doctor_surfaces_recurring_compilation_queue_and_bridge_signals(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            memory = ProjectMemory("C:/Projects/Demo", store_root=tmpdir, allow_fallback=False)
            compilation_entry = {
                "message": (
                    "Assets/Scripts/Player.cs(12,8): error CS0246: "
                    "The type or namespace name 'Foo' could not be found"
                )
            }
            memory.record_compilation_errors([compilation_entry], "MainScene")
            memory.record_compilation_errors([compilation_entry], "MainScene")
            memory.record_operational_signals(
                [
                    {
                        "kind": "queue",
                        "key": "queue-contention",
                        "title": "Queue contention",
                        "detail": "Queue still had active work pending.",
                    },
                    {
                        "kind": "bridge",
                        "key": "bridge-port-hop",
                        "title": "Bridge port hop",
                        "detail": "Recent CLI calls hopped between Unity ports.",
                    },
                ],
                "MainScene",
            )
            memory.record_operational_signals(
                [
                    {
                        "kind": "queue",
                        "key": "queue-contention",
                        "title": "Queue contention",
                        "detail": "Queue still had active work pending.",
                    },
                    {
                        "kind": "bridge",
                        "key": "bridge-port-hop",
                        "title": "Bridge port hop",
                        "detail": "Recent CLI calls hopped between Unity ports.",
                    },
                ],
                "MainScene",
            )
            memory.record_queue_snapshot({"totalQueued": 2, "activeAgents": 1}, "MainScene")
            memory.record_queue_snapshot({"totalQueued": 2, "activeAgents": 1}, "MainScene")
            memory.record_queue_snapshot({"totalQueued": 2, "activeAgents": 1}, "MainScene")

            snapshot = {
                "summary": {"port": 7892, "consoleEntryCount": 0, "sceneDirty": False},
                "editorState": {"isPlaying": False, "isCompiling": False},
                "console": {"entries": []},
                "consoleSummary": {"highestSeverity": "info"},
                "compilation": {"count": 1, "entries": [compilation_entry]},
                "missingReferences": {"totalFound": 0, "results": []},
                "queue": {"totalQueued": 2, "activeAgents": 1},
            }

            report = build_debug_doctor_report(
                snapshot,
                [
                    {"command": "scene/info", "port": 7891},
                    {"command": "scene/info", "port": 7892},
                ],
                7892,
                memory=memory,
            )

            titles = [finding["title"] for finding in report["findings"]]
            self.assertIn("Recurring Compilation Errors", titles)
            self.assertIn("Recurring Queue Contention", titles)
            self.assertIn("Recurring Bridge Port Hops", titles)
            self.assertIn("Queue backlog trend looks persistent", titles)
            self.assertEqual(report["queueDiagnostics"]["status"], "backlog-and-active")
            self.assertEqual(report["queueDiagnostics"]["recurringSignalCount"], 1)
            self.assertIn("queued work pending", report["queueDiagnostics"]["summary"])
            self.assertEqual(report["queueTrend"]["status"], "stalled-backlog-suspected")
            self.assertEqual(report["queueTrend"]["sampleCount"], 3)
            self.assertIn(
                "cli-anything-unity-mcp --json debug bridge --port 7892",
                report["recommendedCommands"],
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_bridge_diagnostics_reports_selected_port_mismatch(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            registry_path = tmpdir / "instances.json"
            session_path = tmpdir / "session.json"
            registry_path.write_text(
                json.dumps(
                    [
                        {
                            "port": 7890,
                            "projectName": "Demo",
                            "projectPath": "C:/Projects/Demo",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            session_store = SessionStore(session_path)
            session_store.save(
                SessionState(
                    selected_port=7891,
                    selected_instance={"port": 7891, "projectName": "Demo", "projectPath": "C:/Projects/Demo"},
                    history=[],
                )
            )
            backend = UnityMCPBackend(
                client=FakeClient(
                    {
                        7890: {
                            "status": "ok",
                            "projectName": "Demo",
                            "projectPath": "C:/Projects/Demo",
                            "unityVersion": "6000.0.0f1",
                            "platform": "WindowsEditor",
                        }
                    }
                ),
                session_store=session_store,
                registry_path=registry_path,
                default_port=7890,
                port_range_start=7890,
                port_range_end=7891,
            )

            payload = backend.get_bridge_diagnostics()

            self.assertEqual(payload["title"], "Unity Bridge Diagnostics")
            self.assertEqual(payload["summary"]["assessment"], "warning")
            self.assertEqual(payload["summary"]["connectionMode"], "registry-backed")
            self.assertTrue(payload["summary"]["canReachUnity"])
            self.assertEqual(payload["summary"]["selectedPort"], 7891)
            self.assertEqual(payload["summary"]["respondingPortCount"], 1)
            self.assertTrue(any(check["port"] == 7890 and check["status"] == "ok" for check in payload["portChecks"]))
            self.assertTrue(any(check["port"] == 7891 and check["status"] != "ok" for check in payload["portChecks"]))
            self.assertTrue(any(item["title"] == "Selected Port Is Not Responding" for item in payload["findings"]))
            self.assertTrue(any(command.startswith("cli-anything-unity-mcp instances") for command in payload["recommendedCommands"]))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_bridge_diagnostics_reports_registry_access_denied_fallback(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            session_path = tmpdir / "session.json"
            session_store = SessionStore(session_path)
            session_store.update_selection(
                {
                    "port": 7892,
                    "projectName": "Demo",
                    "projectPath": "C:/Projects/Demo",
                }
            )
            backend = UnityMCPBackend(
                client=FakeClient(
                    {
                        7892: {
                            "status": "ok",
                            "projectName": "Demo",
                            "projectPath": "C:/Projects/Demo",
                            "unityVersion": "6000.0.0f1",
                            "platform": "WindowsEditor",
                        }
                    }
                ),
                session_store=session_store,
                registry_path=tmpdir / "instances.json",
                default_port=7890,
                port_range_start=7892,
                port_range_end=7892,
            )
            backend.discover_instances = lambda: [  # type: ignore[method-assign]
                {
                    "port": 7892,
                    "projectName": "Demo",
                    "projectPath": "C:/Projects/Demo",
                    "unityVersion": "6000.0.0f1",
                    "platform": "WindowsEditor",
                    "source": "portscan",
                }
            ]
            backend._read_registry_snapshot = lambda: {  # type: ignore[method-assign]
                "path": str(tmpdir / "instances.json"),
                "status": "access-denied",
                "error": "Access is denied",
                "entries": [],
            }

            payload = backend.get_bridge_diagnostics(port=7892)

            self.assertEqual(payload["summary"]["assessment"], "warning")
            self.assertEqual(payload["summary"]["connectionMode"], "portscan-fallback")
            self.assertEqual(payload["summary"]["registryStatus"], "access-denied")
            self.assertEqual(payload["summary"]["registryError"], "Access is denied")
            self.assertTrue(any(item["title"] == "Registry File Access Denied" for item in payload["findings"]))
            self.assertTrue(any("debug doctor" in command for command in payload["recommendedCommands"]))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_failed_route_hint_includes_tool_transport_port_and_retry(self) -> None:
        hint = _format_failed_route_hint(
            {
                "command": "editor/state",
                "transport": "queue",
                "port": 7890,
            }
        )
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertIn("editor/state", hint)
        self.assertIn("unity_editor_state", hint)
        self.assertIn("queue", hint)
        self.assertIn("7890", hint)
        self.assertIn("debug doctor --port 7890", hint)
        self.assertIn("agent queue --port 7890", hint)
        self.assertIn("agent sessions --port 7890", hint)

    def test_failed_route_hint_handles_file_ipc_without_port(self) -> None:
        hint = _format_failed_route_hint(
            {
                "command": "scene/info",
                "transport": "file-ipc",
                "port": None,
            }
        )
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertIn("scene/info", hint)
        self.assertIn("unity_scene_info", hint)
        self.assertIn("file-ipc", hint)
        self.assertIn("debug bridge", hint)
        self.assertNotIn("--port", hint)

    def test_cli_exception_message_ignores_stale_unrelated_history_error(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            store = SessionStore(tmpdir / "session.json")
            store.record_command(
                "editor/state",
                port=7890,
                status="error",
                error="bridge unavailable",
                transport="queue",
            )
            ctx = SimpleNamespace(
                obj=SimpleNamespace(
                    backend=SimpleNamespace(session_store=store),
                )
            )
            message = _format_cli_exception_message(ctx, RuntimeError("totally different failure"))
            self.assertEqual(message, "totally different failure")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_cli_exception_message_appends_route_hint_for_recovery_timeout(self) -> None:
        tmpdir = Path.cwd() / ".tmp-tests" / uuid.uuid4().hex
        tmpdir.mkdir(parents=True, exist_ok=True)
        try:
            store = SessionStore(tmpdir / "session.json")
            store.record_command(
                "editor/state",
                port=7890,
                status="error",
                error="old port is unavailable",
                transport="queue",
            )
            ctx = SimpleNamespace(
                obj=SimpleNamespace(
                    backend=SimpleNamespace(session_store=store),
                )
            )
            message = _format_cli_exception_message(
                ctx,
                BackendSelectionError(
                    "Timed out recovering route editor/state for project C:/Projects/Demo "
                    "after 0.02s. Last error: old port is unavailable"
                ),
            )
            self.assertIn("Timed out recovering route editor/state", message)
            self.assertIn("Try: cli-anything-unity-mcp --json debug doctor --port 7890", message)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
