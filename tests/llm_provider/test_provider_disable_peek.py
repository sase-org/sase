"""Read-only display-path tests for temporary provider disables."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.llm_provider import provider_disable_peek as disable_peek
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_HARD,
    PROVIDER_DISABLE_MODE_SOFT,
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
)


@pytest.fixture(autouse=True)
def reset_peek_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "llm_provider_disables.json"
    monkeypatch.setattr(disable_peek, "sase_home", lambda: tmp_path)
    monkeypatch.setattr(disable_peek, "_peek_cache_path", None)
    monkeypatch.setattr(disable_peek, "_peek_cache_token", None)
    monkeypatch.setattr(disable_peek, "_peek_cache_entries", {})
    monkeypatch.setattr(disable_peek, "_peek_cache_deadline", 0.0)
    return path


def test_peek_missing_or_corrupt_state_is_empty_and_non_mutating(
    reset_peek_cache: Path,
) -> None:
    path = reset_peek_cache

    assert disable_peek.peek_active_provider_disables(now=100.0) == {}
    assert not path.exists()

    path.write_bytes(b"{broken")
    before = path.read_bytes()
    disable_peek._peek_cache_deadline = 0.0

    assert disable_peek.peek_active_provider_disables(now=100.0) == {}
    assert path.read_bytes() == before


def test_peek_filters_expired_entries_without_rewriting(
    reset_peek_cache: Path,
) -> None:
    path = reset_peek_cache
    _write_state(
        path,
        {
            "expired": _entry(provider="expired", expires_at=99.0),
            "active": _entry(provider="active", expires_at=101.0),
        },
    )
    before = path.read_bytes()

    result = disable_peek.peek_active_provider_disables(now=100.0)

    assert list(result) == ["active"]
    assert path.read_bytes() == before

    # Expiry filtering runs on every call even while the parsed-file memo is hot.
    assert disable_peek.peek_active_provider_disables(now=101.0) == {}
    assert path.read_bytes() == before


def test_peek_reloads_after_file_metadata_changes(
    reset_peek_cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = reset_peek_cache
    monotonic = iter((1.0, 2.0))
    monkeypatch.setattr(disable_peek.time, "monotonic", lambda: next(monotonic))
    _write_state(
        path,
        {"claude": _entry(provider="claude", expires_at=None)},
    )

    first = disable_peek.peek_active_provider_disables(now=100.0)
    first_stat = path.stat()
    _write_state(
        path,
        {"codex": _entry(provider="codex", expires_at=None)},
    )
    os.utime(
        path,
        ns=(first_stat.st_atime_ns, first_stat.st_mtime_ns + 1_000_000),
    )
    second = disable_peek.peek_active_provider_disables(now=100.0)

    assert list(first) == ["claude"]
    assert list(second) == ["codex"]


def test_peek_stats_at_most_once_within_floor(
    reset_peek_cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = reset_peek_cache
    _write_state(
        path,
        {"claude": _entry(provider="claude", expires_at=None)},
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
    monkeypatch.setattr(disable_peek.time, "monotonic", lambda: 1.0)

    disable_peek.peek_active_provider_disables(now=100.0)
    disable_peek.peek_active_provider_disables(now=100.0)

    assert stat_calls == 1


def test_peek_invalid_entry_and_read_only_expiry_do_not_mutate(
    reset_peek_cache: Path,
) -> None:
    path = reset_peek_cache
    _write_state(path, {"claude": {"provider": "claude"}})
    before = path.read_bytes()
    assert disable_peek.peek_active_provider_disables(now=100.0) == {}
    assert path.read_bytes() == before

    _write_state(path, {"claude": _entry(provider="claude", expires_at=99.0)})
    path.chmod(0o444)
    try:
        before = path.read_bytes()
        disable_peek._peek_cache_deadline = 0.0
        assert disable_peek.peek_active_provider_disables(now=100.0) == {}
        assert path.read_bytes() == before
    finally:
        path.chmod(0o644)


def test_peek_v1_file_reads_as_hard_and_is_not_rewritten(
    reset_peek_cache: Path,
) -> None:
    path = reset_peek_cache
    _write_state(
        path,
        {"claude": _entry(provider="claude", expires_at=None)},
        version=1,
    )
    before = path.read_bytes()

    result = disable_peek.peek_active_provider_disables(now=100.0)

    assert list(result) == ["claude"]
    assert result["claude"].is_hard
    assert result["claude"].mode == PROVIDER_DISABLE_MODE_HARD
    assert path.read_bytes() == before


def test_peek_v2_file_preserves_soft_mode(reset_peek_cache: Path) -> None:
    path = reset_peek_cache
    _write_state(
        path,
        {
            "codex": _entry(
                provider="codex",
                expires_at=None,
                version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
                mode=PROVIDER_DISABLE_MODE_SOFT,
            )
        },
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    )
    before = path.read_bytes()

    result = disable_peek.peek_active_provider_disables(now=100.0)

    assert list(result) == ["codex"]
    assert result["codex"].is_soft
    assert path.read_bytes() == before


def _write_state(
    path: Path,
    disables: dict[str, dict[str, object]],
    *,
    version: int = 1,
) -> None:
    path.write_text(
        json.dumps({"version": version, "disables": disables}),
        encoding="utf-8",
    )


def _entry(
    *,
    provider: str,
    expires_at: float | None,
    version: int = 1,
    mode: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": version,
        "provider": provider,
        "created_at": 1.0,
        "expires_at": expires_at,
        "source": "test",
    }
    if mode is not None:
        payload["mode"] = mode
    return payload
