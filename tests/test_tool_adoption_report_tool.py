from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.contract

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


def _now(offset: timedelta = timedelta()) -> str:
    return (datetime.now(UTC) - offset).isoformat()


def _call(
    ident: str,
    command: object,
    seconds: int,
    at: str | None = None,
    response: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    stamped = at or _now()
    return [
        {
            "event": "ToolUse",
            "tool_name": "Bash",
            "tool_use_id": ident,
            "recorded_at": stamped,
            "tool_input_summary": {"command": command},
        },
        {
            "event": "ToolResult",
            "tool_use_id": ident,
            "recorded_at": stamped,
            "duration_ms": seconds * 1000,
            "tool_response_summary": response or {},
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
        ("SASE_TOOL_BYPASS='stale install' just check", "bypassed"),
        ("SASE_TOOL_BYPASS=x just check-full", "bypassed"),
        ("SASE_TOOL_BYPASS=x just check 2>&1 | tail -20", "bypassed"),
        ("bash -lc 'SASE_TOOL_BYPASS=x just check'", "bypassed"),
        ("SASE_TOOL_BYPASS=x sase tool run check", "wrapped"),
        ("SASE_TOOL_BYPASS= just check", "other"),
        ("FOO=1 just check", "other"),
        ("SASE_TOOL_BYPASS=x just check && echo done", "ambiguous"),
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
    assert report["counts"] == {
        "wrapped": 1,
        "raw": 1,
        "bypassed": 0,
        "ambiguous": 1,
    }
    assert report["wall_share_wrapped"] == pytest.approx(0.25)
    assert report["exclusions"]["light_excluded"] == 1


def test_zero_denominator_is_none(tmp_path: Path) -> None:
    report = _load().build_report(tmp_path, 7)
    assert report["wall_share_wrapped"] is None
    assert report["count_share_wrapped"] is None


_REFUSAL_RESPONSE = {
    "exit_code": 2,
    "stderr_preview": (
        "sase: refusing raw `just check` in an agent shell.\n"
        "sase: run `sase tool run check` instead.\n"
        "sase: or run `SASE_TOOL_BYPASS='<reason>' just check` to bypass."
    ),
}


def test_refusal_followed_by_wrapped_call_counts(tmp_path: Path) -> None:
    mod = _load()
    _write(
        tmp_path / "p" / "artifacts" / "a" / "tool_calls.jsonl",
        _call("r1", "just check", 1, response=_REFUSAL_RESPONSE)
        + _call("w1", "sase tool run check", 60),
    )
    report = mod.build_report(tmp_path, 7)
    assert report["refusals"] == 1
    # The millisecond refusal is not a heavy call; only the wrapped run is.
    assert report["counts"]["wrapped"] == 1
    assert report["counts"]["raw"] == 0


def test_refusal_without_followup_wrapped_call_does_not_count(
    tmp_path: Path,
) -> None:
    mod = _load()
    _write(
        tmp_path / "p" / "artifacts" / "a" / "tool_calls.jsonl",
        _call("r1", "just check", 1, response=_REFUSAL_RESPONSE),
    )
    assert mod.build_report(tmp_path, 7)["refusals"] == 0


def test_non_guard_exit_2_is_not_a_refusal(tmp_path: Path) -> None:
    mod = _load()
    _write(
        tmp_path / "p" / "artifacts" / "a" / "tool_calls.jsonl",
        _call("r1", "just check", 60, response={"exit_code": 1})
        + _call("w1", "sase tool run check", 60),
    )
    assert mod.build_report(tmp_path, 7)["refusals"] == 0


def test_bypassed_heavy_calls_are_reported(tmp_path: Path) -> None:
    mod = _load()
    _write(
        tmp_path / "p" / "artifacts" / "a" / "tool_calls.jsonl",
        _call("b1", "SASE_TOOL_BYPASS='stale install' just check", 60),
    )
    report = mod.build_report(tmp_path, 7)
    assert report["counts"]["bypassed"] == 1
    # Bypassed calls stay out of the wrapped share denominator.
    assert report["count_share_wrapped"] is None


def test_window_filters_by_each_call_timestamp_not_file_mtime(
    tmp_path: Path,
) -> None:
    mod = _load()
    old = _now(timedelta(days=30))
    _write(
        tmp_path / "p" / "artifacts" / "a" / "tool_calls.jsonl",
        _call("t1", "just check", 60, at=old) + _call("t2", "sase tool run check", 60),
    )
    report = mod.build_report(tmp_path, 7)
    assert report["files_read"] == 1
    assert report["counts"] == {
        "wrapped": 1,
        "raw": 0,
        "bypassed": 0,
        "ambiguous": 0,
    }
    assert report["exclusions"]["outside_window"] == 1


def test_undated_calls_are_counted_not_guessed(tmp_path: Path) -> None:
    mod = _load()
    _write(
        tmp_path / "p" / "artifacts" / "a" / "tool_calls.jsonl",
        [
            {
                "event": "ToolUse",
                "tool_name": "Bash",
                "tool_use_id": "u1",
                "tool_input_summary": {"command": "just check"},
            },
            {
                "event": "ToolResult",
                "tool_use_id": "u1",
                "recorded_at": _now(),
                "duration_ms": 60_000,
                "tool_response_summary": {},
            },
        ],
    )
    report = mod.build_report(tmp_path, 7)
    assert report["counts"]["raw"] == 0
    assert report["exclusions"]["undated"] == 1
