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


def _preview(*, plan_path: str | None = "/tmp/plan.md") -> BeadPreview:
    issue = Issue(
        id="sase-1aa",
        title="Epic title",
        status=Status.IN_PROGRESS,
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        description="Epic body",
    )
    return BeadPreview(
        issue=issue,
        ancestors=(),
        children=(),
        depends_on=(),
        blocks=(),
        store=_store(),
        plan_reference="plan.md",
        plan_source="self",
        plan_path=plan_path,
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
