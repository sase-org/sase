"""Pilot coverage for the ACE-run prune review modal."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from sase.ace.testing.wait import wait_for
from sase.ace.tui.modals._artifact_run_prune_recheck import _on_recheck_complete
from sase.ace.tui.modals.artifact_run_prune_modal import ArtifactRunPruneModal
from sase.ace.tui.modals.report_modal import ReportModal
from sase.ops.names import ARTIFACT_PRUNE_RUNS, ARTIFACT_PRUNE_RUNS_PREVIEW
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
        move = modal.query_one("#prune-review-move", Button)
        assert str(move.label) == "🧹 Move 1 run to trash"
        assert move.disabled is False
        assert move.variant == "warning"
        assert (
            modal.query_one("#prune-review-footer", Static).render().plain
            == "y move to trash · r full report · n/esc cancel"
        )

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
        assert kwargs["operation"] == ARTIFACT_PRUNE_RUNS
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


def _patch_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    *,
    review: RunPruneReview,
    snapshot_exists: bool = True,
) -> None:
    monkeypatch.setattr(
        "sase.core.agent_artifact_run_prune_review.load_snapshot",
        lambda _fingerprint: _snapshot(review) if snapshot_exists else None,
    )
    monkeypatch.setattr(
        "sase.project_display_names.cached_project_display_snapshot",
        lambda: {},
    )


def _assert_recheck_submission(app: _PilotApp) -> None:
    assert len(app.submissions) == 1
    argv, kwargs = app.submissions[0]
    assert argv == [
        "sase",
        "artifact",
        "prune-runs",
        "--publish-preview",
        "--json",
    ]
    assert kwargs["operation"] == ARTIFACT_PRUNE_RUNS_PREVIEW
    assert "nonce" in kwargs["request"]
    assert kwargs["request_fingerprint"].startswith("sha256:")
    assert kwargs["concurrency_keys"] == ("artifact-run-prune",)
    assert kwargs["label"] == "Re-check ACE run prune"
    assert kwargs["display_name"] == "Re-check ACE run prune"
    assert kwargs["duplicate_message"] == "ACE run pruning is already running"
    assert kwargs["reload_on_complete"] is False
    assert kwargs["notify_on_complete"] is False
    assert app.notifications == [
        ("↻ Re-checking ACE run prune protections…", "information")
    ]


async def test_blocked_confirm_submits_recheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = _review(blocked=True)
    _patch_snapshot(monkeypatch, review=review)
    modal = ArtifactRunPruneModal(review, _notification())
    app = _PilotApp(modal)

    async with app.run_test(size=(100, 32)) as pilot:
        await wait_for(pilot, lambda: modal._view.state == "BLOCKED")
        move = modal.query_one("#prune-review-move", Button)
        assert str(move.label) == "↻ Re-check protections"
        assert move.disabled is False
        assert move.variant == "primary"
        assert (
            modal.query_one("#prune-review-footer", Static).render().plain
            == "y re-check now · r full report · n/esc cancel"
        )
        await pilot.press("y")

    _assert_recheck_submission(app)


async def test_snapshot_missing_confirm_submits_recheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = _review()
    _patch_snapshot(monkeypatch, review=review, snapshot_exists=False)
    modal = ArtifactRunPruneModal(review, _notification())
    app = _PilotApp(modal)

    async with app.run_test(size=(100, 32)) as pilot:
        await wait_for(pilot, lambda: modal._view.state == "SNAPSHOT_MISSING")
        move = modal.query_one("#prune-review-move", Button)
        assert str(move.label) == "↻ Refresh preview"
        assert move.disabled is False
        assert move.variant == "primary"
        assert (
            modal.query_one("#prune-review-footer", Static).render().plain
            == "y re-check now · r full report · n/esc cancel"
        )
        await pilot.press("y")

    _assert_recheck_submission(app)


async def test_snapshot_that_no_longer_matches_preview_submits_recheck(
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

    _assert_recheck_submission(app)


async def test_running_warns_and_does_not_submit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = _review()
    _patch_snapshot(monkeypatch, review=review)
    modal = ArtifactRunPruneModal(review, _notification())
    app = _PilotApp(modal)
    app._proc_projection = SimpleNamespace(scope_conflict=lambda _scopes: object())

    async with app.run_test(size=(100, 32)) as pilot:
        await wait_for(pilot, lambda: modal._view.state == "RUNNING")
        move = modal.query_one("#prune-review-move", Button)
        assert move.disabled is True
        assert (
            modal.query_one("#prune-review-footer", Static).render().plain
            == "r full report · n/esc cancel"
        )
        await pilot.press("y")

        assert app.submissions == []
        assert app.notifications == [("ACE run pruning is already running.", "warning")]


async def test_checking_warns_and_does_not_submit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _skip_load(_self: ArtifactRunPruneModal) -> None:
        return None

    monkeypatch.setattr(ArtifactRunPruneModal, "_load_snapshot_state", _skip_load)
    modal = ArtifactRunPruneModal(_review(), _notification())
    app = _PilotApp(modal)

    async with app.run_test(size=(100, 32)) as pilot:
        await wait_for(pilot, lambda: modal._view.state == "CHECKING")
        move = modal.query_one("#prune-review-move", Button)
        assert str(move.label) == "🧹 Move 1 run to trash"
        assert move.disabled is True
        assert (
            modal.query_one("#prune-review-footer", Static).render().plain
            == "r full report · n/esc cancel"
        )
        await pilot.press("y")

        assert app.submissions == []
        assert app.notifications == [
            ("Still checking this preview — try again in a moment.", "warning")
        ]


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


async def test_consequence_uses_configured_grace_days(
    ready_snapshot: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.config.get_artifact_retention_trash_grace_days",
        lambda: 3,
    )
    modal = ArtifactRunPruneModal(
        _review(),
        _notification(),
        now=datetime(2026, 11, 5, 11, 33, tzinfo=UTC),
    )
    app = _PilotApp(modal)

    async with app.run_test(size=(100, 32)) as pilot:
        await _wait_ready(pilot, modal)
        assert modal._grace_days == 3
        consequence = modal._consequence_text()
        assert "3 days" in consequence
        assert "14 days" not in consequence


async def test_completion_warns_on_index_errors() -> None:
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
                    "kept": 0,
                    "restorable_until": "2026-11-19T12:00:00+00:00",
                    "index_errors": ["deindex failed"],
                },
            )
        )
        assert app.notifications == [
            (
                "🧹 Moved 1 ACE run to trash · 2.0 KiB · restorable until Nov 19 · 0 kept · 1 index error(s)",
                "warning",
            )
        ]


class _RecheckHost:
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.refreshed = 0

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _refresh_notification_count(self) -> None:
        self.refreshed += 1


def test_recheck_completion_toasts_actionable_preview() -> None:
    host = _RecheckHost()
    _on_recheck_complete(
        host,
        SimpleNamespace(
            success=True,
            payload={"selected": 3, "bytes": 2048, "unavailable_count": 0},
        ),
    )
    assert host.notifications == [
        (
            "🧹 Protections re-checked — a fresh preview is ready: "
            "3 runs · 2.0 KiB. Open it from the inbox.",
            "information",
        )
    ]
    assert host.refreshed == 1


def test_recheck_completion_toasts_still_paused() -> None:
    host = _RecheckHost()
    _on_recheck_complete(
        host,
        SimpleNamespace(
            success=True,
            payload={
                "selected": 0,
                "bytes": 0,
                "unavailable_count": 2,
                "unavailable_sources": ["body:beads", "body:plans"],
            },
        ),
    )
    assert host.notifications == [
        (
            "🧹 Still paused: 2 protection sources are unreadable "
            "(body:beads). See the proc log.",
            "error",
        )
    ]
    assert host.refreshed == 1


def test_recheck_completion_toasts_nothing_to_prune() -> None:
    host = _RecheckHost()
    _on_recheck_complete(
        host,
        SimpleNamespace(
            success=True,
            payload={"selected": 0, "bytes": 0, "unavailable_count": 0},
        ),
    )
    assert host.notifications == [
        ("🧹 Protections re-checked — nothing to prune.", "information")
    ]
    assert host.refreshed == 1


def test_recheck_completion_toasts_proc_failure() -> None:
    host = _RecheckHost()
    _on_recheck_complete(
        host,
        SimpleNamespace(success=False, error="boom", message=None, payload=None),
    )
    assert host.notifications == [
        ("🧹 Re-check failed: boom. See the proc log.", "error")
    ]
    assert host.refreshed == 1
