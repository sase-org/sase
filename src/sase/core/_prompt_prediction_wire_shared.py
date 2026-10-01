"""Shared wire primitives for the prompt prediction split.

The names here are public so the sibling ``prompt_prediction_wire_*``
modules can import them without touching a ``_``-prefixed symbol across
files. Each value keeps the behavior the former monolithic
:mod:`sase.core.prompt_prediction_wire` module used.
"""

from __future__ import annotations

from typing import Any

PROMPT_PREDICTION_WIRE_SCHEMA_VERSION = 1

#: Source roles the Rust model accepts when composing corpora.
PROMPT_PREDICTION_SOURCE_ROLES = ("history", "session", "archive")


def require_wire_schema(data: dict[str, Any], what: str) -> None:
    """Raise ``ValueError`` when *data* is stamped with a foreign schema."""
    schema = data.get("schema_version")
    if schema != PROMPT_PREDICTION_WIRE_SCHEMA_VERSION:
        raise ValueError(
            f"{what} has schema_version={schema!r}, expected "
            f"{PROMPT_PREDICTION_WIRE_SCHEMA_VERSION}"
        )


__all__ = [
    "PROMPT_PREDICTION_SOURCE_ROLES",
    "PROMPT_PREDICTION_WIRE_SCHEMA_VERSION",
    "require_wire_schema",
]
