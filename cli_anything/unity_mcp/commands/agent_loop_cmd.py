"""agent_loop_cmd.py — `workflow agent-loop` Click command.

Registered into the workflow_group from workflow.py via:
    from .agent_loop_cmd import agent_loop_command
    workflow_group.add_command(agent_loop_command)
"""
from __future__ import annotations

import json as _json
import os
import urllib.request
from pathlib import Path
from typing import Any

import click


@click.command("agent-loop")
@click.option("--intent", "-i", default=None,
              help="Natural language intent (generates plan via AI, requires ANTHROPIC_API_KEY or OPENAI_API_KEY).")
@click.option("--plan-file", "-f", type=click.Path(exists=True, path_type=Path), default=None,
              help="JSON file containing a pre-built plan array.")
@click.option("--plan-json", default=None,
              help="Inline JSON plan string.")
@click.option("--dry-run", is_flag=True,
              help="Print the plan without executing it.")
@click.option("--max-retries", type=int, default=1, show_default=True,
              help="Retries per failing step.")
@click.option("--model", default=None,
              help="AI model for plan generation (e.g. claude-haiku-4-5-20251001 or gpt-4o-mini).")
@click.pass_context
def agent_loop_command(
    ctx: click.Context,
    intent: str | None,
    plan_file: Path | None,
    plan_json: str | None,
    dry_run: bool,
    max_retries: int,
    model: str | None,
) -> None:
    """Execute a multi-step Unity plan autonomously via File IPC.

    \b
    Examples:
      workflow agent-loop --intent "Create a red cube at origin"
      workflow agent-loop --plan-file my_plan.json
      workflow agent-loop --intent "Set up FPS player" --dry-run
    """
    from ..core.agent_loop import AgentLoop, format_results

    obj = ctx.obj

    # ── Resolve plan ──────────────────────────────────────────────────────
    steps: list | None = None

    if plan_file:
        steps = _json.loads(plan_file.read_text(encoding="utf-8"))
    elif plan_json:
        steps = _json.loads(plan_json)
    elif intent:
        click.echo(f"Generating plan for: {intent!r} ...")
        steps = _generate_plan_from_intent(intent, model=model)
        if steps is None:
            raise click.ClickException(
                "Failed to generate plan. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."
            )
    else:
        raise click.UsageError("Provide --intent, --plan-file, or --plan-json.")

    if not isinstance(steps, list) or not steps:
        raise click.ClickException("Plan must be a non-empty JSON array.")

    # ── Print plan ────────────────────────────────────────────────────────
    click.echo(f"\nPlan ({len(steps)} steps):")
    for s in steps:
        num  = s.get("step", "?")
        desc = s.get("description", s.get("route", ""))
        route = s.get("route", "")
        click.echo(f"  [{num}] {desc}  ({route})")
    click.echo()

    if dry_run:
        click.echo("(dry-run — not executing)")
        return

    # ── Get File IPC client ───────────────────────────────────────────────
    file_client = _resolve_file_ipc_client(obj.backend)

    # ── Status file path ──────────────────────────────────────────────────
    status_path: Path | None = None
    try:
        status_path = Path(file_client.project_path) / ".umcp" / "agent-status.json"
    except Exception:
        pass

    # ── Execute ───────────────────────────────────────────────────────────
    def _on_progress(step_num: int, total: int, description: str) -> None:
        click.echo(f"  [{step_num}/{total}] {description}...", nl=False)

    def _on_step(step_num: int, description: str, result: object) -> None:
        click.echo(" \u2713")

    def _on_error(step_num: int, description: str, error: str) -> None:
        click.echo(f" \u2717\n        Error: {error}")

    loop = AgentLoop(
        client=file_client,
        on_step=_on_step,
        on_error=_on_error,
        on_progress=_on_progress,
        max_retries=max_retries,
        status_path=status_path,
    )

    results = loop.execute(steps)
    click.echo(format_results(results))

    if obj.json_output:
        import dataclasses
        click.echo(_json.dumps([dataclasses.asdict(r) for r in results], indent=2))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_file_ipc_client(backend: Any) -> Any:
    """Extract or discover a FileIPCClient from the backend."""
    from ..core.file_ipc import FileIPCClient

    # Backend may already know how to resolve the selected file IPC client.
    resolver = getattr(backend, "_resolve_file_ipc_client", None)
    if callable(resolver):
        client = resolver()
        if client is not None:
            return client

    # Legacy single-client field
    if hasattr(backend, "_file_ipc_client") and backend._file_ipc_client is not None:
        return backend._file_ipc_client

    # Try session store
    if hasattr(backend, "session_store"):
        session = backend.session_store.load()
        selected_instance = getattr(session, "selected_instance", None) or {}
        project_path = (
            selected_instance.get("projectPath")
            or selected_instance.get("project_path")
            or
            getattr(session, "selectedProjectPath", None)
            or getattr(session, "projectPath", None)
        )
        if project_path:
            get_client = getattr(backend, "_get_file_ipc_client", None)
            client = get_client(project_path) if callable(get_client) else FileIPCClient(project_path)
            if client.is_alive():
                return client

    # Walk up from cwd looking for .umcp/ping.json
    cwd = Path(os.getcwd()).resolve()
    candidates = [cwd] + list(cwd.parents)[:4]
    for candidate in candidates:
        if (candidate / ".umcp" / "ping.json").exists():
            client = FileIPCClient(candidate)
            if client.is_alive():
                return client

    raise RuntimeError(
        "Could not find a running Unity project with File IPC. "
        "Make sure FileIPCBridge.cs is in Assets/Editor/ and Unity is open."
    )


_PLAN_SYSTEM_PROMPT = """You are a Unity AI developer assistant. Convert the user's intent into a JSON plan array.

Each step:
  { "step": N, "description": "...", "route": "route/name", "params": {...}, "onError": "abort"|"continue" }

Available routes:
  gameobject/create     (name, primitiveType[Cube|Sphere|Capsule|Cylinder|Plane|Quad|Empty], parent, position{x,y,z})
  gameobject/delete     (name)
  gameobject/duplicate  (gameObject, name)
  gameobject/rename     (gameObject, name)
  gameobject/set-transform (name, position{x,y,z}, rotation{x,y,z}, scale{x,y,z})
  gameobject/set-tag    (gameObject, tag)
  gameobject/set-layer  (gameObject, layerName)
  component/add         (gameObject, component)
  component/remove      (gameObject, component)
  component/set-property (gameObject, component, property, value)
  component/wire-reference (gameObject, component, field, target)
  script/create         (name, folder, content)
  script/update         (path, content)
  material/create       (name, folder, shader)
  material/set-property (path, property, color{r,g,b,a} | value | texture)
  material/assign       (gameObject, material, slot)
  prefab/save           (gameObject, path, overwrite)
  prefab/instantiate    (path, name, parent, position{x,y,z})
  physics/set-rigidbody (gameObject, mass, isKinematic, useGravity)
  physics/set-collider  (gameObject, type[box|sphere|capsule], isTrigger, radius, height)
  lighting/set-sun      (intensity, color{r,g,b}, rotation{x,y,z})
  lighting/set-ambient  (color{r,g,b}, intensity)
  asset/create-folder   (path)
  tag/add               (tag)
  layer/add             (layer)
  scene/save            ()
  editor/play-mode      (action[play|stop|pause])

Return ONLY a valid JSON array, no prose, no markdown code fences."""


def _generate_plan_from_intent(intent: str, *, model: str | None) -> list | None:
    """Call an AI API to convert intent to a plan. Returns None if unavailable."""
    messages = [{"role": "user", "content": f"Intent: {intent}"}]

    # Try Anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        try:
            payload = _json.dumps({
                "model": model or "claude-haiku-4-5-20251001",
                "max_tokens": 2048,
                "system": _PLAN_SYSTEM_PROMPT,
                "messages": messages,
            }).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=payload,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = _json.loads(resp.read())
            text = data["content"][0]["text"].strip()
            if text.startswith("```"):
                text = text.split("```", 2)[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.rsplit("```", 1)[0].strip()
            return _json.loads(text)
        except Exception:
            pass

    # Try OpenAI
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if api_key:
        try:
            payload = _json.dumps({
                "model": model or "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": _PLAN_SYSTEM_PROMPT},
                    *messages,
                ],
                "max_tokens": 2048,
            }).encode()
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "content-type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = _json.loads(resp.read())
            text = data["choices"][0]["message"]["content"].strip()
            if text.startswith("```"):
                text = text.split("```", 2)[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.rsplit("```", 1)[0].strip()
            parsed = _json.loads(text)
            if isinstance(parsed, dict) and "steps" in parsed:
                return parsed["steps"]
            return parsed
        except Exception:
            pass

    return None
