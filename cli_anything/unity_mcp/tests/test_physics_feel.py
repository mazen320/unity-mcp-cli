"""Tests for the physics_feel audit (Step 2 of the anchor demo build)."""
from __future__ import annotations

from cli_anything.unity_mcp.core.skills import ProjectContext
from cli_anything.unity_mcp.core.skills.physics_feel import (
    airtime_estimate,
    audit_physics_feel,
    floatiness_score,
)


# --------------------------------------------------------------------------- #
# Fixture helpers                                                             #
# --------------------------------------------------------------------------- #


def _inspect_with_nodes(nodes: list[dict]) -> dict:
    return {"hierarchy": {"nodes": nodes}}


def _ctx(
    inspect: dict | None = None,
    systems: dict | None = None,
) -> ProjectContext:
    return ProjectContext(
        project_path="/tmp/fake",
        selected_port=None,
        inspect_payload=inspect,
        systems_summary=systems,
    )


# --------------------------------------------------------------------------- #
# Signal math                                                                 #
# --------------------------------------------------------------------------- #


def test_airtime_rises_when_gravity_weakens() -> None:
    tight = airtime_estimate(jump_power=8.0, gravity_y=-25.0)
    loose = airtime_estimate(jump_power=8.0, gravity_y=-9.8)
    assert loose > tight
    # Celeste-ish
    assert abs(tight - (2 * 8.0 / 25.0)) < 1e-6
    # Unity default
    assert abs(loose - (2 * 8.0 / 9.8)) < 1e-6


def test_airtime_clamps_negative_jump_power_to_zero() -> None:
    assert airtime_estimate(jump_power=-5.0, gravity_y=-9.8) == 0.0


def test_floatiness_ranges_make_sense() -> None:
    snappy = floatiness_score(airtime_s=0.3, drag=2.5, gravity_y=-25.0)
    middle = floatiness_score(airtime_s=1.0, drag=1.0, gravity_y=-15.0)
    floaty = floatiness_score(airtime_s=1.8, drag=0.2, gravity_y=-8.0)
    very_floaty = floatiness_score(airtime_s=2.5, drag=0.0, gravity_y=-3.0)

    assert snappy < middle < floaty <= very_floaty
    assert 0 <= snappy <= 100
    assert 0 <= very_floaty <= 100
    # Loose range checks guard against accidental weight flips.
    assert snappy <= 30
    assert very_floaty >= 85


# --------------------------------------------------------------------------- #
# Audit: no context                                                           #
# --------------------------------------------------------------------------- #


def test_audit_with_no_context_reports_low_confidence_without_crashing() -> None:
    result = audit_physics_feel(_ctx())
    assert result.skill == "physics_feel"
    assert result.confidence < 0.5
    assert result.summary["contextAvailable"] is False
    assert any("No live scene" in f.title for f in result.findings)


# --------------------------------------------------------------------------- #
# Audit: no player found                                                      #
# --------------------------------------------------------------------------- #


def test_audit_with_scene_but_no_player_flags_missing_player() -> None:
    inspect = _inspect_with_nodes(
        [
            {"name": "Main Camera", "components": ["Camera", "AudioListener"]},
            {"name": "Directional Light", "components": ["Light"]},
        ]
    )
    result = audit_physics_feel(_ctx(inspect=inspect))
    assert result.summary["playerFound"] is False
    titles = [f.title for f in result.findings]
    assert any("Couldn't find" in t for t in titles)


# --------------------------------------------------------------------------- #
# Audit: floaty player                                                        #
# --------------------------------------------------------------------------- #


def test_audit_floaty_player_flags_movement_feel() -> None:
    # Default Unity gravity + zero drag + stock jump → reads floaty.
    inspect = _inspect_with_nodes(
        [
            {
                "name": "Player",
                "path": "Player",
                "components": ["Rigidbody", "CapsuleCollider"],
                "tuning": {
                    "mass": 1.0,
                    "drag": 0.0,
                    "angularDrag": 0.05,
                    "useGravity": True,
                    "jumpPower": 10.0,
                },
            }
        ]
    )
    result = audit_physics_feel(_ctx(inspect=inspect))
    assert result.summary["playerFound"] is True
    assert result.summary["playerPath"] == "Player"
    assert result.summary["floatiness"] >= 55
    assert result.confidence >= 0.8  # value-aware audit
    titles = [f.title for f in result.findings]
    assert any("floaty" in t.lower() for t in titles)


# --------------------------------------------------------------------------- #
# Audit: snappy player                                                        #
# --------------------------------------------------------------------------- #


def test_audit_snappy_player_does_not_flag_floaty() -> None:
    inspect = _inspect_with_nodes(
        [
            {
                "name": "Player",
                "components": ["CharacterController"],
                "tuning": {
                    "drag": 1.5,
                    "jumpPower": 6.0,
                },
            }
        ]
    )
    # Also provide gravity via systems_summary to cover that source.
    systems = {"physics": {"gravity": {"y": -20.0}}}
    result = audit_physics_feel(_ctx(inspect=inspect, systems=systems))
    assert result.summary["gravityY"] == -20.0
    assert result.summary["floatiness"] < 55
    # No "floaty" finding.
    assert not any("floaty" in f.title.lower() for f in result.findings)


# --------------------------------------------------------------------------- #
# Audit: player with no movement body                                         #
# --------------------------------------------------------------------------- #


def test_audit_player_with_no_body_flags_high_severity() -> None:
    inspect = _inspect_with_nodes(
        [
            {"name": "Player", "components": ["MeshRenderer"]},
        ]
    )
    result = audit_physics_feel(_ctx(inspect=inspect))
    assert result.summary["playerFound"] is True
    highs = [f for f in result.findings if f.severity == "high"]
    assert any("no movement body" in f.title.lower() for f in highs)
    assert result.score <= 40


# --------------------------------------------------------------------------- #
# Audit: player with body but no collider                                     #
# --------------------------------------------------------------------------- #


def test_audit_player_with_body_but_no_collider_flags_medium() -> None:
    inspect = _inspect_with_nodes(
        [
            {"name": "Player", "components": ["Rigidbody"]},
        ]
    )
    result = audit_physics_feel(_ctx(inspect=inspect))
    mediums_and_up = [
        f for f in result.findings if f.severity in ("medium", "high")
    ]
    assert any("no collider" in f.title.lower() for f in mediums_and_up)


# --------------------------------------------------------------------------- #
# Audit: player selected via nested hierarchy                                 #
# --------------------------------------------------------------------------- #


def test_audit_finds_player_nested_in_hierarchy() -> None:
    inspect = _inspect_with_nodes(
        [
            {
                "name": "Level",
                "components": [],
                "children": [
                    {
                        "name": "Characters",
                        "components": [],
                        "children": [
                            {
                                "name": "Hero",
                                "path": "Level/Characters/Hero",
                                "components": ["CharacterController", "CapsuleCollider"],
                            }
                        ],
                    }
                ],
            }
        ]
    )
    result = audit_physics_feel(_ctx(inspect=inspect))
    assert result.summary["playerFound"] is True
    assert result.summary["playerPath"] == "Level/Characters/Hero"


# --------------------------------------------------------------------------- #
# Audit: falls back to Rigidbody-bearing node when no token matches           #
# --------------------------------------------------------------------------- #


def test_audit_falls_back_to_rigidbody_when_no_player_token() -> None:
    inspect = _inspect_with_nodes(
        [
            {"name": "Main Camera", "components": ["Camera"]},
            {"name": "CubeActor", "components": ["Rigidbody", "BoxCollider"]},
        ]
    )
    result = audit_physics_feel(_ctx(inspect=inspect))
    assert result.summary["playerFound"] is True
    assert result.summary["playerPath"] == "CubeActor"


# --------------------------------------------------------------------------- #
# Audit: structural-only signal finding when values aren't surfaced           #
# --------------------------------------------------------------------------- #


def test_audit_notes_structural_only_when_no_tuning_values() -> None:
    inspect = _inspect_with_nodes(
        [
            {"name": "Player", "components": ["Rigidbody", "CapsuleCollider"]},
        ]
    )
    result = audit_physics_feel(_ctx(inspect=inspect))
    assert any("Working from structural signal" in f.title for f in result.findings)
    # Confidence capped because values weren't surfaced.
    assert result.confidence < 0.7
