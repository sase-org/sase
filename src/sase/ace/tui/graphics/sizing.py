"""Sizing helpers for terminal image preview placements."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

DEFAULT_IMAGE_PREVIEW_COLUMNS = 40
DEFAULT_IMAGE_PREVIEW_ROWS = 12
MAX_IMAGE_PREVIEW_COLUMNS = 80
MAX_IMAGE_PREVIEW_ROWS = 24


def image_preview_size_for_viewport(
    *,
    scroll_widget: object | None = None,
    content_widget: object | None = None,
    reserved_rows: int = 0,
    fallback_columns: int = DEFAULT_IMAGE_PREVIEW_COLUMNS,
    fallback_rows: int = DEFAULT_IMAGE_PREVIEW_ROWS,
    max_columns: int = MAX_IMAGE_PREVIEW_COLUMNS,
    max_rows: int = MAX_IMAGE_PREVIEW_ROWS,
) -> tuple[int, int]:
    """Return a Kitty placeholder size that fits the visible viewport.

    Textual panels may have borders, padding, and a scrollbar gutter. Prefer the
    scrollable content region because it reflects the cells where Rich output is
    actually painted. Fall back to widget sizes only when layout information is
    not available yet.
    """
    viewport_columns = _first_positive(
        (
            _region_dimension(scroll_widget, "scrollable_content_region", "width"),
            _region_dimension(scroll_widget, "content_region", "width"),
            _size_dimension(content_widget, "width"),
            _size_dimension(scroll_widget, "width"),
        )
    )
    viewport_rows = _first_positive(
        (
            _region_dimension(scroll_widget, "scrollable_content_region", "height"),
            _region_dimension(scroll_widget, "content_region", "height"),
            _size_dimension(content_widget, "height"),
            _size_dimension(scroll_widget, "height"),
        )
    )

    if viewport_columns is None:
        columns = _clamp(fallback_columns, 1, max_columns)
    else:
        columns = _clamp(viewport_columns, 1, max_columns)

    if viewport_rows is None:
        rows = _clamp(fallback_rows, 1, max_rows)
    else:
        rows = _clamp(viewport_rows - max(0, reserved_rows), 1, max_rows)

    return columns, rows


def _first_positive(values: Iterable[int | None]) -> int | None:
    for value in values:
        if value is not None and value > 0:
            return value
    return None


def _region_dimension(
    widget: object | None,
    region_name: str,
    dimension_name: str,
) -> int | None:
    if widget is None:
        return None
    try:
        region = getattr(widget, region_name)
    except Exception:
        return None
    return _numeric_dimension(region, dimension_name)


def _size_dimension(widget: object | None, dimension_name: str) -> int | None:
    if widget is None:
        return None
    try:
        size = cast(Any, widget).size
    except Exception:
        return None
    return _numeric_dimension(size, dimension_name)


def _numeric_dimension(source: object | None, dimension_name: str) -> int | None:
    if source is None:
        return None
    try:
        value = getattr(source, dimension_name)
    except Exception:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return min(maximum, max(minimum, value))
