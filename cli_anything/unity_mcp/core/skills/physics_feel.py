"""Physics "feel" specialist skill.

This is the anchor demo for Phase 4 (`docs/superpowers/specs/2026-04-17-
phase4-specialist-skills.md`). It encodes physics *as a discipline* — not
a wrapper around the Unity API. When a user says "my player feels floaty,"
the skill audits the player's movement body, proposes three tuning paths
with real tradeoffs, and applies one bounded change with before/after proof.

Audit today runs from ``ProjectContext.inspect_payload`` component-name
strings plus scene systems summary. Reading exact Rigidbody field values
is deferred to a ``physics/get-rigidbody`` route enhancement — when that
lands, the audit gets value-aware and the score sharpens. Until then it
reports a structural floatiness signal with confidence capped accordingly.

Apply uses ``physics/set-rigidbody`` which already exists on both
standalone File IPC and plugin HTTP transports.
"""
from __future__ import annotations

import base64
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..expert_lenses import grade_score
from ..learning import append_run
from .base import (
    ActionOutcome,
    AuditFinding,
    AuditResult,
    ProofArtifact,
    ProjectContext,
    ProposedAction,
)

# Reused from expert_rules/physics.py so terminology stays consistent.
_PLAYER_TOKENS: tuple[str, ...] = ("player", "hero", "avatar", "character", "pawn")

_DEFAULT_GRAVITY_Y: float = -9.81  # Unity project default; treat as baseline.


# --------------------------------------------------------------------------- #
# Hierarchy helpers (mirror expert_rules/physics.py so the two audits agree). #
# --------------------------------------------------------------------------- #


def _flatten_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    stack = list(reversed(nodes))
    while stack:
        node = stack.pop()
        flattened.append(node)
        children = node.get("children") or []
        if isinstance(children, list):
            for child in reversed(children):
                if isinstance(child, dict):
                    stack.append(child)
    return flattened


def _node_components(node: dict[str, Any]) -> set[str]:
    return {str(component or "").strip() for component in (node.get("components") or [])}


def _node_label(node: dict[str, Any]) -> str:
    return str(
        node.get("path")
        or node.get("hierarchyPath")
        or node.get("name")
        or "Unnamed"
    )


def _looks_like_player(node: dict[str, Any], components: set[str]) -> bool:
    label = _node_label(node).lower()
    if "CharacterController" in components:
        return True
    return any(token in label for token in _PLAYER_TOKENS)


def _has_collider(components: set[str]) -> bool:
    return any(component.endswith("Collider") for component in components) or (
        "CharacterController" in components
    )


def _select_player_node(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the best candidate 'likely player' node from a flattened hierarchy.

    Preference order:
    1. Node whose label includes a player token AND has a movement body
    2. Node whose label includes a player token (any components)
    3. Node with a CharacterController (even without player token)
    4. First Rigidbody-bearing node if nothing else matches
    """
    named_with_body: list[dict[str, Any]] = []
    named: list[dict[str, Any]] = []
    controllers: list[dict[str, Any]] = []
    rigidbodies: list[dict[str, Any]] = []

    for node in nodes:
        components = _node_components(node)
        label = _node_label(node).lower()
        has_body = bool(components & {"Rigidbody", "Rigidbody2D", "CharacterController"})
        token_match = any(token in label for token in _PLAYER_TOKENS)
        if token_match and has_body:
            named_with_body.append(node)
        elif token_match:
            named.append(node)
        elif "CharacterController" in components:
            controllers.append(node)
        elif "Rigidbody" in components or "Rigidbody2D" in components:
            rigidbodies.append(node)

    for bucket in (named_with_body, named, controllers, rigidbodies):
        if bucket:
            return bucket[0]
    return None


# --------------------------------------------------------------------------- #
# Floatiness signal                                                           #
# --------------------------------------------------------------------------- #


def airtime_estimate(jump_power: float, gravity_y: float) -> float:
    """Kinematic estimate: ``t_air = 2 * v_initial / |g|`` for a simple impulse.

    Callers pass ``jump_power`` as the initial upward velocity in m/s. Real Unity
    Rigidbody jumps often apply a force or impulse; we treat ``jump_power`` as
    the equivalent initial velocity. The estimate is a heuristic — good enough
    for feel signaling, not a physics simulation.
    """
    g = abs(gravity_y) or abs(_DEFAULT_GRAVITY_Y)
    return (2.0 * max(0.0, jump_power)) / g


def floatiness_score(
    airtime_s: float,
    drag: float,
    gravity_y: float,
) -> int:
    """Return 0-100 where higher = more floaty.

    Three signals contribute: long airtime, low drag, weak gravity. Weights
    were picked empirically against broad movement-feel targets:
        responsive/stiff      ~  8/100
        controlled            ~ 35/100
        loose/floaty          ~ 65/100
        "my player floats"    ~ 75/100+
    """
    # Each penalty is bounded so the total saturates cleanly at 100 without
    # any single signal dominating. Airtime is the biggest contributor because
    # it is the most felt — followed by drag, then gravity magnitude.
    airtime_penalty = min(max(airtime_s, 0.0) / 2.0, 1.0) * 60
    drag_penalty = (1.0 - min(max(drag, 0.0), 3.0) / 3.0) * 25
    gravity_penalty = (1.0 - min(abs(gravity_y) / 20.0, 1.0)) * 15
    raw = airtime_penalty + drag_penalty + gravity_penalty
    return int(max(0, min(100, round(raw))))


# --------------------------------------------------------------------------- #
# Audit                                                                       #
# --------------------------------------------------------------------------- #


def _extract_hierarchy_nodes(inspect_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not inspect_payload:
        return []
    hierarchy = (inspect_payload.get("hierarchy") or {})
    if isinstance(hierarchy, dict):
        raw = hierarchy.get("nodes") or hierarchy.get("hierarchy") or []
    else:
        raw = hierarchy if isinstance(hierarchy, list) else []
    if not isinstance(raw, list):
        return []
    return _flatten_nodes(list(raw))


def _extract_gravity_y(
    inspect_payload: dict[str, Any] | None,
    systems_summary: dict[str, Any] | None,
) -> float:
    """Pull Physics.gravity.y from available payloads. Fallback to Unity default."""
    for source in (inspect_payload or {}, systems_summary or {}):
        physics = source.get("physics") if isinstance(source, dict) else None
        if isinstance(physics, dict):
            gravity = physics.get("gravity")
            if isinstance(gravity, dict) and "y" in gravity:
                try:
                    return float(gravity["y"])
                except (TypeError, ValueError):
                    continue
            if isinstance(gravity, (int, float)):
                return float(gravity)
    return _DEFAULT_GRAVITY_Y


def _extract_player_tuning(
    player_node: dict[str, Any] | None,
) -> dict[str, Any]:
    """Read any available tuning hints from the player node.

    Today inspect surfaces component *names*, not field values. We record what
    we can and mark unknown fields as ``None`` so the score knows confidence
    is capped. When a ``physics/get-rigidbody`` route lands, this becomes
    value-aware and the audit sharpens.
    """
    tuning: dict[str, Any] = {
        "mass": None,
        "drag": None,
        "angularDrag": None,
        "useGravity": None,
        "jumpPower": None,
        "hasCharacterController": False,
        "hasRigidbody": False,
        "hasCollider": False,
    }
    if not player_node:
        return tuning
    components = _node_components(player_node)
    tuning["hasCharacterController"] = "CharacterController" in components
    tuning["hasRigidbody"] = bool(components & {"Rigidbody", "Rigidbody2D"})
    tuning["hasCollider"] = _has_collider(components)

    # Allow inspect_payload to supply richer tuning under a ``tuning`` bag for
    # future route enhancements or test fixtures.
    extras = player_node.get("tuning")
    if isinstance(extras, dict):
        for key in ("mass", "drag", "angularDrag", "useGravity", "jumpPower"):
            if key in extras and extras[key] is not None:
                tuning[key] = extras[key]
    return tuning


def audit_physics_feel(context: ProjectContext) -> AuditResult:
    """Audit the scene from a physics *feel* perspective.

    Returns findings ordered by severity plus a 0-100 score where higher is
    better feel. Confidence is lowered when the live inspect payload does not
    expose real tuning values — the skill still responds usefully, but the
    tradeoffs note the limitation explicitly.
    """
    inspect_payload = context.inspect_payload
    systems_summary = context.systems_summary or {}

    findings: list[AuditFinding] = []

    if not inspect_payload and not systems_summary:
        findings.append(
            AuditFinding(
                severity="low",
                title="No live scene context",
                detail=(
                    "I can propose general physics-feel tuning but cannot point at your "
                    "actual player. Run the CLI against a live Unity editor (via `--port` "
                    "or File IPC) to get a specific diagnosis."
                ),
            )
        )
        return AuditResult(
            skill="physics_feel",
            score=60,
            grade=grade_score(60),
            confidence=0.3,
            findings=findings,
            summary={
                "contextAvailable": False,
                "playerFound": False,
                "gravityY": _DEFAULT_GRAVITY_Y,
            },
        )

    nodes = _extract_hierarchy_nodes(inspect_payload)
    player_node = _select_player_node(nodes)
    tuning = _extract_player_tuning(player_node)
    gravity_y = _extract_gravity_y(inspect_payload, systems_summary)

    confidence = 0.55 if player_node else 0.45
    if tuning["drag"] is not None or tuning["mass"] is not None:
        confidence = 0.85  # value-aware audit

    summary: dict[str, Any] = {
        "contextAvailable": True,
        "playerFound": player_node is not None,
        "playerPath": _node_label(player_node) if player_node else None,
        "projectPath": context.project_path,
        "gravityY": gravity_y,
        "tuning": tuning,
    }

    if not player_node:
        findings.append(
            AuditFinding(
                severity="medium",
                title="Couldn't find the player GameObject",
                detail=(
                    "I looked for objects named player/hero/avatar/character/pawn "
                    "or anything carrying CharacterController / Rigidbody. Nothing "
                    "matched. If your player has a different name, rename it or "
                    "tell me which GameObject to target."
                ),
            )
        )
        score = 55
        return AuditResult(
            skill="physics_feel",
            score=score,
            grade=grade_score(score),
            confidence=0.4,
            findings=findings,
            summary=summary,
        )

    # We have a player. Score feel.
    drag_value = float(tuning["drag"] if tuning["drag"] is not None else 0.0)
    jump_power = float(tuning["jumpPower"] if tuning["jumpPower"] is not None else 8.0)
    airtime = airtime_estimate(jump_power, gravity_y)
    floatiness = floatiness_score(airtime, drag_value, gravity_y)
    feel_score = max(0, 100 - floatiness)

    summary.update(
        {
            "airtimeSeconds": round(airtime, 3),
            "floatiness": floatiness,
        }
    )

    if not tuning["hasRigidbody"] and not tuning["hasCharacterController"]:
        findings.append(
            AuditFinding(
                severity="high",
                title="Player has no movement body",
                detail=(
                    f"'{_node_label(player_node)}' has no Rigidbody or "
                    "CharacterController. There is no physics to tune yet — add "
                    "a movement body first, then I can make it feel good."
                ),
            )
        )
        feel_score = min(feel_score, 40)

    elif not tuning["hasCollider"]:
        findings.append(
            AuditFinding(
                severity="medium",
                title="Player has a body but no collider",
                detail=(
                    f"'{_node_label(player_node)}' has a movement body but no "
                    "collider on the same object. Grounding, contacts, and "
                    "landing feedback will read as floaty or ghostly regardless "
                    "of other tuning."
                ),
            )
        )

    if floatiness >= 55:
        detail_parts = [
            f"Estimated airtime is {airtime:.2f}s (anything over ~0.8s starts reading as floaty)."
        ]
        if drag_value <= 0.1:
            detail_parts.append("Drag is effectively zero — the player never slows in air.")
        if abs(gravity_y) < 15:
            detail_parts.append(
                f"Gravity is {gravity_y:.1f} — default Unity gravity can feel light for punchy movement."
            )
        findings.append(
            AuditFinding(
                severity="high" if floatiness >= 70 else "medium",
                title="Movement feels floaty",
                detail=" ".join(detail_parts),
                data={"floatiness": floatiness, "airtimeSeconds": airtime},
            )
        )
    elif floatiness <= 20 and drag_value >= 2.5:
        findings.append(
            AuditFinding(
                severity="low",
                title="Movement may feel stiff",
                detail=(
                    f"Drag is {drag_value:.1f} and estimated airtime is {airtime:.2f}s. "
                    "That reads as heavy/stiff. If the user wants arcade bounce, we can dial it back."
                ),
            )
        )

    if tuning["drag"] is None and tuning["mass"] is None and player_node is not None:
        findings.append(
            AuditFinding(
                severity="low",
                title="Working from structural signal only",
                detail=(
                    "The current inspect payload surfaces component names but not Rigidbody "
                    "field values, so this diagnosis uses typical defaults. Apply one of the "
                    "tuning paths below and I will show you the resulting before/after values."
                ),
            )
        )

    return AuditResult(
        skill="physics_feel",
        score=feel_score,
        grade=grade_score(feel_score),
        confidence=confidence,
        findings=findings,
        summary=summary,
    )


# --------------------------------------------------------------------------- #
# Proposal paths                                                              #
# --------------------------------------------------------------------------- #


def propose_physics_feel_tuning(
    audit: AuditResult,
    request: str,
) -> list[ProposedAction]:
    """Return three bounded tuning paths with explicit tradeoffs.

    The request text is accepted so future versions can bias the path order
    from phrases like "I want it heavier" or "make it more arcade." The MVP
    keeps the order stable so chat follow-ups can refer to 1/2/3 safely.
    """
    summary = audit.summary or {}
    gravity_y = float(summary.get("gravityY", _DEFAULT_GRAVITY_Y))
    player_path = str(summary.get("playerPath") or "")
    project_path = str(summary.get("projectPath") or "")
    tuning = summary.get("tuning") if isinstance(summary.get("tuning"), dict) else {}
    drag = float(tuning.get("drag") if tuning.get("drag") is not None else 0.0)

    return [
        ProposedAction(
            action_id="physics_feel/snappy",
            title="Snappier jump",
            tradeoff=(
                f"Gravity jumps from {gravity_y:.1f} to -25.0 while drag stays at {drag:.2f}. "
                "The player reaches the apex sooner and falls harder, which reads as responsive "
                "and precise. Tradeoff: less hangtime for corrective air movement."
            ),
            preview={
                "player_path": player_path,
                "project_path": project_path,
                "current_gravity_y": gravity_y,
                "current_drag": drag,
                "gravity_y": -25.0,
                "drag": drag,
            },
            reversible=True,
        ),
        ProposedAction(
            action_id="physics_feel/controlled",
            title="More air control",
            tradeoff=(
                f"Drag rises from {drag:.2f} to 2.0 while gravity stays at {gravity_y:.1f}. "
                "The player keeps roughly the same jump arc but stops gliding through the air, "
                "so movement reads heavier and more intentional. Tradeoff: horizontal air moves "
                "feel lower-energy."
            ),
            preview={
                "player_path": player_path,
                "project_path": project_path,
                "current_gravity_y": gravity_y,
                "current_drag": drag,
                "gravity_y": gravity_y,
                "drag": 2.0,
            },
            reversible=True,
        ),
        ProposedAction(
            action_id="physics_feel/arcade",
            title="Arcade bounce",
            tradeoff=(
                "Gravity shifts to -30.0 and jump power is expected to scale by 1.4x to keep a "
                "similar peak height. The result is punchier takeoff and weightier landings with "
                "arcade bounce. Tradeoff: if you rely on global Physics.gravity, every other "
                "Rigidbody in the scene falls faster too."
            ),
            preview={
                "player_path": player_path,
                "project_path": project_path,
                "current_gravity_y": gravity_y,
                "current_drag": drag,
                "gravity_y": -30.0,
                "drag": drag,
                "jump_power_mult": 1.4,
            },
            reversible=True,
        ),
    ]


# --------------------------------------------------------------------------- #
# Apply + proof                                                               #
# --------------------------------------------------------------------------- #


def _bridge_client(bridge: Any) -> Any:
    client = getattr(bridge, "client", None)
    return client if client is not None else bridge


def _bridge_call_route(bridge: Any, route: str, params: dict[str, Any]) -> dict[str, Any]:
    client = _bridge_client(bridge)
    result = client.call_route(route, params)
    payload = dict(result or {})
    if payload.get("unknownRoute"):
        raise RuntimeError(f"{route} is not available on the connected Unity bridge.")
    if payload.get("success") is False or payload.get("error"):
        detail = str(payload.get("error") or f"{route} failed")
        raise RuntimeError(detail)
    return payload


def _project_root_from_bridge(bridge: Any, action: ProposedAction) -> Path:
    bridge_path = getattr(bridge, "project_path", None) or getattr(bridge, "project_root", None)
    if bridge_path:
        return Path(bridge_path)
    preview_path = str(action.preview.get("project_path") or "").strip()
    if preview_path:
        return Path(preview_path)
    return Path.cwd()


def _capture_dir(project_root: Path) -> Path:
    target = project_root / ".umcp" / "captures" / "physics-feel"
    target.mkdir(parents=True, exist_ok=True)
    return target


def capture_proof(bridge: Any, tag: str, *, project_root: Path) -> ProofArtifact:
    """Capture a single Game view proof image and persist it locally."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    output_path = _capture_dir(project_root) / f"{stamp}-{tag}.png"
    result = _bridge_call_route(bridge, "graphics/game-capture", {"width": 960, "height": 540})
    encoded = str(result.get("base64") or "").strip()
    if not encoded:
        raise ValueError("graphics/game-capture did not return image data.")
    output_path.write_bytes(base64.b64decode(encoded))
    return ProofArtifact(
        kind=f"screenshot-{tag}",
        path=str(output_path),
        data={
            "tag": tag,
            "width": int(result.get("width") or 960),
            "height": int(result.get("height") or 540),
        },
    )


def apply_physics_feel(action: ProposedAction, bridge: Any) -> ActionOutcome:
    """Apply one bounded tuning path via existing physics routes."""
    player_path = str(action.preview.get("player_path") or "").strip()
    if not player_path:
        return ActionOutcome(
            action_id=action.action_id,
            applied=False,
            before={},
            after={},
            captures=[],
            error="No player path was available for this physics-feel action.",
        )

    before = {
        "player_path": player_path,
        "gravity_y": float(action.preview.get("current_gravity_y", _DEFAULT_GRAVITY_Y)),
        "drag": float(action.preview.get("current_drag", 0.0)),
    }
    project_root = _project_root_from_bridge(bridge, action)
    captures: list[str] = []
    notes: list[str] = []

    try:
        before_capture = capture_proof(bridge, "before", project_root=project_root)
        if before_capture.path:
            captures.append(before_capture.path)

        payload: dict[str, Any] = {
            "gameObject": player_path,
            "drag": float(action.preview.get("drag", before["drag"])),
        }
        target_gravity = float(action.preview.get("gravity_y", before["gravity_y"]))
        _bridge_call_route(bridge, "physics/set-gravity", {"y": target_gravity})
        if "useGravity" in action.preview:
            payload["useGravity"] = bool(action.preview["useGravity"])
        if "mass" in action.preview:
            payload["mass"] = float(action.preview["mass"])

        _bridge_call_route(bridge, "physics/set-rigidbody", payload)

        after_capture = capture_proof(bridge, "after", project_root=project_root)
        if after_capture.path:
            captures.append(after_capture.path)
    except Exception as exc:
        outcome = ActionOutcome(
            action_id=action.action_id,
            applied=False,
            before=before,
            after=before,
            captures=[],
            error=str(exc),
        )
        append_run(
            project_root,
            {
                "skill": "physics_feel",
                "request": "physics feel apply",
                "chosen_action": action.action_id,
                "before": before,
                "after": before,
                "captures": [],
                "applied": False,
                "error": outcome.error,
            },
        )
        return outcome

    if "jump_power_mult" in action.preview:
        notes.append(
            "Jump power multiplier was suggested but not auto-applied yet; this MVP only adjusts Rigidbody tuning."
        )

    after = {
        "player_path": player_path,
        "gravity_y": float(action.preview.get("gravity_y", before["gravity_y"])),
        "drag": float(action.preview.get("drag", before["drag"])),
    }
    outcome = ActionOutcome(
        action_id=action.action_id,
        applied=True,
        before=before,
        after=after,
        captures=captures,
        error=None,
        notes=notes,
    )
    append_run(
        project_root,
        {
            "skill": "physics_feel",
            "request": "physics feel apply",
            "chosen_action": action.action_id,
            "before": before,
            "after": after,
            "captures": captures,
            "applied": True,
            "error": None,
            "notes": notes,
        },
    )
    return outcome


# --------------------------------------------------------------------------- #
# Re-exports for consumers that only want the audit half today.               #
# --------------------------------------------------------------------------- #


__all__ = [
    "apply_physics_feel",
    "airtime_estimate",
    "audit_physics_feel",
    "capture_proof",
    "floatiness_score",
    "propose_physics_feel_tuning",
]
