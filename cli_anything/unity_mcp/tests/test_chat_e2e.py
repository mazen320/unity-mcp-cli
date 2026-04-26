"""test_chat_e2e.py — End-to-end tests for agent_chat.py new capabilities.

Tests for Track 2A tasks:
  - Task 1: Visual capture helper
  - Task 2: Player prototype flow
  - Task 3: Script create+attach flow
  - Task 4: Watchdog background thread
  - Task 5: Autonomous goal mode
"""

from __future__ import annotations

import base64
import os
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace


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

    def test_capture_after_action_is_a_noop(self):
        """_capture_after_action is intentionally disabled to avoid automatic capture churn."""
        from unittest.mock import MagicMock
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant
        from cli_anything.unity_mcp.core.file_ipc import FileIPCClient

        with _workspace_temp_dir() as tmp:
            client = MagicMock(spec=FileIPCClient)
            bridge = MagicMock()
            bridge.client = client
            bridge.project_path = tmp
            assistant = _OfflineUnityAssistant(bridge)
            result = assistant._capture_after_action()
            assert result == {}

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

            result = assistant._build_player_prototype_reply()

            # Should have called gameobject/create
            create_calls = [c for c in client.call_route.call_args_list if c[0][0] == "gameobject/create"]
            assert len(create_calls) >= 1
            # Should have called component/add for CharacterController
            cc_calls = [c for c in client.call_route.call_args_list
                        if c[0][0] == "component/add" and "CharacterController" in str(c)]
            assert len(cc_calls) >= 1
            # Reply should mention Player
            assert "Player" in result or "player" in result.lower()
            assert "WASD + Space" in result

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
        result = assistant._build_script_attach_reply("Rotate", "Cube", "rotates the object on Y axis")

        assert "Rotate" in result
        assert "Cube" in result
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

    def test_watchdog_is_disabled_by_default_after_reset(self):
        """Default bridge sessions should not start the watchdog automatically."""
        from unittest.mock import MagicMock
        from cli_anything.unity_mcp.core.agent_chat import ChatBridge
        from cli_anything.unity_mcp.core.file_ipc import FileIPCClient

        with _workspace_temp_dir() as tmp:
            client = MagicMock(spec=FileIPCClient)
            bridge = ChatBridge(tmp, client)
            bridge._ensure_ready()

            assert bridge._watchdog_interval == 0.0
            assert bridge._watchdog_thread is None

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
        assistant._run_internal_workflow = MagicMock(return_value={
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

    # ── Physics-feel specialist flow ────────────────────────────────────────

    def test_dispatch_floaty_player_returns_three_tuning_paths(self):
        """Physics-feel intent should return diagnosis + three proposals and stash follow-up state."""
        from unittest.mock import MagicMock
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        with _workspace_temp_dir() as tmp:
            bridge = MagicMock()
            bridge.project_path = Path(tmp)
            bridge._context = MagicMock()
            bridge._context.get.return_value = {
                "physics": {"gravity": {"y": -9.81}},
                "hierarchy": {
                    "nodes": [
                        {
                            "name": "Player",
                            "path": "Player",
                            "components": ["Rigidbody", "CapsuleCollider"],
                            "tuning": {"drag": 0.0, "jumpPower": 10.0},
                        }
                    ]
                },
            }
            assistant = _OfflineUnityAssistant(bridge)

            result = assistant._dispatch("my player feels floaty")

            assert "Physics feel check" in result
            assert "Three tuning paths" in result
            assert "apply 1" in result
            pending = getattr(bridge, "_pending_physics_feel_proposals", None)
            assert isinstance(pending, dict)
            assert "physics_feel/snappy" in pending

    def test_dispatch_apply_physics_feel_uses_pending_proposal_and_returns_outcome(self):
        """Physics-feel follow-up apply should execute the stored proposal and report before/after."""
        from unittest.mock import MagicMock
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        with _workspace_temp_dir() as tmp:
            bridge = MagicMock()
            bridge.project_path = Path(tmp)
            bridge._context = MagicMock()
            bridge._context.get.return_value = {
                "physics": {"gravity": {"y": -9.81}},
                "hierarchy": {
                    "nodes": [
                        {
                            "name": "Player",
                            "path": "Player",
                            "components": ["Rigidbody", "CapsuleCollider"],
                            "tuning": {"drag": 0.0, "jumpPower": 10.0},
                        }
                    ]
                },
            }

            def call_route(route: str, params: dict[str, object]) -> dict[str, object]:
                if route == "physics/set-gravity":
                    return {"success": True, "gravity": {"y": params.get("y", -9.81)}}
                if route == "physics/set-rigidbody":
                    return {"success": True}
                if route == "graphics/game-capture":
                    encoded = base64.b64encode(b"png").decode("ascii")
                    return {"success": True, "base64": encoded, "width": 960, "height": 540}
                raise AssertionError(f"unexpected route {route}")

            bridge.client.call_route.side_effect = call_route
            assistant = _OfflineUnityAssistant(bridge)

            proposal_reply = assistant._dispatch("my player feels floaty")
            assert "Three tuning paths" in proposal_reply

            result = assistant._dispatch("apply 1")

            assert "Applied:" in result
            assert "Before:" in result
            assert "After:" in result
            assert "Capture:" in result
            assert "Physics-feel score:" in result

    def test_dispatch_apply_physics_feel_without_pending_proposal_fails_cleanly(self):
        """Physics-feel apply follow-up should explain when there is nothing pending."""
        from unittest.mock import MagicMock
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        bridge = MagicMock()
        assistant = _OfflineUnityAssistant(bridge)

        result = assistant._dispatch("apply 1")

        assert "pending" in result.lower()
        assert "physics" in result.lower()

    # ── LLM-first chat behavior ──────────────────────────────────────────────

    def test_best_effort_reply_requires_model_for_freeform_requests(self):
        """Freeform chat should state that a model provider is required when none is configured."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        bridge = MagicMock()
        assistant = _OfflineUnityAssistant(bridge)

        with patch.dict(os.environ, {}, clear=True):
            reply = assistant._best_effort_agent_reply("build a full inventory system for this scene")

        assert "api key" in reply.lower()
        assert "openai_api_key" in reply.lower() or "anthropic_api_key" in reply.lower()

    def test_try_model_backed_plan_passes_full_context_and_recent_history(self):
        """Model-backed planning should receive fresh full context and return a proposal first."""
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
                        reply = assistant._try_model_backed_plan("create a player controller for the active scene")

            bridge._context.as_system_prompt.assert_called_once_with(full=True)
            kwargs = generate_plan.call_args.kwargs
            assert kwargs["history"] == [
                {"role": "user", "content": "inspect project"},
                {"role": "assistant", "content": "Here is the project summary."},
                {"role": "user", "content": "now add a proper player controller"},
            ]
            assert "Unity Project Context" in kwargs["context_prompt"]
            assert "Keep URP and avoid demo residue." in kwargs["context_prompt"]
            assert isinstance(reply, dict)
            assert reply["metadata"]["approvalRequired"] is True
            assert len(reply["steps"]) == 1
            assert getattr(bridge, "_pending_model_plan", None)
            loop_cls.return_value.execute.assert_not_called()

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
                    assistant._try_model_backed_plan("create a player controller for the active scene")

            kwargs = generate_plan.call_args.kwargs
            assert kwargs["model"] == "gpt-5-codex"

    def test_dispatch_yes_executes_pending_model_plan(self):
        """Explicit approval should execute the stored model plan and return structured results."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        bridge = MagicMock()
        bridge.client = MagicMock()
        bridge._status_path = Path("agent-status.json")
        bridge._pending_model_plan = [
            {"step": 1, "description": "Create player", "route": "gameobject/create", "params": {}},
            {"step": 2, "description": "Attach controller", "route": "component/add", "params": {}},
        ]
        assistant = _OfflineUnityAssistant(bridge)

        fake_results = [
            SimpleNamespace(step=1, description="Create player", status="ok"),
            SimpleNamespace(step=2, description="Attach controller", status="error"),
        ]
        with patch("cli_anything.unity_mcp.core.agent_chat.AgentLoop") as loop_cls:
            loop_cls.return_value.execute.return_value = fake_results
            with patch("cli_anything.unity_mcp.core.agent_chat.format_results", return_value="formatted results"):
                result = assistant._dispatch("yes")

        assert isinstance(result, dict)
        assert result["metadata"]["executed"] is True
        assert result["steps"][0]["status"] == "ok"
        assert result["steps"][1]["status"] == "error"
        assert getattr(bridge, "_pending_model_plan", None) is None

    def test_agent_loop_waits_for_compilation_after_script_create_before_attach(self):
        """Generated script plans should not race component/add before Unity compilation settles."""
        from cli_anything.unity_mcp.core.agent_loop import AgentLoop

        class CompileAwareClient:
            def __init__(self):
                self.calls = []
                self.state_polls = 0

            def call_route(self, route, params):
                self.calls.append(route)
                if route == "script/create":
                    return {"success": True}
                if route == "editor/state":
                    self.state_polls += 1
                    return {
                        "isCompiling": self.state_polls == 1,
                        "readyForTools": self.state_polls > 1,
                    }
                if route == "component/add":
                    return {"success": True}
                return {"success": True}

        client = CompileAwareClient()
        loop = AgentLoop(client, max_retries=0, retry_delay=0.0)
        results = loop.execute(
            [
                {
                    "step": 1,
                    "description": "Create script",
                    "route": "script/create",
                    "params": {"path": "Assets/Scripts/Generated.cs", "content": "public class Generated {}"},
                },
                {
                    "step": 2,
                    "description": "Attach script",
                    "route": "component/add",
                    "params": {"gameObjectPath": "Generated", "componentType": "Generated"},
                },
            ]
        )

        assert [result.status for result in results] == ["ok", "ok"]
        assert client.calls.index("editor/state") < client.calls.index("component/add")
        assert client.state_polls >= 2

    def test_pending_model_plan_target_question_describes_plan_without_replanning(self):
        """Plan review questions should explain the pending plan, not create a new plan."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        bridge = MagicMock()
        bridge._pending_model_plan = [
            {
                "step": 1,
                "description": "Assign a new material to the hero mesh",
                "route": "material/assign",
                "params": {"gameObject": "CodexFpsShowcase_Player", "material": "Assets/Materials/Hero.mat"},
            },
        ]
        assistant = _OfflineUnityAssistant(bridge)

        with patch.object(assistant, "_try_model_backed_plan") as plan_reply:
            result = assistant._dispatch("Show me which object you're targeting and why before changing anything.")

        plan_reply.assert_not_called()
        assert isinstance(result, dict)
        assert result["metadata"]["kind"] == "model-plan-review"
        assert result["metadata"]["approvalRequired"] is True
        assert getattr(bridge, "_pending_model_plan", None)
        assert "not changed anything" in result["content"].lower()
        assert "CodexFpsShowcase_Player" in result["content"]

    def test_pending_model_plan_review_reports_missing_concrete_target(self):
        """If the pending plan has no target params, review should block blind approval."""
        from unittest.mock import MagicMock
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        bridge = MagicMock()
        bridge._pending_model_plan = [
            {
                "step": 1,
                "description": "Identify the game object that will receive the new material.",
                "route": "gameobject/info",
                "params": {},
            },
        ]
        assistant = _OfflineUnityAssistant(bridge)

        result = assistant._dispatch("which object are you targeting?")

        assert isinstance(result, dict)
        assert "no concrete target" in result["content"].lower()
        assert "revise" in result["content"].lower()
        assert getattr(bridge, "_pending_model_plan", None)

    def test_pending_model_plan_revision_replaces_plan_for_new_scene(self):
        """Revision follow-ups like 'do it in a new scene' should replan, not chat or apply stale steps."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        with _workspace_temp_dir() as tmp:
            project = Path(tmp)
            bridge = MagicMock()
            bridge.project_path = project
            bridge.client = MagicMock()
            bridge._status_path = project / ".umcp" / "agent-status.json"
            bridge._history = []
            bridge._context = MagicMock()
            bridge._context.as_system_prompt.return_value = "## Unity Project Context\nScene: ExistingScene"
            bridge._pending_model_plan = [
                {
                    "step": 1,
                    "description": "Create manager in current scene",
                    "route": "gameobject/create",
                    "params": {"name": "GeneratedPrototype", "primitiveType": "Empty"},
                }
            ]
            assistant = _OfflineUnityAssistant(bridge)

            replacement_plan = [
                {
                    "step": 1,
                    "description": "Create a new scene for the generated prototype",
                    "route": "scene/new",
                    "params": {"name": "GeneratedPrototypeScene"},
                    "onError": "abort",
                },
                {
                    "step": 2,
                    "description": "Create manager in the new scene",
                    "route": "gameobject/create",
                    "params": {"name": "GeneratedPrototype", "primitiveType": "Empty"},
                },
                {
                    "step": 3,
                    "description": "Save the generated scene",
                    "route": "scene/save",
                    "params": {},
                },
            ]

            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=True):
                with patch(
                    "cli_anything.unity_mcp.commands.agent_loop_cmd._generate_plan_from_intent",
                    return_value=replacement_plan,
                ) as generate_plan:
                    result = assistant._dispatch("do it in a new scene")

        assert isinstance(result, dict)
        assert "revised the pending plan" in result["content"].lower()
        assert bridge._pending_model_plan == replacement_plan
        generated_intent = generate_plan.call_args.args[0]
        assert "Revise the pending Unity execution plan" in generated_intent
        assert "do it in a new scene" in generated_intent
        assert "Create manager in current scene" in generated_intent

    def test_dispatch_capabilities_uses_builtin_help(self):
        """Capability questions should use the product answer instead of model improvisation."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        bridge = MagicMock()
        assistant = _OfflineUnityAssistant(bridge)

        with patch.object(assistant, "_try_model_backed_chat") as chat_reply:
            with patch.object(assistant, "_try_model_backed_plan") as plan_reply:
                reply = assistant._dispatch("what are your capabilities?")

        chat_reply.assert_not_called()
        plan_reply.assert_not_called()
        assert "propose a plan first" in reply.lower()
        assert "approval" in reply.lower()

    def test_best_effort_reply_routes_meta_questions_to_chat_before_planning(self):
        """Review/explanation questions should be answered conversationally first."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        bridge = MagicMock()
        assistant = _OfflineUnityAssistant(bridge)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
            with patch.object(assistant, "_try_model_backed_chat", return_value="I can inspect scenes and propose safe changes.") as chat_reply:
                with patch.object(assistant, "_try_model_backed_plan", return_value={"content": "bad plan"}) as plan_reply:
                    reply = assistant._best_effort_agent_reply("show me what you would change first")

        chat_reply.assert_called_once_with("show me what you would change first")
        plan_reply.assert_not_called()
        assert "inspect scenes" in reply

    def test_best_effort_reply_routes_question_shaped_build_requests_to_chat(self):
        """Question-shaped build discussion should chat instead of immediately proposing a plan."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        bridge = MagicMock()
        assistant = _OfflineUnityAssistant(bridge)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
            with patch.object(assistant, "_try_model_backed_chat", return_value="Yes. I can help design and build that safely.") as chat_reply:
                with patch.object(assistant, "_try_model_backed_plan", return_value={"content": "bad plan"}) as plan_reply:
                    reply = assistant._best_effort_agent_reply("can you build me something like tetris?")

        chat_reply.assert_called_once_with("can you build me something like tetris?")
        plan_reply.assert_not_called()
        assert "design and build" in reply

    def test_best_effort_reply_routes_imperative_build_requests_to_plan(self):
        """Imperative build commands should still propose an executable plan first."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        bridge = MagicMock()
        assistant = _OfflineUnityAssistant(bridge)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
            with patch.object(assistant, "_try_model_backed_plan", return_value={"content": "I found a concrete plan."}) as plan_reply:
                with patch.object(assistant, "_try_model_backed_chat", return_value="chat") as chat_reply:
                    reply = assistant._best_effort_agent_reply("build me a small arcade prototype")

        plan_reply.assert_called_once_with("build me a small arcade prototype")
        chat_reply.assert_not_called()
        assert reply["content"] == "I found a concrete plan."

    def test_try_model_backed_plan_rejects_invalid_routes(self):
        """Model plans with hallucinated routes should fall back instead of awaiting approval."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        with _workspace_temp_dir() as tmp:
            project = Path(tmp)
            bridge = MagicMock()
            bridge.project_path = project
            bridge.client = MagicMock()
            bridge._status_path = project / ".umcp" / "agent-status.json"
            bridge._history = []
            bridge._context = MagicMock()
            bridge._context.as_system_prompt.return_value = "## Unity Project Context"
            assistant = _OfflineUnityAssistant(bridge)

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
                with patch(
                    "cli_anything.unity_mcp.commands.agent_loop_cmd._generate_plan_from_intent",
                    return_value=[{"step": 1, "description": "Answer the user", "route": "continue", "params": {}}],
                ):
                    reply = assistant._try_model_backed_plan("what are your capabilities?")

        assert reply is None
        assert not getattr(bridge, "_pending_model_plan", None)

    def test_try_model_backed_plan_rejects_placeholder_targets(self):
        """Plans with schema placeholder values should not be offered for approval."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        with _workspace_temp_dir() as tmp:
            project = Path(tmp)
            bridge = MagicMock()
            bridge.project_path = project
            bridge.client = MagicMock()
            bridge._status_path = project / ".umcp" / "agent-status.json"
            bridge._history = []
            bridge._context = MagicMock()
            bridge._context.as_system_prompt.return_value = "## Unity Project Context"
            assistant = _OfflineUnityAssistant(bridge)

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
                with patch(
                    "cli_anything.unity_mcp.commands.agent_loop_cmd._generate_plan_from_intent",
                    return_value=[
                        {
                            "step": 1,
                            "description": "Assign new material to object",
                            "route": "material/assign",
                            "params": {"gameObject": "GameObjectPath", "material": "Assets/Materials/New.mat"},
                        }
                    ],
                ):
                    reply = assistant._try_model_backed_plan("make the game look better")

        assert reply is None
        assert not getattr(bridge, "_pending_model_plan", None)

    def test_try_model_backed_plan_rejects_non_executable_feedback_steps(self):
        """Model plans must not offer offline human tasks for approval."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        with _workspace_temp_dir() as tmp:
            project = Path(tmp)
            bridge = MagicMock()
            bridge.project_path = project
            bridge.client = MagicMock()
            bridge._status_path = project / ".umcp" / "agent-status.json"
            bridge._history = []
            bridge._context = MagicMock()
            bridge._context.as_system_prompt.return_value = "## Unity Project Context\nScene: Prototype"

            assistant = _OfflineUnityAssistant(bridge)

            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=True):
                with patch(
                    "cli_anything.unity_mcp.commands.agent_loop_cmd._generate_plan_from_intent",
                    return_value=[
                        {
                            "step": 1,
                            "description": "Playtest the current game mechanics with a small group of players",
                            "route": "editor/play-mode",
                            "params": {"action": "play"},
                        },
                        {
                            "step": 2,
                            "description": "Collect feedback focusing on controls and player satisfaction",
                            "route": "scene/save",
                            "params": {},
                        },
                    ],
                ):
                    reply = assistant._try_model_backed_plan("make the game better")

        assert reply is None
        assert not getattr(bridge, "_pending_model_plan", None)

    def test_try_model_backed_plan_rejects_play_mode_before_scene_edits(self):
        """Plans should not start Play Mode and then try to mutate or save the scene."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        with _workspace_temp_dir() as tmp:
            project = Path(tmp)
            bridge = MagicMock()
            bridge.project_path = project
            bridge.client = MagicMock()
            bridge._status_path = project / ".umcp" / "agent-status.json"
            bridge._history = []
            bridge._context = MagicMock()
            bridge._context.as_system_prompt.return_value = "## Unity Project Context\nScene: Prototype"

            assistant = _OfflineUnityAssistant(bridge)

            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=True):
                with patch(
                    "cli_anything.unity_mcp.commands.agent_loop_cmd._generate_plan_from_intent",
                    return_value=[
                        {
                            "step": 1,
                            "description": "Enter play mode to test the prototype",
                            "route": "editor/play-mode",
                            "params": {"action": "play"},
                        },
                        {
                            "step": 2,
                            "description": "Save the scene after testing",
                            "route": "scene/save",
                            "params": {},
                        },
                    ],
                ):
                    reply = assistant._try_model_backed_plan("test and save the scene")

        assert reply is None
        assert not getattr(bridge, "_pending_model_plan", None)

    def test_try_model_backed_plan_accepts_generation_script_plan(self):
        """Generation requests should be allowed when the model emits executable Unity edits."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        with _workspace_temp_dir() as tmp:
            project = Path(tmp)
            bridge = MagicMock()
            bridge.project_path = project
            bridge.client = MagicMock()
            bridge._status_path = project / ".umcp" / "agent-status.json"
            bridge._history = []
            bridge._context = MagicMock()
            bridge._context.as_system_prompt.return_value = "## Unity Project Context\nScene: EmptyPrototype"

            assistant = _OfflineUnityAssistant(bridge)

            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=True):
                with patch(
                    "cli_anything.unity_mcp.commands.agent_loop_cmd._generate_plan_from_intent",
                    return_value=[
                        {
                            "step": 1,
                            "description": "Create a generated prototype manager object",
                            "route": "gameobject/create",
                            "params": {"name": "GeneratedPrototype", "primitiveType": "Empty"},
                        },
                        {
                            "step": 2,
                            "description": "Create the generated gameplay script",
                            "route": "script/create",
                            "params": {
                                "path": "Assets/Scripts/GeneratedPrototype.cs",
                                "content": "using UnityEngine;\npublic class GeneratedPrototype : MonoBehaviour { void Start() {} }",
                            },
                        },
                        {
                            "step": 3,
                            "description": "Attach the generated script to the manager",
                            "route": "component/add",
                            "params": {"gameObjectPath": "GeneratedPrototype", "componentType": "GeneratedPrototype"},
                        },
                        {
                            "step": 4,
                            "description": "Save the generated scene setup",
                            "route": "scene/save",
                            "params": {},
                        },
                    ],
                ) as generate_plan:
                    reply = assistant._try_model_backed_plan("make me a small arcade block puzzle prototype")

        assert isinstance(reply, dict)
        assert reply["metadata"]["approvalRequired"] is True
        assert len(reply["steps"]) == 4
        assert getattr(bridge, "_pending_model_plan", None)
        generated_intent = generate_plan.call_args.args[0]
        assert "playable/testable vertical slice" in generated_intent
        assert "Do not return prose" in generated_intent
        assert "arcade block puzzle prototype" in generated_intent

    def test_try_model_backed_plan_accepts_new_scene_route(self):
        """The model planner should be allowed to create a fresh scene when requested."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        with _workspace_temp_dir() as tmp:
            project = Path(tmp)
            bridge = MagicMock()
            bridge.project_path = project
            bridge.client = MagicMock()
            bridge._status_path = project / ".umcp" / "agent-status.json"
            bridge._history = []
            bridge._context = MagicMock()
            bridge._context.as_system_prompt.return_value = "## Unity Project Context\nScene: ExistingScene"
            assistant = _OfflineUnityAssistant(bridge)

            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=True):
                with patch(
                    "cli_anything.unity_mcp.commands.agent_loop_cmd._generate_plan_from_intent",
                    return_value=[
                        {
                            "step": 1,
                            "description": "Create a new scene for the generated prototype",
                            "route": "scene/new",
                            "params": {"name": "GeneratedPrototypeScene"},
                        },
                        {
                            "step": 2,
                            "description": "Save the new generated scene",
                            "route": "scene/save",
                            "params": {},
                        },
                    ],
                ):
                    reply = assistant._try_model_backed_plan("build the prototype in a new scene")

        assert isinstance(reply, dict)
        assert getattr(bridge, "_pending_model_plan", None)

    def test_best_effort_generation_request_does_not_fall_back_to_tutorial(self):
        """If a generation plan fails validation, explain instead of returning prose steps."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        bridge = MagicMock()
        assistant = _OfflineUnityAssistant(bridge)

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=True):
            with patch.object(assistant, "_try_model_backed_plan", return_value=None):
                with patch.object(
                    assistant,
                    "_try_model_backed_chat",
                    return_value="Here is a tutorial checklist with playtesting and research.",
                ) as chat_reply:
                    reply = assistant._best_effort_agent_reply("make me a small arcade prototype")

        chat_reply.assert_not_called()
        assert "safe executable Unity plan" in reply
        assert "rejected the vague plan" in reply

    def test_handle_message_preserves_structured_steps(self):
        """Structured assistant replies should persist step previews into chat history."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        bridge = MagicMock()
        bridge._status_state = "awaiting_approval"
        assistant = _OfflineUnityAssistant(bridge)

        with patch.object(
            assistant,
            "_dispatch",
            return_value={
                "content": "I found a plan.",
                "steps": [{"step": 1, "totalSteps": 1, "description": "Create player", "status": "pending"}],
                "metadata": {"approvalRequired": True},
            },
        ):
            assistant.handle_message("create a player", bridge)

        bridge.append_message.assert_called_once()
        kwargs = bridge.append_message.call_args.kwargs
        assert kwargs["steps"][0]["description"] == "Create player"
        assert kwargs["metadata"]["approvalRequired"] is True

    def test_best_effort_reply_falls_back_to_model_chat_when_plan_is_unavailable(self):
        """Freeform chat should use model-backed conversation when planning is not a fit."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        bridge = MagicMock()
        assistant = _OfflineUnityAssistant(bridge)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
            with patch.object(assistant, "_try_model_backed_plan", return_value=None):
                with patch.object(
                    assistant,
                    "_try_model_backed_chat",
                    return_value="You’re building a multiplayer prototype. I’d start by tightening the player loop first.",
                ) as chat_reply:
                    reply = assistant._best_effort_agent_reply("I want this to feel more like a real multiplayer game")

        chat_reply.assert_called_once_with("I want this to feel more like a real multiplayer game")
        assert "multiplayer prototype" in reply.lower()

    def test_try_model_backed_chat_passes_full_context_and_recent_history(self):
        """Model-backed chat should receive fresh full context and recent chat history."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        with _workspace_temp_dir() as tmp:
            project = Path(tmp)
            (project / "AGENTS.md").write_text("Stay grounded in the real scene.\n", encoding="utf-8")

            bridge = MagicMock()
            bridge.project_path = project
            bridge.client = MagicMock()
            bridge._status_path = project / ".umcp" / "agent-status.json"
            bridge._history = [
                {"role": "user", "content": "hello"},
                {"role": "ai", "content": "What are you trying to build?"},
            ]
            bridge._context = MagicMock()
            bridge._context.as_system_prompt.return_value = "## Unity Project Context\nScene: CodexFpsShowcase"

            assistant = _OfflineUnityAssistant(bridge)

            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=True):
                with patch(
                    "cli_anything.unity_mcp.commands.agent_loop_cmd._generate_chat_reply_from_intent",
                    return_value="Let’s scope the player loop first.",
                ) as generate_chat:
                    reply = assistant._try_model_backed_chat("I want this to feel better")

            assert "scope the player loop" in reply.lower()
            bridge._context.as_system_prompt.assert_called_once_with(full=True)
            kwargs = generate_chat.call_args.kwargs
            assert kwargs["history"] == [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "What are you trying to build?"},
            ]
            assert kwargs["model"] == "anthropic/claude-3-haiku"
            assert "Unity Project Context" in kwargs["context_prompt"]
            assert "Stay grounded in the real scene." in kwargs["context_prompt"]

    def test_dispatch_game_review_intent_uses_review_mode_before_planning(self):
        """Natural feedback requests should review live context instead of becoming edit plans."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        bridge = MagicMock()
        assistant = _OfflineUnityAssistant(bridge)

        with patch.object(assistant, "_game_review_reply", return_value="Here is my read on the game.") as review_reply:
            with patch.object(assistant, "_try_model_backed_plan") as plan_reply:
                reply = assistant._dispatch("look at my game and tell me what you think")

        review_reply.assert_called_once_with("look at my game and tell me what you think")
        plan_reply.assert_not_called()
        assert "my read" in reply

    def test_game_review_reply_passes_live_hierarchy_scripts_and_excerpts_to_model(self):
        """Game review should feed the model actual Unity scene/script context."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        with _workspace_temp_dir() as tmp:
            project = Path(tmp)
            (project / "AGENTS.md").write_text("Respect the existing scene and ask before changing it.\n", encoding="utf-8")

            bridge = MagicMock()
            bridge.project_path = project
            bridge._history = []
            bridge._context = MagicMock()
            bridge._context.get.return_value = {
                "projectName": "OutsideTheBox",
                "unityVersion": "6000.4.0f1",
                "scene": {
                    "name": "CodexBirdPovBash",
                    "objectCount": 34,
                    "rootObjects": ["CodexBirdPovBash"],
                },
            }
            bridge.client = MagicMock()

            def route_side_effect(route, payload):
                if route == "editor/state":
                    return {
                        "activeScene": "CodexBirdPovBash",
                        "unityVersion": "6000.4.0f1",
                        "sceneDirty": False,
                        "isPlaying": False,
                        "isCompiling": False,
                    }
                if route == "scene/hierarchy":
                    return {
                        "sceneName": "CodexBirdPovBash",
                        "totalTraversed": 34,
                        "nodes": [
                            {
                                "name": "BirdPlayer",
                                "path": "/CodexBirdPovBash/BirdPlayer",
                                "components": ["Transform", "Rigidbody", "CodexBirdPovBashBirdPovController"],
                            }
                        ],
                    }
                if route == "script/list":
                    return {
                        "count": 2,
                        "scripts": [
                            {
                                "name": "CodexBirdPovBashBirdPovController",
                                "path": "Assets/CodexSamples/BirdPov/CodexBirdPovBashBirdPovController.cs",
                            },
                            {
                                "name": "OutsideTheBoxSmokeTests",
                                "path": "Assets/Tests/OutsideTheBoxSmokeTests.cs",
                            },
                        ],
                    }
                if route == "compilation/errors":
                    return {"hasErrors": False, "count": 0, "entries": []}
                if route == "script/read":
                    return {
                        "path": payload["path"],
                        "lineCount": 20,
                        "content": "public class CodexBirdPovBashBirdPovController : MonoBehaviour { public float LaunchForce = 42f; }",
                    }
                raise AssertionError(route)

            bridge.client.call_route.side_effect = route_side_effect
            assistant = _OfflineUnityAssistant(bridge)

            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=True):
                with patch(
                    "cli_anything.unity_mcp.commands.agent_loop_cmd._generate_chat_reply_from_intent",
                    return_value="This looks like a bird-launch prototype with a clear core loop.",
                ) as generate_chat:
                    reply = assistant._game_review_reply("look at my game")

        assert "bird-launch prototype" in reply
        kwargs = generate_chat.call_args.kwargs
        context_prompt = kwargs["context_prompt"]
        assert "Live Unity Game Review Context" in context_prompt
        assert "CodexBirdPovBash" in context_prompt
        assert "/CodexBirdPovBash/BirdPlayer" in context_prompt
        assert "CodexBirdPovBashBirdPovController" in context_prompt
        assert "LaunchForce" in context_prompt
        assert "approval before applying" in context_prompt

    def test_game_review_falls_back_without_model_provider(self):
        """Review requests should still return a grounded summary without an API key."""
        from unittest.mock import MagicMock, patch
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        bridge = MagicMock()
        bridge.project_path = Path("C:/tmp/OutsideTheBox")
        bridge._history = []
        bridge._context = MagicMock()
        bridge._context.get.return_value = {
            "projectName": "OutsideTheBox",
            "scene": {"name": "PrototypeArena", "objectCount": 12, "rootObjects": ["PrototypeArena"]},
        }
        bridge.client = MagicMock()

        def route_side_effect(route, payload):
            if route == "editor/state":
                return {"activeScene": "PrototypeArena", "sceneDirty": False, "isPlaying": False, "isCompiling": False}
            if route == "scene/hierarchy":
                return {"sceneName": "PrototypeArena", "totalTraversed": 12, "nodes": [{"name": "Player", "components": ["Transform"]}]}
            if route == "script/list":
                return {"count": 1, "scripts": [{"name": "PlayerMovement", "path": "Assets/Scripts/PlayerMovement.cs"}]}
            if route == "compilation/errors":
                return {"hasErrors": False, "count": 0, "entries": []}
            if route == "script/read":
                return {"content": "public class PlayerMovement : MonoBehaviour {}", "lineCount": 1}
            raise AssertionError(route)

        bridge.client.call_route.side_effect = route_side_effect
        assistant = _OfflineUnityAssistant(bridge)

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(assistant, "_try_model_backed_plan") as plan_reply:
                reply = assistant._dispatch("what do you think of my game?")

        plan_reply.assert_not_called()
        assert "prototypearena" in reply.lower()
        assert "compile state looks clean" in reply.lower()

    def test_capture_after_action_does_not_invalidate_cached_context(self):
        """Disabled capture path should return empty and avoid touching cached context."""
        from unittest.mock import MagicMock
        from cli_anything.unity_mcp.core.agent_chat import _OfflineUnityAssistant

        bridge = MagicMock()
        bridge._context = MagicMock()

        assistant = _OfflineUnityAssistant(bridge)
        result = assistant._capture_after_action()

        assert result == {}
        bridge._context.invalidate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
