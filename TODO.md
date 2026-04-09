# TODO

This file is the working roadmap for taking `unity-mcp-cli` from "good CLI wrapper" to "serious Unity agent layer".

It focuses on three outcomes:

- full practical tool coverage and parity
- proof through repeatable live testing
- a CLI-first Unity assistant that is easier to debug, trust, and extend than the current alternatives

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
The next phase is coverage, reliability, observability, and eventually owning more of the backend.

## Definition Of Done

We should consider the tool layer "done enough" when all of these are true:

- every curated MCP tool has automated coverage
- every important upstream advanced-tool category has at least one live validation path
- failure cases produce useful debug output instead of silent breakage
- the CLI can explain likely Unity failures in one pass instead of forcing manual detective work
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

## Track 3: Unity Assistant Quality

### P0

- Keep improving `debug snapshot`, `debug doctor`, `debug watch`, and `debug capture` so the CLI feels like an actual Unity assistant.
- Include the most recent CLI command history in failure triage.
- Explain likely causes for:
  - compilation failures
  - missing scripts or references
  - queue contention
  - bridge restarts or timeouts
  - play-mode state leaks
- Prefer commands that recommend the next useful CLI action instead of dumping raw state only.

### P1

- Add better route-level timeouts, bridge recovery hints, and queue diagnostics.
- Expand issue-specific helper commands for common Unity failures.
- Make tool errors more actionable by surfacing route, category, likely blocker, and suggested retry path.

### P2

- Start separating "CLI layer" work from "future custom Unity backend" work so backend independence becomes a real track, not just an idea.

## Track 4: Validation Probes

### P0

- Keep validation centered on temporary probe creation, scene checks, and screenshot review instead of demo/sample content.
- Make probe-driven validation stable enough to test:
  - script sync
  - play-mode transitions
  - screenshot capture
  - material/visibility sanity
  - advanced-category route safety

### P1

- Add a lightweight capture review command that summarizes obvious visual problems from the last run.
- Store capture metadata in the debug report so visual regressions can be tracked over time.

## Track 5: Visual Verification

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

- Add comparison support so two validation runs can be reviewed side by side.
- Flag when the Game view is clearly blocked by first-person meshes or bad camera placement.

## Track 6: Contributor Clarity

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
2. Keep improving CLI-first debugging so the harness can explain Unity failures clearly.
3. Add failure-focused live-pass summary output and port-hop reporting polish.
4. Add automatic Scene/Game capture review to heavy workflows.
5. Turn the highest-value roadmap items into GitHub issues.

## Notes

- The CLI remains the primary product.
- The thin MCP adapter should stay curated and efficient, not balloon into hundreds of noisy top-level tools.
- If we later build a clean-room Unity backend, this roadmap should split into "CLI/MCP layer" and "Unity runtime/backend layer".
