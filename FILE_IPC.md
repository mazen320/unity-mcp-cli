# Standalone File IPC Bridge

This is the no-port, no-AnkleBreaker-plugin path for core Unity editor control.

Use this when you want the CLI to talk to Unity through the lightweight scripts in this repo instead of the AnkleBreaker HTTP bridge.

## What It Is

File IPC is a tiny Unity Editor bridge:

- `unity-scripts/Editor/FileIPCBridge.cs`
- `unity-scripts/Editor/StandaloneRouteHandler.cs`

The Python CLI writes JSON command files into:

```text
<UnityProject>/.umcp/inbox/
```

Unity reads those files on the main editor thread, executes the requested route, and writes JSON responses into:

```text
<UnityProject>/.umcp/outbox/
```

That means no localhost port, no HTTP server, and no worker-thread calls into Unity editor APIs.

## Setup

1. In your Unity project, create this folder if it does not already exist:

```text
Assets/Editor/
```

2. Copy these files from this repo into that folder:

```text
unity-scripts/Editor/FileIPCBridge.cs
unity-scripts/Editor/StandaloneRouteHandler.cs
```

3. Wait for Unity to compile.

4. Confirm the Unity Console shows:

```text
[FileIPC] Bridge initialized at .../.umcp
```

## Run It

From this repo:

```powershell
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json instances
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json state
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json scene-info
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json hierarchy
```

Example visible edit:

```powershell
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json route --params '{"name":"CLI_FILE_IPC_PROBE"}' gameobject/create
```

Open the optional native Unity panel:

```powershell
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json route --params '{"menuItem":"Window/CLI Anything"}' editor/execute-menu-item
```

## Agents With File IPC

Agents do work with File IPC. They run outside Unity and use the CLI as the transport:

```text
Prompt -> agent -> cli-anything-unity-mcp --transport file -> Unity
```

The CLI already tags requests with an `agentId`, records local trace history, and lets you use saved agent profiles:

```powershell
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json agent current
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json debug trace --tail 10
cli-anything-unity-mcp agent save builder --role builder --agent-id unity-builder
```

File IPC does not need the old Unity request queue because Unity reads each `.umcp/inbox` command on the main thread. So `agent queue` reports a direct File IPC queue state instead of polling the AnkleBreaker HTTP queue:

```powershell
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json agent queue
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json agent sessions
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json agent log unity-builder
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json agent watch --iterations 1 --interval 0
```

Unity's File IPC bridge keeps a lightweight in-memory agent registry. It records each request's `agentId`, route name, status, timestamp, and error string. There is no background polling loop in Unity; the registry updates only when commands arrive.

The native `Window > CLI Anything` panel is the local cockpit for visibility and manual actions. It is not a heavy polling chat UI. That is intentional: the prompt loop stays in the CLI/agent process, while Unity stays fast.

## What Works Without AnkleBreaker

Standalone File IPC currently covers the core local route surface:

- `ping`
- `scene/info`, `scene/hierarchy`, `scene/save`, `scene/new`, `scene/stats`
- `project/info`
- `editor/state`, `editor/play-mode`, `editor/execute-menu-item`
- `compilation/errors`
- `console/log`, `console/clear`
- `gameobject/create`, `gameobject/delete`, `gameobject/info`, `gameobject/set-active`, `gameobject/set-transform`
- `component/add`, `component/get-properties`
- `asset/list`
- `script/create`, `script/read`
- `undo/perform`, `redo/perform`
- `screenshot/game`
- `queue/info`, `agents/list`, `agents/log`

`CliAnythingWindow.cs` is optional. Copy it into `Assets/Editor/` too if you want the native `Window > CLI Anything` panel.

## What Still Needs The Full Plugin

The standalone File IPC bridge is not the full 328-tool advanced surface yet.

Use the AnkleBreaker Unity plugin HTTP bridge when you need the broad advanced catalog today, especially:

- terrain
- animation
- shader and shader graph
- prefab-heavy workflows
- package management
- advanced graphics/rendering probes
- optional package tools such as Amplify and UMA

The roadmap is to keep moving useful routes from "plugin required" to "standalone File IPC supported" as we build our own Unity-side backend depth.

## Tested Locally

This path has been live-tested against the `OutsideTheBox` Unity project with:

- `instances`
- `state`
- `scene-info`
- compact `hierarchy`
- `compilation/errors`
- `editor/execute-menu-item`
- inactive-object `gameobject/info`
- `gameobject/set-active`
- `gameobject/create`
- `gameobject/set-transform`
- `component/add`
- `queue/info`, `agent queue`, `agent sessions`, `agent log`, `agent watch --iterations 1`

The latest visible proof was a File IPC-only scene edit that created:

```text
/McpLiveFpsPass/CLI_FILE_IPC_PROBE_LIGHT
```

with a `Light` component and a verified hierarchy count increase.

## Mental Model

```text
You prompt the agent
-> agent runs cli-anything-unity-mcp --transport file
-> CLI writes JSON into .umcp/inbox
-> Unity reads it on the main thread
-> Unity writes JSON into .umcp/outbox
-> agent reads the result and keeps working
```
