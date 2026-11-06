"""Pilot coverage for the ACE-run prune review modal."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.testing.wait import wait_for
from sase.ace.tui.modals.artifact_run_prune_modal import ArtifactRunPruneModal
from sase.ace.tui.modals.report_modal import ReportModal
from sase.core.agent_artifact_run_prune_review import (
    RunPruneProjectAggregate,
    RunPruneReview,
    RunPruneReviewCounts,
    RunPruneSnapshot,
    RunPruneSnapshotItem,
)
from sase.notifications import Notification, NotificationReport


def _review(*, blocked: bool = False) -> RunPruneReview:
    return RunPruneReview(
        fingerprint="0123456789abcdef",
        captured_at="2026-11-05T11:00:00+00:00",
        keep_recent_months=2,
        first_kept_month="2026-09",
        counts=RunPruneReviewCounts(
            candidates=2,
            selected=1,
            protected=1,
            empty_shards=0,
        ),
        reclaimable_bytes=2048,
        projects=(
            RunPruneProjectAggregate(
                project="project-key",
                runs=1,
                bytes=2048,
                oldest="20260701000000",
                newest="20260701000000",
            ),
        ),
        unavailable_sources=("beads sidecar", "plans sidecar") if blocked else (),
        unavailable_source_count=2 if blocked else 0,
    )


def _notification() -> Notification:
    return Notification(
        id="prune-review",
        timestamp="2026-11-05T11:00:00+00:00",
        sender="axe",
        notes=["1.0 KiB of old ACE runs can be pruned"],
        action="ViewReport",
        action_data={"report": "{}"},
    )


def _snapshot(review: RunPruneReview) -> RunPruneSnapshot:
    items: list[RunPruneSnapshotItem] = []
    for project in review.projects:
        base_size, extra_bytes = divmod(project.bytes, project.runs)
        for index in range(project.runs):
            timestamp = (
                project.oldest
                if index == 0
                else project.newest
                if index == project.runs - 1
                else project.oldest
            )
            items.append(
                RunPruneSnapshotItem(
                    project=project.project,
                    timestamp=timestamp,
                    artifact_dir=f"/fixture/{project.project}/{index}/{timestamp}",
                    size_bytes=base_size + int(index < extra_bytes),
                )
            )
    return RunPruneSnapshot(
        fingerprint=review.fingerprint,
        captured_at=review.captured_at,
        keep_recent_months=review.keep_recent_months,
        items=tuple(items),
        empty_shard_count=review.counts.empty_shards,
        sources_unavailable=review.unavailable_sources,
    )


class _PilotApp(App[None]):
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    ArtifactRunPruneModal { align: center middle; }
    ArtifactRunPruneModal > #prune-review-container {
        width: 95%; height: 90%; padding: 1 2; border: solid cyan;
    }
    ArtifactRunPruneModal #prune-review-scroll { height: 1fr; }
    ArtifactRunPruneModal #prune-review-projects { height: auto; }
    ArtifactRunPruneModal #prune-review-buttons { height: auto; }
    """

    def __init__(self, modal: ArtifactRunPruneModal) -> None:
        super().__init__()
        self.modal = modal
        self.notifications: list[tuple[str, str]] = []
        self.submissions: list[tuple[list[str], dict[str, Any]]] = []
        self.refreshed = 0
        self._proc_projection: object | None = None

    def compose(self) -> ComposeResult:
        yield Static("test app")

    def on_mount(self) -> None:
        self.push_screen(self.modal)

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _submit_durable_proc(self, argv: list[str], **kwargs: Any) -> object:
        self.submissions.append((argv, kwargs))
        return object()

    def _refresh_notification_count(self) -> None:
        self.refreshed += 1


async def _wait_ready(pilot: Any, modal: ArtifactRunPruneModal) -> None:
    await wait_for(pilot, lambda: modal._view.state != "CHECKING")


@pytest.fixture
def ready_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.core.agent_artifact_run_prune_review.load_snapshot",
        lambda _fingerprint: _snapshot(_review()),
    )
    monkeypatch.setattr(
        "sase.project_display_names.cached_project_display_snapshot",
        lambda: {"project-key": "Pretty Project"},
    )


async def test_ready_confirmation_submits_one_durable_proc(
    ready_snapshot: None,
) -> None:
    modal = ArtifactRunPruneModal(
        _review(),
        _notification(),
        now=datetime(2026, 11, 5, 11, 33, tzinfo=UTC),
    )
    app = _PilotApp(modal)

    async with app.run_test(size=(100, 32)) as pilot:
        await _wait_ready(pilot, modal)
        assert modal._view.state == "READY"
        assert modal.query_one("#prune-review-cancel").has_focus

        await pilot.press("y")

        assert len(app.submissions) == 1
        argv, kwargs = app.submissions[0]
        assert argv == [
            "sase",
            "artifact",
            "prune-runs",
            "--apply",
            "--snapshot",
            "0123456789abcdef",
            "--notify",
            "--json",
        ]
        assert kwargs["operation"] == "artifact.prune-runs"
        assert kwargs["request"] == {"snapshot": "0123456789abcdef"}
        assert kwargs["request_fingerprint"].startswith("sha256:")
        assert kwargs["concurrency_keys"] == ("artifact-run-prune",)
        assert kwargs["duplicate_message"] == "ACE run pruning is already running"
        assert kwargs["notify_on_complete"] is False
        assert app.notifications == [
            (
                "🧹 Moving 1 ACE run to trash — re-verifying protections first",
                "information",
            )
        ]


@pytest.mark.parametrize(
    ("review_blocked", "snapshot_exists", "projection", "expected"),
    [
        (True, True, None, "BLOCKED"),
        (False, False, None, "SNAPSHOT_MISSING"),
        (False, True, "running", "RUNNING"),
    ],
)
async def test_non_ready_states_never_submit(
    monkeypatch: pytest.MonkeyPatch,
    review_blocked: bool,
    snapshot_exists: bool,
    projection: str | None,
    expected: str,
) -> None:
    monkeypatch.setattr(
        "sase.core.agent_artifact_run_prune_review.load_snapshot",
        lambda _fingerprint: (
            _snapshot(_review(blocked=review_blocked)) if snapshot_exists else None
        ),
    )
    monkeypatch.setattr(
        "sase.project_display_names.cached_project_display_snapshot",
        lambda: {},
    )
    modal = ArtifactRunPruneModal(_review(blocked=review_blocked), _notification())
    app = _PilotApp(modal)
    if projection == "running":
        app._proc_projection = SimpleNamespace(scope_conflict=lambda _scopes: object())

    async with app.run_test(size=(100, 32)) as pilot:
        await wait_for(pilot, lambda: modal._view.state == expected)
        assert modal._view.state == expected

        await pilot.press("y")

        assert app.submissions == []


async def test_snapshot_that_no_longer_matches_preview_cannot_be_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = _review()
    snapshot = _snapshot(review)
    monkeypatch.setattr(
        "sase.core.agent_artifact_run_prune_review.load_snapshot",
        lambda _fingerprint: RunPruneSnapshot(
            fingerprint=snapshot.fingerprint,
            captured_at=snapshot.captured_at,
            keep_recent_months=snapshot.keep_recent_months,
            items=(),
            empty_shard_count=snapshot.empty_shard_count,
            sources_unavailable=snapshot.sources_unavailable,
        ),
    )
    monkeypatch.setattr(
        "sase.project_display_names.cached_project_display_snapshot",
        lambda: {"project-key": "Pretty Project"},
    )
    modal = ArtifactRunPruneModal(review, _notification())
    app = _PilotApp(modal)

    async with app.run_test(size=(100, 32)) as pilot:
        await _wait_ready(pilot, modal)
        assert modal._view.state == "SNAPSHOT_MISSING"
        await pilot.press("y")
        assert app.submissions == []


async def test_report_opens_on_top_and_returns_to_review(
    ready_snapshot: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = NotificationReport(
        document={"title": "Prune report", "blocks": []},
        source="snapshot",
        title="Prune report",
        path=None,
        updated_at=None,
        error=None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.artifact_run_prune_modal.load_notification_report",
        lambda _notification: report,
    )
    modal = ArtifactRunPruneModal(_review(), _notification())
    app = _PilotApp(modal)

    async with app.run_test(size=(100, 32)) as pilot:
        await _wait_ready(pilot, modal)
        await pilot.press("r")
        assert isinstance(app.screen, ReportModal)

        await pilot.press("escape")
        assert app.screen is modal


@pytest.mark.parametrize("key", ["n", "escape", "q"])
async def test_cancel_keys_never_submit(key: str, ready_snapshot: None) -> None:
    modal = ArtifactRunPruneModal(_review(), _notification())
    app = _PilotApp(modal)

    async with app.run_test(size=(100, 32)) as pilot:
        await _wait_ready(pilot, modal)
        await pilot.press(key)
        assert app.submissions == []


async def test_duplicate_projection_warns_and_disables_confirmation(
    ready_snapshot: None,
) -> None:
    modal = ArtifactRunPruneModal(_review(), _notification())
    app = _PilotApp(modal)

    async with app.run_test(size=(100, 32)) as pilot:
        await _wait_ready(pilot, modal)
        app._proc_projection = SimpleNamespace(scope_conflict=lambda _scopes: object())
        await pilot.press("y")

        assert app.submissions == []
        assert modal._view.state == "RUNNING"
        assert app.notifications == [("ACE run pruning is already running", "warning")]


async def test_completion_reports_success_and_failure() -> None:
    modal = ArtifactRunPruneModal(_review(), _notification())
    app = _PilotApp(modal)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        modal._on_complete(
            SimpleNamespace(
                success=True,
                message="ok",
                payload={
                    "quarantined": 1,
                    "bytes": 2048,
                    "kept": 2,
                    "restorable_until": "2026-11-19T12:00:00+00:00",
                },
            )
        )
        modal._on_complete(
            SimpleNamespace(
                success=False,
                message="blocked",
                error=None,
                payload={"blocked_reason": "protection_unavailable"},
            )
        )

        assert app.notifications == [
            (
                "🧹 Moved 1 ACE run to trash · 2.0 KiB · restorable until Nov 19 · 2 kept",
                "information",
            ),
            (
                "🧹 Preview kept; protection_unavailable. See the proc log.",
                "error",
            ),
        ]
        assert app.refreshed == 2
