"""Clan aggregation in the runner's wait-dependency index."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.wait_dependency_resolution import build_wait_dependency_index
from tests._dismissed_completion_helpers import (
    add_archive_identity,
    rebuild_completion_archive,
    write_dismissed_completion,
)


def _member(
    projects_root: Path,
    timestamp: str,
    name: str,
    *,
    generation: str,
    done: bool,
    queued: bool = False,
) -> Path:
    artifact_dir = projects_root / "proj/artifacts/ace-run" / timestamp
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": name,
                "agent_clan": "research",
                "agent_clan_generation": generation,
            }
        )
    )
    if done:
        (artifact_dir / "done.json").write_text(json.dumps({"outcome": "completed"}))
    if queued:
        (artifact_dir / "waiting.json").write_text(
            json.dumps({"waiting_for": ["research.predecessor"]})
        )
    return artifact_dir


def test_wait_on_clan_requires_every_member(tmp_path: Path) -> None:
    first = _member(
        tmp_path,
        "20260717010101",
        "research.one",
        generation="20260717010000",
        done=True,
    )
    second = _member(
        tmp_path,
        "20260717010202",
        "research.two",
        generation="20260717010000",
        done=False,
    )
    index = build_wait_dependency_index("proj", projects_root=tmp_path)

    assert not index.is_resolved("research")
    assert index.is_resolved("research", exclude_artifact_dir=second)
    (second / "done.json").write_text(json.dumps({"outcome": "completed"}))
    index = build_wait_dependency_index("proj", projects_root=tmp_path)
    assert index.is_resolved("research")
    assert first != second


def test_wait_on_clan_uses_newest_generation(tmp_path: Path) -> None:
    _member(
        tmp_path,
        "20260717010101",
        "research.old",
        generation="20260717010000",
        done=False,
    )
    _member(
        tmp_path,
        "20260717020101",
        "research.new",
        generation="20260717020000",
        done=True,
    )

    index = build_wait_dependency_index("proj", projects_root=tmp_path)

    assert index.is_resolved("research")


def test_wait_on_clan_counts_queued_members_as_unfinished(tmp_path: Path) -> None:
    generation = "20260717030000"
    for index in range(6):
        _member(
            tmp_path,
            f"20260717030{index + 1}00",
            f"research.done-{index + 1}",
            generation=generation,
            done=True,
        )
    queued_members = [
        _member(
            tmp_path,
            f"20260717031{index + 1}00",
            f"research.queued-{index + 1}",
            generation=generation,
            done=False,
            queued=True,
        )
        for index in range(3)
    ]

    index = build_wait_dependency_index("proj", projects_root=tmp_path)

    assert not index.is_resolved("research")

    for member in queued_members:
        (member / "done.json").write_text(json.dumps({"outcome": "completed"}))
    index = build_wait_dependency_index("proj", projects_root=tmp_path)

    assert index.is_resolved("research")


def test_wait_on_clan_uses_mixed_live_and_dismissed_successes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    generation = "20260720080000"
    archived_members = [
        _member(
            tmp_path,
            f"20260720080{index + 1}00",
            f"research.{index + 1}",
            generation=generation,
            done=True,
        )
        for index in range(6)
    ]
    for index, artifact_dir in enumerate(archived_members, start=1):
        add_archive_identity(artifact_dir)
        write_dismissed_completion(
            tmp_path,
            artifact_dir,
            f"research.{index}",
        )
        (artifact_dir / "done.json").unlink()

    for index in range(3):
        _member(
            tmp_path,
            f"20260720081{index + 1}00",
            f"research.current-{index + 1}",
            generation=generation,
            done=True,
        )
    rebuild_completion_archive()

    index = build_wait_dependency_index("proj", projects_root=tmp_path)

    assert index.is_resolved("research")
    assert all(
        member.archived_completion is not None
        for member in index.clans["research"][generation][:6]
    )


def test_wait_on_clan_rejects_dismissed_failed_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    generation = "20260720090000"
    failed = _member(
        tmp_path,
        "20260720090100",
        "research.failed",
        generation=generation,
        done=True,
    )
    add_archive_identity(failed)
    write_dismissed_completion(
        tmp_path,
        failed,
        "research.failed",
        status="FAILED",
    )
    (failed / "done.json").unlink()
    _member(
        tmp_path,
        "20260720090200",
        "research.done",
        generation=generation,
        done=True,
    )
    rebuild_completion_archive()

    index = build_wait_dependency_index("proj", projects_root=tmp_path)

    assert not index.is_resolved("research")
    candidate = index.clan_candidate("research")
    assert candidate is not None
    assert candidate.is_failed


def test_dismissed_completion_cannot_cross_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    artifact_dir = _member(
        tmp_path / "other-root",
        "20260720100100",
        "research.only",
        generation="20260720100000",
        done=False,
    )
    add_archive_identity(artifact_dir)
    write_dismissed_completion(
        tmp_path,
        artifact_dir,
        "research.only",
        project_name="different-project",
    )
    rebuild_completion_archive()

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / "other-root",
    )

    assert not index.is_resolved("research")
