# Contributing

Thanks for helping improve CLI Anything Unity MCP.

This project is alpha. Contributions that make the assistant more honest, more Unity-aware, and easier to install are especially valuable.

## Project Scope

This repo owns:

- Python CLI and agent backend.
- File IPC client and execution loop.
- Unity editor scripts under `unity-scripts/Editor/`.
- Agent tab UX.
- Local memory, ledger, tests, docs, and packaging.

The key direction: the LLM should decide what to do from context. The backend should provide tools, validation, execution, and verification. Avoid adding task-specific hardcoded recipes unless they are small safety or validation rules.

## Local Setup

```powershell
python -m pip install -e .
```

Optional test dependency:

```powershell
python -m pip install pytest
```

## Run Tests

Full suite:

```powershell
python -m unittest discover -s cli_anything/unity_mcp/tests -t . -v
```

Quick smoke:

```powershell
python -m unittest cli_anything.unity_mcp.tests.test_chat_e2e -v
cli-anything-unity-mcp --help
```

If your change touches Unity editor behavior, also test manually in a real Unity project.

## Good First Contribution Areas

- Clearer setup docs.
- Better route error messages.
- Stronger File IPC route tests.
- Unity Undo coverage audits.
- Compile/console verification after script changes.
- Screenshot/evidence capture after visual changes.
- Target resolution from hierarchy, components, and scripts.
- Agent tab UI polish.

## Pull Request Checklist

Please include:

- What user workflow changed.
- What was verified.
- Test output or why tests were not possible.
- Screenshots or short video for UI changes.
- Docs updates for user-facing behavior.

If public behavior changes, update:

- `README.md`
- `PLAN.md` if direction changed
- `TODO.md` if priority changed
- `CHANGELOG.md`

## Contributor Rights And Sign-Offs

This repository uses a lightweight contributor rights policy so future project ownership, relicensing, or commercial arrangements stay clear.

For outside contributors:

- Read [CLA.md](CLA.md) before opening a non-trivial pull request.
- Sign off commits with `git commit -s`.
- Be ready to leave an explicit PR comment agreeing to the CLA policy if a maintainer asks.

Helpful command:

```powershell
git commit -s -m "Describe your change"
```

## Reporting Issues

Good bug reports include:

- Unity version.
- Python version.
- Commit or package version.
- Whether you used File IPC or another transport.
- Exact prompt or command.
- Expected result.
- Actual result.
- Relevant `.umcp` status/history/log files if safe to share.

Do not include API keys or private project assets in issues.
