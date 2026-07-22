"""Pure Rich rendering for config transaction previews."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from rich.text import Text

from sase.config import EditPlanResult

from .config_edit_helpers import format_value
from .config_edit_types import _ACCENT, _ERR_COLOR, _MUTED, _OK_COLOR, _WARN_COLOR
from .config_pane_rendering import format_row_value_summary, is_structured_value


_INLINE_VALUE_MAX_WIDTH = 72


@dataclass(frozen=True)
class TransactionDiagnostic:
    """Frontend-neutral diagnostic rendered in a transaction preview."""

    severity: str
    message: str
    path: str | None = None
    code: str | None = None


@dataclass(frozen=True)
class TransactionEffectivePreview:
    """Before/after effective value for a planned mutation."""

    has_before: bool
    before: Any
    has_after: bool
    after: Any
    changed: bool
    label: str = "Effective value"


@dataclass(frozen=True)
class ConfigTransactionPreview:
    """Immutable display projection of an arbitrary config plan."""

    target_path: str | None
    effective: TransactionEffectivePreview | None
    diagnostics: tuple[TransactionDiagnostic, ...]
    warnings: tuple[str, ...]
    text_diff: str
    used_chezmoi: bool = False
    valid: bool = True

    @property
    def is_valid(self) -> bool:
        return self.valid and not any(
            diagnostic.severity == "error" for diagnostic in self.diagnostics
        )

    @classmethod
    def from_edit_plan(cls, plan: EditPlanResult) -> ConfigTransactionPreview:
        effective = plan.effective_preview
        diagnostics = tuple(
            TransactionDiagnostic(
                severity=item.severity,
                message=item.message,
                path=item.path,
                code=item.code,
            )
            for item in (*plan.validation, *plan.diagnostics)
        )
        return cls(
            target_path=plan.target_path,
            effective=TransactionEffectivePreview(
                has_before=effective.has_before,
                before=effective.before,
                has_after=effective.has_after,
                after=effective.after,
                changed=effective.changed,
            ),
            diagnostics=diagnostics,
            warnings=(),
            text_diff=plan.text_diff,
            used_chezmoi=plan.used_chezmoi,
            valid=plan.is_valid,
        )


def coerce_transaction_preview(plan: Any) -> ConfigTransactionPreview:
    """Normalize an injected plan into the shared preview record."""
    if isinstance(plan, ConfigTransactionPreview):
        return plan
    if isinstance(plan, EditPlanResult):
        return ConfigTransactionPreview.from_edit_plan(plan)
    preview = getattr(plan, "preview", None)
    if isinstance(preview, ConfigTransactionPreview):
        return preview
    if isinstance(plan, Mapping):
        return _preview_from_mapping(plan)
    raise TypeError(
        "plan callback must return EditPlanResult, ConfigTransactionPreview, "
        "or an object exposing a ConfigTransactionPreview as .preview"
    )


def render_transaction_preview(preview: ConfigTransactionPreview) -> Text:
    """Render target, effective change, warnings, validation, and unified diff."""
    text = Text()
    text.append("Target file\n", style="bold")
    text.append(f"  {preview.target_path or '(none)'}", style=_ACCENT)
    if preview.used_chezmoi:
        text.append("  (chezmoi source)", style=_MUTED)
    text.append("\n\n")
    if preview.effective is not None:
        _append_effective(preview.effective, text)
    _append_warnings(preview.warnings, text)
    _append_validation(preview.diagnostics, text)
    _append_diff(preview.text_diff, text)
    return text


def render_edit_plan_preview(plan: EditPlanResult) -> Text:
    """Compatibility helper for Config Center's existing plan type."""
    return render_transaction_preview(ConfigTransactionPreview.from_edit_plan(plan))


def _append_effective(preview: TransactionEffectivePreview, text: Text) -> None:
    text.append(preview.label, style="bold")
    text.append("  (after merge)\n", style=_MUTED)
    text.append("  ")
    text.append(
        _modal_inline_value(preview.before) if preview.has_before else "(unset)",
        style=_MUTED,
    )
    text.append("  →  ", style=_MUTED)
    text.append(
        _modal_inline_value(preview.after) if preview.has_after else "(unset)",
        style=f"bold {_OK_COLOR if preview.changed else _MUTED}",
    )
    text.append("\n\n")


def _append_warnings(warnings: Iterable[str], text: Text) -> None:
    items = tuple(warnings)
    if not items:
        return
    text.append("Warnings\n", style="bold")
    for warning in items:
        text.append("  warning: ", style=_WARN_COLOR)
        text.append(warning, style=_MUTED)
        text.append("\n")
    text.append("\n")


def _append_validation(
    diagnostics: Iterable[TransactionDiagnostic], text: Text
) -> None:
    issues = tuple(diagnostics)
    if not issues:
        text.append("Validation: ", style="bold")
        text.append("ok\n\n", style=_OK_COLOR)
        return
    text.append("Validation\n", style="bold")
    for diagnostic in issues:
        color = _ERR_COLOR if diagnostic.severity == "error" else _WARN_COLOR
        text.append(f"  {diagnostic.severity}: ", style=color)
        text.append(diagnostic.message, style=_MUTED)
        if diagnostic.path:
            text.append(f" [{diagnostic.path}]", style=f"dim {_MUTED}")
        text.append("\n")
    text.append("\n")


def _append_diff(diff: str, text: Text) -> None:
    text.append("Diff\n", style="bold")
    if not diff.strip():
        text.append("  (no changes — value already effective)\n", style=_MUTED)
        return
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            style = _OK_COLOR
        elif line.startswith("-") and not line.startswith("---"):
            style = _ERR_COLOR
        elif line.startswith("@@"):
            style = _ACCENT
        else:
            style = _MUTED
        text.append(f"  {line}\n", style=style)


def _modal_inline_value(value: Any) -> str:
    rendered = format_value(value)
    if (
        is_structured_value(value)
        or "\n" in rendered
        or len(rendered) > _INLINE_VALUE_MAX_WIDTH
    ):
        return format_row_value_summary(value, max_width=_INLINE_VALUE_MAX_WIDTH)
    return rendered


def _preview_from_mapping(payload: Mapping[str, Any]) -> ConfigTransactionPreview:
    effective_raw = payload.get("effective")
    effective: TransactionEffectivePreview | None = None
    if isinstance(effective_raw, Mapping):
        effective = TransactionEffectivePreview(
            has_before=bool(effective_raw.get("has_before", "before" in effective_raw)),
            before=effective_raw.get("before"),
            has_after=bool(effective_raw.get("has_after", "after" in effective_raw)),
            after=effective_raw.get("after"),
            changed=bool(effective_raw.get("changed", True)),
            label=str(effective_raw.get("label", "Effective value")),
        )
    diagnostics: list[TransactionDiagnostic] = []
    for item in payload.get("diagnostics", ()):
        if isinstance(item, TransactionDiagnostic):
            diagnostics.append(item)
        elif isinstance(item, Mapping):
            diagnostics.append(
                TransactionDiagnostic(
                    severity=str(item.get("severity", "error")),
                    message=str(item.get("message", "")),
                    path=str(item["path"]) if item.get("path") is not None else None,
                    code=str(item["code"]) if item.get("code") is not None else None,
                )
            )
    return ConfigTransactionPreview(
        target_path=(
            str(payload["target_path"])
            if payload.get("target_path") is not None
            else None
        ),
        effective=effective,
        diagnostics=tuple(diagnostics),
        warnings=tuple(str(item) for item in payload.get("warnings", ())),
        text_diff=str(payload.get("text_diff", "")),
        used_chezmoi=bool(payload.get("used_chezmoi", False)),
        valid=bool(payload.get("valid", True)),
    )


__all__ = [
    "ConfigTransactionPreview",
    "TransactionDiagnostic",
    "TransactionEffectivePreview",
    "coerce_transaction_preview",
    "render_edit_plan_preview",
    "render_transaction_preview",
]

TransactionPreview = ConfigTransactionPreview
