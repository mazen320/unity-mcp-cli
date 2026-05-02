# Unity Plugin Setup

This page explains the full advanced optional plugin path.

If you want the standalone core route path that does not require the optional plugin, use [FILE_IPC.md](FILE_IPC.md) instead.

`unity-mcp-cli` is the client. For the plugin HTTP path, the Unity Editor also needs the upstream Unity MCP plugin inside the Unity project.

## What The Plugin Is

The plugin is the Unity-side bridge.

It runs inside the Unity Editor and does the real work:

- reads scenes
- creates and deletes GameObjects
- adds components
- edits serialized properties
- creates prefabs
- enters play mode
- captures scene and game screenshots

Without that plugin, the plugin HTTP path has nothing to talk to. The separate File IPC path can still work for core routes if you install the bridge scripts from this repo.

Simple mental model:

1. Unity plugin:
   Lives inside the Unity project and opens a local bridge on `127.0.0.1`.

2. This CLI:
   Runs in your terminal and sends commands to that local bridge.

So when the docs say "install the upstream Unity plugin in your Unity project", they mean:

- put the upstream Unity MCP package into the Unity project you want to control
- open that project in Unity
- let the plugin start its local server
- then run `cli-anything-unity-mcp`

## Very Important: A Local Clone Is Not An Installed Plugin

This folder on your machine:

```text
C:\Users\mazen\OneDrive\Desktop\New Unity MCP Replacement\CLI\unity-mcp-plugin
```

is a source clone.

That does **not** automatically mean Unity is using it.

For Unity to actually use the plugin, the package must be added to the Unity project itself.

So there are two different things:

1. Plugin source clone on disk
   Useful if you want to read or edit plugin code.

2. Plugin installed into a Unity project
   Required for the plugin HTTP path to control that Unity project.

Most people only need the second one.

## Where To Get It

Upstream plugin repo:

- [AnkleBreaker-Studio/unity-mcp-plugin](https://github.com/AnkleBreaker-Studio/unity-mcp-plugin)

Git URL for Unity Package Manager:

```text
https://github.com/AnkleBreaker-Studio/unity-mcp-plugin.git
```

## Easiest Install Path

Use Unity Package Manager with the Git URL.

### Step By Step

1. Open the Unity project you want to control.
2. In Unity, open `Window > Package Manager`.
3. Click the `+` button.
4. Choose `Add package from git URL...`
5. Paste:

```text
https://github.com/AnkleBreaker-Studio/unity-mcp-plugin.git
```

6. Click `Add`.
7. Wait for Unity to finish importing and compiling.
8. Check the Unity Console for a message showing the bridge started and which port it picked.

You will usually see something like:

```text
[AB-UMCP] Server started on port 7891
```

or:

```text
[AB-UMCP] Server started on port 7893
```

That means the plugin is running correctly.

## How To Confirm It Works

After Unity logs the port:

1. Open a terminal in this CLI repo.
2. Run:

```powershell
cli-anything-unity-mcp instances
```

3. You should see your Unity project listed with a port.
4. Then run:

```powershell
cli-anything-unity-mcp select <port>
cli-anything-unity-mcp scene-info --port <port>
```

If that works, the CLI and plugin are connected.

## Example First Run

```powershell
python -m pip install -e .
cli-anything-unity-mcp instances
cli-anything-unity-mcp select 7891
cli-anything-unity-mcp --json workflow inspect --port 7891
```

## If You Already Cloned The Plugin Repo

If you already have a local clone of the plugin, that clone is mostly for development.

Most users do not need to copy files manually.

The normal usage path is still:

1. install the plugin into the Unity project
2. open the Unity project
3. run the CLI against the live Unity port

Only use the local plugin source clone if you are modifying Unity-side backend behavior.

If you want Unity to use your local clone instead of the Git URL version, that is a separate development setup and should be documented separately.

## What You Do Not Need

You do not need:

- the `unity-mcp-server` repo
- an MCP client setup
- a plugin source fork just to use the CLI

For standalone core File IPC use, the minimum setup is:

1. Unity project
2. `FileIPCBridge.cs` and `StandaloneRouteHandler.cs` copied into `Assets/Editor/`
3. this CLI installed on your machine

For full advanced plugin HTTP use, the minimum setup is:

1. Unity project
2. upstream Unity plugin installed in that project
3. this CLI installed on your machine

## Why This Dependency Still Exists

This CLI is a better client layer plus a growing standalone bridge, not a full replacement for every Unity Editor backend route yet.

Right now:

- the File IPC bridge performs core editor actions without the optional plugin
- the plugin is still the thing inside Unity that performs the broad advanced route surface
- the CLI is the lightweight way to drive either path

If the standalone bridge grows into a full Unity-side backend package, this setup can change.
But today, this is the honest architecture.
