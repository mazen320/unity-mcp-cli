from __future__ import annotations

import json
from contextlib import redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True)
class EmbeddedCLIOptions:
    host: str = "127.0.0.1"
    default_port: int = 7890
    registry_path: Path | None = None
    session_path: Path | None = None
    port_range_start: int = 7890
    port_range_end: int = 7899
    agent_id: str = "cli-anything-unity-mcp-mcp"
    legacy: bool = False

    def build_base_args(self, *, json_output: bool = True) -> list[str]:
        args = [
            "--host",
            self.host,
            "--default-port",
            str(self.default_port),
            "--agent-id",
            self.agent_id,
            "--port-range-start",
            str(self.port_range_start),
            "--port-range-end",
            str(self.port_range_end),
        ]
        if self.registry_path:
            args.extend(["--registry-path", str(self.registry_path)])
        if self.session_path:
            args.extend(["--session-path", str(self.session_path)])
        if json_output:
            args.append("--json")
        if self.legacy:
            args.append("--legacy")
        return args


def run_cli_json(
    argv: Sequence[str],
    options: EmbeddedCLIOptions,
    *,
    prog_name: str = "cli-anything-unity-mcp",
) -> Any:
    from ..unity_mcp_cli import cli

    stdout = StringIO()
    full_argv = [*options.build_base_args(json_output=True), *argv]
    with redirect_stdout(stdout):
        try:
            cli.main(args=full_argv, prog_name=prog_name, standalone_mode=False)
        except SystemExit as exc:  # pragma: no cover - defensive guard
            code = exc.code if isinstance(exc.code, int) else 1
            if code:
                raise RuntimeError(f"Embedded CLI exited with status {code}.") from exc

    raw = stdout.getvalue().strip()
    if not raw:
        return {}
    last_line = next((line for line in reversed(raw.splitlines()) if line.strip()), "")
    if not last_line:
        return {}
    return json.loads(last_line)
