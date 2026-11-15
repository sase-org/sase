"""Behavior tests for the bead preview modal."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.testing import wait_for
from sase.ace.tui.modals.bead_preview_modal import BeadPreviewModal
from sase.ace.tui.models.bead_preview import BeadPreview, BeadStoreRef
from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.pager.document import PagerDocument, PagerSection
from sase.pager.link_scan import PagerOrigin
from sase.pager.targets import LinkResolution, LinkTarget, LinkTargetKind


class _BeadModalTestApp(App[None]):
    def __init__(self, modal: BeadPreviewModal) -> None:
        super().__init__()
        self.modal = modal

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(self.modal)


def _store() -> BeadStoreRef:
    return BeadStoreRef(
        project_key="sase",
        project_label="sase",
        beads_dir=Path("/tmp/beads"),
        primary_workspace=Path("/tmp"),
    )


def _issue(**overrides: object) -> Issue:
    values: dict[str, object] = {
        "id": "sase-1aa",
        "title": "Epic title",
        "status": Status.IN_PROGRESS,
        "issue_type": IssueType.PLAN,
        "tier": BeadTier.EPIC,
        "description": "Epic body",
    }
    values.update(overrides)
    return Issue(**values)  # type: ignore[arg-type]


def _preview(
    *,
    plan_path: str | None = "/tmp/plan.md",
    issue: Issue | None = None,
    ancestors: tuple[Issue | None, ...] = (),
    children: tuple[Issue, ...] = (),
    depends_on: tuple[Issue | None, ...] = (),
    blocks: tuple[Issue, ...] = (),
) -> BeadPreview:
    return BeadPreview(
        issue=issue or _issue(),
        ancestors=ancestors,
        children=children,
        depends_on=depends_on,
        blocks=blocks,
        store=_store(),
        plan_reference="plan.md",
        plan_source="self",
        plan_path=plan_path,
    )


def _phase_issue() -> Issue:
    return _issue(
        id="sase-1aa.1",
        title="Phase one",
        issue_type=IssueType.PHASE,
        tier=None,
        parent_id="sase-1aa",
        size="small",
        description="Phase body",
    )


def _detail_document() -> PagerDocument:
    return PagerDocument(
        sections=(
            PagerSection(
                identity="bead:sase-1aa",
                title="sase-1aa",
                kind="bead",
                body="Epic body",
            ),
        ),
        title="sase-1aa",
        origin=PagerOrigin.BEAD,
    )


async def test_preloaded_preview_skips_loading_and_lists_plan_keys() -> None:
    modal = BeadPreviewModal(_store(), "sase-1aa", preview=_preview())
    app = _BeadModalTestApp(modal)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert modal._preview is not None
        footer = modal._build_footer()
        assert "y id" in footer
        assert "Y path" in footer
        assert "o edit" in footer
        assert "Z view" in footer
        assert "r retry" not in footer
        assert "Loading" not in str(modal._build_status())


async def test_loading_then_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()
    preview = _preview()

    def load(_bead_id: str, _store: BeadStoreRef) -> BeadPreview:
        release.wait(timeout=2)
        return preview

    monkeypatch.setattr(
        "sase.ace.tui.modals.bead_preview_modal.load_bead_preview",
        load,
    )
    modal = BeadPreviewModal(_store(), "sase-1aa")
    app = _BeadModalTestApp(modal)
    async with app.run_test(size=(100, 30)) as pilot:
        await wait_for(pilot, lambda: "Loading" in str(modal._build_status()))
        assert modal._preview is None
        release.set()
        await wait_for(pilot, lambda: modal._preview is preview)
        assert "Loading" not in str(modal._build_status())
        assert modal._preview.issue.title == "Epic title"


async def test_in_card_error_and_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    preview = _preview()

    def load(_bead_id: str, _store: BeadStoreRef) -> BeadPreview:
        calls["n"] += 1
        if calls["n"] == 1:
            raise KeyError("sase-1aa")
        return preview

    monkeypatch.setattr(
        "sase.ace.tui.modals.bead_preview_modal.load_bead_preview",
        load,
    )
    modal = BeadPreviewModal(_store(), "sase-1aa")
    app = _BeadModalTestApp(modal)
    async with app.run_test(size=(100, 30)) as pilot:
        await wait_for(pilot, lambda: modal._error is not None)
        assert "r retry" in modal._build_footer()
        await pilot.press("r")
        await wait_for(pilot, lambda: modal._preview is preview)
        assert modal._error is None
        assert "r retry" not in modal._build_footer()


async def test_y_copies_id_and_plan_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[tuple[str, str]] = []

    def fake_copy(
        _widget: object,
        payload: str,
        *,
        copied_label: str,
        task_name: str,
    ) -> None:
        del task_name
        copied.append((payload, copied_label))

    monkeypatch.setattr(
        "sase.ace.tui.modals.bead_preview_modal.schedule_copy_delivery",
        fake_copy,
    )
    opened: list[str] = []
    viewed: list[str] = []

    modal = BeadPreviewModal(_store(), "sase-1aa", preview=_preview())
    monkeypatch.setattr(
        modal,
        "action_open_in_editor",
        lambda: opened.append(modal._source_action_path() or ""),
    )
    monkeypatch.setattr(
        modal,
        "action_open_in_viewer",
        lambda: viewed.append(modal._source_action_path() or ""),
    )
    app = _BeadModalTestApp(modal)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert copied == [("sase-1aa", "bead ID")]
        await pilot.press("o")
        await pilot.press("Z")
        assert opened == ["/tmp/plan.md"]
        assert viewed == ["/tmp/plan.md"]


async def test_y_copy_path_uses_plan_path(monkeypatch: pytest.MonkeyPatch) -> None:
    copied: list[str] = []

    def fake_copy(
        _widget: object,
        payload: str,
        **_kwargs: Any,
    ) -> None:
        copied.append(payload)

    monkeypatch.setattr(
        "sase.ace.tui.modals._source_file_actions.schedule_copy_delivery",
        fake_copy,
    )
    modal = BeadPreviewModal(_store(), "sase-1aa", preview=_preview())
    app = _BeadModalTestApp(modal)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("Y")
        await wait_for(pilot, lambda: bool(copied))
        assert copied == ["/tmp/plan.md"]


async def test_number_p_backspace_and_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    epic_issue = _issue()
    phase_issue = _phase_issue()
    extra = _issue(
        id="sase-1aa.2",
        title="Phase two",
        issue_type=IssueType.PHASE,
        tier=None,
        parent_id="sase-1aa",
        size="medium",
        description="Second phase",
    )
    epic = _preview(issue=epic_issue, children=(phase_issue, extra))
    phase = _preview(
        issue=phase_issue,
        ancestors=(epic_issue,),
        plan_path=None,
    )
    loaded: list[str] = []

    def load(bead_id: str, _store: BeadStoreRef) -> BeadPreview:
        loaded.append(bead_id)
        if bead_id == phase_issue.id:
            return phase
        return epic

    monkeypatch.setattr(
        "sase.ace.tui.modals.bead_preview_modal.load_bead_preview",
        load,
    )
    modal = BeadPreviewModal(_store(), "sase-1aa", preview=epic)
    app = _BeadModalTestApp(modal)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        footer = modal._build_footer()
        assert "1-2 phase" in footer
        assert "⏎ detail" in footer
        assert "p parent" not in footer

        await pilot.press("9")
        await pilot.pause()
        assert modal._bead_id == "sase-1aa"
        assert modal._preview is epic

        await pilot.press("1")
        await wait_for(pilot, lambda: modal._preview is phase)
        assert modal._bead_id == phase_issue.id
        assert "⌫ back" in modal._build_footer()
        assert "p parent" in modal._build_footer()
        assert loaded == [phase_issue.id]

        await pilot.press("p")
        await wait_for(pilot, lambda: modal._bead_id == "sase-1aa")
        await wait_for(pilot, lambda: modal._preview is epic)
        assert loaded == [phase_issue.id, "sase-1aa"]
        assert "⌫ back" in modal._build_footer()

        await pilot.press("backspace")
        await wait_for(pilot, lambda: modal._bead_id == phase_issue.id)
        assert modal._preview is phase
        assert loaded == [phase_issue.id, "sase-1aa"]

        await pilot.press("r")
        await wait_for(
            pilot, lambda: loaded == [phase_issue.id, "sase-1aa", phase_issue.id]
        )
        assert modal._preview is phase


async def test_enter_pushes_pager_and_unresolved_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _detail_document()
    resolution = LinkResolution(
        target=LinkTarget(kind=LinkTargetKind.DOCUMENT, document=document)
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.bead_preview_modal.bead_detail_link_resolution",
        lambda *_a, **_k: resolution,
    )
    pushed: list[object] = []
    modal = BeadPreviewModal(_store(), "sase-1aa", preview=_preview())
    app = _BeadModalTestApp(modal)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        original_push = app.push_screen

        def capture(screen: object, *args: object, **kwargs: object) -> object:
            pushed.append(screen)
            return original_push(screen, *args, **kwargs)

        monkeypatch.setattr(app, "push_screen", capture)
        await pilot.press("enter")
        await wait_for(pilot, lambda: bool(pushed))
        screen = pushed[0]
        assert type(screen).__name__ == "PagerScreen"

    notifications: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "sase.ace.tui.modals.bead_preview_modal.bead_detail_link_resolution",
        lambda *_a, **_k: LinkResolution(unresolved_message="bead gone"),
    )
    modal = BeadPreviewModal(_store(), "sase-1aa", preview=_preview())
    app = _BeadModalTestApp(modal)
    monkeypatch.setattr(
        app,
        "notify",
        lambda message, severity="information", **_k: notifications.append(
            (message, severity)
        ),
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await wait_for(pilot, lambda: bool(notifications))
        assert notifications == [("bead gone", "warning")]
