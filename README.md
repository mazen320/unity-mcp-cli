# Unity MCP CLI

`unity-mcp-cli` is a Codex-first CLI harness for the AnkleBreaker Unity MCP editor bridge.

Instead of exposing Unity through MCP tool registration, this project talks directly to the Unity plugin's localhost HTTP bridge and uses the shared instance registry to discover running Unity editors.

This keeps the backend power of the Unity plugin while cutting out the extra MCP overhead.

## Requirements

To use this project, you need:

- Python `3.11` or newer
- a Unity project with the AnkleBreaker Unity MCP plugin installed and running in the editor
- localhost access to the Unity bridge started by that plugin

Python dependency requirements are intentionally small:

- `click>=8.1`

They are listed in `requirements.txt` and also in `setup.py`.

## Installation

Clone the repo, then from the repository root run:

```powershell
python -m pip install -r requirements.txt
python -m pip install -e .
```

If you do not care about `requirements.txt`, this also works:

```powershell
python -m pip install -e .
```

## Why This Exists

- lower overhead than a full MCP session
- easier to debug because every action is a CLI command
- works well with Codex and shell-driven agents
- keeps the Unity plugin as the real backend, so scenes, scripts, components, prefabs, and play mode still work

## What It Can Do

- inspect the active Unity project and scene
- create MonoBehaviour scripts and attach them to scene objects
- wire serialized references between objects and assets
- save scene objects as prefabs and instantiate them back into the scene
- validate scenes for missing references and compilation issues
- run rollback-friendly smoke tests
- drive play mode with recovery when the Unity bridge rebinds during Play Mode transitions

## Quick Start

1. Open your Unity project.
2. Make sure the AnkleBreaker Unity MCP plugin is installed in that project.
3. Wait for Unity to log that the bridge server started and note the port.
4. From this repo, install the CLI and connect to the running editor.

```powershell
python -m pip install -e .
cli-anything-unity-mcp instances
cli-anything-unity-mcp select 7891
cli-anything-unity-mcp --json workflow inspect --port 7891
cli-anything-unity-mcp --json workflow create-behaviour PlayerMover --port 7891
cli-anything-unity-mcp --json workflow validate-scene --include-hierarchy --port 7891
```

## Main Commands

- `workflow inspect`
- `workflow create-behaviour`
- `workflow wire-reference`
- `workflow create-prefab`
- `workflow validate-scene`
- `workflow smoke-test`
- `play play`
- `play stop`

More beginner-friendly usage notes live in `START_HERE.md`.

## How People Use It

The normal flow is:

1. Unity starts the local bridge through the plugin.
2. This CLI discovers that running Unity instance through the shared registry and ping checks.
3. You run either high-level `workflow` commands or lower-level `tool` and `route` commands.
4. The CLI sends HTTP requests directly to Unity on `127.0.0.1`.

So people do not use this by itself.
They use it together with the Unity plugin running inside their Unity project.

## Validation

```powershell
python -m unittest cli_anything.unity_mcp.tests.test_core cli_anything.unity_mcp.tests.test_full_e2e -v
cli-anything-unity-mcp --help
```

## Credits

This project was inspired by CLI-Anything and built around the AnkleBreaker Unity MCP ecosystem:

- https://github.com/AnkleBreaker-Studio/unity-mcp-server
- https://github.com/AnkleBreaker-Studio/unity-mcp-plugin

This repository publishes the standalone CLI layer only.
