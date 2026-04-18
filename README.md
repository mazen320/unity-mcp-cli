# Unity AI Copilot

A Unity AI copilot for real game development. Like Bezi or Cursor, but native to the Unity editor.

It does not generate games. It helps users build the one they already have.

The target is straightforward: eliminate Unity tedium without bulldozing project architecture, code style, or design intent.

## Product stance

- **Collaborator, not generator**. Work with the existing project. Respect current architecture, naming, and conventions.
- **Context-aware**. Read the real scene, scripts, prefabs, assets, and settings before acting.
- **Execute in-editor**. Scene and inspector changes should happen through Unity editor APIs, not blind file writes.
- **Reversible**. Every mutation should be Undo-safe.
- **Tedious-work first**. Focus on wiring, inspector edits, event hookups, physics setup, animator setup, references, and other work that slows real Unity development down.
- **Verify and self-correct**. Compile, inspect, capture, and report the real result instead of pretending success.
- **Conversational**. The product surface is natural-language chat inside Unity.
- **Safe by default**. Destructive work needs clear consent. Batch sweeps are not the default.

## What it does today

- Runs inside the Unity editor through the `Agent` tab in `Window > CLI Anything`
- Reads live project and scene context before bounded actions
- Supports project-local model/provider configuration through `.umcp/agent-config.json`
- Supports project-local provider secrets through `.umcp/agent.env`
- Ships a first specialist skill, `physics_feel`, for requests like `my player feels floaty`
- Applies bounded scene hygiene fixes through the Unity bridge for low-risk setup issues
- Captures before/after proof for visual flows
- Logs local run history in `.umcp/ledger/`
- Exposes a CLI for debugging, bridge inspection, and power-user scripting

## What it is not

- Not a game generator
- Not a raw text-sandbox that rewrites code blindly
- Not a batch cleanup bot that mutates a whole project without consent
- Not a grading product whose main value is scores or benchmark numbers
- Not a cloud-first system that depends on hidden telemetry

## How it should feel

Open Unity. Open `Window > CLI Anything`. Go to the `Agent` tab. Talk to it.

> **You:** my player feels floaty
>
> **Copilot:** I checked the live player setup. Three ways to tighten the feel:
> 1. Raise gravity for a snappier fall
> 2. Increase body weight for a heavier feel
> 3. Rebalance drag and gravity for more tuning headroom
>
> Which direction do you want?
>
> **You:** 1
>
> **Copilot:** Applying option 1. I’ll capture before/after and keep this Undo-safe.

That loop matters more than raw tool count:

- read the real project
- propose real tradeoffs
- get consent
- mutate safely
- verify the result
- make it easy to revert

## Install

### Requirements

- Unity 2021.3+ recommended
- Python 3.11+
- `click>=8.1`

### Setup

1. Copy the bridge scripts into your Unity project:
   - `unity-scripts/Editor/FileIPCBridge.cs` -> `Assets/Editor/`
   - `unity-scripts/Editor/StandaloneRouteHandler.cs` -> `Assets/Editor/`
   - `unity-scripts/Editor/CliAnythingWindow.cs` -> `Assets/Editor/`
2. Install the Python package:

```powershell
python -m pip install -e .
```

3. In Unity, open `Window > CLI Anything`.
4. Go to the `Agent` tab and click `Connect`.

Communication happens through `.umcp/` files in the Unity project. No ports are required for the File IPC path.

## Bridge configuration

Per-project provider/model preferences live in `.umcp/agent-config.json`:

```json
{
  "preferredProvider": "auto",
  "preferredModel": "gpt-5-codex"
}
```

Optional local provider secrets live in `.umcp/agent.env`:

```dotenv
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
```

Process environment variables still take precedence. `.umcp/agent.env` is the project-local convenience layer, not a replacement for normal environment configuration.

## Specialist skills

The copilot should grow as a set of specialist skills. Each skill should follow the same shape:

`notice -> diagnose -> propose tradeoffs -> consent -> apply -> verify -> ledger`

Current anchor skill:

- `physics_feel`

Next skills in the backlog:

- `collision_setup`
- `event_wiring`
- `animator_wiring`
- `ui_canvas`
- `serialized_property`
- `scriptable_refs`
- `layer_matrix`
- `prefab_overrides`
- `input_binding`
- `reference_rewiring`

If you are adding a skill, use [docs/skills/WRITING_A_SKILL.md](docs/skills/WRITING_A_SKILL.md).

## Architecture

```text
You
  -> Unity Agent tab
  -> skill router
  -> specialist skill
  -> File IPC bridge
  -> Unity main thread
  -> local ledger + memory
```

The CLI still matters, but as a support surface:

- debugging
- bridge inspection
- scripted power-user flows
- regression checks

The chat surface inside Unity is the product. The CLI is the power-user and debugging layer behind it.

## Power-user CLI

Useful commands when debugging or scripting the bridge:

```powershell
cli-anything-unity-mcp instances
cli-anything-unity-mcp select <port>
cli-anything-unity-mcp --json status --port <port>
cli-anything-unity-mcp --json debug doctor --port <port>
cli-anything-unity-mcp --json debug trace --tail 20
cli-anything-unity-mcp --json debug capture --kind both --port <port>
cli-anything-unity-mcp --json agent sessions
cli-anything-unity-mcp --json agent queue
```

Use the CLI when you need to inspect the bridge, verify behavior, or automate a debugging flow. Do not treat it as the main user-facing product story.

## Docs

- [../../PLAN.md](../../PLAN.md) — product vision and roadmap
- [TODO.md](TODO.md) — current priorities
- [TASKS.md](TASKS.md) — full backlog
- [AGENTS.md](AGENTS.md) — repo operating rules for AI agents
- [docs/skills/WRITING_A_SKILL.md](docs/skills/WRITING_A_SKILL.md) — skill template
- [FILE_IPC.md](FILE_IPC.md) — transport details
- [CONTRIBUTING.md](CONTRIBUTING.md) — contribution flow

## License

MIT. See [LICENSE](LICENSE).
