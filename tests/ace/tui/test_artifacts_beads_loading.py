"""Data-loading coverage for the read-only Artifacts Beads pane."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.testing import make_patch
from sase.ace.tui.widgets.artifacts import beads_data, beads_data_sources
from sase.ace.tui.widgets.artifacts.beads_data import load_beads_snapshot
from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.notifications.models import Notification
from sase.vcs_provider import IssueWire


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
        design="plan:202608/beads.md",
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
    flag = Issue(
        "alpha-flag",
        "Flag",
        issue_type=IssueType.TASK,
        task_type="flag",
        task_type_fields={
            "key": "plugins_enabled",
            "kind": "beta",
            "when_enabled": "on",
            "when_disabled": "off",
            "remove_when": "done",
            "remove_by_date": "2026-12-01",
            "remove_by_release": "0.19.0",
        },
    )
    calls = 0

    def load(_path: Path) -> tuple[list[Issue], frozenset[str], frozenset[str]]:
        nonlocal calls
        calls += 1
        return [task, flag, phase, epic], frozenset({task.id}), frozenset()

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
    monkeypatch.setattr("sase.__version__", "0.19.0")
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_data.core_time.local_now",
        lambda: datetime(2026, 12, 7, 12, 0, 0),
    )

    first = load_beads_snapshot("alpha")
    reused = load_beads_snapshot("alpha", previous=first)
    forced = load_beads_snapshot("alpha", previous=first, force=True)

    assert reused is first
    assert forced is not first
    assert calls == 2
    assert [item.issue.id for item in first.tasks] == [task.id]
    assert [item.issue.id for item in first.flags] == [flag.id]
    assert first.flag_due[("alpha", flag.id)].state == "due"
    assert [item.issue.id for item in first.epics] == [epic.id]
    assert [item.issue.id for item in first.phases_by_epic[("alpha", epic.id)]] == [
        phase.id
    ]
    assert first.plan_links[("alpha", epic.id)].endswith("resolved.md")


def test_snapshot_groups_flag_task_beads_with_flags_not_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir = tmp_path / "beads"
    task = Issue(
        "alpha-task",
        "Task",
        issue_type=IssueType.TASK,
        status=Status.READY,
    )
    flag_task = Issue(
        "alpha-flag",
        "Flag",
        issue_type=IssueType.TASK,
        task_type="flag",
        task_type_fields={
            "key": "plugins_enabled",
            "kind": "beta",
            "when_enabled": "new path",
            "when_disabled": "old path",
            "remove_when": "when proven",
            "remove_by_date": "2026-12-01",
            "remove_by_release": "0.19.0",
        },
    )

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
    monkeypatch.setattr(
        beads_data,
        "_load_project_beads",
        lambda _path: ([task, flag_task], frozenset(), frozenset()),
    )
    monkeypatch.setattr(beads_data, "_load_pending_triage", lambda: {})
    monkeypatch.setattr("sase.__version__", "0.19.0")
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_data.core_time.local_now",
        lambda: datetime(2026, 12, 7, 12, 0, 0),
    )

    snapshot = load_beads_snapshot("alpha", force=True)

    assert [item.issue.id for item in snapshot.tasks] == [task.id]
    assert [item.issue.id for item in snapshot.flags] == [flag_task.id]
    assert snapshot.flag_due[("alpha", flag_task.id)].state == "due"


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


def test_snapshot_resolves_display_name_scope_to_project_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A #gh project scoped by display name must not report a missing store."""
    record = ProjectRecordWire(
        schema_version=3,
        project_name="gh_acme__widget",
        project_dir="/state/projects/gh_acme__widget",
        project_file="/state/projects/gh_acme__widget/gh_acme__widget.sase",
        archive_file=None,
        workspace_dir=str(tmp_path / "workspace"),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=[],
        display_name="widget",
    )
    monkeypatch.setattr(
        "sase.core.project_lifecycle_facade.list_project_records",
        lambda *_a, **_kw: [record],
    )
    beads_dir = tmp_path / "beads"

    def project_beads_dir(project: str) -> Path | None:
        return beads_dir if project == "gh_acme__widget" else None

    monkeypatch.setattr(beads_data, "_project_beads_dir", project_beads_dir)
    monkeypatch.setattr(beads_data, "_project_document_roots", lambda _project: {})
    monkeypatch.setattr(beads_data, "_store_mtime_key", lambda _path: ())
    monkeypatch.setattr(beads_data, "_notifications_mtime_key", lambda: ())
    monkeypatch.setattr(beads_data, "_load_pending_triage", lambda: {})
    monkeypatch.setattr(
        beads_data,
        "_load_project_beads",
        lambda _path: (
            [Issue("widget-task", "Task", issue_type=IssueType.TASK)],
            frozenset(),
            frozenset(),
        ),
    )

    snapshot = load_beads_snapshot("widget", force=True)

    assert snapshot.errors == {}
    assert [item.issue.id for item in snapshot.tasks] == ["widget-task"]


def test_snapshot_builds_external_issue_cache_and_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir = tmp_path / "beads"
    mirrored = Issue(
        "alpha-ready",
        "Ready for triage",
        issue_type=IssueType.TASK,
        external_ref="42",
    )
    drifted = Issue(
        "alpha-closed",
        "Local closed title",
        issue_type=IssueType.TASK,
        status=Status.CLOSED,
        external_ref="43",
    )
    stale = Issue(
        "alpha-ref",
        "Referenced issue",
        issue_type=IssueType.TASK,
        refs=["bug:alpha#99"],
    )
    linked_patch = make_patch(name="linked_patch")
    linked_patch.bug = "bug:alpha#42"
    remote_issues = (
        IssueWire(
            number=42,
            title="Ready for triage",
            state="open",
            labels=("priority:high",),
            url="https://example.test/issues/42",
        ),
        IssueWire(number=43, title="Remote open title", state="open"),
        IssueWire(number=77, title="Remote only", state="closed"),
    )
    list_calls: list[tuple[str, int]] = []

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
    monkeypatch.setattr(beads_data, "_project_document_roots", lambda _project: {})
    monkeypatch.setattr(beads_data, "_store_mtime_key", lambda _path: ())
    monkeypatch.setattr(beads_data, "_notifications_mtime_key", lambda: ())
    monkeypatch.setattr(
        beads_data,
        "_load_project_beads",
        lambda _path: ([mirrored, drifted, stale], frozenset(), frozenset()),
    )
    monkeypatch.setattr(beads_data, "_load_pending_triage", lambda: {})
    monkeypatch.setattr(
        beads_data,
        "resolve_issue_tracker_scope",
        lambda _project: SimpleNamespace(
            project_key="alpha",
            display_name="Alpha",
            project_file="/state/alpha.sase",
            cwd="/repos/alpha",
            provider=object(),
        ),
    )
    monkeypatch.setattr(
        beads_data,
        "issue_tracker_capabilities",
        lambda _provider: SimpleNamespace(
            listing=True,
            reads=True,
            mutations=False,
            urls=True,
        ),
    )

    def list_issues(
        _scope: object,
        *,
        state: str,
        limit: int,
    ) -> tuple[IssueWire, ...]:
        list_calls.append((state, limit))
        return remote_issues

    monkeypatch.setattr(beads_data, "list_project_issues", list_issues)

    result = load_beads_snapshot("alpha", force=True, patches=(linked_patch,))

    assert list_calls == [("all", 101)]
    assert result.external_projects["alpha"].issues == remote_issues
    assert result.external_unmirrored_counts == {"alpha": 1}
    ready_link = result.external_links[("alpha", "alpha-ready")][0]
    assert ready_link.issue == remote_issues[0]
    assert ready_link.relation == "mirrored"
    assert ready_link.reverse_beads == (mirrored,)
    assert ready_link.reverse_patches == (linked_patch,)
    drift_link = result.external_links[("alpha", "alpha-closed")][0]
    assert drift_link.drift is True
    stale_link = result.external_links[("alpha", "alpha-ref")][0]
    assert stale_link.relation == "referenced"
    assert stale_link.stale is True
    assert stale_link.issue is None


def test_snapshot_can_skip_external_issue_cache_for_first_paint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir = tmp_path / "beads"
    task = Issue(
        "alpha-ready",
        "Ready for triage",
        issue_type=IssueType.TASK,
        external_ref="42",
    )

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
    monkeypatch.setattr(beads_data, "_project_document_roots", lambda _project: {})
    monkeypatch.setattr(beads_data, "_store_mtime_key", lambda _path: ())
    monkeypatch.setattr(beads_data, "_notifications_mtime_key", lambda: ())
    monkeypatch.setattr(
        beads_data,
        "_load_project_beads",
        lambda _path: ([task], frozenset(), frozenset()),
    )
    monkeypatch.setattr(beads_data, "_load_pending_triage", lambda: {})
    monkeypatch.setattr(
        beads_data,
        "resolve_issue_tracker_scope",
        lambda _project: pytest.fail("first paint must not resolve issue trackers"),
    )
    monkeypatch.setattr(
        beads_data,
        "list_project_issues",
        lambda *_args, **_kwargs: pytest.fail("first paint must not list issues"),
    )

    result = load_beads_snapshot("alpha", force=True, include_external=False)

    assert [item.issue.id for item in result.tasks] == ["alpha-ready"]
    assert result.external_projects == {}
    assert result.external_links == {}
    assert result.external_unmirrored_counts == {}


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
