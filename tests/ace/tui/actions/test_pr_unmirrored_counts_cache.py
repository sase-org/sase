"""Tests for the PR filter-outcome document cache used by the Patches pane."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sase.ace.tui.actions.patch import _loading as loading_module
from sase.external_mirror import state as state_module


@pytest.fixture(autouse=True)
def _reset_module_cache() -> Iterator[None]:
    loading_module._pr_unmirrored_cache_key = None
    loading_module._pr_unmirrored_cache_value = {}
    yield
    loading_module._pr_unmirrored_cache_key = None
    loading_module._pr_unmirrored_cache_value = {}


def _counting_reader(calls: list[int]):
    real_read = state_module.read_pr_unmirrored_counts

    def _read() -> dict[str, int]:
        calls.append(1)
        return real_read()

    return _read


def test_second_call_with_unchanged_document_does_not_reread(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    state_module.write_pr_unmirrored_count(
        "sase", fetched=5, unmirrored=2, now=datetime(2026, 8, 3, tzinfo=UTC)
    )
    calls: list[int] = []
    monkeypatch.setattr(
        state_module, "read_pr_unmirrored_counts", _counting_reader(calls)
    )

    first = loading_module._cached_pr_unmirrored_counts()
    second = loading_module._cached_pr_unmirrored_counts()

    assert first == {"sase": 2}
    assert second == first
    assert len(calls) == 1


def test_document_change_invalidates_the_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    state_module.write_pr_unmirrored_count(
        "sase", fetched=5, unmirrored=2, now=datetime(2026, 8, 3, tzinfo=UTC)
    )
    calls: list[int] = []
    monkeypatch.setattr(
        state_module, "read_pr_unmirrored_counts", _counting_reader(calls)
    )

    first = loading_module._cached_pr_unmirrored_counts()
    # A markedly different digit count guarantees the document's byte size
    # changes, so this assertion doesn't depend on filesystem mtime
    # resolution being fine enough to separate two fast successive writes.
    state_module.write_pr_unmirrored_count(
        "sase", fetched=500, unmirrored=12345, now=datetime(2026, 8, 3, 1, tzinfo=UTC)
    )
    second = loading_module._cached_pr_unmirrored_counts()

    assert first == {"sase": 2}
    assert second == {"sase": 12345}
    assert len(calls) == 2


def test_missing_document_returns_empty_and_resets_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    assert loading_module._cached_pr_unmirrored_counts() == {}
