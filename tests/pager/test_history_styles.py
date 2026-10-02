"""Badge-phase tests: the theme-aware history style set.

Every built-in host theme, dark and light, must give text roles at
>= 4.5:1, marks at >= 3.0:1, pill text at >= 4.5:1, band text at
>= 4.5:1 against the past tint, the past hue >= 60 degrees from the
warning hue, and the changed-mark blue >= 30 degrees from past.
"""

from __future__ import annotations

from textual.theme import BUILTIN_THEMES

from sase.pager.history.styles import (
    default_history_styles,
    history_styles_for_theme,
    _history_styles_from_palette,
    _hue_distance,
)
from sase.pager.syntax_theme import contrast_ratio, history_palette_from_theme


def test_styles_resolve_for_every_builtin_theme() -> None:
    assert BUILTIN_THEMES, "expected at least one built-in theme"
    for name, theme in BUILTIN_THEMES.items():
        styles = history_styles_for_theme(theme)
        assert styles.signature, name
        # Resolved twice, the cached styles are identical.
        assert history_styles_for_theme(theme) is styles, name


def test_text_roles_keep_reader_contrast_on_every_theme() -> None:
    for name, theme in BUILTIN_THEMES.items():
        styles = history_styles_for_theme(theme)
        for role in (
            styles.past,
            styles.insert,
            styles.delete,
            styles.uncommitted,
        ):
            assert contrast_ratio(role, styles.background) >= 4.5, (name, role)


def test_marks_keep_mark_contrast_on_every_theme() -> None:
    for name, theme in BUILTIN_THEMES.items():
        styles = history_styles_for_theme(theme)
        for role in (
            styles.gutter_add,
            styles.gutter_change,
            styles.gutter_remove,
            styles.rail_past,
            styles.rail_deleted,
        ):
            assert contrast_ratio(role, styles.background) >= 3.0, (name, role)


def test_pill_text_reads_on_every_pill_on_every_theme() -> None:
    for name, theme in BUILTIN_THEMES.items():
        styles = history_styles_for_theme(theme)
        for bg, fg in (
            (styles.now_pill_bg, styles.now_pill_fg),
            (styles.past_pill_bg, styles.past_pill_fg),
            (styles.uncommitted_pill_bg, styles.uncommitted_pill_fg),
            (styles.deleted_pill_bg, styles.deleted_pill_fg),
        ):
            assert fg in ("#000000", "#ffffff"), (name, bg, fg)
            assert contrast_ratio(fg, bg) >= 4.5, (name, bg, fg)


def test_band_text_reads_on_the_past_tint_on_every_theme() -> None:
    for name, theme in BUILTIN_THEMES.items():
        styles = history_styles_for_theme(theme)
        assert contrast_ratio(styles.foreground, styles.band_past_tint) >= 4.5, name


def test_past_hue_stays_clear_of_warning_on_every_theme() -> None:
    for name, theme in BUILTIN_THEMES.items():
        styles = history_styles_for_theme(theme)
        warning = getattr(theme, "warning", None) or "#FFB000"
        distance = _hue_distance(styles.past, warning)
        assert distance is not None and distance >= 60, (name, distance)


def test_modified_hue_stays_clear_of_past_on_every_theme() -> None:
    for name, theme in BUILTIN_THEMES.items():
        styles = history_styles_for_theme(theme)
        distance = _hue_distance(styles.modified, styles.past)
        assert distance is not None and distance >= 30, (name, distance)


def test_palette_carries_every_badge_role() -> None:
    palette = history_palette_from_theme(None)
    for role in (
        "modified",
        "now_pill_bg",
        "past_pill_bg",
        "uncommitted_pill_bg",
        "deleted_pill_bg",
        "rail_past",
        "rail_deleted",
        "band_past_tint",
    ):
        assert palette[role].startswith("#"), role
    # The changed-line mark is the VCS blue, not the violet past.
    assert palette["gutter_change"] == palette["modified"]
    assert palette["gutter_change"] != palette["past"]


def test_styles_build_from_a_bare_palette() -> None:
    styles = _history_styles_from_palette({})
    assert styles.signature
    assert contrast_ratio(styles.past_pill_fg, styles.past_pill_bg) >= 4.5
    assert (
        default_history_styles().signature == history_styles_for_theme(None).signature
    )


def test_secondary_metadata_stays_readable_without_bare_dim() -> None:
    for name, theme in BUILTIN_THEMES.items():
        styles = history_styles_for_theme(theme)
        assert styles.secondary.startswith("#"), name
        assert contrast_ratio(styles.secondary, styles.background) >= 4.5, name


def test_link_accents_correct_against_light_surfaces() -> None:
    from sase.pager._labels import style_target_accents
    from sase.pager.document import PagerDocument, PagerOrigin, PagerSection

    light = history_styles_for_theme(BUILTIN_THEMES["textual-light"]).background
    section = PagerSection(
        identity="file:/tmp/links.txt",
        title="links.txt",
        kind="file",
        body="open src/sase/pager/app.py and https://example.test/page\n",
    )
    for surface in (
        history_styles_for_theme(BUILTIN_THEMES["textual-dark"]).background,
        light,
    ):
        styled = style_target_accents(
            section.body_text,
            section,
            0,
            PagerOrigin.FILE,
            surface=surface,
        )
        assert styled.plain == section.body_text.plain
        assert styled.spans, surface
        for span in styled.spans:
            style = str(span.style or "")
            color = style.split()[-1] if style else ""
            if color.startswith("#"):
                assert contrast_ratio(color, surface) >= 4.5, (style, surface)
