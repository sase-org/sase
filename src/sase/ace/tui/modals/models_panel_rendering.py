"""Stable facade for Models panel rendering helpers.

The implementations are grouped by layout, data rows, and description-strip
rendering. Re-exporting the established API here keeps callers decoupled from
that internal organization.
"""

from sase.ace.tui.model_alias_styles import OWNERSHIP_ACCENT

from .models_panel_rendering_descriptions import (
    custom_builtin_shadow_warning_message,
    description_text_for_row,
    description_text_for_view,
)
from .models_panel_rendering_layout import (
    PROVIDER_MODEL_CELL_MAX,
    apply_jump_gutter,
    jump_hint_gutter_width,
    render_empty_custom_hint,
    render_launch_settings_header,
    render_section_header,
    render_section_spacer,
    section_count_label as _section_count_label,
)
from .models_panel_rendering_rows import (
    format_phase_threshold,
    kind_label,
    panel_value_column_width,
    provider_model_column_width,
    render_alias_row,
    render_bucket_row,
    render_panel_row,
    state_tag,
)

__all__ = [
    "OWNERSHIP_ACCENT",
    "PROVIDER_MODEL_CELL_MAX",
    "_section_count_label",
    "apply_jump_gutter",
    "custom_builtin_shadow_warning_message",
    "description_text_for_row",
    "description_text_for_view",
    "format_phase_threshold",
    "jump_hint_gutter_width",
    "kind_label",
    "panel_value_column_width",
    "provider_model_column_width",
    "render_alias_row",
    "render_bucket_row",
    "render_empty_custom_hint",
    "render_launch_settings_header",
    "render_panel_row",
    "render_section_header",
    "render_section_spacer",
    "state_tag",
]
