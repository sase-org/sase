"""Read-only display-path tests for temporary provider priority."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.llm_provider import provider_priority as priority
from sase.llm_provider import provider_priority_peek as priority_peek
from sase.llm_provider.provider_priority import PROVIDER_PRIORITY_WIRE_SCHEMA_VERSION


@pytest.fixture(autouse=True)
def reset_priority_peek_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "llm_provider_priority.json"
    monkeypatch.setattr(priority, "sase_home", lambda: tmp_path)
    monkeypatch.setattr(priority_peek, "_peek_cache_path", None)
    monkeypatch.setattr(priority_peek, "_peek_cache_token", None)
    monkeypatch.setattr(
        priority_peek,
        "_peek_cache_decode",
        priority.ProviderPriorityDecode(version=1, priority=None, diagnostics=()),
    )
    monkeypatch.setattr(priority_peek, "_peek_cache_deadline", 0.0)
    return path


def test_priority_peek_missing_or_corrupt_state_is_empty_and_non_mutating(
    reset_priority_peek_cache: Path,
) -> None:
    path = reset_priority_peek_cache

    assert priority_peek.peek_active_provider_priority(now=100.0) is None
    assert not path.exists()

    path.write_bytes(b"{broken")
    before = path.read_bytes()
    priority_peek._peek_cache_deadline = 0.0

    assert priority_peek.peek_active_provider_priority(now=100.0) is None
    assert path.read_bytes() == before


def test_priority_peek_filters_expiry_without_rewriting(
    reset_priority_peek_cache: Path,
) -> None:
    path = reset_priority_peek_cache
    _write_state(path, provider="codex", expires_at=101.0)
    before = path.read_bytes()

    result = priority_peek.peek_active_provider_priority(now=100.0)

    assert result is not None
    assert result.provider == "codex"
    assert path.read_bytes() == before

    # Expiry filtering runs on every call even while the parsed-file memo is hot.
    assert priority_peek.peek_active_provider_priority(now=101.0) is None
    assert path.read_bytes() == before


def test_priority_peek_reloads_after_file_metadata_changes(
    reset_priority_peek_cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = reset_priority_peek_cache
    monotonic = iter((1.0, 2.0))
    monkeypatch.setattr(priority_peek.time, "monotonic", lambda: next(monotonic))
    _write_state(path, provider="claude", expires_at=None)

    first = priority_peek.peek_active_provider_priority(now=100.0)
    first_stat = path.stat()
    _write_state(path, provider="codex", expires_at=None)
    os.utime(
        path,
        ns=(first_stat.st_atime_ns, first_stat.st_mtime_ns + 1_000_000),
    )
    second = priority_peek.peek_active_provider_priority(now=100.0)

    assert first is not None
    assert second is not None
    assert first.provider == "claude"
    assert second.provider == "codex"


def test_priority_change_token_changes_after_expiry_without_rewrite(
    reset_priority_peek_cache: Path,
) -> None:
    path = reset_priority_peek_cache
    _write_state(path, provider="codex", expires_at=101.0)
    before = path.read_bytes()

    active = priority_peek.peek_provider_priority_change_token(now=100.0)
    expired = priority_peek.peek_provider_priority_change_token(now=101.0)

    assert active != expired
    assert active[1] is not None
    assert expired[1] is None
    assert path.read_bytes() == before


def _write_state(path: Path, *, provider: str, expires_at: float | None) -> None:
    path.write_text(
        json.dumps(
            {
                "version": PROVIDER_PRIORITY_WIRE_SCHEMA_VERSION,
                "provider": provider,
                "created_at": 1.0,
                "expires_at": expires_at,
                "source": "test",
            }
        ),
        encoding="utf-8",
    )
