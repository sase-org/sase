"""Prompt-level `%final` selector parsing."""

from __future__ import annotations

import re
from collections.abc import Sequence

from sase.core.finalizer_wire import (
    FinalizerSelectorOpWire,
    finalizer_add,
    finalizer_clear,
    finalizer_remove,
)


_INSTANCE_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


class FinalizerSelectorError(ValueError):
    """Raised when prompt-authored finalizer selectors are malformed."""


def parse_finalizer_selector_ops(
    raw_operations: Sequence[str],
) -> list[FinalizerSelectorOpWire]:
    """Translate ordered raw `%final` operations into Rust wire selectors."""

    selectors: list[FinalizerSelectorOpWire] = []
    for index, raw in enumerate(raw_operations):
        op = raw.strip()
        if not op:
            raise FinalizerSelectorError(
                "%final contains an empty selector; remove the bare directive "
                "or empty comma element"
            )
        if op == "none":
            selectors.append(finalizer_clear())
            continue
        if op.startswith("!"):
            instance_id = op[1:]
            _require_instance_id(instance_id, index=index, source=raw)
            selectors.append(finalizer_remove(instance_id))
            continue
        _require_instance_id(op, index=index, source=raw)
        selectors.append(finalizer_add(op))
    return selectors


def _require_instance_id(instance_id: str, *, index: int, source: str) -> None:
    if _INSTANCE_RE.fullmatch(instance_id) is None:
        raise FinalizerSelectorError(
            f"invalid %final selector #{index + 1} {source!r}; expected "
            "a lowercase instance slug, !slug, or none"
        )


__all__ = ["FinalizerSelectorError", "parse_finalizer_selector_ops"]
