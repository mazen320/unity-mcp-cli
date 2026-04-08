# Unity MCP CLI Harness

Target software:
- Server source: `C:\Users\mazen\OneDrive\Desktop\New Unity MCP Replacement\CLI\unity-mcp-server`
- Plugin source: `C:\Users\mazen\OneDrive\Desktop\New Unity MCP Replacement\CLI\unity-mcp-plugin`

Goal:
- Replace the MCP protocol layer with a local CLI that Codex can call directly.
- Preserve the real backend by talking to the Unity plugin's localhost HTTP bridge.
- Keep multi-instance discovery by reading the same `UnityMCP/instances.json` registry file used by the original server.

What this harness ships:
- A stateful Click CLI with REPL mode when no subcommand is given.
- Session persistence for selected Unity instance and recent command history.
- Direct wrappers for common workflows: instance routing, state, scenes, console, play mode, builds, scripts, context, undo/redo.
- Generic `route` and `tool` commands so the long tail of Unity commands still stays reachable without authoring hundreds of bespoke wrappers.

Design notes:
- Queue mode is used by default so the CLI still benefits from the plugin's fair scheduling and agent tracking.
- If queue endpoints are unavailable, the harness falls back to legacy direct POST calls.
- Unity Hub commands are intentionally out of scope for the first pass because the practical cost issue is the MCP protocol, not the editor bridge.
