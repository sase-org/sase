"""Exact archive fallback semantics for terminal agent artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.dismissed_agents import mark_bundles_revived_by_suffixes
from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    build_wait_dependency_index,
    dependency_resolution_status,
)
from tests._agent_names_fixtures import make_agent
from tests._dismissed_completion_helpers import (
    add_archive_identity,
    rebuild_completion_archive,
    write_dismissed_completion,
)


def _archived_agent(
    tmp_path: Path,
    *,
    status: str = "DONE",
    name: str = "worker",
    suffix: str = "20260720120100",
) -> Path:
    artifact_dir = make_agent(tmp_path, "proj", suffix, name)
    add_archive_identity(artifact_dir)
    write_dismissed_completion(tmp_path, artifact_dir, name, status=status)
    return artifact_dir


def _identity_dependency(artifact_dir: Path, name: str = "worker") -> dict[str, str]:
    return {
        "project_name": "proj",
        "timestamp": artifact_dir.name,
        "artifact_dir": str(artifact_dir),
        "name": name,
    }


def _wait_classification(
    index: WaitDependencyIndex,
    *,
    artifact_dir: Path,
    name: str,
) -> tuple[bool, bool]:
    name_wait_resolved = index.is_resolved(name)
    identity_wait_resolved = dependency_resolution_status(
        index,
        [],
        [_identity_dependency(artifact_dir, name)],
    ).resolved
    return name_wait_resolved, identity_wait_resolved


@pytest.mark.parametrize(
    (
        "outcome",
        "archived_status",
        "expected_name_wait",
        "expected_identity_wait",
        "suffix",
    ),
    [
        ("completed", "DONE", True, True, "20260720160100"),
        ("completed", "PLAN DONE", True, True, "20260720160200"),
        ("completed", "TALE DONE", True, True, "20260720160300"),
        ("completed", "FEEDBACK", True, True, "20260720160400"),
        ("plan_committed", "PLAN COMMITTED", True, True, "20260720160500"),
        ("epic_approved", "EPIC APPROVED", True, True, "20260720160600"),
        ("epic_approved", "EPIC CREATED", True, True, "20260720160700"),
        ("noop", "DONE", True, True, "20260720160800"),
        ("plan_rejected", "PLAN REJECTED", False, True, "20260720160900"),
        ("failed", "FAILED", False, False, "20260720161000"),
        ("killed", "KILLED", False, False, "20260720161100"),
        ("stopped", "STOPPED", False, False, "20260720161200"),
        ("epic_launch_failed", "FAILED", False, False, "20260720161300"),
    ],
)
def test_live_done_and_archived_status_wait_classification_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    archived_status: str,
    expected_name_wait: bool,
    expected_identity_wait: bool,
    suffix: str,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    live_name = f"live-{suffix}"
    archived_name = f"archived-{suffix}"
    live = make_agent(
        tmp_path,
        "proj",
        suffix,
        live_name,
        done=True,
        outcome=outcome,
    )
    archived = _archived_agent(
        tmp_path,
        status=archived_status,
        name=archived_name,
        suffix=f"{int(suffix) + 100}",
    )
    rebuild_completion_archive()

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert _wait_classification(index, artifact_dir=live, name=live_name) == (
        expected_name_wait,
        expected_identity_wait,
    )
    assert _wait_classification(index, artifact_dir=archived, name=archived_name) == (
        expected_name_wait,
        expected_identity_wait,
    )


def test_plan_rejected_archive_is_identity_terminal_but_not_wait_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    artifact_dir = _archived_agent(tmp_path, status="PLAN REJECTED")
    rebuild_completion_archive()

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert not index.is_resolved("worker")
    assert dependency_resolution_status(
        index,
        [],
        [_identity_dependency(artifact_dir)],
    ).resolved


@pytest.mark.parametrize("status", ["FAILED", "KILLED", "STOPPED"])
def test_failed_archived_statuses_remain_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    artifact_dir = _archived_agent(tmp_path, status=status)
    rebuild_completion_archive()

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert not index.is_resolved("worker")
    assert not dependency_resolution_status(
        index,
        [],
        [_identity_dependency(artifact_dir)],
    ).resolved


@pytest.mark.parametrize(
    ("monitor_state", "expected_resolved"),
    [
        ("completed", True),
        ("stopped", True),
        ("failed", False),
        ("timeout", False),
        (None, False),
    ],
)
def test_archived_default_monitor_status_uses_monitor_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    monitor_state: str | None,
    expected_resolved: bool,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    artifact_dir = make_agent(
        tmp_path,
        "proj",
        "20260720162000",
        "worker",
    )
    add_archive_identity(artifact_dir)
    extra = {} if monitor_state is None else {"monitor_state": monitor_state}
    write_dismissed_completion(
        tmp_path,
        artifact_dir,
        "worker",
        status="MONITORED",
        extra=extra,
    )
    rebuild_completion_archive()

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert _wait_classification(index, artifact_dir=artifact_dir, name="worker") == (
        expected_resolved,
        expected_resolved,
    )
    candidate = index.artifacts_by_dir[str(artifact_dir)]
    assert candidate.archived_completion is not None
    assert candidate.is_failed is (not expected_resolved)


@pytest.mark.parametrize(
    ("monitor_state", "expected_resolved"),
    [
        ("completed", True),
        ("stopped", True),
        ("failed", False),
        ("timeout", False),
        (None, False),
    ],
)
def test_archived_recorded_stop_status_uses_monitor_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    monitor_state: str | None,
    expected_resolved: bool,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    artifact_dir = make_agent(
        tmp_path,
        "proj",
        "20260720162100",
        "worker",
    )
    add_archive_identity(artifact_dir)
    extra: dict[str, str] = {"monitor_stop_status": "TESTED"}
    if monitor_state is not None:
        extra["monitor_state"] = monitor_state
    write_dismissed_completion(
        tmp_path,
        artifact_dir,
        "worker",
        status="TESTED",
        extra=extra,
    )
    rebuild_completion_archive()

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert _wait_classification(index, artifact_dir=artifact_dir, name="worker") == (
        expected_resolved,
        expected_resolved,
    )
    candidate = index.artifacts_by_dir[str(artifact_dir)]
    assert candidate.archived_completion is not None
    assert candidate.is_failed is (not expected_resolved)


def test_archived_recorded_stop_status_compare_is_case_insensitive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    artifact_dir = make_agent(
        tmp_path,
        "proj",
        "20260720162200",
        "worker",
    )
    add_archive_identity(artifact_dir)
    write_dismissed_completion(
        tmp_path,
        artifact_dir,
        "worker",
        status="tested",
        extra={"monitor_stop_status": "TESTED", "monitor_state": "completed"},
    )
    rebuild_completion_archive()

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert _wait_classification(index, artifact_dir=artifact_dir, name="worker") == (
        True,
        True,
    )


@pytest.mark.parametrize(
    ("extra", "suffix"),
    [
        ({"monitor_state": "completed"}, "20260720162300"),
        (
            {"monitor_state": "completed", "monitor_stop_status": "TESTED"},
            "20260720162400",
        ),
    ],
    ids=["unrecorded_custom_label", "mismatched_recorded_pair"],
)
def test_archived_custom_monitor_stop_status_remains_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra: dict[str, str],
    suffix: str,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    artifact_dir = make_agent(
        tmp_path,
        "proj",
        suffix,
        "worker",
    )
    add_archive_identity(artifact_dir)
    write_dismissed_completion(
        tmp_path,
        artifact_dir,
        "worker",
        status="SLEPT",
        extra=extra,
    )
    rebuild_completion_archive()

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert not index.is_resolved("worker")
    assert index.artifacts_by_dir[str(artifact_dir)].archived_completion is None


@pytest.mark.parametrize(
    ("bundle_name", "bundle_patch"),
    [("other", "change"), ("worker", "other-change")],
)
def test_archive_name_and_patch_mismatches_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bundle_name: str,
    bundle_patch: str,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    artifact_dir = make_agent(
        tmp_path,
        "proj",
        "20260720130100",
        "worker",
    )
    add_archive_identity(artifact_dir)
    write_dismissed_completion(
        tmp_path,
        artifact_dir,
        bundle_name,
        changespec_name=bundle_patch,
    )
    rebuild_completion_archive()

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert not index.is_resolved("worker")


def test_corrupt_or_revived_archive_does_not_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    corrupt = make_agent(
        tmp_path,
        "proj",
        "20260720140100",
        "corrupt",
    )
    add_archive_identity(corrupt)
    corrupt_bundle = write_dismissed_completion(tmp_path, corrupt, "corrupt")
    corrupt_bundle.write_text("{", encoding="utf-8")

    revived = make_agent(
        tmp_path,
        "proj",
        "20260720140200",
        "revived",
    )
    add_archive_identity(revived)
    write_dismissed_completion(tmp_path, revived, "revived")
    rebuild_completion_archive()
    assert mark_bundles_revived_by_suffixes({revived.name}) == 1

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert not index.is_resolved("corrupt")
    assert not index.is_resolved("revived")


def test_live_done_marker_precedes_matching_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    artifact_dir = make_agent(
        tmp_path,
        "proj",
        "20260720150100",
        "worker",
        done=True,
        outcome="failed",
    )
    add_archive_identity(artifact_dir)
    write_dismissed_completion(tmp_path, artifact_dir, "worker", status="DONE")
    rebuild_completion_archive()

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert not index.is_resolved("worker")


def test_ambiguous_exact_archive_rows_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    artifact_dir = _archived_agent(tmp_path)
    first_bundle = write_dismissed_completion(tmp_path, artifact_dir, "worker")
    duplicate = first_bundle.parent / "202607" / first_bundle.name
    duplicate.parent.mkdir(parents=True)
    duplicate.write_text(first_bundle.read_text(encoding="utf-8"), encoding="utf-8")
    rebuild_completion_archive()

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert not index.is_resolved("worker")
