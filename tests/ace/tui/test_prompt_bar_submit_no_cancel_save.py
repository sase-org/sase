"""Regression tests for sase-3q.2: successful submit must not write cancelled.

The bug: on successful prompt submit the launch path ran the prompt bar
through the cancel safety net (``_save_bar_text_as_cancelled``), which
serialized a ``cancelled=True`` history write that races with — and on
the older single-threaded path actually preceded — the final non-cancelled
write the launch worker emits.

The fix splits unmount into two paths:

- ``_unmount_prompt_bar`` — cancel/dismiss safety net (still saves).
- ``_unmount_prompt_bar_after_submit`` — successful submit (no save).

These tests pin the contract so a future refactor can't quietly route
the submit path back through the cancel save.
"""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.actions.agent_workflow._prompt_bar_mount import (
    PromptBarMountMixin,
)
from sase.ace.tui.actions.agent_workflow._types import PromptContext

from tests.ace.tui._agent_launch_helpers import _FakeApp


def _ctx() -> PromptContext:
    return PromptContext(
        project_name="proj",
        cl_name="cl",
        project_file="/tmp/proj.sase",
        workspace_dir="/tmp/ws",
        workspace_num=1,
        workflow_name="ace(run)-ts",
        timestamp="ts",
        history_sort_key="branch",
        display_name="proj",
        update_target="",
        is_home_mode=False,
    )


def test_finish_agent_launch_uses_submit_unmount_not_cancel_path() -> None:
    """Successful ``_finish_agent_launch`` must route through the no-save unmount."""
    app = _FakeApp()

    app._finish_agent_launch("real prompt")

    assert app.unmount_calls == ["submit"]


def test_finish_agent_launch_does_not_write_cancelled_history() -> None:
    """No ``add_or_update_prompt(..., cancelled=True)`` on the submit path."""
    app = _FakeApp()

    with patch("sase.history.prompt.add_or_update_prompt") as add_or_update:
        app._finish_agent_launch("real prompt")

    cancelled_writes = [
        call for call in add_or_update.call_args_list if call.kwargs.get("cancelled")
    ]
    assert cancelled_writes == []


class _MountHarness(PromptBarMountMixin):
    """Drive the unmount methods without a live Textual DOM."""

    def __init__(
        self, bar: object | None, *, saved_text: str = "stored prompt"
    ) -> None:
        self._prompt_context: PromptContext | None = _ctx()
        self._bar = bar
        self._saved_text = saved_text
        self.detached: list[object] = []
        self.save_called_with: list[object] = []

    def query_one(self, selector: str, _cls: object | None = None) -> object:
        del selector, _cls
        if self._bar is None:
            raise RuntimeError("no bar mounted")
        return self._bar

    def _save_bar_text_as_cancelled(self, bar: object) -> str:  # type: ignore[override]
        self.save_called_with.append(bar)
        return self._saved_text

    def _detach_prompt_bar(self, bar: object) -> None:  # type: ignore[override]
        self.detached.append(bar)


def test_unmount_after_submit_skips_cancel_save_and_detaches() -> None:
    """The submit unmount detaches the bar but does NOT save as cancelled."""
    bar = object()
    harness = _MountHarness(bar)

    harness._unmount_prompt_bar_after_submit()

    assert harness.save_called_with == []
    assert harness.detached == [bar]


def test_cancel_unmount_still_saves_text_as_cancelled() -> None:
    """The cancel/dismiss path must still call the safety-net save."""
    bar = object()
    harness = _MountHarness(bar)

    stored = harness._unmount_prompt_bar()

    assert harness.save_called_with == [bar]
    assert harness.detached == [bar]
    assert stored == "stored prompt"


def test_unmount_after_submit_is_noop_when_no_bar_mounted() -> None:
    """Missing bar must not raise — same contract as cancel-path unmount."""
    harness = _MountHarness(bar=None)

    harness._unmount_prompt_bar_after_submit()

    assert harness.save_called_with == []
    assert harness.detached == []


class _Bar:
    def __init__(self, text: str) -> None:
        self._text = text

    def current_prompt_text(self) -> str:
        return self._text


class _RealSaveHarness(PromptBarMountMixin):
    def __init__(self, bar: object | None) -> None:
        self._prompt_context: PromptContext | None = _ctx()
        self._bar = bar
        self.detached: list[object] = []

    def query_one(self, selector: str, _cls: object | None = None) -> object:
        del selector, _cls
        if self._bar is None:
            raise RuntimeError("no bar mounted")
        return self._bar

    def _detach_prompt_bar(self, bar: object) -> None:  # type: ignore[override]
        self.detached.append(bar)


def test_save_text_as_cancelled_returns_recorded_text() -> None:
    harness = _RealSaveHarness(bar=None)

    with (
        patch("sase.history.prompt.add_or_update_prompt") as add_or_update,
        patch(
            "sase.history.file_references.extract_recordable_file_refs",
            return_value=[],
        ),
    ):
        stored = harness._save_text_as_cancelled("  fix the bug  ")

    assert stored == "fix the bug"
    add_or_update.assert_called_once_with("fix the bug", cancelled=True)


def test_save_text_as_cancelled_returns_empty_for_unrecordable_text() -> None:
    harness = _RealSaveHarness(bar=None)

    with (
        patch("sase.history.prompt.add_or_update_prompt") as add_or_update,
        patch(
            "sase.history.file_references.extract_recordable_file_refs",
            return_value=[],
        ),
    ):
        empty = harness._save_text_as_cancelled("  \n\t  ")
        short = harness._save_text_as_cancelled("#gh:sase")

    assert empty == ""
    assert short == ""
    add_or_update.assert_called_once_with("#gh:sase", cancelled=True)


def test_save_bar_text_as_cancelled_propagates_recorded_text() -> None:
    harness = _RealSaveHarness(bar=None)

    with (
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.history.file_references.extract_recordable_file_refs",
            return_value=[],
        ),
    ):
        stored = harness._save_bar_text_as_cancelled(_Bar("fix the bug"))

    assert stored == "fix the bug"


def test_unmount_prompt_bar_propagates_recorded_text() -> None:
    bar = _Bar("fix the bug")
    harness = _RealSaveHarness(bar)

    with (
        patch("sase.history.prompt.add_or_update_prompt"),
        patch(
            "sase.history.file_references.extract_recordable_file_refs",
            return_value=[],
        ),
    ):
        stored = harness._unmount_prompt_bar()

    assert stored == "fix the bug"
    assert harness.detached == [bar]
