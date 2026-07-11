"""Row and description rendering helpers for the Models panel."""

from __future__ import annotations

from collections.abc import Iterable

from rich.text import Text

from sase.ace.tui.provider_styles import provider_model_badge_markup
from sase.llm_provider import AliasView, BucketView
from sase.llm_provider.config import DEFAULT_MODEL_ALIAS_NAME
from sase.llm_provider.temporary_override import TemporaryLLMOverride

from .models_panel_duration import format_remaining

_KIND_CELL = 13
_NAME_CELL = 16

# The provider/model badge is treated as its own column so the rightmost
# state/provenance tag lines up across rows. The column is sized to the widest
# badge currently visible, capped so the state tag stays inside the 84-column
# modal budget: content width (78, after the double border and 1 2 padding)
# minus the fixed kind/name columns and their inner spaces (31), minus the
# fixed gap before the state tag (3), minus the longest state tag
# ("override · until cleared", 24) leaves 20 columns for the badge.
PROVIDER_MODEL_CELL_MAX = 20
_STATE_GAP = "   "

_KIND_LABELS: dict[str, str] = {
    "default": "default",
    "role": "role",
    "provider_coder": "coder",
    "user": "user",
}

_KIND_STYLES: dict[str, str] = {
    "default": "bold #87D7FF",
    "role": "bold #87D7AF",
    "provider_coder": "bold #AFAFFF",
    "user": "bold #D7AF87",
}

_OVERRIDE_TAG_STYLE = "bold #AF87FF"
_CONFIGURED_TAG_STYLE = "#87D787"
_IMPLICIT_TAG_STYLE = "dim #9E9E9E"
_DESCRIPTION_STYLE = "italic #B0B0B0"
_DESCRIPTION_MISSING_STYLE = "italic #D7AF87"
_BUCKET_STYLE = "bold #FFD787"
_BUCKET_DIM_STYLE = "dim #FFD787"


def _pad(value: str, width: int) -> str:
    """Truncate-or-pad *value* to exactly *width* columns."""
    if len(value) > width:
        return value[: max(0, width - 1)] + "…"
    return value.ljust(width)


def kind_label(view: AliasView) -> str:
    """Return the small kind badge text for *view*."""
    return _KIND_LABELS.get(view.kind, view.kind)


def _override_chip(override: TemporaryLLMOverride, now: float) -> str:
    """Render the active-override state chip (``override · 15m left``)."""
    if override.expires_at is None:
        return "override · until cleared"
    return f"override · {format_remaining(override.expires_at - now)} left"


def state_tag(view: AliasView, now: float) -> tuple[str, str]:
    """Return ``(text, style)`` for the provenance / override state column."""
    if view.override is not None:
        return _override_chip(view.override, now), _OVERRIDE_TAG_STYLE
    if view.configured:
        return "configured", _CONFIGURED_TAG_STYLE
    if view.name == DEFAULT_MODEL_ALIAS_NAME:
        return "implicit", _IMPLICIT_TAG_STYLE
    if view.kind == "provider_coder":
        return "implicit → @coder", _IMPLICIT_TAG_STYLE
    return "implicit → @default", _IMPLICIT_TAG_STYLE


def _provider_model_text(view: AliasView) -> Text:
    """Build the themed ``PROVIDER(model)`` badge for *view* as a Rich ``Text``.

    Building a ``Text`` (rather than leaving the raw markup string) keeps the
    badge measurable and truncatable while preserving provider styling - and
    ensures no markup ever leaks into a rendered row.
    """
    return Text.from_markup(provider_model_badge_markup(view.provider, view.model))


def provider_model_column_width(views: Iterable[AliasView]) -> int:
    """Return the provider/model column width (in cells) for *views*.

    Sized to the widest badge currently visible, capped by
    :data:`PROVIDER_MODEL_CELL_MAX` so the state tag stays on-screen. Rich cell
    widths are used (not ``len``) so wide glyphs and future badges are measured
    correctly. Collapses to ``0`` when no row has a badge.
    """
    widest = 0
    for view in views:
        widest = max(widest, _provider_model_text(view).cell_len)
    return min(widest, PROVIDER_MODEL_CELL_MAX)


def render_alias_row(view: AliasView, *, now: float, provider_model_width: int) -> Text:
    """Render one alias row as a single-line Rich ``Text``.

    Layout: ``<kind badge> <alias name> <PROVIDER(model) badge> <state tag>``.
    The provider/model badge is fitted to *provider_model_width* - padded when
    short and ellipsized when it exceeds the cap - so the rightmost state tag
    starts at the same cell across every row. Building a ``Text`` (rather than
    a markup string) keeps alias/model values literal so a stray bracket in a
    config value can never break rendering.
    """
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(_pad(kind_label(view), _KIND_CELL), style=_KIND_STYLES.get(view.kind))
    text.append(" ")
    text.append(_pad(view.name, _NAME_CELL), style="bold")
    text.append(" ")
    badge = _provider_model_text(view)
    badge.truncate(provider_model_width, overflow="ellipsis", pad=True)
    text.append_text(badge)
    text.append(_STATE_GAP)
    tag_text, tag_style = state_tag(view, now)
    text.append(tag_text, style=tag_style)
    return text


def render_bucket_row(bucket: BucketView, *, provider_model_width: int) -> Text:
    """Render one collapsed bucket using the alias-row column skeleton."""
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(_pad("▸ bucket", _KIND_CELL), style=_BUCKET_STYLE)
    text.append(" ")
    text.append(_pad(bucket.name, _NAME_CELL), style="bold")
    text.append(" ")
    count_label = f"{bucket.alias_count} aliases"
    text.append(_pad(count_label, provider_model_width), style="dim")
    text.append(_STATE_GAP)
    if bucket.override_count:
        text.append(
            f"override · {bucket.override_count} active", style=_OVERRIDE_TAG_STYLE
        )
    else:
        text.append("bucket", style=_BUCKET_DIM_STYLE)
    return text


def description_text_for_view(view: AliasView | None) -> Text:
    """Return the two-line description strip content for *view*."""
    if view is None:
        return Text("", style=_DESCRIPTION_STYLE)
    if view.description:
        return Text(view.description, style=_DESCRIPTION_STYLE)
    if view.kind == "user":
        return Text(
            "no description - set "
            f"llm_provider.model_aliases.custom.{view.name}.description",
            style=_DESCRIPTION_MISSING_STYLE,
        )
    return Text("", style=_DESCRIPTION_STYLE)


def _description_text_for_bucket(bucket: BucketView) -> Text:
    """Return the two-line description and effective-model mix for *bucket*."""
    text = Text()
    if bucket.description:
        text.append(bucket.description, style=_DESCRIPTION_STYLE)
    else:
        text.append(
            "no description - set "
            f"llm_provider.model_aliases.buckets.{bucket.name}.description",
            style=_DESCRIPTION_MISSING_STYLE,
        )
    text.append("\n")
    text.append(
        " · ".join(f"{model} ×{count}" for model, count in bucket.model_counts),
        style="dim",
    )
    return text


def description_text_for_row(row: AliasView | BucketView | None) -> Text:
    """Dispatch Models-panel description rendering by row type."""
    if isinstance(row, BucketView):
        return _description_text_for_bucket(row)
    return description_text_for_view(row)
