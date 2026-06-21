"""Tests for the ``#@`` xprompt-selector request handling from the prompt bar.

Phase 1 makes the selector act on the exact pane that opened it: the
``SnippetRequested`` message carries the originating bar / text area / pane id /
trigger range, and the handler routes insertion through
``insert_snippet_at_target`` instead of re-querying the generic
``#prompt-input-bar`` after the modal closes.
"""

from __future__ import annotations

from sase.ace.tui.actions.agent_workflow._prompt_bar_requests import (
    PromptBarRequestsMixin,
)
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ace.tui.modals import XPromptSelectModal
from sase.ace.tui.modals.xprompt_select_modal import XPromptSelection
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


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


class _StubTextArea:
    """Minimal origin text area exposing only the ``text`` the handler reads."""

    def __init__(self, text: str = "") -> None:
        self.text = text


class _OriginBar(PromptInputBar):
    """Real ``PromptInputBar`` (so the handler's ``isinstance`` guard accepts it).

    Only the methods the handler calls on the origin are overridden so the test
    can record the targeted insertion and simulate a stale target.
    """

    def __init__(self, *, inserted: bool = True) -> None:
        super().__init__()
        self._inserted = inserted
        self.insert_calls: list[tuple[object, str, object, str, object]] = []

    def insert_snippet_at_target(  # type: ignore[override]
        self,
        target_text_area: object,
        pane_id: str,
        trigger_range: object,
        snippet_name: str,
        entry: object = None,
    ) -> bool:
        self.insert_calls.append(
            (target_text_area, pane_id, trigger_range, snippet_name, entry)
        )
        return self._inserted


class _SelectorHarness(PromptBarRequestsMixin):
    """App stand-in capturing pushed modals and notifications."""

    def __init__(self) -> None:
        self._prompt_context: PromptContext | None = _ctx()
        self.pushed: list[tuple[object, object]] = []
        self.notifications: list[tuple[str, str | None]] = []

    def push_screen(self, modal: object, callback: object) -> None:
        self.pushed.append((modal, callback))

    def notify(self, message: str, severity: str | None = None) -> None:
        self.notifications.append((message, severity))


def _event(
    origin_bar: PromptInputBar,
    origin_text_area: object,
    *,
    pane_id: str = "prompt-input-g0-p0",
    trigger_range: tuple[tuple[int, int], tuple[int, int]] = ((0, 0), (0, 1)),
) -> PromptInputBar.SnippetRequested:
    return PromptInputBar.SnippetRequested(
        origin_bar=origin_bar,
        origin_text_area=origin_text_area,  # type: ignore[arg-type]
        origin_pane_id=pane_id,
        trigger_range=trigger_range,
    )


def test_pushes_selector_modal_with_context_project() -> None:
    harness = _SelectorHarness()
    origin_bar = _OriginBar()
    harness.on_prompt_input_bar_snippet_requested(_event(origin_bar, _StubTextArea()))

    modal, _callback = harness.pushed[0]
    assert isinstance(modal, XPromptSelectModal)


def test_selection_inserts_into_captured_origin_pane() -> None:
    harness = _SelectorHarness()
    origin_bar = _OriginBar(inserted=True)
    origin_ta = _StubTextArea(text="before #")

    harness.on_prompt_input_bar_snippet_requested(
        _event(origin_bar, origin_ta, trigger_range=((0, 7), (0, 8)))
    )
    _modal, callback = harness.pushed[0]
    callback(XPromptSelection(suffix="review"))

    # The captured origin pane is targeted directly (not a re-queried bar), with
    # the captured pane id and trigger range threaded straight through.
    assert origin_bar.insert_calls == [
        (origin_ta, "prompt-input-g0-p0", ((0, 7), (0, 8)), "review", None)
    ]
    assert harness.notifications == []


def test_selection_forwards_entry_for_smart_args() -> None:
    harness = _SelectorHarness()
    origin_bar = _OriginBar(inserted=True)
    origin_ta = _StubTextArea()
    sentinel_entry = object()

    harness.on_prompt_input_bar_snippet_requested(_event(origin_bar, origin_ta))
    _modal, callback = harness.pushed[0]
    callback(XPromptSelection(suffix="review", entry=sentinel_entry))  # type: ignore[arg-type]

    assert origin_bar.insert_calls[0][3] == "review"
    assert origin_bar.insert_calls[0][4] is sentinel_entry


def test_plain_string_result_inserts_suffix_without_entry() -> None:
    harness = _SelectorHarness()
    origin_bar = _OriginBar(inserted=True)
    origin_ta = _StubTextArea()

    harness.on_prompt_input_bar_snippet_requested(_event(origin_bar, origin_ta))
    _modal, callback = harness.pushed[0]
    callback("review")

    assert origin_bar.insert_calls == [
        (origin_ta, "prompt-input-g0-p0", ((0, 0), (0, 1)), "review", None)
    ]


def test_stale_target_notifies_and_leaves_prompt_unchanged() -> None:
    harness = _SelectorHarness()
    origin_bar = _OriginBar(inserted=False)  # origin pane gone before selection

    harness.on_prompt_input_bar_snippet_requested(_event(origin_bar, _StubTextArea()))
    _modal, callback = harness.pushed[0]
    callback(XPromptSelection(suffix="review"))

    assert len(origin_bar.insert_calls) == 1  # attempted exactly once
    assert harness.notifications == [
        ("Prompt pane is no longer available - selection discarded", "warning")
    ]


def test_cancel_does_not_insert_or_notify() -> None:
    harness = _SelectorHarness()
    origin_bar = _OriginBar()

    harness.on_prompt_input_bar_snippet_requested(_event(origin_bar, _StubTextArea()))
    _modal, callback = harness.pushed[0]
    callback(None)

    assert origin_bar.insert_calls == []
    assert harness.notifications == []
