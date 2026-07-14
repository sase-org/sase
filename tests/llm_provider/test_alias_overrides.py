"""Tests for the per-alias temporary override state (epic sase-5e phase 1).

These cover the v2 keyed schema, the v1→v2 read migration, multi-alias
set/clear, and per-entry expiry pruning with empty-file cleanup. The
``default``-keyed back-compat wrappers are exercised by
``test_temporary_override.py``.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time

import pytest

from sase.llm_provider.temporary_override import (
    _state_path,
    clear_alias_override,
    get_active_alias_override,
    get_active_alias_overrides,
    get_active_temporary_override,
    set_alias_override,
    set_alias_override_until,
)


def _read_state() -> dict:
    return json.loads(_state_path().read_text(encoding="utf-8"))


def _write_state(data: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Basic per-alias set / get
# ---------------------------------------------------------------------------


def test_get_unknown_alias_returns_none() -> None:
    assert get_active_alias_override("coder") is None
    assert get_active_alias_overrides() == {}


def test_set_then_get_alias_override() -> None:
    override = set_alias_override("coder", "codex/o3", 3600.0, source="panel")

    assert override.provider == "codex"
    assert override.model == "o3"
    assert override.raw_model == "codex/o3"
    assert override.source == "panel"

    fetched = get_active_alias_override("coder")
    assert fetched is not None
    assert fetched.provider == "codex"
    assert fetched.model == "o3"


def test_set_until_cleared_has_no_expiry() -> None:
    override = set_alias_override("coder", "opus", None, source="panel")
    assert override.expires_at is None

    far_future = time.time() + 10 * 365 * 24 * 3600
    fetched = get_active_alias_override("coder", now=far_future)
    assert fetched is not None
    assert fetched.model == "opus"


def test_set_until_stores_exact_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "time", lambda: 1000.0)

    override = set_alias_override_until("coder", "codex/o3", 4321.25, source="panel")

    assert override.created_at == 1000.0
    assert override.expires_at == 4321.25
    assert _read_state()["overrides"]["coder"]["expires_at"] == 4321.25


def test_set_until_preserves_other_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    set_alias_override("phase_worker", "claude/opus", None, source="panel")

    set_alias_override_until("coder", "codex/o3", 2000.0, source="panel")

    data = _read_state()
    assert data["version"] == 2
    assert set(data) == {"version", "overrides"}
    assert set(data["overrides"]) == {"coder", "phase_worker"}


@pytest.mark.parametrize("expires_at", [float("nan"), float("inf"), float("-inf")])
def test_set_until_rejects_non_finite_expiry(expires_at: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        set_alias_override_until("coder", "codex/o3", expires_at, source="panel")


def test_set_until_rejects_expiry_at_or_before_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(time, "time", lambda: 1000.0)

    with pytest.raises(ValueError, match="future"):
        set_alias_override_until("coder", "codex/o3", 1000.0, source="panel")


def test_set_until_uses_existing_expiry_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    override = set_alias_override_until("coder", "codex/o3", 2000.0, source="panel")

    assert get_active_alias_override("coder", now=1999.999) == override
    assert get_active_alias_override("coder", now=2000.0) is None


def test_overwriting_same_alias_replaces_target() -> None:
    set_alias_override("coder", "opus", None, source="panel")
    set_alias_override("coder", "codex/o3", None, source="panel")

    fetched = get_active_alias_override("coder")
    assert fetched is not None
    assert fetched.provider == "codex"
    assert fetched.model == "o3"


# ---------------------------------------------------------------------------
# Multiple independent aliases
# ---------------------------------------------------------------------------


def test_overrides_on_multiple_aliases_are_independent() -> None:
    set_alias_override("coder", "codex/o3", None, source="panel")
    set_alias_override("phase_worker", "claude/opus", None, source="panel")

    active = get_active_alias_overrides()
    assert set(active) == {"coder", "phase_worker"}
    assert active["coder"].model == "o3"
    assert active["phase_worker"].model == "opus"


def test_setting_one_alias_preserves_others() -> None:
    set_alias_override("coder", "codex/o3", None, source="panel")
    set_alias_override("phase_worker", "claude/opus", None, source="panel")

    # A third set must not drop the first two.
    set_alias_override("epic_lander", "codex/o3", None, source="panel")

    assert set(get_active_alias_overrides()) == {
        "coder",
        "phase_worker",
        "epic_lander",
    }


def test_concurrent_alias_writers_preserve_every_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The process-shared state serializes the full read/modify/write cycle."""
    import sase.llm_provider.temporary_override as override_store

    writer_count = 8
    first_write_barrier = threading.Barrier(writer_count)
    real_atomic_write = override_store._atomic_write_json

    def synchronized_first_write(path: object, data: dict) -> None:
        try:
            first_write_barrier.wait(timeout=0.2)
        except threading.BrokenBarrierError:
            pass
        real_atomic_write(path, data)  # type: ignore[arg-type]

    monkeypatch.setattr(override_store, "_atomic_write_json", synchronized_first_write)

    aliases = [f"alias_{index}" for index in range(writer_count)]
    with ThreadPoolExecutor(max_workers=writer_count) as executor:
        list(
            executor.map(
                lambda alias: set_alias_override(
                    alias, "codex/o3", None, source="concurrent-test"
                ),
                aliases,
            )
        )

    assert set(get_active_alias_overrides()) == set(aliases)


def test_alias_and_default_overrides_coexist() -> None:
    set_alias_override("default", "claude/opus", None, source="panel")
    set_alias_override("coder", "codex/o3", None, source="panel")

    # The default back-compat reader sees only the default entry.
    default_override = get_active_temporary_override()
    assert default_override is not None
    assert default_override.model == "opus"

    # The alias map sees both.
    assert set(get_active_alias_overrides()) == {"default", "coder"}


# ---------------------------------------------------------------------------
# Clearing
# ---------------------------------------------------------------------------


def test_clear_one_alias_keeps_others() -> None:
    set_alias_override("coder", "codex/o3", None, source="panel")
    set_alias_override("phase_worker", "claude/opus", None, source="panel")

    assert clear_alias_override("coder") is True

    active = get_active_alias_overrides()
    assert set(active) == {"phase_worker"}
    assert _state_path().exists()


def test_clear_last_alias_deletes_file() -> None:
    set_alias_override("coder", "codex/o3", None, source="panel")
    assert clear_alias_override("coder") is True
    assert get_active_alias_overrides() == {}
    assert not _state_path().exists()


def test_clear_unknown_alias_returns_false() -> None:
    set_alias_override("coder", "codex/o3", None, source="panel")
    assert clear_alias_override("phase_worker") is False
    # The untouched override is still present.
    assert get_active_alias_override("coder") is not None


def test_clear_when_no_state_returns_false() -> None:
    assert clear_alias_override("coder") is False


@pytest.mark.parametrize("alias", ["", "   "])
def test_clear_empty_alias_returns_false(alias: str) -> None:
    set_alias_override("coder", "codex/o3", None, source="panel")
    assert clear_alias_override(alias) is False


def test_clear_present_but_expired_alias_returns_true() -> None:
    """Clearing an entry that exists on disk (even if expired) still reports True."""
    set_alias_override("coder", "codex/o3", 60.0, source="panel")
    data = _read_state()
    data["overrides"]["coder"]["expires_at"] = time.time() - 1
    _write_state(data)

    assert clear_alias_override("coder") is True
    assert not _state_path().exists()


# ---------------------------------------------------------------------------
# Expiry pruning + empty-file cleanup
# ---------------------------------------------------------------------------


def test_expired_entry_pruned_active_entry_kept() -> None:
    set_alias_override("coder", "codex/o3", None, source="panel")  # no expiry
    set_alias_override("phase_worker", "claude/opus", 60.0, source="panel")

    data = _read_state()
    data["overrides"]["phase_worker"]["expires_at"] = time.time() - 1
    _write_state(data)

    active = get_active_alias_overrides()
    assert set(active) == {"coder"}

    # The state file was rewritten without the expired entry (and still exists).
    assert _state_path().exists()
    assert set(_read_state()["overrides"]) == {"coder"}


def test_all_entries_expired_deletes_file() -> None:
    set_alias_override("coder", "codex/o3", 60.0, source="panel")
    set_alias_override("phase_worker", "claude/opus", 60.0, source="panel")

    data = _read_state()
    past = time.time() - 1
    data["overrides"]["coder"]["expires_at"] = past
    data["overrides"]["phase_worker"]["expires_at"] = past
    _write_state(data)

    assert get_active_alias_overrides() == {}
    assert not _state_path().exists()


def test_expiry_boundary_is_expired() -> None:
    override = set_alias_override("coder", "codex/o3", 60.0, source="panel")
    assert override.expires_at is not None
    assert get_active_alias_override("coder", now=override.expires_at) is None


def test_get_all_prunes_only_expired_entry() -> None:
    set_alias_override("coder", "codex/o3", None, source="panel")
    short = set_alias_override("phase_worker", "claude/opus", 60.0, source="panel")
    assert short.expires_at is not None

    active = get_active_alias_overrides(now=short.expires_at)
    assert set(active) == {"coder"}


# ---------------------------------------------------------------------------
# Steady-state reads do not rewrite a canonical file
# ---------------------------------------------------------------------------


def test_steady_state_read_does_not_rewrite_file() -> None:
    set_alias_override("coder", "codex/o3", None, source="panel")
    before = _state_path().read_text(encoding="utf-8")

    get_active_alias_overrides()
    get_active_alias_override("coder")

    assert _state_path().read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("alias", ["", "   "])
def test_set_empty_alias_raises(alias: str) -> None:
    with pytest.raises(ValueError):
        set_alias_override(alias, "codex/o3", 60.0, source="panel")


@pytest.mark.parametrize("raw", ["", "   "])
def test_set_empty_raw_model_raises(raw: str) -> None:
    with pytest.raises(ValueError):
        set_alias_override("coder", raw, 60.0, source="panel")


@pytest.mark.parametrize("duration", [0.0, -1.0])
def test_set_non_positive_duration_raises(duration: float) -> None:
    with pytest.raises(ValueError):
        set_alias_override("coder", "codex/o3", duration, source="panel")


def test_set_empty_source_raises() -> None:
    with pytest.raises(ValueError):
        set_alias_override("coder", "codex/o3", 60.0, source=" ")


# ---------------------------------------------------------------------------
# v1 -> v2 read migration
# ---------------------------------------------------------------------------


def test_v1_flat_state_migrates_to_default_alias() -> None:
    """A legacy flat v1 object is read as the ``default`` alias override."""
    _write_state(
        {
            "provider": "codex",
            "model": "o3",
            "raw_model": "codex/o3",
            "created_at": time.time(),
            "expires_at": time.time() + 3600,
            "source": "ace",
        }
    )

    fetched = get_active_alias_override("default")
    assert fetched is not None
    assert fetched.provider == "codex"
    assert fetched.model == "o3"
    # No non-default override leaks out of the migration.
    assert get_active_alias_override("coder") is None


def test_v1_flat_state_is_rewritten_as_v2_on_read() -> None:
    _write_state(
        {
            "provider": "codex",
            "model": "o3",
            "raw_model": "codex/o3",
            "created_at": time.time(),
            "expires_at": time.time() + 3600,
            "source": "ace",
        }
    )

    assert get_active_alias_overrides()  # triggers the migrating read

    data = _read_state()
    assert data["version"] == 2
    assert set(data["overrides"]) == {"default"}
    # Canonical entry only — no stray top-level v1 keys remain.
    assert set(data) == {"version", "overrides"}


def test_expired_v1_flat_state_deletes_file() -> None:
    _write_state(
        {
            "provider": "codex",
            "model": "o3",
            "raw_model": "codex/o3",
            "created_at": time.time() - 7200,
            "expires_at": time.time() - 3600,
            "source": "ace",
        }
    )

    assert get_active_alias_overrides() == {}
    assert not _state_path().exists()


# ---------------------------------------------------------------------------
# Robustness against bad state files
# ---------------------------------------------------------------------------


def test_overrides_not_a_dict_deletes_file() -> None:
    _write_state({"version": 2, "overrides": ["not", "a", "map"]})
    assert get_active_alias_overrides() == {}
    assert not _state_path().exists()


def test_one_malformed_entry_pruned_valid_kept() -> None:
    set_alias_override("coder", "codex/o3", None, source="panel")
    data = _read_state()
    data["overrides"]["phase_worker"] = {"provider": "claude"}  # missing fields
    _write_state(data)

    active = get_active_alias_overrides()
    assert set(active) == {"coder"}
    assert set(_read_state()["overrides"]) == {"coder"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("created_at", float("nan")),
        ("created_at", float("inf")),
        ("created_at", True),
        ("created_at", 10**400),
        ("expires_at", float("nan")),
        ("expires_at", float("-inf")),
        ("expires_at", False),
        ("expires_at", 10**400),
    ],
)
def test_non_finite_persisted_timestamp_is_pruned(
    field: str,
    value: object,
) -> None:
    set_alias_override("coder", "codex/o3", None, source="panel")
    data = _read_state()
    data["overrides"]["phase_worker"] = {
        "provider": "claude",
        "model": "opus",
        "raw_model": "claude/opus",
        "created_at": time.time(),
        "expires_at": None,
        "source": "panel",
        field: value,
    }
    _write_state(data)

    active = get_active_alias_overrides()

    assert set(active) == {"coder"}
    assert set(_read_state()["overrides"]) == {"coder"}


def test_top_level_list_returns_empty_and_deletes() -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    assert get_active_alias_overrides() == {}
    assert not path.exists()


def test_malformed_json_returns_empty_and_deletes() -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json{{{", encoding="utf-8")

    assert get_active_alias_overrides() == {}
    assert not path.exists()
