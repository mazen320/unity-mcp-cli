# Unity CLI Guide

This guide explains the new `cli-anything-unity-mcp` setup in plain language.

## What This Is

This CLI lets Codex control Unity without using MCP as the transport layer.

Think of the system like this:

1. Unity bridge:
   This is the Unity-side code that actually edits scenes, scripts, components, assets, and build settings.

2. Bridge choices:
   The standalone File IPC bridge in this repo handles core local routes without the AnkleBreaker plugin. The AnkleBreaker plugin HTTP bridge handles the broader advanced route surface.

3. This CLI repo:
   This skips the MCP protocol layer and talks directly to whichever Unity bridge you choose.

So this is not a complete clean-room rewrite of the whole Unity backend yet. It is a separate CLI/client layer with a growing standalone File IPC bridge for core routes and compatibility with the full upstream plugin for advanced routes.

## Why Use This

The main reason is cost and simplicity.

Benefits:
- lower overhead than a full MCP tool session
- easier to debug because every action is just a command
- works well with Codex because Codex can call shell commands directly
- can run core routes without the AnkleBreaker plugin through File IPC
- can still use the upstream plugin backend when you need the full advanced surface

Tradeoffs:
- no native MCP tool registry inside the client
- Codex needs good prompting so it knows which CLI commands to run
- some workflows may need extra wrappers to feel as smooth as native MCP tools

## Requirements

Before someone can use this setup, they need:

- Python `3.11` or newer
- either the File IPC bridge scripts from this repo or the AnkleBreaker Unity MCP plugin installed in their Unity project
- the Unity Editor running

If they want the no-AnkleBreaker-plugin core path, send them here:

- [FILE_IPC.md](FILE_IPC.md)

If they want the full advanced plugin path, send them here:

- [PLUGIN_SETUP.md](PLUGIN_SETUP.md)

Python package requirements are intentionally small:

- `click>=8.1`

That dependency is listed in both `requirements.txt` and `setup.py`.

## Which Repo Is The Real Project?

For most people, this CLI repo is the real project.

For the core route path, you only need the File IPC bridge scripts copied into the Unity project. For the full advanced route path, you need the AnkleBreaker Unity plugin installed inside the Unity project you want to control. You do not need to actively maintain a separate plugin source fork unless you are changing Unity-side backend behavior.

Simple rule:

- customize this CLI repo for your workflows
- use File IPC when the core standalone route surface is enough
- use the upstream plugin when you need advanced routes we have not rebuilt yet
- only fork the plugin when a fix cannot be solved in this CLI or standalone bridge layer

## Installation

From the repository root:

```powershell
python -m pip install -r requirements.txt
python -m pip install -e .
```

If they prefer the shortest path:

```powershell
python -m pip install -e .
```

After installation, the command will be available as:

```powershell
cli-anything-unity-mcp
```

## The Unity Bridge Part

The Python CLI alone is not enough. Unity needs a bridge inside the project.

You have two options.

### Option A: Standalone File IPC

This path does not require the AnkleBreaker plugin for core routes.

Copy these files into your Unity project's `Assets/Editor/` folder:

```text
unity-scripts/Editor/FileIPCBridge.cs
unity-scripts/Editor/StandaloneRouteHandler.cs
```

Wait for Unity to compile and look for:

```text
[FileIPC] Bridge initialized at .../.umcp
```

Then run:

```powershell
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json state
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json scene-info
```

See [FILE_IPC.md](FILE_IPC.md) for the full standalone setup.

### Option B: Full Plugin HTTP Bridge

Use this when you need the full advanced route surface.

Shortest setup:

1. Open the Unity project.
2. Go to `Window > Package Manager`.
3. Click `+`.
4. Choose `Add package from git URL...`
5. Paste:

```text
https://github.com/AnkleBreaker-Studio/unity-mcp-plugin.git
```

6. Click `Add`.
7. Wait for Unity to compile.
8. Check the Unity Console for a line like:

```text
[AB-UMCP] Server started on port 7891
```

That means the bridge is live.

## What It Can Do Right Now

The CLI already supports the broad surface below when the matching Unity-side bridge supports the route. The standalone File IPC subset is listed in [FILE_IPC.md](FILE_IPC.md); the full advanced surface still uses the plugin HTTP bridge today.

- standalone File IPC: core scene, hierarchy, editor, console, compilation, GameObject, component, asset, script, undo/redo, screenshot, and native panel routes
- plugin HTTP bridge: the broader advanced route surface while we keep expanding standalone coverage

Across the full CLI surface:
- discovering running Unity instances
- selecting the Unity instance to target
- browsing a large local compatibility catalog generated from the upstream Unity MCP tool surface
- searching tools by name/category/tier and inspecting their input schema
- collecting a combined high-level project snapshot with one command
- creating a MonoBehaviour script and attaching it to a new scene object
- wiring serialized object references between scene objects and assets
- saving scene objects as prefabs and instantiating them again
- validating a scene for missing references, compilation issues, and object/component counts
- running a reversible smoke test that creates temporary content and cleans it up
- reading editor state and scene info
- opening scenes with explicit save/discard behavior
- listing assets and hierarchy
- reading, creating, and updating scripts
- creating and deleting scene objects
- adding components
- reading and setting serialized component properties
- running arbitrary C# editor code
- querying queue info, routes, and project context
- starting builds
- undo and redo
- interactive REPL mode

There are also two generic escape hatches:
- `tool`
  Use Unity-style tool names such as `unity_gameobject_create`
- `route`
  Call raw bridge routes such as `scene/info`

These are important because they keep the harness useful even if we have not added a dedicated top-level CLI command yet.

There is also now a richer discovery layer:

- `tools`
  Browse the upstream-style tool catalog by category, tier, or search term
- `advanced-tools`
  Focus on the advanced part of the tool surface, like terrain, shadergraph, animation, or UI
- `tool-info`
  Inspect one tool's route, description, tier, and input schema

## What Was Live-Tested

The live Unity project acceptance pass confirmed:

- instance discovery worked against a real editor instance
- project info, hierarchy, and asset listing worked
- a temporary script asset was created in the real project
- Unity compiled that script with zero errors
- a temporary GameObject was created in the real scene
- the new component was attached successfully
- component properties were read and updated successfully
- the temporary object and script were deleted successfully
- the scene was restored to a clean state afterward
- play mode enter and stop were both confirmed through live state polling
- the full high-level smoke test completed with play mode enabled and cleaned up after itself
- the new sample-builder created a full demo slice with generated scripts, primitives, prefab cloning, reference wiring, validation, and cleanup in a real Unity project
- the advanced-tool audit passed live across memory, graphics, sceneview, settings, profiler, testing, and disposable physics probes without leaving scene changes behind

That means the CLI is already capable of real authoring work in your project.

It also now has a higher-level workflow layer so Codex does not need to manually stitch every low-level route together for common tasks.

It does not mean the whole upstream Unity backend disappeared. The core File IPC path works without the AnkleBreaker plugin, but the broad advanced surface still depends on the Unity plugin being present in the target project.

## Known Rough Edges

These are the main issues observed so far:

1. Console log freshness may need work.
   `execute-code` ran successfully, but the expected fresh log message was not visible in the returned console buffer during one live test.

2. Some live plugin route catalogs are optimistic.
   In one live session, `scene/stats` appeared in the route list but still returned `Unknown API endpoint`. The CLI now falls back gracefully during scene validation when that happens.

3. Codex desktop sandbox permissions can block writes to default app-data locations.
   The CLI now falls back to a workspace-local session file when that happens, so it still works inside Codex.

These issues do not block normal scene, script, component, asset, or play-mode control.

## Basic Workflow

From the `agent-harness` folder:

```powershell
cli-anything-unity-mcp instances
cli-anything-unity-mcp select 7893
cli-anything-unity-mcp workflow inspect --port 7893
cli-anything-unity-mcp workflow create-behaviour PlayerMover --port 7893
cli-anything-unity-mcp scene-info --port 7893
cli-anything-unity-mcp state --port 7893
cli-anything-unity-mcp play play --port 7893
cli-anything-unity-mcp play stop --port 7893
```

Interactive mode:

```powershell
cli-anything-unity-mcp
```

Then type commands like:

```text
instances
select 7893
scene-info --port 7893
tool unity_gameobject_create --params {"name":"Probe","primitiveType":"Empty"} --port 7893
```

Machine-readable mode:

```powershell
cli-anything-unity-mcp --json project-info --port 7893
```

Catalog examples:

```powershell
cli-anything-unity-mcp --json tools --search terrain
cli-anything-unity-mcp --json advanced-tools --category terrain
cli-anything-unity-mcp --json tool-info unity_scene_stats
cli-anything-unity-mcp --json tool unity_list_advanced_tools --param category=terrain
```

## High-Level Workflows

These are the best commands to start with if you want Codex to behave more like a teammate and less like a raw transport client.

Inspect the current project and scene in one shot:

```powershell
cli-anything-unity-mcp --json workflow inspect --port 7893
```

Create a new MonoBehaviour script and attach it to a new scene object:

```powershell
cli-anything-unity-mcp --json workflow create-behaviour PlayerMover --port 7893
```

Put the script in a custom folder or namespace:

```powershell
cli-anything-unity-mcp --json workflow create-behaviour EnemyBrain --folder Assets/Scripts/AI --namespace OutsideTheBox.AI --port 7893
```

Reload the current scene safely:

```powershell
cli-anything-unity-mcp workflow reset-scene --discard-unsaved --port 7893
```

Wire a serialized reference on a gameplay component:

```powershell
cli-anything-unity-mcp --json workflow wire-reference PlayerSpawner EnemySpawner PrefabToSpawn --asset-path Assets/Prefabs/Enemy.prefab --port 7893
```

Save a scene object as a prefab and spawn a copy back into the scene:

```powershell
cli-anything-unity-mcp --json workflow create-prefab EnemyRoot --instantiate --instance-name EnemyClone --port 7893
```

Validate the current scene before doing more work:

```powershell
cli-anything-unity-mcp --json workflow validate-scene --include-hierarchy --port 7893
```

Run a reusable advanced-tool audit:

```powershell
cli-anything-unity-mcp --json workflow audit-advanced --port 7893
```

Focus on only the categories you care about:

```powershell
cli-anything-unity-mcp --json workflow audit-advanced --category graphics --category physics --port 7893
```

Save paired Game View and Scene View screenshots before or after a visual edit:

```powershell
cli-anything-unity-mcp --json debug capture --kind both --port 7893
```

## When To Use `tool` vs `route`

Use `tool` when you already know the old Unity MCP tool name:

```powershell
cli-anything-unity-mcp --json tool unity_component_add --params "{\"gameObjectPath\":\"Player\",\"componentType\":\"Rigidbody2D\"}" --port 7893
```

Use `route` when you want raw bridge access:

```powershell
cli-anything-unity-mcp --json route scene/info --port 7893
```

If you are unsure which exists, run:

```powershell
cli-anything-unity-mcp tools
cli-anything-unity-mcp tools --live --port 7893
cli-anything-unity-mcp routes --port 7893
```

## Safe Scene Reloads

This matters for cleanup and testing.

If the active scene is dirty and you try to reopen it, the CLI now avoids trapping you in Unity's save popup by default.

Instead, it returns a structured response telling you a decision is required.

Example:

```powershell
cli-anything-unity-mcp scene-open Assets/Scenes/SampleScene.unity --port 7893
```

If you want to discard temporary test changes without a popup:

```powershell
cli-anything-unity-mcp scene-open Assets/Scenes/SampleScene.unity --discard-unsaved --port 7893
```

If you want to save first:

```powershell
cli-anything-unity-mcp scene-open Assets/Scenes/SampleScene.unity --save-if-dirty --port 7893
```

This is the recommended cleanup pattern for Codex-driven temporary probes.

## Play Mode Behavior

The `play` command now waits for a real editor-state transition instead of returning immediately and leaving you guessing.

It is also more resilient to the Unity bridge briefly disappearing or rebinding to a different port during Play Mode transitions.

Examples:

```powershell
cli-anything-unity-mcp play play --port 7893
cli-anything-unity-mcp play stop --port 7893
```

Optional controls:

```powershell
cli-anything-unity-mcp play play --timeout 15 --interval 0.5 --port 7893
cli-anything-unity-mcp play stop --no-wait --port 7893
```

## Best Setup Right Now

Best practical setup today:

1. Use `--transport file` and the File IPC bridge for core standalone work.
2. Keep the Unity plugin running only when you need advanced routes not yet supported by the standalone bridge.
3. Use this CLI as Codex's main Unity control path.
4. Prefer `--json` when the result will be read by another tool or agent.
5. For File IPC, always pass `--transport file --file-ipc-path <project>`. For plugin HTTP, pass `--port <port>` when you know the target instance.
6. Prefer the `workflow` commands first, then fall back to `tool` or `route` only when needed.

For actual game work, the best pattern right now is:

1. Start with `workflow inspect` or `workflow validate-scene`
2. Use `workflow create-behaviour` to add gameplay scripts quickly
3. Use `workflow wire-reference` to connect scene objects and prefab references
4. Use `workflow create-prefab` once an authored scene object becomes reusable
5. Use `workflow audit-advanced` when you want a broader compatibility pass across advanced tool categories

For your use case, this is the best current path if the main goal is:

"Let Codex do real Unity work without paying MCP overhead."

## Recommended Next Improvements

The highest-value next steps are:

1. Add more project-specific high-level commands.
   Examples: wire references, inspect missing references, create prefabs, capture scene screenshots.

2. Keep hardening runtime workflows.
   Console log freshness is still the main rough edge worth tightening.

3. Add a Codex skill or instruction file.
   This will teach Codex exactly how to prefer `workflow inspect`, `workflow validate-scene`, and `debug doctor` before dropping to lower-level commands.

4. Add more rollback-friendly authoring helpers.
   Examples: temporary-object workflows, prefab probes, and scene validation passes.
