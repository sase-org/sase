"""Data-loading coverage for the read-only Artifacts Beads pane."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.widgets.artifacts import beads_data, beads_data_sources
from sase.ace.tui.widgets.artifacts.beads_data import load_beads_snapshot
from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.notifications.models import Notification


def test_snapshot_reuses_unchanged_source_key_and_force_reloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir = tmp_path / "beads"
    epic = Issue(
        "alpha-1",
        "Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="plans:202608/beads.md",
    )
    phase = Issue(
        "alpha-1.1",
        "Phase",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
    )
    task = Issue(
        "alpha-task",
        "Task",
        issue_type=IssueType.TASK,
        status=Status.READY,
    )
    calls = 0

    def load(_path: Path) -> tuple[list[Issue], frozenset[str], frozenset[str]]:
        nonlocal calls
        calls += 1
        return [task, phase, epic], frozenset({task.id}), frozenset()

    monkeypatch.setattr(
        beads_data,
        "_resolve_projects",
        lambda _project: (
            SimpleNamespace(
                project="alpha",
                display_name="Alpha",
                workspace_dir=str(tmp_path / "workspace"),
            ),
        ),
    )
    monkeypatch.setattr(beads_data, "_project_beads_dir", lambda _project: beads_dir)
    monkeypatch.setattr(
        beads_data, "_project_document_roots", lambda _project: {"plans": tmp_path}
    )
    monkeypatch.setattr(
        beads_data, "_store_mtime_key", lambda _path: (("store", 1, 1),)
    )
    monkeypatch.setattr(
        beads_data, "_notifications_mtime_key", lambda: (("notifications", 1, 1),)
    )
    monkeypatch.setattr(beads_data, "_load_project_beads", load)
    monkeypatch.setattr(beads_data, "_load_pending_triage", lambda: {})
    monkeypatch.setattr(
        beads_data,
        "_resolve_plan_link",
        lambda *_args, **_kwargs: str(tmp_path / "resolved.md"),
    )

    first = load_beads_snapshot("alpha")
    reused = load_beads_snapshot("alpha", previous=first)
    forced = load_beads_snapshot("alpha", previous=first, force=True)

    assert reused is first
    assert forced is not first
    assert calls == 2
    assert [item.issue.id for item in first.tasks] == [task.id]
    assert [item.issue.id for item in first.epics] == [epic.id]
    assert [item.issue.id for item in first.phases_by_epic[("alpha", epic.id)]] == [
        phase.id
    ]
    assert first.plan_links[("alpha", epic.id)].endswith("resolved.md")


def test_snapshot_isolates_per_project_read_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        beads_data,
        "_resolve_projects",
        lambda _project: tuple(
            SimpleNamespace(project=name, display_name=name.title(), workspace_dir=None)
            for name in ("alpha", "beta")
        ),
    )
    monkeypatch.setattr(
        beads_data,
        "_project_beads_dir",
        lambda project: tmp_path / project / "beads",
    )
    monkeypatch.setattr(beads_data, "_project_document_roots", lambda _project: {})
    monkeypatch.setattr(beads_data, "_store_mtime_key", lambda _path: ())
    monkeypatch.setattr(beads_data, "_notifications_mtime_key", lambda: ())
    monkeypatch.setattr(beads_data, "_load_pending_triage", lambda: {})

    def load(path: Path) -> tuple[list[Issue], frozenset[str], frozenset[str]]:
        if "beta" in path.parts:
            raise ValueError("broken event")
        return (
            [Issue("alpha-task", "Task", issue_type=IssueType.TASK)],
            frozenset(),
            frozenset(),
        )

    monkeypatch.setattr(beads_data, "_load_project_beads", load)

    result = load_beads_snapshot(None, force=True)

    assert [item.issue.id for item in result.tasks] == ["alpha-task"]
    assert result.errors == {"beta": "Unable to read beads: broken event"}


def test_triage_gate_matches_request_payload_not_request_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "request_id": "opaque-random-id",
                "created_at": "2026-08-01T10:00:00-04:00",
                "payload": {"project": "alpha", "bead_id": "alpha-task"},
            }
        ),
        encoding="utf-8",
    )
    notification = Notification(
        id="notification-1",
        timestamp="2026-08-01T10:01:00-04:00",
        sender="bead",
        action="TaskTriage",
        action_data={"request_id": "does-not-contain-the-bead-id"},
    )
    monkeypatch.setattr(
        "sase.notifications.store.load_notifications",
        lambda **_kwargs: [notification],
    )
    monkeypatch.setattr(
        "sase.notification_gates.paths.resolve_notification_bundle",
        lambda _notification: SimpleNamespace(request=request),
    )

    matches = beads_data_sources.load_pending_triage()

    gate = matches[("alpha", "alpha-task")]
    assert gate.notification_id == notification.id
    assert gate.request_id == "opaque-random-id"
    assert gate.created_at == "2026-08-01T10:00:00-04:00"
