from __future__ import annotations

from pathlib import Path

from cli_anything.unity_mcp.core.learning.ledger import append_run, read_runs


def test_append_run_and_read_runs_roundtrip(tmp_path: Path) -> None:
    append_run(tmp_path, {"skill": "physics_feel", "chosen_action": "physics_feel/snappy"})
    append_run(tmp_path, {"skill": "physics_feel", "chosen_action": "physics_feel/controlled"})

    runs = read_runs(tmp_path)

    assert len(runs) == 2
    assert runs[0]["skill"] == "physics_feel"
    assert runs[1]["chosen_action"] == "physics_feel/controlled"
    assert "timestamp" in runs[0]


def test_read_runs_respects_limit(tmp_path: Path) -> None:
    append_run(tmp_path, {"index": 1})
    append_run(tmp_path, {"index": 2})
    append_run(tmp_path, {"index": 3})

    runs = read_runs(tmp_path, limit=2)

    assert [entry["index"] for entry in runs] == [2, 3]


def test_read_runs_returns_empty_when_file_missing(tmp_path: Path) -> None:
    assert read_runs(tmp_path) == []
