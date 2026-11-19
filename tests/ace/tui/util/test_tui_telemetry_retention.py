"""Retention contract for TUI stall and heartbeat telemetry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.logs import tui_telemetry
from sase.logs._bounded import DEFAULT_MAX_BYTES


@pytest.fixture
def stall_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    monkeypatch.delenv(tui_telemetry.ENV_STALL_MAX_BYTES, raising=False)
    monkeypatch.delenv(tui_telemetry.ENV_MAX_BYTES, raising=False)
    return path


def _rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_stall_cap_holds_48h_and_exceeds_the_sibling_cap() -> None:
    # One segment alone must cover 48 h of athena's ~19.8 MiB of slimmed rows.
    assert tui_telemetry.STALL_MAX_BYTES == 24 * 1024 * 1024
    assert tui_telemetry.STALL_MAX_BYTES > 2 * DEFAULT_MAX_BYTES
    assert tui_telemetry._stall_max_bytes() == tui_telemetry.STALL_MAX_BYTES


def test_stall_log_size_rotates_to_one_prior_segment(
    stall_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(tui_telemetry.ENV_STALL_MAX_BYTES, "64")
    old_rows = [{"ts": 1.0, "event": "first"}, {"ts": 2.0, "event": "second"}]
    stall_path.write_text("".join(json.dumps(row) + "\n" for row in old_rows))

    tui_telemetry.log_tui_stall({"ts": 3.0, "event": "third", "pad": "x" * 20})

    rotated = stall_path.with_name("tui_stalls.jsonl.1")
    assert _rows(rotated) == old_rows
    assert [row["event"] for row in _rows(stall_path)] == ["third"]


def test_stall_log_keeps_old_rows_without_parsing_or_rewriting(
    stall_path: Path,
) -> None:
    # The removed hourly prune dropped rows older than 48 h and re-wrote the
    # file in place. Rotation is size-only: age never removes a row, and
    # existing bytes (even a torn line) stay byte-for-byte untouched.
    existing = (
        json.dumps({"ts": 0.0, "event": "ancient"}) + "\n" + '{"ts": 1.0, "event": "to'
    )
    stall_path.write_text(existing)

    tui_telemetry.log_tui_stall({"ts": 2.0, "event": "current"})

    text = stall_path.read_text()
    assert text.startswith(existing)
    assert text.endswith(json.dumps({"ts": 2.0, "event": "current"}) + "\n")
    assert not stall_path.with_name("tui_stalls.jsonl.1").exists()


def test_stall_cap_ignores_the_sibling_byte_override(
    stall_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(tui_telemetry.ENV_MAX_BYTES, "1")
    stall_path.write_text(json.dumps({"ts": 1.0, "event": "kept"}) + "\n")

    tui_telemetry.log_tui_stall({"ts": 2.0, "event": "current"})

    assert [row["event"] for row in _rows(stall_path)] == ["kept", "current"]
    assert not stall_path.with_name("tui_stalls.jsonl.1").exists()


def test_stall_cap_zero_disables_rotation(
    stall_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(tui_telemetry.ENV_STALL_MAX_BYTES, "0")
    stall_path.write_text(json.dumps({"ts": 1.0, "pad": "x" * 200}) + "\n")

    tui_telemetry.log_tui_stall({"ts": 2.0, "event": "current"})

    assert len(_rows(stall_path)) == 2
    assert not stall_path.with_name("tui_stalls.jsonl.1").exists()
