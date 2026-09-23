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
    rebuilds: list[bool] = []
    fake = SimpleNamespace(
        refresh=lambda: refreshes.append("refresh"),
        _refresh_agent_focus_detail=lambda *, render_immediate=True: rebuilds.append(
            render_immediate
        ),
        screen_stack=[],
        screen=None,
    )

    StartupLoadsMixin.on_project_tag_catalog_warmed(fake, ProjectTagCatalogWarmed())
    StartupLoadsMixin.on_project_tag_catalog_warmed(fake, ProjectTagCatalogWarmed())

    assert refreshes == ["refresh"]
    assert rebuilds == [False]
    assert fake._project_tag_warm_refresh_signature == "sig-1"

    monkeypatch.setattr(
        project_tags, "peek_project_tag_catalog_signature", lambda: "sig-2"
    )
    StartupLoadsMixin.on_project_tag_catalog_warmed(fake, ProjectTagCatalogWarmed())

    assert refreshes == ["refresh", "refresh"]
    assert rebuilds == [False, False]


async def test_warmed_message_rebuilds_cold_detail_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real app re-renders cold ``#`` detail as ``+`` once warm."""
    import sase.project_display_names as display_names
    import sase.project_tags.catalog as tag_catalog_module
    from sase.project_tags.catalog import ProjectTagCatalog, ProjectTagTarget
    from textual.app import App, ComposeResult
    from textual.widgets import Label

    monkeypatch.setattr(
        display_names,
        "_project_display_name_map_cached",
        lambda _root=None: {"sase": "sase"},
    )
    tag_catalog_module._CATALOG_CACHE = None  # noqa: SLF001

    class WarmApp(StartupLoadsMixin, App[None]):
        def __init__(self) -> None:
            super().__init__()
            self.rebuilds: list[bool] = []

        def compose(self) -> ComposeResult:
            yield Label("#gh:sase do things", id="detail")

        def _refresh_agent_focus_detail(self, *, render_immediate: bool = True) -> None:
            from sase.project_display_names import humanize_vcs_refs_in_text

            self.rebuilds.append(render_immediate)
            try:
                text = humanize_vcs_refs_in_text("#gh:sase do things")
            except Exception:
                text = "#gh:sase do things"
            try:
                self.query_one("#detail", Label).update(text)
            except Exception:
                pass

    app = WarmApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert str(app.query_one("#detail", Label).content) == "#gh:sase do things"

        catalog = ProjectTagCatalog(
            targets=(
                ProjectTagTarget(
                    key="sase",
                    name="sase",
                    tag="+sase",
                    workflow_type="gh",
                    vcs_ref="#gh:sase",
                    accent="#123456",
                ),
            ),
            accent_palette=("#123456",),
            signature=("warm-test",),
        )
        tag_catalog_module._CATALOG_CACHE = (catalog.signature, catalog)  # noqa: SLF001
        app.post_message(ProjectTagCatalogWarmed())
        await pilot.pause()
        await pilot.pause()

        assert str(app.query_one("#detail", Label).content) == "+sase do things"
        assert app.rebuilds and all(flag is False for flag in app.rebuilds)

        rebuild_count = len(app.rebuilds)
        app.post_message(ProjectTagCatalogWarmed())
        await pilot.pause()
        assert len(app.rebuilds) == rebuild_count
    tag_catalog_module._CATALOG_CACHE = None  # noqa: SLF001
