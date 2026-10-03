"""Per-command repo-inventory and config-key memoization tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase import _linked_repo_config as linked_repo_config
from sase import _linked_repo_config_state as config_state
from sase.repo_inventory import (
    collect_repo_inventory,
    repo_inventory_session,
    reset_repo_inventory_memo,
)
from tests._repo_inventory_helpers import project_record

__all__ = [
    "test_config_cache_key_memoized_by_identity",
    "test_config_cache_key_reset_clears_identity_memo",
    "test_inventory_memo_hits_within_session",
    "test_inventory_memo_matches_uncached_result",
    "test_inventory_memo_misses_on_config_token_change",
    "test_inventory_memo_misses_on_projects_root_change",
    "test_inventory_not_memoized_outside_session",
    "test_sidecar_dirnames_reuse_identity_memo",
]


def _counted_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> list[int]:
    calls: list[int] = []
    project = project_record(tmp_path)

    def list_records(*args: object, **kwargs: object) -> list[object]:
        calls.append(1)
        return [project]  # type: ignore[return-value]

    monkeypatch.setattr("sase.repo_inventory.list_project_records", list_records)
    monkeypatch.setattr(
        "sase.repo_inventory.resolution_config",
        lambda *_args, **_kwargs: {},
    )
    return calls


def test_inventory_memo_hits_within_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _counted_project(tmp_path, monkeypatch)
    root = tmp_path / "projects"

    with repo_inventory_session():
        first = collect_repo_inventory(root)
        second = collect_repo_inventory(root)

    assert calls == [1]
    assert second is first


def test_inventory_not_memoized_outside_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _counted_project(tmp_path, monkeypatch)
    root = tmp_path / "projects"

    first = collect_repo_inventory(root)
    second = collect_repo_inventory(root)

    assert calls == [1, 1]
    assert second == first
    assert second is not first


def test_inventory_memo_misses_on_config_token_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _counted_project(tmp_path, monkeypatch)
    root = tmp_path / "projects"
    tokens = [(("generation", 1),), (("generation", 2),)]
    monkeypatch.setattr(
        "sase.config.core.current_config_token",
        lambda: tokens[len(calls) - 1],
    )

    with repo_inventory_session():
        collect_repo_inventory(root)
        collect_repo_inventory(root)

    assert calls == [1, 1]


def test_inventory_memo_misses_on_projects_root_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _counted_project(tmp_path, monkeypatch)
    other = tmp_path / "other"
    other.mkdir()
    (other / "projects").mkdir()

    with repo_inventory_session():
        collect_repo_inventory(tmp_path / "projects")
        collect_repo_inventory(other / "projects")

    assert calls == [1, 1]


def test_inventory_memo_matches_uncached_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _counted_project(tmp_path, monkeypatch)
    root = tmp_path / "projects"

    uncached = collect_repo_inventory(root)
    with repo_inventory_session():
        memoized = collect_repo_inventory(root)
        reset_repo_inventory_memo()
        rebuilt = collect_repo_inventory(root)

    assert memoized == uncached
    assert rebuilt == uncached


def test_config_cache_key_memoized_by_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freezes: list[object] = []
    real_freeze = config_state._freeze_config_value

    def counted(value: object) -> tuple[object, ...]:
        freezes.append(value)
        return real_freeze(value)

    monkeypatch.setattr(config_state, "_freeze_config_value", counted)
    config = {"repos": {"linked": [{"name": "x"}]}}

    first = linked_repo_config.repo_config_cache_key(config)
    frozen_once = len(freezes)
    assert frozen_once > 0
    second = linked_repo_config.repo_config_cache_key(config)

    assert second is first
    assert len(freezes) == frozen_once

    # A distinct object with equal contents still freezes independently.
    other = linked_repo_config.repo_config_cache_key(dict(config))

    assert other == first
    assert other is not first
    assert len(freezes) > frozen_once


def test_config_cache_key_reset_clears_identity_memo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freezes: list[object] = []
    real_freeze = config_state._freeze_config_value

    def counted(value: object) -> tuple[object, ...]:
        freezes.append(value)
        return real_freeze(value)

    monkeypatch.setattr(config_state, "_freeze_config_value", counted)
    config = {"repos": {"linked": []}}

    linked_repo_config.repo_config_cache_key(config)
    frozen_once = len(freezes)
    assert frozen_once > 0
    linked_repo_config.reset_linked_repo_config_caches()
    linked_repo_config.repo_config_cache_key(config)

    assert len(freezes) > frozen_once


def test_sidecar_dirnames_reuse_identity_memo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase._linked_repo_paths import _sdd_sidecar_repo_dirnames

    freezes: list[object] = []
    real_freeze = config_state._freeze_config_value

    def counted(value: object) -> tuple[object, ...]:
        freezes.append(value)
        return real_freeze(value)

    monkeypatch.setattr(config_state, "_freeze_config_value", counted)
    primary = tmp_path / "widget"
    primary.mkdir()
    config = {"repos": {"sidecar": {"custom": {}}}}

    _sdd_sidecar_repo_dirnames(str(primary), config=config)
    frozen_once = len(freezes)
    assert frozen_once > 0
    _sdd_sidecar_repo_dirnames(str(primary), config=config)

    assert len(freezes) == frozen_once
