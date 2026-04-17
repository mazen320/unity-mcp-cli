"""test_chat_e2e.py — End-to-end tests for agent_chat.py new capabilities.

Tests for Track 2A tasks:
  - Task 1: Visual capture helper
  - Task 2: Player prototype flow
  - Task 3: Script create+attach flow
  - Task 4: Watchdog background thread
  - Task 5: Autonomous goal mode
"""

from __future__ import annotations

import os
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def _workspace_temp_dir() -> str:
    root = Path.cwd() / ".tmp-tests"
    root.mkdir(parents=True, exist_ok=True)
    tmpdir = root / uuid.uuid4().hex
    tmpdir.mkdir(parents=True, exist_ok=True)
    try:
        yield str(tmpdir)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


class ChatE2ETests(unittest.TestCase):

    # ── Task 1: Visual capture helper ─────────────────────────────────────────

    def test_capture_after_action_returns_paths_when_live(self):
        """_capture_after_action returns a non-empty dict when file client responds."""
        from unittest.mock import MagicMock
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant
        from cli_anything.unity_mcp.core.file_ipc import FileIPCClient

        with _workspace_temp_dir() as tmp:
            client = MagicMock(spec=FileIPCClient)
            client.call_route.return_value = {
                "gamePath": "/tmp/game.png",
                "scenePath": "/tmp/scene.png",
            }
            bridge = MagicMock()
            bridge.client = client
            bridge.project_path = tmp
            assistant = _OfflineUnityAssistant(bridge)
            result = assistant._capture_after_action()
            assert result.get("gamePath") == "/tmp/game.png"
            assert result.get("scenePath") == "/tmp/scene.png"

    def test_capture_after_action_returns_empty_on_error(self):
        """_capture_after_action returns empty dict when capture fails."""
        from unittest.mock import MagicMock
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant
        from cli_anything.unity_mcp.core.file_ipc import FileIPCClient

        client = MagicMock(spec=FileIPCClient)
        client.call_route.side_effect = RuntimeError("no unity")
        bridge = MagicMock()
        bridge.client = client
        assistant = _OfflineUnityAssistant(bridge)
        result = assistant._capture_after_action()
        assert result == {}

    # ── Task 2: Player prototype flow ─────────────────────────────────────────

    def test_player_prototype_reply_creates_go_and_returns_steps(self):
        """_build_player_prototype_reply calls create GO, add CharacterController, create script."""
        from unittest.mock import MagicMock
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        with _workspace_temp_dir() as tmp:
            client = MagicMock()
            client.call_route.return_value = {"name": "Player", "id": "abc123"}
            bridge = MagicMock()
            bridge.client = client
            bridge.project_path = tmp
            assistant = _OfflineUnityAssistant(bridge)

            # Mock _run_embedded_cli to avoid needing full CLI
            assistant._run_embedded_cli = MagicMock(return_value={"success": True, "path": "/Assets/Scripts/PlayerMovement.cs"})
            assistant._capture_after_action = MagicMock(return_value={"gamePath": "/tmp/game.png"})

            result = assistant._build_player_prototype_reply()

            # Should have called gameobject/create
            create_calls = [c for c in client.call_route.call_args_list if c[0][0] == "gameobject/create"]
            assert len(create_calls) >= 1
            # Should have called component/add for CharacterController
            cc_calls = [c for c in client.call_route.call_args_list
                        if c[0][0] == "component/add" and "CharacterController" in str(c)]
            assert len(cc_calls) >= 1
            # Should have tried to capture
            assistant._capture_after_action.assert_called_once()
            # Reply should mention Player
            assert "Player" in result or "player" in result.lower()

    # ── Task 3: Script create+attach flow ─────────────────────────────────────

    def test_build_script_attach_reply_creates_and_attaches(self):
        """_build_script_attach_reply creates a script and attaches it to a named GO."""
        from unittest.mock import MagicMock
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        client = MagicMock()
        client.call_route.return_value = {"success": True}
        bridge = MagicMock()
        bridge.client = client
        assistant = _OfflineUnityAssistant(bridge)
        assistant._run_embedded_cli = MagicMock(return_value={"path": "Assets/Scripts/Rotate.cs"})
        assistant._capture_after_action = MagicMock(return_value={})

        result = assistant._build_script_attach_reply("Rotate", "Cube", "rotates the object on Y axis")

        assert "Rotate" in result
        assert "Cube" in result
        assistant._run_embedded_cli.assert_called_once()
        cc_calls = [c for c in client.call_route.call_args_list if "component/add" in str(c)]
        assert len(cc_calls) >= 1

    # ── Task 4: Watchdog background thread ────────────────────────────────────

    def test_watchdog_thread_starts_and_stops(self):
        """ChatBridge watchdog thread starts and stops correctly."""
        import time
        from unittest.mock import MagicMock
        from cli_anything.unity_mcp.core.agent_chat import ChatBridge
        from cli_anything.unity_mcp.core.file_ipc import FileIPCClient

        with _workspace_temp_dir() as tmp:
            client = MagicMock(spec=FileIPCClient)
            bridge = ChatBridge(tmp, client, poll_interval=0.05, watchdog_interval=0.1)
            bridge._ensure_ready()

            bridge._start_watchdog()
            time.sleep(0.05)
            assert bridge._watchdog_thread is not None
            assert bridge._watchdog_thread.is_alive()

            bridge._stop_watchdog()
            bridge._watchdog_thread.join(timeout=1.0)
            assert not bridge._watchdog_thread.is_alive()

    def test_watchdog_does_not_post_duplicate_findings(self):
        """Watchdog suppresses findings already surfaced in this session."""
        from unittest.mock import MagicMock
        from cli_anything.unity_mcp.core.agent_chat import ChatBridge
        from cli_anything.unity_mcp.core.file_ipc import FileIPCClient

        with _workspace_temp_dir() as tmp:
            client = MagicMock(spec=FileIPCClient)
            bridge = ChatBridge(tmp, client)
            bridge._ensure_ready()

            # Simulate that "No AudioListener in scene" was already surfaced
            bridge._watchdog_surfaced.add("No AudioListener in scene")

            findings = [{"title": "No AudioListener in scene", "severity": "warning"}]
            new_findings = bridge._watchdog_filter_new(findings)
            assert new_findings == []

    # ── Task 5: Autonomous goal mode ──────────────────────────────────────────

    def test_autonomous_goal_reply_returns_plan_for_review(self):
        """_autonomous_goal_reply posts a plan and waits for user confirmation."""
        from unittest.mock import MagicMock
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        client = MagicMock()
        bridge = MagicMock()
        bridge.client = client
        assistant = _OfflineUnityAssistant(bridge)

        # Mock quality score to return some findings
        assistant._run_embedded_cli = MagicMock(return_value={
            "lensScores": [{"name": "systems", "score": 40, "findings": [
                {"title": "No EventSystem in scene", "severity": "error"},
                {"title": "No AudioListener in scene", "severity": "warning"},
            ]}]
        })

        result = assistant._autonomous_goal_reply("fix all the issues in my project")
        assert "plan" in result.lower() or "step" in result.lower() or "fix" in result.lower()
        assert "confirm" in result.lower() or "proceed" in result.lower() or "ready" in result.lower() or "yes" in result.lower() or "go" in result.lower()

    def test_autonomous_goal_detects_polish_intent(self):
        """_dispatch routes 'polish X' to autonomous goal handler."""
        from unittest.mock import MagicMock
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        bridge = MagicMock()
        assistant = _OfflineUnityAssistant(bridge)
        assistant._autonomous_goal_reply = MagicMock(return_value="here is my plan")

        result = assistant._dispatch("polish the combat feel")
        assistant._autonomous_goal_reply.assert_called_once_with("polish the combat feel")

    # ── LLM-first chat behavior ──────────────────────────────────────────────

    def test_best_effort_reply_requires_model_for_freeform_requests(self):
        """Freeform chat should state that a model provider is required when none is configured."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        bridge = MagicMock()
        assistant = _OfflineUnityAssistant(bridge)

        with patch.dict(os.environ, {}, clear=True):
            reply = assistant._best_effort_agent_reply("build a full inventory system for this scene")

        assert "model provider" in reply.lower()
        assert "openai_api_key" in reply.lower() or "anthropic_api_key" in reply.lower()

    def test_try_model_backed_plan_passes_full_context_and_recent_history(self):
        """Model-backed planning should receive fresh full context and recent chat history."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        with _workspace_temp_dir() as tmp:
            project = Path(tmp)
            (project / "AGENTS.md").write_text("Keep URP and avoid demo residue.\n", encoding="utf-8")

            bridge = MagicMock()
            bridge.project_path = project
            bridge.client = MagicMock()
            bridge._status_path = project / ".umcp" / "agent-status.json"
            bridge._history = [
                {"role": "user", "content": "inspect project"},
                {"role": "ai", "content": "Here is the project summary."},
                {"role": "user", "content": "now add a proper player controller"},
            ]
            bridge._context = MagicMock()
            bridge._context.as_system_prompt.return_value = "## Unity Project Context\nScene: McpLiveFpsPass"

            assistant = _OfflineUnityAssistant(bridge)

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
                with patch(
                    "cli_anything.unity_mcp.commands.agent_loop_cmd._generate_plan_from_intent",
                    return_value=[{"step": 1, "description": "Create player", "route": "gameobject/create", "params": {}}],
                ) as generate_plan:
                    with patch("cli_anything.unity_mcp.core.agent_chat.AgentLoop") as loop_cls:
                        loop_cls.return_value.execute.return_value = []

                        assistant._try_model_backed_plan("create a player controller for the active scene")

            bridge._context.as_system_prompt.assert_called_once_with(full=True)
            kwargs = generate_plan.call_args.kwargs
            assert kwargs["history"] == [
                {"role": "user", "content": "inspect project"},
                {"role": "assistant", "content": "Here is the project summary."},
                {"role": "user", "content": "now add a proper player controller"},
            ]
            assert "Unity Project Context" in kwargs["context_prompt"]
            assert "Keep URP and avoid demo residue." in kwargs["context_prompt"]

    def test_try_model_backed_plan_uses_project_selected_model(self):
        """Model-backed planning should respect the project agent-config model selection."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        with _workspace_temp_dir() as tmp:
            project = Path(tmp)
            umcp = project / ".umcp"
            umcp.mkdir(parents=True, exist_ok=True)
            (umcp / "agent-config.json").write_text(
                '{"preferredProvider":"openai","preferredModel":"gpt-5-codex"}',
                encoding="utf-8",
            )

            bridge = MagicMock()
            bridge.project_path = project
            bridge.client = MagicMock()
            bridge._status_path = project / ".umcp" / "agent-status.json"
            bridge._history = []
            bridge._context = MagicMock()
            bridge._context.as_system_prompt.return_value = "## Unity Project Context\nScene: Demo"

            assistant = _OfflineUnityAssistant(bridge)

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
                with patch(
                    "cli_anything.unity_mcp.commands.agent_loop_cmd._generate_plan_from_intent",
                    return_value=[{"step": 1, "description": "Create player", "route": "gameobject/create", "params": {}}],
                ) as generate_plan:
                    with patch("cli_anything.unity_mcp.core.agent_chat.AgentLoop") as loop_cls:
                        loop_cls.return_value.execute.return_value = []

                        assistant._try_model_backed_plan("create a player controller for the active scene")

            kwargs = generate_plan.call_args.kwargs
            assert kwargs["model"] == "gpt-5-codex"

    def test_capture_after_action_invalidates_cached_context(self):
        """Scene captures should invalidate cached context before reading proof artifacts."""
        from unittest.mock import MagicMock
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        bridge = MagicMock()
        bridge.client.call_route.return_value = {
            "gamePath": "/tmp/game.png",
            "scenePath": "/tmp/scene.png",
        }
        bridge._context = MagicMock()

        assistant = _OfflineUnityAssistant(bridge)
        result = assistant._capture_after_action()

        assert result.get("gamePath") == "/tmp/game.png"
        bridge._context.invalidate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
