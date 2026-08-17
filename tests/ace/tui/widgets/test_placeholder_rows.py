"""Rich-row and subtitle tests for smart-ranked saved placeholder signals."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.widgets._prompt_input_bar_completion_panel_labels import (
    _PLACEHOLDER_SOURCE_LEGEND,
    placeholder_completion_subtitle,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_rows_simple import (
    append_placeholder_completion_row,
    placeholder_label_width,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.placeholder_completion import (
    PLACEHOLDER_COMPLETION_KIND,
    PlaceholderCompletionMetadata,
    PlaceholderRankingMetadata,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

from ._completion_helpers import CompletionTestApp


def _prompt_candidate(text: str) -> CompletionCandidate:
    return CompletionCandidate(
        display=text,
        insertion=text,
        is_dir=False,
        name=text,
        metadata=PlaceholderCompletionMetadata(source="prompt"),
    )


def _recent_candidate(text: str) -> CompletionCandidate:
    """A saved candidate from ``recent`` mode: no ranking evidence attached."""
    return CompletionCandidate(
        display=text,
        insertion=text,
        is_dir=False,
        name=text,
        metadata=PlaceholderCompletionMetadata(source="common", ranking=None),
    )


def _saved_candidate(
    text: str,
    *,
    reason: str = "frequency",
    related_to: str = "epic name",
    use_count: int = 5,
    age_seconds: float = 259200.0,
    score: float = 0.4,
    relation: float = 0.0,
    recency: float = 0.0,
    frequency: float = 0.4,
) -> CompletionCandidate:
    return CompletionCandidate(
        display=text,
        insertion=text,
        is_dir=False,
        name=text,
        metadata=PlaceholderCompletionMetadata(
            source="common",
            ranking=PlaceholderRankingMetadata(
                reason=reason,
                related_to=related_to,
                use_count=use_count,
                age_seconds=age_seconds,
                score=score,
                relation=relation,
                recency=recency,
                frequency=frequency,
            ),
        ),
    )


def _render_row(
    candidate: CompletionCandidate,
    *,
    label_width: int,
    inner_width: int,
    signals_enabled: bool = True,
    selected: bool = False,
) -> Text:
    content = Text()
    append_placeholder_completion_row(
        content,
        candidate,
        selected,
        label_width=label_width,
        inner_width=inner_width,
        signals_enabled=signals_enabled,
    )
    return content


def test_placeholder_label_width_measures_badge_plus_label_and_caps() -> None:
    assert placeholder_label_width(_prompt_candidate("alpha")) == cell_len("<> ") + 5
    assert placeholder_label_width(_saved_candidate("phase title")) == cell_len(
        "◆  "
    ) + len("phase title")
    assert placeholder_label_width(_saved_candidate("a" * 40)) == 28


def test_row_renders_meter_and_chip_on_saved_row_when_wide() -> None:
    candidate = _saved_candidate("worker", reason="frequency", use_count=12)

    rendered = _render_row(candidate, label_width=14, inner_width=40)

    assert rendered.plain == "◆  worker" + " " * 7 + "▰▰▱▱▱" + "  " + "✦ 12×"


def test_row_drops_chip_before_meter_on_narrow_panel() -> None:
    candidate = _saved_candidate("worker", reason="frequency", use_count=12)

    dropped_chip = _render_row(candidate, label_width=14, inner_width=25)
    dropped_both = _render_row(candidate, label_width=14, inner_width=15)

    assert dropped_chip.plain == "◆  worker" + " " * 7 + "▰▰▱▱▱"
    assert dropped_both.plain == "◆  worker"


def test_row_is_unconstrained_when_inner_width_is_not_positive() -> None:
    candidate = _saved_candidate("worker", reason="frequency", use_count=12)

    rendered = _render_row(candidate, label_width=14, inner_width=0)

    assert "✦ 12×" in rendered.plain


def test_row_falls_back_to_plain_row_when_signals_disabled() -> None:
    candidate = _saved_candidate("worker")

    rendered = _render_row(
        candidate, label_width=14, inner_width=40, signals_enabled=False
    )

    assert rendered.plain == "◆  worker"
    assert "▰" not in rendered.plain


def test_row_renders_todays_row_for_prompt_candidate() -> None:
    candidate = _prompt_candidate("alpha")

    rendered = _render_row(candidate, label_width=14, inner_width=40)

    assert rendered.plain == "<> alpha"


def test_row_renders_todays_row_when_ranking_is_none() -> None:
    candidate = _recent_candidate("worker")

    rendered = _render_row(candidate, label_width=14, inner_width=40)

    assert rendered.plain == "◆  worker"


def test_subtitle_shows_full_ladder_when_wide() -> None:
    visible = [_prompt_candidate("alpha"), _saved_candidate("worker")]

    subtitle = placeholder_completion_subtitle(visible, 200)

    assert isinstance(subtitle, Text)
    assert subtitle.plain == (
        f"{_PLACEHOLDER_SOURCE_LEGEND}  ⇄ related · ◷ recent · ✦ frequent  [^D] delete"
    )


def test_subtitle_drops_source_legend_when_full_ladder_does_not_fit() -> None:
    # Full ladder is 67 cells; 60 excludes it but still fits the 46-cell
    # signal-legend-only rung.
    visible = [_prompt_candidate("alpha"), _saved_candidate("worker")]

    subtitle = placeholder_completion_subtitle(visible, 60)

    assert isinstance(subtitle, Text)
    assert subtitle.plain == "⇄ related · ◷ recent · ✦ frequent  [^D] delete"


def test_subtitle_drops_signal_legend_leaving_todays_subtitle() -> None:
    # 40 excludes the 46-cell signal-only rung but still fits the 32-cell
    # today's-subtitle rung (source legend, no signal legend).
    visible = [_prompt_candidate("alpha"), _saved_candidate("worker")]

    subtitle = placeholder_completion_subtitle(visible, 40)

    assert subtitle == f"{_PLACEHOLDER_SOURCE_LEGEND}  [^D] delete"


def test_subtitle_falls_back_to_delete_alone_when_narrowest() -> None:
    # 20 excludes the 32-cell today's-subtitle rung but still fits the
    # 11-cell delete-alone rung.
    visible = [_prompt_candidate("alpha"), _saved_candidate("worker")]

    subtitle = placeholder_completion_subtitle(visible, 20)

    assert subtitle == "[^D] delete"


def test_subtitle_returns_delete_hint_even_narrower_than_delete_hint() -> None:
    visible = [_prompt_candidate("alpha"), _saved_candidate("worker")]

    subtitle = placeholder_completion_subtitle(visible, 5)

    assert subtitle == "[^D] delete"


def test_subtitle_has_no_source_legend_when_no_saved_rows_are_visible() -> None:
    visible = [_prompt_candidate("alpha"), _prompt_candidate("beta")]

    subtitle = placeholder_completion_subtitle(visible, 200)

    assert subtitle == "[^D] delete"


def test_subtitle_has_no_source_legend_when_only_saved_rows_are_visible() -> None:
    visible = [_saved_candidate("worker")]

    subtitle = placeholder_completion_subtitle(visible, 200)

    assert isinstance(subtitle, Text)
    assert _PLACEHOLDER_SOURCE_LEGEND not in subtitle.plain
    assert subtitle.plain == "⇄ related · ◷ recent · ✦ frequent  [^D] delete"


def test_subtitle_has_no_signal_legend_when_no_row_carries_metadata() -> None:
    visible = [_prompt_candidate("alpha"), _recent_candidate("worker")]

    subtitle = placeholder_completion_subtitle(visible, 200)

    assert subtitle == f"{_PLACEHOLDER_SOURCE_LEGEND}  [^D] delete"


async def test_panel_renders_full_signals_when_wide() -> None:
    app = CompletionTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        bar = app.query_one(PromptInputBar)
        panel = bar.query_one("#prompt-completion", Static)

        bar.show_file_completions(
            "rel",
            [_prompt_candidate("alpha"), _saved_candidate("release checklist")],
            selected_index=0,
            completion_kind=PLACEHOLDER_COMPLETION_KIND,
        )
        await pilot.pause()

        rendered = panel.render().plain
        assert "▰" in rendered
        assert "✦ 5×" in rendered
        assert "related" in str(panel.border_subtitle)


async def test_panel_degrades_on_narrow_width() -> None:
    app = CompletionTestApp()
    async with app.run_test(size=(24, 24)) as pilot:
        bar = app.query_one(PromptInputBar)
        panel = bar.query_one("#prompt-completion", Static)

        bar.show_file_completions(
            "rel",
            [_saved_candidate("release checklist")],
            selected_index=0,
            completion_kind=PLACEHOLDER_COMPLETION_KIND,
        )
        await pilot.pause()

        rendered = panel.render().plain
        assert "release checklist" in rendered
        assert "▰" not in rendered


async def test_panel_renders_plain_rows_when_signals_disabled() -> None:
    app = CompletionTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        bar = app.query_one(PromptInputBar)
        panel = bar.query_one("#prompt-completion", Static)

        bar.show_file_completions(
            "rel",
            [_prompt_candidate("alpha"), _saved_candidate("release checklist")],
            selected_index=0,
            completion_kind=PLACEHOLDER_COMPLETION_KIND,
            placeholder_ranking_signals=False,
        )
        await pilot.pause()

        rendered = panel.render().plain
        assert "release checklist" in rendered
        assert "▰" not in rendered
        assert "⇄" not in rendered
        assert (
            str(panel.border_subtitle) == f"{_PLACEHOLDER_SOURCE_LEGEND}  [^D] delete"
        )


async def test_panel_aligns_saved_meter_to_longest_label_across_both_groups() -> None:
    app = CompletionTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        bar = app.query_one(PromptInputBar)
        panel = bar.query_one("#prompt-completion", Static)

        prompt_candidate = _prompt_candidate("release owner")
        bar.show_file_completions(
            "rel",
            [prompt_candidate, _saved_candidate("worker")],
            selected_index=0,
            completion_kind=PLACEHOLDER_COMPLETION_KIND,
        )
        await pilot.pause()

        saved_line = panel.render().plain.splitlines()[1]
        meter_column = saved_line.index("▰")
        # "<> release owner" is wider than "◆  worker" alone; the saved
        # row's meter must start where the wider prompt row's label ends,
        # proving both source groups share one label column.
        expected_label_width = placeholder_label_width(prompt_candidate)
        assert meter_column == 2 + expected_label_width + 2
