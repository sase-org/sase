"""Shared ordering and display rendering for plan frontmatter properties."""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from datetime import date
from typing import Any

PLAN_PROPERTY_ORDER: tuple[str, ...] = (
    "title",
    "tier",
    "kind",
    "status",
    "create_time",
    "created",
    "created_at",
    "goal",
)


def plan_property_label(key: str) -> str:
    """Turn a frontmatter key into a compact, readable label."""
    return key.replace("_", " ").strip().capitalize() or key


def ordered_plan_property_items(
    frontmatter: Mapping[str, Any],
) -> list[tuple[str, Any]]:
    """Return all properties in canonical leading order, then alphabetically."""
    known_order = {key: index for index, key in enumerate(PLAN_PROPERTY_ORDER)}
    return sorted(
        frontmatter.items(),
        key=lambda item: (
            known_order.get(item[0].casefold(), len(known_order)),
            item[0].casefold(),
            item[0],
        ),
    )


def render_plan_value_lines(value: Any) -> list[str]:
    """Recursively render a parsed YAML value as deterministic display lines."""
    return _render_plan_value_lines(value, seen=set())


def _scalar_text(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value if value else "—"
    return str(value)


def _mapping_key_text(value: Any) -> str:
    if isinstance(value, (Mapping, Sequence, Set)) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return str(value)
    return _scalar_text(value)


def _render_plan_value_lines(value: Any, *, seen: set[int]) -> list[str]:
    if isinstance(value, Mapping):
        if not value:
            return ["{}"]
        value_id = id(value)
        if value_id in seen:
            return ["↻ recursive reference"]
        seen.add(value_id)
        lines: list[str] = []
        try:
            for key, nested_value in value.items():
                key_text = _mapping_key_text(key)
                nested_lines = _render_plan_value_lines(nested_value, seen=seen)
                if len(nested_lines) == 1:
                    lines.append(f"{key_text}: {nested_lines[0]}")
                else:
                    lines.append(f"{key_text}:")
                    lines.extend(f"  {line}" for line in nested_lines)
        finally:
            seen.remove(value_id)
        return lines

    if isinstance(value, Set) and not isinstance(value, (str, bytes, bytearray)):
        if not value:
            return ["[]"]
        ordered_values = sorted(value, key=lambda item: _scalar_text(item).casefold())
        return _render_plan_value_lines(ordered_values, seen=seen)

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if not value:
            return ["[]"]
        value_id = id(value)
        if value_id in seen:
            return ["↻ recursive reference"]
        seen.add(value_id)
        lines = []
        try:
            for nested_value in value:
                nested_lines = _render_plan_value_lines(nested_value, seen=seen)
                if len(nested_lines) == 1:
                    lines.append(f"• {nested_lines[0]}")
                else:
                    lines.append("•")
                    lines.extend(f"  {line}" for line in nested_lines)
        finally:
            seen.remove(value_id)
        return lines

    return _scalar_text(value).split("\n")
