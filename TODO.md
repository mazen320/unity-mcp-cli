# TODO

Short current-focus view. The larger backlog lives in [TASKS.md](TASKS.md).

## Current Goal

Prepare the repo for open-source use while keeping the technical direction correct:

- LLM decides the Unity work.
- Backend provides context, route schemas, validation, execution, and verification.
- Unity confirms what actually changed.
- Public docs are honest about alpha status.

## Open-Source Readiness

- [x] MIT license present.
- [x] Contribution guide present.
- [x] Security policy present.
- [x] Code of conduct present.
- [x] GitHub issue and PR templates present.
- [x] CI workflow present.
- [x] README rewritten around real current behavior and roadmap.
- [x] PLAN rewritten around AI-driven Unity control.
- [x] AGENTS rewritten around correct engineering rules.
- [ ] Full test suite run before push.
- [ ] Manual Unity smoke test after restarting the agent backend.

## Immediate Engineering Priorities

1. Trust loop: route result readback, compile/console checks, visual capture, and no fake success.
2. Target resolution: infer objects from hierarchy, components, scripts, tags, and user language.
3. Generated-code safety: diff first, compile, repair or rollback.
4. Agent tab UX: plan cards, progress cards, evidence cards, visible Undo.
5. Context engine: scripts, scenes, prefabs, assets, settings, and packages.

## Known Open Issues

- The assistant can still overstate success if a route says OK but no follow-up readback verifies the final Unity state.
- Generated scripts need stronger compile-error repair and rollback.
- Visual workflows need real proof media: short GIFs or captures from actual in-editor chat plus applied Unity changes, not static placeholder screenshots.
- Some docs in the deeper backlog may still mention retired score/benchmark language.
- The project has local/import artifacts that should stay ignored and out of commits.

## Useful Commands

```powershell
python -m unittest discover -s cli_anything/unity_mcp/tests -t . -v
cli-anything-unity-mcp --help
cli-anything-unity-mcp --transport file --file-ipc-path <UnityProject> --json debug doctor
cli-anything-unity-mcp --transport file --file-ipc-path <UnityProject> --json agent sessions
```
