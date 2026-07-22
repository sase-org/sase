"""Frontmatter-compatible wrapper around the reusable property picker."""

from __future__ import annotations

from dataclasses import dataclass

from .property_picker_modal import (
    PropertyPickerChoice,
    PropertyPickerItem,
    PropertyPickerModal,
    assign_property_accelerators,
    choose_property_accelerator,
)


@dataclass(frozen=True)
class AddableProperty(PropertyPickerItem):
    """Backward-compatible name for a pickable frontmatter property."""


class AddPropertyModal(PropertyPickerModal):
    """Pick a frontmatter property while retaining the original DOM contract."""

    def __init__(self, properties: list[AddableProperty]) -> None:
        super().__init__(
            properties,
            title="Add frontmatter property",
            empty_message="No frontmatter properties are available.",
            dom_prefix="add-property",
            generic_style=False,
        )

    @property
    def _row_classes(self) -> str:
        return "property-picker-row add-property-row"


# Preserve the private helper names used by older focused tests.
_PropertyChoice = PropertyPickerChoice
_assign_accelerators = assign_property_accelerators
_choose_accelerator = choose_property_accelerator


__all__ = ["AddableProperty", "AddPropertyModal"]
