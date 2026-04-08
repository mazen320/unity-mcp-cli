# Contributing

Thanks for helping improve `unity-mcp-cli`.

## Before You Start

Please check whether your change belongs in this repo.

This repo owns:

- CLI commands
- workflow helpers
- bridge discovery and recovery logic
- JSON output and REPL behavior
- docs and tests for the CLI layer

This repo does not own:

- Unity plugin internals
- Unity Editor command implementations
- Unity-side API additions that only exist inside the plugin

If your fix depends on changing Unity plugin behavior, open an issue here for tracking if useful, but plan to also update the plugin fork or upstream plugin repo.

## Local Setup

From the repo root:

```powershell
python -m pip install -r requirements.txt
python -m pip install -e .
```

## Run Tests

```powershell
python -m unittest cli_anything.unity_mcp.tests.test_core cli_anything.unity_mcp.tests.test_full_e2e -v
```

If you add or change CLI behavior, update tests in both places when relevant:

- `test_core.py` for isolated behavior
- `test_full_e2e.py` for realistic workflows and bridge interaction

## Development Guidelines

- Keep the CLI stateful, scriptable, and JSON-friendly.
- Prefer wrapping real bridge behavior instead of reimplementing Unity logic in Python.
- Preserve the REPL-first experience when adding new commands.
- Add fallbacks when live bridge behavior is inconsistent across plugin versions.
- Keep docs beginner-friendly. If a new command is important, update `README.md` and `START_HERE.md`.

## Pull Requests

Good PRs usually include:

- a short explanation of the user workflow being improved
- the code change
- test coverage or a reason tests could not be added
- doc updates for user-facing behavior

If your PR changes public command behavior, include before/after examples in the description.

## Scope Tips

Good issues and PRs for this repo:

- better workflow commands
- stronger play-mode recovery
- clearer errors
- improved discovery and session behavior
- better JSON output for agent use
- docs, templates, packaging, and contributor ergonomics

Issues that may belong elsewhere:

- new Unity-side bridge routes
- editor features that require new C# backend support
- plugin serialization bugs
- scene save behavior controlled entirely inside the Unity plugin
