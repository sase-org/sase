"""Publish-phase ordering and deadline-deferral tests."""

from __future__ import annotations

import fcntl
import time
from pathlib import Path

import pytest

from sase.core.paths import sase_projects_dir
from sase.memory.locks import locked_file
from sase.sdd._artifact_link_event_canonical import (
    ARTIFACT_LINK_EVENT_LOCK_FILENAME,
)
from sase.sdd._artifact_link_event_project import (
    BEAD_PROJECTION_DEFERRED_DIAGNOSTIC,
)
from sase.sdd._artifact_link_event_publish import (
    AGGREGATE_PROJECTION_DEFERRED_DIAGNOSTIC,
)
from sase.sdd._artifact_link_store_aggregate import (
    ArtifactLinkAggregateWriteDeferred,
)
from sase.sdd.artifact_link_event_publisher import (
    observation_or_put_event_from_row,
    publish_artifact_link_events,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import _row, allow_machine_sidecar_writes


_PUBLISH_PHASES = (
    "admission",
    "states",
    "roots",
    "local_receipts",
    "beads",
    "aggregate",
)


def _ownerless_event(operation_id: str) -> dict[str, object]:
    return observation_or_put_event_from_row(
        _row(
            source="agent:reader",
            relation="related",
            target="agent:planner",
            origin="manual",
        ),
        project_key="gh_sase-org__sase",
        operation_id=operation_id,
    )


def test_publish_report_lists_every_publish_sub_phase_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    store = ArtifactLinkStore(project_key="gh_sase-org__sase", sidecar_roots={})

    report = publish_artifact_link_events(
        store,
        (_ownerless_event("eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"),),
        push_after_commit=False,
        mutation_origin="machine",
    )

    assert report.published == 1
    assert tuple(name for name, _seconds in report.phase_seconds) == _PUBLISH_PHASES
    assert all(seconds >= 0.0 for _name, seconds in report.phase_seconds)


def test_aggregate_deferral_retains_the_rows_and_marks_the_report_deferred(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """publish_deferral = retain: a deferred rebuild settles nothing."""

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    store = ArtifactLinkStore(project_key="gh_sase-org__sase", sidecar_roots={})
    seen_deadlines: list[float | None] = []

    def deferred_rebuild(
        _store: ArtifactLinkStore, *, deadline: float | None = None, **_kwargs: object
    ) -> dict[str, object]:
        seen_deadlines.append(deadline)
        raise ArtifactLinkAggregateWriteDeferred(attempts=1, last_compute_seconds=60.0)

    with monkeypatch.context() as deferred:
        deferred.setattr(ArtifactLinkStore, "rebuild_aggregate", deferred_rebuild)
        report = publish_artifact_link_events(
            store,
            (_ownerless_event("ffffffffffffffffffffffffffffffff"),),
            push_after_commit=False,
            mutation_origin="machine",
            deadline=time.monotonic() + 600.0,
        )

    assert seen_deadlines and seen_deadlines[0] is not None
    assert report.deferred is True
    assert report.published == 0
    assert report.published_operation_ids == ()
    assert report.published_event_keys == ()
    assert report.aggregate_rows == ()
    assert AGGREGATE_PROJECTION_DEFERRED_DIAGNOSTIC in report.skip_diagnostics
    assert tuple(name for name, _seconds in report.phase_seconds) == _PUBLISH_PHASES

    # The durable event already landed, so the retained row republishes
    # idempotently once the aggregate rebuild fits its budget.
    replay = publish_artifact_link_events(
        store,
        (_ownerless_event("ffffffffffffffffffffffffffffffff"),),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert replay.published == 1
    assert replay.deferred is False
    assert len(store.load_aggregate()["rows"]) == 1


def test_publish_defers_when_the_event_lock_is_busy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    store = ArtifactLinkStore(project_key="gh_sase-org__sase", sidecar_roots={})
    admitted: list[object] = []

    def _admit(*_args: object, **_kwargs: object) -> None:
        admitted.append(True)
        raise AssertionError("admission should not run while the lock is busy")

    monkeypatch.setattr(
        "sase.sdd._artifact_link_event_publish._admit_incoming_event_objects",
        _admit,
    )
    lock_path = (
        sase_projects_dir() / store.project_key / ARTIFACT_LINK_EVENT_LOCK_FILENAME
    )
    with locked_file(lock_path, fcntl.LOCK_EX):
        report = publish_artifact_link_events(
            store,
            (_ownerless_event("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),),
            push_after_commit=False,
            mutation_origin="machine",
            deadline=time.monotonic() + 0.2,
        )

    assert report.deferred is True
    assert report.published == 0
    assert admitted == []
    assert BEAD_PROJECTION_DEFERRED_DIAGNOSTIC in report.skip_diagnostics
    assert ARTIFACT_LINK_EVENT_LOCK_FILENAME in " ".join(report.skip_diagnostics)


def test_publish_defers_inside_the_headroom_window_before_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    store = ArtifactLinkStore(project_key="gh_sase-org__sase", sidecar_roots={})
    admitted: list[object] = []

    def _admit(*_args: object, **_kwargs: object) -> None:
        admitted.append(True)
        raise AssertionError("admission should not run inside the headroom window")

    monkeypatch.setattr(
        "sase.sdd._artifact_link_event_publish._admit_incoming_event_objects",
        _admit,
    )

    report = publish_artifact_link_events(
        store,
        (_ownerless_event("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"),),
        push_after_commit=False,
        mutation_origin="machine",
        deadline=time.monotonic() + 30.0,
    )

    assert report.deferred is True
    assert report.published == 0
    assert admitted == []
    assert BEAD_PROJECTION_DEFERRED_DIAGNOSTIC in report.skip_diagnostics
