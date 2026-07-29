"""Row and description rendering helpers for the Models panel."""

from __future__ import annotations

from collections.abc import Iterable

from rich.text import Text

from sase.ace.tui.model_alias_styles import (
    MODEL_ALIAS_KIND_STYLES,
    OWNERSHIP_ACCENT,
    alias_kind_label,
    alias_state_text,
    append_alias_reference,
    append_effort_suffix,
    append_pool_chip,
    provider_model_text,
)
from sase.llm_provider import AliasView, BucketView, ModelsPanelSection
from sase.llm_provider.config import DEFAULT_MODEL_ALIAS_NAME
from sase.llm_provider.temporary_override import TemporaryLLMOverride

from .models_panel_duration import format_remaining

_KIND_CELL = 13
_NAME_CELL = 22
_OWNERSHIP_GUTTER_CELL = 2

# The provider/model badge is treated as its own column so the rightmost
# state/provenance tag lines up across rows. The column is sized to the widest
# badge currently visible, capped so the state tag stays inside the preferred
# 110-column modal budget. Its roughly 100-cell option rows leave room for the
# fixed kind/name columns, inner spaces, state gap, longest state tag, and a
# 32-cell provider/model badge. Narrow viewports fall back to whole-row
# ellipsis via the Rich Text returned by :func:`render_alias_row`.
PROVIDER_MODEL_CELL_MAX = 32
_STATE_GAP = "   "

_OVERRIDE_TAG_STYLE = "bold #AF87FF"
_IMPLICIT_TAG_STYLE = "dim #9E9E9E"
_DESCRIPTION_STYLE = "italic #B0B0B0"
_DESCRIPTION_MISSING_STYLE = "italic #D7AF87"
_BUCKET_STYLE = "bold #FFD787"
_BUCKET_DIM_STYLE = "dim #FFD787"
_WARNING_STYLE = "bold #FFD75F"
_POOL_AVAILABLE_STYLE = "#87D787"
_POOL_UNAVAILABLE_STYLE = "#D78787"
_OWNERSHIP_STYLE = f"bold {OWNERSHIP_ACCENT}"
_BUILTIN_SECTION_STYLE = "bold #87D7FF"

_CUSTOM_ALIASES_PATH = "llm_provider.model_aliases.custom"
_BUILTIN_ALIASES_PATH = "llm_provider.model_aliases.builtin"


def _pad(value: str, width: int) -> str:
    """Truncate-or-pad *value* to exactly *width* columns."""
    if len(value) > width:
        return value[: max(0, width - 1)] + "…"
    return value.ljust(width)


def _append_ownership_gutter(text: Text, *, user_owned: bool) -> None:
    """Append the fixed-width ownership gutter to *text*."""
    if user_owned:
        text.append("▌", style=_OWNERSHIP_STYLE)
        text.append(" ")
    else:
        text.append(" " * _OWNERSHIP_GUTTER_CELL)


def _count_label(count: int, singular: str) -> str:
    """Return a correctly singularized count label."""
    noun = (
        singular if count == 1 else "aliases" if singular == "alias" else f"{singular}s"
    )
    return f"{count} {noun}"


def _section_count_label(section: ModelsPanelSection) -> str:
    """Return the state-column count label for a section header."""
    label = _count_label(section.alias_count, "alias")
    if section.bucket_count:
        label += f" · {_count_label(section.bucket_count, 'bucket')}"
    return label


def render_section_header(
    section: ModelsPanelSection,
    *,
    provider_model_width: int,
) -> Text:
    """Render a disabled section header on the same grid as data rows."""
    text = Text(no_wrap=True, overflow="ellipsis")
    _append_ownership_gutter(text, user_owned=section.is_user_owned)
    label = "Custom" if section.is_user_owned else "Built-in"
    rule_width = _KIND_CELL + 1 + _NAME_CELL + 1 + provider_model_width
    rule_label = f"── {label} "
    rule = rule_label + ("─" * max(0, rule_width - len(rule_label)))
    rule_style = _OWNERSHIP_STYLE if section.is_user_owned else _BUILTIN_SECTION_STYLE
    text.append(_pad(rule, rule_width), style=rule_style)
    text.append(_STATE_GAP)
    text.append(_section_count_label(section), style="dim")
    return text


def render_empty_custom_hint() -> Text:
    """Render the disabled hint shown when the user section has no rows."""
    text = Text(no_wrap=True, overflow="ellipsis")
    _append_ownership_gutter(text, user_owned=False)
    text.append(
        f"No custom aliases · declare them under {_CUSTOM_ALIASES_PATH}",
        style="dim italic",
    )
    return text


def kind_label(view: AliasView) -> str:
    """Return the small kind badge text for *view*."""
    # Keep the Models panel's established ``user`` label while the denser
    # completion table uses the clearer shared ``custom`` vocabulary.
    if view.kind == "user":
        return "user"
    return alias_kind_label(view.kind)


def custom_builtin_shadow_warning_message(names: Iterable[str]) -> str:
    """Return actionable opening-toast text for misplaced builtin aliases."""
    aliases = tuple(f"@{name}" for name in sorted(names))
    if len(aliases) == 1:
        return (
            f"Builtin alias {aliases[0]} is configured under {_CUSTOM_ALIASES_PATH}. "
            f"Move its model value from {_CUSTOM_ALIASES_PATH} to "
            f"{_BUILTIN_ALIASES_PATH}."
        )
    return (
        f"Builtin aliases {', '.join(aliases)} are configured under "
        f"{_CUSTOM_ALIASES_PATH}. Move each custom entry's model value from "
        f"{_CUSTOM_ALIASES_PATH} to {_BUILTIN_ALIASES_PATH}."
    )


def _custom_builtin_shadow_description(names: Iterable[str]) -> Text:
    """Return the two-line persistent warning for highlighted problem rows."""
    aliases = tuple(f"@{name}" for name in sorted(names))
    noun = "alias" if len(aliases) == 1 else "aliases"
    pronoun = "its model value" if len(aliases) == 1 else "their model values"
    text = Text(style=_WARNING_STYLE, no_wrap=True, overflow="ellipsis")
    text.append(f"! Misplaced builtin {noun}: {', '.join(aliases)}")
    text.append(
        f"\nMove {pronoun} from {_CUSTOM_ALIASES_PATH} to {_BUILTIN_ALIASES_PATH}."
    )
    return text


def _override_chip(override: TemporaryLLMOverride, now: float) -> str:
    """Render the active-override state chip (``override · 15m left``)."""
    if override.expires_at is None:
        return "override · until cleared"
    return f"override · {format_remaining(override.expires_at - now)} left"


def state_tag(view: AliasView, now: float) -> Text:
    """Return the styled provenance / override state column for *view*."""
    if view.override is not None:
        return Text(_override_chip(view.override, now), style=_OVERRIDE_TAG_STYLE)
    reference = ""
    if view.configured and view.references is not None:
        reference = view.references
    elif (
        not view.configured
        and view.name != DEFAULT_MODEL_ALIAS_NAME
        and view.implicit_fallback is not None
    ):
        reference = view.implicit_fallback
    members = view.selector_members if view.selector_mode == "round_robin" else ()
    text = alias_state_text("configured" if view.configured else "implicit")
    if members:
        append_pool_chip(
            text,
            sum(member.available for member in members),
            len(members),
        )
    elif reference:
        append_alias_reference(text, reference, view.reference_effort or "")
    return text


def _provider_model_text(view: AliasView) -> Text:
    """Build the shared provider/model badge for one alias view."""
    text = provider_model_text(view.provider, view.model)
    append_effort_suffix(text, view.effort or "")
    return text


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

    Layout: ``<ownership> <kind> <name> <PROVIDER(model)> <state>``.
    The provider/model badge is fitted to *provider_model_width* - padded when
    short and ellipsized when it exceeds the cap - so the rightmost state tag
    starts at the same cell across every row. Building a ``Text`` (rather than
    a markup string) keeps alias/model values literal so a stray bracket in a
    config value can never break rendering.
    """
    text = Text(no_wrap=True, overflow="ellipsis")
    _append_ownership_gutter(text, user_owned=view.is_user_owned)
    kind = kind_label(view)
    if view.is_custom_builtin_shadow:
        text.append(_pad(f"! {kind}", _KIND_CELL), style=_WARNING_STYLE)
    else:
        text.append(
            _pad(kind, _KIND_CELL),
            style=MODEL_ALIAS_KIND_STYLES.get(view.kind),
        )
    text.append(" ")
    text.append(_pad(view.name, _NAME_CELL), style="bold")
    text.append(" ")
    badge = _provider_model_text(view)
    badge.truncate(provider_model_width, overflow="ellipsis", pad=True)
    text.append_text(badge)
    text.append(_STATE_GAP)
    text.append_text(state_tag(view, now))
    return text


def render_bucket_row(bucket: BucketView, *, provider_model_width: int) -> Text:
    """Render one collapsed bucket using the alias-row column skeleton."""
    text = Text(no_wrap=True, overflow="ellipsis")
    _append_ownership_gutter(text, user_owned=bucket.is_user_owned)
    bucket_label = "▸ ! bucket" if bucket.custom_builtin_shadow_count else "▸ bucket"
    bucket_style = (
        _WARNING_STYLE
        if bucket.custom_builtin_shadow_count
        else _OWNERSHIP_STYLE
        if bucket.is_user_owned
        else _BUCKET_STYLE
    )
    text.append(_pad(bucket_label, _KIND_CELL), style=bucket_style)
    text.append(" ")
    name_style = _OWNERSHIP_STYLE if bucket.is_user_owned else "bold"
    text.append(_pad(bucket.name, _NAME_CELL), style=name_style)
    text.append(" ")
    count_label = _count_label(bucket.alias_count, "alias")
    text.append(_pad(count_label, provider_model_width), style="dim")
    text.append(_STATE_GAP)
    if bucket.custom_builtin_shadow_count:
        text.append(
            f"! {bucket.custom_builtin_shadow_count} misplaced", style=_WARNING_STYLE
        )
        if bucket.override_count:
            text.append(
                f" · {bucket.override_count} override",
                style=_OVERRIDE_TAG_STYLE,
            )
    elif bucket.override_count:
        text.append(
            f"override · {bucket.override_count} active", style=_OVERRIDE_TAG_STYLE
        )
    else:
        bucket_state_style = (
            _OWNERSHIP_STYLE if bucket.is_user_owned else _BUCKET_DIM_STYLE
        )
        text.append("bucket", style=bucket_state_style)
    if not bucket.is_user_owned and bucket.user_member_count:
        text.append(" · ", style=_IMPLICIT_TAG_STYLE)
        text.append(
            f"{bucket.user_member_count} custom",
            style=_OWNERSHIP_STYLE,
        )
    return text


def description_text_for_view(
    view: AliasView | None,
    default_effort: str | None = None,
) -> Text:
    """Return the two-line description strip content for *view*."""
    if view is None:
        return Text("", style=_DESCRIPTION_STYLE)
    if view.is_custom_builtin_shadow:
        return _custom_builtin_shadow_description((view.name,))
    text = Text()
    if view.description:
        text.append(view.description, style=_DESCRIPTION_STYLE)
    elif view.kind == "user":
        text.append(
            "no description - set "
            f"llm_provider.model_aliases.custom.{view.name}.description",
            style=_DESCRIPTION_MISSING_STYLE,
        )
    if view.selector_members:
        if text:
            text.append("\n")
        label = "pool" if view.selector_mode == "round_robin" else "fallback"
        suspended = view.override is not None
        if suspended:
            label = f"{label} (suspended by override)"
        text.append(f"{label}: ", style="dim")
        for index, member in enumerate(view.selector_members):
            if index:
                text.append(" · ", style="dim")
            if member.selected and not suspended:
                arrow_style = (
                    "bold #FFD75F"
                    if not member.valid
                    else f"bold {'#87D787' if member.available else '#D78787'}"
                )
                text.append("→ ", style=arrow_style)
            if member.valid:
                marker = "✓" if member.available else "×"
                target = member.target
                if member.effort:
                    target = f"{target}@{member.effort}"
                color = (
                    _POOL_AVAILABLE_STYLE
                    if member.available
                    else _POOL_UNAVAILABLE_STYLE
                )
                dimmed = suspended or not member.selected
                style = f"dim {color}" if dimmed else color
                text.append(f"{marker} {target}", style=style)
            else:
                style = (
                    "dim #FFD75F"
                    if suspended or not member.selected
                    else _WARNING_STYLE
                )
                text.append(f"! {member.value}", style=style)
    elif view.effort:
        if text:
            text.append("\n")
        text.append(f"effort: {view.effort}", style="dim")
        if view.override is None and view.reference_effort is not None:
            reference = view.references or view.implicit_fallback
            if reference is not None:
                text.append(
                    f" (via @{reference}@{view.reference_effort})",
                    style="dim",
                )
        if default_effort is None:
            text.append(" · no default configured", style="dim")
        elif view.effort == default_effort:
            text.append(" · matches default", style="dim")
        else:
            text.append(
                f" · overrides default {default_effort}",
                style="dim",
            )
    return text


def _description_text_for_bucket(bucket: BucketView) -> Text:
    """Return the two-line description and effective-model mix for *bucket*."""
    if bucket.custom_builtin_shadow_names:
        return _custom_builtin_shadow_description(bucket.custom_builtin_shadow_names)
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


def description_text_for_row(
    row: AliasView | BucketView | None,
    default_effort: str | None = None,
) -> Text:
    """Dispatch Models-panel description rendering by row type."""
    if isinstance(row, BucketView):
        return _description_text_for_bucket(row)
    return description_text_for_view(row, default_effort)
