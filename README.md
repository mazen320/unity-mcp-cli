# Unity MCP CLI

`unity-mcp-cli` is a CLI-first Unity assistant for Unity projects, built to work with the AnkleBreaker Unity MCP plugin and the standalone File IPC bridge scripts in this repo.

It talks directly to Unity through either the plugin's local HTTP bridge or the repo's file-based IPC bridge instead of relying on a full MCP tool-registration flow every turn. The result is a faster, easier-to-debug shell surface for Codex and other command-driven agents.

## Pick A Bridge

- Use [FILE_IPC.md](FILE_IPC.md) if you want the standalone core route path that does not require the AnkleBreaker Unity plugin.
- Use [PLUGIN_SETUP.md](PLUGIN_SETUP.md) if you want the full advanced AnkleBreaker plugin HTTP bridge path.

| Bridge | Best for | Needs plugin | Needs ports |
| --- | --- | --- | --- |
| File IPC | fast local scene work, debugging, core agent loop | no | no |
| Plugin HTTP | full advanced Unity route surface | yes | yes |

## Why This Exists

- Lower overhead than exposing everything through a giant MCP surface
- Better debugging for real Unity problems
- A shell-friendly workflow for Codex, scripts, and CI
- Direct access to Unity through either the standalone File IPC bridge or the upstream plugin HTTP bridge

## What It Does

- discovers running Unity editors
- inspects project, scene, hierarchy, console, compilation, queue, and editor state
- creates and edits scripts, scene objects, components, references, and prefabs
- captures Game View and Scene View screenshots
- explains likely Unity problems with `debug doctor`
- shows recent CLI activity with `debug trace`
- reads the real Unity `Editor.log`
- reads optional Unity MCP project context without using the plugin's main-thread-unsafe direct context endpoint first
- exposes an optional thin MCP adapter when a client still needs MCP transport

## What This Repo Is

This repo is the CLI/client layer plus optional Unity Editor bridge scripts.

It is not yet a full clean-room replacement for the deepest Unity backend surface. The full AnkleBreaker Unity-side plugin still powers the broad advanced route surface. The File IPC bridge in `unity-scripts/Editor/` is now a standalone-first direct path for core editor routes when you want zero-port setup, lower overhead, or no plugin dependency for day-to-day scene work.

If you are using this repo with Codex or another coding agent, read [AGENTS.md](AGENTS.md) first. It defines the intended CLI-first workflow, debugging loop, and verification expectations.

## What You Need

- Python `3.11+`
- `click>=8.1`
- a Unity project with either the AnkleBreaker Unity MCP plugin installed or the File IPC bridge scripts from `unity-scripts/Editor/`
- the Unity Editor running

If you want the zero-port fallback path, start with [FILE_IPC.md](FILE_IPC.md). If plugin setup is the unclear part, start with [PLUGIN_SETUP.md](PLUGIN_SETUP.md).

## Install

```powershell
python -m pip install -r requirements.txt
python -m pip install -e .
```

Or just:

```powershell
python -m pip install -e .
```

Main command:

```powershell
cli-anything-unity-mcp
```

Optional thin MCP adapter:

```powershell
cli-anything-unity-mcp-mcp --default-port <port> --port-range-start <port> --port-range-end <port>
```

## Quick Start

1. Open your Unity project.
2. Choose the Unity-side bridge:

- Full advanced surface: install the AnkleBreaker Unity plugin and wait for Unity to log a bridge port like `[AB-UMCP] Server started on port 7892`.
- Core local surface: copy `FileIPCBridge.cs` and `StandaloneRouteHandler.cs` into `Assets/Editor/` and wait for `[FileIPC] Bridge initialized at .../.umcp`.

From this repo, the plugin HTTP path looks like:

```powershell
cli-anything-unity-mcp instances
cli-anything-unity-mcp select <port>
cli-anything-unity-mcp --json workflow inspect --port <port>
cli-anything-unity-mcp --json debug doctor --port <port>
cli-anything-unity-mcp --json debug capture --kind both --port <port>
```

File IPC mode skips port discovery and talks through `.umcp` files in the Unity project:

```powershell
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json instances
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json state
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json scene-info
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json route --params '{"menuItem":"Window/CLI Anything"}' editor/execute-menu-item
```

If you want a reusable standalone verification pass instead of typing commands one by one:

```powershell
python .\scripts\run_file_ipc_smoke.py --file-ipc-path "C:/Projects/MyGame"
python .\scripts\run_file_ipc_smoke.py --file-ipc-path "C:/Projects/MyGame" --json
```

`CliAnythingWindow.cs` is optional. Copy it into `Assets/Editor/` if you want a native Unity panel at `Window > CLI Anything`.

Standalone File IPC is intentionally smaller than the full plugin route surface. It is good for core local control such as editor state, scene info, hierarchy, console, compilation errors, GameObject basics, component basics, script read/create, undo/redo, screenshots, agent session/log visibility, and opening the native CLI Anything panel. Use the AnkleBreaker plugin HTTP bridge when you need the full advanced catalog across terrain, animation, shaders, prefabs, packages, and other deep Unity systems.

Recent standalone File IPC live verification in `OutsideTheBox` also covered direct `context`, `search/scene-stats`, `search/missing-references`, `debug breadcrumb`, `console/log` breadcrumb readback, and `debug capture --kind both`.

Agents still work on the File IPC path. The agent process runs the CLI, the CLI tags commands with an `agentId`, and the Unity-side File IPC bridge records lightweight `agent sessions` / `agent log` state without background polling. File IPC executes directly on Unity's main thread, so it does not need the old HTTP queue for core routes.

## Using This With Codex

The intended pattern is:

1. use the CLI as the main Unity control surface
2. inspect and debug before making changes
3. verify with trace, editor log, and captures

Start here:

```powershell
cli-anything-unity-mcp --json workflow inspect --port <port>
cli-anything-unity-mcp --json debug doctor --port <port>
cli-anything-unity-mcp --json debug trace --tail 20
cli-anything-unity-mcp --json debug capture --kind both --port <port>
python .\scripts\run_live_mcp_pass.py --port <port> --summary-only
```

Normal commands now emit visible Unity-side `[CLI-TRACE]` breadcrumbs, so you can watch agent activity in the Unity Console or Editor log:

```powershell
cli-anything-unity-mcp debug editor-log --contains "CLI-TRACE" --follow
cli-anything-unity-mcp debug trace --follow --history --tail 12
cli-anything-unity-mcp --json debug trace --summary --tail 20
cli-anything-unity-mcp --json debug trace --summary --status error --tail 20
cli-anything-unity-mcp --json debug trace --category scene
cli-anything-unity-mcp --json debug trace --route scene/info
cli-anything-unity-mcp --json debug trace --tool unity_scene_stats
```

`debug trace --summary` now separates current `problemGroups` from normal recent activity, returns `recommendedCommands` when something is still failing, and renders a readable text report when you run it without `--json`.

If you want a more detailed live debugging surface, launch the local browser dashboard:

```powershell
cli-anything-unity-mcp debug dashboard --port <port>
```

If Unity Console breadcrumbs are getting noisy, you can turn them off without disabling local trace/history:

```powershell
cli-anything-unity-mcp --json debug settings --no-unity-console-breadcrumbs
cli-anything-unity-mcp --json debug settings --unity-console-breadcrumbs
```

For repeatable MCP validation, use the live-pass runner:

```powershell
python .\scripts\run_live_mcp_pass.py --port <port> --summary-only
python .\scripts\run_live_mcp_pass.py --port <port> --profile ui --debug --report-file .\.cli-anything-unity-mcp\live-pass-ui-debug.json
```

Text mode now reports counts, failures/timeouts, Unity bridge port hops, slowest steps, and the first useful follow-up command for each failed step. Use `--summary-only` when you only want the failure-first view, or `--json` when an agent needs the full structured report.

For multi-step workflows, those breadcrumbs now include substeps like:

- `locke-debug: Checking project info`
- `locke-debug: Checking editor state`
- `locke-debug: Inspecting scene hierarchy (depth 3, max 12 nodes)`
- `locke-debug: Listing assets in Assets/Scripts`

## Best Commands To Know

### General

```powershell
cli-anything-unity-mcp instances
cli-anything-unity-mcp select <port>
cli-anything-unity-mcp --json status --port <port>
cli-anything-unity-mcp --json workflow inspect --port <port>
```

### Debugging

```powershell
cli-anything-unity-mcp --json debug doctor --recent-commands 8 --port <port>
cli-anything-unity-mcp --json debug bridge --port <port>
cli-anything-unity-mcp --json debug trace --tail 20
cli-anything-unity-mcp --json debug settings
cli-anything-unity-mcp --json debug snapshot --console-count 100 --include-hierarchy --port <port>
cli-anything-unity-mcp --json debug capture --kind both --port <port>
cli-anything-unity-mcp --json debug editor-log --tail 120 --ab-umcp-only
cli-anything-unity-mcp --json agent queue
cli-anything-unity-mcp --json agent sessions
cli-anything-unity-mcp --json agent watch --iterations 1 --interval 0
cli-anything-unity-mcp debug dashboard --port <port>
python .\scripts\run_live_mcp_pass.py --port <port> --summary-only
```

### Tool Surface

```powershell
cli-anything-unity-mcp --json tools --search scene
cli-anything-unity-mcp --json tool-info unity_scene_stats
cli-anything-unity-mcp --json tool unity_scene_stats --port <port>
cli-anything-unity-mcp --json tool unity_get_project_context --port <port>
cli-anything-unity-mcp --json tool-coverage --summary
cli-anything-unity-mcp --json tool-coverage --category amplify --status deferred --summary --next-batch 5
cli-anything-unity-mcp --json tool-coverage --status deferred --summary --fixture-plan
cli-anything-unity-mcp --json tool-coverage --status unsupported --summary --support-plan
cli-anything-unity-mcp --json tool-coverage --summary --handoff-plan
```

## Coverage Snapshot

Current checked-in matrix:

- `328` upstream catalog tools
- `32` live-tested
- `37` covered
- `215` mock-only
- `38` deferred
- `6` unsupported

Important nuance:

- `unsupported` currently means Unity Hub-only functionality
- `deferred` means known work that still needs wrapper depth, live audits, or package-specific validation

Use:

```powershell
cli-anything-unity-mcp --json tool-coverage --summary
cli-anything-unity-mcp --json tool-coverage --status unsupported
cli-anything-unity-mcp --json tool-coverage --status deferred --category amplify
cli-anything-unity-mcp --json tool-coverage --status deferred --category amplify --summary --next-batch 5
cli-anything-unity-mcp --json tool-coverage --status deferred --summary --fixture-plan
cli-anything-unity-mcp --json tool-coverage --status unsupported --summary --support-plan
cli-anything-unity-mcp --json tool-coverage --summary --handoff-plan
```

`--next-batch` is the handoff view for contributors or parallel agents. It returns prioritized deferred tools with risk labels, required parameter templates, suggested commands, and a short audit prompt for live validation.

`--fixture-plan` is the package-level handoff view for the remaining deferred work. It groups Amplify and UMA by package, fixture root, preflight tools, safe mutation order, cleanup, and recommended commands.

`--support-plan` is the implementation-plan view for unsupported surfaces. Today that means the Unity Hub tools, which need a separate Hub backend rather than the editor bridge.

`--handoff-plan` is the quick "what is left?" view. It summarizes the remaining 44 tools into the optional-package live-audit track and the Unity Hub backend track.

## Product Direction

The main goal is to make this the best Unity CLI assistant surface:

- stronger debugging than raw MCP transport
- better recovery around play mode and bridge rebinding
- higher tool parity with the upstream ecosystem
- room for custom tools and eventually deeper backend independence

Validation should happen through CLI diagnostics, tool audits, and temporary probes. The shipped product surface is the CLI layer itself.

## Repo Boundaries

- You do **not** need `unity-mcp-server` to use this CLI.
- You do **not** need your own plugin fork just to use this CLI.
- You **do** need either the Unity plugin installed for the full route surface or the File IPC bridge scripts installed for the smaller core route surface.

This repo stays focused on the CLI layer. If you need more beginner setup help, use [START_HERE.md](START_HERE.md) and [PLUGIN_SETUP.md](PLUGIN_SETUP.md).

## Docs

- [START_HERE.md](START_HERE.md): beginner-friendly walkthrough
- [FILE_IPC.md](FILE_IPC.md): standalone core route setup without the AnkleBreaker plugin
- [PLUGIN_SETUP.md](PLUGIN_SETUP.md): plugin install steps
- [TEST.md](TEST.md): validation commands and test flows
- [TODO.md](TODO.md): roadmap and coverage work
- [ATTRIBUTION.md](ATTRIBUTION.md): upstream attribution and boundaries
- [CONTRIBUTING.md](CONTRIBUTING.md): contributor workflow

## Attribution

This project is a separate CLI/client layer built around Unity editor automation. It can run core routes through the standalone File IPC bridge without the AnkleBreaker plugin, while the full advanced route surface still uses the AnkleBreaker Unity MCP plugin.

See [ATTRIBUTION.md](ATTRIBUTION.md) for the exact repo boundary and upstream credit notes.

## License

This repository is MIT licensed. See [LICENSE](LICENSE).
