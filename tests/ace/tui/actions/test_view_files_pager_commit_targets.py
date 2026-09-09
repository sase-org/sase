"""Tests for commit attached-target actions in the view-file pager."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from sase.ace.tui.actions.hints._files import _handle_commit_attached_target
from sase.ace.tui.modals.commit_view_modal import CommitViewModal

from ._view_files_helpers import _commit_spec
from ._view_files_pager_helpers import _FakeScreen, _target


def test_commit_attached_target_copy_copies_the_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screen = _FakeScreen()
    spec = _commit_spec(sha="abcdef1234567890")
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._files.schedule_copy_delivery",
        lambda owner, value, **kwargs: calls.append((owner, value, kwargs)),
    )

    _handle_commit_attached_target(screen, _target(spec), "copy")  # type: ignore[arg-type]

    assert calls == [
        (
            screen,
            spec.sha,
            {"copied_label": "commit SHA", "task_name": "sase-pager-copy-commit"},
        )
    ]


def test_commit_attached_target_edit_opens_editor_with_diff_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    screen = _FakeScreen()
    diff_path = tmp_path / "commit.diff"
    spec = _commit_spec(diff_path=str(diff_path))
    run_calls: list[list[str]] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._files.subprocess.run",
        lambda argv, **kwargs: run_calls.append(list(argv)),
    )
    monkeypatch.setenv("EDITOR", "nvim")

    @contextmanager
    def fake_suspend(_app: object, **_metadata: object):
        yield

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._files.suspend_for_external_tool", fake_suspend
    )

    _handle_commit_attached_target(screen, _target(spec), "edit")  # type: ignore[arg-type]

    assert run_calls == [["nvim", str(diff_path)]]


def test_commit_attached_target_edit_without_diff_path_warns() -> None:
    screen = _FakeScreen()
    spec = _commit_spec()

    _handle_commit_attached_target(screen, _target(spec), "edit")  # type: ignore[arg-type]

    screen.notify.assert_called_once()
    assert "No raw diff path" in screen.notify.call_args.args[0]


def test_commit_attached_target_follow_opens_commit_view_modal() -> None:
    screen = _FakeScreen()
    spec = _commit_spec()

    _handle_commit_attached_target(screen, _target(spec), "follow")  # type: ignore[arg-type]

    screen.app.push_screen.assert_called_once()
    modal = screen.app.push_screen.call_args.args[0]
    assert isinstance(modal, CommitViewModal)
    assert modal._commit_specs == (spec,)
