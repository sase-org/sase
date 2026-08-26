"""Built-in notification section strategy for the Beads tab."""

from __future__ import annotations

from collections.abc import Mapping

from sase.notification_gates.presentation import gate_chip_from_action_data
from sase.notifications import Notification
from sase.task_type_presentation import task_type_presentation
from sase.task_types.registry import get_task_type_registry

from .notification_sections import NotificationSection

_DUE_SECTION = NotificationSection(
    key="kind:due",
    label="Due",
    glyph="⏰",
    color="#FFAF00",
    order=(1, 0, ""),
)
_CLEANUP_SECTION = NotificationSection(
    key="kind:cleanup",
    label="Cleanup",
    glyph="🧹",
    color="#5FAFAF",
    order=(2, 0, ""),
)
_OTHER_SECTION = NotificationSection(
    key="kind:other",
    label="Other",
    glyph="◈",
    color="#AF87FF",
    order=(3, 0, ""),
)


def bead_type_section_for(notification: Notification) -> NotificationSection:
    """Return the Beads-tab section for one notification row."""
    action_data = notification.action_data
    chip = gate_chip_from_action_data(action_data)
    if chip is not None:
        registry = get_task_type_registry()
        known_slugs = {
            record.task_type: index for index, record in enumerate(registry.records)
        }
        slug = chip.label
        catalog_index = known_slugs.get(slug)
        if catalog_index is not None:
            presentation = task_type_presentation(slug, registry=registry)
            return NotificationSection(
                key=f"type:{slug}",
                label=presentation.label,
                glyph=presentation.glyph,
                color=presentation.accent_color,
                order=(0, catalog_index, presentation.label),
            )
        return NotificationSection(
            key=f"type:{slug}",
            label=chip.label,
            glyph=chip.glyph,
            color=chip.color or "#AF87FF",
            order=(0, len(registry.records), chip.label),
        )

    request_kind = ""
    if isinstance(action_data, Mapping):
        request_kind = str(action_data.get("request_kind", ""))
    if request_kind == "bead_snooze":
        return _DUE_SECTION
    if request_kind == "bead_stale_cleanup":
        return _CLEANUP_SECTION
    return _OTHER_SECTION


__all__ = ["bead_type_section_for"]
