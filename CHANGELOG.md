# Changelog

All notable changes to this project will be documented in this file.

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
