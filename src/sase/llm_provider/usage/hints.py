"""Pure capacity-hint helpers for picker rows, alias detail, and attention."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sase.llm_provider.usage.store import (
    provider_usage_format_remaining_text,
    provider_usage_summarize_for_model,
    provider_usage_window_applies,
)

_ATTENTION_RANK: Mapping[str, int] = {
    "rejected": 4,
    "very_low": 3,
    "low": 2,
    "collection_problem": 1,
    "unknown": 1,
    "none": 0,
}
_CONSTRAINT_KINDS = frozenset({"rejected", "very_low", "low"})
_SHARED_KINDS = frozenset({"account", "unknown"})


@dataclass(frozen=True, slots=True)
class CapacityHint:
    """One scoped capacity hint for a picker row, alias member, or indicator."""

    kind: str
    label: str
    provider: str
    window_key: str | None = None
    scope: str | None = None
    remaining_percent: float | None = None

    @property
    def marker(self) -> str:
        """Return the colorless attention glyph for this hint."""
        return capacity_hint_marker(self.kind)

    @property
    def rank(self) -> int:
        """Return the stable attention rank; rejected outranks low, then collection."""
        return _ATTENTION_RANK.get(self.kind, 0)

    @property
    def display(self) -> str:
        """Return the glyph plus label used on picker rows and the indicator."""
        return f"{self.marker} {self.label}"


def provider_header_capacity_hint(provider: Mapping[str, Any]) -> CapacityHint | None:
    """Return a shared or unknown-scope hint for a provider heading, if any."""
    name = _provider_name(provider)
    attention = _attention_kind(provider)
    if attention == "collection_problem":
        return CapacityHint(kind="collection_problem", label="usage", provider=name)
    for constraint, window in _iter_constraints(provider):
        if not _is_shared_or_unknown(window.get("applicability")):
            continue
        unknown = _is_unknown_scope(window.get("applicability"))
        return _hint_from_constraint(name, constraint, window, unknown=unknown)
    shared = _attention_hint(provider, shared_only=True)
    if shared is not None:
        return shared
    for window in _windows(provider):
        if _is_unknown_scope(window.get("applicability")):
            return _unknown_window_hint(name, window)
    return None


def model_capacity_hint(
    provider: Mapping[str, Any],
    model_id: str,
) -> CapacityHint | None:
    """Return a model-specific or unknown-scope hint that is not on the header."""
    name = _provider_name(provider)
    try:
        summary = provider_usage_summarize_for_model(_windows(provider), model_id)
    except Exception:
        summary = None
    for constraint, window in _iter_constraints(provider):
        applicability = window.get("applicability")
        if _is_shared_or_unknown(applicability):
            continue
        match = _window_match(applicability, model_id)
        if match == "does_not_apply":
            continue
        hint = _hint_from_constraint(
            name, constraint, window, unknown=match == "unknown"
        )
        return _fill_hint_remaining(hint, summary)
    return None


def member_capacity_hint(
    provider: Mapping[str, Any] | None,
    model_id: str,
) -> CapacityHint | None:
    """Return the best applicable hint for one alias member, including shared windows."""
    if provider is None or not model_id:
        return None
    name = _provider_name(provider)
    for constraint, window in _iter_constraints(provider):
        match = _window_match(window.get("applicability"), model_id)
        if match == "does_not_apply":
            continue
        return _hint_from_constraint(
            name, constraint, window, unknown=match == "unknown"
        )
    if _attention_kind(provider) == "collection_problem":
        return CapacityHint(kind="collection_problem", label="usage", provider=name)
    for window in _windows(provider):
        if _window_match(window.get("applicability"), model_id) == "unknown":
            return _unknown_window_hint(name, window)
    return None


def alias_capacity_hint(
    *,
    provider: str | None,
    model: str | None,
    selector_members: Sequence[Any] = (),
    providers: Mapping[str, Mapping[str, Any]],
) -> CapacityHint | None:
    """Return a member-scoped alias hint without combining member percentages."""
    if selector_members:
        best: CapacityHint | None = None
        for member in selector_members:
            if getattr(member, "valid", True) is False:
                continue
            member_provider = getattr(member, "provider", None)
            target = str(getattr(member, "target", "") or "")
            model_id = _model_id_from_target(target)
            if not isinstance(member_provider, str) or not model_id:
                continue
            hint = member_capacity_hint(providers.get(member_provider), model_id)
            if hint is None:
                continue
            labeled = CapacityHint(
                kind=hint.kind,
                label=f"{model_id} {hint.label}",
                provider=hint.provider,
                window_key=hint.window_key,
                scope=hint.scope,
                remaining_percent=hint.remaining_percent,
            )
            if _hint_sort_key(labeled) < _hint_sort_key(best):
                best = labeled
        return best
    if not isinstance(provider, str) or not model:
        return None
    return member_capacity_hint(providers.get(provider), model)


def indicator_usage_items(
    providers: Sequence[Mapping[str, Any]],
    eligible: Sequence[str] | set[str] | frozenset[str],
) -> tuple[CapacityHint, ...]:
    """Return eligible usage attention items, highest rank first, then provider id."""
    allowed = set(eligible)
    items: list[CapacityHint] = []
    for provider in providers:
        name = _provider_name(provider)
        if name not in allowed:
            continue
        hint = _attention_hint(provider, shared_only=False)
        if hint is not None:
            items.append(hint)
    items.sort(key=_hint_sort_key)
    return tuple(items)


def indicator_usage_attention(
    providers: Sequence[Mapping[str, Any]],
    eligible: Sequence[str] | set[str] | frozenset[str],
) -> tuple[CapacityHint | None, int]:
    """Return the highest-rank eligible usage item and the eligible attention count."""
    items = indicator_usage_items(providers, eligible)
    if not items:
        return None, 0
    return items[0], len(items)


def providers_by_name(
    providers: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    """Index provider snapshots by provider id, skipping nameless rows."""
    indexed: dict[str, Mapping[str, Any]] = {}
    for provider in providers:
        name = _provider_name(provider)
        if name:
            indexed[name] = provider
    return indexed


def model_id_from_target(target: str) -> str:
    """Return the model id from a ``provider/model`` target or a bare model id."""
    return _model_id_from_target(target)


def capacity_hint_marker(kind: str | None) -> str:
    """Return the colorless capacity glyph; unknown uses a question mark."""
    return "?" if kind in {"unknown", "collection_problem"} else "!"


def capacity_hint_style(kind: str | None) -> str:
    """Return a color that still leaves the glyph and words as the meaning."""
    if kind in {"rejected", "very_low"}:
        return "bold #FF5F5F"
    if kind == "low":
        return "#FFAF00"
    return "#FFD75F"


def _attention_hint(
    provider: Mapping[str, Any],
    *,
    shared_only: bool,
) -> CapacityHint | None:
    name = _provider_name(provider)
    kind = _attention_kind(provider)
    if kind == "none":
        return None
    if kind == "collection_problem":
        return CapacityHint(kind="collection_problem", label="usage", provider=name)
    window_key = _attention_window_key(provider)
    window = _window_by_key(_windows(provider), window_key)
    if window is None:
        return CapacityHint(kind=kind, label=_kind_fallback_label(kind), provider=name)
    if shared_only and not _is_shared_or_unknown(window.get("applicability")):
        return None
    unknown = _is_unknown_scope(window.get("applicability"))
    return _hint_from_window(name, kind, window, unknown=unknown)


def _fill_hint_remaining(
    hint: CapacityHint,
    summary: Mapping[str, Any] | None,
) -> CapacityHint:
    """Copy remaining percent from the scoped core summary when the window omitted it."""
    if hint.remaining_percent is not None or not isinstance(summary, Mapping):
        return hint
    if summary.get("key") not in {hint.window_key, None}:
        return hint
    remaining = _optional_float(summary.get("remaining_percent"))
    if remaining is None:
        return hint
    return CapacityHint(
        kind=hint.kind,
        label=hint.label,
        provider=hint.provider,
        window_key=hint.window_key,
        scope=hint.scope,
        remaining_percent=remaining,
    )


def _hint_from_constraint(
    provider: str,
    constraint: Mapping[str, Any],
    window: Mapping[str, Any],
    *,
    unknown: bool = False,
) -> CapacityHint:
    kind = str(constraint.get("attention") or "low")
    if kind not in _CONSTRAINT_KINDS:
        kind = "low"
    if unknown:
        kind = "unknown" if kind not in _CONSTRAINT_KINDS else kind
    return _hint_from_window(provider, kind, window, unknown=unknown)


def _hint_from_window(
    provider: str,
    kind: str,
    window: Mapping[str, Any],
    *,
    unknown: bool,
) -> CapacityHint:
    remaining = _remaining_text(window)
    scope = _window_scope_label(window, unknown=unknown)
    if remaining is None:
        label = "usage unknown" if unknown else "usage"
    elif unknown:
        label = f"{remaining} · scope unknown"
    elif scope:
        label = f"{remaining} · {scope}"
    else:
        label = remaining
    return CapacityHint(
        kind="unknown" if unknown and kind not in _CONSTRAINT_KINDS else kind,
        label=label,
        provider=provider,
        window_key=_optional_text(window.get("key")),
        scope=scope,
        remaining_percent=_optional_float(window.get("remaining_percent")),
    )


def _unknown_window_hint(provider: str, window: Mapping[str, Any]) -> CapacityHint:
    remaining = _remaining_text(window)
    label = f"{remaining} · scope unknown" if remaining else "usage unknown"
    return CapacityHint(
        kind="unknown",
        label=label,
        provider=provider,
        window_key=_optional_text(window.get("key")),
        scope=_window_scope_label(window, unknown=True),
        remaining_percent=_optional_float(window.get("remaining_percent")),
    )


def _iter_constraints(
    provider: Mapping[str, Any],
) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    windows = _windows(provider)
    pairs: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    raw = provider.get("known_constraints")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            window = _window_by_key(windows, item.get("window_key"))
            if window is not None:
                pairs.append((item, window))
    if pairs:
        return pairs
    kind = _attention_kind(provider)
    window = _window_by_key(windows, _attention_window_key(provider))
    if kind in _CONSTRAINT_KINDS and window is not None:
        pairs.append(({"attention": kind, "window_key": window.get("key")}, window))
    return pairs


def _windows(provider: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw = provider.get("windows")
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _window_by_key(
    windows: Sequence[Mapping[str, Any]],
    key: object,
) -> Mapping[str, Any] | None:
    if not isinstance(key, str) or not key:
        return None
    for window in windows:
        if window.get("key") == key:
            return window
    return None


def _window_match(applicability: object, model_id: str) -> str:
    if not isinstance(applicability, Mapping):
        return "unknown"
    try:
        return provider_usage_window_applies(applicability, model_id)
    except Exception:
        return "unknown"


def _is_unknown_scope(applicability: object) -> bool:
    kind = _applicability_kind(applicability)
    if kind == "unknown":
        return True
    if kind in {"product", "model_family"}:
        model_ids = (
            applicability.get("model_ids")
            if isinstance(applicability, Mapping)
            else None
        )
        return not model_ids
    return False


def _is_shared_or_unknown(applicability: object) -> bool:
    kind = _applicability_kind(applicability)
    if kind in _SHARED_KINDS:
        return True
    return _is_unknown_scope(applicability)


def _applicability_kind(applicability: object) -> str:
    if not isinstance(applicability, Mapping):
        return "unknown"
    kind = applicability.get("kind")
    return kind if isinstance(kind, str) and kind else "unknown"


def _window_scope_label(window: Mapping[str, Any], *, unknown: bool) -> str | None:
    if unknown:
        return "scope unknown"
    label = _optional_text(window.get("label"))
    return label


def _remaining_text(window: Mapping[str, Any]) -> str | None:
    used = _optional_float(window.get("used_percent"))
    if used is None:
        remaining = _optional_float(window.get("remaining_percent"))
        if remaining is None:
            return None
        return f"{_format_number(remaining)}% left"
    try:
        return provider_usage_format_remaining_text(used)
    except Exception:
        remaining = max(0.0, 100.0 - used)
        return f"{_format_number(remaining)}% left"


def _attention_kind(provider: Mapping[str, Any]) -> str:
    attention = provider.get("attention")
    if isinstance(attention, Mapping):
        kind = attention.get("kind")
    else:
        kind = attention
    if not isinstance(kind, str) or kind in {"", "none"}:
        return "none"
    return kind


def _attention_window_key(provider: Mapping[str, Any]) -> str | None:
    attention = provider.get("attention")
    if isinstance(attention, Mapping):
        return _optional_text(attention.get("window_key"))
    return None


def _provider_name(provider: Mapping[str, Any]) -> str:
    return str(provider.get("provider") or "")


def _model_id_from_target(target: str) -> str:
    cleaned = target.strip()
    if "/" in cleaned:
        return cleaned.split("/", 1)[1].strip()
    return cleaned


def _hint_sort_key(hint: CapacityHint | None) -> tuple[int, str]:
    if hint is None:
        return (0, "")
    return (-hint.rank, hint.provider)


def _kind_fallback_label(kind: str) -> str:
    if kind == "collection_problem":
        return "usage"
    return "usage unknown" if kind == "unknown" else kind.replace("_", " ")


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


__all__ = [
    "CapacityHint",
    "alias_capacity_hint",
    "capacity_hint_marker",
    "capacity_hint_style",
    "indicator_usage_attention",
    "indicator_usage_items",
    "member_capacity_hint",
    "model_capacity_hint",
    "model_id_from_target",
    "provider_header_capacity_hint",
    "providers_by_name",
]
