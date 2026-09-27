"""Deferred Main view bodies: badge-first P transitions (D10).

The synchronous prefix of a user-initiated Main view change flips the badge
(``_render_mode`` + ``refresh_chrome``) and returns. The reply strips for the
destination body are built off the UI thread with ``asyncio.to_thread`` on a
private ``rich.console.Console``. The UI thread then applies the prebuilt
strips (generation-guarded) so the Rich walk never runs on the event loop
and the stall watchdog stays quiet.

Pixel guarantee: the off-thread render replicates Textual's
``RichVisual.render_strips`` exactly. The UI thread snapshots
:func:`capture_prebuilt_context` — the app console options, the widget's
``post_render``-wrapped renderable under the current compositor base style,
and that style's token — and the worker renders the wrapped renderable on a
private console built with the same settings Textual's ``App`` uses
(``markup=True, emoji=False, safe_box=False, force_terminal=True,
soft_wrap=False``) with options derived the same way
(``highlight=False``, full height, ``update_width``). Skipping either step
drifts: without the mirror console, box/emoji/color output differs; without
``post_render`` plus the base style, unstyled segments miss the panel
background (and Textual's link-style pass drops them entirely).

Prebuilt bodies are keyed by ``(digest, width, style_token)`` for full
paints only. The style token keeps a focus or accent change from serving
strips painted under another base style; a token miss falls back to the
synchronous render. The widget link style is widget-CSS-fixed (it does not
vary with focus), so it is captured inside the wrapped renderable rather
than the key. Textual's post-render link walk still runs on the UI thread
over the returned strips.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Literal, cast

from rich.console import Console, ConsoleOptions, Group
from rich.segment import Segment
from textual import constants as textual_constants
from textual.app import _NullFile
from textual.strip import Strip

_PREBUILT_MAX_ENTRIES = 8
_prebuilt_bodies: OrderedDict[
    tuple[str, int, str], tuple[tuple[Strip, ...], int, tuple[Any, ...]]
] = OrderedDict()


@dataclass(frozen=True, slots=True)
class PrebuiltRenderContext:
    """UI-thread inputs for one faithful off-thread Main body render."""

    options: ConsoleOptions
    wrapped: Any
    style_token: str


def capture_prebuilt_context(
    app: Any, view: Any, renderable: Any
) -> PrebuiltRenderContext | None:
    """Snapshot the inputs :func:`build_prebuilt_offthread` needs.

    Runs on the UI thread: reads ``app.console_options``, the view's last
    compositor base style, and wraps ``renderable`` with
    ``view.post_render`` under that style. Returns None when the view has
    never painted (no base style yet) so callers fall back to synchronous.
    """
    try:
        options = app.console_options
    except Exception:
        return None
    try:
        tracking = view.render()
        base_style = getattr(tracking, "_last_base_style", None)
    except Exception:
        return None
    if base_style is None:
        return None
    try:
        wrapped = view.post_render(renderable, base_style.rich_style)
    except Exception:
        return None
    try:
        from sase.ace.tui.widgets.prompt_panel._section_navigation import (
            textual_style_token,
        )

        style_token = textual_style_token(base_style)
    except Exception:
        return None
    if not style_token:
        return None
    return PrebuiltRenderContext(
        options=options, wrapped=wrapped, style_token=style_token
    )


def store_prebuilt(
    digest: str | None,
    width: int,
    strips: tuple[Strip, ...],
    height: int,
    anchors: tuple[Any, ...],
    style_token: str = "",
) -> None:
    """Store a full-document prebuilt body, capped at 8 entries."""
    if digest is None or width <= 0:
        return
    key = (digest, int(width), str(style_token))
    _prebuilt_bodies[key] = (strips, int(height), anchors)
    _prebuilt_bodies.move_to_end(key)
    if len(_prebuilt_bodies) > _PREBUILT_MAX_ENTRIES:
        _prebuilt_bodies.popitem(last=False)


def get_prebuilt(
    digest: str | None, width: int, style_token: str = ""
) -> tuple[tuple[Strip, ...], int, tuple[Any, ...]] | None:
    """Return the prebuilt body for ``(digest, width, style_token)``."""
    if digest is None or width <= 0:
        return None
    key = (digest, int(width), str(style_token))
    entry = _prebuilt_bodies.get(key)
    if entry is None:
        return None
    _prebuilt_bodies.move_to_end(key)
    return entry


def get_prebuilt_height(digest: str | None, width: int) -> int | None:
    """Return any stored full height for ``(digest, width)``.

    Height does not vary with the base style, so every style variant
    shares it.
    """
    if digest is None or width <= 0:
        return None
    for (entry_digest, entry_width, _), (_, height, _) in _prebuilt_bodies.items():
        if entry_digest == digest and entry_width == int(width):
            return int(height)
    return None


def get_prebuilt_anchors(digest: str | None, width: int) -> tuple[Any, ...] | None:
    """Return stored anchors for ``(digest, width)``, any style variant."""
    if digest is None or width <= 0:
        return None
    for (entry_digest, entry_width, _), (_, _, anchors) in _prebuilt_bodies.items():
        if entry_digest == digest and entry_width == int(width):
            return anchors
    return None


def _faithful_console(width: int) -> Console:
    """Build a private console matching Textual's ``App.console`` settings."""
    return Console(
        color_system=cast(
            "Literal['auto', 'standard', '256', 'truecolor', 'windows'] | None",
            textual_constants.COLOR_SYSTEM,
        ),
        file=_NullFile(),  # type: ignore[arg-type]
        markup=True,
        highlight=False,
        emoji=False,
        legacy_windows=False,
        force_terminal=True,
        safe_box=False,
        soft_wrap=False,
        width=max(1, int(width)),
    )


def build_prebuilt_offthread(
    context: PrebuiltRenderContext, width: int
) -> tuple[tuple[Strip, ...], int, tuple[Any, ...]]:
    """Render the captured body to full strips/height/anchors off the loop.

    Uses a private mirror console plus the UI-thread ``ConsoleOptions``
    snapshot, derived exactly like ``RichVisual.render_strips`` (full
    height, ``update_width``). Never touches widgets, the app console, or
    shared caches. Callers store the result with :func:`store_prebuilt` on
    the UI thread under ``context.style_token``.
    """
    from sase.ace.tui.widgets.prompt_panel._section_navigation import (
        segment_section_identity,
    )

    render_width = max(1, int(width))
    console = _faithful_console(render_width)
    options = context.options.update(
        highlight=False, width=render_width, height=None
    ).update_width(render_width)
    segments = console.render(context.wrapped, options)
    strips = [
        Strip(line)
        for line in Segment.split_and_crop_lines(
            segments, render_width, include_new_lines=False, pad=False
        )
    ]
    anchors: list[Any] = []
    seen: set[str] = set()
    for row, strip in enumerate(strips):
        for segment in strip:
            resolved = segment_section_identity(segment)
            if resolved is None:
                continue
            identity, role = resolved
            if identity not in seen:
                seen.add(identity)
                # Anchor type is PromptPanelSectionAnchor; keep Any here to
                # avoid importing widget types off-thread.
                from sase.ace.tui.widgets.prompt_panel._section_navigation import (
                    PromptPanelSectionAnchor,
                )

                anchors.append(PromptPanelSectionAnchor(identity, row, role))
    return (tuple(strips), len(strips), tuple(anchors))


def build_destination_renderable(
    document: Any,
    *,
    spread: bool,
    target_card_id: str | None,
    anchor_block_id: str | None,
    want_paged_blocks: bool,
    spread_accent: str = "",
) -> tuple[Any, str | None]:
    """Build the destination Group and digest without touching widgets."""
    digest = getattr(document, "digest", None)
    if spread:
        from .separators import card_separator_for
        from .model import DeckId

        parts: list[Any] = []
        try:
            cards = list(document.cards)
        except Exception:
            cards = []
        for index, card in enumerate(cards):
            if index > 0:
                try:
                    parts.append(
                        card_separator_for(DeckId.MAIN, card, accent=spread_accent)
                    )
                except Exception:
                    pass
            try:
                parts.extend(list(card.renderables))
            except Exception:
                pass
        spread_digest = None if digest is None else f"{digest}:spread"
        return (Group(*parts), spread_digest)
    card = None
    if target_card_id is not None:
        try:
            card = document.card(target_card_id)
        except Exception:
            card = None
    if card is None:
        return (Group(), None if digest is None else f"{digest}:{target_card_id}")
    if want_paged_blocks and anchor_block_id is not None:
        try:
            page = card.block_page(anchor_block_id)
        except Exception:
            page = None
        if page is not None:
            page_digest = (
                None if digest is None else f"{digest}:{card.card_id}:{anchor_block_id}"
            )
            return (Group(*page), page_digest)
    try:
        renderables = list(card.renderables)
    except Exception:
        renderables = []
    try:
        block_ids = tuple(getattr(card, "block_ids", ()) or ())
    except Exception:
        block_ids = ()
    if not want_paged_blocks and len(block_ids) >= 2 and digest is not None:
        card_digest: str | None = f"{digest}:{card.card_id}:spread"
    else:
        card_digest = None if digest is None else f"{digest}:{card.card_id}"
    return (Group(*renderables), card_digest)


__all__ = [
    "PrebuiltRenderContext",
    "build_destination_renderable",
    "build_prebuilt_offthread",
    "capture_prebuilt_context",
    "get_prebuilt",
    "get_prebuilt_anchors",
    "get_prebuilt_height",
    "store_prebuilt",
]
