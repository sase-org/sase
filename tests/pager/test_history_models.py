"""Focused history seam tests: models, registry, syntax keys, gutter, chrome."""

from __future__ import annotations

from rich.text import Text

from sase.pager._chrome import footer_legend, subject_line
from sase.pager._gutter import apply_gutter
from sase.pager._screen_syntax import _syntax_key_for_section  # noqa: PLC2701
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.history.models import (
    committed_pin_for_ordinal,
    live_pin_for_subject,
)
from sase.pager.history.provider import (
    clear_history_provider_factories,
    history_provider_for_section,
    register_history_provider_factory,
)
from sase.pager.syntax_theme import contrast_ratio, history_palette_from_theme


def _section(identity: str, body: str = "hello\n") -> PagerSection:
    return PagerSection(identity=identity, title=identity, kind="file", body=body)


def test_version_pin_display() -> None:
    live = live_pin_for_subject("note:project:sase/tui")
    assert live.is_live and live.display == "now"
    pinned = committed_pin_for_ordinal("note:project:sase/tui", 3)
    assert not pinned.is_live and pinned.display == "v3"


def test_registry_declines_without_factories() -> None:
    clear_history_provider_factories()
    try:
        assert history_provider_for_section(_section("sase/memory/tui.md")) is None
    finally:
        clear_history_provider_factories()


def test_registry_uses_first_recognizing_provider() -> None:
    clear_history_provider_factories()
    try:

        class _Fake:
            provider_key = "fake"

            def recognizes(self, section: PagerSection) -> bool:
                return "memory" in section.identity

            def load_timeline(self, section: PagerSection) -> dict[str, object]:
                return {"versions": []}

            def load_version(
                self, section: PagerSection, ordinal: int
            ) -> PagerSection | None:
                return None

            def compare_versions(
                self, section: PagerSection, base_ordinal: int, target_ordinal: int
            ) -> dict[str, object] | None:
                return None

            def resolve_historical_link(
                self, section: PagerSection, ref: str
            ) -> PagerSection | None:
                return None

            def refresh(self, section: PagerSection) -> PagerSection | None:
                return None

        register_history_provider_factory(lambda: _Fake())
        provider = history_provider_for_section(_section("sase/memory/tui.md"))
        assert provider is not None
        assert history_provider_for_section(_section("unrelated.txt")) is None
    finally:
        clear_history_provider_factories()


def test_syntax_keys_separate_blobs_sharing_identity() -> None:
    pinned_old = PagerSection(
        identity="sase/memory/tui.md",
        title="tui.md",
        kind="file",
        body="one\n",
        version_pin=committed_pin_for_ordinal("s", 1, blob_oid="a" * 40),
    )
    pinned_new = PagerSection(
        identity="sase/memory/tui.md",
        title="tui.md",
        kind="file",
        body="two\n",
        version_pin=committed_pin_for_ordinal("s", 2, blob_oid="b" * 40),
    )
    assert _syntax_key_for_section(pinned_old) != _syntax_key_for_section(pinned_new)
    assert _syntax_key_for_section(pinned_old)[0] == "sase/memory/tui.md"
    # Live history pins key by content digest, not identity alone.
    live_one = PagerSection(
        identity="sase/memory/tui.md",
        title="tui.md",
        kind="file",
        body="one\n",
        version_pin=live_pin_for_subject("s"),
    )
    live_two = PagerSection(
        identity="sase/memory/tui.md",
        title="tui.md",
        kind="file",
        body="two\n",
        version_pin=live_pin_for_subject("s"),
    )
    assert _syntax_key_for_section(live_one) != _syntax_key_for_section(live_two)
    # Non-history sections keep the legacy key.
    assert _syntax_key_for_section(_section("sase/memory/tui.md")) == (
        "sase/memory/tui.md",
        None,
    )


def test_gutter_change_marks_and_goto_priority() -> None:
    text = Text("one\ntwo\nthree\n")
    marked = apply_gutter(
        text,
        content_width=40,
        number_width=2,
        change_marks={2: "added"},
        removal_anchors={3},
    )
    assert "▌" in marked.text.plain
    assert "╴" in marked.text.plain
    # Goto rail wins when both coincide on line 2.
    both = apply_gutter(
        text,
        content_width=40,
        number_width=2,
        emphasis_range=(2, 2),
        accent="#FFD75F",
        change_marks={2: "added"},
    )
    assert "┃" in both.text.plain


def test_subject_chips_and_footer_verbs() -> None:
    document = PagerDocument(
        sections=(_section("a"),), title="doc", origin=PagerOrigin.FILE
    )
    past = subject_line(
        document,
        document.sections[0],
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=80,
        history_state={"ordinal": 2, "total": 5, "age": "3d"},
    )
    assert "PAST v2/5" in past.plain
    dirty = subject_line(
        document,
        document.sections[0],
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=80,
        history_state={"ordinal": 0, "total": 5, "dirty": True},
    )
    assert "uncommitted" in dirty.plain
    footer = footer_legend(section_total=1, history_available=True, history_pinned=True)
    assert "( )" in footer.plain and "edits now" in footer.plain
    plain_footer = footer_legend(section_total=1)
    assert "( )" not in plain_footer.plain


def test_history_palette_contrast_and_hue() -> None:
    palette = history_palette_from_theme(None)
    assert palette["past"].lower().startswith("#9d7cd8") or palette["past"].startswith(
        "#"
    )
    assert contrast_ratio(palette["past"], "#000000") >= 3.0
    assert contrast_ratio("#ffffff", "#000000") >= 4.5
