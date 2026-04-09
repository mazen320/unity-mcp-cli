# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Added

- local upstream tool-catalog snapshot and schema-aware discovery commands
- generated tool coverage matrix JSON and a `tool-coverage` command for tracking live-tested, covered, unsupported, and deferred upstream tools
- saved optional sidecar agent profiles plus CLI commands for `agent current`, `agent list`, `agent save`, `agent use`, `agent clear`, and `agent remove`
- live agent inspection commands for `agent sessions`, `agent log`, and `agent queue`
- MCP-style meta-tool support for advanced-tool browsing and project-context access
- optional thin MCP adapter entry point, `cli-anything-unity-mcp-mcp`
- curated MCP tool registry that delegates into the existing CLI/core
- live MCP pass runner script for repeatable checks against a real Unity editor
- named live-pass profiles for focused validation runs such as `ui`, `lighting`, `terrain`, `graphics`, `advanced`, and `heavy`
- `workflow audit-advanced` for repeatable validation of safe advanced-tool categories and disposable probe-backed graphics/physics checks
- Unity debug snapshot/template commands for bundling console, compilation, scene, hierarchy, and queue state into a reusable CLI-first debug flow
- `debug watch` for repeatedly sampling Unity console/editor/queue state over time without rerunning snapshot by hand
- `agent watch` for sampling queue, sessions, logs, and debug snapshot summaries over time
- explicit CLI progress trace entries so multi-step workflows can write substeps into both `debug trace` and the Unity Console
- persisted `debug settings` for Unity Console breadcrumb control and dashboard defaults
- `debug dashboard`, a local browser UI for live doctor findings, trace entries, bridge diagnostics, Unity console state, and Editor.log context

### Improved

- route resolution for plugin variants such as `unity_scene_stats`
- graphics advanced tools now normalize `objectPath` to `gameObjectPath` for plugin compatibility
- mock bridge coverage for transforms, parenting, prefab instantiation, and recursive scene cleanup
- MCP adapter coverage for initialize, tools/list, and real tools/call flows against the mock Unity bridge
- curated MCP matrix coverage now exercises most of the high-level tool surface in one pass
- the live MCP pass runner can now emit debug reports, capture failure console snapshots, and follow Unity editor port rebinds during play-mode transitions
- the live MCP pass runner can now prepare a dirty scene explicitly with `--prepare-scene save|discard` before mutating validation steps
- `workflow audit-advanced` now probes UI, audio, lighting, animation, input, shadergraph, terrain, and navmesh in addition to the earlier core categories, with built-in asset cleanup
- docs and test plan coverage for CLI-first validation, debugging, and advanced-tool auditing
- public contribution flow with a lightweight CLA policy, commit sign-off guidance, and PR checklist updates
- tool coverage entries now include blocker labels so deferred tools are grouped as live-audit work, package-dependent work, environment-sensitive work, or true Hub integration gaps
- Unity console summaries now normalize common plugin log types like `log` into useful snapshot severity output
- automatic Unity breadcrumbs now use more specific workflow wording, including substeps like `Checking project info`, `Checking editor state`, and `Listing assets in Assets/...`
- `debug editor-log` now supports context windows around matches so bridge lines can be inspected with the surrounding reload/import activity

### Changed

- removed deprecated sample/scaffold workflows from the public CLI and MCP surface so the repo stays focused on the CLI/debugging/tooling layer

## 0.1.0 - 2026-04-08

Initial public-ready release of the CLI harness.

### Added

- direct CLI access to the Unity plugin bridge without MCP transport overhead
- REPL-first command flow with `--json` output
- instance discovery, selection, history, and session persistence
- route and tool passthrough commands for bridge coverage
- high-level workflows for inspect, behavior creation, scene reset, reference wiring, prefab creation, and scene validation
- play-mode recovery support for temporary bridge rebinds
- beginner-friendly docs and contributor docs
- issue templates, PR template, security policy, and repository hygiene files

### Verified

- editable install via `python -m pip install -e .`
- unit and end-to-end test coverage through `unittest`
- live authoring flows against a real Unity project
