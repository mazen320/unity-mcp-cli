# Unity MCP CLI

`unity-mcp-cli` is a Codex-first CLI harness for the AnkleBreaker Unity MCP bridge.

Instead of exposing Unity through MCP tool registration, this project talks directly to the Unity plugin's local HTTP bridge and uses the shared instance registry to discover running editors.

The result is a lighter, easier-to-debug workflow that still uses the real Unity-side backend.

## What This Repo Is

This repository publishes the standalone CLI layer only.

It is meant for people who want:

- a shell-friendly way to drive Unity
- lower overhead than a full MCP session
- a good fit for Codex and other command-driven agents
- direct access to the same Unity backend the MCP stack uses

## What You Need

To use this repo, you need:

- Python `3.11+`
- a Unity project with the AnkleBreaker Unity MCP plugin installed
- the Unity Editor running so the plugin can start its local bridge

Python dependency requirements are intentionally small:

- `click>=8.1`

## What You Do Not Need

You do not need the `unity-mcp-server` repo to use this CLI.

For normal usage, the setup is:

1. Install the Unity plugin in your Unity project.
2. Run Unity so the bridge starts.
3. Use this CLI repo to talk to that bridge.

The old server repo matters only if you want the MCP transport layer itself.

## How It Works

The system is split into two layers:

- Unity plugin: the real backend that edits scenes, scripts, components, assets, and play mode
- This CLI: a direct client for that backend over `127.0.0.1`

That means this repo is not reimplementing Unity behavior. It is wrapping the existing Unity bridge in a CLI that is easier for Codex to drive.

## Installation

From the repository root:

```powershell
python -m pip install -r requirements.txt
python -m pip install -e .
```

The shorter path also works:

```powershell
python -m pip install -e .
```

After installation, the command is:

```powershell
cli-anything-unity-mcp
```

## Quick Start

1. Open your Unity project.
2. Make sure the Unity MCP plugin is installed in that project.
3. Wait for Unity to log the bridge port.
4. From this repo, install the CLI and connect to the running editor.

```powershell
cli-anything-unity-mcp instances
cli-anything-unity-mcp select <port>
cli-anything-unity-mcp --json workflow inspect --port <port>
cli-anything-unity-mcp --json workflow create-behaviour PlayerMover --port <port>
cli-anything-unity-mcp --json workflow validate-scene --include-hierarchy --port <port>
```

## What It Can Do

- discover running Unity instances
- inspect project, scene, editor, hierarchy, and assets
- create and update scripts
- create scene objects and attach components
- wire serialized references between scene objects and assets
- create prefabs and instantiate them back into the scene
- validate scenes for missing references and compile problems
- control play mode with recovery when the bridge rebinds
- run high-level smoke tests that clean up after themselves
- fall back to raw `tool` and `route` calls when a dedicated command does not exist yet

## Main Commands

- `workflow inspect`
- `workflow create-behaviour`
- `workflow wire-reference`
- `workflow create-prefab`
- `workflow validate-scene`
- `workflow reset-scene`
- `workflow smoke-test`
- `play play`
- `play stop`
- `tool`
- `route`

More beginner-friendly docs live in `START_HERE.md`.

## Current Status

This project is already useful for real Unity authoring work. It has been live-tested against a real Unity project for:

- script creation
- component attachment
- serialized reference wiring
- prefab creation and instantiation
- scene validation
- scene reset with explicit save or discard behavior
- play-mode enter and stop
- cleanup-safe smoke testing

## Known Limitations

- This repo depends on the Unity plugin being present in the target Unity project.
- If you want to publish Unity-side fixes, those belong in a separate plugin fork or plugin PR.
- Some bridge routes can vary by plugin version, so the CLI includes fallbacks where possible.

## Validation

```powershell
python -m unittest cli_anything.unity_mcp.tests.test_core cli_anything.unity_mcp.tests.test_full_e2e -v
cli-anything-unity-mcp --help
```

## Repo Layout

```text
agent-harness/
├── README.md
├── START_HERE.md
├── TEST.md
├── requirements.txt
├── setup.py
└── cli_anything/
    └── unity_mcp/
```

## Credits

This project was inspired by CLI-Anything and built around the AnkleBreaker Unity MCP ecosystem:

- [AnkleBreaker-Studio/unity-mcp-server](https://github.com/AnkleBreaker-Studio/unity-mcp-server)
- [AnkleBreaker-Studio/unity-mcp-plugin](https://github.com/AnkleBreaker-Studio/unity-mcp-plugin)

This repository publishes the CLI layer only.
