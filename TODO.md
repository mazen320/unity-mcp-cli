# TODO

This file is the working roadmap for taking `unity-mcp-cli` from "good CLI wrapper" to "serious Unity agent layer".

It focuses on three outcomes:

- full practical MCP-tool coverage
- proof through repeatable live testing
- higher-end Unity building workflows that feel good enough for real project work

## Current Baseline

As of 2026-04-09:

- thin MCP adapter is working
- upstream coverage matrix exists in code and JSON form
- `37/37` automated tests are passing
- heavy live MCP pass is passing `15/15`
- live debug reports can be written with `scripts/run_live_mcp_pass.py --debug --report-file ...`
- advanced-tool audit now reaches UI, audio, lighting, animation, input, shadergraph, terrain, and navmesh
- tool coverage is measurable: `31` live-tested, `31` covered, `260` deferred, `6` unsupported
- `unsupported` currently maps to the Unity Hub surface only
- deferred tools now carry blocker labels like `stateful-live-audit`, `package-dependent-live-audit`, and `unity-hub-integration`

That means the project is no longer blocked on basic transport.
The next phase is coverage, reliability, and quality of generated Unity output.

## Definition Of Done

We should consider the tool layer "done enough" when all of these are true:

- every curated MCP tool has automated coverage
- every important upstream advanced-tool category has at least one live validation path
- failure cases produce useful debug output instead of silent breakage
- scene-building workflows produce acceptable visuals by default
- generated gameplay samples are input-safe, reload-safe, and play-mode-safe
- contributors can see what is implemented, what is partially supported, and what is intentionally deferred

## Track 1: MCP And Tool Coverage

### P0

- Expand the coverage matrix so fewer tools remain in `deferred`.
- Keep each tool tagged as one of:
  - `covered`
  - `live-tested`
  - `mock-only`
  - `unsupported`
  - `deferred`
- Keep blocker labels actionable so `deferred` never means "ignored forever."
- Refresh the machine-readable coverage file whenever status changes.
- Keep the `tool-coverage` command aligned with the checked-in matrix.

### P1

- Expand live validation beyond the current safe categories:
  - `ui`
  - `audio`
  - `lighting`
  - `animation`
  - `terrain`
  - `navmesh`
  - `shadergraph`
- Add category-specific probe builders so these tools can be exercised safely in disposable scenes.
- Normalize more parameter mismatches between catalog expectations and live plugin routes.

### P2

- Add support notes for package-dependent tools.
- Make unsupported tools fail clearly with actionable explanations.
- Add a generated report that lists dynamic routes missing from the catalog snapshot.

## Track 2: Testing And Debugging

### P0

- Keep `scripts/run_live_mcp_pass.py` as the source of truth for live validation.
- Expand and tune the named pass profiles:
  - `core`
  - `advanced`
  - `heavy`
  - `graphics`
  - `ui`
  - `terrain`
- Save each run to a timestamped report file by default when `--debug` is enabled.
- Add a summary mode that prints only failures, timeouts, and port hops.

### P1

- Capture Unity console before and after every heavy workflow.
- Capture Scene view and Game view automatically for visual workflows.
- Add detection for:
  - play-mode timeout
  - compilation error
  - bridge rebind
  - scene-dirty prompt risk
  - missing renderer/material output
- Add regression tests for previously fixed issues:
  - Input System mismatch
  - double HUD/canvas overlays
  - port rebind after play mode
  - dirty-scene reset prompts

### P2

- Add CI jobs for unit tests plus a report-only dry run of live-pass formatting logic.
- Add a "known flaky" section if any Unity-side plugin behaviors remain inconsistent.

## Track 3: High-End Unity Workflows

This is the part that makes the repo feel powerful, not just compatible.

### P0

- Improve `workflow build-fps-sample` so it feels like a believable starter scene, not a debug blockout.
- Add better default composition:
  - stronger lighting contrast
  - better materials
  - more readable targets
  - clearer HUD
  - sane mouse sensitivity defaults
- Add a proper shooting validation step:
  - target hit feedback
  - ammo updates
  - visible hit markers or impact effect

### P1

- Add `workflow build-third-person-sample`.
- Add `workflow build-2d-platformer-sample`.
- Add `workflow build-topdown-sample`.
- Add `workflow build-ui-showcase`.
- Add `workflow build-advanced-scene` for a more presentation-ready environment.

### P2

- Add reusable "quality presets" for samples:
  - `prototype`
  - `gameplay`
  - `presentation`
- Add optional post-processing, fog, and audio dressing where supported.
- Add generated materials and scene dressing that fit URP/2D defaults better.

## Track 4: Visual Verification

### P0

- Make screenshot capture part of every visually meaningful workflow.
- Save paired Scene/Game captures into the runtime capture folder with predictable names.
- Add simple visual heuristics:
  - too bright
  - too dark
  - empty frame
  - HUD overlap
  - missing crosshair

### P1

- Add a lightweight capture review command that summarizes obvious visual problems from the last run.
- Store capture metadata in the debug report so visual regressions can be tracked over time.

## Track 5: Contributor Clarity

### P0

- Publish the tool coverage matrix in the repo.
- Link this file from the README.
- Add a "good first issue" bucket:
  - tool alias fixes
  - category probe builders
  - new live-pass profiles
  - new high-level workflows

### P1

- Open GitHub issues for each major category instead of keeping all planning in one file.
- Tag issues by:
  - `tool-coverage`
  - `live-testing`
  - `visual-quality`
  - `workflow`
  - `docs`

## Immediate Next Sprint

These are the next best moves right now:

1. Reduce the `deferred` count in the checked-in tool coverage matrix, starting with `terrain`, `ui`, `lighting`, and `animation`.
2. Add failure-focused live-pass summary output and port-hop reporting polish.
3. Improve `workflow build-fps-sample` visuals, shooting feedback, and default sensitivity tuning.
4. Add automatic Scene/Game capture review to heavy workflows.
5. Turn the highest-value roadmap items into GitHub issues.

## Notes

- The CLI remains the primary product.
- The thin MCP adapter should stay curated and efficient, not balloon into hundreds of noisy top-level tools.
- If we later build a clean-room Unity backend, this roadmap should split into "CLI/MCP layer" and "Unity runtime/backend layer".
