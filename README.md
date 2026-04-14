# Unity MCP CLI

`unity-mcp-cli` is an open-source **CLI-first Unity agent layer** for real Unity projects.

The main bet of this repo is simple: if you want AI agents to be genuinely useful inside Unity, the control path needs to be **fast, debuggable, main-thread-safe, and easy to install**. That is why this project pushes a **File IPC-first** architecture for day-to-day agent work, while still supporting the AnkleBreaker plugin HTTP bridge when you need the broader advanced surface.

Instead of forcing every turn through a heavy MCP registration loop, this repo gives agents a direct shell and workflow surface for Unity. The result is a tighter loop for Codex, Claude, scripts, and future in-editor agent UX.

## Why This Matters

Most Unity AI setups still feel brittle in practice:
- too much transport overhead
- weak debugging when Unity gets weird
- too much dependence on one plugin/runtime path
- not enough structure for planning, verification, and recovery

This repo is trying to close that gap.

The goal is not just “a CLI wrapper around Unity MCP.” The goal is a serious foundation for a **real Unity assistant** that can:
- understand project context
- inspect before acting
- execute multi-step work safely
- explain failures clearly
- surface useful status inside and outside the editor

## The Product Direction

The product is being built with a **dual-track method**:
- **Engine track**: standalone-first Unity control, reusable workflows, expert audits, bounded fixes, and benchmark/evidence tooling
- **Magic track**: every engine improvement must turn into something visible and satisfying for the Unity user within one or two steps

That means the goal is not just a good backend or just a flashy chat surface. The goal is a real Unity developer system that is reliable, visible, and measurable.

The strategic direction is:
- **File IPC as the primary transport** for zero-config, fast, main-thread-safe Unity control
- **CLI workflows as the reusable product engine** for agents and power users
- **plugin HTTP compatibility** while standalone depth catches up
- **in-editor product magic** like score deltas, applied/skipped fixes, exports, and visible assistant outcomes
- **proof-first iteration** through benchmark reports, comparisons, captures, and markdown artifacts

If you want the shortest description, it is this:

> An open-source attempt at a real Unity AI developer: File-IPC-first, workflow-driven, visibly useful in-editor, and backed by proof instead of claims.

## Pick A Bridge

- Use [FILE_IPC.md](FILE_IPC.md) if you want the standalone-first path and the main direction of the project.
- Use [PLUGIN_SETUP.md](PLUGIN_SETUP.md) if you want the full advanced AnkleBreaker plugin HTTP bridge path.

| Bridge | Best for | Needs plugin | Needs ports |
| --- | --- | --- | --- |
| File IPC | fastest local agent loop, debugging, standalone-first workflows, zero-config setup | no | no |
| Plugin HTTP | full advanced Unity route surface today | yes | yes |

## What This Repo Already Does

- discovers running Unity editors or standalone File IPC projects
- inspects project, scene, hierarchy, console, compilation, queue, and editor state
- scans local project guidance, asset structure, packages, and importer hints during `workflow inspect`
- creates and edits scripts, scene objects, components, references, materials, and prefabs
- captures Game View and Scene View screenshots
- explains likely Unity problems with `debug doctor`
- shows recent CLI activity with `debug trace`
- reads the real Unity `Editor.log`
- supports built-in developer profiles so the CLI itself can stay in `normal`, `builder`, `review`, or `caveman` mode across sessions
- exposes an optional thin MCP adapter when a client still needs MCP transport

## Why File IPC Is The Center Of Gravity

File IPC is not just a fallback here. It is the path that best matches the end goal.

Why it matters:
- **no port setup**
- **main-thread-safe execution in Unity**
- **lower overhead for fast agent loops**
- **less fragile during play mode, reloads, and editor weirdness**
- **easier debugging because the transport is simple and inspectable**

That makes it the best route for the future "ask the agent to build something in Unity and watch it happen" experience.

## Architecture In One Glance

```text
Prompt -> agent -> cli-anything-unity-mcp -> File IPC or plugin HTTP -> Unity
```

Today:
- **File IPC** is the preferred standalone path for fast core editor control and agent iteration
- **plugin HTTP** is the compatibility path for broader advanced coverage

## What Makes This Different

This repo is trying to combine a few things that usually live in separate, weaker tools:
- a shell-first Unity control surface
- a standalone-first Unity bridge path
- a debug-first workflow instead of a "hope the agent guessed right" workflow
- project-aware inspections, audits, quality scoring, and fix planning
- groundwork for a more visible in-editor agent experience

That combination is the real product story.

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

Developer profile helpers:

```powershell
cli-anything-unity-mcp --json developer list
cli-anything-unity-mcp --json developer current
cli-anything-unity-mcp --json developer use builder
cli-anything-unity-mcp --json developer clear
cli-anything-unity-mcp --json --developer-profile caveman workflow inspect --port <port>
```

## Quick Start

If you only try one path, try **File IPC first**.

1. Open your Unity project.
2. Choose the Unity-side bridge:

- **Recommended:** copy `FileIPCBridge.cs` and `StandaloneRouteHandler.cs` into `Assets/Editor/` and wait for `[FileIPC] Bridge initialized at .../.umcp`
- **Advanced compatibility path:** install the AnkleBreaker Unity plugin and wait for Unity to log a bridge port like `[AB-UMCP] Server started on port 7892`

### File IPC quick start

File IPC mode skips port discovery and talks through `.umcp` files in the Unity project:

```powershell
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json instances
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json workflow inspect
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json debug doctor
cli-anything-unity-mcp --transport file --file-ipc-path "C:/Projects/MyGame" --json debug capture --kind both
```

If you want a reusable standalone verification pass instead of typing commands one by one:

```powershell
python .\scripts\run_file_ipc_smoke.py --file-ipc-path "C:/Projects/MyGame"
python .\scripts\run_file_ipc_smoke.py --file-ipc-path "C:/Projects/MyGame" --json
```

### Plugin HTTP quick start

From this repo, the plugin HTTP path looks like:

```powershell
cli-anything-unity-mcp instances
cli-anything-unity-mcp select <port>
cli-anything-unity-mcp --json workflow inspect --port <port>
cli-anything-unity-mcp --json workflow asset-audit --port <port>
cli-anything-unity-mcp --json workflow bootstrap-guidance --port <port>
cli-anything-unity-mcp --json workflow create-sandbox-scene --port <port>
cli-anything-unity-mcp --json workflow expert-audit --lens director --port <port>
cli-anything-unity-mcp --json workflow quality-score --port <port>
cli-anything-unity-mcp --json workflow benchmark-report --port <port>
cli-anything-unity-mcp --json debug doctor --port <port>
cli-anything-unity-mcp --json debug capture --kind both --port <port>
```

`CliAnythingWindow.cs` is optional. Copy it into `Assets/Editor/` if you want a native Unity panel at `Window > CLI Anything`.

That panel now includes:
- a real local `Codex` provider path that uses the machine's Codex CLI login instead of pretending ChatGPT session tokens are API keys
- a `Goal Assistant` tab for local project scans and ranked improvement suggestions
- an Agent tab `Connect` path that can launch the Python chat bridge from the `agent-harness` source tree with a configurable harness root plus Python launcher, instead of assuming `python -m cli_anything.unity_mcp` already works in the user's shell
- an offline project-aware Agent chat layer that can answer greetings/help, inspect the project, run quality scores and benchmarks, scaffold guidance/tests, create sandbox scenes, save scenes, read compiler state, and create simple primitives even without external API keys
- a dedicated Agent-tab `improve project` summary card that surfaces the latest score delta, applied fixes, skipped fixes, rerun action, and markdown export from the shared workflow payload instead of hiding that data inside chat text
- a copyable `Agent Brief` so you can hand the current project context to the CLI agent quickly
- generated `Suggested CLI Commands` based on the current project path and selected object
- lightweight importer audit for model material ownership and likely normal-map or sprite import mismatches
- the older cached `Scene`, `Inspector`, `Actions`, and `Bridge` tabs for direct editor work without polling

Standalone File IPC is intentionally smaller than the full plugin route surface. It is good for core local control such as editor state, scene info, hierarchy, console, compilation errors, asset search, scene object search, selection control, GameObject basics, component basics, script read/create, undo/redo, screenshots, agent session/log visibility, sandbox-scene creation, lightweight animation clip/controller creation and inspection, lightweight animation controller scaffolding/wireup, lightweight parameter/state/transition authoring, explicit default-state edits, and opening the native CLI Anything panel. Use the AnkleBreaker plugin HTTP bridge when you need the full advanced catalog across terrain, deeper animation systems, shaders, prefabs, packages, and other deep Unity systems.

Recent standalone File IPC live verification in `OutsideTheBox` also covered direct `context`, `search/scene-stats`, `search/missing-references`, `search/by-component`, `selection/get`, `selection/set`, `selection/focus-scene-view`, `animation/create-clip`, `animation/clip-info`, `animation/create-controller`, `animation/assign-controller`, `animation/controller-info`, `animation/add-parameter`, `animation/add-state`, `animation/set-default-state`, `animation/add-transition`, `debug breadcrumb`, `console/log` breadcrumb readback, and `debug capture --kind both`.

Agents still work on the File IPC path. The agent process runs the CLI, the CLI tags commands with an `agentId`, and the Unity-side File IPC bridge records lightweight `agent sessions` / `agent log` state without background polling. File IPC executes directly on Unity's main thread, so it does not need the old HTTP queue for core routes.

## Developer Profiles

The CLI now has a first-class developer-profile layer for shaping how the assistant behaves, reports, and prioritizes work.

- `normal` is the default balanced mode.
- `builder` is action-first for implementation and fast shipping.
- `review` is risk-first for bugs, regressions, and test gaps.
- `caveman` is the terse low-token mode.
- `director`, `systems`, `physics`, `animator`, `tech-artist`, `ui-designer`, and `level-designer` are specialist Unity content modes that pair well with the expert audit workflows.

Use them either persistently:

```powershell
cli-anything-unity-mcp --json developer use review
cli-anything-unity-mcp --json developer current
```

Or per invocation:

```powershell
cli-anything-unity-mcp --json --developer-profile builder workflow create-sandbox-scene --port <port>
cli-anything-unity-mcp --json --developer-profile caveman debug doctor --port <port>
```

If no developer profile is selected, the CLI resolves to `normal`. Non-default developer profiles also show up in CLI status output and can label Unity-side trace breadcrumbs more clearly during active sessions.

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

`workflow inspect` now does more than just ask Unity for scene state. When the project path is available, it also scans the local project on disk and returns:

- guidance sources such as `AGENTS.md`, `README.md`, and `Assets/MCP/Context`
- asset/layout counts for scenes, scripts, asmdefs, prefabs, materials, models, animations, audio, shaders, and tests
- disk-based importer heuristics from adjacent `.meta` files, including model material-import state plus likely normal-map and sprite-import mismatches
- improvement suggestions such as adding agent guidance, adding tests, prefabizing imported models, auditing rig/animation setup, or creating a sandbox scene

When you want the project-scan part without the full scene snapshot, use:

```powershell
cli-anything-unity-mcp --json workflow asset-audit --port <port>
cli-anything-unity-mcp --json workflow asset-audit C:/Projects/MyUnityGame
cli-anything-unity-mcp --json workflow bootstrap-guidance C:/Projects/MyUnityGame
cli-anything-unity-mcp --json workflow bootstrap-guidance C:/Projects/MyUnityGame --write
cli-anything-unity-mcp --json workflow create-sandbox-scene --port <port>
cli-anything-unity-mcp --json workflow create-sandbox-scene --name GameplayLab --folder Assets/Scenes/Sandboxes --open --port <port>
cli-anything-unity-mcp --json workflow expert-audit --lens tech-art --port <port>
cli-anything-unity-mcp --json workflow expert-audit --lens systems --port <port>
cli-anything-unity-mcp --json workflow scene-critique --port <port>
cli-anything-unity-mcp --json workflow quality-score C:/Projects/MyUnityGame
cli-anything-unity-mcp --json workflow benchmark-report C:/Projects/MyUnityGame
cli-anything-unity-mcp --json workflow benchmark-report --report-file .cli-anything-unity-mcp/benchmarks/my-project.json --port <port>
cli-anything-unity-mcp --json workflow benchmark-compare .cli-anything-unity-mcp/benchmarks/before.json .cli-anything-unity-mcp/benchmarks/after.json
cli-anything-unity-mcp --json workflow benchmark-compare --markdown-file .cli-anything-unity-mcp/benchmarks/compare.md .cli-anything-unity-mcp/benchmarks/before.json .cli-anything-unity-mcp/benchmarks/after.json
cli-anything-unity-mcp --json workflow improve-project C:/Projects/MyUnityGame
cli-anything-unity-mcp --json workflow improve-project --port <port> C:/Projects/MyUnityGame
cli-anything-unity-mcp --json workflow quality-fix --lens director --fix guidance C:/Projects/MyUnityGame
cli-anything-unity-mcp --json workflow quality-fix --lens director --fix guidance --apply C:/Projects/MyUnityGame
cli-anything-unity-mcp --json workflow quality-fix --lens director --fix test-scaffold --apply C:/Projects/MyUnityGame
cli-anything-unity-mcp --json workflow quality-fix --lens director --fix sandbox-scene --apply --port <port>
cli-anything-unity-mcp --json workflow quality-fix --lens systems --fix event-system --apply --port <port>
cli-anything-unity-mcp --json workflow quality-fix --lens animation --fix controller-scaffold --apply --port <port>
cli-anything-unity-mcp --json workflow quality-fix --lens animation --fix controller-wireup --apply --port <port>
```

`workflow asset-audit` returns a tighter summary for guidance coverage, asset counts, importer-hint counts, priority buckets, focus areas, and the top recommendations to tackle first.

`workflow bootstrap-guidance` uses that same audit to generate a starter `AGENTS.md` and, by default, `Assets/MCP/Context/ProjectSummary.md`. Preview mode is the default so you can inspect the generated files first; add `--write` when you want the CLI to create them.

`workflow create-sandbox-scene` creates or reopens a saved sandbox scene under `Assets/Scenes` by default. It restores the original scene after creation unless you pass `--open`, which makes it safer to scaffold test space without throwing away your current working context.

`workflow expert-audit` runs one specialist lens at a time, such as `director`, `systems`, `physics`, `animation`, `tech-art`, `ui`, or `level-art`, and returns a lens-specific score, findings, supported follow-up fixes, and the relevant project summary context.

The new `systems` lens is intentionally Unity-wide, not genre-specific. It looks for scene architecture and runtime hygiene issues such as missing sandbox coverage, scene-only setup with no prefab coverage, duplicate `AudioListener` usage, UI canvases without an `EventSystem`, likely player objects with no movement foundation, collider gaps in scenes that already look interactive, and disposable probe/demo objects left in the scene.

When a live scene still contains obvious tooling leftovers, `workflow quality-fix --lens systems --fix disposable-cleanup --apply` can now remove probe, fixture, temp, debug, or standalone objects through the same bounded workflow layer instead of leaving that cleanup only to the in-editor assistant.

The new `physics` lens focuses on setup hygiene for colliders, rigidbodies, and controller ownership. It flags Rigidbody objects that have no collider on the same object, likely player objects that still have no clear movement body, and scenes that look playable but still have no collision foundation.

When there is exactly one clear likely player object in the live scene, `workflow quality-fix --lens physics --fix player-character-controller --apply` can now add a bounded `CharacterController` through Unity instead of leaving that finding as a manual follow-up.

`ui` and `level-art` are scene-dependent lenses. If you run them against a bare project path without a live selected Unity editor, they now report that the live scene context is unavailable instead of pretending the scene is healthy.

The `animation` lens now checks both the asset pipeline and the inspected scene. It can flag models with no animation evidence, clips without Animator Controller coverage, and scenes that still have no `Animator` components even though animation assets exist.

When that audit points to a missing controller scaffold, `workflow quality-fix --lens animation --fix controller-scaffold --apply` creates a generated Animator Controller asset through Unity at a safe default path under `Assets/Animations/Generated/`.

When the scene already has a live `Animator`, `workflow quality-fix --lens animation --fix controller-wireup --apply` now creates or reuses that generated controller and assigns it through Unity to the first detected Animator in the inspected scene.

`workflow scene-critique` bundles the high-signal scene-facing lenses together so you can get a fast content-direction review without manually calling each one.

`workflow quality-score` scores the whole project across all built-in expert lenses and returns per-lens grades plus an overall average.

`workflow improve-project` is the new top-level safe improvement pass. Offline, it writes missing project guidance and EditMode smoke-test scaffolding when the Unity Test Framework is already installed. When you also pass `--port <port>`, it adds the bounded live-scene repair bundle on top: sandbox-scene creation, disposable probe cleanup, `AudioListener` repair, `EventSystem` repair/normalization, missing `CanvasScaler` and `GraphicRaycaster` components, and the bounded likely-player `CharacterController` fix.

If the CLI already has a selected Unity target whose `projectPath` matches `PROJECT_ROOT`, `workflow improve-project` now reuses that live editor automatically even without `--port`. That matters for the Unity Agent tab and embedded CLI flows, because they can run the same bounded improvement workflow and keep live scene repairs enabled instead of silently degrading to an offline-only pass.

That gives the CLI a single demoable “make this Unity project healthier” entrypoint instead of forcing users to remember nine separate `quality-fix` commands. It also makes before/after evidence cleaner: the command returns `baselineScore`, `finalScore`, `scoreDelta`, plus explicit `applied` and `skipped` fix lists, so GitHub writeups can show exactly what changed and what it unlocked.

`workflow agent-chat <PROJECT_ROOT>` now seeds that explicit File IPC project into the embedded CLI session before the chat loop starts. In practice, that means an in-editor `improve project` request is no longer a separate handwritten repair path: the Agent assistant reuses the same `workflow improve-project` engine, score delta, and applied/skipped fix reporting that the shell command uses.

If you want a GitHub-friendly artifact from the same run, add `--markdown-file <path>`. The workflow will write a compact markdown summary with the project root, live/offline status, quality-score delta, and the exact applied/skipped fix lists, so a single improvement pass can produce both machine-readable JSON and a human-readable status update.

The Unity Agent tab now reads that same structured `improve-project` payload back from `.umcp/chat/history.json` and renders it as a report card above the chat log. That gives the in-editor surface a visible product payoff: users can rerun the pass, inspect the last score delta and fix lists at a glance, and export the exact markdown artifact without leaving Unity.

`workflow benchmark-report` packages those same lens scores into a stable JSON report with overall grade, weakest lenses, severity breakdown, top findings, and project summary metadata. It also includes bounded recurring diagnostics memory for repeat compiler failures and repeat queue/bridge instability, a dedicated `queueDiagnostics` block for recurring queue pressure, and a `queueTrend` block for longer-horizon queue history, so GitHub snapshots and local benchmark artifacts keep the long-running health signal instead of only the current pass.

`workflow benchmark-compare` compares two saved benchmark-report JSON files and returns overall score delta, per-lens score deltas, new vs resolved findings, recurring-diagnostics churn, queue-health deltas, and queue-trend deltas. It also emits a compact Markdown summary, and `--markdown-file` writes that summary directly for GitHub regressions, milestone writeups, or proving that a fix batch improved the benchmark instead of only generating a fresh snapshot.

When a CLI command fails on a Unity route, the error text now reuses the latest backend history entry to show which route failed, which derived tool it maps to, which transport/port was involved, and which debug command to try next. Queue-backed failures also point directly at `agent queue` and `agent sessions`, so contention or stuck worker state is one command away instead of hidden behind a generic bridge error.

When recovery polling itself times out, the backend now reports the route it was trying to recover, the selected project or port it was waiting on, and the last transport error that blocked recovery. Combined with the normal failure-hint layer, that turns a dead bridge or stale port into an actionable message instead of a bare socket exception.

`debug doctor` now separates queue backlog from active worker state. `Queued Requests Pending` means work is waiting to start, while `Active Unity Agents Running` means Unity is still mutating state during inspection. It also returns a compact `queueDiagnostics` block plus a `queueTrend` block, so queue health is easier to read from benchmark artifacts, agent tooling, and issue reports.

`workflow quality-fix` is intentionally a planner first. It turns a supported expert finding into the safest next CLI action instead of silently editing the project.

For the `director` lens, `workflow quality-fix --lens director --fix test-scaffold --apply` now writes a minimal EditMode smoke test plus a matching test assembly definition under `Assets/Tests/EditMode/`. It only auto-applies when `com.unity.test-framework` is already present, so it does not introduce compile errors into projects that have not installed the Unity Test Framework yet.

For the `systems` lens, `workflow quality-fix --lens systems --fix event-system --apply` now adds a bounded UI input foundation when a live scene has Canvas objects but no `EventSystem`. It creates or repairs an `EventSystem` GameObject and chooses `InputSystemUIInputModule` when the project depends on `com.unity.inputsystem`, otherwise it falls back to `StandaloneInputModule`.

When you add `--apply`, the first bounded fixes can run directly:

- `guidance` writes the generated `AGENTS.md` and optional `Assets/MCP/Context/ProjectSummary.md`
- `sandbox-scene` runs the sandbox-scene workflow with the same safety flags (`--open`, `--save-if-dirty`, `--discard-unsaved`)
- `ui-canvas-scaler` finds live Canvas objects that are missing `CanvasScaler` and adds the component in-place when a Unity editor is selected
- `texture-imports` repairs likely normal-map and sprite importer mismatches through Unity using the importer-audit sample paths
- `controller-scaffold` creates a generated Animator Controller asset through Unity when the animation audit finds controller coverage gaps
- `controller-wireup` creates or reuses the generated Animator Controller asset and assigns it to the first live Animator in the inspected scene

Manual-only fixes still stay planner-only and return a clear error if you try to auto-apply them.

When you pass a direct project path to `workflow asset-audit` or `workflow bootstrap-guidance`, the run stays local to that project scan and does not emit Unity Console breadcrumbs into whichever editor you currently have selected.

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

## Roadmap Hierarchy

The main goal is to make this the best open-source Unity AI developer surface for real project work:

- stronger debugging than raw MCP transport
- faster inner loops through File IPC
- safer planning and verification before edits
- better recovery around play mode and bridge rebinding
- higher standalone route depth over time
- reusable workflows that power both shell and in-editor assistant behavior
- visible in-editor magic instead of hidden backend capability
- benchmark and export flows that make progress provable
- a local-first learning loop so the assistant can improve from real runs, evals, and structured memory instead of only prompt edits

The product is being built in a strict hierarchy:
- [PLAN.md](../../PLAN.md) explains how the product gets built
- this README explains what the product is becoming
- [TODO.md](TODO.md) explains what happens next

Validation should happen through CLI diagnostics, tool audits, captures, temporary probes, benchmark artifacts, and markdown summaries. The shipped product surface is the CLI layer plus the standalone-first bridge path, with the Unity Agent tab becoming the visible layer on top.

## Repo Boundaries

- You do **not** need `unity-mcp-server` to use this CLI.
- You do **not** need your own plugin fork just to use this CLI.
- You **do** need either the Unity plugin installed for the full route surface or the File IPC bridge scripts installed for the smaller core route surface.

This repo stays focused on the CLI layer. If you need more beginner setup help, use [START_HERE.md](START_HERE.md) and [PLUGIN_SETUP.md](PLUGIN_SETUP.md).

## Docs

- [START_HERE.md](START_HERE.md): beginner-friendly walkthrough
- [PLAN.md](../../PLAN.md): canonical product roadmap and method
- [docs/superpowers/specs/2026-04-14-learning-system-design.md](docs/superpowers/specs/2026-04-14-learning-system-design.md): local-first learning-system design
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
