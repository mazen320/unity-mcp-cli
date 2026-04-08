# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Added

- local upstream tool-catalog snapshot and schema-aware discovery commands
- MCP-style meta-tool support for advanced-tool browsing and project-context access
- `workflow build-sample` for generating a complete demo slice with scripts, transforms, prefab cloning, reference wiring, validation, play-mode checks, and optional cleanup

### Improved

- route resolution for plugin variants such as `unity_scene_stats`
- mock bridge coverage for transforms, parenting, prefab instantiation, and recursive scene cleanup
- docs and test plan coverage for the higher-level sample-building workflow
- public contribution flow with a lightweight CLA policy, commit sign-off guidance, and PR checklist updates

## 0.1.0 - 2026-04-08

Initial public-ready release of the CLI harness.

### Added

- direct CLI access to the Unity plugin bridge without MCP transport overhead
- REPL-first command flow with `--json` output
- instance discovery, selection, history, and session persistence
- route and tool passthrough commands for bridge coverage
- high-level workflows for inspect, behavior creation, scene reset, smoke testing, reference wiring, prefab creation, and scene validation
- play-mode recovery support for temporary bridge rebinds
- beginner-friendly docs and contributor docs
- issue templates, PR template, security policy, and repository hygiene files

### Verified

- editable install via `python -m pip install -e .`
- unit and end-to-end test coverage through `unittest`
- live authoring flows against a real Unity project
