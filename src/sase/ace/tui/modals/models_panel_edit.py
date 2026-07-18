"""Preview-and-confirm modal for a persistent model-alias edit.

Phase 3 (epic sase-5e): when the user edits or resets an alias from the Models
panel, this modal plans the relevant ``llm_provider.model_aliases.builtin`` or
``llm_provider.model_aliases.custom`` set/unset edit (Rust-backed,
source-preserving), shows the *effective* before→after value and the target-file
diff, and on confirm writes it — applying chezmoi when enabled, exactly like the
Config Center. It dismisses with an :class:`AliasEditOutcome`
after a successful write (so the panel can offer commit+push), or ``None`` on
cancel.

Planning and writing both run in worker threads so the Rust call and disk IO
never block the event loop; the modal renders ``planning…`` / ``writing…``
states in between.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from sase.config import (
    ConfigEditError,
    ConfigEditOp,
    EditPlanResult,
    apply_chezmoi,
    apply_config_edit,
)

from .config_edit_types import (
    _ACCENT,
    _ERR_COLOR,
    _MOD_COLOR,
    _MUTED,
    _OK_COLOR,
)
from .models_panel_edit_helpers import AliasEditOutcome, plan_alias_edit


class AliasEditPreviewModal(ModalScreen["AliasEditOutcome | None"]):
    """Plan, preview, confirm, and write a single persistent alias edit."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("y", "confirm", "Write"),
        ("enter", "confirm", "Write"),
        ("ctrl+s", "confirm", "Write"),
    ]

    def __init__(
        self,
        alias: str,
        op: ConfigEditOp,
        *,
        path: str | None = None,
        action_label: str | None = None,
        reset_deletes_alias: bool = False,
    ) -> None:
        super().__init__()
        self._alias = alias
        self._op = op
        self._path = path
        self._action_label = action_label
        self._reset_deletes_alias = reset_deletes_alias
        self._is_unset = op.kind == "unset"
        self._plan: EditPlanResult | None = None
        self._busy = True  # planning on mount
        self._error: str | None = None
        self._plan_worker: Worker[Any] | None = None
        self._apply_worker: Worker[Any] | None = None

    # -- compose --------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="alias-edit-container"):
            yield Static(self._title_text(), id="alias-edit-title")
            with VerticalScroll(id="alias-edit-preview-scroll"):
                yield Static(self._body_text(), id="alias-edit-preview")
            yield Static(self._hints_text(), id="alias-edit-hints")

    def on_mount(self) -> None:
        self._start_plan()

    # -- rendering ------------------------------------------------------

    def _title_text(self) -> Text:
        verb = self._action_label or ("Reset" if self._is_unset else "Edit")
        text = Text()
        text.append(f"{verb} Model Alias  ", style="bold")
        text.append(f"@{self._alias}", style=f"bold {_ACCENT}")
        return text

    def _render_all(self) -> None:
        self.query_one("#alias-edit-preview", Static).update(self._body_text())
        self.query_one("#alias-edit-hints", Static).update(self._hints_text())

    def _body_text(self) -> Text:
        if self._error is not None:
            return Text(f"✗ {self._error}", style=_ERR_COLOR)
        if self._busy and self._plan is None:
            return Text("planning…", style=_MUTED)
        if self._plan is None:
            return Text("planning…", style=_MUTED)
        return self._preview_text(self._plan)

    def _preview_text(self, plan: EditPlanResult) -> Text:
        text = Text()
        self._append_operation(text)
        text.append("\nTarget\n", style="bold")
        text.append(f"  {plan.target_path or '(none)'}\n", style=_ACCENT)
        if plan.used_chezmoi:
            text.append("  (chezmoi source — applied on write)\n", style=_MUTED)
        self._append_effective(text, plan)
        self._append_validation(text, plan)
        self._append_diff(text, plan)
        return text

    def _append_operation(self, text: Text) -> None:
        text.append("Operation\n", style="bold")
        if self._is_unset:
            text.append("  reset ", style=f"bold {_MOD_COLOR}")
            text.append(f"@{self._alias}", style=f"bold {_ACCENT}")
            if self._reset_deletes_alias:
                text.append(" by deleting the custom alias ", style=_MUTED)
            else:
                text.append(" to its implicit fallback ", style=_MUTED)
            text.append("(removes the configured key)\n", style=_MUTED)
            return
        text.append("  set ", style="bold")
        text.append(f"@{self._alias}", style=f"bold {_ACCENT}")
        text.append("  →  ", style=_MUTED)
        text.append(str(self._op.value), style=f"bold {_OK_COLOR}")
        text.append("\n")

    @staticmethod
    def _append_effective(text: Text, plan: EditPlanResult) -> None:
        preview = plan.effective_preview
        text.append("\nEffective\n", style="bold")
        before = _format_effective(preview.has_before, preview.before)
        after = _format_effective(preview.has_after, preview.after)
        text.append("  ")
        text.append(before, style=_MUTED)
        text.append("  →  ", style=_MUTED)
        text.append(
            after,
            style=f"bold {_OK_COLOR if preview.changed else _MUTED}",
        )
        text.append("\n")

    @staticmethod
    def _append_validation(text: Text, plan: EditPlanResult) -> None:
        errors = [d for d in plan.validation if d.severity == "error"]
        if not errors:
            return
        text.append("\nValidation\n", style="bold")
        for diagnostic in errors:
            text.append(f"  ✗ {diagnostic.message}\n", style=_ERR_COLOR)

    @staticmethod
    def _append_diff(text: Text, plan: EditPlanResult) -> None:
        text.append("\nDiff\n", style="bold")
        if not plan.text_diff.strip():
            text.append("  (no changes — value already effective)\n", style=_MUTED)
            return
        for line in plan.text_diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                style = _OK_COLOR
            elif line.startswith("-") and not line.startswith("---"):
                style = _ERR_COLOR
            elif line.startswith("@@"):
                style = _ACCENT
            else:
                style = _MUTED
            text.append(f"  {line}\n", style=style)

    def _hints_text(self) -> str:
        if self._busy:
            return "writing…" if self._plan is not None else "planning…"
        if self._plan is not None and self._can_write(self._plan):
            return "y / enter: write   esc: cancel"
        return "esc: cancel"

    # -- planning -------------------------------------------------------

    def _start_plan(self) -> None:
        alias = self._alias
        op = self._op
        path = self._path

        def task() -> EditPlanResult:
            return plan_alias_edit(alias, op, path=path)

        self._busy = True
        self._plan_worker = self.run_worker(task, thread=True, exclusive=True)

    # -- writing --------------------------------------------------------

    def _can_write(self, plan: EditPlanResult) -> bool:
        return plan.is_valid and bool(plan.text_diff.strip())

    def action_confirm(self) -> None:
        if self._busy:
            return
        plan = self._plan
        if plan is None:
            return
        if not plan.is_valid:
            self._error = "fix validation errors before writing"
            self._render_all()
            return
        if not plan.text_diff.strip():
            self._error = "nothing to write — value already effective"
            self._render_all()
            return
        self._busy = True
        self._error = None
        self._render_all()

        def task() -> tuple[AliasEditOutcome, str | None]:
            applied = apply_config_edit(plan)
            note: str | None = None
            # ``chezmoi apply`` takes the home *target* path, not the chezmoi
            # source we just wrote to. Only apply when a real source→target
            # remap happened (target differs from the written source path).
            target = plan.write_plan.file
            if applied.used_chezmoi and target is not None and target != applied.path:
                proc = apply_chezmoi(target)
                if proc.returncode != 0:
                    detail = proc.stderr.strip() or f"exit {proc.returncode}"
                    note = f"chezmoi apply failed: {detail}"
            return AliasEditOutcome(alias=self._alias, applied=applied), note

        self._apply_worker = self.run_worker(task, thread=True, exclusive=True)

    def action_cancel(self) -> None:
        if self._busy and self._apply_worker is not None:
            # A write is in flight; don't abandon it mid-flight.
            return
        self.dismiss(None)

    # -- worker plumbing ------------------------------------------------

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._plan_worker:
            self._on_plan_worker(event)
        elif event.worker is self._apply_worker:
            self._on_apply_worker(event)

    def _on_plan_worker(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            self._busy = False
            self._plan = event.worker.result
            self._render_all()
        elif event.state == WorkerState.ERROR:
            self._busy = False
            self._error = self._worker_error(event, "could not plan edit")
            self._render_all()

    def _on_apply_worker(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            self._busy = False
            outcome = event.worker.result
            if not isinstance(outcome, tuple):
                self.dismiss(None)
                return
            result, note = outcome
            if note is not None:
                # The file was written but chezmoi propagation failed; keep the
                # modal open so the user can retry or apply chezmoi manually.
                self._error = note
                self._render_all()
                return
            self.dismiss(result)
        elif event.state == WorkerState.ERROR:
            self._busy = False
            self._error = self._worker_error(event, "write failed")
            self._render_all()

    @staticmethod
    def _worker_error(event: Worker.StateChanged, fallback: str) -> str:
        error = event.worker.error
        if isinstance(error, ConfigEditError):
            return str(error)
        return str(error) if error else fallback


def _format_effective(has_value: bool, value: object) -> str:
    """Render an effective-value side of the before/after preview."""
    if not has_value:
        return "(unset)"
    return str(value)


__all__ = ["AliasEditPreviewModal"]
