from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from .routes import RouteResolutionError, tool_name_to_route
from .schema_templates import summarize_schema
from .tool_catalog import get_upstream_catalog, iter_upstream_tools


COVERAGE_STATUSES = (
    "live-tested",
    "covered",
    "mock-only",
    "unsupported",
    "deferred",
)


LIVE_TESTED_ROUTE_NOTES: Dict[str, str] = {
    "context": "Verified against a real Unity editor through the CLI context command; now uses queued context with an execute-code main-thread fallback.",
    "profiler/memory-status": "Verified against a real Unity editor through the advanced audit workflow.",
    "graphics/lighting-summary": "Verified against a real Unity editor through the advanced audit workflow.",
    "sceneview/info": "Verified against a real Unity editor through the advanced audit workflow.",
    "settings/quality": "Verified against a real Unity editor through the advanced audit workflow.",
    "settings/time": "Verified against a real Unity editor through the advanced audit workflow.",
    "profiler/stats": "Verified against a real Unity editor through the advanced audit workflow.",
    "testing/list-tests": "Verified against a real Unity editor through the advanced audit workflow.",
    "graphics/renderer-info": "Verified against a real Unity editor through the standalone File IPC prefab/material/renderer parity probe, returning live renderer metadata for a scene object.",
    "graphics/mesh-info": "Verified against a real Unity editor through the advanced audit workflow.",
    "graphics/material-info": "Verified against a real Unity editor through the standalone File IPC prefab/material/renderer parity probe, returning live material shader properties from both asset and scene targets.",
    "physics/raycast": "Verified against a real Unity editor through the advanced audit workflow.",
    "ui/create-canvas": "Verified against a real Unity editor through the advanced audit workflow.",
    "ui/info": "Verified against a real Unity editor through the advanced audit workflow.",
    "audio/info": "Verified against a real Unity editor through the advanced audit workflow.",
    "lighting/create": "Verified against a real Unity editor through the advanced audit workflow.",
    "lighting/info": "Verified against a real Unity editor through the advanced audit workflow.",
    "animation/create-controller": "Verified against a real Unity editor through the advanced audit workflow.",
    "animation/create-clip": "Verified against a real Unity editor through the advanced audit workflow.",
    "animation/set-clip-curve": "Verified against a real Unity editor through the advanced audit workflow.",
    "animation/add-layer": "Verified against a real Unity editor through the advanced audit workflow.",
    "animation/add-parameter": "Verified against a real Unity editor through the standalone File IPC animation authoring routes.",
    "animation/add-state": "Verified against a real Unity editor through the standalone File IPC animation authoring routes.",
    "animation/set-default-state": "Verified against a real Unity editor through the standalone File IPC animation authoring routes, flipping the Animator layer default state without adding fake entry transitions.",
    "animation/add-transition": "Verified against a real Unity editor through the standalone File IPC animation authoring routes.",
    "animation/assign-controller": "Verified against a real Unity editor through the standalone File IPC animation wireup workflow.",
    "animation/clip-info": "Verified against a real Unity editor through the standalone File IPC animation inspection routes.",
    "animation/controller-info": "Verified against a real Unity editor through the standalone File IPC animation inspection and authoring routes.",
    "input/create": "Verified against a real Unity editor through the advanced audit workflow.",
    "input/info": "Verified against a real Unity editor through the advanced audit workflow.",
    "shadergraph/status": "Verified against a real Unity editor through the advanced audit workflow.",
    "shadergraph/create": "Verified against a real Unity editor through the advanced audit workflow.",
    "shadergraph/list": "Verified against a real Unity editor through the advanced audit workflow.",
    "terrain/create": "Verified against a real Unity editor through the advanced audit workflow.",
    "terrain/info": "Verified against a real Unity editor through the advanced audit workflow.",
    "terrain/get-height": "Verified against a real Unity editor through the advanced audit workflow.",
    "navigation/info": "Verified against a real Unity editor through the advanced audit workflow.",
    "search/by-component": "Verified against a real Unity editor through the standalone File IPC smoke pass, returning live scene object matches by component type.",
    "selection/get": "Verified against a real Unity editor through the standalone File IPC smoke pass, returning the current Unity selection state.",
    "selection/set": "Verified against a real Unity editor through the standalone File IPC smoke pass, selecting a live scene object by path.",
    "selection/focus-scene-view": "Verified against a real Unity editor through the standalone File IPC smoke pass, focusing the Scene view on the selected live object.",
    "asset/create-material": "Verified against a real Unity editor through the standalone File IPC prefab/material/renderer parity probe, creating a disposable material asset on the public route surface.",
    "asset/create-prefab": "Verified against a real Unity editor through the standalone File IPC prefab/material/renderer parity probe, saving a live scene object as a prefab through the public route surface.",
    "asset/instantiate-prefab": "Verified against a real Unity editor through the standalone File IPC prefab/material/renderer parity probe, instantiating a disposable prefab into the active scene through the public route surface.",
    "renderer/set-material": "Verified against a real Unity editor through the standalone File IPC prefab/material/renderer parity probe, swapping a live renderer material through the public route surface.",
    "prefab/info": "Verified against a real Unity editor through the standalone File IPC prefab/material/renderer parity probe, reading both prefab asset metadata and connected scene-instance metadata.",
}


COVERED_ROUTE_NOTES: Dict[str, str] = {
    "scene/info": "Covered by automated tests and higher-level workflows.",
    "project/info": "Covered by automated tests and higher-level workflows.",
    "scene/open": "Covered by automated tests and higher-level workflows.",
    "scene/save": "Covered by automated tests and higher-level workflows.",
    "scene/hierarchy": "Covered by automated tests and higher-level workflows.",
    "search/missing-references": "Covered by automated tests and higher-level workflows.",
    "search/scene-stats": "Covered by automated tests and higher-level workflows.",
    "editor/state": "Covered by automated tests and higher-level workflows.",
    "editor/play-mode": "Covered by automated tests and live-pass workflows.",
    "compilation/errors": "Covered by automated tests and higher-level workflows.",
    "editor/execute-code": "Covered by automated tests and higher-level workflows.",
    "asset/list": "Covered by automated tests and higher-level workflows.",
    "asset/delete": "Covered by automated tests and higher-level workflows.",
    "script/create": "Covered by automated tests and higher-level workflows.",
    "script/read": "Covered by automated tests and higher-level workflows.",
    "script/update": "Covered by automated tests and higher-level workflows.",
    "gameobject/create": "Covered by automated tests and higher-level workflows.",
    "gameobject/info": "Covered by automated tests and higher-level workflows.",
    "gameobject/delete": "Covered by automated tests and higher-level workflows.",
    "gameobject/set-transform": "Covered by automated tests and higher-level workflows.",
    "component/add": "Covered by automated tests and higher-level workflows.",
    "component/get-properties": "Covered by automated tests and higher-level workflows.",
    "component/set-property": "Covered by automated tests and higher-level workflows.",
    "component/set-reference": "Covered by automated tests and higher-level workflows.",
    "graphics/game-capture": "Covered by automated tests and higher-level workflows.",
    "graphics/scene-capture": "Covered by automated tests and higher-level workflows.",
    "agents/list": "Covered by automated tests and higher-level agent-session workflows.",
    "console/log": "Covered by automated tests and higher-level debug snapshot workflows.",
    "queue/info": "Covered by automated tests and live MCP pass workflows.",
    "queue/status": "Covered by automated tests and live MCP pass workflows.",
    "undo/perform": "Covered by automated tests and higher-level workflows.",
}


COVERED_TOOL_NOTES: Dict[str, str] = {
    "unity_advanced_tool": "Covered by automated tests through the CLI meta-tool dispatch path.",
    "unity_list_advanced_tools": "Covered by automated tests through the CLI advanced-tool listing path.",
    "unity_list_instances": "Covered by automated tests through the CLI instance discovery wrapper.",
    "unity_select_instance": "Covered by automated tests through the CLI instance selection wrapper.",
}


MOCK_ONLY_ROUTE_NOTES: Dict[str, str] = {
    "ui/create-element": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "ui/set-image": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "ui/set-text": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "lighting/create-light-probe-group": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "lighting/create-reflection-probe": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "lighting/set-environment": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "animation/add-event": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "animation/get-curve-keyframes": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "animation/get-events": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/get-heights-region": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/get-steepness": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/get-tree-instances": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/list": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Terrain mutation routes — disposable-terrain fixture coverage added
    "terrain/set-settings": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/set-height": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/set-heights-region": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/raise-lower": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/flatten": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/smooth": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/noise": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/add-layer": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/remove-layer": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/fill-layer": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/paint-layer": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/add-detail-prototype": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/add-tree-prototype": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/remove-tree-prototype": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/place-trees": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/clear-trees": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/paint-detail": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/scatter-detail": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/clear-detail": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/set-neighbors": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/set-holes": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/resize": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/create-grid": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/export-heightmap": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "terrain/import-heightmap": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Animation mutation/read routes — disposable-controller fixture coverage added
    "animation/get-blend-tree": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "animation/add-keyframe": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "animation/remove-keyframe": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "animation/remove-curve": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "animation/remove-event": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "animation/remove-layer": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "animation/remove-parameter": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "animation/remove-state": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "animation/remove-transition": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "animation/create-blend-tree": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "animation/set-clip-settings": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Prefab routes — disposable-prefab fixture coverage added
    "prefab/apply-overrides": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab/revert-overrides": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab/create-variant": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab/unpack": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab-asset/hierarchy": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab-asset/get-properties": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab-asset/set-property": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab-asset/set-reference": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab-asset/add-component": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab-asset/remove-component": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab-asset/add-gameobject": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab-asset/remove-gameobject": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab-asset/compare-variant": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab-asset/variant-info": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab-asset/apply-variant-override": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab-asset/revert-variant-override": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab-asset/transfer-variant-overrides": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Asmdef routes — assembly definition fixture coverage added
    "asmdef/list": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "asmdef/info": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "asmdef/create": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "asmdef/create-ref": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "asmdef/add-references": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "asmdef/remove-references": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "asmdef/set-platforms": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "asmdef/update-settings": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Particle routes — particle system fixture coverage added
    "particle/create": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "particle/info": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "particle/playback": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "particle/set-emission": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "particle/set-main": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "particle/set-shape": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # LOD routes
    "lod/create": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "lod/info": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Constraint routes
    "constraint/add": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "constraint/info": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Search routes (all read-only)
    "search/assets": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "search/by-layer": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "search/by-name": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "search/by-shader": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "search/by-tag": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Shader routes (read-only)
    "shadergraph/get-properties": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "shadergraph/list-shaders": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # ShaderGraph routes
    "shadergraph/add-node": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "shadergraph/connect": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "shadergraph/disconnect": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "shadergraph/get-edges": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "shadergraph/get-node-types": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "shadergraph/get-nodes": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "shadergraph/info": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "shadergraph/list-subgraphs": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "shadergraph/open": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "shadergraph/remove-node": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "shadergraph/set-node-property": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # PlayerPrefs routes
    "playerprefs/delete": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "playerprefs/delete-all": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "playerprefs/get": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "playerprefs/set": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Input System routes
    "input/add-action": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "input/add-binding": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "input/add-composite-binding": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "input/add-map": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "input/remove-action": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "input/remove-map": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Selection routes
    "selection/find-by-type": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # ScriptableObject routes
    "scriptableobject/create": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "scriptableobject/info": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "scriptableobject/list-types": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "scriptableobject/set-field": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Settings routes
    "settings/physics": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "settings/player": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "settings/render-pipeline": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "settings/set-physics": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "settings/set-player": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "settings/quality-level": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "settings/set-time": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Tag/Layer routes
    "taglayer/add-tag": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "taglayer/info": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "taglayer/set-layer": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "taglayer/set-static": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "taglayer/set-tag": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Texture routes
    "texture/info": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "texture/reimport": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "texture/set-import": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "texture/set-normalmap": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "texture/set-sprite": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # NavMesh routes
    "navigation/add-agent": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "navigation/add-obstacle": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "navigation/bake": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "navigation/clear": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "navigation/set-destination": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Physics routes
    "physics/collision-matrix": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "physics/overlap-box": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "physics/overlap-sphere": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "physics/set-collision-layer": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "physics/set-gravity": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Graphics routes
    "graphics/asset-preview": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "graphics/prefab-render": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "graphics/texture-info": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Packages routes
    "packages/add": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "packages/info": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "packages/list": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "packages/remove": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "packages/search": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # SpriteAtlas routes
    "spriteatlas/add": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "spriteatlas/create": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "spriteatlas/delete": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "spriteatlas/info": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "spriteatlas/list": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "spriteatlas/remove": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "spriteatlas/settings": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Profiler routes
    "profiler/analyze": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "profiler/enable": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "profiler/frame-data": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "profiler/memory": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "profiler/memory-breakdown": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "profiler/memory-snapshot": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "profiler/memory-top-assets": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Debugger routes
    "debugger/enable": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "debugger/event-details": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "debugger/events": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # EditorPrefs routes
    "editorprefs/delete": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "editorprefs/get": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "editorprefs/set": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Audio routes
    "audio/create-source": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "audio/set-global": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Console routes
    "console/clear": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Screenshot routes
    "screenshot/game": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "screenshot/scene": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Testing routes
    "testing/get-job": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "testing/run-tests": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Undo routes
    "undo/clear": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "undo/history": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "undo/redo": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # VFX routes
    "shadergraph/list-vfx": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "shadergraph/open-vfx": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Component additional routes
    "component/batch-wire": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "component/get-referenceable": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "component/remove": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # GameObject additional routes
    "prefab/duplicate": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab/reparent": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab/set-active": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "prefab/set-object-reference": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Agent/Agents routes
    "agents/log": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Asset additional routes
    "asset/import": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Build route
    "build/start": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Editor ping
    "ping": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Execute menu item
    "editor/execute-menu-item": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # Renderer additional
    # Scene new
    "scene/new": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # SceneView set-camera
    "sceneview/set-camera": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    # MPPM / scenario route overrides
    "scenario/activate": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "scenario/info": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "scenario/list": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "scenario/start": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "scenario/status": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
    "scenario/stop": "Covered by subprocess e2e tests against the mock Unity bridge; needs live fixture validation before promotion.",
}

PACKAGE_FIXTURE_HINTS: Dict[str, Dict[str, Any]] = {
    "amplify": {
        "package": "Amplify Shader Editor",
        "fixtureRoot": "Assets/CLIAnythingFixtures/Amplify",
        "setup": "Use a disposable Unity project with Amplify Shader Editor installed and the Unity MCP bridge loaded.",
        "assets": [
            "A disposable Amplify shader asset under Assets/CLIAnythingFixtures/Amplify.",
            "A material that references that shader for open/save/node mutation checks.",
        ],
        "preflight": [
            "unity_amplify_status",
            "unity_amplify_list",
            "unity_amplify_get_node_types",
        ],
        "cleanup": "Delete Assets/CLIAnythingFixtures/Amplify and restore any open Amplify editor window state.",
    },
    "uma": {
        "package": "UMA / UMA DCS",
        "fixtureRoot": "Assets/CLIAnythingFixtures/UMA",
        "setup": "Use a disposable Unity project with UMA content imported and its global library initialized.",
        "assets": [
            "A tiny disposable FBX or known UMA sample FBX for inspect/create-slot flows.",
            "A known UMA material asset and at least one compatible race from the fixture library.",
        ],
        "preflight": [
            "unity_uma_get_project_config",
            "unity_uma_list_global_library",
            "unity_uma_list_uma_materials",
        ],
        "cleanup": "Delete Assets/CLIAnythingFixtures/UMA and rebuild the UMA global library if the test registered assets.",
    },
    "mppm": {
        "package": "Unity Multiplayer Play Mode",
        "fixtureRoot": "Assets/CLIAnythingFixtures/MPPM",
        "setup": "Use a disposable Unity project with Multiplayer Play Mode scenarios enabled.",
        "assets": [
            "One disposable Multiplayer Play Mode scenario asset.",
        ],
        "preflight": [
            "unity_mppm_info",
            "unity_mppm_list_scenarios",
            "unity_mppm_status",
        ],
        "cleanup": "Stop MPPM and reset the active scenario to the previous editor state.",
    },
}

PACKAGE_DEPENDENT_CATEGORIES = {
    "amplify",
    "mppm",
    "shadergraph",
    "spriteatlas",
    "uma",
}

STATEFUL_MUTATION_CATEGORIES = {
    "animation",
    "asset",
    "audio",
    "component",
    "constraint",
    "gameobject",
    "graphics",
    "input",
    "lighting",
    "lod",
    "material",
    "navmesh",
    "packages",
    "particle",
    "physics",
    "prefab",
    "renderer",
    "scene",
    "sceneview",
    "scriptableobject",
    "search",
    "selection",
    "settings",
    "terrain",
    "texture",
    "ui",
    "undo",
    "vfx",
}

ENVIRONMENT_DEPENDENT_CATEGORIES = {
    "build",
    "console",
    "debugger",
    "editor",
    "editorprefs",
    "execute",
    "memory",
    "playerprefs",
    "profiler",
    "screenshot",
    "testing",
}

META_SURFACE_CATEGORIES = {
    "agent",
    "agents",
    "context",
    "list",
    "meta",
    "select",
}


def _unsupported_note(tool: Dict[str, Any]) -> tuple[str, str]:
    category = str(tool.get("category") or "").lower()
    if category == "hub":
        return (
            "Requires separate Unity Hub integration. These commands are outside the current editor bridge and need Hub discovery/install automation.",
            "unity-hub-integration",
        )
    return "Marked unsupported in the upstream catalog.", "upstream-unsupported"


def _deferred_note(tool: Dict[str, Any]) -> tuple[str, str]:
    category = str(tool.get("category") or "").lower()
    if category in PACKAGE_DEPENDENT_CATEGORIES:
        return (
            "Known upstream tool, but it depends on optional packages/assets and still needs fixture-based live validation before promotion.",
            "package-dependent-live-audit",
        )
    if category in STATEFUL_MUTATION_CATEGORIES:
        return (
            "Known upstream tool, but it performs stateful editor mutations. We need disposable fixtures and live audit coverage before promoting it.",
            "stateful-live-audit",
        )
    if category in ENVIRONMENT_DEPENDENT_CATEGORIES:
        return (
            "Known upstream tool, but it depends on machine/editor/runtime state that has not been fully wired into the automated coverage pass yet.",
            "environment-sensitive",
        )
    if category in META_SURFACE_CATEGORIES:
        return (
            "Known upstream/meta surface, but the CLI-first equivalent has not been explicitly mapped into the coverage matrix yet.",
            "matrix-mapping-gap",
        )
    return (
        "Known in the upstream catalog, but it has not been wrapped or verified deeply enough yet.",
        "wrapper-gap",
    )


def _coverage_status(tool: Dict[str, Any]) -> tuple[str, str, str]:
    route = _resolved_tool_route(tool)
    name = str(tool.get("name") or "")
    if tool.get("unsupported"):
        note, blocker = _unsupported_note(tool)
        return "unsupported", note, blocker
    if route in LIVE_TESTED_ROUTE_NOTES:
        return "live-tested", LIVE_TESTED_ROUTE_NOTES[route], "verified-live"
    if route in COVERED_ROUTE_NOTES:
        return "covered", COVERED_ROUTE_NOTES[route], "verified-automated"
    if name in COVERED_TOOL_NOTES:
        return "covered", COVERED_TOOL_NOTES[name], "verified-automated"
    if route in MOCK_ONLY_ROUTE_NOTES:
        return "mock-only", MOCK_ONLY_ROUTE_NOTES[route], "verified-mock"
    note, blocker = _deferred_note(tool)
    return "deferred", note, blocker


def _resolved_tool_route(tool: Dict[str, Any]) -> str:
    route = str(tool.get("route") or "")
    if route:
        return route
    name = str(tool.get("name") or "")
    if not name:
        return ""
    try:
        return tool_name_to_route(name)
    except RouteResolutionError:
        return ""


def _tool_risk(tool: Dict[str, Any]) -> tuple[str, int]:
    route = _resolved_tool_route(tool).lower()
    name = str(tool.get("name") or "").lower()
    text = f"{route} {name}"
    destructive_words = ("delete", "remove", "clear", "destroy", "unload")
    read_words = (
        "info",
        "list",
        "get",
        "summary",
        "status",
        "find",
        "search",
        "validate",
        "preview",
    )
    create_words = ("create", "generate", "bake", "build")
    if any(word in text for word in destructive_words):
        return "destructive", 3
    if any(word in text for word in read_words):
        return "read-only", 0
    if any(word in text for word in create_words):
        return "safe-mutation", 1
    return "stateful-mutation", 2


def _fixture_hint(tool: Dict[str, Any]) -> Dict[str, Any] | None:
    category = str(tool.get("category") or "").lower()
    hint = PACKAGE_FIXTURE_HINTS.get(category)
    return dict(hint) if hint else None


def _route_label(route: str) -> str:
    return route or "CLI wrapper/no upstream route"


def _next_batch_reason(tool: Dict[str, Any], risk: str) -> str:
    blocker = str(tool.get("coverageBlocker") or "")
    if blocker == "package-dependent-live-audit":
        return "Needs package-aware fixture checks before promotion."
    if risk == "read-only":
        return "Good first candidate because it can usually be inspected without mutating the scene."
    if blocker == "stateful-live-audit":
        return "Needs disposable-scene setup, assertions, and cleanup before promotion."
    if blocker == "environment-sensitive":
        return "Needs editor-state guardrails so the live audit is repeatable."
    return "Needs explicit wrapper or live-audit evidence before promotion."


def _coverage_next_batch(tools: list[Dict[str, Any]], limit: int) -> list[Dict[str, Any]]:
    if limit <= 0:
        return []

    candidates = [tool for tool in tools if tool.get("coverageStatus") == "deferred"]
    candidates.sort(
        key=lambda tool: (
            _tool_risk(tool)[1],
            str(tool.get("category") or ""),
            str(tool.get("name") or ""),
        )
    )

    batch: list[Dict[str, Any]] = []
    for tool in candidates[:limit]:
        risk, _rank = _tool_risk(tool)
        schema = summarize_schema(tool.get("inputSchema"))
        name = str(tool.get("name") or "")
        route = str(tool.get("resolvedRoute") or _resolved_tool_route(tool))
        fixture_hint = _fixture_hint(tool)
        template = schema["requiredTemplate"]
        if template:
            params_json = json.dumps(template, separators=(",", ":"), ensure_ascii=True)
            tool_command = f"cli-anything-unity-mcp --json tool {name} --params '{params_json}' --port <port>"
        else:
            tool_command = f"cli-anything-unity-mcp --json tool {name} --port <port>"
        item = {
            "name": name,
            "route": route,
            "category": tool.get("category"),
            "risk": risk,
            "coverageStatus": tool.get("coverageStatus"),
            "coverageBlocker": tool.get("coverageBlocker"),
            "required": schema["required"],
            "optional": schema["optional"],
            "requiredTemplate": schema["requiredTemplate"],
            "reason": _next_batch_reason(tool, risk),
            "recommendedCommands": [
                f"cli-anything-unity-mcp --json tool-info {name} --port <port>",
                f"cli-anything-unity-mcp --json tool-template {name} --include-optional --port <port>",
                tool_command,
            ],
            "handoffPrompt": (
                f"Audit {name} ({_route_label(route)}) in a disposable Unity scene. Start with tool-info "
                "and tool-template, run the smallest safe live check, capture before/after evidence, "
                "and only promote coverage if cleanup is reliable."
            ),
        }
        if fixture_hint:
            item["fixtureHint"] = fixture_hint
            item["handoffPrompt"] = (
                f"Audit {name} ({_route_label(route)}) in a disposable Unity project with "
                f"{fixture_hint['package']}. Run the preflight commands first, use fixture assets under "
                f"{fixture_hint['fixtureRoot']}, capture before/after evidence, then follow cleanup: "
                f"{fixture_hint['cleanup']}"
            )
        batch.append(item)
    return batch


def _compact_tool_entry(tool: Dict[str, Any]) -> Dict[str, str]:
    return {
        "name": str(tool.get("name") or ""),
        "route": str(tool.get("resolvedRoute") or _resolved_tool_route(tool)),
    }


def _coverage_fixture_plans(tools: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for tool in tools:
        if tool.get("coverageStatus") != "deferred":
            continue
        if tool.get("coverageBlocker") != "package-dependent-live-audit":
            continue
        fixture_hint = _fixture_hint(tool)
        if not fixture_hint:
            continue

        category = str(tool.get("category") or "uncategorized").lower()
        plan = grouped.setdefault(
            category,
            {
                "category": category,
                "package": fixture_hint.get("package"),
                "fixtureRoot": fixture_hint.get("fixtureRoot"),
                "setup": fixture_hint.get("setup"),
                "assets": fixture_hint.get("assets", []),
                "preflight": fixture_hint.get("preflight", []),
                "cleanup": fixture_hint.get("cleanup"),
                "toolsByRisk": {
                    "read-only": [],
                    "safe-mutation": [],
                    "stateful-mutation": [],
                    "destructive": [],
                },
            },
        )
        risk, _rank = _tool_risk(tool)
        plan["toolsByRisk"][risk].append(_compact_tool_entry(tool))

    plans: list[Dict[str, Any]] = []
    for category, plan in sorted(grouped.items()):
        tools_by_risk = plan["toolsByRisk"]
        for risk_tools in tools_by_risk.values():
            risk_tools.sort(key=lambda item: item["name"])

        deferred_tool_count = sum(len(risk_tools) for risk_tools in tools_by_risk.values())
        preflight_commands = [
            f"cli-anything-unity-mcp --json tool {tool_name} --port <port>"
            for tool_name in plan["preflight"]
        ]
        plan["deferredToolCount"] = deferred_tool_count
        plan["readOnlyFirst"] = tools_by_risk["read-only"]
        plan["safeMutationNext"] = tools_by_risk["safe-mutation"]
        plan["statefulMutationLater"] = tools_by_risk["stateful-mutation"]
        plan["destructiveLast"] = tools_by_risk["destructive"]
        plan["recommendedCommands"] = [
            f"cli-anything-unity-mcp --json tool-coverage --category {category} --status deferred --summary --next-batch 10",
            f"cli-anything-unity-mcp --json tool-coverage --category {category} --status deferred",
            *preflight_commands,
        ]
        plan["handoffPrompt"] = (
            f"Live-audit the deferred {category} tools in a disposable Unity project with "
            f"{plan['package']} installed. Use fixtures under {plan['fixtureRoot']}, run the "
            "preflight commands first, test read-only tools before mutations, capture before/after "
            f"evidence, and clean up with: {plan['cleanup']}"
        )
        plans.append(plan)
    return plans


def _coverage_support_plans(tools: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    hub_tools = [
        _compact_tool_entry(tool)
        for tool in tools
        if tool.get("coverageStatus") == "unsupported"
        and tool.get("coverageBlocker") == "unity-hub-integration"
    ]
    if not hub_tools:
        return []

    hub_tools.sort(key=lambda item: item["name"])
    return [
        {
            "category": "hub",
            "coverageBlocker": "unity-hub-integration",
            "toolCount": len(hub_tools),
            "tools": hub_tools,
            "goal": "Add an optional Unity Hub backend without coupling editor-bridge commands to Hub availability.",
            "safeImplementationOrder": [
                "Read-only discovery first: list installed editors, install path, and available releases.",
                "State-changing commands next: set install path only with explicit user input.",
                "Install commands last: require explicit version/modules, dry-run-friendly output, and clear long-running progress reporting.",
            ],
            "integrationNotes": [
                "Prefer Unity Hub's supported CLI or documented local metadata over screen automation.",
                "Keep Hub commands usable when no Unity Editor bridge is running.",
                "Do not promote Hub tools out of unsupported until the backend has tests and platform-specific failure handling.",
            ],
            "recommendedCommands": [
                "cli-anything-unity-mcp --json tool-coverage --category hub --status unsupported",
                "cli-anything-unity-mcp --json tool-info unity_hub_list_editors",
                "cli-anything-unity-mcp --json tool-info unity_hub_available_releases",
                "cli-anything-unity-mcp --json tool-template unity_hub_install_editor --include-optional",
            ],
            "handoffPrompt": (
                "Design and implement the optional Unity Hub backend for the unsupported hub tools. "
                "Start with read-only editor discovery and install-path queries, keep it independent "
                "from the Unity Editor bridge, add tests before changing coverage status, and leave "
                "install/set-path commands guarded until progress and error handling are reliable."
            ),
        }
    ]


def _count_by_key(tools: list[Dict[str, Any]], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for tool in tools:
        value = str(tool.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _coverage_handoff_plan(tools: list[Dict[str, Any]]) -> Dict[str, Any]:
    deferred = [tool for tool in tools if tool.get("coverageStatus") == "deferred"]
    unsupported = [tool for tool in tools if tool.get("coverageStatus") == "unsupported"]
    fixture_plans = _coverage_fixture_plans(tools)
    support_plans = _coverage_support_plans(tools)

    tracks: list[Dict[str, Any]] = []
    if fixture_plans:
        tracks.append(
            {
                "name": "optional-package-live-audits",
                "status": "deferred",
                "toolCount": sum(int(plan["deferredToolCount"]) for plan in fixture_plans),
                "categories": [str(plan["category"]) for plan in fixture_plans],
                "nextCommand": "cli-anything-unity-mcp --json tool-coverage --status deferred --summary --fixture-plan",
                "ownerHint": "Assign to contributors with the optional Unity packages installed in a disposable project.",
            }
        )
    if support_plans:
        tracks.append(
            {
                "name": "unity-hub-backend",
                "status": "unsupported",
                "toolCount": sum(int(plan["toolCount"]) for plan in support_plans),
                "categories": [str(plan["category"]) for plan in support_plans],
                "nextCommand": "cli-anything-unity-mcp --json tool-coverage --status unsupported --summary --support-plan",
                "ownerHint": "Assign separately from editor-bridge work because Hub commands do not run through the Unity Editor bridge.",
            }
        )

    return {
        "goal": "Coordinate remaining coverage without mixing editor-bridge, optional-package, and Unity Hub backend work.",
        "remainingToolCount": len(deferred) + len(unsupported),
        "deferredToolCount": len(deferred),
        "unsupportedToolCount": len(unsupported),
        "deferredByBlocker": _count_by_key(deferred, "coverageBlocker"),
        "unsupportedByBlocker": _count_by_key(unsupported, "coverageBlocker"),
        "tracks": tracks,
        "recommendedCommands": [
            "cli-anything-unity-mcp --json tool-coverage --summary",
            "cli-anything-unity-mcp --json tool-coverage --status deferred --summary --fixture-plan",
            "cli-anything-unity-mcp --json tool-coverage --status unsupported --summary --support-plan",
            "cli-anything-unity-mcp --json tool-coverage --status deferred --summary --next-batch 10",
        ],
        "handoffPrompt": (
            "Use this handoff plan before assigning coverage work. Keep optional-package live audits "
            "separate from Unity Hub backend integration, start with read-only checks, and only change "
            "coverage status after tests and cleanup are reliable."
        ),
    }


def _coverage_evidence_summary(counts_by_status: Dict[str, int]) -> Dict[str, Any]:
    live_verified = int(counts_by_status.get("live-tested", 0))
    automated_covered = int(counts_by_status.get("covered", 0))
    mock_only = int(counts_by_status.get("mock-only", 0))
    deferred = int(counts_by_status.get("deferred", 0))
    unsupported = int(counts_by_status.get("unsupported", 0))
    remaining = deferred + unsupported
    return {
        "liveVerifiedCount": live_verified,
        "automatedCoveredCount": automated_covered,
        "mockOnlyCount": mock_only,
        "remainingCount": remaining,
        "remainingByStatus": {
            "deferred": deferred,
            "unsupported": unsupported,
        },
        "headline": (
            f"{live_verified} live-verified, "
            f"{automated_covered} automated-covered, "
            f"{mock_only} mock-only, "
            f"{remaining} remaining"
        ),
        "note": (
            "Do not blend live-tested, covered, and mock-only into one confidence percentage. "
            "Report them separately."
        ),
    }


def build_tool_coverage_matrix(
    category: str | None = None,
    status: str | None = None,
    search: str | None = None,
    include_unsupported: bool = True,
    summary_only: bool = False,
    next_batch_limit: int = 0,
    fixture_plan: bool = False,
    support_plan: bool = False,
    handoff_plan: bool = False,
) -> Dict[str, Any]:
    status_filter = (status or "").strip().lower() or None
    if status_filter and status_filter not in COVERAGE_STATUSES:
        raise ValueError(
            f"Unsupported coverage status `{status}`. Expected one of: {', '.join(COVERAGE_STATUSES)}."
        )

    tools: List[Dict[str, Any]] = []
    for tool in iter_upstream_tools(
        category=category,
        search=search,
        include_unsupported=True,
    ):
        coverage_status, note, blocker = _coverage_status(tool)
        if not include_unsupported and coverage_status == "unsupported":
            continue
        if status_filter and coverage_status != status_filter:
            continue
        item = dict(tool)
        resolved_route = _resolved_tool_route(item)
        if resolved_route and resolved_route != item.get("route"):
            item["resolvedRoute"] = resolved_route
        item["coverageStatus"] = coverage_status
        item["coverageNote"] = note
        item["coverageBlocker"] = blocker
        tools.append(item)

    tools.sort(key=lambda item: str(item.get("name", "")))

    counts_by_status = {name: 0 for name in COVERAGE_STATUSES}
    counts_by_category: Dict[str, Dict[str, int]] = {}
    for tool in tools:
        coverage_status = str(tool["coverageStatus"])
        counts_by_status[coverage_status] = counts_by_status.get(coverage_status, 0) + 1
        category_name = str(tool.get("category") or "uncategorized")
        category_counts = counts_by_category.setdefault(
            category_name,
            {"total": 0, **{name: 0 for name in COVERAGE_STATUSES}},
        )
        category_counts["total"] += 1
        category_counts[coverage_status] = category_counts.get(coverage_status, 0) + 1

    summary = {
        "catalogVersion": str(get_upstream_catalog().get("version") or "unknown"),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totalTools": len(tools),
        "countsByStatus": counts_by_status,
        "evidenceSummary": _coverage_evidence_summary(counts_by_status),
        "countsByCategory": counts_by_category,
        "filters": {
            "category": category,
            "status": status_filter,
            "search": search,
            "includeUnsupported": include_unsupported,
            "summaryOnly": summary_only,
            "nextBatchLimit": next_batch_limit,
            "fixturePlan": fixture_plan,
            "supportPlan": support_plan,
            "handoffPlan": handoff_plan,
        },
    }

    payload: Dict[str, Any] = {"summary": summary}
    if next_batch_limit > 0:
        payload["nextBatch"] = _coverage_next_batch(tools, next_batch_limit)
    if fixture_plan:
        payload["fixturePlans"] = _coverage_fixture_plans(tools)
    if support_plan:
        payload["supportPlans"] = _coverage_support_plans(tools)
    if handoff_plan:
        payload["handoffPlan"] = _coverage_handoff_plan(tools)
    if not summary_only:
        payload["tools"] = tools
    return payload
