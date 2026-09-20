from __future__ import annotations

import importlib.util
import json
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    script = ROOT / "tools" / "tool_adoption_report"
    loader = SourceFileLoader("tool_adoption_report_tool", str(script))
    spec = importlib.util.spec_from_file_location(
        "tool_adoption_report_tool", script, loader=loader
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _call(ident: str, command: object, seconds: int) -> list[dict[str, object]]:
    return [
        {
            "event": "ToolUse",
            "tool_name": "Bash",
            "tool_use_id": ident,
            "recorded_at": "2026-09-19T10:00:00+00:00",
            "tool_input_summary": {"command": command},
        },
        {
            "event": "ToolResult",
            "tool_use_id": ident,
            "recorded_at": "2026-09-19T10:00:00+00:00",
            "duration_ms": seconds * 1000,
            "tool_response_summary": {},
        },
    ]


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("just check", "raw"),
        ("just check 2>&1 | tail -150", "raw"),
        ("sase tool run check-full", "wrapped"),
        ("sase tool run -q -T 5 check", "wrapped"),
        (["/usr/bin/zsh", "-lc", "just check"], "raw"),
        ("bash -lc 'sase tool run check'", "wrapped"),
        ("just check && echo done", "ambiguous"),
        ("just check | grep FAIL", "ambiguous"),
        ("just lint", "other"),
    ],
)
def test_classify(command: object, expected: str) -> None:
    assert _load().classify({"command": command}) == expected


def test_report_pairs_per_file_and_computes_shares(tmp_path: Path) -> None:
    mod = _load()
    _write(
        tmp_path / "p" / "artifacts" / "a" / "tool_calls.jsonl",
        _call("t1", "just check", 60) + _call("t2", "sase tool run check", 20),
    )
    # Reused id in another file must not pair with the first file's rows.
    _write(
        tmp_path / "p" / "artifacts" / "b" / "tool_calls.jsonl",
        _call("t1", "just check", 5) + _call("t9", "just check; true", 90),
    )
    report = mod.build_report(tmp_path, 7)
    assert report["counts"] == {"wrapped": 1, "raw": 1, "ambiguous": 1}
    assert report["wall_share_wrapped"] == pytest.approx(0.25)
    assert report["exclusions"]["light_excluded"] == 1


def test_zero_denominator_is_none(tmp_path: Path) -> None:
    report = _load().build_report(tmp_path, 7)
    assert report["wall_share_wrapped"] is None
    assert report["count_share_wrapped"] is None
