# Start Here

This repo is an alpha Unity AI copilot. Start with the files below.

## For Users

1. Read [README.md](README.md).
2. Install the Python package with `python -m pip install -e .`.
3. Copy the scripts in `unity-scripts/Editor/` into `Assets/Editor/` in a Unity project.
4. Open Unity: `Window > CLI Copilot`.
5. Configure an API key through the window or `.umcp/agent.env`.
6. Ask a conversational question first, then try a bounded edit.

Good first test:

```text
What can you see in this project?
```

Then:

```text
Create a new scene for testing this feature and set up the required objects. Propose the plan first.
```

## For Contributors

1. Read [PLAN.md](PLAN.md) for direction.
2. Read [AGENTS.md](AGENTS.md) for engineering rules.
3. Read [CONTRIBUTING.md](CONTRIBUTING.md).
4. Run tests:

   ```powershell
   python -m unittest discover -s cli_anything/unity_mcp/tests -t . -v
   ```

5. Pick work from [TODO.md](TODO.md) or [TASKS.md](TASKS.md).

## Current Direction

Do not add more hardcoded game/task logic to Python. Improve the general loop:

- context
- route schemas
- LLM planning
- approval
- execution
- verification
- recovery

If the assistant says something happened but Unity did not confirm it, that is a bug.
