"""Python facade over the Rust question-round projection binding."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding

QUESTION_ROUND_WIRE_SCHEMA_VERSION = 1


def project_question_round(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return the Rust read model for one question gate bundle.

    *request* must be a ``QuestionRoundRequestWire``-shape mapping carrying
    the gate identity plus the bundle's ``request``/``response``/
    ``cancellation`` contents. The projection is pure and performs no I/O.

    Raises ``ValueError`` (propagated from the Rust binding, message
    prefixed with its stable error code, e.g.
    ``unsupported_question_round_schema: ...``) when the request carries an
    unsupported schema version or is structurally invalid. Malformed bundle
    content never raises: it degrades ``data_state`` instead.
    """
    binding = require_rust_binding("project_question_round")
    result = binding(dict(request))
    if not isinstance(result, dict):
        raise TypeError("project_question_round returned a non-mapping")
    return dict(result)


__all__ = [
    "QUESTION_ROUND_WIRE_SCHEMA_VERSION",
    "project_question_round",
]
