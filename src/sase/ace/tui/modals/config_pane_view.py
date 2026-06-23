"""Joined data view for the Config Center config pane."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.config import (
    ConfigField,
    ConfigFieldModel,
    ConfigFieldState,
    ConfigInventory,
)

# Layer kinds that a user can actually write to. A field touched by any of
# these is "modified" relative to the shipped built-in / plugin defaults.
_MUTABLE_KINDS: frozenset[str] = frozenset({"user", "overlay", "local"})

# Short, colored badge per source kind, reused by the tree rows, the source
# rail, and the provenance stack so a layer reads the same everywhere.
_KIND_LABEL: dict[str, str] = {
    "builtin": "built-in",
    "plugin": "plugin",
    "user": "user",
    "overlay": "overlay",
    "local": "local",
    "other": "other",
}
_KIND_COLOR: dict[str, str] = {
    "builtin": "#888888",
    "plugin": "#AF87FF",
    "user": "#00D7AF",
    "overlay": "#87D7FF",
    "local": "#5FAF5F",
    "other": "#888888",
}

_MODIFIED_COLOR = "#FFD700"
_DEPRECATED_COLOR = "#FF8787"
_MUTED = "#888888"

InputMode = Literal["filter", "jump"]


@dataclass(frozen=True)
class ConfigPaneView:
    """Joined, lookup-friendly view over the field model and inventory.

    The field model supplies the ordered tree structure and per-field schema
    metadata (type, description, default, enum, deprecation); the inventory
    supplies effective values and the per-field provenance stack. They are
    keyed 1:1 by dotted ``path``.
    """

    field_model: ConfigFieldModel
    inventory: ConfigInventory
    fields_by_path: dict[str, ConfigField]
    state_by_path: dict[str, ConfigFieldState]
    kind_by_layer: dict[str, str]

    @classmethod
    def build(
        cls, field_model: ConfigFieldModel, inventory: ConfigInventory
    ) -> ConfigPaneView:
        return cls(
            field_model=field_model,
            inventory=inventory,
            fields_by_path={f.path: f for f in field_model.fields},
            state_by_path={s.path: s for s in inventory.fields},
            kind_by_layer={s.name: s.kind for s in inventory.sources},
        )

    # -- per-field derivations --

    def winning_layer(self, path: str) -> str | None:
        """Return the highest-priority contributing layer for *path*."""
        state = self.state_by_path.get(path)
        if state is None:
            return None
        for contribution in state.contributions:
            if contribution.winning:
                return contribution.layer
        return None

    def is_modified(self, path: str) -> bool:
        """True when a writable (user/overlay/local) layer set this field."""
        state = self.state_by_path.get(path)
        if state is None:
            return False
        return any(
            self.kind_by_layer.get(c.layer) in _MUTABLE_KINDS
            for c in state.contributions
        )

    def modified_paths(self) -> set[str]:
        """All leaf paths a writable layer contributed to."""
        return {
            field.path
            for field in self.field_model.fields
            if field.leaf and self.is_modified(field.path)
        }

    def deprecation_replacement(self, path: str) -> str | None:
        """Replacement key for *path*, from the schema or the inventory policy.

        A key can be deprecated by the schema (``deprecated: true``) or by the
        runtime deprecation policy surfaced through the inventory field state;
        either source supplies the suggested replacement.
        """
        field = self.fields_by_path.get(path)
        if field is not None and field.deprecated_replacement:
            return field.deprecated_replacement
        state = self.state_by_path.get(path)
        if state is not None and state.deprecated_replacement:
            return state.deprecated_replacement
        return None

    def is_deprecated(self, path: str) -> bool:
        """True when the schema or the deprecation policy flags *path*."""
        field = self.fields_by_path.get(path)
        if field is not None and field.deprecated:
            return True
        state = self.state_by_path.get(path)
        return state is not None and state.deprecated_replacement is not None
