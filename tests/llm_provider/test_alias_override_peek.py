"""Read-only display-path tests for temporary model-alias overrides."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.llm_provider import temporary_override_peek as override_store
from sase.llm_provider import temporary_override_state as override_state


@pytest.fixture(autouse=True)
def reset_peek_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "llm_override.json"
    monkeypatch.setattr(override_state, "sase_home", lambda: tmp_path)
    monkeypatch.setattr(override_store, "_peek_cache_path", None)
    monkeypatch.setattr(override_store, "_peek_cache_token", None)
    monkeypatch.setattr(override_store, "_peek_cache_entries", {})
    monkeypatch.setattr(override_store, "_peek_cache_deadline", 0.0)
    return path


def test_peek_missing_or_corrupt_state_is_empty_and_non_mutating(
    reset_peek_cache: Path,
) -> None:
    path = reset_peek_cache

    assert override_store.peek_active_alias_overrides(now=100.0) == {}
    assert not path.exists()

    path.write_bytes(b"{broken")
    before = path.read_bytes()
    override_store._peek_cache_deadline = 0.0

    assert override_store.peek_active_alias_overrides(now=100.0) == {}
    assert path.read_bytes() == before


def test_peek_filters_expired_entries_without_rewriting(
    reset_peek_cache: Path,
) -> None:
    path = reset_peek_cache
    _write_state(
        path,
        {
            "expired": _entry(provider="claude", model="opus", expires_at=99.0),
            "active": _entry(provider="codex", model="o3", expires_at=101.0),
        },
    )
    before = path.read_bytes()

    result = override_store.peek_active_alias_overrides(now=100.0)

    assert set(result) == {"active"}
    assert result["active"].model == "o3"
    assert path.read_bytes() == before

    # Expiry filtering runs on every call even while the parsed-file memo is hot.
    assert override_store.peek_active_alias_overrides(now=101.0) == {}
    assert path.read_bytes() == before


def test_peek_reloads_after_file_metadata_changes(
    reset_peek_cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = reset_peek_cache
    monotonic = iter((1.0, 2.0))
    monkeypatch.setattr(override_store.time, "monotonic", lambda: next(monotonic))
    _write_state(
        path,
        {"coder": _entry(provider="claude", model="opus", expires_at=None)},
    )

    first = override_store.peek_active_alias_overrides(now=100.0)
    first_stat = path.stat()
    _write_state(
        path,
        {"coder": _entry(provider="codex", model="gpt5", expires_at=None)},
    )
    os.utime(
        path,
        ns=(first_stat.st_atime_ns, first_stat.st_mtime_ns + 1_000_000),
    )
    second = override_store.peek_active_alias_overrides(now=100.0)

    assert (first["coder"].provider, first["coder"].model) == ("claude", "opus")
    assert (second["coder"].provider, second["coder"].model) == ("codex", "gpt5")


def test_peek_stats_at_most_once_within_floor(
    reset_peek_cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = reset_peek_cache
    _write_state(
        path,
        {"coder": _entry(provider="claude", model="opus", expires_at=None)},
    )
    stat_calls = 0
    original_stat = Path.stat

    def counting_stat(
        candidate: Path, *args: object, **kwargs: object
    ) -> os.stat_result:
        nonlocal stat_calls
        if candidate == path:
            stat_calls += 1
        return original_stat(candidate, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "stat", counting_stat)
    monkeypatch.setattr(override_store.time, "monotonic", lambda: 1.0)

    override_store.peek_active_alias_overrides(now=100.0)
    override_store.peek_active_alias_overrides(now=100.0)

    assert stat_calls == 1


def _write_state(path: Path, overrides: dict[str, dict[str, object]]) -> None:
    path.write_text(
        json.dumps({"version": 2, "overrides": overrides}),
        encoding="utf-8",
    )


def _entry(
    *,
    provider: str,
    model: str,
    expires_at: float | None,
) -> dict[str, object]:
    return {
        "provider": provider,
        "model": model,
        "raw_model": f"{provider}/{model}",
        "created_at": 1.0,
        "expires_at": expires_at,
        "source": "test",
        "effort": None,
    }
