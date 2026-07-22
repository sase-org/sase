"""Shared dataclasses for config edit planning and execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.config.inventory import ConfigDiagnostic


class ConfigEditError(RuntimeError):
    """Raised when a config edit cannot be planned or applied."""


class ConfigEditConflict(ConfigEditError):
    """Raised when the target changed after an edit was previewed."""


@dataclass(frozen=True)
class ConfigEditOp:
    """A set/unset operation on a field."""

    kind: str
    value: Any = None

    @classmethod
    def set_value(cls, value: Any) -> ConfigEditOp:
        """An operation that sets the field to *value*."""
        return cls("set", value)

    @classmethod
    def unset(cls) -> ConfigEditOp:
        """An operation that removes the field from the target layer."""
        return cls("unset")

    def to_wire(self) -> dict[str, Any]:
        if self.kind == "unset":
            return {"kind": "unset"}
        return {"kind": "set", "value": self.value}


@dataclass(frozen=True)
class ConfigWritePlan:
    """The logical, frontend-agnostic write plan from the Rust core."""

    file: str | None
    layer: str
    key_path: tuple[str, ...]
    op: str
    has_value: bool
    new_value: Any

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ConfigWritePlan:
        return cls(
            file=payload.get("file"),
            layer=payload["layer"],
            key_path=tuple(payload["key_path"]),
            op=payload["op"],
            has_value=payload["has_value"],
            new_value=payload["new_value"],
        )


@dataclass(frozen=True)
class ConfigEffectivePreview:
    """The before/after effective value for the edited field."""

    path: str
    has_before: bool
    before: Any
    has_after: bool
    after: Any
    changed: bool

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ConfigEffectivePreview:
        return cls(
            path=payload["path"],
            has_before=payload["has_before"],
            before=payload["before"],
            has_after=payload["has_after"],
            after=payload["after"],
            changed=payload["changed"],
        )


@dataclass(frozen=True)
class EditPlanResult:
    """The full result of planning a config edit without writing."""

    schema_version: int
    write_plan: ConfigWritePlan
    candidate_config: dict[str, Any]
    effective_preview: ConfigEffectivePreview
    validation: tuple[ConfigDiagnostic, ...]
    diagnostics: tuple[ConfigDiagnostic, ...]
    target_path: str | None
    used_chezmoi: bool
    current_text: str
    new_text: str
    text_diff: str
    target_existed: bool = False
    target_bytes: bytes | None = None
    target_token: str = "absent"

    @property
    def is_valid(self) -> bool:
        """Return ``True`` when the candidate config has no validation errors."""
        return not any(d.severity == "error" for d in self.validation)


@dataclass(frozen=True)
class AppliedResult:
    """The outcome of a source-preserving config write."""

    path: str
    op: str
    key_path: tuple[str, ...]
    created: bool
    used_chezmoi: bool
