"""Review-stage generation, rejection, and confirmability guards."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import Button

from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.modals.new_project_review import NewProjectReview
from sase.ace.tui.proc_observer import ObservedProc
from sase.core.time import local_now
from tests.ace.tui.modals.test_new_project_configure_review import _document


class _ReviewApp(App[None]):
    CSS_PATH = Path(__file__).parents[4] / "src/sase/ace/tui/styles.tcss"
    ENABLE_COMMAND_PALETTE = False

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[Any, dict[str, Any]]] = []
        self.submit_handle: ObservedProc | None = ObservedProc(
            proc_id="check-1",
            proc_type="project-add-check",
            cl_name="",
            project_file="",
            status="running",
            message="running",
            started_at=local_now(),
        )

    def compose(self) -> ComposeResult:
        yield NewProjectReview()

    def _submit_session_worker(self, proc_type: str, body: Any, **kwargs: Any) -> Any:
        self.calls.append((proc_type, kwargs))
        return self.submit_handle


def _completion(
    payload: dict[str, Any] | None,
    *,
    success: bool = True,
    message: str = "ok",
) -> TrackedProcCompletion[dict[str, Any]]:
    return TrackedProcCompletion(
        proc_info=ObservedProc(
            proc_id="check-1",
            proc_type="project-add-check",
            cl_name="",
            project_file="",
            status="success" if success else "error",
            message=message,
            started_at=local_now(),
        ),
        success=success,
        message=message,
        output="",
        payload=payload,
    )


async def test_stale_check_completion_does_not_enable_confirm() -> None:
    app = _ReviewApp()
    async with app.run_test(size=(120, 40)):
        review = app.query_one(NewProjectReview)
        newest = _document("newest")
        obsolete = _document("obsolete")
        obsolete["intent_fingerprint"] = "b" * 64
        review.start_check(obsolete)
        first = app.calls[-1][1]["on_complete"]
        review.start_check(newest)
        second = app.calls[-1][1]["on_complete"]
        first(_completion(obsolete))
        confirm = review.query_one("#new-project-review-confirm", Button)
        assert confirm.disabled
        second(_completion(newest))
        assert not confirm.disabled
        assert review._document["apply_argv"] == newest["apply_argv"]


async def test_rejected_submit_clears_loading() -> None:
    app = _ReviewApp()
    app.submit_handle = None
    async with app.run_test(size=(120, 40)):
        review = app.query_one(NewProjectReview)
        review.start_check(_document())
        assert review._loading is False
        assert review._view is None
        assert review.query_one("#new-project-review-confirm", Button).disabled
        state = review.query_one("#new-project-review-state").render().plain
        assert "already being checked" in state


async def test_error_after_valid_view_disables_confirm() -> None:
    app = _ReviewApp()
    async with app.run_test(size=(120, 40)):
        review = app.query_one(NewProjectReview)
        review.show_document(_document())
        assert not review.query_one("#new-project-review-confirm", Button).disabled
        review.set_error("check failed")
        assert review._view is None
        assert review.query_one("#new-project-review-confirm", Button).disabled


async def test_back_invalidates_in_flight_check() -> None:
    app = _ReviewApp()
    async with app.run_test(size=(120, 40)):
        review = app.query_one(NewProjectReview)
        review.start_check(_document())
        complete = app.calls[-1][1]["on_complete"]
        review.invalidate_check()
        complete(_completion(_document()))
        assert review._view is None
        assert review.query_one("#new-project-review-confirm", Button).disabled


async def test_dedup_key_includes_intent_fingerprint() -> None:
    app = _ReviewApp()
    async with app.run_test(size=(120, 40)):
        review = app.query_one(NewProjectReview)
        document = _document("renamed")
        review.start_check(document)
        _proc_type, kwargs = app.calls[-1]
        assert _proc_type == "project-add-check"
        assert kwargs["dedup_key"] == (
            "project-add-check:github.com/sase-org/new:" + "a" * 64
        )


async def test_create_check_uses_create_proc_type() -> None:
    app = _ReviewApp()
    async with app.run_test(size=(120, 40)):
        review = app.query_one(NewProjectReview)
        document = _document()
        document["mode"] = "create"
        document["apply_argv"] = [
            "sase",
            "project",
            "create",
            "sase-org/new",
            "--visibility",
            "private",
            "--yes",
            "--json",
        ]
        review.start_check(document)
        proc_type, kwargs = app.calls[-1]
        assert proc_type == "project-create-check"
        assert kwargs["dedup_key"] == (
            "project-create-check:github.com/sase-org/new:" + "a" * 64
        )
        assert kwargs["duplicate_message"] == (
            "This project create plan is already being checked."
        )


async def test_resume_notice_is_amber_not_error() -> None:
    app = _ReviewApp()
    async with app.run_test(size=(120, 40)):
        review = app.query_one(NewProjectReview)
        review.show_document(
            _document(),
            notice="Previous add choices were not recovered. Review this plan before applying.",
        )
        state = review.query_one("#new-project-review-state").render().plain
        assert "not recovered" in state
        assert not review.query_one("#new-project-review-confirm", Button).disabled
