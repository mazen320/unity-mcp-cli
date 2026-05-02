"""agent_loop.py — Multi-step agentic execution engine for Unity via File IPC.

Usage
-----
    from .agent_loop import AgentLoop, PlanStep

    loop = AgentLoop(client, on_step=lambda n, d, r: print(f"[{n}] {d}"))
    results = loop.execute(steps)

Plan schema (list of PlanStep dicts)
-------------------------------------
    [
      {
        "step": 1,
        "description": "Create PlayerController script",
        "route": "script/create",
        "params": {"name": "PlayerController", "folder": "Assets/Scripts/Player", "content": "..."},
        "expect": {"success": True},       # optional — keys that must be in result
        "onError": "abort",                # "abort" | "continue" (default: continue)
        "dependsOn": []                    # step numbers that must have succeeded first
      },
      ...
    ]
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .file_ipc import FileIPCClient, FileIPCError


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PlanStep:
    step: int
    description: str
    route: str
    params: Dict[str, Any] = field(default_factory=dict)
    expect: Dict[str, Any] = field(default_factory=dict)
    on_error: str = "continue"   # "abort" | "continue"
    depends_on: List[int] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any], index: int = 0) -> "PlanStep":
        return cls(
            step=int(d.get("step", index + 1)),
            description=str(d.get("description", d.get("route", ""))),
            route=str(d.get("route", "")),
            params=d.get("params") or {},
            expect=d.get("expect") or {},
            on_error=str(d.get("onError", d.get("on_error", "continue"))).lower(),
            depends_on=[int(x) for x in (d.get("dependsOn") or d.get("depends_on") or [])],
        )


@dataclass
class StepResult:
    step: int
    description: str
    status: str          # "ok" | "error" | "skipped"
    result: Any = None
    error: str = ""
    duration_ms: float = 0.0


# ── AgentLoop ─────────────────────────────────────────────────────────────────

class AgentLoop:
    """Executes a multi-step plan against Unity via File IPC.

    Parameters
    ----------
    client:
        A connected ``FileIPCClient``.
    on_step:
        Optional callback called after each successful step.
        Signature: ``(step_num: int, description: str, result: Any) -> None``
    on_error:
        Optional callback called after each failed step.
        Signature: ``(step_num: int, description: str, error: str) -> None``
    on_progress:
        Optional callback called before each step starts.
        Signature: ``(step_num: int, total: int, description: str) -> None``
    max_retries:
        How many times to retry a failing step before giving up.
    retry_delay:
        Seconds to wait between retries.
    status_path:
        If set, write live agent-status JSON to this path so the Unity
        EditorWindow can display progress in real-time.
    """

    def __init__(
        self,
        client: FileIPCClient,
        on_step: Optional[Callable[[int, str, Any], None]] = None,
        on_error: Optional[Callable[[int, str, str], None]] = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        max_retries: int = 1,
        retry_delay: float = 0.5,
        status_path: Optional[Path] = None,
    ) -> None:
        self.client = client
        self.on_step = on_step
        self.on_error = on_error
        self.on_progress = on_progress
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.status_path = status_path

    # ── Public API ────────────────────────────────────────────────────────

    def execute(self, steps: List[Dict[str, Any] | PlanStep]) -> List[StepResult]:
        """Execute *steps* in order, respecting dependencies and error policy."""
        parsed = [
            s if isinstance(s, PlanStep) else PlanStep.from_dict(s, i)
            for i, s in enumerate(steps)
        ]
        total = len(parsed)
        completed: set[int] = set()
        failed: set[int] = set()
        results: List[StepResult] = []
        aborted = False

        for step in parsed:
            if aborted:
                results.append(StepResult(
                    step=step.step, description=step.description,
                    status="skipped", error="aborted by prior step"
                ))
                continue

            # Dependency check
            unmet = [d for d in step.depends_on if d not in completed]
            if unmet:
                results.append(StepResult(
                    step=step.step, description=step.description,
                    status="skipped",
                    error=f"dependencies not met: {unmet}"
                ))
                continue

            if self.on_progress:
                self.on_progress(step.step, total, step.description)
            self._write_status("executing", step.step, total, step.description)

            result = self._execute_step(step)
            results.append(result)

            if result.status == "ok":
                completed.add(step.step)
                if self.on_step:
                    self.on_step(step.step, step.description, result.result)
            else:
                failed.add(step.step)
                if self.on_error:
                    self.on_error(step.step, step.description, result.error)
                if step.on_error == "abort":
                    aborted = True

        self._write_status("done", total, total, "")
        return results

    def execute_from_json(self, plan_json: str) -> List[StepResult]:
        """Parse a JSON plan string and execute it."""
        steps = json.loads(plan_json)
        if not isinstance(steps, list):
            raise ValueError("Plan must be a JSON array of step objects")
        return self.execute(steps)

    # ── Internal ──────────────────────────────────────────────────────────

    def _execute_step(self, step: PlanStep) -> StepResult:
        last_error = ""
        for attempt in range(self.max_retries + 1):
            t0 = time.monotonic()
            try:
                result = self.client.call_route(step.route, step.params)
                duration_ms = (time.monotonic() - t0) * 1000

                # Validate expectations
                if step.expect:
                    for key, expected in step.expect.items():
                        actual = result.get(key) if isinstance(result, dict) else None
                        if actual != expected:
                            raise AssertionError(
                                f"Expected {key}={expected!r} but got {actual!r}"
                            )

                # Check Unity-side error in result
                if isinstance(result, dict) and result.get("error"):
                    raise FileIPCError(str(result["error"]))

                if step.route in {"script/create", "script/update"}:
                    self._wait_for_unity_compilation()

                if step.route == "scene/new":
                    result = self._verify_scene_new(step, result)

                return StepResult(
                    step=step.step,
                    description=step.description,
                    status="ok",
                    result=result,
                    duration_ms=duration_ms,
                )
            except (FileIPCError, AssertionError, Exception) as exc:
                last_error = str(exc)
                if attempt < self.max_retries:
                    if step.route == "component/add" and self._looks_like_component_compile_race(last_error):
                        self._wait_for_unity_compilation()
                    time.sleep(self.retry_delay)

        return StepResult(
            step=step.step,
            description=step.description,
            status="error",
            error=last_error,
        )

    def _write_status(self, state: str, current: int, total: int, action: str) -> None:
        if not self.status_path:
            return
        try:
            import datetime
            payload = {
                "state": state,
                "currentStep": current,
                "totalSteps": total,
                "currentAction": action,
                "lastUpdated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            tmp = self.status_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.status_path)
        except Exception:
            pass

    def _wait_for_unity_compilation(self, *, timeout: float = 25.0, interval: float = 0.25) -> None:
        """Wait for Unity to finish script compilation/domain reload after script edits.

        Script creation returns before Unity can always attach the new MonoBehaviour.
        This keeps generated-script plans from racing into component/add.
        """
        deadline = time.monotonic() + timeout
        saw_busy = False
        stable_ready_polls = 0
        time.sleep(min(interval, 0.25))
        while time.monotonic() < deadline:
            try:
                state = self.client.call_route("editor/state", {})
            except Exception:
                return
            if not isinstance(state, dict):
                return
            is_compiling = bool(state.get("isCompiling") or state.get("is_compiling"))
            domain_reload = bool(
                state.get("isDomainReloadPending")
                or state.get("is_domain_reload_pending")
                or state.get("domainReloadPending")
            )
            ready = state.get("readyForTools", state.get("ready_for_tools", True))
            busy = is_compiling or domain_reload or ready is False
            if busy:
                saw_busy = True
                stable_ready_polls = 0
            else:
                stable_ready_polls += 1
                if saw_busy or stable_ready_polls >= 2:
                    return
            time.sleep(interval)

    def _looks_like_component_compile_race(self, error: str) -> bool:
        lowered = str(error or "").lower()
        return (
            "component not found" in lowered
            or "script class" in lowered
            or "monobehaviour" in lowered
            or "cannot be found" in lowered
        )

    def _verify_scene_new(self, step: PlanStep, result: Any) -> Any:
        """Read back the active scene after creation so we do not report false success."""
        if not isinstance(result, dict):
            raise AssertionError("scene/new did not return a structured result")

        info = self.client.call_route("scene/info", {})
        if not isinstance(info, dict):
            raise AssertionError("scene/new verification failed: scene/info returned no data")
        if info.get("error"):
            raise AssertionError(f"scene/new verification failed: {info['error']}")

        active_name = str(info.get("name") or info.get("activeScene") or "").strip()
        active_path = str(info.get("path") or "").replace("\\", "/").strip()
        result_name = str(result.get("sceneName") or result.get("name") or "").strip()
        requested_name = str(step.params.get("name") or "").strip()
        expected_name = result_name or requested_name

        if expected_name and active_name != expected_name:
            raise AssertionError(
                f"scene/new readback mismatch: expected active scene {expected_name!r} "
                f"but scene/info returned {active_name!r}"
            )

        result_path = str(result.get("path") or "").replace("\\", "/").strip()
        if result_path and active_path and result_path != active_path:
            raise AssertionError(
                f"scene/new path mismatch: route returned {result_path!r} "
                f"but scene/info returned {active_path!r}"
            )

        enriched = dict(result)
        enriched["verifiedScene"] = {
            "name": active_name,
            "path": active_path,
            "isLoaded": bool(info.get("isLoaded", True)),
        }
        return enriched


# ── Formatting helpers ────────────────────────────────────────────────────────

def format_results(results: List[StepResult], *, color: bool = True) -> str:
    """Return a human-readable summary of step results."""
    lines = []
    ok = sum(1 for r in results if r.status == "ok")
    total = len(results)

    for r in results:
        if r.status == "ok":
            icon = "✓" if color else "[ok]"
            dur = f" ({r.duration_ms:.0f}ms)" if r.duration_ms else ""
            lines.append(f"  [{r.step}/{total}] {icon} {r.description}{dur}")
        elif r.status == "error":
            icon = "✗" if color else "[error]"
            lines.append(f"  [{r.step}/{total}] {icon} {r.description}")
            lines.append(f"        Error: {r.error}")
        else:
            icon = "–" if color else "[skip]"
            lines.append(f"  [{r.step}/{total}] {icon} {r.description} (skipped: {r.error})")

    lines.append(f"\nDone. {ok}/{total} steps completed.")
    return "\n".join(lines)
