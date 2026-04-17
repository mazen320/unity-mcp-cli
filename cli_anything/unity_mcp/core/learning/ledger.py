"""Append-only run ledger for project-local learning."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _ledger_path(project_root: Path) -> Path:
    ledger_dir = Path(project_root) / ".umcp" / "ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    return ledger_dir / "runs.jsonl"


def append_run(project_root: Path, entry: dict[str, Any]) -> None:
    payload = dict(entry)
    payload.setdefault("timestamp", datetime.now(UTC).isoformat())
    with _ledger_path(project_root).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def read_runs(project_root: Path, limit: int | None = None) -> list[dict[str, Any]]:
    path = _ledger_path(project_root)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if limit is not None:
        lines = lines[-limit:]
    return [json.loads(line) for line in lines if line.strip()]
