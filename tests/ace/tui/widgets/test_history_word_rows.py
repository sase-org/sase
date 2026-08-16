"""Rich-row tests for smart-ranked history-word signals."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.widgets._history_word_rows import (
    RECENCY_COLOR,
    RELATION_COLOR,
    append_history_word_completion_row,
    build_score_meter,
    format_reason_chip,
    history_word_label_width,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_panel_labels import (
    history_word_completion_subtitle,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.history_word_completion import (
    HISTORY_WORD_COMPLETION_KIND,
    HistoryWordCompletionMetadata,
    build_loading_history_words_placeholder,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

from ._completion_helpers import CompletionTestApp


def _ranked_candidate(
    word: str,
    *,
    reason: str = "relation",
    related_to: str = "monitor",
    use_count: int = 47,
    age_seconds: float = 1200.0,
    score: float = 0.6,
    relation: float = 0.4,
    recency: float = 0.2,
    frequency: float = 0.0,
) -> CompletionCandidate:
    return CompletionCandidate(
        display=word,
        insertion=word,
        is_dir=False,
        name=word,
        metadata=HistoryWordCompletionMetadata(
            reason=reason,
            related_to=related_to,
            use_count=use_count,
            age_seconds=age_seconds,
            score=score,
            relation=relation,
            recency=recency,
            frequency=frequency,
        ),
    )


def _plain_candidate(word: str) -> CompletionCandidate:
    return CompletionCandidate(display=word, insertion=word, is_dir=False, name=word)


def test_history_word_label_width_caps_at_28_and_skips_placeholder() -> None:
    assert history_word_label_width(_plain_candidate("reconciliation")) == 14
    assert history_word_label_width(_plain_candidate("a" * 40)) == 28
    assert history_word_label_width(build_loading_history_words_placeholder()) == 0


def test_score_meter_renders_empty_for_zero_score() -> None:
    metadata = HistoryWordCompletionMetadata(
        reason="recency",
        related_to="",
        use_count=0,
        age_seconds=0.0,
        score=0.0,
        relation=0.0,
        recency=0.0,
        frequency=0.0,
    )

    meter = build_score_meter(metadata)

    assert meter.plain == "▱▱▱▱▱"
    assert all(str(span.style) == "dim" for span in meter.spans)


def test_score_meter_distributes_fixed_signal_order_by_largest_remainder() -> None:
    metadata = HistoryWordCompletionMetadata(
        reason="relation",
        related_to="monitor",
        use_count=1,
        age_seconds=10.0,
        score=0.6,
        relation=0.4,
        recency=0.2,
        frequency=0.0,
    )

    meter = build_score_meter(metadata)

    assert meter.plain == "▰▰▰▱▱"
    styles = [str(span.style) for span in meter.spans]
    assert styles == [
        f"bold {RELATION_COLOR}",
        f"bold {RELATION_COLOR}",
        f"bold {RECENCY_COLOR}",
        "dim",
        "dim",
    ]


def test_score_meter_never_shows_fewer_than_one_filled_cell_for_positive_score() -> (
    None
):
    metadata = HistoryWordCompletionMetadata(
        reason="frequency",
        related_to="",
        use_count=1,
        age_seconds=0.0,
        score=0.02,
        relation=0.0,
        recency=0.0,
        frequency=0.02,
    )

    meter = build_score_meter(metadata)

    assert meter.plain.count("▰") == 1
    assert meter.plain.count("▱") == 4


def test_reason_chip_shows_related_context_word() -> None:
    metadata = HistoryWordCompletionMetadata(
        reason="relation",
        related_to="monitor",
        use_count=0,
        age_seconds=0.0,
        score=0.4,
        relation=0.4,
        recency=0.0,
        frequency=0.0,
    )

    chip = format_reason_chip(metadata)

    assert chip.plain == "⇄ monitor"


def test_reason_chip_truncates_long_context_word() -> None:
    metadata = HistoryWordCompletionMetadata(
        reason="relation",
        related_to="a" * 20,
        use_count=0,
        age_seconds=0.0,
        score=0.4,
        relation=0.4,
        recency=0.0,
        frequency=0.0,
    )

    chip = format_reason_chip(metadata)

    assert chip.plain == "⇄ " + "a" * 13 + "..."


def test_reason_chip_shows_use_count_for_frequency() -> None:
    metadata = HistoryWordCompletionMetadata(
        reason="frequency",
        related_to="",
        use_count=47,
        age_seconds=0.0,
        score=0.2,
        relation=0.0,
        recency=0.0,
        frequency=0.2,
    )

    chip = format_reason_chip(metadata)

    assert chip.plain == "✦ 47×"


def test_reason_chip_age_unit_boundaries() -> None:
    def chip_for(age_seconds: float) -> str:
        metadata = HistoryWordCompletionMetadata(
            reason="recency",
            related_to="",
            use_count=0,
            age_seconds=age_seconds,
            score=0.3,
            relation=0.0,
            recency=0.3,
            frequency=0.0,
        )
        return format_reason_chip(metadata).plain

    assert chip_for(59) == "◷ 59s"
    assert chip_for(60) == "◷ 1m"
    assert chip_for(3599) == "◷ 59m"
    assert chip_for(3600) == "◷ 1h"
    assert chip_for(86399) == "◷ 23h"
    assert chip_for(86400) == "◷ 1d"
    assert chip_for(604799) == "◷ 6d"
    assert chip_for(604800) == "◷ 1w"


def _render_row(
    candidate: CompletionCandidate,
    *,
    label_width: int,
    inner_width: int,
    signals_enabled: bool = True,
    selected: bool = False,
) -> Text:
    content = Text()
    append_history_word_completion_row(
        content,
        candidate,
        selected,
        label_width=label_width,
        inner_width=inner_width,
        signals_enabled=signals_enabled,
    )
    return content


def test_row_renders_word_meter_and_chip_when_wide() -> None:
    candidate = _ranked_candidate("reconcile")

    rendered = _render_row(candidate, label_width=14, inner_width=40)

    assert rendered.plain == "reconcile" + " " * 7 + "▰▰▰▱▱" + "  " + "⇄ monitor"


def test_row_drops_chip_before_meter_on_narrow_panel() -> None:
    candidate = _ranked_candidate("reconcile")

    dropped_chip = _render_row(candidate, label_width=14, inner_width=25)
    dropped_both = _render_row(candidate, label_width=14, inner_width=15)

    assert dropped_chip.plain == "reconcile" + " " * 7 + "▰▰▰▱▱"
    assert dropped_both.plain == "reconcile"


def test_row_is_unconstrained_when_inner_width_is_not_positive() -> None:
    candidate = _ranked_candidate("reconcile")

    rendered = _render_row(candidate, label_width=14, inner_width=0)

    assert "⇄ monitor" in rendered.plain


def test_row_falls_back_to_plain_word_when_signals_disabled() -> None:
    candidate = _ranked_candidate("reconcile")

    rendered = _render_row(
        candidate, label_width=14, inner_width=40, signals_enabled=False
    )

    assert rendered.plain == "reconcile"
    assert "▰" not in rendered.plain


def test_row_falls_back_to_plain_word_without_metadata() -> None:
    candidate = _plain_candidate("reconcile")

    rendered = _render_row(candidate, label_width=14, inner_width=40)

    assert rendered.plain == "reconcile"


def test_row_renders_placeholder_dim_italic() -> None:
    placeholder = build_loading_history_words_placeholder()

    rendered = _render_row(placeholder, label_width=0, inner_width=40)

    assert rendered.plain == placeholder.display
    assert str(rendered.spans[0].style) == "dim italic"


def test_subtitle_shows_legend_when_wide_and_metadata_present() -> None:
    visible = [_ranked_candidate("reconcile")]

    subtitle = history_word_completion_subtitle(visible, 200)

    assert isinstance(subtitle, Text)
    assert subtitle.plain.startswith("⇄ related · ◷ recent · ✦ frequent")
    assert subtitle.plain.endswith("[^L] accept  [^D] delete")


def test_subtitle_falls_back_to_plain_hint_when_too_narrow() -> None:
    visible = [_ranked_candidate("reconcile")]
    full = history_word_completion_subtitle(visible, 200)
    assert isinstance(full, Text)

    narrow = history_word_completion_subtitle(visible, full.cell_len - 1)

    assert narrow == "[^L] accept  [^D] delete"


def test_subtitle_falls_back_when_no_row_carries_metadata() -> None:
    visible = [_plain_candidate("reconcile")]

    subtitle = history_word_completion_subtitle(visible, 200)

    assert subtitle == "[^L] accept  [^D] delete"


def test_subtitle_is_empty_when_only_placeholder_is_visible() -> None:
    visible = [build_loading_history_words_placeholder()]

    assert history_word_completion_subtitle(visible, 200) == ""


async def test_panel_renders_full_signals_when_wide() -> None:
    app = CompletionTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        bar = app.query_one(PromptInputBar)
        panel = bar.query_one("#prompt-completion", Static)

        bar.show_file_completions(
            "rec",
            [_ranked_candidate("reconcile"), _ranked_candidate("reconciliation")],
            selected_index=0,
            completion_kind=HISTORY_WORD_COMPLETION_KIND,
        )
        await pilot.pause()

        rendered = panel.render().plain
        assert "▰" in rendered
        assert "⇄ monitor" in rendered
        assert "related" in str(panel.border_subtitle)


async def test_panel_degrades_on_narrow_width() -> None:
    app = CompletionTestApp()
    async with app.run_test(size=(24, 24)) as pilot:
        bar = app.query_one(PromptInputBar)
        panel = bar.query_one("#prompt-completion", Static)

        bar.show_file_completions(
            "rec",
            [_ranked_candidate("reconciliation")],
            selected_index=0,
            completion_kind=HISTORY_WORD_COMPLETION_KIND,
        )
        await pilot.pause()

        rendered = panel.render().plain
        assert "reconciliation" in rendered
        assert "▰" not in rendered


async def test_panel_renders_plain_rows_when_signals_disabled() -> None:
    app = CompletionTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        bar = app.query_one(PromptInputBar)
        panel = bar.query_one("#prompt-completion", Static)

        bar.show_file_completions(
            "rec",
            [_ranked_candidate("reconcile")],
            selected_index=0,
            completion_kind=HISTORY_WORD_COMPLETION_KIND,
            word_ranking_signals=False,
        )
        await pilot.pause()

        rendered = panel.render().plain
        assert "reconcile" in rendered
        assert "▰" not in rendered
        assert "⇄" not in rendered
        assert panel.border_subtitle == "[^L] accept  [^D] delete"
