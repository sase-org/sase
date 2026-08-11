"""Focused mutation contracts for the "mark PR origin" TUI action."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from sase.ace.patch import Patch
from sase.ace.testing import make_patch
from sase.ace.tui.actions.status import StatusActionsMixin
from sase.ace.tui.modals import PrOriginModal


def _project_file(tmp_path: Path, name: str = "sase_feature") -> Path:
    project = tmp_path / "sase.sase"
    project.write_text(
        f"NAME: {name}\n"
        "DESCRIPTION:\n"
        "  Example\n"
        "PR: https://example.test/pull/1\n"
        "STATUS: Draft\n",
        encoding="utf-8",
    )
    return project


def test_action_mark_pr_origin_noops_without_selected_patch() -> None:
    push_screen = Mock()
    host = SimpleNamespace(
        current_tab="artifacts", patches=[], current_idx=0, push_screen=push_screen
    )

    StatusActionsMixin.action_mark_pr_origin(host)

    push_screen.assert_not_called()


def test_action_mark_pr_origin_noops_without_pr_url() -> None:
    push_screen = Mock()
    patch = make_patch(cl=None)
    host = SimpleNamespace(
        current_tab="artifacts",
        patches=[patch],
        current_idx=0,
        push_screen=push_screen,
    )

    StatusActionsMixin.action_mark_pr_origin(host)

    push_screen.assert_not_called()


def test_action_mark_pr_origin_opens_modal_for_selected_patch() -> None:
    push_screen = Mock()
    patch = make_patch(cl="https://example.test/pull/1", pr_origin="unknown")
    host = SimpleNamespace(
        current_tab="artifacts",
        patches=[patch],
        current_idx=0,
        push_screen=push_screen,
    )

    StatusActionsMixin.action_mark_pr_origin(host)

    push_screen.assert_called_once()
    modal, _on_dismiss = push_screen.call_args.args
    assert isinstance(modal, PrOriginModal)
    assert modal.current_pr_origin == "unknown"


def test_apply_pr_origin_change_persists_and_notifies(tmp_path: Path) -> None:
    project = _project_file(tmp_path)
    patch = Patch(
        name="sase_feature",
        description="Example",
        parent=None,
        pr_url="https://example.test/pull/1",
        pr_origin="unknown",
        status="Draft",
        file_path=str(project),
    )
    notify = Mock()
    reload_and_reposition = Mock()
    host = SimpleNamespace(notify=notify, _reload_and_reposition=reload_and_reposition)

    StatusActionsMixin._apply_pr_origin_change(host, patch, "external")

    assert "PR_ORIGIN: external" in project.read_text(encoding="utf-8")
    notify.assert_called_once()
    assert "external" in notify.call_args.args[0]
    reload_and_reposition.assert_called_once()
