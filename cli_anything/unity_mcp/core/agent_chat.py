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
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from .agent_loop import AgentLoop, format_results
from .file_ipc import FileIPCClient, ContextInjector

if TYPE_CHECKING:
    from .embedded_cli import EmbeddedCLIOptions


_PROJECT_ENV_KEYS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_ORG_ID",
)


def _parse_project_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        raw_text = path.read_text(encoding="utf-8")
    except Exception:
        return {}

    values: dict[str, str] = {}
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
            value = value[1:-1]
        values[key] = value
    return values


class _OfflineUnityAssistant:
    """Project-aware offline assistant for the Unity Agent tab.

    This keeps the Agent tab useful without requiring API keys. It routes
    project-wide requests through embedded CLI workflows and keeps fast live
    scene actions on direct File IPC.
    """

    _GREETING_RE = re.compile(r"^(hi|hello|hey|yo|sup)\b", re.IGNORECASE)
    _CREATE_PRIMITIVE_RE = re.compile(
        r"\bcreate(?:\s+a|\s+an)?\s+(cube|sphere|capsule|cylinder|plane|quad|empty)\b",
        re.IGNORECASE,
    )
    _POSITION_RE = re.compile(
        r"\bat\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\b",
        re.IGNORECASE,
    )
    _DISPOSABLE_OBJECT_TOKENS: tuple[str, ...] = ("probe", "fixture", "temp", "debug", "standalone")
    _PLAYER_TOKENS: tuple[str, ...] = ("player", "hero", "avatar", "character", "pawn")
    _PHYSICS_FEEL_RE = re.compile(
        r"\b(floaty|floats?|weighty|heavy|slippery|snappy|stiff|sluggish|"
        r"sloppy|jumps?\s+feel|movement\s+feel|feels?\s+off|feels?\s+wrong|"
        r"doesn't\s+feel\s+right)\b",
        re.IGNORECASE,
    )
    _PHYSICS_APPLY_RE = re.compile(
        r"^apply\s+(?:option\s+)?(1|2|3|snappy|controlled|arcade)\b",
        re.IGNORECASE,
    )
    _AUTONOMOUS_TRIGGERS: tuple[str, ...] = (
        "fix all", "fix everything", "fix the issues",
        "polish", "improve the", "clean up",
        "make it better", "optimize", "refactor",
        "do a pass", "run a pass",
    )
    _MOVEMENT_SCRIPT_TEMPLATE: str = """\
using UnityEngine;

[RequireComponent(typeof(CharacterController))]
public class PlayerMovement : MonoBehaviour
{{
    [SerializeField] private float speed = 5f;
    [SerializeField] private float jumpHeight = 1.5f;
    [SerializeField] private float gravity = -9.81f;

    private CharacterController _controller;
    private Vector3 _velocity;
    private bool _isGrounded;

    private void Awake() => _controller = GetComponent<CharacterController>();

    private void Update()
    {{
        _isGrounded = _controller.isGrounded;
        if (_isGrounded && _velocity.y < 0) _velocity.y = -2f;

        float h = Input.GetAxis("Horizontal");
        float v = Input.GetAxis("Vertical");
        Vector3 move = transform.right * h + transform.forward * v;
        _controller.Move(move * speed * Time.deltaTime);

        if (Input.GetButtonDown("Jump") && _isGrounded)
            _velocity.y = Mathf.Sqrt(jumpHeight * -2f * gravity);

        _velocity.y += gravity * Time.deltaTime;
        _controller.Move(_velocity * Time.deltaTime);
    }}
}}
"""

    def __init__(
        self,
        bridge: "ChatBridge",
        *,
        embedded_options: "EmbeddedCLIOptions | None" = None,
    ) -> None:
        self.bridge = bridge
        self.embedded_options = embedded_options

    def handle_message(self, content: str, bridge: "ChatBridge") -> None:
        try:
            reply = self._dispatch(content)
        except Exception as exc:
            bridge.append_message("ai", f"I hit an error while processing that: {exc}")
        else:
            if isinstance(reply, dict):
                bridge.append_message(
                    "ai",
                    str(reply.get("content") or ""),
                    metadata=dict(reply.get("metadata") or {}),
                )
            else:
                bridge.append_message("ai", reply)
        finally:
            bridge.write_status("idle", 0, 0, "")

    def _dispatch(self, content: str) -> str | dict[str, Any]:
        normalized = " ".join((content or "").strip().split())
        lowered = normalized.lower()
        if not normalized:
            return self._help_reply()
        if self._GREETING_RE.match(normalized) or lowered in {"help", "what can you do", "what do you do"}:
            return self._greeting_reply()
        if lowered in {"context", "project context", "project info", "what do you know about the project"}:
            return self._context_reply()
        if any(phrase in lowered for phrase in ("improve project", "make the project better", "safe improvements", "fix what you can")):
            return self._improve_project_reply()
        if any(phrase in lowered for phrase in ("inspect project", "audit project", "analyze project", "review project")):
            return self._project_audit_reply()
        if "quality score" in lowered or "project score" in lowered or "how healthy" in lowered:
            return self._quality_score_reply()
        if "benchmark" in lowered or "scorecard" in lowered:
            return self._benchmark_reply()
        if "scene critique" in lowered or "critique scene" in lowered:
            return self._scene_critique_reply()
        if lowered in {"compile errors", "compilation errors", "errors", "compiler errors"}:
            return self._compile_errors_reply()
        if lowered in {"scene info", "scene", "scene/info"}:
            return self._scene_info_reply()
        if lowered in {"list scripts", "scripts"}:
            return self._scripts_reply()
        if lowered in {"hierarchy", "scene hierarchy"}:
            return self._hierarchy_reply()
        if lowered in {"save scene", "save"}:
            return self._save_scene_reply()
        if "sandbox" in lowered and any(word in lowered for word in ("create", "make", "add")):
            return self._create_sandbox_reply()
        if "guidance" in lowered and any(word in lowered for word in ("create", "write", "bootstrap", "scaffold", "add")):
            return self._guidance_reply()
        if ("test scaffold" in lowered or "scaffold test" in lowered or "create tests" in lowered or "add tests" in lowered):
            return self._test_scaffold_reply()
        physics_apply_match = self._PHYSICS_APPLY_RE.match(lowered)
        if physics_apply_match:
            return self._apply_physics_feel_reply(physics_apply_match.group(1))
        if self._PHYSICS_FEEL_RE.search(normalized):
            return self._build_physics_feel_reply(normalized)
        # Player prototype
        if any(phrase in lowered for phrase in (
            "build a player", "create a player", "add a player",
            "player controller", "player prototype", "make a player",
            "build player", "create player",
        )):
            player_name = "Player"
            name_match = re.search(r"(?:called|named|name[d]?)\s+([A-Za-z_]\w*)", normalized)
            if name_match:
                player_name = name_match.group(1)
            return self._build_player_prototype_reply(player_name)
        # Script create+attach: "create a Rotate script and attach it to Cube"
        _script_attach_re = re.compile(
            r"(?:create|add|write|make)\s+(?:a\s+)?([A-Za-z_]\w*)\s+script"
            r"(?:\s+(?:and\s+)?(?:attach|add)\s+(?:it\s+)?(?:to\s+)?([A-Za-z_]\w*))?",
            re.IGNORECASE,
        )
        script_match = _script_attach_re.search(normalized)
        if script_match:
            sname = script_match.group(1)
            go = script_match.group(2) or "GameObject"
            return self._build_script_attach_reply(sname, go, normalized)
        # Check for pending autonomous plan confirmation
        pending_plan = getattr(self.bridge, "_pending_autonomous_plan", None)
        if pending_plan and lowered in {"yes", "go", "proceed", "do it", "execute", "run it", "confirm"}:
            return self._execute_pending_autonomous_plan()
        # Autonomous goal mode
        if any(phrase in lowered for phrase in self._AUTONOMOUS_TRIGGERS):
            return self._autonomous_goal_reply(normalized)
        create_match = self._CREATE_PRIMITIVE_RE.search(normalized)
        if create_match:
            return self._create_primitive_reply(create_match.group(1), normalized)
        return self._best_effort_agent_reply(normalized)

    def _run_embedded_cli(self, argv: list[str]) -> dict[str, Any]:
        if self.embedded_options is None:
            raise RuntimeError("Embedded CLI options are unavailable for this chat session.")
        from .embedded_cli import run_cli_json

        return dict(run_cli_json(argv, self.embedded_options) or {})

    def _set_status(self, action: str, *, current: int = 0, total: int = 1) -> None:
        self.bridge.write_status("executing", current, total, action)

    def _context_payload(self) -> dict[str, Any]:
        self._set_status("Reading Unity project context")
        return dict(self.bridge._context.get(force=True) or {})

    def _skill_project_context(self) -> "ProjectContext":
        from .skills import ProjectContext

        try:
            context_payload = dict(self.bridge._context.get(force=True, full=True) or {})
        except Exception:
            context_payload = {}
        return ProjectContext(
            project_path=str(getattr(self.bridge, "project_path", "") or ""),
            selected_port=None,
            inspect_payload=context_payload,
            systems_summary=context_payload,
        )

    def _compact_findings(self, findings: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
        lines: list[str] = []
        for finding in findings[:limit]:
            title = str(finding.get("title") or "Finding").strip()
            detail = str(finding.get("detail") or "").strip()
            lines.append(f"- {title}: {detail}" if detail else f"- {title}")
        return lines

    def _compact_recommendations(self, recommendations: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
        lines: list[str] = []
        for item in recommendations[:limit]:
            title = str(item.get("title") or "Recommendation").strip()
            detail = str(item.get("detail") or "").strip()
            lines.append(f"- {title}: {detail}" if detail else f"- {title}")
        return lines

    def _score_lines(self, lens_scores: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
        scored = [dict(item) for item in lens_scores if isinstance(item, dict)]
        scored.sort(
            key=lambda item: (
                item.get("score") is None,
                int(item.get("score") or 999),
                str(item.get("name") or ""),
            )
        )
        lines: list[str] = []
        for item in scored[:limit]:
            score = item.get("score")
            grade = str(item.get("grade") or "").strip()
            lines.append(f"- {item.get('name')}: {score} ({grade})" if score is not None else f"- {item.get('name')}: no live score")
        return lines

    def _project_name(self) -> str:
        try:
            context = self.bridge._context.get()
        except Exception:
            context = {}
        return str(context.get("projectName") or self.bridge.project_path.name)

    def _active_scene_name(self) -> str:
        try:
            context = self.bridge._context.get()
        except Exception:
            context = {}
        scene = dict(context.get("scene") or {})
        return str(scene.get("name") or "unknown")

    def _configured_model_provider(self) -> str | None:
        preferred = self._preferred_provider()
        if preferred == "openai" and os.environ.get("OPENAI_API_KEY"):
            return "OpenAI"
        if preferred == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
            return "Anthropic"
        if preferred == "openrouter" and os.environ.get("OPENROUTER_API_KEY"):
            return "OpenRouter"
        if os.environ.get("OPENROUTER_API_KEY"):
            return "OpenRouter"
        if os.environ.get("OPENAI_API_KEY"):
            return "OpenAI"
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "Anthropic"
        return None

    def _selected_model(self) -> str | None:
        model = self._load_agent_config().get("preferredModel")
        if model:
            return str(model).strip() or None
        provider = self._configured_model_provider()
        if provider == "OpenAI":
            return "gpt-5-codex"
        if provider == "Anthropic":
            return "claude-haiku-4-5-20251001"
        if provider == "OpenRouter":
            return "anthropic/claude-3-haiku"
        return None

    def _preferred_provider(self) -> str | None:
        provider = self._load_agent_config().get("preferredProvider")
        normalized = str(provider or "").strip().lower()
        if normalized in {"openai", "anthropic", "openrouter"}:
            return normalized
        return None

    def _load_agent_config(self) -> dict[str, Any]:
        config_path = self.bridge.project_path / ".umcp" / "agent-config.json"
        if not config_path.exists():
            return {}
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return dict(raw) if isinstance(raw, dict) else {}

    def _recent_history(self, limit: int = 6) -> list[dict[str, str]]:
        entries = list(getattr(self.bridge, "_history", []) or [])
        recent: list[dict[str, str]] = []
        for entry in entries[-limit:]:
            role = str(entry.get("role") or "").strip().lower()
            content = str(entry.get("content") or "").strip()
            if not content or role not in {"user", "ai", "assistant"}:
                continue
            recent.append(
                {
                    "role": "assistant" if role in {"ai", "assistant"} else "user",
                    "content": content,
                }
            )
        return recent

    def _project_instructions(self) -> str:
        agents_path = self.bridge.project_path / "AGENTS.md"
        if not agents_path.exists():
            return ""
        try:
            text = agents_path.read_text(encoding="utf-8")
        except Exception:
            return ""
        normalized = " ".join(text.split())
        if not normalized:
            return ""
        return normalized[:1200] + ("..." if len(normalized) > 1200 else "")

    def _model_context_prompt(self) -> str:
        sections: list[str] = []
        try:
            prompt = self.bridge._context.as_system_prompt(full=True)
        except Exception:
            prompt = ""
        prompt = str(prompt or "").strip()
        if prompt:
            sections.append(prompt)
        instructions = self._project_instructions()
        if instructions:
            sections.append(f"## Project Instructions\n{instructions}")
        return "\n\n".join(section for section in sections if section)

    def _invalidate_context_cache(self) -> None:
        context = getattr(self.bridge, "_context", None)
        invalidate = getattr(context, "invalidate", None)
        if callable(invalidate):
            try:
                invalidate()
            except Exception:
                pass

    def _greeting_reply(self) -> str:
        project_name = self._project_name()
        active_scene = self._active_scene_name()
        return (
            f"I’m connected to `{project_name}` and the current scene looks like `{active_scene}`.\n\n"
            "I can inspect the project, score quality, run benchmarks, check compile errors, "
            "show scene info or hierarchy, save the scene, create sandbox scenes, scaffold guidance/tests, "
            "and create basic primitives directly in Unity.\n\n"
            "Try asking:\n"
            "- improve project\n"
            "- inspect project\n"
            "- quality score\n"
            "- benchmark\n"
            "- compile errors\n"
            "- create sandbox scene\n"
            "- create guidance\n"
            "- create cube at 0 1 0"
        )

    def _help_reply(self) -> str:
        return self._greeting_reply()

    def _context_reply(self) -> str:
        context = self._context_payload()
        scene = dict(context.get("scene") or {})
        asset_counts = dict(context.get("assetCounts") or {})
        compile_errors = list(context.get("compileErrors") or [])
        recent_console_errors = list(context.get("recentConsoleErrors") or [])
        lines = [
            self.bridge._context.as_system_prompt(),
            "",
            f"Scene roots: {', '.join(scene.get('rootObjects') or []) or 'n/a'}",
            (
                "Assets: "
                f"{asset_counts.get('scripts', 0)} scripts, "
                f"{asset_counts.get('prefabs', 0)} prefabs, "
                f"{asset_counts.get('materials', 0)} materials, "
                f"{asset_counts.get('scenes', 0)} scenes"
            ),
        ]
        if compile_errors:
            lines.append(f"Compile errors: {len(compile_errors)}")
        elif recent_console_errors:
            lines.append("Recent console issue: " + str(recent_console_errors[0].get("message") or "")[:140])
        else:
            lines.append("Compiler state looks clean right now.")
        return "\n".join(lines)

    def _project_audit_reply(self) -> str:
        if self.embedded_options is None:
            return self._context_reply()
        self._set_status("Running project audit")
        quality = self._run_embedded_cli(["workflow", "quality-score", str(self.bridge.project_path)])
        systems = self._run_embedded_cli(
            ["workflow", "expert-audit", "--lens", "systems", str(self.bridge.project_path)]
        )
        lines = [
            f"Overall quality: {quality.get('overallScore')}."
        ]
        lens_scores = list(quality.get("lensScores") or [])
        if lens_scores:
            lines.append("Weakest lenses:")
            lines.extend(self._score_lines(lens_scores))
        findings = list(systems.get("findings") or [])
        if findings:
            lines.append("")
            lines.append("Top systems findings:")
            lines.extend(self._compact_findings(findings))
        recommendations = list(systems.get("topRecommendations") or [])
        if recommendations:
            lines.append("")
            lines.append("Best next moves:")
            lines.extend(self._compact_recommendations(recommendations))
        return "\n".join(lines)

    def _quality_score_reply(self) -> str:
        if self.embedded_options is None:
            return "Quality scoring needs the embedded CLI path, which is unavailable in this chat session."
        self._set_status("Scoring project quality")
        payload = self._run_embedded_cli(["workflow", "quality-score", str(self.bridge.project_path)])
        lines = [f"Overall quality score: {payload.get('overallScore')}."]
        lens_scores = list(payload.get("lensScores") or [])
        if lens_scores:
            lines.append("Weakest lenses:")
            lines.extend(self._score_lines(lens_scores))
        return "\n".join(lines)

    def _benchmark_reply(self) -> str:
        if self.embedded_options is None:
            return "Benchmark reporting needs the embedded CLI path, which is unavailable in this chat session."
        self._set_status("Building benchmark report")
        payload = self._run_embedded_cli(["workflow", "benchmark-report", str(self.bridge.project_path)])
        lines = [
            f"Benchmark score: {payload.get('overallScore')} ({payload.get('overallGrade')}).",
        ]
        weakest = list(payload.get("weakestLenses") or [])
        if weakest:
            lines.append("Weakest lenses:")
            lines.extend(
                f"- {item.get('name')}: {item.get('score')} ({item.get('grade')})"
                for item in weakest[:3]
            )
        queue_diagnostics = dict(payload.get("queueDiagnostics") or {})
        if queue_diagnostics:
            lines.append("")
            lines.append("Queue health:")
            lines.append(f"- {queue_diagnostics.get('summary')}")
        queue_trend = dict(payload.get("queueTrend") or {})
        if queue_trend:
            lines.append(f"- Queue trend: {queue_trend.get('summary')}")
        top_findings = list(payload.get("topFindings") or [])
        if top_findings:
            lines.append("")
            lines.append("Top findings:")
            lines.extend(self._compact_findings(top_findings))
        return "\n".join(lines)

    def _scene_critique_reply(self) -> str:
        if self.embedded_options is None:
            return "Scene critique needs the embedded CLI path, which is unavailable in this chat session."
        self._set_status("Running scene critique")
        payload = self._run_embedded_cli(["workflow", "scene-critique", str(self.bridge.project_path)])
        lines = [
            f"Scene critique average score: {payload.get('averageScore')}.",
            f"Finding count: {payload.get('findingCount')}.",
        ]
        findings = list(payload.get("findings") or [])
        if findings:
            lines.append("Top critique findings:")
            lines.extend(self._compact_findings(findings))
        return "\n".join(lines)

    def _compile_errors_reply(self) -> str:
        self._set_status("Reading compilation errors")
        result = dict(self.bridge.client.call_route("compilation/errors", {}))
        if not result.get("hasErrors"):
            return "No compilation errors found right now."
        entries = list(result.get("entries") or [])
        lines = [f"{result.get('count')} compilation error(s):"]
        for entry in entries[:5]:
            lines.append("- " + str(entry.get("message") or "").strip())
        return "\n".join(lines)

    def _scene_info_reply(self) -> str:
        self._set_status("Reading scene info")
        result = dict(self.bridge.client.call_route("scene/info", {}))
        active_scene = result.get("sceneName") or result.get("name") or "unknown"
        lines = [f"Active scene: {active_scene}."]
        if result.get("path"):
            lines.append(f"Path: {result.get('path')}")
        if result.get("isDirty") is not None:
            lines.append(f"Dirty: {result.get('isDirty')}")
        if result.get("rootCount") is not None:
            lines.append(f"Root objects: {result.get('rootCount')}")
        return "\n".join(lines)

    def _scripts_reply(self) -> str:
        self._set_status("Listing scripts")
        result = dict(self.bridge.client.call_route("script/list", {}))
        scripts = list(result.get("scripts") or [])
        lines = [f"{result.get('count', len(scripts))} scripts found:"]
        for script in scripts[:12]:
            lines.append(f"- {script.get('name')} ({script.get('path')})")
        return "\n".join(lines)

    def _hierarchy_reply(self) -> str:
        self._set_status("Reading scene hierarchy")
        result = dict(self.bridge.client.call_route("scene/hierarchy", {"maxNodes": 100}))
        nodes = list(result.get("nodes") or [])
        lines = [f"Scene: {result.get('sceneName')} ({result.get('totalTraversed')} objects)"]
        for node in nodes[:20]:
            components = ", ".join(node.get("components") or [])
            lines.append(f"- {node.get('name')} [{components}]".rstrip())
        return "\n".join(lines)

    def _save_scene_reply(self) -> str:
        self._set_status("Saving scene")
        result = dict(self.bridge.client.call_route("scene/save", {}))
        return f"Scene saved: {result.get('scene') or result.get('sceneName') or 'active scene'}."

    def _create_sandbox_reply(self) -> str:
        if not self._has_live_unity():
            return "Could not create the sandbox scene because no live Unity session is available."
        self._set_status("Creating sandbox scene")
        result = dict(
            self.bridge.client.call_route(
                "scene/create-sandbox",
                {"saveIfDirty": True, "open": False},
            )
        )
        if result.get("error"):
            return f"Could not create the sandbox scene: {result.get('error')}"
        return (
            f"Sandbox scene ready at {result.get('path')}.\n"
            f"Kept open: {result.get('keptOpen')} | Restored original: {result.get('reopenedOriginal')}"
        )

    def _guidance_reply(self) -> str:
        if self.embedded_options is None:
            return "Guidance scaffolding needs the embedded CLI path, which is unavailable in this chat session."
        self._set_status("Writing project guidance")
        payload = self._run_embedded_cli(
            [
                "workflow",
                "quality-fix",
                "--lens",
                "director",
                "--fix",
                "guidance",
                "--apply",
                str(self.bridge.project_path),
            ]
        )
        apply_result = dict(payload.get("applyResult") or {})
        result = dict(apply_result.get("result") or {})
        write_result = dict(result.get("writeResult") or {})
        written_paths = [str(item.get("path") or "") for item in (write_result.get("files") or []) if isinstance(item, dict)]
        lines = [f"Guidance written: {write_result.get('writeCount', 0)} file(s)."]
        if written_paths:
            lines.extend(f"- {path}" for path in written_paths[:4])
        return "\n".join(lines)

    def _test_scaffold_reply(self) -> str:
        if self.embedded_options is None:
            return "Test scaffolding needs the embedded CLI path, which is unavailable in this chat session."
        self._set_status("Scaffolding tests")
        payload = self._run_embedded_cli(
            [
                "workflow",
                "quality-fix",
                "--lens",
                "director",
                "--fix",
                "test-scaffold",
                "--apply",
                str(self.bridge.project_path),
            ]
        )
        apply_result = dict(payload.get("applyResult") or {})
        result = dict(apply_result.get("result") or {})
        return (
            f"EditMode test scaffold written: {result.get('writeCount', 0)} file(s).\n"
            f"Folder: {result.get('folder') or 'Assets/Tests/EditMode'}"
        )

    def _project_has_guidance(self) -> bool:
        return (self.bridge.project_path / "AGENTS.md").exists()

    def _project_has_sandbox_scene(self) -> bool:
        assets_root = self.bridge.project_path / "Assets"
        if not assets_root.exists():
            return False
        for scene_path in assets_root.rglob("*.unity"):
            lower_name = scene_path.name.lower()
            if any(token in lower_name for token in ("sandbox", "playground", "prototype", "test")):
                return True
        return False

    def _project_has_tests(self) -> bool:
        assets_root = self.bridge.project_path / "Assets"
        if not assets_root.exists():
            return False
        for path in assets_root.rglob("*.cs"):
            if not path.is_file():
                continue
            try:
                relative_parts = [part.lower() for part in path.relative_to(assets_root).parts]
            except ValueError:
                continue
            parent_parts = relative_parts[:-1]
            filename = relative_parts[-1] if relative_parts else path.name.lower()
            if "test" in filename or any("test" in part for part in parent_parts):
                return True
        return False

    def _project_has_test_framework(self) -> bool:
        manifest_path = self.bridge.project_path / "Packages" / "manifest.json"
        if not manifest_path.exists():
            return False
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        dependencies = dict(payload.get("dependencies") or {})
        return "com.unity.test-framework" in dependencies

    def _uses_input_system(self) -> bool:
        manifest_path = self.bridge.project_path / "Packages" / "manifest.json"
        if not manifest_path.exists():
            return False
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        dependencies = dict(payload.get("dependencies") or {})
        return "com.unity.inputsystem" in dependencies

    def _hierarchy_nodes(self) -> list[dict[str, Any]]:
        payload = dict(self.bridge.client.call_route("scene/hierarchy", {"maxNodes": 500}))
        raw_nodes = payload.get("nodes") or payload.get("hierarchy") or []
        flattened: list[dict[str, Any]] = []
        stack = [node for node in raw_nodes if isinstance(node, dict)]
        while stack:
            node = stack.pop(0)
            flattened.append(node)
            children = node.get("children") or []
            if isinstance(children, list):
                stack.extend(child for child in children if isinstance(child, dict))
        return flattened

    def _event_system_target_path(self, node: dict[str, Any]) -> str:
        return str(
            node.get("path")
            or node.get("hierarchyPath")
            or node.get("gameObjectPath")
            or node.get("name")
            or "EventSystem"
        ).strip()

    def _choose_primary_audio_listener(self, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        def _rank(node: dict[str, Any]) -> tuple[int, int, str]:
            path = self._event_system_target_path(node).lower()
            priority = 2
            if "main camera" in path:
                priority = 0
            elif "camera" in path:
                priority = 1
            return (priority, len(path), path)

        return sorted(nodes, key=_rank)[0]

    def _rank_likely_player(self, node: dict[str, Any]) -> tuple[int, int, str]:
        path = self._event_system_target_path(node).lower()
        priority = 2
        if path == "player" or path.endswith("/player"):
            priority = 0
        elif "player" in path:
            priority = 1
        return (priority, len(path), path)

    def _choose_likely_player(self, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        return sorted(nodes, key=self._rank_likely_player)[0]

    def _looks_disposable_object(self, path: str) -> bool:
        normalized = str(path or "").replace("\\", "/").lower()
        return any(token in normalized for token in self._DISPOSABLE_OBJECT_TOKENS)

    def _repair_audio_listener_setup(self) -> dict[str, Any] | None:
        nodes = self._hierarchy_nodes()
        listener_nodes = [
            node
            for node in nodes
            if "AudioListener" in {str(component) for component in (node.get("components") or [])}
        ]
        if not listener_nodes:
            camera_nodes = [
                node
                for node in nodes
                if "Camera" in {str(component) for component in (node.get("components") or [])}
            ]
            if not camera_nodes:
                return None

            keep_node = self._choose_primary_audio_listener(camera_nodes)
            keep_path = self._event_system_target_path(keep_node)
            self.bridge.client.call_route(
                "component/add",
                {"gameObjectPath": keep_path, "componentType": "AudioListener"},
            )
            return {
                "applied": True,
                "keptPath": keep_path,
                "removedPaths": [],
                "removedCount": 0,
                "added": True,
            }

        if len(listener_nodes) == 1:
            return None

        keep_node = self._choose_primary_audio_listener(listener_nodes)
        keep_path = self._event_system_target_path(keep_node)
        removed_paths: list[str] = []

        for node in listener_nodes:
            path = self._event_system_target_path(node)
            if path == keep_path:
                continue
            self.bridge.client.call_route(
                "component/remove",
                {
                    "gameObject": path,
                    "gameObjectPath": path,
                    "component": "AudioListener",
                },
            )
            removed_paths.append(path)

        return {
            "applied": True,
            "keptPath": keep_path,
            "removedPaths": removed_paths,
            "removedCount": len(removed_paths),
        }

    def _cleanup_disposable_objects(self) -> dict[str, Any] | None:
        nodes = self._hierarchy_nodes()
        disposable_paths = [
            self._event_system_target_path(node)
            for node in nodes
            if self._looks_disposable_object(self._event_system_target_path(node))
        ]
        unique_paths: list[str] = []
        seen: set[str] = set()
        for path in disposable_paths:
            if not path or path in seen:
                continue
            seen.add(path)
            unique_paths.append(path)
        if not unique_paths:
            return None

        removed_paths: list[str] = []
        for path in unique_paths:
            result = dict(
                self.bridge.client.call_route(
                    "gameobject/delete",
                    {"gameObjectPath": path, "path": path},
                )
            )
            if result.get("success") or result.get("deleted"):
                removed_paths.append(path)
        return {
            "applied": bool(removed_paths),
            "removedPaths": removed_paths,
            "removedCount": len(removed_paths),
        }

    def _repair_player_character_controller(self) -> dict[str, Any] | None:
        nodes = self._hierarchy_nodes()
        candidate_nodes: list[dict[str, Any]] = []
        for node in nodes:
            path = self._event_system_target_path(node)
            normalized = path.lower()
            if not any(token in normalized for token in self._PLAYER_TOKENS):
                continue
            components = {str(component) for component in (node.get("components") or [])}
            if "CharacterController" in components or "Rigidbody" in components or "Rigidbody2D" in components:
                continue
            candidate_nodes.append(node)

        if not candidate_nodes:
            return None

        if len(candidate_nodes) > 1:
            candidate_paths = [
                self._event_system_target_path(node)
                for node in sorted(candidate_nodes, key=self._rank_likely_player)
            ]
            return {
                "applied": False,
                "candidateCount": len(candidate_paths),
                "candidatePaths": candidate_paths[:6],
                "reason": "Multiple likely player objects were found, so the bounded CharacterController fix refused to guess.",
            }

        target_node = self._choose_likely_player(candidate_nodes)
        target_path = self._event_system_target_path(target_node)
        self.bridge.client.call_route(
            "component/add",
            {"gameObjectPath": target_path, "componentType": "CharacterController"},
        )
        return {
            "applied": True,
            "targetPath": target_path,
        }

    def _repair_event_system_setup(self) -> dict[str, Any] | None:
        nodes = self._hierarchy_nodes()
        canvas_nodes = [
            node for node in nodes if "Canvas" in {str(component) for component in (node.get("components") or [])}
        ]
        if not canvas_nodes:
            return None

        module_type = "InputSystemUIInputModule" if self._uses_input_system() else "StandaloneInputModule"

        event_nodes = [
            node for node in nodes if "EventSystem" in {str(component) for component in (node.get("components") or [])}
        ]
        if event_nodes:
            keep_node = next(
                (node for node in event_nodes if str(node.get("name") or "").strip() == "EventSystem"),
                event_nodes[0],
            )
            keep_path = self._event_system_target_path(keep_node)
            keep_components = {str(component) for component in (keep_node.get("components") or [])}
            removable_components = {"EventSystem", "StandaloneInputModule", "InputSystemUIInputModule"}
            extra_keep_modules = [
                component_type
                for component_type in sorted((removable_components - {"EventSystem", module_type}) & keep_components)
            ]
            for component_type in extra_keep_modules:
                self.bridge.client.call_route(
                    "component/remove",
                    {
                        "gameObject": keep_path,
                        "gameObjectPath": keep_path,
                        "component": component_type,
                    },
                )
            duplicate_paths: list[str] = []
            for node in event_nodes:
                target_path = self._event_system_target_path(node)
                if target_path == keep_path:
                    continue
                duplicate_components = {str(component) for component in (node.get("components") or [])}
                removed_any = False
                for component_type in sorted(removable_components & duplicate_components):
                    self.bridge.client.call_route(
                        "component/remove",
                        {
                            "gameObject": target_path,
                            "gameObjectPath": target_path,
                            "component": component_type,
                        },
                    )
                    removed_any = True
                if removed_any:
                    duplicate_paths.append(target_path)

            applied = False
            if module_type not in keep_components:
                self.bridge.client.call_route(
                    "component/add",
                    {"gameObjectPath": keep_path, "componentType": module_type},
                )
                applied = True
            if extra_keep_modules:
                applied = True

            if applied or duplicate_paths:
                return {
                    "applied": True,
                    "gameObjectPath": keep_path,
                    "moduleType": module_type,
                    "created": False,
                    "canvasCount": len(canvas_nodes),
                    "duplicateRemovedCount": len(duplicate_paths),
                    "duplicatePaths": duplicate_paths,
                    "moduleAdded": module_type not in keep_components,
                    "primaryRemovedComponents": extra_keep_modules,
                }
            return {
                "applied": False,
                "reason": "Scene EventSystem already exists.",
                "moduleType": None,
            }

        named_event_node = next(
            (node for node in nodes if str(node.get("name") or "").strip() == "EventSystem"),
            None,
        )
        created = False
        if named_event_node is not None:
            target_path = self._event_system_target_path(named_event_node)
        else:
            create_result = dict(
                self.bridge.client.call_route(
                    "gameobject/create",
                    {"name": "EventSystem", "primitiveType": "Empty"},
                )
            )
            target_path = str(create_result.get("path") or create_result.get("name") or "EventSystem").strip()
            created = True

        for component_type in ("EventSystem", module_type):
            self.bridge.client.call_route(
                "component/add",
                {"gameObjectPath": target_path, "componentType": component_type},
            )

        return {
            "applied": True,
            "gameObjectPath": target_path,
            "moduleType": module_type,
            "created": created,
            "canvasCount": len(canvas_nodes),
            "duplicateRemovedCount": 0,
            "duplicatePaths": [],
            "moduleAdded": True,
        }

    def _repair_canvas_scalers(self) -> dict[str, Any] | None:
        nodes = self._hierarchy_nodes()
        canvas_nodes = [
            node for node in nodes if "Canvas" in {str(component) for component in (node.get("components") or [])}
        ]
        if not canvas_nodes:
            return None

        target_paths: list[str] = []
        for node in canvas_nodes:
            components = {str(component) for component in (node.get("components") or [])}
            if "CanvasScaler" in components:
                continue
            target_path = self._event_system_target_path(node)
            if target_path:
                target_paths.append(target_path)

        if not target_paths:
            return {
                "applied": False,
                "reason": "All Canvas objects already have CanvasScaler.",
                "updatedCount": 0,
                "updatedPaths": [],
            }

        updated_paths: list[str] = []
        for target_path in target_paths:
            self.bridge.client.call_route(
                "component/add",
                {"gameObjectPath": target_path, "componentType": "CanvasScaler"},
            )
            updated_paths.append(target_path)

        return {
            "applied": bool(updated_paths),
            "updatedCount": len(updated_paths),
            "updatedPaths": updated_paths,
        }

    def _repair_graphic_raycasters(self) -> dict[str, Any] | None:
        nodes = self._hierarchy_nodes()
        canvas_nodes = [
            node for node in nodes if "Canvas" in {str(component) for component in (node.get("components") or [])}
        ]
        if not canvas_nodes:
            return None

        target_paths: list[str] = []
        for node in canvas_nodes:
            components = {str(component) for component in (node.get("components") or [])}
            if "GraphicRaycaster" in components:
                continue
            target_path = self._event_system_target_path(node)
            if target_path:
                target_paths.append(target_path)

        if not target_paths:
            return {
                "applied": False,
                "reason": "All Canvas objects already have GraphicRaycaster.",
                "updatedCount": 0,
                "updatedPaths": [],
            }

        updated_paths: list[str] = []
        for target_path in target_paths:
            self.bridge.client.call_route(
                "component/add",
                {"gameObjectPath": target_path, "componentType": "GraphicRaycaster"},
            )
            updated_paths.append(target_path)

        return {
            "applied": bool(updated_paths),
            "updatedCount": len(updated_paths),
            "updatedPaths": updated_paths,
        }

    def _has_live_unity(self) -> bool:
        is_alive = getattr(self.bridge.client, "is_alive", None)
        if callable(is_alive):
            try:
                return bool(is_alive(timeout=0.2))
            except TypeError:
                try:
                    return bool(is_alive())
                except Exception:
                    return False
            except Exception:
                return False
        ping = getattr(self.bridge.client, "ping", None)
        if callable(ping):
            try:
                ping(timeout=0.2)
                return True
            except TypeError:
                try:
                    ping()
                    return True
                except Exception:
                    return False
            except Exception:
                return False
        return False

    def _capture_after_action(self) -> dict[str, Any]:
        """Take a Game View + Scene View screenshot after a scene-modifying action.

        Returns a dict with ``gamePath`` and ``scenePath`` keys, or empty dict on failure.
        Used to provide visual proof after any action that changes the scene.
        """
        self._invalidate_context_cache()
        try:
            result = self.bridge.client.call_route(
                "graphics/capture",
                {"kind": "both"},
            )
            return dict(result or {})
        except Exception:
            return {}

    def _capture_lines(self, capture: dict[str, Any]) -> list[str]:
        """Format capture paths as display lines for a reply message."""
        lines: list[str] = []
        game_path = capture.get("gamePath") or capture.get("game_path")
        scene_path = capture.get("scenePath") or capture.get("scene_path")
        if game_path:
            lines.append(f"Game view: `{game_path}`")
        if scene_path:
            lines.append(f"Scene view: `{scene_path}`")
        return lines

    def _build_physics_feel_reply(self, text: str) -> str:
        from .skills.physics_feel import audit_physics_feel, propose_physics_feel_tuning

        self._set_status("Auditing physics feel")
        context = self._skill_project_context()
        audit = audit_physics_feel(context)
        proposals = propose_physics_feel_tuning(audit, text)

        self.bridge._pending_physics_feel_audit = audit
        self.bridge._pending_physics_feel_proposals = {
            proposal.action_id: proposal for proposal in proposals
        }

        lines = [f"Physics feel check: score {audit.score}/100", ""]
        if audit.findings:
            lines.append("Diagnosis:")
            for finding in audit.findings[:3]:
                lines.append(f"- {finding.detail}")
            lines.append("")

        lines.append("Three tuning paths:")
        for index, proposal in enumerate(proposals, 1):
            lines.append(f"{index}. {proposal.title}")
            lines.append(f"   {proposal.tradeoff}")
        lines.append("")
        lines.append("Reply `apply 1`, `apply 2`, or `apply 3` to try one.")
        return "\n".join(lines)

    def _resolve_physics_action_id(self, selector: str) -> str | None:
        normalized = str(selector or "").strip().lower()
        mapping = {
            "1": "physics_feel/snappy",
            "snappy": "physics_feel/snappy",
            "2": "physics_feel/controlled",
            "controlled": "physics_feel/controlled",
            "3": "physics_feel/arcade",
            "arcade": "physics_feel/arcade",
        }
        return mapping.get(normalized)

    def _apply_physics_feel_reply(self, selector: str) -> str:
        from .skills.physics_feel import apply_physics_feel, airtime_estimate, floatiness_score

        raw_proposals = getattr(self.bridge, "_pending_physics_feel_proposals", None)
        proposals = raw_proposals if isinstance(raw_proposals, dict) else {}
        audit = getattr(self.bridge, "_pending_physics_feel_audit", None)
        if not proposals:
            return "No pending physics-feel proposal. Ask me to check why the player feels floaty first."

        action_id = self._resolve_physics_action_id(selector)
        if not action_id or action_id not in proposals:
            return "I could not match that physics-feel option. Reply with `apply 1`, `apply 2`, or `apply 3`."

        self._set_status("Applying physics feel tuning")
        action = proposals[action_id]
        outcome = apply_physics_feel(action, self.bridge)
        self.bridge._pending_physics_feel_proposals = None
        self.bridge._pending_physics_feel_audit = None

        if not outcome.applied:
            return f"Physics-feel apply failed: {outcome.error or 'unknown error'}"

        before_score = int(getattr(audit, "score", 0) or 0)
        jump_power = 8.0
        if audit is not None:
            tuning = dict(getattr(audit, "summary", {}).get("tuning") or {})
            try:
                jump_power = float(tuning.get("jumpPower") or 8.0)
            except (TypeError, ValueError):
                jump_power = 8.0
        after_airtime = airtime_estimate(jump_power, float(outcome.after.get("gravity_y") or -9.81))
        after_floatiness = floatiness_score(
            airtime_s=after_airtime,
            drag=float(outcome.after.get("drag") or 0.0),
            gravity_y=float(outcome.after.get("gravity_y") or -9.81),
        )
        after_score = max(0, 100 - after_floatiness)

        lines = [
            f"Applied: {action.title}",
            f"Before: gravity {float(outcome.before.get('gravity_y') or -9.81):.2f}, drag {float(outcome.before.get('drag') or 0.0):.2f}",
            f"After: gravity {float(outcome.after.get('gravity_y') or -9.81):.2f}, drag {float(outcome.after.get('drag') or 0.0):.2f}",
        ]
        if outcome.captures:
            lines.append("Capture: " + ", ".join(f"`{path}`" for path in outcome.captures))
        lines.append(f"Physics-feel score: {before_score} -> {after_score}")
        for note in outcome.notes:
            if note:
                lines.append(f"Note: {note}")
        return "\n".join(lines)

    def _format_improve_project_payload(self, payload: dict[str, Any]) -> str:
        applied_items = list(payload.get("applied") or [])
        skipped_items = list(payload.get("skipped") or [])

        lines = ["Safe project improvement pass finished."]

        if applied_items:
            lines.append("")
            lines.append("Applied:")
            for item in applied_items:
                if isinstance(item, dict):
                    summary = str(item.get("summary") or item.get("message") or item.get("fix") or "").strip()
                else:
                    summary = str(item).strip()
                if summary:
                    lines.append(f"- {summary}")

        if skipped_items:
            lines.append("")
            lines.append("Skipped:")
            for item in skipped_items:
                if isinstance(item, dict):
                    reason = str(item.get("reason") or item.get("message") or item.get("fix") or "").strip()
                else:
                    reason = str(item).strip()
                if reason:
                    lines.append(f"- {reason}")

        baseline_raw = payload.get("baselineScore")
        final_raw = payload.get("finalScore")
        delta_raw = payload.get("scoreDelta")
        try:
            baseline_score = float(baseline_raw) if baseline_raw is not None else None
        except (TypeError, ValueError):
            baseline_score = None
        try:
            final_score = float(final_raw) if final_raw is not None else None
        except (TypeError, ValueError):
            final_score = None
        try:
            score_delta = float(delta_raw) if delta_raw is not None else None
        except (TypeError, ValueError):
            score_delta = None

        if baseline_score is not None and final_score is not None:
            if score_delta is None:
                score_delta = final_score - baseline_score
            lines.append("")
            lines.append(f"Quality score: {baseline_score:.1f} -> {final_score:.1f} ({score_delta:+.1f}).")
        elif final_score is not None:
            lines.append("")
            lines.append(f"Current quality score: {final_score:.1f}.")

        return "\n".join(lines)

    def _render_improve_project_markdown(self, payload: dict[str, Any]) -> str:
        try:
            from ..commands.workflow import _render_improve_project_markdown
        except Exception:
            lines = [
                "## Improve Project",
                "",
                f"- Project root: `{payload.get('projectRoot')}`",
                (
                    f"- Quality score: `{payload.get('baselineScore')} -> {payload.get('finalScore')}` "
                    f"(`{payload.get('scoreDelta')}`)"
                ),
            ]
            return "\n".join(lines) + "\n"
        return _render_improve_project_markdown(payload)

    def _build_improve_project_reply(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized_payload = dict(payload)
        applied_items = list(normalized_payload.get("applied") or [])
        skipped_items = list(normalized_payload.get("skipped") or [])
        normalized_payload.setdefault("projectRoot", str(self.bridge.project_path))
        normalized_payload.setdefault("liveUnityAvailable", self._has_live_unity())
        normalized_payload.setdefault("appliedCount", len(applied_items))
        normalized_payload.setdefault("skippedCount", len(skipped_items))
        if normalized_payload.get("scoreDelta") is None:
            try:
                baseline_score = float(normalized_payload.get("baselineScore"))
                final_score = float(normalized_payload.get("finalScore"))
            except (TypeError, ValueError):
                pass
            else:
                normalized_payload["scoreDelta"] = final_score - baseline_score
        return {
            "content": self._format_improve_project_payload(normalized_payload),
            "metadata": {
                "kind": "improve-project",
                "payload": normalized_payload,
                "markdown": self._render_improve_project_markdown(normalized_payload),
            },
        }

    def _improve_project_reply(self) -> dict[str, Any]:
        if self.embedded_options is not None:
            try:
                self._set_status("Running safe project improvement pass", current=0, total=1)
                payload = self._run_embedded_cli(["workflow", "improve-project", str(self.bridge.project_path)])
                return self._build_improve_project_reply(payload)
            except Exception:
                pass

        applied: list[str] = []
        skipped: list[str] = []
        baseline_score: float | None = None
        final_score: float | None = None
        total_steps = 10 if self.embedded_options is not None else 9

        if self.embedded_options is not None:
            try:
                self._set_status("Scoring project before safe improvements", current=0, total=total_steps)
                baseline_payload = self._run_embedded_cli(["workflow", "quality-score", str(self.bridge.project_path)])
                baseline_raw = baseline_payload.get("overallScore")
                baseline_score = float(baseline_raw) if baseline_raw is not None else None
            except Exception:
                baseline_score = None

        self._set_status("Running safe project improvement pass", current=0, total=total_steps)

        if self._project_has_guidance():
            skipped.append("Guidance already exists.")
        elif self.embedded_options is None:
            skipped.append("Guidance skipped because embedded CLI workflows are unavailable.")
        else:
            payload = self._run_embedded_cli(
                [
                    "workflow",
                    "quality-fix",
                    "--lens",
                    "director",
                    "--fix",
                    "guidance",
                    "--apply",
                    str(self.bridge.project_path),
                ]
            )
            apply_result = dict(payload.get("applyResult") or {})
            if apply_result.get("applied"):
                applied.append("Wrote project guidance files.")
            else:
                skipped.append("Guidance fix was available but did not apply.")

        self._set_status("Running safe project improvement pass", current=1, total=total_steps)
        if self._project_has_sandbox_scene():
            skipped.append("Sandbox scene already exists.")
        elif not self._has_live_unity():
            skipped.append("Sandbox scene skipped because no live Unity session is available.")
        else:
            try:
                result = dict(
                    self.bridge.client.call_route(
                        "scene/create-sandbox",
                        {"saveIfDirty": True, "open": False},
                    )
                )
                if result.get("error"):
                    skipped.append(f"Sandbox scene skipped: {result.get('error')}")
                else:
                    applied.append(f"Created sandbox scene at {result.get('path')}.")
            except Exception as exc:
                skipped.append(f"Sandbox scene skipped: {exc}")

        self._set_status("Running safe project improvement pass", current=2, total=total_steps)
        if not self._has_live_unity():
            skipped.append("Disposable object cleanup skipped because no live Unity session is available.")
        else:
            try:
                disposable_result = self._cleanup_disposable_objects()
                if disposable_result is None:
                    skipped.append("Disposable object cleanup not needed because no probe/demo objects were found.")
                elif disposable_result.get("applied"):
                    removed_paths = list(disposable_result.get("removedPaths") or [])
                    preview = ", ".join(removed_paths[:3])
                    applied.append(
                        f"Removed {disposable_result.get('removedCount')} disposable probe/demo object(s): {preview}."
                    )
                else:
                    skipped.append("Disposable object cleanup did not remove any objects.")
            except Exception as exc:
                skipped.append(f"Disposable object cleanup skipped: {exc}")

        self._set_status("Running safe project improvement pass", current=3, total=total_steps)
        if not self._has_live_unity():
            skipped.append("AudioListener fix skipped because no live Unity session is available.")
        else:
            try:
                audio_result = self._repair_audio_listener_setup()
                if audio_result is None:
                    skipped.append("AudioListener fix not needed because the scene already has one listener.")
                elif audio_result.get("added"):
                    applied.append(f"Added AudioListener to {audio_result.get('keptPath')}.")
                else:
                    applied.append(
                        f"Removed {audio_result.get('removedCount')} extra AudioListener(s) and kept {audio_result.get('keptPath')}."
                    )
            except Exception as exc:
                skipped.append(f"AudioListener fix skipped: {exc}")

        self._set_status("Running safe project improvement pass", current=4, total=total_steps)
        if not self._has_live_unity():
            skipped.append("EventSystem fix skipped because no live Unity session is available.")
        else:
            try:
                event_result = self._repair_event_system_setup()
                if event_result is None:
                    skipped.append("EventSystem fix not needed because no Canvas UI was found.")
                elif event_result.get("applied"):
                    message = (
                        "Repaired scene EventSystem setup"
                        + (
                            f" with {event_result.get('moduleType')}."
                            if event_result.get("moduleType")
                            else "."
                        )
                    )
                    duplicate_removed_count = int(event_result.get("duplicateRemovedCount") or 0)
                    if duplicate_removed_count > 0:
                        duplicate_paths = list(event_result.get("duplicatePaths") or [])
                        preview = ", ".join(duplicate_paths[:3])
                        message += (
                            f" Removed {duplicate_removed_count} duplicate EventSystem object(s): {preview}."
                        )
                    applied.append(message)
                else:
                    skipped.append(str(event_result.get("reason") or "Scene EventSystem already exists."))
            except Exception as exc:
                skipped.append(f"EventSystem fix skipped: {exc}")

        self._set_status("Running safe project improvement pass", current=5, total=total_steps)
        if not self._has_live_unity():
            skipped.append("CanvasScaler fix skipped because no live Unity session is available.")
        else:
            try:
                canvas_scaler_result = self._repair_canvas_scalers()
                if canvas_scaler_result is None:
                    skipped.append("CanvasScaler fix not needed because no Canvas UI was found.")
                elif canvas_scaler_result.get("applied"):
                    updated_paths = list(canvas_scaler_result.get("updatedPaths") or [])
                    preview = ", ".join(updated_paths[:3])
                    applied.append(
                        f"Added CanvasScaler to {canvas_scaler_result.get('updatedCount')} Canvas object(s): {preview}."
                    )
                else:
                    skipped.append(str(canvas_scaler_result.get("reason") or "CanvasScaler fix not needed."))
            except Exception as exc:
                skipped.append(f"CanvasScaler fix skipped: {exc}")

        self._set_status("Running safe project improvement pass", current=6, total=total_steps)
        if not self._has_live_unity():
            skipped.append("GraphicRaycaster fix skipped because no live Unity session is available.")
        else:
            try:
                graphic_raycaster_result = self._repair_graphic_raycasters()
                if graphic_raycaster_result is None:
                    skipped.append("GraphicRaycaster fix not needed because no Canvas UI was found.")
                elif graphic_raycaster_result.get("applied"):
                    updated_paths = list(graphic_raycaster_result.get("updatedPaths") or [])
                    preview = ", ".join(updated_paths[:3])
                    applied.append(
                        f"Added GraphicRaycaster to {graphic_raycaster_result.get('updatedCount')} Canvas object(s): {preview}."
                    )
                else:
                    skipped.append(
                        str(graphic_raycaster_result.get("reason") or "GraphicRaycaster fix not needed.")
                    )
            except Exception as exc:
                skipped.append(f"GraphicRaycaster fix skipped: {exc}")

        self._set_status("Running safe project improvement pass", current=7, total=total_steps)
        if not self._has_live_unity():
            skipped.append("CharacterController fix skipped because no live Unity session is available.")
        else:
            try:
                controller_result = self._repair_player_character_controller()
                if controller_result is None:
                    skipped.append(
                        "CharacterController fix not needed because no clear likely player object without a movement body was found."
                    )
                elif controller_result.get("applied"):
                    applied.append(f"Added CharacterController to {controller_result.get('targetPath')}.")
                else:
                    skipped.append(
                        str(
                            controller_result.get("reason")
                            or "CharacterController fix skipped because the scene was ambiguous."
                        )
                    )
            except Exception as exc:
                skipped.append(f"CharacterController fix skipped: {exc}")

        self._set_status("Running safe project improvement pass", current=8, total=total_steps)
        if self._project_has_tests():
            skipped.append("Tests already exist.")
        elif not self._project_has_test_framework():
            skipped.append("Test scaffold skipped because com.unity.test-framework is not installed.")
        elif self.embedded_options is None:
            skipped.append("Test scaffold skipped because embedded CLI workflows are unavailable.")
        else:
            payload = self._run_embedded_cli(
                [
                    "workflow",
                    "quality-fix",
                    "--lens",
                    "director",
                    "--fix",
                    "test-scaffold",
                    "--apply",
                    str(self.bridge.project_path),
                ]
            )
            apply_result = dict(payload.get("applyResult") or {})
            if apply_result.get("applied"):
                applied.append("Wrote EditMode smoke-test scaffold.")
            else:
                skipped.append("Test scaffold fix was available but did not apply.")

        lines = ["Safe project improvement pass finished."]
        if applied:
            lines.append("")
            lines.append("Applied:")
            lines.extend(f"- {item}" for item in applied)
        if skipped:
            lines.append("")
            lines.append("Skipped:")
            lines.extend(f"- {item}" for item in skipped)
        if self.embedded_options is not None:
            try:
                self._set_status("Scoring project after safe improvements", current=9, total=total_steps)
                score_payload = self._run_embedded_cli(["workflow", "quality-score", str(self.bridge.project_path)])
                score_raw = score_payload.get("overallScore")
                final_score = float(score_raw) if score_raw is not None else None
                lines.append("")
                if baseline_score is not None and final_score is not None:
                    delta = final_score - baseline_score
                    lines.append(f"Quality score: {baseline_score:.1f} -> {final_score:.1f} ({delta:+.1f}).")
                elif final_score is not None:
                    lines.append(f"Current quality score: {final_score:.1f}.")
            except Exception:
                pass
        payload = {
            "projectRoot": str(self.bridge.project_path),
            "liveUnityAvailable": self._has_live_unity(),
            "baselineScore": baseline_score,
            "finalScore": final_score,
            "scoreDelta": (final_score - baseline_score) if baseline_score is not None and final_score is not None else None,
            "appliedCount": len(applied),
            "skippedCount": len(skipped),
            "applied": [{"summary": item} for item in applied],
            "skipped": [{"reason": item} for item in skipped],
        }
        return self._build_improve_project_reply(payload)

    def _create_primitive_reply(self, primitive_name: str, original_text: str) -> str:
        primitive = primitive_name.capitalize()
        params: dict[str, Any] = {"name": primitive, "primitiveType": primitive}
        position_match = self._POSITION_RE.search(original_text)
        if position_match:
            params["position"] = {
                "x": float(position_match.group(1)),
                "y": float(position_match.group(2)),
                "z": float(position_match.group(3)),
            }
        self._set_status(f"Creating {primitive}")
        loop = AgentLoop(self.bridge.client, max_retries=1, status_path=self.bridge._status_path)
        results = loop.execute(
            [
                {
                    "step": 1,
                    "description": f"Create {primitive}",
                    "route": "gameobject/create",
                    "params": params,
                    "onError": "abort",
                }
            ]
        )
        summary = format_results(results, color=False)
        if results and results[0].status == "ok":
            created = dict(results[0].result or {})
            return (
                f"Created {primitive} `{created.get('name') or primitive}`.\n\n"
                f"{summary}"
            )
        return f"Could not create {primitive}.\n\n{summary}"

    # -- Task 2: Player prototype flow ----------------------------------------

    def _build_player_prototype_reply(self, name: str = "Player") -> str:
        """Build a player GO with CharacterController + movement script in one flow."""
        self._set_status("Creating player GameObject")
        steps_done: list[str] = []
        errors: list[str] = []

        try:
            self.bridge.client.call_route("gameobject/create", {"name": name})
            steps_done.append(f"Created GameObject `{name}`")
        except Exception as exc:
            errors.append(f"Could not create GameObject: {exc}")
            return "\n".join(errors) + "\n\nMake sure a Unity editor is connected."

        self._set_status("Adding CharacterController")
        try:
            self.bridge.client.call_route(
                "component/add",
                {"gameObjectName": name, "componentType": "UnityEngine.CharacterController"},
            )
            steps_done.append("Added `CharacterController`")
        except Exception as exc:
            errors.append(f"CharacterController: {exc}")

        self._set_status("Creating PlayerMovement script")
        script_path = "Assets/Scripts/PlayerMovement.cs"
        try:
            result = self._run_embedded_cli([
                "script", "create",
                "--name", "PlayerMovement",
                "--path", script_path,
                "--content", self._MOVEMENT_SCRIPT_TEMPLATE,
            ])
            actual_path = (result or {}).get("path") or script_path
            steps_done.append(f"Created `{actual_path}`")
        except Exception as exc:
            errors.append(f"Script creation: {exc}")

        self._set_status("Attaching PlayerMovement to GameObject")
        try:
            self.bridge.client.call_route(
                "component/add",
                {"gameObjectName": name, "componentType": "PlayerMovement"},
            )
            steps_done.append("Attached `PlayerMovement` to GameObject")
        except Exception as exc:
            errors.append(f"Script attach: {exc}")

        self._set_status("Capturing scene")
        capture = self._capture_after_action()
        capture_lines = self._capture_lines(capture)

        lines = [f"Built player prototype `{name}`:", ""] + steps_done
        if errors:
            lines += [""] + errors
        if capture_lines:
            lines += [""] + capture_lines
        lines += [
            "",
            "Next: press Play and test movement with WASD + Space.",
            "Ask me to adjust speed, add a camera follow, or write tests for the controller.",
        ]
        return "\n".join(lines)

    # -- Task 3: Script create+attach flow ------------------------------------

    def _build_script_attach_reply(
        self,
        script_name: str,
        go_name: str,
        description: str = "",
    ) -> str:
        """Create a C# script and attach it to a named GameObject."""
        self._set_status(f"Creating {script_name}.cs")
        steps_done: list[str] = []
        errors: list[str] = []
        script_path = f"Assets/Scripts/{script_name}.cs"

        comment = f"// {description}" if description else "// TODO: implement"
        script_content = (
            f"using UnityEngine;\n\n"
            f"public class {script_name} : MonoBehaviour\n{{\n"
            f"    {comment}\n"
            f"    private void Start() {{ }}\n"
            f"    private void Update() {{ }}\n"
            f"}}\n"
        )

        try:
            result = self._run_embedded_cli([
                "script", "create",
                "--name", script_name,
                "--path", script_path,
                "--content", script_content,
            ])
            actual_path = (result or {}).get("path") or script_path
            steps_done.append(f"Created `{actual_path}`")
        except Exception as exc:
            errors.append(f"Script creation failed: {exc}")
            return "\n".join(errors)

        self._set_status(f"Attaching {script_name} to {go_name}")
        try:
            self.bridge.client.call_route(
                "component/add",
                {"gameObjectName": go_name, "componentType": script_name},
            )
            steps_done.append(f"Attached `{script_name}` to `{go_name}`")
        except Exception as exc:
            errors.append(f"Attach failed: {exc}")

        capture = self._capture_after_action()
        capture_lines = self._capture_lines(capture)

        lines = [f"Created and attached `{script_name}` to `{go_name}`:", ""] + steps_done
        if errors:
            lines += [""] + errors
        if capture_lines:
            lines += [""] + capture_lines
        lines += ["", f"Open `{script_path}` to implement the logic."]
        return "\n".join(lines)

    # -- Task 5: Autonomous goal mode -----------------------------------------

    def _autonomous_goal_reply(self, goal: str) -> str:
        """Autonomous mode: audit state, build a plan, ask for confirmation."""
        self._set_status("Auditing project for goal planning")

        try:
            score_result = self._run_embedded_cli(["--json", "workflow", "quality-score"])
        except Exception as exc:
            return (
                f"I couldn't audit the project to build a plan: {exc}\n\n"
                "Make sure Unity is connected and try again."
            )

        lens_scores = (score_result or {}).get("lensScores") or []
        all_findings: list[dict[str, Any]] = []
        for lens in lens_scores:
            for finding in (lens.get("findings") or []):
                all_findings.append({**finding, "_lens": lens.get("name", "")})

        if not all_findings:
            return (
                f"I ran an audit for goal: **{goal}**\n\n"
                "Good news: no actionable issues right now. "
                "The project looks healthy."
            )

        severity_rank = {"error": 0, "warning": 1, "info": 2}
        all_findings.sort(key=lambda f: severity_rank.get(str(f.get("severity") or "info"), 2))
        plan_steps = all_findings[:5]

        lines = [f"Goal: **{goal}**", "", "Here's my plan based on the current audit:", ""]
        for i, finding in enumerate(plan_steps, 1):
            title = str(finding.get("title") or "Fix")
            detail = str(finding.get("detail") or "")
            severity = str(finding.get("severity") or "info")
            icon = "error" if severity == "error" else "warning" if severity == "warning" else "info"
            lines.append(f"{i}. [{icon}] **{title}**" + (f" -- {detail}" if detail else ""))

        lines += [
            "",
            "Reply **yes** or **go** and I'll execute these steps one by one.",
        ]

        self.bridge._pending_autonomous_plan = plan_steps
        self.bridge._pending_autonomous_goal = goal

        return "\n".join(lines)

    def _execute_pending_autonomous_plan(self) -> str:
        """Execute the pending autonomous plan step by step."""
        plan = getattr(self.bridge, "_pending_autonomous_plan", [])
        goal = getattr(self.bridge, "_pending_autonomous_goal", "your goal")

        if not plan:
            return "No pending plan to execute. Try stating your goal again."

        self.bridge._pending_autonomous_plan = None
        self.bridge._pending_autonomous_goal = None

        self._set_status("Executing plan")
        results_lines = [f"Executing plan for: **{goal}**", ""]

        for i, finding in enumerate(plan, 1):
            title = str(finding.get("title") or "Fix")
            lens = str(finding.get("_lens") or "systems")
            self._set_status(f"Step {i}: {title}")
            try:
                fix_result = self._run_embedded_cli([
                    "--json", "workflow", "quality-fix",
                    "--lens", lens,
                    "--fix", title.lower().replace(" ", "-"),
                    "--apply",
                ])
                success = (fix_result or {}).get("applied") or (fix_result or {}).get("success")
                if success:
                    results_lines.append(f"Step {i}: {title} -- done")
                else:
                    skip_reason = (fix_result or {}).get("skippedReason") or "not applicable"
                    results_lines.append(f"Step {i}: {title} -- skipped ({skip_reason})")
            except Exception as exc:
                results_lines.append(f"Step {i}: {title} -- {exc}")

        capture = self._capture_after_action()
        capture_lines = self._capture_lines(capture)
        if capture_lines:
            results_lines += [""] + capture_lines
        results_lines += ["", "Done. Ask me to audit again to see the score delta."]
        return "\n".join(results_lines)

    def _best_effort_agent_reply(self, content: str) -> str:
        provider = self._configured_model_provider()
        if not provider:
            return (
                "This request needs a configured model provider. The Unity Agent tab can still run bounded commands "
                "like `improve project`, `inspect project`, `benchmark`, `compile errors`, and basic scene actions, "
                "but open-ended chat is disabled until `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY` "
                "is available in the bridge process. OpenRouter is recommended — one key, any model."
            )
        planned = self._try_model_backed_plan(content)
        if planned:
            return planned
        return (
            f"{provider} is configured, but I could not turn that request into a safe executable Unity plan.\n\n"
            "Try asking for a concrete outcome such as:\n"
            "- create a player controller for the active scene\n"
            "- add a reticle canvas and event system\n"
            "- create a sandbox scene and save it\n\n"
            "If this should have been understood, the next thing to inspect is the live project context being fed to the planner."
        )

    def _try_model_backed_plan(self, content: str) -> str | None:
        try:
            from ..commands.agent_loop_cmd import _generate_plan_from_intent
        except Exception:
            return None
        if not self._configured_model_provider():
            return None
        self._set_status("Planning task with model")
        steps = _generate_plan_from_intent(
            content,
            model=self._selected_model(),
            context_prompt=self._model_context_prompt(),
            history=self._recent_history(),
        )
        if not isinstance(steps, list) or not steps:
            return None
        loop = AgentLoop(self.bridge.client, max_retries=1, status_path=self.bridge._status_path)
        results = loop.execute(steps)
        self._invalidate_context_cache()
        return (
            f"I planned {len(steps)} step(s) and executed them.\n\n"
            f"{format_results(results, color=False)}"
        )


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
        embedded_options: "EmbeddedCLIOptions | None" = None,
        poll_interval: float = 0.25,
        watchdog_interval: float = 60.0,  # check project health every 60 seconds
    ) -> None:
        self.project_path = Path(project_path)
        self.client = file_client
        self._assistant = _OfflineUnityAssistant(self, embedded_options=embedded_options)
        self.handler = handler or self._assistant.handle_message
        self.poll_interval = poll_interval

        self._umcp = self.project_path / ".umcp"
        self._chat_dir = self._umcp / "chat"
        self._inbox_dir = self._chat_dir / "user-inbox"
        self._legacy_inbox = self._chat_dir / "user-inbox.json"
        self._history_path = self._chat_dir / "history.json"
        self._status_path = self._umcp / "agent-status.json"
        self._project_env_path = self._umcp / "agent.env"

        self._history: List[Dict[str, Any]] = []
        self._context = ContextInjector(file_client)
        self._running = False
        self._status_state = "idle"
        self._status_current = 0
        self._status_total = 0
        self._status_action = ""
        self._last_status_write = 0.0
        self._status_heartbeat_interval = 2.0

        # Watchdog state
        self._watchdog_interval: float = watchdog_interval
        self._watchdog_thread: threading.Thread | None = None
        self._watchdog_running = False
        self._watchdog_surfaced: set[str] = set()  # finding titles already shown this session
        self._project_env_mtime: float = 0.0
        self._project_env_loaded_keys = self._load_project_env()

    # ── Public API ────────────────────────────────────────────────────────

    def _check_single_instance(self) -> bool:
        """Return True if this process may run; False if another bridge is already live."""
        try:
            if not self._status_path.exists():
                return True
            raw = self._status_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            other_pid = int(data.get("pid") or 0)
            if other_pid == os.getpid():
                return True
            # Check staleness — if status is > 10 s old the other process is gone.
            last_mtime = self._status_path.stat().st_mtime
            if (time.time() - last_mtime) > 10.0:
                return True
            # Try to see if that PID is actually running.
            try:
                os.kill(other_pid, 0)  # signal 0 = existence check, no-op on Windows
                is_running = True
            except (OSError, SystemError):
                is_running = False
            return not is_running
        except Exception:
            return True

    def run(self) -> None:
        """Block and process messages until stopped."""
        if not self._check_single_instance():
            import sys
            pid_hint = ""
            try:
                data = json.loads(self._status_path.read_text(encoding="utf-8"))
                pid_hint = f" (PID {data.get('pid', '?')})"
            except Exception:
                pass
            print(
                f"[agent-chat] Another bridge is already running{pid_hint}. "
                "Stop it first or wait for it to become stale.",
                file=sys.stderr,
            )
            return
        self._running = True
        self._ensure_ready()
        if self._watchdog_interval > 0:
            self._start_watchdog()

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
        self._stop_watchdog()

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
        metadata: Dict[str, Any] | None = None,
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
        if metadata:
            entry["metadata"] = metadata
        self._history.append(entry)
        self._write_history()

    def write_status(self, state: str, current: int, total: int, action: str) -> None:
        self._status_state = state
        self._status_current = current
        self._status_total = total
        self._status_action = action
        self._write_status(state, current, total, action)

    def _watchdog_filter_new(self, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return only findings not already surfaced this session."""
        new: list[dict[str, Any]] = []
        for finding in findings:
            key = str(finding.get("title") or "")
            if key and key not in self._watchdog_surfaced:
                new.append(finding)
        return new

    def _watchdog_surface_findings(self, findings: list[dict[str, Any]]) -> None:
        """Post proactive message for new findings, mark them as surfaced."""
        if not findings:
            return
        lines = ["I noticed a few things while watching your project:", ""]
        for finding in findings[:3]:  # cap at 3 to avoid noise
            title = str(finding.get("title") or "Finding")
            detail = str(finding.get("detail") or "")
            severity = str(finding.get("severity") or "info")
            icon = "warning" if severity == "warning" else "error" if severity == "error" else "info"
            lines.append(f"[{icon}] **{title}**" + (f": {detail}" if detail else ""))
            self._watchdog_surfaced.add(title)
        lines += ["", "Ask me to fix any of these or run `inspect project` for the full picture."]
        self.append_message("ai", "\n".join(lines))

    def _watchdog_loop(self) -> None:
        """Background thread: periodically run a lightweight project health check."""
        while self._watchdog_running:
            time.sleep(self._watchdog_interval)
            if not self._watchdog_running:
                break
            try:
                result = self._assistant._run_embedded_cli(["--json", "workflow", "quality-score"])
                findings = (result or {}).get("findings") or []
                new_findings = self._watchdog_filter_new(findings)
                self._watchdog_surface_findings(new_findings)
            except Exception:
                pass  # watchdog never crashes the bridge

    def _start_watchdog(self) -> None:
        """Start the background watchdog thread."""
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            return
        self._watchdog_running = True
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
            name="unity-mcp-watchdog",
        )
        self._watchdog_thread.start()

    def _stop_watchdog(self) -> None:
        """Stop the watchdog thread (signals it to exit; does not null the ref)."""
        self._watchdog_running = False
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=2.0)

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

    def _load_project_env(self) -> set[str]:
        loaded: set[str] = set()
        parsed = _parse_project_env_file(self._project_env_path)
        for key in _PROJECT_ENV_KEYS:
            value = parsed.get(key)
            if not value or os.environ.get(key):
                continue
            os.environ[key] = value
            loaded.add(key)
        self._project_env_mtime: float = (
            self._project_env_path.stat().st_mtime
            if self._project_env_path.exists() else 0.0
        )
        return loaded

    def _reload_project_env_if_changed(self) -> None:
        """Re-read agent.env when its mtime changes (e.g. user saved a new API key)."""
        try:
            mtime = (
                self._project_env_path.stat().st_mtime
                if self._project_env_path.exists() else 0.0
            )
        except Exception:
            return
        if mtime <= self._project_env_mtime:
            return
        # File changed — reload all keys, overwriting even previously set values.
        parsed = _parse_project_env_file(self._project_env_path)
        loaded: set[str] = set()
        for key in _PROJECT_ENV_KEYS:
            value = parsed.get(key)
            if not value:
                continue
            os.environ[key] = value
            loaded.add(key)
        self._project_env_loaded_keys = loaded
        self._project_env_mtime = mtime

    def _llm_config_source(self, llm_provider: str | None) -> str | None:
        if llm_provider == "OpenAI":
            if "OPENAI_API_KEY" in self._project_env_loaded_keys:
                return ".umcp/agent.env"
            if os.environ.get("OPENAI_API_KEY"):
                return "environment"
        if llm_provider == "Anthropic":
            if "ANTHROPIC_API_KEY" in self._project_env_loaded_keys:
                return ".umcp/agent.env"
            if os.environ.get("ANTHROPIC_API_KEY"):
                return "environment"
        if llm_provider == "OpenRouter":
            if "OPENROUTER_API_KEY" in self._project_env_loaded_keys:
                return ".umcp/agent.env"
            if os.environ.get("OPENROUTER_API_KEY"):
                return "environment"
        return None

    def _write_status(self, state: str, current: int, total: int, action: str) -> None:
        try:
            self._reload_project_env_if_changed()
            self._status_path.parent.mkdir(parents=True, exist_ok=True)
            llm_provider = self._assistant._configured_model_provider()
            llm_model = self._assistant._selected_model() if llm_provider else None
            llm_config_source = self._llm_config_source(llm_provider)
            payload = {
                "state": state,
                "currentStep": current,
                "totalSteps": total,
                "currentAction": action,
                "pid": os.getpid(),
                "projectPath": str(self.project_path),
                "llmAvailable": bool(llm_provider),
                "llmProvider": llm_provider,
                "llmModel": llm_model,
                "llmConfigSource": llm_config_source,
                "lastUpdated": datetime.now(timezone.utc).isoformat(),
            }
            tmp = self._status_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._status_path)
            self._last_status_write = time.monotonic()
        except Exception:
            pass
