from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable


NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")


def coerce_cli_value(raw: str) -> Any:
    lowered = raw.lower()
    if lowered in {"true", "false", "null"}:
        return json.loads(lowered)
    if raw.startswith("{") or raw.startswith("[") or raw.startswith('"'):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    if NUMBER_RE.match(raw):
        return float(raw) if "." in raw else int(raw)
    return raw


def load_json_params(
    params_text: str | None = None,
    params_file: str | Path | None = None,
    param_pairs: Iterable[str] = (),
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if params_text:
        parsed = json.loads(params_text)
        if not isinstance(parsed, dict):
            raise ValueError("Inline params must decode to a JSON object.")
        payload.update(parsed)
    if params_file:
        parsed = json.loads(Path(params_file).read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("Params file must decode to a JSON object.")
        payload.update(parsed)
    for pair in param_pairs:
        if "=" not in pair:
            raise ValueError(f"Expected key=value for --param, got: {pair}")
        key, raw_value = pair.split("=", 1)
        payload[key] = coerce_cli_value(raw_value)
    return payload


def load_text_value(
    content: str | None = None,
    file_path: str | Path | None = None,
    required: bool = True,
) -> str | None:
    if content is not None and file_path is not None:
        raise ValueError("Use either inline content or a file path, not both.")
    if file_path is not None:
        return Path(file_path).read_text(encoding="utf-8")
    if content is not None:
        return content
    if required:
        raise ValueError("Content is required.")
    return None


def format_output(value: Any, json_output: bool) -> str:
    if isinstance(value, str):
        return value
    if json_output:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=True)
    return json.dumps(value, indent=2, ensure_ascii=True)
