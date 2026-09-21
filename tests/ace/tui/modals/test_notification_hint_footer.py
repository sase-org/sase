"""Tests for the width-aware notification modal footer hint line."""

from rich.cells import cell_len

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_constants import (
    DEFAULT_HINT_TEXT,
    GATE_HINT_TEXT,
    NOTIFICATION_HINT_FALLBACK_WIDTH,
    QUESTION_HINT_TEXT,
    notification_hint_text,
    notification_hint_tier,
)
from sase.ace.tui.modals.notification_modal_footer import NotificationHintFooter

from tests._notification_modal_helpers import _make_notification

_VARIANTS = ("default", "question", "gate")


def test_hint_variants_fit_modal_content_width_at_120_columns() -> None:
    """Every variant fits the 120-column modal and keeps close and +1.

    Pins the bead invariant by measurement, not string equality: the modal
    content is NOTIFICATION_HINT_FALLBACK_WIDTH cells wide at 120 columns.
    """
    for variant in _VARIANTS:
        text = notification_hint_text(variant, NOTIFICATION_HINT_FALLBACK_WIDTH)
        assert cell_len(text) <= NOTIFICATION_HINT_FALLBACK_WIDTH
        assert "+: +1" in text
        assert "q: close" in text


def test_hint_footer_first_paint_fits_120_column_modal() -> None:
    """A fresh footer already fits the 120-column modal before any resize.

    The widget cannot measure its own width before layout (width auto sizes
    to the content), so the constructor renders at the fallback content
    width instead of the full tier: close and +1 are visible on first paint,
    not only after the first resize event.
    """
    for variant in _VARIANTS:
        text = str(NotificationHintFooter(variant).content)
        assert cell_len(text) <= NOTIFICATION_HINT_FALLBACK_WIDTH
        assert "+: +1" in text
        assert "q: close" in text


def test_close_and_plus_one_survive_every_tier() -> None:
    """Close and +1 hints are present at every measured width."""
    for variant in _VARIANTS:
        for width in (200, 108, 100, 87, 60, 30, 21, 10):
            text = notification_hint_text(variant, width)
            assert "+: +1" in text, (variant, width)
            assert "q: close" in text, (variant, width)


def test_full_tier_preserves_legacy_hint_strings() -> None:
    """A wide modal renders exactly the long-standing hint strings."""
    assert notification_hint_text("default", 10**6) == DEFAULT_HINT_TEXT
    assert notification_hint_text("question", 10**6) == QUESTION_HINT_TEXT
    assert notification_hint_text("gate", 10**6) == GATE_HINT_TEXT


def test_compact_tier_sheds_file_navigation_first() -> None:
    """The 120-column tier drops file-nav entries but keeps navigation aids."""
    text = notification_hint_text("default", NOTIFICATION_HINT_FALLBACK_WIDTH)
    assert notification_hint_tier("default", NOTIFICATION_HINT_FALLBACK_WIDTH) == (
        "compact"
    )
    assert "C-n/C-p" not in text
    assert "V: view" not in text
    assert "Enter: select" in text
    assert "S: sections" in text
    assert "1-0/[]: tab" in text


class _RecordingFooter:
    """Minimal footer double without the widget's tier machinery."""

    def __init__(self) -> None:
        self.updated: str | None = None
        self.variant: str | None = None

    def update(self, text: str) -> None:
        self.updated = text


def _modal_with_footer(
    notification_action: str | None,
) -> tuple[NotificationModal, _RecordingFooter]:
    """Return a modal whose footer updates are recorded, not rendered."""
    modal = NotificationModal([_make_notification("n1", action=notification_action)])
    footer = _RecordingFooter()
    modal._get_highlighted_notification = (  # type: ignore[method-assign]
        lambda: modal._notifications[0]
    )
    modal.query_one = lambda *args, **kwargs: footer  # type: ignore[method-assign]
    return modal, footer


def test_update_hint_footer_selects_question_variant() -> None:
    modal, footer = _modal_with_footer("UserQuestion")
    modal._update_hint_footer()
    assert footer.updated is not None
    assert cell_len(footer.updated) <= NOTIFICATION_HINT_FALLBACK_WIDTH
    assert "Enter: answer" in footer.updated


def test_update_hint_footer_selects_gate_variant() -> None:
    modal, footer = _modal_with_footer("HITL")
    modal._update_hint_footer()
    assert footer.updated is not None
    assert cell_len(footer.updated) <= NOTIFICATION_HINT_FALLBACK_WIDTH
    assert "Enter: review" in footer.updated


def test_update_hint_footer_selects_default_variant() -> None:
    modal, footer = _modal_with_footer(None)
    modal._update_hint_footer()
    assert footer.updated is not None
    assert cell_len(footer.updated) <= NOTIFICATION_HINT_FALLBACK_WIDTH
    assert "Enter: select" in footer.updated


class _RecordingHintFooter(NotificationHintFooter):
    """Widget that records repaint text instead of rendering it."""

    def __init__(self, variant: str = "default") -> None:
        self.repaints: list[str] = []
        super().__init__(variant)

    def update(self, content: object = "", *, layout: bool = True) -> None:
        self.repaints.append(str(content))


def _resize_to(width: int) -> object:
    """Build the narrowest event double the widget's resize path reads."""
    return type("Resize", (), {"size": type("Size", (), {"width": width})()})()


def test_hint_footer_widget_repaints_on_variant_and_width() -> None:
    """The widget picks the tier from its measured width, not a snapshot."""
    footer = _RecordingHintFooter("default")
    # First paint already renders the fallback-width tier, so a resize to
    # the same width is correctly a no-op rather than a repaint.
    assert str(footer.content) == notification_hint_text("default", 108)
    footer.on_resize(_resize_to(108))  # type: ignore[arg-type]
    assert footer.repaints == []
    footer.set_variant("question")
    assert footer.repaints[-1] == notification_hint_text("question", 108)
    footer.on_resize(_resize_to(40))  # type: ignore[arg-type]
    assert footer.repaints[-1] == notification_hint_text("question", 40)
    assert cell_len(footer.repaints[-1]) <= 40
    assert "q: close" in footer.repaints[-1]
