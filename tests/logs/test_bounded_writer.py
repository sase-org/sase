"""Regression coverage for the shared bounded durable-log writer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.logs import _bounded


def test_rotation_replaces_only_single_backup_and_keeps_current_record(
    tmp_path: Path,
) -> None:
    path = tmp_path / "records.jsonl"
    rotated = tmp_path / "records.jsonl.1"
    path.write_text('{"old":"current"}\n', encoding="utf-8")
    rotated.write_text('{"old":"backup"}\n', encoding="utf-8")

    _bounded.append_jsonl_record(path, {"new": "record"}, max_bytes=20)

    assert rotated.read_text(encoding="utf-8") == '{"old":"current"}\n'
    assert json.loads(path.read_text(encoding="utf-8")) == {"new": "record"}
    assert not (tmp_path / "records.jsonl.2").exists()


def test_short_write_is_not_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def short_write(fd: int, data: bytes) -> int:
        del fd
        nonlocal calls
        calls += 1
        return len(data) - 1

    monkeypatch.setattr(_bounded.os, "write", short_write)

    with pytest.raises(OSError, match="short durable-log write"):
        _bounded.append_jsonl_record(tmp_path / "records.jsonl", {"record": 1})

    assert calls == 1
