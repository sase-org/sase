"""Display-fixes coverage: tag-catalog warm refresh and editor re-highlight."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from textual.worker import WorkerState

from sase.ace.tui.actions._startup_loads import StartupLoadsMixin
from sase.ace.tui.project_tag_messages import ProjectTagCatalogWarmed
from sase.ace.tui.widgets._file_completion_workers import FileCompletionWorkerMixin


class _WorkerWidget(FileCompletionWorkerMixin):
    """Minimal widget surface for worker-result routing tests."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.posted: list[object] = []
        self.super_calls: list[str] = []

    def _build_highlight_map(self) -> None:
        self.calls.append("highlight")

    def refresh(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self.calls.append("refresh")

    def post_message(self, message: object) -> None:
        self.posted.append(message)


def _catalog_worker_event(state: WorkerState) -> SimpleNamespace:
    return SimpleNamespace(
        worker=SimpleNamespace(group="prompt-vcs-project-catalog"),
        state=state,
    )


def test_catalog_worker_success_rehighlights_editor_and_announces() -> None:
    """The prompt editor rebuilds highlights when the catalog worker lands."""
    widget = _WorkerWidget()

    FileCompletionWorkerMixin.on_worker_state_changed(
        widget, _catalog_worker_event(WorkerState.SUCCESS)
    )

    assert widget.calls == ["highlight", "refresh"]
    assert len(widget.posted) == 1
    assert isinstance(widget.posted[0], ProjectTagCatalogWarmed)


def test_catalog_worker_error_leaves_editor_alone() -> None:
    """A failed catalog worker does not repaint or announce warmth."""
    widget = _WorkerWidget()

    FileCompletionWorkerMixin.on_worker_state_changed(
        widget, _catalog_worker_event(WorkerState.ERROR)
    )

    assert widget.calls == []
    assert widget.posted == []


def test_warmed_message_refreshes_once_per_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cold-surface repaints coalesce per catalog signature."""
    import sase.project_tags as project_tags

    monkeypatch.setattr(
        project_tags, "peek_project_tag_catalog_signature", lambda: "sig-1"
    )
    refreshes: list[str] = []
    fake = SimpleNamespace(refresh=lambda: refreshes.append("refresh"))

    StartupLoadsMixin.on_project_tag_catalog_warmed(fake, ProjectTagCatalogWarmed())
    StartupLoadsMixin.on_project_tag_catalog_warmed(fake, ProjectTagCatalogWarmed())

    assert refreshes == ["refresh"]
    assert fake._project_tag_warm_refresh_signature == "sig-1"

    monkeypatch.setattr(
        project_tags, "peek_project_tag_catalog_signature", lambda: "sig-2"
    )
    StartupLoadsMixin.on_project_tag_catalog_warmed(fake, ProjectTagCatalogWarmed())

    assert refreshes == ["refresh", "refresh"]
