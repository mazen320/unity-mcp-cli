# Unity Mastery Pack Phase 1 Design

Date: 2026-04-11
Repo: `C:\Users\mazen\OneDrive\Desktop\New Unity MCP Replacement\CLI\unity-mcp\agent-harness`

## Goal

Evolve the Unity CLI from a capable bridge and debug harness into a high-trust Unity expert that feels closer to a senior game team than a generic coding assistant.

Phase 1 focuses on content quality and project direction first, because those areas are:

- visible to the user immediately
- inspectable through Unity and project files
- auditable without full gameplay simulation
- a strong foundation for later gameplay-feel and systems passes

The Phase 1 assistant should be able to inspect a Unity project, understand which content pipelines are in use, critique quality using evidence, and return concrete, actionable recommendations or safe fixes.

## Problem Statement

The current CLI is strong at transport, debugging, route discovery, project inspection, and basic workflow orchestration. It is not yet opinionated or expert enough in the way a strong game developer, technical artist, animator, or UI designer would be.

Today it can answer questions and inspect project state, but it does not yet consistently behave like:

- a technical artist who catches weak material, shader, and VFX usage
- an animator who recognizes rig, avatar, import, and controller issues
- a UI/HUD designer who catches bad anchors, scaling, hierarchy, or readability
- a level art or game director who can critique scene composition and overall direction

The result is that the CLI can be powerful, but it does not yet feel "trained" in a professional Unity sense.

## Product Outcome

After Phase 1, the CLI should feel like a Unity content-quality director with specialist lenses.

It should:

- inspect a live Unity project or direct project path
- detect important package and render-pipeline context
- choose an expert lens intentionally instead of giving generic advice
- score quality based on real evidence
- explain what is wrong in clear Unity language
- recommend the next best actions in priority order
- optionally apply safe, bounded fixes

It should not pretend to fully replace high-end art direction, animation production, or environment art creation in Phase 1. Instead, it should become a reliable expert reviewer and structured fixer.

## Recommendation

Use a `director + specialist lenses + evidence-driven workflows` architecture.

This is better than building one giant generalist profile because:

- specialist behavior is easier to reason about and trust
- the CLI can match advice to actual package and project context
- audits can be tested lens by lens
- the same project can be reviewed from multiple expert angles without muddy output

Phase 1 should prioritize the content and presentation pipeline:

1. `director`
2. `animation`
3. `tech-art`
4. `ui`
5. `level-art`

Gameplay and feel-specific systems should be Phase 2, once the content-quality layer is reliable.

## Scope

### In Scope

- expert-lens selection and resolution
- package-aware and render-pipeline-aware inspections
- quality scoring for content-focused areas
- project critique workflows
- safe recommendation and bounded auto-fix workflows
- benchmark scenes and eval cases for content-quality problems
- documentation and developer-profile support for the new expert layer

### Out of Scope

- model fine-tuning
- full autonomous worldbuilding
- one-shot generation of production-ready levels
- advanced gameplay-feel simulation
- full replacement of package-specific authoring tools like Timeline, VFX Graph, or ProBuilder editors

## Core Concepts

### 1. Project Brain

The CLI already has the beginnings of a project brain through `workflow inspect`, `workflow asset-audit`, memory, and direct bridge inspection. Phase 1 should formalize that into a reusable expert context bundle.

The expert context bundle should include:

- Unity version
- active render pipeline
- installed packages
- scene and prefab counts
- material, shader, texture, animation, model, test, and UI asset counts
- importer hints from `.meta` files
- selection context
- scene stats
- console and compile health
- recent captures when available

This bundle becomes the shared input to every expert lens.

### 2. Specialist Lenses

Each lens should have:

- a clear purpose
- a defined evidence set
- a scoring rubric
- recommendation rules
- optional safe fixes

#### Director Lens

Purpose:
- critique overall project and scene direction
- identify missing structure, weak readability, weak guidance, and content-pipeline gaps

Evidence:
- project brain
- captures
- scene stats
- guidance files
- package list

Outputs:
- project-level direction notes
- top priorities
- missing pipeline recommendations

#### Animation Lens

Purpose:
- inspect rigs, clips, controllers, avatars, import settings, and animation pipeline readiness

Evidence:
- model importer settings
- animation clips
- animator controllers
- controller wiring
- scene object animator usage

Outputs:
- rig and avatar findings
- import warnings
- controller-gap findings
- safe next-step fixes

#### Tech-Art Lens

Purpose:
- inspect materials, shaders, textures, VFX readiness, renderer setup, and render-pipeline consistency

Evidence:
- materials
- renderer usage
- texture import settings
- pipeline package state
- shader references
- scene lighting summary

Outputs:
- material/shader consistency findings
- texture import findings
- VFX readiness suggestions
- render-pipeline mismatch findings

#### UI Lens

Purpose:
- inspect Canvas hierarchy, scaling, anchors, text readability, HUD layering, and likely UX clarity issues

Evidence:
- Canvas and RectTransform hierarchy
- CanvasScaler settings
- anchors and offsets
- capture images
- scene/game-view context

Outputs:
- layout and scaling findings
- hierarchy clarity findings
- likely readability issues
- safe fix candidates for anchors, scaler setup, and naming/structure

#### Level-Art Lens

Purpose:
- inspect scene readability, composition, prop balance, lighting readability, traversal framing, and encounter-space clarity

Evidence:
- scene hierarchy
- scene stats
- captures
- light counts and placement
- object density patterns

Outputs:
- readability findings
- flatness, clutter, or emptiness findings
- composition and coverage recommendations

### 3. Quality Scores

Each lens should return a normalized score with category detail rather than a vague pass/fail.

Recommended score model:

- `0-39`: poor
- `40-59`: weak
- `60-74`: workable
- `75-89`: strong
- `90-100`: excellent

Each score should include:

- `score`
- `grade`
- `confidence`
- `evidenceCount`
- `topFindings`
- `topRecommendations`

Confidence matters because some lenses can only infer quality from partial signals. The CLI should say when confidence is limited instead of overclaiming.

## CLI Surface Design

Phase 1 should add expert-facing workflows rather than burying everything under raw routes.

Recommended commands:

```powershell
cli-anything-unity-mcp --json workflow expert-audit --lens director --port <port>
cli-anything-unity-mcp --json workflow expert-audit --lens animation --port <port>
cli-anything-unity-mcp --json workflow expert-audit --lens tech-art --port <port>
cli-anything-unity-mcp --json workflow expert-audit --lens ui --port <port>
cli-anything-unity-mcp --json workflow expert-audit --lens level-art --port <port>
cli-anything-unity-mcp --json workflow scene-critique --port <port>
cli-anything-unity-mcp --json workflow quality-score --port <port>
cli-anything-unity-mcp --json workflow quality-fix --lens ui --fix anchors --port <port>
```

Recommended developer-profile additions:

- `director`
- `animator`
- `tech-artist`
- `ui-designer`
- `level-designer`

These profiles should change tone, prioritization, and suggested workflows, but not become separate transport systems.

## Architecture

### New Core Modules

Recommended Python additions:

- `core/expert_context.py`
  - build the shared project/lens input bundle
- `core/expert_lenses.py`
  - lens registry, score contracts, result shapes
- `core/expert_rules/`
  - per-lens heuristic modules
- `core/expert_fixes.py`
  - bounded safe-fix planning and execution
- `core/expert_evals.py`
  - benchmark definitions and result scoring

Recommended command additions:

- `commands/workflow.py`
  - add expert audit and critique entrypoints
- `commands/developer.py`
  - expose new specialist profiles

### Unity-Side Support

Most Phase 1 can be built on current bridge capabilities plus targeted route additions.

Likely route additions:

- richer animator/controller inspection
- deeper material and renderer info
- canvas and RectTransform layout summaries
- scene composition summaries
- optional capture metadata for critique loops

These should be added to the standalone path when possible, and only fall back to the plugin path where the standalone bridge does not yet have parity.

## Data Flow

1. User runs an expert workflow.
2. CLI resolves the target Unity project or direct project path.
3. CLI builds the expert context bundle from:
   - cached inspect data
   - fresh Unity bridge data
   - direct asset/meta scans
   - captures if needed
4. CLI resolves the correct lens and supporting package context.
5. Lens rules evaluate the context and produce:
   - findings
   - score
   - confidence
   - recommendations
   - safe fixes, if any
6. CLI returns a concise summary plus structured JSON.
7. If the user requests a fix, the CLI executes only the bounded fix plan and then re-runs the relevant audit.

## Safety And Trust

This system should be opinionated, but never reckless.

Rules:

- never auto-apply destructive changes without explicit user intent
- never claim certainty when evidence is weak
- always surface what evidence was used
- show why a score or recommendation exists
- prefer preview or dry-run mode for multi-object or multi-asset changes
- re-audit after any fix workflow

Safe auto-fix examples:

- create missing guidance files
- create sandbox scene
- repair common CanvasScaler defaults
- fix anchor presets for known HUD patterns
- normalize obvious texture import mismatches

Unsafe changes that should stay review-first:

- broad prefab restructuring
- large material swaps
- controller rewiring across many animators
- scene-wide lighting overhauls

## Error Handling

Expert workflows should degrade gracefully.

If required evidence is missing:

- return partial audit results
- lower confidence
- state exactly what is missing
- recommend the next acquisition step, such as captures, selection, or a richer route

If a route is unsupported on standalone File IPC:

- prefer a clear fallback message over a generic transport failure
- only suggest plugin-backed execution when the lens genuinely requires it

If a package is absent:

- do not produce package-specific warnings as if the feature should exist
- instead recommend installation only when the project intent suggests it

## Testing And Evals

Phase 1 should be evaluated with benchmark fixtures, not just route-level unit tests.

Recommended benchmark buckets:

- bad rig import
- no avatar / wrong rig type
- animation clips without controller usage
- controller with obvious missing state/parameter wiring
- UI with broken anchors or scaler setup
- HUD overlap and likely readability issues
- overbright or flat lighting
- material/shader mismatch
- texture import mismatch
- weak scene readability or poor prop/cover balance

Each benchmark should define:

- fixture setup
- expected top findings
- expected score band
- expected top recommendation

Success means the CLI catches the right class of issue consistently, not that it uses perfect wording.

## Rollout Plan

### Milestone 1: Expert Foundations

- create expert context bundle
- add lens registry
- add new specialist developer profiles
- add `workflow expert-audit`

### Milestone 2: Content Lenses

- implement `director`
- implement `animation`
- implement `tech-art`
- implement `ui`
- implement `level-art`

### Milestone 3: Quality Scores And Safe Fixes

- add scoring contracts
- add confidence and evidence reporting
- add first bounded fix workflows

### Milestone 4: Benchmarks

- add benchmark fixtures
- add eval runner
- track lens quality over time

## Why This Comes Before Gameplay-Focused Mastery

Gameplay expertise matters, but content-quality expertise is the faster path to something that feels genuinely professional in Unity because:

- content problems are easier to inspect deterministically
- the user sees the improvement immediately
- the CLI can critique visual and structural quality without full game simulation
- this lays the groundwork for later gameplay-feel and systems analysis

Once Phase 1 is reliable, Phase 2 should add gameplay, physics, controller, encounter, and feel-focused specialist lenses.

## Decision

Proceed with `Unity Mastery Pack Phase 1` as a content-first expert layer built on top of the existing CLI, project scan, memory, developer-profile, and bridge systems.

This phase should make the CLI feel meaningfully more "trained" for real Unity work without requiring model fine-tuning first.
