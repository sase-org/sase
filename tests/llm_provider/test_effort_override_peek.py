"""Read-only display-path tests for the default-effort override peek."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.llm_provider import effort_override as effort_state
from sase.llm_provider import effort_override_peek as effort_peek
from sase.llm_provider.effort_override import TemporaryEffortOverride


@pytest.fixture(autouse=True)
def reset_peek_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "llm_effort_override.json"
    monkeypatch.setattr(effort_state, "sase_home", lambda: tmp_path)
    monkeypatch.setattr(effort_peek, "_peek_cache_path", None)
    monkeypatch.setattr(effort_peek, "_peek_cache_token", None)
    monkeypatch.setattr(effort_peek, "_peek_cache_record", None)
    monkeypatch.setattr(effort_peek, "_peek_cache_deadline", 0.0)
    return path


def test_peek_missing_or_corrupt_state_is_empty_and_non_mutating(
    reset_peek_cache: Path,
) -> None:
    path = reset_peek_cache

    assert effort_peek.peek_active_effort_override(now=100.0) is None
    assert not path.exists()

    path.write_bytes(b"{broken")
    before = path.read_bytes()
    effort_peek._peek_cache_deadline = 0.0

    assert effort_peek.peek_active_effort_override(now=100.0) is None
    assert path.read_bytes() == before


def test_peek_filters_expiry_without_rewriting(reset_peek_cache: Path) -> None:
    path = reset_peek_cache
    payload = {
        "version": 1,
        "effort": "high",
        "created_at": 1.0,
        "expires_at": 101.0,
        "source": "test",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_bytes()

    active = effort_peek.peek_active_effort_override(now=100.0)
    assert active == TemporaryEffortOverride.from_wire(payload)

    effort_peek._peek_cache_deadline = 0.0
    assert effort_peek.peek_active_effort_override(now=101.0) is None
    assert path.read_bytes() == before


def test_peek_never_takes_effort_override_lock_or_deletes_file(
    reset_peek_cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = reset_peek_cache
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "effort": "medium",
                "created_at": 1.0,
                "expires_at": None,
                "source": "test",
            }
        ),
        encoding="utf-8",
    )

    def fail(_name: str):
        def inner(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("peek must not take the effort-override lock")

        return inner

    monkeypatch.setattr(effort_state, "require_rust_binding", fail)

    record = effort_peek.peek_active_effort_override(now=100.0)

    assert record is not None
    assert record.effort == "medium"
    assert path.exists()
