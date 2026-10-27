"""Unit tests for the Muse session-log commentary tail."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.llm_provider._muse_commentary_tail import (
    MUSE_COMMENTARY_TAIL_UNAVAILABLE,
    MuseCommentaryTail,
)

from ._muse_commentary_helpers import (
    commentary_record,
    install_sessions_root_log,
    marker_record,
    reasoning_record,
    retained_frame_line,
)

_SESSION_ID = "66b7ac36-396c-49f1-a3ef-58d4e1a43008"
_FOREIGN_ID = "00000000-0000-0000-0000-000000000000"


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _excerpt(session_id: str = _SESSION_ID) -> str:
    first = commentary_record(
        session_id=session_id,
        text="Approved — implementing your docs theme plan now.",
        message_id="msg-1",
        sequence=1,
    )
    second = commentary_record(
        session_id=session_id,
        text="Next I will run the tests.",
        message_id="msg-2",
        sequence=2,
    )
    unphased = commentary_record(
        session_id=session_id,
        text="Done. Phase complete.",
        message_id="msg-final",
        sequence=3,
        phase=None,
    )
    nested = commentary_record(
        session_id=session_id,
        text="Nested commentary from a retained frame.",
        message_id="msg-nested",
        sequence=4,
    )
    duplicate = commentary_record(
        session_id=session_id,
        text="Approved — implementing your docs theme plan now.",
        message_id="msg-1",
        sequence=5,
    )
    foreign = commentary_record(
        session_id=_FOREIGN_ID,
        text="From another session.",
        message_id="msg-foreign",
        sequence=6,
    )
    return "".join(
        [
            first,
            second,
            unphased,
            retained_frame_line(nested),
            marker_record(session_id=session_id),
            reasoning_record(session_id=session_id),
            duplicate,
            foreign,
        ]
    )


def _tail(
    tmp_path: Path,
    *,
    clock: _Clock | None = None,
    session_id: str = _SESSION_ID,
) -> tuple[MuseCommentaryTail, list[str]]:
    events: list[str] = []
    tail = MuseCommentaryTail(
        session_id,
        events.append,
        sessions_root=tmp_path,
        clock=clock if clock is not None else _Clock(),
    )
    return tail, events


def _diagnostics(artifacts: Path) -> list[dict[str, object]]:
    path = artifacts / "tool_calls_writer_errors.jsonl"
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_tail_emits_only_commentary_in_order_once_each(tmp_path: Path) -> None:
    install_sessions_root_log(tmp_path, _SESSION_ID, _excerpt())
    tail, events = _tail(tmp_path)

    tail.drain()

    assert events == [
        "Approved — implementing your docs theme plan now.",
        "Next I will run the tests.",
        "Nested commentary from a retained frame.",
    ]


def test_tail_accepts_commentary_without_a_message_id(tmp_path: Path) -> None:
    body = commentary_record(
        session_id=_SESSION_ID,
        text="No id, still commentary.",
        message_id=None,
    )
    install_sessions_root_log(tmp_path, _SESSION_ID, body)
    tail, events = _tail(tmp_path)

    tail.drain()

    assert events == ["No id, still commentary."]


def test_tail_picks_up_appends_between_ticks_without_a_rescan(
    tmp_path: Path,
) -> None:
    log_path = install_sessions_root_log(
        tmp_path,
        _SESSION_ID,
        commentary_record(
            session_id=_SESSION_ID, text="First.", message_id="msg-1", sequence=1
        ),
    )
    clock = _Clock()
    tail, events = _tail(tmp_path, clock=clock)

    tail.tick()
    assert events == ["First."]

    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(
            commentary_record(
                session_id=_SESSION_ID,
                text="Second.",
                message_id="msg-2",
                sequence=2,
            )
        )
        handle.flush()

    clock.advance(0.3)
    tail.tick()
    assert events == ["First.", "Second."]


def test_tail_finds_a_log_that_appears_after_several_ticks(tmp_path: Path) -> None:
    clock = _Clock()
    tail, events = _tail(tmp_path, clock=clock)

    tail.tick()
    clock.advance(0.3)
    tail.tick()
    assert events == []

    install_sessions_root_log(
        tmp_path,
        _SESSION_ID,
        commentary_record(session_id=_SESSION_ID, text="Late.", message_id="late"),
    )
    clock.advance(1.0)
    tail.tick()

    assert events == ["Late."]


def test_missing_log_records_one_diagnostic_from_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    clock = _Clock()
    tail, events = _tail(sessions, clock=clock)

    tail.tick()
    clock.advance(0.3)
    tail.tick()
    tail.finish()

    assert events == []
    diagnostics = [
        entry
        for entry in _diagnostics(artifacts)
        if entry["reason"] == MUSE_COMMENTARY_TAIL_UNAVAILABLE
    ]
    assert len(diagnostics) == 1
    assert diagnostics[0]["cause"] == "session_log_not_found"
    assert diagnostics[0]["session_id"] == _SESSION_ID


def test_read_error_records_one_diagnostic_and_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    session_dir = tmp_path.joinpath("2026", "10", "26", _SESSION_ID)
    session_dir.mkdir(parents=True)
    (session_dir / "session.jsonl").mkdir()
    tail, events = _tail(tmp_path)

    tail.tick()
    tail.finish()

    assert events == []
    diagnostics = _diagnostics(artifacts)
    assert len(diagnostics) == 1
    assert diagnostics[0]["reason"] == MUSE_COMMENTARY_TAIL_UNAVAILABLE
    assert diagnostics[0]["cause"] == "read_error"


def test_malformed_line_records_one_diagnostic_and_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    body = (
        '{"assistant_message_committed":true,"commentary":true,\n'
        + commentary_record(
            session_id=_SESSION_ID, text="After the junk.", message_id="ok"
        )
    )
    install_sessions_root_log(tmp_path, _SESSION_ID, body)
    tail, events = _tail(tmp_path)

    tail.drain()
    tail.finish()

    assert events == ["After the junk."]
    diagnostics = _diagnostics(artifacts)
    assert len(diagnostics) == 1
    assert diagnostics[0]["cause"] == "malformed_record"


def test_unexpected_error_records_one_diagnostic_and_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    install_sessions_root_log(
        tmp_path,
        _SESSION_ID,
        commentary_record(session_id=_SESSION_ID, text="Boom.", message_id="boom"),
    )

    def boom(_text: str) -> None:
        raise RuntimeError("callback failed")

    tail = MuseCommentaryTail(_SESSION_ID, boom, sessions_root=tmp_path, clock=_Clock())
    tail.drain()
    tail.finish()

    diagnostics = _diagnostics(artifacts)
    assert len(diagnostics) == 1
    assert diagnostics[0]["cause"] == "unexpected_error"


def test_partial_last_line_completes_on_a_later_append(tmp_path: Path) -> None:
    first = commentary_record(
        session_id=_SESSION_ID, text="Complete first.", message_id="msg-1", sequence=1
    )
    second = commentary_record(
        session_id=_SESSION_ID, text="Completed later.", message_id="msg-2", sequence=2
    )
    split_at = len(second) // 2
    log_path = install_sessions_root_log(
        tmp_path, _SESSION_ID, first + second[:split_at]
    )
    clock = _Clock()
    tail, events = _tail(tmp_path, clock=clock)

    tail.tick()
    assert events == ["Complete first."]

    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(second[split_at:])
        handle.flush()
    clock.advance(0.3)
    tail.tick()

    assert events == ["Complete first.", "Completed later."]


def test_bounded_reads_still_reach_commentary_across_ticks(tmp_path: Path) -> None:
    padding = ("x" * (1024 * 1024 + 50_000)) + "\n"
    commentary = commentary_record(
        session_id=_SESSION_ID,
        text="Behind the tool output.",
        message_id="behind",
    )
    install_sessions_root_log(tmp_path, _SESSION_ID, padding + commentary)
    clock = _Clock()
    tail, events = _tail(tmp_path, clock=clock)

    tail.tick()
    assert events == []

    clock.advance(0.3)
    tail.tick()
    assert events == ["Behind the tool output."]
