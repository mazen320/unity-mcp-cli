from __future__ import annotations

from ..expert_lenses import grade_score


def _flatten_nodes(nodes: list[dict]) -> list[dict]:
    flattened: list[dict] = []
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


def _severity_penalty(severity: str) -> int:
    normalized = str(severity or "").strip().lower()
    if normalized == "high":
        return 18
    if normalized == "medium":
        return 12
    if normalized == "low":
        return 6
    return 0


def audit_systems_lens(context: dict) -> dict:
    findings: list[dict] = []
    project = dict(context.get("project") or {})
    assets = dict(context.get("assets") or {})
    systems = dict(context.get("systems") or {})

    if int(assets.get("sceneCount") or 0) > 0 and not systems.get("hasSandboxScene"):
        findings.append(
            {
                "severity": "low",
                "title": "No sandbox scene detected",
                "detail": "No scene path suggests a dedicated sandbox, test, prototype, or playground scene. A disposable scene makes probes and agent passes safer.",
            }
        )

    if (
        int(assets.get("sceneCount") or 0) > 0
        and int(assets.get("scriptCount") or 0) > 0
        and int(assets.get("prefabCount") or 0) == 0
    ):
        findings.append(
            {
                "severity": "medium",
                "title": "Scene-first content with no prefab coverage",
                "detail": "Scripts and scenes exist, but the audit found no prefabs. Reusable gameplay setup will stay fragile if everything lives only in scene files.",
            }
        )

    if systems.get("contextAvailable"):
        hierarchy_node_count = int(systems.get("hierarchyNodeCount") or 0)
        active_camera_count = int(systems.get("activeCameraCount") or 0)
        audio_listener_count = int(systems.get("audioListenerCount") or 0)
        canvas_count = int(systems.get("canvasCount") or 0)
        event_system_count = int(systems.get("eventSystemCount") or 0)
        character_controller_count = int(systems.get("characterControllerCount") or 0)
        rigidbody_count = int(systems.get("rigidbodyCount") or 0)
        collider_count = int(systems.get("colliderCount") or 0)
        likely_player_count = int(systems.get("likelyPlayerCount") or 0)
        disposable_object_count = int(systems.get("disposableObjectCount") or 0)
        hierarchy = (((context.get("raw") or {}).get("inspect") or {}).get("hierarchy") or {})
        raw_nodes = hierarchy.get("nodes") or hierarchy.get("hierarchy") or []
        nodes = _flatten_nodes(list(raw_nodes))
        event_system_nodes = [
            node for node in nodes if "EventSystem" in set(node.get("components") or [])
        ]
        input_module_types = {"StandaloneInputModule", "InputSystemUIInputModule"}

        if hierarchy_node_count > 0 and active_camera_count == 0:
            findings.append(
                {
                    "severity": "high",
                    "title": "No live Camera found in scene",
                    "detail": "The inspected hierarchy has no Camera component, so playability and framing are currently undefined.",
                }
            )

        if audio_listener_count > 1:
            findings.append(
                {
                    "severity": "high",
                    "title": "Multiple AudioListeners in scene",
                    "detail": f"The live hierarchy currently has {audio_listener_count} AudioListener components. Unity expects one active listener.",
                }
            )
        elif active_camera_count > 0 and audio_listener_count == 0:
            findings.append(
                {
                    "severity": "high",
                    "title": "No AudioListener in scene",
                    "detail": "The inspected scene has at least one Camera component, but no AudioListener was found. Audio playback and listener-relative effects will not behave correctly.",
                }
            )

        if canvas_count > 0 and event_system_count == 0:
            findings.append(
                {
                    "severity": "medium",
                    "title": "Canvas present without EventSystem",
                    "detail": "UI canvases exist in the inspected scene, but no EventSystem component was found. Interactive UI will not receive input reliably.",
                }
            )
        elif event_system_count > 1:
            findings.append(
                {
                    "severity": "high",
                    "title": "Multiple EventSystems in scene",
                    "detail": f"The inspected hierarchy currently has {event_system_count} EventSystem components. Unity UI should be driven by one primary EventSystem.",
                }
            )

        if event_system_nodes:
            for node in event_system_nodes:
                modules = input_module_types & set(node.get("components") or [])
                if not modules:
                    findings.append(
                        {
                            "severity": "medium",
                            "title": "EventSystem missing UI input module",
                            "detail": f"EventSystem `{node.get('name')}` has no UI input module component.",
                            "path": node.get("path") or node.get("hierarchyPath"),
                        }
                    )
                    break

        if likely_player_count > 0 and character_controller_count == 0 and rigidbody_count == 0:
            findings.append(
                {
                    "severity": "medium",
                    "title": "Likely player objects lack movement foundation",
                    "detail": "Player-like scene objects were detected, but the hierarchy currently has no CharacterController or Rigidbody component for movement and grounding.",
                }
            )

        if hierarchy_node_count >= 8 and active_camera_count > 0 and collider_count == 0:
            findings.append(
                {
                    "severity": "medium",
                    "title": "Scene appears interactive but has no collider coverage",
                    "detail": "The scene has enough hierarchy to look playable and already has a Camera, but no Collider components were detected.",
                }
            )

        if disposable_object_count > 0:
            disposable_names = ", ".join(str(path) for path in (systems.get("disposableObjects") or [])[:3])
            findings.append(
                {
                    "severity": "low",
                    "title": "Disposable probe/demo objects still present",
                    "detail": f"Temporary probe or fixture objects are still in the scene: {disposable_names}. Clean them before shipping or benchmarking.",
                }
            )

    score = max(35, 94 - sum(_severity_penalty(item.get("severity")) for item in findings))
    return {
        "lens": "systems",
        "score": score,
        "grade": grade_score(score),
        "confidence": 0.8 if systems.get("contextAvailable") else 0.7,
        "findings": findings,
        "summary": {
            "activeScene": project.get("activeScene"),
            "contextAvailable": bool(systems.get("contextAvailable")),
        },
    }
