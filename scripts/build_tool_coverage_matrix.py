from __future__ import annotations

import json
from pathlib import Path

from cli_anything.unity_mcp.core.tool_coverage import build_tool_coverage_matrix


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    output_path = repo_root / "cli_anything" / "unity_mcp" / "data" / "tool_coverage_matrix.json"
    payload = build_tool_coverage_matrix(include_unsupported=True, summary_only=False)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
