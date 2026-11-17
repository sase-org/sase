"""Descriptor diff helpers for Artifacts generation publication."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

_PUBLISHED_PANE_ID_ATTR = "_artifacts_published_pane_id"


def mark_staged_replacement(widget: Any, pane_id: str) -> None:
    """Record the pane id a replacement widget will receive at commit.

    Textual allows a node id to be set only once, so replacements mount
    without an id and are promoted after the outgoing widget is removed.
    """

    setattr(widget, _PUBLISHED_PANE_ID_ATTR, pane_id)


def _staged_replacement_pane_id(widget: Any) -> str | None:
    value = getattr(widget, _PUBLISHED_PANE_ID_ATTR, None)
    return value if isinstance(value, str) and value else None


def is_staged_replacement_widget(widget: Any) -> bool:
    return (
        _staged_replacement_pane_id(widget) is not None
        and getattr(widget, "id", None) is None
    )


def promote_staged_replacement(widget: Any) -> None:
    """Assign the published pane id now that the outgoing widget is gone."""

    pane_id = _staged_replacement_pane_id(widget)
    if pane_id is None:
        return
    current_id = getattr(widget, "id", None)
    if current_id is not None:
        raise RuntimeError(f"staged replacement already has id {current_id!r}")
    widget.id = pane_id


def _contract_fingerprint(contract: Any) -> object:
    """Compare contracts without digit/order presentation churn.

    ``contract_with_digit`` copies the pane contract whenever Files or a
    provider is renumbered. Digit, order, and the digest derived from them
    must not remount an otherwise unchanged widget.
    """

    if contract is None:
        return None
    try:
        return replace(contract, digit=None, order=0, presentation_digest="")
    except (TypeError, ValueError):
        return contract


def _widget_signature(descriptor: Any) -> tuple[object, ...]:
    """Identity for whether a mounted widget must be replaced.

    Digit shortcuts are display-only and must not remount an unchanged pane
    when a later generation merely renumbers Files or a provider.
    """

    return (
        getattr(descriptor, "id", None),
        getattr(descriptor, "pane_id", None),
        getattr(descriptor, "provider_kind", None),
        getattr(descriptor, "provider_spec_digest", None),
        getattr(descriptor, "error", None),
        getattr(descriptor, "error_code", None),
        getattr(descriptor, "error_source", None),
        getattr(descriptor, "label", None),
        getattr(descriptor, "item_noun", None),
        bool(getattr(descriptor, "is_degraded", False)),
        _contract_fingerprint(getattr(descriptor, "contract", None)),
    )


def diff_artifact_descriptors(
    old_descriptors: tuple[Any, ...] | list[Any],
    new_descriptors: tuple[Any, ...] | list[Any],
) -> tuple[list[Any], tuple[str, ...], list[Any]]:
    """Return ``(added, removed_pane_ids, replaced)`` for one generation."""

    old_by_id = {descriptor.id: descriptor for descriptor in old_descriptors}
    new_ids = {descriptor.id for descriptor in new_descriptors}
    added = [
        descriptor for descriptor in new_descriptors if descriptor.id not in old_by_id
    ]
    removed = tuple(
        sorted(old_by_id[pane_id].pane_id for pane_id in set(old_by_id) - new_ids)
    )
    replaced = [
        descriptor
        for descriptor in new_descriptors
        if descriptor.id in old_by_id
        and _widget_signature(old_by_id[descriptor.id]) != _widget_signature(descriptor)
    ]
    return added, removed, replaced
