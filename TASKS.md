# TASKS

This file is the full backlog. [TODO.md](TODO.md) is the short current-focus view.

Columns:

- `Priority`: `P0` is highest
- `Estimate`: `S`, `M`, `L`, `XL`
- `Status`: current tracked state

## E1 Foundation Cleanup

| ID | Title | Priority | Estimate | Status | Description |
| --- | --- | --- | --- | --- | --- |
| E1-T1 | Delete CLI workflow * user-facing commands | P0 | M | Active | Remove improve-project, benchmark-report, benchmark-compare, quality-score, expert-audit, scene-critique, quality-fix, bootstrap-guidance, asset-audit, create-sandbox-scene from commands/workflow.py. Keep underlying helpers. |
| E1-T2 | Delete CLI developer-profile layer | P0 | S | Done | Remove developer list/current/use/clear, --developer-profile flag, --developer-profiles-path flag. |
| E1-T3 | Delete Agent tab improve-project report card | P0 | M | Done | Strip score delta display, applied/skipped summary, rerun button, markdown export from CliAnythingWindow.cs. |
| E1-T4 | Replace PLAN.md with new vision | P0 | S | Done | Drop in the new PLAN.md reflecting collaborator-not-generator, conversation, consent, Undo, tedium. |
| E1-T5 | Rewrite README.md around Agent tab | P0 | M | Done | Agent tab leads. CLI demoted to Debugging / Power Users section. Kill tool-coverage % and score marketing. |
| E1-T6 | Rewrite TODO.md as skill-first backlog | P0 | S | Done | Replace execution tracks with skill backlog. Reference TASKS.md. |
| E1-T7 | Rewrite AGENTS.md around consent + Undo + chat | P0 | M | Done | Drop workflow * recommendations. Default workflow = natural language + skill + consent + Undo checks. |
| E1-T8 | Internalize expert lenses | P0 | M | Active | Keep core/expert_lenses.py and expert_rules as internal detection feeding the agent. Remove score emission from user-facing surfaces. |
| E1-T9 | Drop new WRITING_A_SKILL.md into docs/skills/ | P0 | S | Done | Replace existing template. |
| E1-T10 | Clean up CHANGELOG going forward | P1 | S | Active | Stop adding benchmark/score/improve-project entries. Add Direction change note. |

## E10 Team Features

| ID | Title | Priority | Estimate | Status | Description |
| --- | --- | --- | --- | --- | --- |
| E10-T1 | Convention config file | P2 | M | Backlog | .umcp/conventions.json committed. Team agreement overrides detection. |
| E10-T2 | Convention drift warnings | P2 | M | Backlog | Flag files breaking stated conventions. Offer alignment. |
| E10-T3 | Onboarding tour mode | P2 | L | Backlog | New team member walkthrough: systems, conventions, entry points, recent work. |
| E10-T4 | Auto-generated project docs | P2 | L | Backlog | Regenerate README sections, architecture overview from index + ledger. |
| E10-T5 | Tool documentation auto-gen | P2 | M | Backlog | Every copilot-built tool gets docs/tools/<tool>.md. |
| E10-T6 | Local team activity feed | P2 | M | Backlog | Aggregate ledger across team (committed or optional share). Fully local. |

## E11 Polish & Quality

| ID | Title | Priority | Estimate | Status | Description |
| --- | --- | --- | --- | --- | --- |
| E11-T1 | Cut failing tests per deletion commit | P0 | M | Active | As E1 deletions land remove invalid tests. Keep suite green each commit. |
| E11-T2 | Skill test template | P0 | M | Backlog | Standard 6 tests per skill matching WRITING_A_SKILL.md. physics_feel conforms. |
| E11-T3 | Error message quality pass | P1 | M | Backlog | Every user-facing error: what failed, why, next action. No raw exceptions. |
| E11-T4 | Cross-platform validation | P1 | L | Backlog | File IPC paths, .umcp folder, Python launcher work on Windows/macOS/Linux. |
| E11-T5 | Indexer performance budget | P1 | M | Backlog | Full index <10s for 1000 scripts. Incremental <500ms. CI fails on regression. |
| E11-T6 | Consent fatigue audit | P1 | S | Backlog | Review every consent prompt. Merge truly atomic ones. Never batch unrelated fixes. |
| E11-T7 | Undo coverage audit | P0 | M | Backlog | Every mutation route in StandaloneRouteHandler.cs has Undo.* wrapping. Fix gaps. |
| E11-T8 | First-run experience | P1 | M | Backlog | New user to working chat session in <2 min without doc-diving. |
| E11-T9 | Crash/hang recovery | P1 | M | Backlog | Bridge crash, Unity freeze, domain reload mid-request. Clean recovery, honest surfacing. |
| E11-T10 | Documentation accuracy sweep | P1 | M | Active | Grep for retired feature names in docs after E1. Zero hits required. |

## E2 Context Engine

| ID | Title | Priority | Estimate | Status | Description |
| --- | --- | --- | --- | --- | --- |
| E2-T1 | Design the index schema | P0 | M | Backlog | Define structured shape for scripts, assets, scenes, prefabs, packages, settings. Write as docs/context/INDEX_SCHEMA.md. |
| E2-T2 | Script indexer C# AST-level | P0 | L | Backlog | Parse C# with Roslyn-compatible tooling. Extract classes, MonoBehaviours, SOs, SerializeField fields, UnityEvents. Not regex. |
| E2-T3 | Asset indexer | P0 | M | Backlog | Walk Assets/ and read .meta files. Map guid to path to type. |
| E2-T4 | Scene + hierarchy indexer | P0 | M | Backlog | Snapshot active scene hierarchy + components via File IPC. Update incrementally. |
| E2-T5 | Prefab connection graph | P1 | M | Backlog | Map scene instances to prefab assets. Track overrides. Queryable graph. |
| E2-T6 | ScriptableObject inventory | P1 | M | Backlog | Scan SO assets, types, and who references them. |
| E2-T7 | Project settings indexer | P1 | S | Backlog | Read Tags, Layers, Input, Physics, Quality, Graphics settings. Surface RP, input system, scripting backend. |
| E2-T8 | Package manifest indexer | P0 | S | Backlog | Parse Packages/manifest.json and packages-lock.json. |
| E2-T9 | File-watcher for live refresh | P1 | M | Backlog | Watch Assets/, Packages/, ProjectSettings/ for changes. Debounce and re-index incrementally. |
| E2-T10 | Convention detection | P1 | L | Backlog | Infer naming, brace style, tabs/spaces, var usage, using-order, access modifier conventions. Code-gen uses this. |
| E2-T11 | Architecture pattern detection | P2 | L | Backlog | Detect Zenject/VContainer DI, SO architecture, event bus, MVVM, state machines. |
| E2-T12 | External context ingestion - markdown | P1 | M | Backlog | Ingest GDDs/specs from a configured path. Chunked with metadata for semantic queries. |
| E2-T13 | External context ingestion - spreadsheets | P2 | M | Backlog | Read CSV/XLSX design data. Expose as queryable data for generation. |
| E2-T14 | Index persistence | P1 | M | Backlog | Serialize index to .umcp/index/. Invalidate per-file by mtime+hash. |
| E2-T15 | Index query API for skills | P0 | M | Backlog | Expose clean Python API. Every skill uses this not ad-hoc scanning. |
| E2-T16 | Index health surface | P2 | S | Backlog | debug index-status command shows freshness, coverage, errors. |

## E3 Specialist Skills

| ID | Title | Priority | Estimate | Status | Description |
| --- | --- | --- | --- | --- | --- |
| E3-T1 | Skill base class + shared plumbing | P0 | M | Backlog | Extract common shape from physics_feel into core/skills/base.py. Registry for skills. |
| E3-T2 | Skill routing in chat bridge | P0 | M | Backlog | Route user messages to right skill by trigger + index context. Ambiguous matches ask for clarification. |
| E3-T3 | collision_setup skill | P0 | L | Backlog | Diagnose missing colliders, trigger vs solid, common setups. Propose with tradeoffs. File IPC apply + Undo. |
| E3-T4 | event_wiring skill | P0 | L | Backlog | Wire UnityEvents to target methods. List methods on target. Apply via SerializedProperty. |
| E3-T5 | animator_wiring skill | P0 | XL | Backlog | Animator state machine wiring: params, states, transitions. Uses existing File IPC animation routes. |
| E3-T6 | serialized_property skill | P1 | M | Backlog | Edit Inspector fields safely. Nested properties, arrays, object refs. Type-safe, Undo-grouped. |
| E3-T7 | scriptable_refs skill | P1 | M | Backlog | Wire ScriptableObject instances into scene/prefab fields. Detect unassigned refs. |
| E3-T8 | ui_canvas skill | P0 | L | Backlog | Canvas, CanvasScaler, GraphicRaycaster, EventSystem. Replace bulk bundle with per-fix flow. |
| E3-T9 | layer_matrix skill | P1 | M | Backlog | Tags/layers assignment and collision matrix. Bulk-assign via pattern match. |
| E3-T10 | prefab_overrides skill | P1 | L | Backlog | Detect drifted instances. Propose revert/apply-up/keep with per-override consent. |
| E3-T11 | audio_hygiene skill | P2 | S | Backlog | AudioListener placement/dedup, missing AudioSource, 2D vs 3D. |
| E3-T12 | physics_materials skill | P2 | M | Backlog | Friction, bounce, combine modes from gameplay feel keywords. |
| E3-T13 | ragdoll_setup skill | P1 | XL | Backlog | Joint wiring across a rig. Detect humanoid bones. Propose joint hierarchy with limits. |
| E3-T14 | animated_asset_swap skill | P2 | L | Backlog | Replace static model with animated. Rewire Animator, preserve references. |
| E3-T15 | input_binding skill | P1 | L | Backlog | Input System action maps. Create actions, bindings, hook PlayerInput. Detect legacy Input.* usage. |
| E3-T16 | reference_rewiring skill | P2 | L | Backlog | Post-refactor reference fixing across scene, prefab, SO, code. |
| E3-T17 | build_settings skill | P2 | M | Backlog | Scenes in build list, target platform, compression, development build. |

## E4 Debug Sidekick

| ID | Title | Priority | Estimate | Status | Description |
| --- | --- | --- | --- | --- | --- |
| E4-T1 | Cross-boundary runtime issue tracer | P1 | XL | Backlog | Trace issues across script + scene + asset + settings. Produce narrative root-cause hypothesis. |
| E4-T2 | Missing reference resolver | P1 | M | Backlog | Given a null, trace what field, what was assigned, when it disappeared. |
| E4-T3 | Serialized-field drift detector | P1 | M | Backlog | Detect script schema changes that scene objects didn't follow. Propose updates. |
| E4-T4 | Event graph visualizer | P2 | L | Backlog | Visualize UnityEvent/C# event connections in the scene. |
| E4-T5 | Render pipeline conflict detector | P1 | M | Backlog | Flag materials/shaders that don't match active RP. Per-material migration plan. |
| E4-T6 | Tag/layer code-vs-project checker | P2 | S | Backlog | Find CompareTag calls where tag doesn't exist. Offer to add. |
| E4-T7 | Runtime error classifier | P1 | M | Backlog | Parse log, cluster by root cause, one fix path per cluster not per line. |
| E4-T8 | Prefab override drift report | P2 | M | Backlog | Identify heavy-override instances. Flag variant candidates. |
| E4-T9 | Build error translator | P1 | M | Backlog | Compilation errors to plain-language cause + fix path. Expand error-heuristics engine. |

## E5 Code Generation

| ID | Title | Priority | Estimate | Status | Description |
| --- | --- | --- | --- | --- | --- |
| E5-T1 | Diff-first code change protocol | P1 | L | Backlog | Every script write: read > patch > diff > consent > apply > compile-verify. Never blind overwrite. |
| E5-T2 | Inline diff viewer in Agent tab | P1 | L | Backlog | Unified diff with syntax highlighting + approve/reject/modify buttons in chat. |
| E5-T3 | Convention-aware script generation | P1 | L | Backlog | Generated code follows detected conventions. Linting passes against existing code. |
| E5-T4 | Architecture-aware generation | P2 | L | Backlog | Honor detected architecture: DI, SO-based, etc. |
| E5-T5 | Modify X minimal-patch flow | P1 | M | Backlog | Read existing script, propose smallest diff. No rewriting untouched regions. |
| E5-T6 | Compile-verify + rollback | P1 | M | Backlog | After any script write trigger compile. On failure show errors, offer revert or iterate. |
| E5-T7 | Multi-file atomic changes | P2 | L | Backlog | One consent for N-file request. Atomic apply; all roll back on failure. |
| E5-T8 | Approve-all vs review-each modes | P2 | S | Backlog | Session toggle for trust level on small edits. |

## E6 Tool Builder

| ID | Title | Priority | Estimate | Status | Description |
| --- | --- | --- | --- | --- | --- |
| E6-T1 | Editor script generator from observed workflow | P2 | XL | Backlog | Observe repeats via ledger. Offer to codify as reusable tool. Writes to Assets/Editor/CopilotTools/. |
| E6-T2 | Custom gizmo builder | P2 | L | Backlog | Generate OnDrawGizmos methods for invisible state visualization. |
| E6-T3 | Procedural tool generator | P2 | XL | Backlog | Parameterized editor tools (spawn grids, scatter, layouts) as EditorWindows. |
| E6-T4 | Tool registry | P2 | S | Backlog | List copilot-built tools with metadata. |
| E6-T5 | Tool version control + attribution | P2 | S | Backlog | Every generated tool has a header: purpose, request, date, version. |
| E6-T6 | Tool test scaffolds | P2 | M | Backlog | Generated tools come with basic EditMode test template. |

## E7 Interactive Learning

| ID | Title | Priority | Estimate | Status | Description |
| --- | --- | --- | --- | --- | --- |
| E7-T1 | Explain this script mode | P2 | M | Backlog | Grounded explanation using index. Who calls, what depends on, how it fits. |
| E7-T2 | Explain this scene mode | P2 | M | Backlog | Summarize scene systems: player, enemies, UI, managers. Cross-references. |
| E7-T3 | How do I add X walkthrough | P2 | L | Backlog | Step-by-step tailored to architecture. Pause between steps. User confirms. |
| E7-T4 | Architecture diagram generator | P2 | L | Backlog | Mermaid/SVG diagram of project systems from index. |

## E8 Agent Tab UX

| ID | Title | Priority | Estimate | Status | Description |
| --- | --- | --- | --- | --- | --- |
| E8-T1 | Remove score/improve-project UI chrome | P0 | S | Backlog | Covered by E1-T3. Listed for epic completeness. |
| E8-T2 | Per-change consent prompt pattern | P0 | L | Backlog | Standard inline UI: proposal summary + approve/modify/reject. Used by every skill. |
| E8-T3 | Visible Undo affordance | P1 | M | Backlog | Compact inline Undo action after each applied change. Triggers Unity Undo. |
| E8-T4 | Multi-turn consent flow | P1 | M | Backlog | Show full plan, consent once, optional per-step pause. |
| E8-T5 | Before/after screenshot viewer inline | P1 | M | Backlog | Visual skills show before/after captures side-by-side in chat. |
| E8-T6 | Ledger viewer | P1 | M | Backlog | What did we do today timeline. Filter by skill/date. |
| E8-T7 | Convention detection surface | P2 | S | Backlog | Status indicator showing detected conventions. |
| E8-T8 | Indexer status indicator | P2 | S | Backlog | Show freshness, coverage, last refresh. |
| E8-T9 | External context drop zone | P2 | M | Backlog | Drag GDD/spec/CSV into chat. Triggers ingestion. |
| E8-T10 | Typing indicator + cancellable requests | P1 | S | Backlog | Thinking indicator + cancel button for long operations. |

## E9 Learning Loop

| ID | Title | Priority | Estimate | Status | Description |
| --- | --- | --- | --- | --- | --- |
| E9-T1 | Finalize run ledger schema | P1 | S | Backlog | Lock JSONL shape: skill, intent, options_presented, option_chosen, before, after, captures, ts, success, user_reverted. |
| E9-T2 | User reversion detection | P1 | M | Backlog | Detect Undo that reverts copilot action. Tag ledger entry. |
| E9-T3 | Skill ranking from ledger | P1 | M | Backlog | Rank options by historical user preference. Project > similar > global. |
| E9-T4 | Eval fixtures from ledger runs | P2 | L | Backlog | Replay historical runs against new skill versions for regression. |
| E9-T5 | Memory deprioritization of failed approaches | P1 | M | Backlog | Failed/reverted options get bottom ranking per project. |
| E9-T6 | Cross-skill pattern detection | P2 | L | Backlog | Suggest Y after X based on historical co-occurrence. |
| E9-T7 | Opt-in redacted sync - design only | P2 | L | Backlog | Design spec for future cloud sync. Redaction, consent, boundaries. No code. |
