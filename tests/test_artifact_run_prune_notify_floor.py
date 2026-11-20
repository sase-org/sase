"""The hourly ACE-run prune preview's selected-bytes floor and pressure gate."""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.config import (
    DEFAULT_ARTIFACT_RETENTION_RUN_PRUNE_NOTIFY_MIN_BYTES,
    get_artifact_retention_run_prune_notify_min_bytes,
)
from sase.core.agent_artifact_run_prune_publish import publish_run_prune_preview
from sase.notifications.store import load_notifications

from tests._axe_chop_output_contract_helpers import (
    retention_empty_shard,
    retention_plan,
    retention_selected_item,
)

_GIB = 1024**3
_SMALL_SELECTION_BYTES = 873 * 1024


def _observation(*, total_bytes: int, free_bytes: int) -> dict[str, Any]:
    return {
        "label": "ace_runs",
        "role": "owner",
        "path": "/runs",
        "measurement_path": "/runs",
        "total_bytes": total_bytes,
        "used_bytes": total_bytes - free_bytes,
        "free_bytes": free_bytes,
    }


_ROOMY_DISK = _observation(total_bytes=1024 * _GIB, free_bytes=283 * _GIB)
_FULL_DISK = _observation(total_bytes=100 * _GIB, free_bytes=500 * 1024**2)


@pytest.fixture
def publish(monkeypatch: pytest.MonkeyPatch) -> Any:
    module = importlib.import_module("sase.core.agent_artifact_run_prune_publish")
    monkeypatch.setattr(
        module,
        "load_project_ref_display_snapshot",
        lambda **_kwargs: SimpleNamespace(
            display_snapshot={"proj": "Pretty Project"},
            label_for_ref=lambda _project: "Pretty Project",
        ),
    )
    return module


def _measure_as(
    monkeypatch: pytest.MonkeyPatch, publish: Any, observation: dict[str, Any]
) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    def collect(targets: Any, **_kwargs: Any) -> tuple[dict[str, Any], ...]:
        calls.append(tuple(targets))
        return (dict(observation),)

    monkeypatch.setattr(publish, "collect_filesystem_observations", collect)
    return calls


def _small_plan(tmp_path: Path) -> Any:
    return retention_plan(
        selected=(retention_selected_item(tmp_path),),
        reclaimable_bytes=_SMALL_SELECTION_BYTES,
    )


def test_small_selection_on_roomy_disk_does_not_notify(
    monkeypatch: pytest.MonkeyPatch, publish: Any, tmp_path: Path
) -> None:
    calls = _measure_as(monkeypatch, publish, _ROOMY_DISK)

    outcome = publish_run_prune_preview(_small_plan(tmp_path))

    assert outcome.action == "none"
    assert load_notifications(include_dismissed=True) == []
    assert len(calls) == 1
    assert calls[0][0]["path"] == str(
        _small_plan(tmp_path).policy.normalized_projects_root()
    )


def test_small_selection_under_disk_pressure_notifies(
    monkeypatch: pytest.MonkeyPatch, publish: Any, tmp_path: Path
) -> None:
    _measure_as(monkeypatch, publish, _FULL_DISK)

    outcome = publish_run_prune_preview(_small_plan(tmp_path))

    assert outcome.action == "created"
    rows = load_notifications()
    assert len(rows) == 1
    assert rows[0].notes[0] == "873.0 KiB of old ACE runs can be pruned"


def test_selection_at_the_floor_notifies_without_measuring_the_disk(
    monkeypatch: pytest.MonkeyPatch, publish: Any, tmp_path: Path
) -> None:
    calls = _measure_as(monkeypatch, publish, _ROOMY_DISK)
    plan = retention_plan(
        selected=(retention_selected_item(tmp_path),),
        reclaimable_bytes=DEFAULT_ARTIFACT_RETENTION_RUN_PRUNE_NOTIFY_MIN_BYTES,
    )

    outcome = publish_run_prune_preview(plan)

    assert outcome.action == "created"
    assert len(load_notifications()) == 1
    assert calls == []


def test_dropping_below_the_floor_retires_the_live_preview(
    monkeypatch: pytest.MonkeyPatch, publish: Any, tmp_path: Path
) -> None:
    _measure_as(monkeypatch, publish, _ROOMY_DISK)
    big = retention_plan(
        selected=(retention_selected_item(tmp_path),), reclaimable_bytes=2 * _GIB
    )

    assert publish_run_prune_preview(big).action == "created"
    assert publish_run_prune_preview(_small_plan(tmp_path)).action == "retired"

    assert load_notifications() == []


def test_unreadable_sources_and_empty_shards_still_notify_on_a_roomy_disk(
    monkeypatch: pytest.MonkeyPatch, publish: Any, tmp_path: Path
) -> None:
    calls = _measure_as(monkeypatch, publish, _ROOMY_DISK)

    paused = publish_run_prune_preview(
        retention_plan(sources_unavailable=("artifact_index: unreadable",))
    )
    shards = publish_run_prune_preview(
        retention_plan(empty_shards=(retention_empty_shard(tmp_path),))
    )

    assert paused.action == "created"
    assert shards.action == "created"
    assert calls == []


def test_explicit_publish_ignores_the_floor(
    monkeypatch: pytest.MonkeyPatch, publish: Any, tmp_path: Path
) -> None:
    calls = _measure_as(monkeypatch, publish, _ROOMY_DISK)

    outcome = publish_run_prune_preview(_small_plan(tmp_path), apply_notify_floor=False)

    assert outcome.action == "created"
    assert len(load_notifications()) == 1
    assert calls == []


def test_pressure_measurement_failure_leaves_only_the_size_floor(
    monkeypatch: pytest.MonkeyPatch, publish: Any, tmp_path: Path
) -> None:
    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("statvfs failed")

    monkeypatch.setattr(publish, "collect_filesystem_observations", broken)

    outcome = publish_run_prune_preview(_small_plan(tmp_path))

    assert outcome.action == "none"
    assert load_notifications(include_dismissed=True) == []


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (None, DEFAULT_ARTIFACT_RETENTION_RUN_PRUNE_NOTIFY_MIN_BYTES),
        (0, 0),
        (5 * _GIB, 5 * _GIB),
        (-1, DEFAULT_ARTIFACT_RETENTION_RUN_PRUNE_NOTIFY_MIN_BYTES),
        ("1G", DEFAULT_ARTIFACT_RETENTION_RUN_PRUNE_NOTIFY_MIN_BYTES),
        (True, DEFAULT_ARTIFACT_RETENTION_RUN_PRUNE_NOTIFY_MIN_BYTES),
    ],
)
def test_notify_floor_config_validation(
    monkeypatch: pytest.MonkeyPatch, configured: object, expected: int
) -> None:
    retention = {} if configured is None else {"run_prune_notify_min_bytes": configured}
    monkeypatch.setattr(
        "sase.config._settings_artifacts._artifact_retention_config",
        lambda: retention,
    )

    assert get_artifact_retention_run_prune_notify_min_bytes() == expected
    assert DEFAULT_ARTIFACT_RETENTION_RUN_PRUNE_NOTIFY_MIN_BYTES == _GIB
