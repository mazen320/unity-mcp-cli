from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ExpertLens:
    name: str
    description: str
    focus: str
    audit: Callable[[dict[str, Any]], dict[str, Any]]
    supported_fix_types: tuple[str, ...] = field(default_factory=tuple)
    requires_live_scene: bool = False


def grade_score(score: int) -> str:
    if score < 40:
        return "poor"
    if score < 60:
        return "weak"
    if score < 75:
        return "workable"
    if score < 90:
        return "strong"
    return "excellent"


def iter_builtin_expert_lenses() -> list[ExpertLens]:
    from .expert_rules import (
        audit_animation_lens,
        audit_director_lens,
        audit_level_art_lens,
        audit_physics_lens,
        audit_systems_lens,
        audit_tech_art_lens,
        audit_ui_lens,
    )

    return [
        ExpertLens(
            name="director",
            description="Overall game direction and content priorities.",
            focus="direction",
            audit=audit_director_lens,
            supported_fix_types=("guidance", "sandbox-scene", "test-scaffold"),
        ),
        ExpertLens(
            name="systems",
            description="Unity systems audit for scene architecture, playability hooks, and runtime hygiene.",
            focus="unity systems",
            audit=audit_systems_lens,
            supported_fix_types=("guidance", "sandbox-scene", "event-system", "audio-listener"),
        ),
        ExpertLens(
            name="physics",
            description="Collider, rigidbody, and movement-body audit.",
            focus="physics foundations",
            audit=audit_physics_lens,
            requires_live_scene=True,
        ),
        ExpertLens(
            name="animation",
            description="Rig, avatar, clip, and controller audit.",
            focus="animation pipeline",
            audit=audit_animation_lens,
            supported_fix_types=("controller-scaffold", "controller-wireup"),
        ),
        ExpertLens(
            name="tech-art",
            description="Materials, shaders, textures, and render-pipeline audit.",
            focus="technical art",
            audit=audit_tech_art_lens,
            supported_fix_types=("texture-imports",),
        ),
        ExpertLens(
            name="ui",
            description="Canvas, anchors, scaler, and HUD audit.",
            focus="ui readability",
            audit=audit_ui_lens,
            supported_fix_types=("ui-canvas-scaler", "ui-graphic-raycaster"),
            requires_live_scene=True,
        ),
        ExpertLens(
            name="level-art",
            description="Scene readability, density, and composition audit.",
            focus="level readability",
            audit=audit_level_art_lens,
            supported_fix_types=("sandbox-scene",),
            requires_live_scene=True,
        ),
    ]


def get_builtin_expert_lens(name: str) -> ExpertLens:
    normalized = str(name or "").strip().lower()
    for lens in iter_builtin_expert_lenses():
        if lens.name == normalized:
            return lens
    available = ", ".join(lens.name for lens in iter_builtin_expert_lenses())
    raise ValueError(f"Unknown expert lens '{name}'. Available lenses: {available}.")
