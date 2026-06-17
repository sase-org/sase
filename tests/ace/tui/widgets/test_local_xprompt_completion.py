"""Local-xprompt completion parity for the prompt input bar (Phase 4).

A ``#_helper`` declared in the Frontmatter Panel's ``xprompts:`` field must light
up ``<ctrl+t>`` / ``<ctrl+l>`` completion and argument hints in every prompt pane
exactly like a global xprompt.  These tests cover the pure conversion + merge
helpers, the bar's live ``local_xprompt_assist_entries`` source, and the pane-level
injection into the completion-candidate and argument-assist surfaces.
"""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    detect_xprompt_arg_hint_at_cursor,
    merge_local_xprompt_entries,
    xprompt_assist_entry_from_local_xprompt,
)
from sase.xprompt.models import InputArg, InputType, XPrompt
from sase.xprompt.prompt_frontmatter import LOCAL_XPROMPT_SOURCE


class _PromptBarApp(App[None]):
    """Minimal app hosting a single prompt input bar with frontmatter."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str = "") -> None:
        super().__init__()
        self._initial_value = initial_value

    def compose(self) -> ComposeResult:
        yield PromptInputBar(initial_value=self._initial_value, id="prompt-input-bar")


def _global_entry(name: str, *, description: str | None = None) -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name=name,
        insertion=f"#{name}",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(),
        content_preview=None,
        description=description,
    )


# --- pure conversion + merge ----------------------------------------------


def test_local_xprompt_entry_mirrors_global_shape() -> None:
    """A simple local helper becomes a ``#``-prefixed entry with its inputs."""
    xprompt = XPrompt(
        name="_rules",
        content="Follow the team review checklist",
        source_path=LOCAL_XPROMPT_SOURCE,
        description="team rules",
        inputs=[
            InputArg(name="service", type=InputType.WORD),
            InputArg(name="dry_run", type=InputType.BOOL, default=False),
        ],
    )
    entry = xprompt_assist_entry_from_local_xprompt("_rules", xprompt)

    assert entry.name == "_rules"
    assert entry.insertion == "#_rules"
    assert entry.reference_prefix == "#"
    assert entry.description == "team rules"
    assert entry.content_preview == "Follow the team review checklist"
    assert [(inp.name, inp.type, inp.required) for inp in entry.inputs] == [
        ("service", "word", True),
        ("dry_run", "bool", False),
    ]


def test_local_xprompt_entry_uses_inline_marker_for_segments() -> None:
    """A helper whose body carries ``---`` segments still inserts as ``#``."""
    xprompt = XPrompt(
        name="_multi",
        content="first agent\n---\nsecond agent",
        source_path=LOCAL_XPROMPT_SOURCE,
    )
    entry = xprompt_assist_entry_from_local_xprompt("_multi", xprompt)

    assert entry.reference_prefix == "#"
    assert entry.insertion == "#_multi"


def test_merge_is_additive_and_local_wins_on_collision() -> None:
    """Local entries append; on a name clash the live local definition wins."""
    base = [_global_entry("commit"), _global_entry("_rules", description="STALE")]
    local = [_global_entry("_rules", description="LIVE")]

    merged = merge_local_xprompt_entries(base, local)

    assert [e.name for e in merged] == ["commit", "_rules"]
    # The live local entry replaces the stale global of the same name, and lands
    # last so by-name resolvers select it.
    assert merged[-1].description == "LIVE"


def test_merge_empty_local_returns_base_unchanged() -> None:
    base = [_global_entry("commit")]
    assert merge_local_xprompt_entries(base, []) is base


# --- bar: live local entries ----------------------------------------------


async def test_bar_exposes_live_local_xprompt_entries() -> None:
    """The bar surfaces local xprompts parsed from its live frontmatter string."""
    app = _PromptBarApp("body")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar._stack.frontmatter = "---\nxprompts:\n  _rules: Follow the checklist\n---"

        entries = bar.local_xprompt_assist_entries()
        assert [e.name for e in entries] == ["_rules"]
        assert entries[0].insertion == "#_rules"


async def test_bar_local_entries_track_frontmatter_edits() -> None:
    """Editing the frontmatter invalidates the cache so completion stays live."""
    app = _PromptBarApp("body")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        assert bar.local_xprompt_assist_entries() == []

        bar._stack.frontmatter = "---\nxprompts:\n  _helper: do the thing\n---"
        assert [e.name for e in bar.local_xprompt_assist_entries()] == ["_helper"]

        bar._stack.frontmatter = (
            "---\nxprompts:\n  _helper: do the thing\n  _other: another\n---"
        )
        assert [e.name for e in bar.local_xprompt_assist_entries()] == [
            "_helper",
            "_other",
        ]


async def test_bar_local_entries_empty_for_invalid_frontmatter() -> None:
    """A non-underscore local name yields no entries rather than raising."""
    app = _PromptBarApp("body")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        bar._stack.frontmatter = "---\nxprompts:\n  bad: missing underscore\n---"
        assert bar.local_xprompt_assist_entries() == []


# --- pane: <ctrl+t> completion + arg assist --------------------------------


async def test_pane_ctrl_t_completion_lists_local_helper() -> None:
    """``<ctrl+t>`` candidates include the local helper alongside globals."""
    app = _PromptBarApp("body")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar._stack.frontmatter = "---\nxprompts:\n  _rules: Follow the checklist\n---"
        pane = app.query_one(PromptTextArea)
        # Seed the warm project catalog so the merge takes the deterministic fast
        # path rather than building the real global catalog.
        pane._xprompt_arg_assist_entries_by_project[None] = [_global_entry("commit")]

        candidates, _shared = pane._build_xprompt_completion_candidates("#_")
        assert [c.insertion for c in candidates] == ["#_rules"]

        candidates, _shared = pane._build_xprompt_completion_candidates("#")
        names = {c.name for c in candidates}
        assert {"commit", "_rules"} <= names


async def test_pane_ctrl_t_local_overrides_stale_global() -> None:
    """A live local helper wins over a same-named global in ``<ctrl+t>``."""
    app = _PromptBarApp("body")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar._stack.frontmatter = "---\nxprompts:\n  _rules: live body\n---"
        pane = app.query_one(PromptTextArea)
        pane._xprompt_arg_assist_entries_by_project[None] = [
            _global_entry("_rules", description="STALE")
        ]

        candidates, _shared = pane._build_xprompt_completion_candidates("#_rules")
        assert len(candidates) == 1
        # The metadata carried into completion is the live local entry.
        metadata = candidates[0].metadata
        assert isinstance(metadata, XPromptAssistEntry)
        assert metadata.content_preview == "live body"


async def test_pane_arg_assist_entries_include_local_with_inputs() -> None:
    """Local helpers with inputs reach the argument-hint resolver in each pane."""
    frontmatter = (
        "---\n"
        "xprompts:\n"
        "  _svc:\n"
        "    content: refactor the service\n"
        "    input:\n"
        "      target: word\n"
        "---"
    )
    app = _PromptBarApp("body")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar._stack.frontmatter = frontmatter
        pane = app.query_one(PromptTextArea)
        pane._xprompt_arg_assist_entries_by_project[None] = [_global_entry("commit")]

        entries = pane._get_xprompt_arg_assist_entries()
        by_name = {e.name: e for e in entries}
        assert "_svc" in by_name
        assert [inp.name for inp in by_name["_svc"].inputs] == ["target"]

        # The merged entries drive real argument-hint detection for ``#_svc(``.
        text = "#_svc("
        hint = detect_xprompt_arg_hint_at_cursor(text, len(text), entries)
        assert hint is not None
        assert hint.entry.name == "_svc"
