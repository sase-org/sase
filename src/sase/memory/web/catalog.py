"""Glossary catalog helpers for memory-web-backed sources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.core.glossary_facade import GlossarySource


def glossary_source_from_wire(payload: object) -> GlossarySource | None:
    """Return source metadata from either v1 or v2 glossary source wire keys."""

    if not isinstance(payload, Mapping):
        return None

    source_path = _string_value(payload.get("source_path"))
    if source_path is None:
        source_path = _string_value(payload.get("config_path"))

    key_path = _string_tuple(payload.get("key_path"))
    if not key_path:
        key_path = _string_tuple(payload.get("config_key_path"))

    keyword_range = _range_payload(payload.get("keyword_range"))
    if keyword_range is None:
        keyword_range = _range_payload(payload.get("term_range"))

    body_range = _range_payload(payload.get("body_range"))
    if body_range is None:
        body_range = _range_payload(payload.get("definition_range"))

    aliases_range = _range_payload(payload.get("aliases_range"))

    if (
        source_path is None
        and not key_path
        and keyword_range is None
        and body_range is None
        and aliases_range is None
    ):
        return None

    return GlossarySource(
        source_path=source_path,
        key_path=key_path,
        keyword_range=keyword_range,
        body_range=body_range,
        aliases_range=aliases_range,
    )


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _range_payload(value: object) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


__all__ = ["glossary_source_from_wire"]
