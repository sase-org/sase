"""Shared layout primitives for Models panel rendering."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.model_alias_styles import OWNERSHIP_ACCENT
from sase.llm_provider import ModelsPanelSection

from ..actions.navigation.jump_hints import JUMP_HINT_CHARS
from .pane_entry_jump import apply_jump_hint_prefix

_NAME_CELL = 22
_OWNERSHIP_GUTTER_CELL = 2

# The provider/model badge is treated as its own column so the rightmost
# state/provenance tag lines up across rows. The column is sized to the widest
# badge currently visible, capped so the state tag stays inside the preferred
# 110-column modal budget. Removing the old 13-cell kind column and separator
# gives those 14 cells back to long alias/model expressions while preserving
# the established state-column budget.
PROVIDER_MODEL_CELL_MAX = 46
_STATE_GAP = "   "

_OVERRIDE_TAG_STYLE = "bold #AF87FF"
_PAUSED_OVERRIDE_TAG_STYLE = "bold #FFAF5F"
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

_LAUNCH_SECTION_LABEL = "Launch settings"
_BUILTIN_SECTION_LABEL = "Built-in size aliases"
_CUSTOM_SECTION_LABEL = "Your aliases"


def pad_to_width(value: str, width: int) -> str:
    """Truncate-or-pad *value* to exactly *width* columns."""
    if len(value) > width:
        return value[: max(0, width - 1)] + "…"
    return value.ljust(width)


def append_ownership_gutter(text: Text, *, user_owned: bool) -> None:
    """Append the fixed-width ownership gutter to *text*."""
    if user_owned:
        text.append("▌", style=_OWNERSHIP_STYLE)
        text.append(" ")
    else:
        text.append(" " * _OWNERSHIP_GUTTER_CELL)


def jump_hint_gutter_width(target_count: int) -> int:
    """Return the fixed jump-mode gutter width for a *target_count*-row session.

    Matches the width of :func:`apply_jump_hint_prefix`'s ``[<hint>] `` marker:
    four cells for the one-character hints a session of at most
    :data:`JUMP_HINT_CHARS`-many targets uses, five for the two-character
    hints a larger session requires.
    """
    hint_width = 1 if target_count <= len(JUMP_HINT_CHARS) else 2
    return hint_width + 3


def apply_jump_gutter(text: Text, hint: str | None, *, gutter_width: int) -> Text:
    """Reserve the transient jump-mode gutter ahead of *text*.

    Selectable rows with a hint get the standard ``[<hint>] `` marker from
    :func:`apply_jump_hint_prefix`; every other row -- including disabled
    headers, spacers, and the empty-custom hint -- gets a blank gutter of the
    same width so the ownership/name/value/state grid stays aligned while
    hints are painted.
    """
    if hint is not None:
        return apply_jump_hint_prefix(text, hint)
    decorated = Text(no_wrap=text.no_wrap, overflow=text.overflow)
    decorated.append(" " * gutter_width)
    decorated.append_text(text)
    return decorated


def count_label(count: int, singular: str) -> str:
    """Return a correctly singularized count label."""
    noun = (
        singular if count == 1 else "aliases" if singular == "alias" else f"{singular}s"
    )
    return f"{count} {noun}"


def section_count_label(section: ModelsPanelSection) -> str:
    """Return the state-column count label for a section header."""
    label = count_label(section.alias_count, "alias")
    if section.bucket_count:
        label += f" · {count_label(section.bucket_count, 'bucket')}"
    return label


def render_section_spacer() -> Text:
    """Render the disabled blank row between adjacent visible sections."""
    return Text("", no_wrap=True)


def render_section_header(
    section: ModelsPanelSection,
    *,
    provider_model_width: int,
) -> Text:
    """Render a disabled section header on the same grid as data rows."""
    text = Text(no_wrap=True, overflow="ellipsis")
    append_ownership_gutter(text, user_owned=section.is_user_owned)
    label = _CUSTOM_SECTION_LABEL if section.is_user_owned else _BUILTIN_SECTION_LABEL
    rule_width = _NAME_CELL + 1 + provider_model_width
    rule_label = f"── {label} "
    rule = rule_label + ("─" * max(0, rule_width - len(rule_label)))
    rule_style = _OWNERSHIP_STYLE if section.is_user_owned else _BUILTIN_SECTION_STYLE
    text.append(pad_to_width(rule, rule_width), style=rule_style)
    text.append(_STATE_GAP)
    text.append(section_count_label(section), style="dim")
    return text


def render_launch_settings_header(*, value_width: int, count: int) -> Text:
    """Render the disabled launch-settings section header."""
    text = Text(no_wrap=True, overflow="ellipsis")
    append_ownership_gutter(text, user_owned=False)
    rule_width = _NAME_CELL + 1 + value_width
    rule_label = f"── {_LAUNCH_SECTION_LABEL} "
    rule = rule_label + ("─" * max(0, rule_width - len(rule_label)))
    text.append(pad_to_width(rule, rule_width), style=_BUILTIN_SECTION_STYLE)
    text.append(_STATE_GAP)
    text.append(count_label(count, "setting"), style="dim")
    return text


def render_empty_custom_hint() -> Text:
    """Render the disabled hint shown when the user section has no rows."""
    text = Text(no_wrap=True, overflow="ellipsis")
    append_ownership_gutter(text, user_owned=False)
    text.append(
        f"No custom aliases · declare them under {_CUSTOM_ALIASES_PATH}",
        style="dim italic",
    )
    return text
