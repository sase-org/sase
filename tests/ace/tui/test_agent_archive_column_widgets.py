"""Archive column widgets: row rendering, pulse, echo guards, and responsiveness."""

from __future__ import annotations

from datetime import UTC
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.geometry import Size

from sase.ace.tui.models.agent_archive_controller import ArchiveInboxPulse
from sase.ace.tui.models.agent_archive_list import (
    ITEM_BANNER,
    ITEM_CONTAINER,
    ITEM_LOADING,
    ITEM_MEMBER,
    ITEM_MESSAGE,
    ITEM_ROW,
    ITEM_TAIL,
    ArchiveListItem,
    archive_row_key,
)
from sase.ace.tui.models.agent_archive_view import (
    ARCHIVE_SECTION_LIST,
    ARCHIVE_SECTION_PULSE,
)
from sase.ace.tui.widgets.agents_archive import (
    ArchiveColumn,
    ArchiveList,
    ArchivePulse,
)
from sase.ace.tui.widgets.agents_archive._rows import (
    ArchiveRenderContext,
    format_archive_item,
    format_pulse,
    outcome_cell_width,
)


def _light(run: str, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "archive_key": {
            "source_username": "u",
            "source_machine": "m",
            "source_run_id": run,
        },
        "container_key": f"archive:u.m@{run}",
        "container": False,
        "member_count": 1,
        "agent_name": f"agent-{run}",
        "status": "DONE",
        "outcome": "done",
        "model": "claude-opus-4",
        "runtime_seconds": 272,
        "last_activity_at": "2026-10-10T15:30:00Z",
        "time_basis": "ended",
        "restorable": True,
    }
    row.update(extra)
    return row


def _item(row: dict[str, Any], kind: str = ITEM_ROW, **extra: Any) -> ArchiveListItem:
    return ArchiveListItem(
        archive_row_key(row) or "x",
        kind,
        True,
        banner_key="day:2026-10-10",
        row=row,
        **extra,
    )


def _style_at(text: Text, needle: str) -> str:
    start = text.plain.index(needle)
    for span in reversed(text.spans):
        if span.start <= start < span.end:
            return str(span.style)
    return str(text.style)


CTX = ArchiveRenderContext(tz=UTC, grouping="day", width=60)


# --- rendering --------------------------------------------------------------


def test_outcomes_are_past_tense_with_dim_terminal_colors() -> None:
    done = format_archive_item(_item(_light("a")), CTX)
    failed = format_archive_item(
        _item(_light("b", outcome="failed", status="FAILED")), CTX
    )

    assert "✓ done" in done.plain and "agent-a" in done.plain
    assert "✗ failed" in failed.plain
    assert "dim" in _style_at(done, "✓ done") and "5faf5f" in _style_at(done, "✓ done")
    assert "dim" in _style_at(failed, "✗ failed") and "d75f5f" in _style_at(
        failed, "✗ failed"
    )


def test_interrupted_rows_show_was_stored_status_in_stopped_violet() -> None:
    row = _light("c", outcome="interrupted", status="RUNNING")
    text = format_archive_item(_item(row), CTX)

    assert "○ WAS RUNNING" in text.plain
    assert "8787AF" in _style_at(text, "○ WAS RUNNING").upper()
    waiting = format_archive_item(
        _item(_light("d", outcome="interrupted", status="PLAN")), CTX
    )
    assert "○ WAS PLAN" in waiting.plain


def test_time_chip_uses_core_basis_and_start_only_time_is_dim_italic() -> None:
    ended = format_archive_item(_item(_light("a")), CTX)
    started = format_archive_item(
        _item(
            _light("b", time_basis="started", outcome="interrupted", status="RUNNING")
        ),
        CTX,
    )
    dismissed = format_archive_item(_item(_light("c", time_basis="dismissed")), CTX)
    missing = format_archive_item(_item(_light("d", last_activity_at=None)), CTX)

    assert ended.plain.lstrip().startswith("15:30")
    assert "italic" in _style_at(started, started.plain.strip()[:5])
    assert "italic" not in _style_at(dismissed, dismissed.plain.strip()[:5])
    assert "dim" in _style_at(dismissed, dismissed.plain.strip()[:5])
    assert missing.plain.strip().startswith("--")


def test_non_day_grouping_includes_the_date_in_the_time_chip() -> None:
    ctx = ArchiveRenderContext(tz=UTC, grouping="project", width=70)
    text = format_archive_item(_item(_light("a")), ctx)

    assert "Oct 10" in text.plain


def test_long_names_middle_truncate_and_columns_drop_model_then_runtime() -> None:
    long_name = "x" * 30 + "MIDDLE" + "y" * 30
    row = _light("a", agent_name=long_name)

    wide = format_archive_item(
        _item(row), ArchiveRenderContext(tz=UTC, width=120)
    ).plain
    assert long_name in wide and "opus" in wide and "4m32s" in wide

    # The name keeps a 16-cell floor before any column drops.
    medium = format_archive_item(
        _item(row), ArchiveRenderContext(tz=UTC, width=50)
    ).plain
    assert "…" in medium and "MIDDLE" not in medium
    assert "opus" in medium and "4m32s" in medium

    tight = format_archive_item(
        _item(row), ArchiveRenderContext(tz=UTC, width=40)
    ).plain
    assert "opus" not in tight and "4m32s" in tight  # MODEL went first

    narrow = format_archive_item(
        _item(row), ArchiveRenderContext(tz=UTC, width=34)
    ).plain
    assert "4m32s" not in narrow and "opus" not in narrow  # then RUNTIME
    assert "…" in narrow
    assert len(narrow) <= 34


def test_model_drops_before_runtime_at_intermediate_width() -> None:
    row = _light("a", agent_name="a-name-of-medium-length-here")
    both = format_archive_item(_item(row), ArchiveRenderContext(tz=UTC, width=70)).plain
    no_model = None
    for width in range(69, 30, -1):
        plain = format_archive_item(
            _item(row), ArchiveRenderContext(tz=UTC, width=width)
        ).plain
        if "opus" not in plain:
            no_model = plain
            break
    assert "opus" in both
    assert no_model is not None and "4m32s" in no_model


def test_container_rows_show_glyph_count_and_members_indent() -> None:
    container = _light("n", container=True, container_key="clan:x:1", member_count=3)
    container["agent_name"] = "my-clan"
    collapsed = format_archive_item(
        _item(container, ITEM_CONTAINER, count=3, expanded=False), CTX
    )
    expanded = format_archive_item(
        _item(container, ITEM_CONTAINER, count=3, expanded=True), CTX
    )
    member = format_archive_item(
        _item(_light("m", container_key="clan:x:1"), ITEM_MEMBER), CTX
    )

    assert "▸ my-clan" in collapsed.plain and "×3" in collapsed.plain
    assert "▾ my-clan" in expanded.plain
    assert member.plain.startswith("    ")
    assert not format_archive_item(_item(_light("p")), CTX).plain.startswith("    ")


def test_restored_overlay_renders_home_chip() -> None:
    item = _item(_light("a"))
    ctx = ArchiveRenderContext(
        tz=UTC, grouping="day", width=80, restored_keys=frozenset()
    )
    assert "⌂ restored" not in format_archive_item(item, ctx).plain
    restored = ArchiveRenderContext(
        tz=UTC, grouping="day", width=80, restored_keys=frozenset({item.key})
    )
    text = format_archive_item(item, restored)
    assert "⌂ restored" in text.plain
    assert "d7af5f" in _style_at(text, "⌂ restored")


def test_legacy_duplicate_option_ids_are_unique_on_the_widget() -> None:
    widget = ArchiveList()
    items = (
        ArchiveListItem("legacy", ITEM_ROW, True, row={"name": "legacy"}),
        ArchiveListItem("legacy#2", ITEM_ROW, True, row={"name": "legacy"}),
    )
    widget.apply_items(items, "legacy", tz=UTC, grouping="day")
    assert widget.item_keys == ("legacy", "legacy#2")


def test_exception_chip_and_unnamed_rows() -> None:
    text = format_archive_item(
        _item(_light("a", restorable=False)),
        ArchiveRenderContext(tz=UTC, width=90),
    )
    assert "⊘ no restore" in text.plain
    unnamed = _light("zzz", agent_name=None)
    assert "zzz" in format_archive_item(_item(unnamed), CTX).plain


def test_banner_tail_and_note_rendering() -> None:
    banner = ArchiveListItem(
        "banner:day:x",
        ITEM_BANNER,
        True,
        banner_key="day:x",
        label="Today",
        count=12,
        open=True,
    )
    folded = ArchiveListItem(
        "banner:day:y",
        ITEM_BANNER,
        True,
        banner_key="day:y",
        label="Fri Oct 2",
        count=1,
    )
    tail = ArchiveListItem(
        "tail:day:x", ITEM_TAIL, True, banner_key="day:x", remaining=7
    )
    loading = ArchiveListItem("loading:x", ITEM_LOADING, False, label="loading…")
    note = ArchiveListItem(
        "message:status",
        ITEM_MESSAGE,
        False,
        label="Archive index unavailable — sase agent archive rebuild-index",
    )

    open_text = format_archive_item(banner, CTX)
    assert open_text.plain == "▾ Today  12 runs"
    assert "d7af5f" in _style_at(open_text, "Today")
    assert format_archive_item(folded, CTX).plain == "▸ Fri Oct 2  1 run"
    assert format_archive_item(tail, CTX).plain.strip() == "⋮ 7 more · l"
    assert format_archive_item(loading, CTX).plain.strip() == "loading…"
    assert format_archive_item(note, CTX).plain.startswith("Archive index unavailable")


def test_outcome_column_aligns_names_across_rows() -> None:
    items = [
        _item(_light("a")),
        _item(_light("b", outcome="interrupted", status="WORKING PLAN")),
    ]
    width = outcome_cell_width(items)
    ctx = ArchiveRenderContext(tz=UTC, width=80, outcome_width=width)
    first, second = (format_archive_item(item, ctx).plain for item in items)

    assert first.index("agent-a") == second.index("agent-b")


def test_pulse_matches_spec_and_omits_zero_attention() -> None:
    pulse = ArchiveInboxPulse(total=12, running=3, waiting=1, unread=2, attention=2)
    text = format_pulse(pulse)

    assert text.plain == "⌂ Inbox · 12 [R3 W1 U2] · 2 needs you"
    quiet = format_pulse(ArchiveInboxPulse(total=4, running=1, attention=0))
    assert quiet.plain == "⌂ Inbox · 4 [R1]"
    assert format_pulse(ArchiveInboxPulse()).plain == "⌂ Inbox · 0"


# --- widgets ----------------------------------------------------------------


class _Host(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[tuple[str, str | None]] = []

    def compose(self) -> ComposeResult:
        yield ArchiveColumn(id="archive-column")

    def on_archive_list_cursor_moved(self, event: ArchiveList.CursorMoved) -> None:
        self.messages.append(("moved", event.key))

    def on_archive_list_item_activated(self, event: ArchiveList.ItemActivated) -> None:
        self.messages.append(("activated", event.key))

    def on_archive_pulse_activated(self, _event: ArchivePulse.Activated) -> None:
        self.messages.append(("pulse", None))


def _items(count: int = 6) -> list[ArchiveListItem]:
    items = [
        ArchiveListItem(
            "banner:day:a",
            ITEM_BANNER,
            True,
            banner_key="day:a",
            label="Today",
            count=count,
            open=True,
        )
    ]
    for index in range(count):
        row = _light(f"r{index}")
        items.append(_item(row))
    items.append(ArchiveListItem("note", ITEM_LOADING, False, label="loading…"))
    return items


async def test_programmatic_cursor_is_silent_and_user_movement_posts_once() -> None:
    app = _Host()
    async with app.run_test(size=(80, 30)) as pilot:
        column = app.query_one(ArchiveColumn)
        column.apply_items(_items(), "u.m@r2", tz=UTC, grouping="day")
        await pilot.pause()
        archive_list = column.archive_list

        assert archive_list.highlighted == archive_list.item_keys.index("u.m@r2")
        assert app.messages == []

        column.set_cursor("u.m@r4")
        await pilot.pause()
        assert archive_list.highlighted == archive_list.item_keys.index("u.m@r4")
        assert app.messages == []  # echo guard: no phantom CursorMoved

        archive_list.action_cursor_down()
        await pilot.pause()
        assert app.messages == [("moved", "u.m@r5")]


async def test_enter_binding_is_not_consumed_and_click_posts_activation() -> None:
    app = _Host()
    async with app.run_test(size=(80, 30)) as pilot:
        column = app.query_one(ArchiveColumn)
        column.apply_items(_items(), "u.m@r0", tz=UTC, grouping="day")
        await pilot.pause()
        archive_list = column.archive_list

        assert "enter" not in {binding.key for binding in archive_list.BINDINGS}
        await pilot.click(ArchiveList, offset=(3, 3))
        await pilot.pause()

        kinds = [kind for kind, _key in app.messages]
        assert "activated" in kinds
        assert app.messages[-1][1] == archive_list.item_keys[2]


async def test_disabled_rows_are_not_navigable_by_the_cursor() -> None:
    app = _Host()
    async with app.run_test(size=(80, 30)) as pilot:
        column = app.query_one(ArchiveColumn)
        column.apply_items(_items(2), "u.m@r1", tz=UTC, grouping="day")
        await pilot.pause()
        archive_list = column.archive_list

        for _ in range(3):
            archive_list.action_cursor_down()
            await pilot.pause()
            assert archive_list.item_keys[archive_list.highlighted] != "note"

        assert all(kind == "moved" for kind, _key in app.messages)


async def test_apply_preserves_scroll_and_cursor_across_rebuilds() -> None:
    app = _Host()
    async with app.run_test(size=(80, 12)) as pilot:
        await pilot.pause()
        column = app.query_one(ArchiveColumn)
        items = _items(40)
        column.apply_items(items, "u.m@r35", tz=UTC, grouping="day")
        await pilot.pause()
        archive_list = column.archive_list
        before = archive_list.scroll_y
        assert before > 0

        column.apply_items(items, "u.m@r35", tz=UTC, grouping="day")
        await pilot.pause()

        assert archive_list.scroll_y == before
        assert archive_list.highlighted == archive_list.item_keys.index("u.m@r35")
        assert app.messages == []


async def test_cursor_row_scrolls_into_view_once_a_hidden_column_is_shown() -> None:
    app = _Host()
    async with app.run_test(size=(80, 12)) as pilot:
        column = app.query_one(ArchiveColumn)
        column.display = False
        await pilot.pause()
        column.apply_items(_items(40), "u.m@r38", tz=UTC, grouping="day")
        await pilot.pause()

        column.display = True
        column.reveal_cursor()
        archive_list = column.archive_list
        for _attempt in range(50):  # an explicit delay waits out the layout pass
            await pilot.pause(0.02)
            if archive_list.scroll_y > 0:
                break
        assert archive_list.scroll_y > 0
        assert archive_list.highlighted == archive_list.item_keys.index("u.m@r38")


async def test_missing_cursor_key_clears_the_highlight_silently() -> None:
    app = _Host()
    async with app.run_test(size=(80, 30)) as pilot:
        column = app.query_one(ArchiveColumn)
        column.apply_items(_items(), "u.m@r2", tz=UTC, grouping="day")
        await pilot.pause()

        column.set_cursor("gone")
        await pilot.pause()

        assert column.archive_list.highlighted is None
        assert app.messages == []


async def test_rows_refit_when_the_column_is_resized() -> None:
    app = _Host()
    async with app.run_test(size=(120, 20)) as pilot:
        column = app.query_one(ArchiveColumn)
        column.styles.width = 110
        column.apply_items(_items(2), "u.m@r0", tz=UTC, grouping="day")
        await pilot.pause()
        archive_list = column.archive_list

        def prompt_for(key: str) -> str:
            option = archive_list.get_option(key)
            return str(
                option.prompt.plain
                if isinstance(option.prompt, Text)
                else option.prompt
            )

        wide = prompt_for("u.m@r0")
        assert "opus" in wide and "4m32s" in wide

        column.styles.width = 40
        await pilot.pause()
        await pilot.pause()

        narrow = prompt_for("u.m@r0")
        assert "opus" not in narrow and "4m32s" not in narrow
        assert "agent-r0" in narrow


async def test_pulse_selection_and_click() -> None:
    app = _Host()
    async with app.run_test(size=(80, 20)) as pilot:
        column = app.query_one(ArchiveColumn)
        column.set_pulse(ArchiveInboxPulse(total=5, running=2, attention=1))
        column.set_section(ARCHIVE_SECTION_PULSE)
        await pilot.pause()
        pulse = column.archive_pulse

        assert pulse.has_class("-selected")
        assert "⌂ Inbox · 5 [R2] · 1 needs you" in str(pulse.render())
        assert column.archive_list.has_class("-dimmed")

        column.set_section(ARCHIVE_SECTION_LIST)
        await pilot.pause()
        assert not pulse.has_class("-selected")
        assert not column.archive_list.has_class("-dimmed")

        await pilot.click(ArchivePulse)
        await pilot.pause()
        assert ("pulse", None) in app.messages


async def test_state_pushed_before_mount_is_flushed_on_mount() -> None:
    column = ArchiveColumn(id="archive-column")
    column.apply_items(_items(3), "u.m@r1", tz=UTC, grouping="day")
    column.set_cursor("u.m@r1")
    column.set_section(ARCHIVE_SECTION_PULSE)
    column.set_pulse(ArchiveInboxPulse(total=1))

    class _LateHost(_Host):
        def compose(self) -> ComposeResult:
            yield column

    app = _LateHost()
    async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause()
        assert column.archive_list.highlighted == column.archive_list.item_keys.index(
            "u.m@r1"
        )
        assert column.archive_pulse.has_class("-selected")
        assert "⌂ Inbox · 1" in str(column.archive_pulse.render())
        assert Size(80, 20)  # layout ran without error
