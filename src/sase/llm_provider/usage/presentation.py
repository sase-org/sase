"""Shared presentation helpers for cached subscription usage.

Thin facade over the ``_presentation_*`` modules: stable snapshot payloads live
in :mod:`sase.llm_provider.usage._presentation_snapshot`, human-readable labels
and Rich styles in :mod:`sase.llm_provider.usage._presentation_labels`,
plain-text and Rich renderers in
:mod:`sase.llm_provider.usage._presentation_render`, and shared coercion
primitives in :mod:`sase.llm_provider.usage._presentation_shared`.
"""

from __future__ import annotations

from sase.llm_provider.usage._presentation_labels import (
    _collector_health_label,
    _collector_health_style,
    age_label,
    applicability_label,
    collector_health_style,
    collector_retry_label,
    diagnostic_line,
    duration_label,
    provider_status_label,
    provider_style,
    reset_label,
    timestamp_label,
    window_label,
    window_status_label,
)
from sase.llm_provider.usage._presentation_render import (
    render_refresh_receipt_plain,
    render_usage_plain,
    render_usage_refresh_toast,
    render_usage_rich,
)
from sase.llm_provider.usage._presentation_snapshot import usage_snapshot_json_payload
from sase.llm_provider.usage.store import provider_usage_format_remaining_text

__all__ = [
    "age_label",
    "applicability_label",
    "collector_health_style",
    "collector_retry_label",
    "diagnostic_line",
    "duration_label",
    "provider_status_label",
    "provider_style",
    "render_refresh_receipt_plain",
    "render_usage_plain",
    "render_usage_rich",
    "reset_label",
    "timestamp_label",
    "usage_snapshot_json_payload",
    "window_label",
    "window_status_label",
]
