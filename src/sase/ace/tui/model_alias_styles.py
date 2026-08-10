"""Shared model-alias presentation helpers for ACE surfaces."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.provider_styles import provider_model_badge_markup
from sase.llm_provider.model_label import (
    MODEL_ALIAS_CONNECTIVE_STYLE,
    MODEL_ALIAS_REFERENCE_STYLE,
)

OWNERSHIP_ACCENT = "#D7AF87"

MODEL_ALIAS_KIND_LABELS: dict[str, str] = {
    "default": "default",
    "role": "role",
    "user": "custom",
}

MODEL_ALIAS_KIND_STYLES: dict[str, str] = {
    "default": "bold #87D7FF",
    "role": "bold #87D7AF",
    "user": f"bold {OWNERSHIP_ACCENT}",
}

_OVERRIDE_TAG_STYLE = "bold #AF87FF"
_CONFIGURED_TAG_STYLE = "#87D787"
_IMPLICIT_TAG_STYLE = "dim #9E9E9E"
_REFERENCE_TAG_STYLE = MODEL_ALIAS_REFERENCE_STYLE
_PROVENANCE_CONNECTIVE_STYLE = MODEL_ALIAS_CONNECTIVE_STYLE
_EFFORT_CONNECTIVE_STYLE = "#878787"
_EFFORT_LEVEL_STYLE = "bold #AF87FF"
_POOL_AVAILABLE_STYLE = "#87D787"
_POOL_UNAVAILABLE_STYLE = "#D78787"
_POOL_PARTIAL_STYLE = "bold #FFD75F"


def alias_kind_label(kind: str) -> str:
    """Return the compact presentation label for an alias kind."""
    return MODEL_ALIAS_KIND_LABELS.get(kind, kind)


def append_effort_suffix(text: Text, effort: str) -> None:
    """Append the uniform `` @ <effort>`` suffix used across SASE."""
    if not effort:
        return
    text.append(" @ ", style=_EFFORT_CONNECTIVE_STYLE)
    text.append(effort, style=_EFFORT_LEVEL_STYLE)


def append_alias_reference(text: Text, reference: str, effort: str = "") -> None:
    """Append a consistently styled alias-reference suffix to *text*."""
    if not reference:
        return
    text.append(" → ", style=_PROVENANCE_CONNECTIVE_STYLE)
    text.append(f"@{reference.lstrip('@')}", style=_REFERENCE_TAG_STYLE)
    append_effort_suffix(text, effort)


def append_pool_chip(text: Text, available: int, total: int) -> None:
    """Append an availability-colored ``pool <up>/<total>`` chip."""
    if total <= 0:
        return
    if available == total:
        style = _POOL_AVAILABLE_STYLE
    elif available > 0:
        style = _POOL_PARTIAL_STYLE
    else:
        style = _POOL_UNAVAILABLE_STYLE
    text.append(" · ", style=_IMPLICIT_TAG_STYLE)
    text.append(f"pool {available}/{total}", style=style)


def alias_state_text(
    provenance: str,
    reference: str = "",
    reference_effort: str = "",
    pool_available: int = 0,
    pool_total: int = 0,
) -> Text:
    """Return a styled alias provenance/reference/pool state cell."""
    styles = {
        "override": _OVERRIDE_TAG_STYLE,
        "configured": _CONFIGURED_TAG_STYLE,
        "implicit": _IMPLICIT_TAG_STYLE,
    }
    text = Text(provenance, style=styles.get(provenance, "dim"))
    if not provenance:
        return text
    if pool_total:
        append_pool_chip(text, pool_available, pool_total)
    elif reference:
        append_alias_reference(text, reference, reference_effort)
    return text


def provider_model_text(
    provider: str | None,
    model: str | None,
    effort: str = "",
) -> Text:
    """Build a measurable, truncatable ``PROVIDER(model) @ effort`` badge."""
    text = Text.from_markup(provider_model_badge_markup(provider, model))
    append_effort_suffix(text, effort)
    return text


__all__ = [
    "MODEL_ALIAS_KIND_LABELS",
    "MODEL_ALIAS_KIND_STYLES",
    "OWNERSHIP_ACCENT",
    "alias_kind_label",
    "alias_state_text",
    "append_alias_reference",
    "append_effort_suffix",
    "append_pool_chip",
    "provider_model_text",
]
