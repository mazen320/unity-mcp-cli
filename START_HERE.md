# Unity CLI Guide

This guide explains the new `cli-anything-unity-mcp` setup in plain language.

## What This Is

This CLI lets Codex control Unity without using MCP as the transport layer.

Think of the system like this:

1. Unity plugin:
   This is the real backend. It runs inside the Unity Editor and actually edits scenes, scripts, components, assets, and build settings.

2. Old MCP server:
   This sits between the AI and the Unity plugin. It translates MCP tool calls into local HTTP requests to the plugin.

3. New CLI:
   This skips the MCP protocol layer and talks directly to the same Unity plugin over localhost.

So the CLI is not a fake replacement. It uses the same Unity-side bridge that the MCP setup uses.

## Why Use This

The main reason is cost and simplicity.

Benefits:
- lower overhead than a full MCP tool session
- easier to debug because every action is just a command
- works well with Codex because Codex can call shell commands directly
- keeps most of the same Unity power because the plugin backend is unchanged

Tradeoffs:
- no native MCP tool registry inside the client
- Codex needs good prompting so it knows which CLI commands to run
- some workflows may need extra wrappers to feel as smooth as native MCP tools

## What It Can Do Right Now

The CLI already supports:
- discovering running Unity instances
- selecting the Unity instance to target
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

That means the CLI is already capable of real authoring work in your project.

It also now has a higher-level workflow layer so Codex does not need to manually stitch every low-level route together for common tasks.

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

Run a reversible end-to-end smoke test:

```powershell
cli-anything-unity-mcp --json workflow smoke-test --port 7893
```

If your scene already has unsaved changes and you want the smoke test to save them first:

```powershell
cli-anything-unity-mcp --json workflow smoke-test --save-if-dirty-start --port 7893
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

1. Keep the Unity plugin running in the editor.
2. Use this CLI as Codex's main Unity control path.
3. Prefer `--json` when the result will be read by another tool or agent.
4. Always pass `--port <port>` when you know the target instance.
5. Prefer the `workflow` commands first, then fall back to `tool` or `route` only when needed.

For actual game work, the best pattern right now is:

1. Start with `workflow inspect` or `workflow validate-scene`
2. Use `workflow create-behaviour` to add gameplay scripts quickly
3. Use `workflow wire-reference` to connect scene objects and prefab references
4. Use `workflow create-prefab` once an authored scene object becomes reusable
5. Use `workflow smoke-test` when you want a full end-to-end validation pass, or `workflow smoke-test --no-play-check` when you want the faster authoring-only version

For your use case, this is the best current path if the main goal is:

"Let Codex do real Unity work without paying MCP overhead."

## Recommended Next Improvements

The highest-value next steps are:

1. Add more project-specific high-level commands.
   Examples: wire references, inspect missing references, create prefabs, capture scene screenshots.

2. Keep hardening runtime workflows.
   Console log freshness is still the main rough edge worth tightening.

3. Add a Codex skill or instruction file.
   This will teach Codex exactly how to prefer `workflow inspect`, `workflow create-behaviour`, and `workflow smoke-test` before dropping to lower-level commands.

4. Add more rollback-friendly authoring helpers.
   Examples: temporary-object workflows, prefab probes, and scene validation passes.
