# Local-First Learning System Design

Date: 2026-04-14
Repo: `C:\Users\mazen\OneDrive\Desktop\New Unity MCP Replacement\CLI\unity-mcp\agent-harness`

## Goal

Add a learning system that makes the Unity assistant improve from real runs, real failures, and real outcomes without turning the product into an opaque telemetry backend.

The design target is:

- local-first by default
- inspectable and explainable
- useful before any hosted service exists
- compatible with later optional redacted sync
- grounded in reusable workflows, not freeform chat logs

This is not a generic analytics project. It is the learning loop for a Unity AI developer.

## Problem Statement

The current product can already inspect, score, fix, benchmark, compare, and improve Unity projects. That makes it useful, but static.

Today, when the assistant succeeds or fails:

- we do not consistently preserve the run in a replayable format
- we do not rank which workflow or fix path worked best
- we do not build structured memory from repeated project patterns
- we do not convert enough real runs into eval cases

That means the product still improves mostly through manual prompt and workflow edits. That is too slow if the goal is to become better than broader competitors with larger tool catalogs.

## Recommendation

Build a `local-first learning loop` in three layers:

1. `Run ledger`
Store structured records for meaningful workflow runs and outcomes.

2. `Memory`
Promote recurring facts into structured project, user, and system memory.

3. `Eval and replay`
Turn real runs into replayable cases and benchmarkable regressions.

Only after those are working should the product consider optional cloud sync, retrieval ranking, or model training.

This is the highest-leverage path because it improves:

- workflow selection
- fix reliability
- recurrence handling
- user trust
- product iteration speed

## Why This Is The Right Wedge

Competing Unity AI projects can win on breadth, built-in tool count, or installation polish.

This product should win on:

- trust
- visible assistant quality
- workflow rigor
- learning speed
- proof quality

The learning system is how the product compounds instead of only expanding.

## Scope

### In Scope

- structured local run records
- structured memory promotion rules
- replayable eval-case generation
- privacy and redaction rules
- optional-sync boundary design
- ranking inputs for future workflow and prompt selection
- explicit subagent/planning guidance

### Out of Scope

- default cloud sync
- raw project upload by default
- fine-tuning the base model
- autonomous self-modifying behavior
- collecting unstructured full chat history as the main learning input

## Product Outcome

After this system exists, the product should be able to:

- remember recurring facts about a Unity project
- recognize repeated failure modes
- compare which fix paths succeed most often
- replay important runs as evals
- improve workflow defaults over time
- optionally share redacted outcomes later without changing the local-first core

The user should still be able to inspect what was recorded and understand why the assistant is behaving differently.

## Core Design

### 1. Learning Input Boundary

The system should learn from structured outcomes, not vague activity.

High-value inputs:

- user intent
- selected workflow
- workflow arguments
- routes called
- route failures and latency
- benchmark deltas
- applied fixes
- skipped fixes
- whether the fix was kept, reverted, or rerun
- project context summary:
  - Unity version
  - render pipeline
  - key packages
  - scene and asset summary

Low-value inputs:

- full raw chat transcripts as the primary signal
- raw project files by default
- giant console dumps with no classification
- activity logs without outcome labels

### 2. Storage Model

#### Local Run Ledger

Persist each important run to a bounded local store.

Recommended record shape:

- `runId`
- `timestamp`
- `projectId`
- `projectPathHash` or local project identity
- `source`
  - CLI
  - Agent tab
  - benchmark
  - debug doctor
- `intent`
- `workflow`
- `workflowArgs`
- `liveUnityAvailable`
- `selectedTarget`
- `contextSummary`
- `result`
  - success
  - partial
  - failure
- `applied`
- `skipped`
- `scoreBefore`
- `scoreAfter`
- `scoreDelta`
- `errorSummary`
- `artifacts`
  - benchmark json
  - markdown report
  - captures
- `followUpSignal`
  - accepted
  - rerun
  - reverted
  - unknown

#### Memory Layers

Three memory layers are enough for v1:

1. `Project memory`
- installed packages
- render pipeline
- common recurring failures
- preferred working patterns discovered from the project
- recurring scene hygiene gaps

2. `User memory`
- preferred safety level
- preferred surface:
  - CLI
  - Unity UI
- preferred output style
- tolerance for auto-apply behavior

3. `System memory`
- workflow success rates
- fix success rates
- recurring route failure patterns
- strongest prompts/selection rules once ranking exists

These should be structured and queryable, not one long prose blob.

### 3. Eval And Replay

Every meaningful improvement path should be replayable.

Replay inputs:

- project context summary
- workflow intent
- workflow chosen
- expected applied/skipped behavior
- expected score movement when applicable

Replay outputs:

- matched workflow choice
- same or better result class
- no forbidden risky action
- stable report formatting

Sources for replay cases:

- real user runs that solved something important
- benchmark runs
- failure cases that exposed regressions
- live repair flows with strong before/after evidence

### 4. Privacy Model

Local-first is the default.

Rules:

- store locally by default
- no background upload by default
- redact before any optional sync
- let the user inspect what is stored
- define exactly which fields are sync-safe

Never sync by default:

- raw scripts
- raw scene files
- raw full chat history
- raw project paths
- secrets

Safe candidates for optional sync later:

- normalized workflow outcome
- redacted error class
- package and pipeline summary
- score delta
- applied/skipped fix labels
- artifact summaries or sanitized markdown

### 5. Optional Cloud Boundary

The product should not depend on a backend to be useful.

If a hosted layer is added later, it should do only these jobs:

- aggregate redacted run outcomes
- aggregate eval results
- rank workflows and prompts
- support a shared benchmark dashboard

The hosted layer should be an accelerator, not a dependency.

## Architecture

### Local Components

1. `run recorder`
- hooks into workflow completion paths
- writes bounded structured run records

2. `memory manager`
- promotes repeated patterns into memory
- expires or compacts stale records

3. `eval builder`
- turns selected runs into replayable fixtures

4. `learning viewer`
- surfaces recent runs, outcomes, and recurring patterns in CLI and later Unity UI

### Future Optional Components

1. `redaction pipeline`
- strips unsafe fields before export

2. `sync client`
- explicit opt-in upload of redacted outcomes

3. `ranking service`
- computes best workflow/fix/prompt choices from outcomes

## Rollout Phases

### Phase L1 — Local Run Ledger

Deliver:

- workflow run schema
- local persistence
- artifact linking
- compact retention rules

Success criteria:

- important workflows create inspectable run records
- records are stable enough for replay/eval generation

### Phase L2 — Structured Memory

Deliver:

- project memory
- user preference memory
- recurring-pattern memory

Success criteria:

- repeated patterns can influence safe defaults
- memory stays structured and bounded

### Phase L3 — Eval And Replay

Deliver:

- replay case format
- fixture generation from real runs
- CLI replay/eval command

Success criteria:

- regressions can be caught from real product behavior
- benchmark and repair flows can be replayed

### Phase L4 — Optional Redacted Sync

Deliver:

- explicit sync configuration
- redaction rules
- hosted aggregation of outcome summaries

Success criteria:

- local-only users lose nothing
- hosted users gain shared learning and ranking

### Phase L5 — Ranking And Retrieval

Deliver:

- workflow ranking from outcome quality
- retrieval over relevant prior runs
- stronger default workflow selection

Success criteria:

- workflow selection measurably improves
- repeated failures drop on known scenarios

## What To Build First

The first implementation slice should be narrow:

1. record `workflow improve-project`
2. record `workflow benchmark-report`
3. record `workflow benchmark-compare`
4. record bounded `quality-fix --apply` runs

Why:

- these already have structured outputs
- they already produce meaningful deltas
- they already support proof artifacts
- they are the right seed set for a learning loop

## Validation

The learning system is only worth shipping if it improves product behavior without reducing trust.

Validate against:

- run-record completeness
- replay reliability
- privacy boundary correctness
- storage boundedness
- usefulness of memory in later workflow selection

Core checks:

- can a real improvement run be recorded cleanly?
- can it be replayed as an eval?
- can the record be inspected by a user?
- can unsafe fields be kept local?
- does the system help choose better defaults later?

## Risks

### 1. Generic Telemetry Drift

Risk:
The system degenerates into analytics noise.

Mitigation:
Only store structured run outcomes that can drive memory or evals.

### 2. Hidden Cloud Dependence

Risk:
The product quietly becomes backend-dependent.

Mitigation:
Keep local-first as a hard rule. Hosted sync stays optional.

### 3. Unbounded Storage

Risk:
The run ledger becomes a dumping ground.

Mitigation:
Use bounded retention, summaries, and promotion into structured memory.

### 4. Premature Training

Risk:
Attention shifts to fine-tuning before the traces are good.

Mitigation:
Do not consider tuning until replay/eval quality is already strong.

## Subagent Brief

Any planning or architecture subagent working on this area should know:

- the goal is the best open-source Unity AI developer, not the largest Unity MCP tool catalog
- the primary wedge is trust, visible assistant quality, learning speed, and proof
- local-first is non-negotiable
- learning should come from structured outcomes, not vague telemetry
- reusable workflows remain the execution backbone
- any learning component must stay inspectable and explainable

Subagents should not optimize for:

- tool count as the main success metric
- raw project collection
- early fine-tuning
- backend dependence
- broad autonomous behavior without workflow gates

## Recommendation

Write the implementation plan for `Phase L1 — Local Run Ledger` next.

That is the smallest slice that:

- creates real product leverage
- fits the current roadmap
- respects local-first principles
- gives later memory and eval work something solid to build on
