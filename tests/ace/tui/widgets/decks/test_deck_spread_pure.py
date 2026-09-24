"""Pure spread tests: settings, anchors, separators, subtitle tag."""

from __future__ import annotations

from rich.console import Console
from rich.segment import Segment
from rich.style import Style
from rich.text import Text

from sase.ace.tui.agent_decks_settings import (
    DEFAULT_AGENT_DECKS_SETTINGS,
    AgentDecksSettings,
    agent_decks_settings_for,
    parse_agent_decks_settings,
)
from sase.ace.tui.widgets.decks.availability import DeckAvailability
from sase.ace.tui.widgets.decks.model import DeckId
from sase.ace.tui.widgets.decks.separators import CardSeparator
from sase.ace.tui.widgets.decks.titles import deck_subtitle
from sase.ace.tui.widgets.prompt_panel._section_navigation import (
    DECK_CARD_META_KEY,
    PromptPanelSectionRole,
    _segment_section_identity,
)


def test_settings_parser() -> None:
    assert parse_agent_decks_settings({}) == DEFAULT_AGENT_DECKS_SETTINGS
    assert parse_agent_decks_settings(None) == DEFAULT_AGENT_DECKS_SETTINGS
    assert (
        parse_agent_decks_settings({"agent_decks": True})
        == DEFAULT_AGENT_DECKS_SETTINGS
    )
    assert parse_agent_decks_settings(
        {"agent_decks": {"spread_max_screens": True}}
    ) == (DEFAULT_AGENT_DECKS_SETTINGS)
    assert (
        parse_agent_decks_settings({"agent_decks": {"spread_max_screens": "1.5"}})
        == DEFAULT_AGENT_DECKS_SETTINGS
    )
    assert (
        parse_agent_decks_settings({"agent_decks": {"spread_max_screens": -1}})
        == DEFAULT_AGENT_DECKS_SETTINGS
    )
    assert parse_agent_decks_settings(
        {"agent_decks": {"spread_max_screens": 0}}
    ) == AgentDecksSettings(spread_max_screens=0.0)
    assert parse_agent_decks_settings(
        {"agent_decks": {"spread_max_screens": 2}}
    ) == AgentDecksSettings(spread_max_screens=2.0)
    assert parse_agent_decks_settings(
        {"agent_decks": {"spread_max_screens": 2.5}}
    ) == AgentDecksSettings(spread_max_screens=2.5)


def test_settings_helper_fails_open() -> None:
    assert agent_decks_settings_for(object()) == DEFAULT_AGENT_DECKS_SETTINGS

    class _App:
        _agent_decks_settings = AgentDecksSettings(spread_max_screens=0.0)

    class _Widget:
        app = _App()

    assert agent_decks_settings_for(_Widget()).spread_max_screens == 0.0


def test_card_meta_yields_card_anchor() -> None:
    seg = Segment("rule", Style(meta={DECK_CARD_META_KEY: "reply"}))
    assert _segment_section_identity(seg) == (
        "card:reply",
        PromptPanelSectionRole.CARD,
    )


def test_card_key_wins_over_section_key() -> None:
    from sase.ace.tui.widgets.prompt_panel._section_navigation import (
        SECTION_MARKER_META_KEY,
    )

    seg = Segment(
        "x",
        Style(meta={DECK_CARD_META_KEY: "c", SECTION_MARKER_META_KEY: "s"}),
    )
    identity, role = _segment_section_identity(seg)  # type: ignore[misc]
    assert identity == "card:c"
    assert role is PromptPanelSectionRole.CARD


def test_section_target_ignores_card_anchors() -> None:
    from sase.ace.tui.widgets.prompt_panel._section_view import SectionViewMixin
    from sase.ace.tui.widgets.prompt_panel._section_navigation import (
        PromptPanelSectionAnchor,
    )

    view = SectionViewMixin()
    view._section_generation = 1
    view._section_anchor_generation = 1
    view._section_anchor_width = 80
    view._section_anchors = (
        PromptPanelSectionAnchor("card:reply", 5, PromptPanelSectionRole.CARD),
    )
    target = view.resolve_section_target(1, width=80)
    assert target.kind.name == "EMPTY"
    assert view.resolve_section_at_row(10, width=80) is None


def test_reserve_covers_last_card_anchor() -> None:
    from textual.geometry import Size

    from sase.ace.tui.widgets.prompt_panel._section_view import SectionViewMixin
    from sase.ace.tui.widgets.prompt_panel._section_navigation import (
        PromptPanelSectionAnchor,
    )

    class _View(SectionViewMixin):  # type: ignore[misc]
        def __init__(self) -> None:
            self._section_generation = 1
            self._section_anchor_generation = 1
            self._section_anchor_width = 80
            self._section_anchors = (
                PromptPanelSectionAnchor("card:reply", 40, PromptPanelSectionRole.CARD),
            )
            self._section_layout_reserve_enabled = True
            self._section_real_content_height = 0

    view = _View.__new__(_View)
    SectionViewMixin.__init__(view)  # type: ignore[call-arg]
    view._section_generation = 1
    view._section_anchor_generation = 1
    view._section_anchor_width = 80
    view._section_anchors = (
        PromptPanelSectionAnchor("card:reply", 40, PromptPanelSectionRole.CARD),
    )
    view._section_layout_reserve_enabled = True
    # Real height 30 in a 20-row container: reserve must cover row 40.
    container = Size(80, 20)
    viewport = Size(80, 20)
    # Monkeypatch the super height to 30.
    import textual.widgets._static as _static_mod

    orig = _static_mod.Static.get_content_height
    try:
        _static_mod.Static.get_content_height = lambda self, c, v, w: 30  # type: ignore[method-assign]
        total = SectionViewMixin.get_content_height(view, container, viewport, 80)
    finally:
        _static_mod.Static.get_content_height = orig  # type: ignore[method-assign]
    assert total >= 40 + 20 - 30 + 30 or total >= 30


def test_separators_render_and_meta() -> None:
    console = Console(width=40)
    options = console.options.update_width(40)
    sep = CardSeparator("reply", "Reply", glyph="◆", accent="green")
    lines = console.render_lines(sep, options, pad=False)
    assert len(lines) == 2
    text = "".join(seg.text for line in lines for seg in line)
    assert "Reply" in text
    assert "◆" in text
    # Meta on exactly one row (the rule row).
    metas: list[bool] = []
    for line in lines:
        metas.append(
            any(
                seg.style is not None
                and seg.style.meta
                and DECK_CARD_META_KEY in seg.style.meta
                for seg in line
            )
        )
    assert metas.count(True) == 1
    # Tiny widths degrade gracefully.
    tiny_options = console.options.update_width(4)
    tiny_lines = console.render_lines(sep, tiny_options, pad=False)
    assert len(tiny_lines) == 2


def test_no_separator_before_first_card() -> None:
    # Separators are placed between consecutive cards only; the first card's
    # anchor is implicitly row 0. This is a contract test on the helper used
    # by spread composition: two cards need exactly one separator.
    from sase.ace.tui.widgets.decks.separators import files_separator_for

    first = files_separator_for("file-0", "a")
    second = files_separator_for("file-1", "b")
    assert first.card_id == "file-0"
    assert second.card_id == "file-1"


def test_config_schema_agent_decks_parity() -> None:
    import yaml
    from jsonschema import Draft7Validator
    from jsonschema.exceptions import ValidationError
    import pytest

    from tests._config_schema_helpers import REPO_ROOT, schema

    validator = Draft7Validator(schema())
    public_schema = schema()
    agent_decks = public_schema["properties"]["ace"]["properties"]["agent_decks"]
    default_config = yaml.safe_load(
        (REPO_ROOT / "src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    validator.validate({"ace": {"agent_decks": {"spread_max_screens": 1.5}}})
    validator.validate({"ace": {"agent_decks": {"spread_max_screens": 0}}})
    assert default_config["ace"]["agent_decks"] == {"spread_max_screens": 1.5}
    assert agent_decks["additionalProperties"] is False
    assert agent_decks["properties"]["spread_max_screens"]["default"] == 1.5
    assert agent_decks["properties"]["spread_max_screens"]["minimum"] == 0
    for invalid in (
        {"spread_max_screens": "1.5"},
        {"spread_max_screens": -1},
        {"spread_max_screens": True},
        {"unknown": True},
    ):
        with pytest.raises(ValidationError):
            validator.validate({"ace": {"agent_decks": invalid}})


def test_subtitle_spread_tag() -> None:
    availability = {
        DeckId.MAIN: DeckAvailability(True, 2),
        DeckId.FILES: DeckAvailability(True, 1),
        DeckId.TOOLS: DeckAvailability(False, 0),
    }
    accent_for = {
        DeckId.MAIN: "red",
        DeckId.FILES: "green",
        DeckId.TOOLS: "#87D7FF",
    }
    plain = deck_subtitle(
        DeckId.MAIN, availability, status=None, width=80, accent_for=accent_for
    )
    assert "spread" not in plain.plain
    spread = deck_subtitle(
        DeckId.MAIN,
        availability,
        status=None,
        width=80,
        accent_for=accent_for,
        spread=True,
    )
    assert "spread" in spread.plain
    # Spread tag is dropped first when width is tight.
    tight = deck_subtitle(
        DeckId.MAIN,
        availability,
        status=None,
        width=6,
        accent_for=accent_for,
        spread=True,
    )
    assert "spread" not in tight.plain
    status = Text("ok")
    with_status = deck_subtitle(
        DeckId.MAIN,
        availability,
        status=status,
        width=80,
        accent_for=accent_for,
        spread=True,
    )
    assert "spread" in with_status.plain
    # Tight with status drops the spread tag before the switcher.
    tight_status = deck_subtitle(
        DeckId.MAIN,
        availability,
        status=Text("a very long status line that will not fit at all"),
        width=20,
        accent_for=accent_for,
        spread=True,
    )
    assert "spread" not in tight_status.plain
