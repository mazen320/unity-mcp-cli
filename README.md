# CLI Anything Unity MCP

An open-source Unity AI copilot that runs inside the Unity Editor.

The goal is simple: make Unity development feel faster by letting an LLM inspect the real project, propose changes, execute through Unity editor APIs, and verify what actually happened.

This is not a pile of hardcoded Python recipes. The assistant should learn the user's intent from chat, read Unity context, choose available Unity routes, and operate the editor safely.

> Status: alpha. Useful, but still being hardened. Expect rough edges around generated scripts, route coverage, and verification. Contributions are welcome.

## What It Can Do Today

- Chat inside Unity through `Window > CLI Copilot` or the `Agent` tab in `Window > CLI Anything`.
- Use OpenRouter, OpenAI, or Anthropic API keys for model-backed conversation and planning.
- Read live Unity context: active scene, hierarchy, scripts, compile state, project settings, and recent chat.
- Propose executable multi-step plans and wait for approval before applying.
- Create and modify GameObjects, components, materials, scripts, scenes, prefabs, lighting, tags, layers, and physics setup through File IPC routes.
- Create new scenes when the user asks for work to happen separately.
- Wait for Unity script compilation before attaching newly generated MonoBehaviours.
- Review a game/project conversationally without immediately turning every message into a plan.
- Run local debugging and inspection commands from the CLI.

## What It Is Not

- Not a one-click replacement for a Unity developer.
- Not a prompt-only chatbot that pretends it changed Unity.
- Not a code dump tool that blindly writes files without Unity context.
- Not a benchmark or scoring product.
- Not cloud-first telemetry. Project memory and run logs are local-first.

It can help create or modify project features when asked. The difference is that the LLM should use real Unity context and editor routes rather than prewritten task recipes.

## How It Works

```text
User chat in Unity
        |
        v
Model-backed assistant
        |
        v
Context + route-aware planner
        |
        v
File IPC command queue in .umcp/
        |
        v
Unity Editor main thread
        |
        v
Route result, compile check, screenshots, history
```

The split matters:

- The LLM decides what the user wants and what Unity actions to take.
- Python validates that the plan is executable and safe enough to ask for approval.
- Unity executes the work on the main thread through editor APIs.
- The assistant reports route results instead of claiming success blindly.

## Install

### Requirements

- Unity 2021.3 or newer recommended
- Python 3.11 or newer
- A model provider key for real chat/planning:
  - `OPENROUTER_API_KEY`
  - `OPENAI_API_KEY`
  - `ANTHROPIC_API_KEY`

### Setup

1. Install the Python package from this repository:

   ```powershell
   python -m pip install -e .
   ```

2. Copy the Unity editor scripts into your Unity project:

   ```text
   unity-scripts/Editor/FileIPCBridge.cs -> Assets/Editor/FileIPCBridge.cs
   unity-scripts/Editor/StandaloneRouteHandler.cs -> Assets/Editor/StandaloneRouteHandler.cs
   unity-scripts/Editor/CliAnythingWindow.cs -> Assets/Editor/CliAnythingWindow.cs
   ```

3. Open Unity and use one of:

   ```text
   Window > CLI Copilot
   Window > CLI Anything
   ```

4. In the Copilot settings, configure a provider/model, or add a project-local env file:

   ```text
   <UnityProject>/.umcp/agent.env
   ```

   Example:

   ```dotenv
   OPENAI_API_KEY=...
   ```

   Direct OpenAI defaults to `gpt-5.2-codex` for coding-oriented Unity planning when that model is available on your API account. You can pick another OpenAI, OpenRouter, or Anthropic model from the Unity settings panel.

5. Click `Connect` in the Unity window.

## Example Prompts

Use it conversationally:

```text
What do you think of this scene?
Can you inspect my player controller setup?
Why does the camera feel wrong?
```

Ask for bounded edits:

```text
Create a new scene for testing this feature and set up the required objects.
Add a CharacterController-based player to this scene.
Create a script for this object and attach it after compile.
Show me which object you are targeting before changing anything.
```

For larger requests, the assistant should propose a plan first and wait for approval.

## Power-User CLI

The CLI is mainly for debugging and automation:

```powershell
cli-anything-unity-mcp --help
cli-anything-unity-mcp --transport file --file-ipc-path "C:\Path\To\UnityProject" --json debug doctor
cli-anything-unity-mcp --transport file --file-ipc-path "C:\Path\To\UnityProject" --json agent sessions
cli-anything-unity-mcp --transport file --file-ipc-path "C:\Path\To\UnityProject" --json scene-info
```

## Roadmap Direction

The right direction is AI-driven Unity control, not hardcoded per-task scripts.

Near-term priorities:

1. Stronger project context indexing across scripts, scenes, prefabs, assets, and settings.
2. Better post-action verification: compile errors, route readback, screenshots, and clear failure messages.
3. Safer generated-code flow: diff first, compile, repair or rollback.
4. Smarter target resolution from hierarchy, components, scripts, and user language.
5. Cleaner in-editor UX for plan review, progress, evidence, and undo.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [AGENTS.md](AGENTS.md).

Good first contribution areas:

- Route reliability and clearer error messages.
- Unity-side Undo coverage.
- Context indexing.
- Agent tab UX.
- Real Unity project smoke tests.
- Documentation and setup improvements.

## License

MIT. See [LICENSE](LICENSE).
