# cli-anything-unity-mcp

`cli-anything-unity-mcp` is a direct CLI client for Unity projects that can use either an optional Unity MCP HTTP plugin or the standalone File IPC bridge in this repo.

Instead of speaking MCP over stdio, it talks to the Unity package's local HTTP bridge on `127.0.0.1` and uses the shared instance registry to discover running editors.

Common examples:

```powershell
cli-anything-unity-mcp instances
cli-anything-unity-mcp select 7890
cli-anything-unity-mcp scene-info
cli-anything-unity-mcp tool unity_gameobject_create --params "{\"name\":\"Cube\",\"primitiveType\":\"Cube\"}"
cli-anything-unity-mcp route search/by-name --param name=Player
cli-anything-unity-mcp
```

Notes:
- REPL mode starts automatically if no subcommand is given.
- `--json` emits compact machine-readable JSON for Codex-friendly scripting.
- Queue mode is enabled by default and falls back to legacy POST mode if needed.
