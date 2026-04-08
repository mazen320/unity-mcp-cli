# Unity MCP CLI

`unity-mcp-cli` is a Codex-first CLI client for Unity projects that use the AnkleBreaker Unity MCP bridge.

Instead of exposing Unity through MCP tool registration, this project talks directly to the Unity plugin's local HTTP bridge and uses the shared instance registry to discover running editors.

The result is a lighter, easier-to-debug workflow that still uses the real Unity-side backend.

## What This Repo Is

This repository publishes a separate CLI/client layer.

It is meant for people who want:

- a shell-friendly way to drive Unity
- lower overhead than a full MCP session
- a good fit for Codex and other command-driven agents
- direct access to the same Unity backend the upstream MCP stack uses

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

You also do not need your own plugin fork just to use this CLI.

Most users should:

1. install the upstream Unity plugin in their Unity project
2. keep this CLI repo as the thing they customize
3. only fork the plugin if they need Unity-side backend changes

## How It Works

The system is split into two layers:

- Upstream Unity plugin: the real backend that edits scenes, scripts, components, assets, and play mode
- This CLI repo: a direct client for that backend over `127.0.0.1`

That means this repo is not a clean-room replacement for the Unity backend. It is a separate CLI layer built to drive the existing bridge more efficiently from Codex and the shell.

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
cli-anything-unity-mcp --json workflow build-sample --name CodexArena --cleanup --port <port>
cli-anything-unity-mcp --json workflow create-behaviour PlayerMover --port <port>
cli-anything-unity-mcp --json workflow validate-scene --include-hierarchy --port <port>
```

## What It Can Do

- discover running Unity instances
- inspect project, scene, editor, hierarchy, and assets
- browse a 300+ tool compatibility snapshot generated from the upstream Unity MCP ecosystem
- inspect tool descriptions, tiers, routes, and input schemas with `tool-info`
- create and update scripts
- create scene objects and attach components
- wire serialized references between scene objects and assets
- create prefabs and instantiate them back into the scene
- build a complete sample gameplay slice that exercises scripts, transforms, references, prefabs, validation, and play mode
- run a reusable advanced-tool audit across safe categories and sample-backed graphics/physics probes
- validate scenes for missing references and compile problems
- control play mode with recovery when the bridge rebinds
- run high-level smoke tests that clean up after themselves
- emulate MCP-style meta-tools like `unity_list_advanced_tools` and `unity_advanced_tool`
- fall back to raw `tool` and `route` calls when a dedicated command does not exist yet

## Main Commands

- `tools`
- `advanced-tools`
- `tool-info`
- `workflow inspect`
- `workflow build-sample`
- `workflow audit-advanced`
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

## MCP Vocabulary Compatibility

One of the goals of this CLI is to let Codex keep using the upstream Unity MCP naming style without paying the MCP transport cost.

That means the CLI now understands important MCP meta-tools too:

- `unity_list_advanced_tools`
- `unity_advanced_tool`
- `unity_list_instances`
- `unity_select_instance`
- `unity_get_project_context`

Examples:

```powershell
cli-anything-unity-mcp --json advanced-tools --category terrain
cli-anything-unity-mcp --json tool-info unity_scene_stats
cli-anything-unity-mcp --json tool unity_list_advanced_tools --param category=terrain
cli-anything-unity-mcp --json tool unity_advanced_tool --params '{"tool":"unity_scene_stats","params":{}}'
```

## Current Status

This project is already useful for real Unity authoring work. It has been live-tested against a real Unity project for:

- script creation
- component attachment
- serialized reference wiring
- prefab creation and instantiation
- complete sample-scaffold generation with cleanup-safe validation
- reusable advanced-tool audits with disposable graphics/physics probes
- scene validation
- scene reset with explicit save or discard behavior
- play-mode enter and stop
- cleanup-safe smoke testing

## FAQ

### Do I need both the CLI repo and the plugin repo?

No.

You need:

- this CLI repo
- the Unity plugin installed in the Unity project you want to control

You do not need to actively work inside a plugin source clone unless you are changing the Unity-side backend itself.

### Do I need the `unity-mcp-server` repo?

No, not for this project.

This CLI talks directly to the Unity plugin bridge. The old server repo is only relevant if you want the MCP transport layer.

### What if the upstream plugin keeps changing?

That is expected.

The intended maintenance model for this repo is:

- keep the CLI as the main project
- stay compatible with upstream plugin releases where possible
- keep plugin-side patches small and upstreamable

### Should the plugin fork be public too?

Not necessarily.

The CLI can be your public project. A plugin fork only needs to be public if you want to publish Unity-side fixes or open upstream pull requests from it.

## Known Limitations

- This repo depends on the Unity plugin being present in the target Unity project.
- If you want to publish Unity-side fixes, those belong in a separate plugin fork or plugin PR.
- Some bridge routes can vary by plugin version, so the CLI includes fallbacks where possible.

## Project Boundaries

This repo is the CLI client only.

Work that belongs here:

- CLI commands
- workflow ergonomics
- session handling
- JSON output
- tests for bridge/client behavior
- docs for Codex and shell-driven use

Work that does not belong here:

- Unity Editor backend command implementations
- Unity-side scene or editor APIs
- plugin packaging for Unity projects

If a bug only exists because the Unity plugin behavior itself needs to change, that should usually go into a plugin fork or upstream plugin issue.

## Contributing

Contributions are welcome.

For local setup, testing, repo boundaries, and PR expectations, see [CONTRIBUTING.md](CONTRIBUTING.md).
For outside contributions, see [CLA.md](CLA.md) too.

If you are not sure whether a change belongs in this repo or the Unity plugin repo, open an issue first and describe the workflow you are trying to improve.

## Security

If you find a security problem, especially around local bridge exposure, unsafe code execution, or destructive editor actions, please follow [SECURITY.md](SECURITY.md) instead of opening a public issue first.

## Upstream Attribution

This CLI is a separate project, but it integrates with the upstream AnkleBreaker Unity MCP plugin and server ecosystem and still depends on that Unity-side backend at runtime.

If you distribute a product or tool that includes or depends on that upstream software, check the upstream license terms and attribution requirements. The upstream license explicitly asks for attribution such as:

- `Made with AnkleBreaker MCP`
- `Powered by AnkleBreaker MCP`

Project-specific guidance for this repo lives in [ATTRIBUTION.md](ATTRIBUTION.md).

## Validation

```powershell
python -m unittest cli_anything.unity_mcp.tests.test_core cli_anything.unity_mcp.tests.test_full_e2e -v
cli-anything-unity-mcp --help
```

## Repo Layout

```text
agent-harness/
├── ATTRIBUTION.md
├── CHANGELOG.md
├── README.md
├── START_HERE.md
├── TEST.md
├── requirements.txt
├── setup.py
└── cli_anything/
    └── unity_mcp/
```

## Credits

This project was inspired by CLI-Anything and built as a separate CLI layer for the AnkleBreaker Unity MCP ecosystem:

- [AnkleBreaker-Studio/unity-mcp-server](https://github.com/AnkleBreaker-Studio/unity-mcp-server)
- [AnkleBreaker-Studio/unity-mcp-plugin](https://github.com/AnkleBreaker-Studio/unity-mcp-plugin)

This repository publishes the CLI/client layer only. It does not claim ownership of the upstream Unity backend.

## License

This repository is licensed under the MIT License for the code in this repo. See [LICENSE](LICENSE).

Compatibility with the Unity plugin does not change the upstream license terms of the plugin itself. If you use or distribute the plugin, check the upstream plugin and server repositories for their own license terms.
