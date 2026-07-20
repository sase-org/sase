"""Compatibility surface and cached loader for the Config Center config pane."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.config import build_config_inventory, config_field_model
from sase.config.core import clear_config_cache, current_config_token

from .config_commit import (
    ConfigCommitOffer,
    build_config_commit_offer as _build_config_commit_offer,
)
from .config_pane_rendering import (
    abbreviate_path as _abbreviate_path,
    ancestor_paths as _ancestor_paths,
    append_value_block as _append_value_block,
    format_row_value_summary as _format_row_value_summary,
    format_value as _format_value,
    format_value_block as _format_value_block,
    highlight_value_block as _highlight_value_block,
    is_structured_value as _is_structured_value,
    kind_badge as _kind_badge,
    render_detail as _render_detail,
    render_field_diagnostics as _render_field_diagnostics,
    render_leaf_detail as _render_leaf_detail,
    render_provenance as _render_provenance,
    render_row_label as _render_row_label,
    render_section_detail as _render_section_detail,
    render_source_rail as _render_source_rail,
    sort_mapping_keys as _sort_mapping_keys,
    source_badges as _source_badges,
    source_status_marker as _source_status_marker,
    truncate_value_block as _truncate_value_block,
    visible_leaf_paths as _visible_leaf_paths,
    visible_paths as _visible_paths,
)
from .config_pane_view import (
    ConfigPaneView,
    InputMode,
    _DEPRECATED_COLOR,
    _KIND_COLOR,
    _KIND_LABEL,
    _MODIFIED_COLOR,
    _MUTABLE_KINDS,
    _MUTED,
)
from .config_pane_widget import ConfigFilterInput as _ConfigFilterInput, ConfigPane


@dataclass(frozen=True)
class _LoadResult:
    """The outcome of a (possibly cached) inventory load."""

    view: ConfigPaneView | None
    error: str | None
    token: Any


# Process-wide inventory cache keyed by (stat-token, local_paths). Re-opening
# the Config Center reuses this when nothing on disk changed; ``r`` forces a
# rebuild by bypassing the cache.
_cache_key: tuple[Any, tuple[str, ...]] | None = None
_cache_result: _LoadResult | None = None


def _load_config_view(
    *,
    local_paths: tuple[str, ...] = (),
    force: bool = False,
) -> _LoadResult:
    """Build (or reuse) the joined config view. Safe to call off-thread."""
    global _cache_key, _cache_result
    try:
        token = current_config_token()
    except Exception:  # pragma: no cover - token is best-effort
        token = None
    key = (token, tuple(local_paths))
    if (
        not force
        and token is not None
        and _cache_key == key
        and _cache_result is not None
    ):
        return _cache_result
    try:
        field_model = config_field_model()
        inventory = build_config_inventory(local_paths=local_paths)
        result = _LoadResult(
            view=ConfigPaneView.build(field_model, inventory),
            error=None,
            token=token,
        )
    except Exception as exc:  # surfaced as the pane error state
        result = _LoadResult(view=None, error=str(exc), token=token)
    _cache_key = key
    _cache_result = result
    return result


def _clear_view_cache() -> None:
    """Drop the cached view (used by ``r`` and by tests)."""
    global _cache_key, _cache_result
    _cache_key = None
    _cache_result = None
    clear_config_cache()


__all__ = [
    "ConfigPane",
    "ConfigPaneView",
    "ConfigCommitOffer",
    "InputMode",
    "_ConfigFilterInput",
    "_DEPRECATED_COLOR",
    "_KIND_COLOR",
    "_KIND_LABEL",
    "_LoadResult",
    "_MODIFIED_COLOR",
    "_MUTABLE_KINDS",
    "_MUTED",
    "_abbreviate_path",
    "_ancestor_paths",
    "_append_value_block",
    "_clear_view_cache",
    "_build_config_commit_offer",
    "_format_value",
    "_format_row_value_summary",
    "_format_value_block",
    "_highlight_value_block",
    "_is_structured_value",
    "_kind_badge",
    "_load_config_view",
    "_render_detail",
    "_render_field_diagnostics",
    "_render_leaf_detail",
    "_render_provenance",
    "_render_row_label",
    "_render_section_detail",
    "_render_source_rail",
    "_sort_mapping_keys",
    "_source_badges",
    "_source_status_marker",
    "_truncate_value_block",
    "_visible_leaf_paths",
    "_visible_paths",
    "build_config_inventory",
    "config_field_model",
    "current_config_token",
]
