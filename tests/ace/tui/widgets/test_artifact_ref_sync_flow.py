"""Widget state-machine coverage for the ``@<kind>::`` ref-sync gesture."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from sase.ace.tui._proc_observer_models import ObservedProc
from sase.ace.tui.actions._proc_action_types import (
    TrackedProcCompletion,
    TrackedProcResult,
)
from sase.ace.tui.widgets._artifact_ref_sync import ArtifactRefSyncCompletionMetadata
from sase.ace.tui.widgets.artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
    _ArtifactRefDocumentCandidate,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._artifact_ref_completion_helpers import CATALOG, seed_catalog
from ._completion_helpers import CompletionTestApp

_NEW_DOC = _ArtifactRefDocumentCandidate(
    "plans", "202608/new.md", "New plan", "2026-08-01T12:00:00Z"
)


class _RefSyncApp(CompletionTestApp):
    """Records session-worker submissions instead of running a real thread."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.submitted: list[dict[str, Any]] = []
        self.toasts: list[tuple[str, str]] = []

    def _submit_session_worker(
        self,
        proc_type: str,
        body: Any,
        *,
        on_complete: Any = None,
        **kwargs: Any,
    ) -> object:
        self.submitted.append(
            {"proc_type": proc_type, "body": body, "on_complete": on_complete, **kwargs}
        )
        return object()

    def notify(self, message: str, *, severity: str = "information", **_: Any) -> None:
        self.toasts.append((message, severity))


def _place_at_empty_payload(text_area: PromptTextArea, kind: str) -> None:
    text_area.load_text(f"@{kind}:")
    text_area.cursor_location = (0, len(f"@{kind}:"))


def _complete(entry: dict[str, Any], *, success: bool) -> None:
    """Run the captured ``body`` and feed a completion into ``on_complete``."""
    result: TrackedProcResult[Any] = entry["body"]()
    completion = TrackedProcCompletion(
        proc_info=ObservedProc(
            proc_id="ref-sync-0",
            proc_type=entry["proc_type"],
            cl_name="",
            project_file="",
            status="success" if success else "failure",
            message=result.message,
            started_at=datetime.now(),
        ),
        success=result.success,
        message=result.message,
        output="",
        payload=result.payload,
        error=result.error,
    )
    entry["on_complete"](completion)


async def test_running_reloading_settled_ok_and_new_payloads() -> None:
    app = _RefSyncApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
        _place_at_empty_payload(text_area, "plans")

        rewarm_calls: list[str | None] = []

        def fake_warm() -> None:
            rewarm_calls.append(text_area._xprompt_arg_assist_project_from_text())
            grown = replace(CATALOG, documents=(*CATALOG.documents, _NEW_DOC))
            text_area._artifact_ref_completion_catalogs_by_project[None] = grown
            text_area._finish_artifact_ref_sync_reload_for_project(None)

        text_area._warm_current_artifact_ref_completion_catalog = fake_warm  # type: ignore[method-assign]

        text_area._start_artifact_ref_sync("plans")

        key = (None, "plans")
        assert text_area._artifact_ref_sync_states[key].phase == "running"
        assert text_area._file_completion_active is True
        assert text_area._completion_kind == ARTIFACT_REF_COMPLETION_KIND
        assert len(app.submitted) == 1

        _complete(app.submitted[0], success=True)

        assert rewarm_calls == [None]
        state = text_area._artifact_ref_sync_states[key]
        assert state.phase == "settled_ok"
        assert state.new_payloads == frozenset({"202608/new.md"})

        # Eviction happened exactly once and left the re-warmed catalog in place.
        assert (
            text_area._artifact_ref_completion_catalogs_by_project[None]
            .documents[-1]
            .payload
            == "202608/new.md"
        )


async def test_second_gesture_while_running_submits_nothing() -> None:
    app = _RefSyncApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
        text_area._warm_current_artifact_ref_completion_catalog = lambda: None  # type: ignore[method-assign]

        text_area._start_artifact_ref_sync("plans")
        text_area._start_artifact_ref_sync("plans")

        assert len(app.submitted) == 1


async def test_failure_yields_settled_error() -> None:
    app = _RefSyncApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)

        text_area._start_artifact_ref_sync("plans")
        entry = app.submitted[0]
        entry["body"] = lambda: TrackedProcResult(
            success=False,
            message="could not reach origin",
            error="could not reach origin",
        )

        _complete(entry, success=False)

        key = (None, "plans")
        state = text_area._artifact_ref_sync_states[key]
        assert state.phase == "settled_error"
        assert state.detail


async def test_failure_with_closed_panel_yields_one_warning_toast() -> None:
    app = _RefSyncApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)

        text_area._start_artifact_ref_sync("plans")
        entry = app.submitted[0]
        entry["body"] = lambda: TrackedProcResult(
            success=False, message="denied", error="denied"
        )
        text_area._clear_file_completion()

        _complete(entry, success=False)

        assert len(app.toasts) == 1
        assert app.toasts[0][1] == "warning"


async def test_unmounted_text_area_applies_nothing_mid_sync() -> None:
    app = _RefSyncApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)

        text_area._start_artifact_ref_sync("plans")
        entry = app.submitted[0]
        key = (None, "plans")

        text_area._is_mounted = False

        _complete(entry, success=True)

        state = text_area._artifact_ref_sync_states[key]
        assert state.phase == "running"


async def test_sync_row_is_pinned_at_index_zero_while_running() -> None:
    app = _RefSyncApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        seed_catalog(text_area, CATALOG)
        _place_at_empty_payload(text_area, "plans")

        text_area._start_artifact_ref_sync("plans")

        assert text_area._file_completion_candidates
        first = text_area._file_completion_candidates[0]
        assert isinstance(first.metadata, ArtifactRefSyncCompletionMetadata)
        assert first.metadata.phase == "running"
        assert first.metadata.kind == "plans"
