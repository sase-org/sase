"""Bundle-backed implementation of the gate modals' action contract.

This is the only place ACE turns a declared gate action into work against a
bundle: the modal asks for an action by id and gets an outcome back, and never
learns where the bundle lives or how the editor was launched.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.ace.tui.actions._durable_ops import (
    durable_fingerprint,
    durable_request_payload,
    sase_argv,
)
from sase.ops.names import GATE_ACT

from ...modals.gate_action_controls import GateActionsData
from ...modals.gate_action_runner import GateCommandOutcome, GateEditOutcome

if TYPE_CHECKING:
    from sase.notification_gates.model_operations import GateOperation
    from sase.notifications import Notification


def load_gate_actions(bundle_path: Path, envelope: dict[str, Any]) -> GateActionsData:
    """Project a verified envelope's declared actions and its draft state.

    Called from the worker thread that already loaded the bundle, never on the
    event loop: reading a draft state hashes the origin file.
    """
    from sase.notification_gates.edits import origin_draft_state, resolve_edit_path
    from sase.notification_gates.model_operations import GateOperation
    from sase.notification_gates.models import GateError

    raw_operations = envelope.get("operations")
    if not isinstance(raw_operations, list) or not raw_operations:
        return GateActionsData()
    operations = tuple(
        GateOperation.from_mapping(raw, index)
        for index, raw in enumerate(raw_operations)
    )
    for operation in operations:
        if operation.kind != "edit_file":
            continue
        try:
            if origin_draft_state(bundle_path, operation.id) != "draft":
                continue
            draft_path = resolve_edit_path(bundle_path, envelope, operation.id).path
        except (GateError, OSError):
            continue
        return GateActionsData(
            operations=operations,
            draft_operation_id=operation.id,
            draft_path=_display_path(draft_path),
        )
    return GateActionsData(operations=operations)


def _display_path(path: Path) -> str:
    home = Path.home()
    try:
        return f"~/{path.relative_to(home)}"
    except ValueError:
        return str(path)


@dataclass
class NotificationGateActionRunner:
    """Run one gate's declared actions against its bundle on ACE's behalf."""

    app: Any
    notification: Notification
    bundle_path: Path
    operations: tuple[GateOperation, ...]

    def run_edit(self, operation_id: str) -> GateEditOutcome:
        """Edit the declared target in ``$EDITOR`` and accept the result."""
        from sase.notification_gates.durability import read_json_object
        from sase.notification_gates.edits import (
            accept_edited_origin,
            resolve_edit_path,
        )
        from sase.notification_gates.models import GateError

        try:
            envelope = read_json_object(self.bundle_path / "request.json")
            target = resolve_edit_path(self.bundle_path, envelope, operation_id)
        except (GateError, OSError) as exc:
            return GateEditOutcome(accepted=False, message=str(exc))

        editor = os.environ.get("EDITOR") or "nvim"
        with self.app.suspend():
            subprocess.run([editor, str(target.path)], check=False)

        draft_path = _display_path(target.path)
        try:
            accept_edited_origin(self.bundle_path, operation_id)
        except Exception as exc:
            # An adapter rejects with whatever error its own validator raises
            # — the plan adapter with PlanApprovalValidationError — and every
            # one of them is a diagnosable rejection, not a crash.
            return GateEditOutcome(
                accepted=False,
                message=str(exc),
                draft=self._is_draft(operation_id),
                draft_path=draft_path,
            )
        return GateEditOutcome(
            accepted=True,
            content=self.reviewed_content(),
            draft=False,
            draft_path=draft_path,
        )

    def discard_draft(self, operation_id: str) -> GateEditOutcome:
        """Throw the origin draft away and restore the reviewed content."""
        from sase.notification_gates.edits import discard_origin_draft
        from sase.notification_gates.models import GateError

        try:
            discard_origin_draft(self.bundle_path, operation_id)
        except (GateError, OSError) as exc:
            return GateEditOutcome(
                accepted=False, message=str(exc), draft=self._is_draft(operation_id)
            )
        return GateEditOutcome(
            accepted=True,
            content=self.reviewed_content(),
            message="Discarded your draft",
            draft=False,
        )

    def run_command(
        self, operation_id: str, on_done: Callable[[GateCommandOutcome], None]
    ) -> bool:
        """Run one ``run_command`` action through ACE's durable task queue."""
        submit = getattr(self.app, "_submit_durable_proc", None)
        if not callable(submit):
            return False

        operation = self._operation(operation_id)
        label = operation_id if operation is None else operation.label
        request_id = str(
            self.notification.action_data.get("request_id") or self.notification.id
        )
        request_kind = str(
            self.notification.action_data.get("request_kind") or "custom"
        )

        def on_complete(completion: object) -> None:
            outcome = getattr(completion, "payload", None)
            if isinstance(outcome, dict):
                outcome = GateCommandOutcome(
                    success=bool(getattr(completion, "success", False)),
                    summary=_optional_str(outcome.get("summary")),
                    body=_optional_str(outcome.get("body")),
                    display_format=str(outcome.get("display_format") or "text"),
                    refresh=bool(outcome.get("refresh")),
                    message=_optional_str(outcome.get("message")),
                )
            else:
                outcome = GateCommandOutcome(
                    success=False,
                    message=str(getattr(completion, "message", "Action failed")),
                )
            on_done(outcome)

        task = submit(
            sase_argv(
                "gate",
                "act",
                "--id",
                request_id,
                "--kind",
                request_kind,
                "--operation",
                operation_id,
                "--json",
            ),
            operation=GATE_ACT,
            request=durable_request_payload(input_data=None),
            request_fingerprint=durable_fingerprint(
                GATE_ACT,
                request_kind,
                request_id,
                operation_id,
            ),
            concurrency_keys=(f"gate-action:{self.notification.id}:{operation_id}",),
            label=f"Gate action: {label}",
            display_name=f"Gate action: {label}",
            cl_name=f"action {operation_id}",
            project_file=str(self.bundle_path),
            on_complete=on_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )
        return task is not None

    def reviewed_content(self) -> str | None:
        """Re-verify the bundle and read back the reviewed document text."""
        from sase.notification_gates.hashing import load_and_verify_bundle
        from sase.notification_gates.models import GateError
        from sase.notification_gates.paths import owned_resource_path

        target = next(
            (
                operation.target
                for operation in self.operations
                if operation.kind == "edit_file" and operation.target
            ),
            None,
        )
        if target is None:
            return None
        try:
            load_and_verify_bundle(self.bundle_path)
            path = owned_resource_path(self.bundle_path, target)
            return path.read_text(encoding="utf-8")
        except (GateError, OSError, UnicodeDecodeError):
            return None

    def _is_draft(self, operation_id: str) -> bool:
        from sase.notification_gates.edits import origin_draft_state
        from sase.notification_gates.models import GateError

        try:
            return origin_draft_state(self.bundle_path, operation_id) == "draft"
        except (GateError, OSError):
            return False

    def _operation(self, operation_id: str) -> GateOperation | None:
        for operation in self.operations:
            if operation.id == operation_id:
                return operation
        return None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def legacy_plan_edit_actions() -> GateActionsData:
    """Synthesize the plan edit action for a notification with no gate bundle.

    Pre-gate plan notifications never declared actions, but the reviewer has
    always been able to press ``e``. Presenting the same declared action keeps
    one rendering path instead of a legacy branch inside the modal.
    """
    from sase.notification_gates.model_operations import GateOperation

    return GateActionsData(
        operations=(
            GateOperation.from_mapping(
                {
                    "id": "edit_plan",
                    "kind": "edit_file",
                    "target": "plan.md",
                    "label": "Edit plan",
                    "icon": "✏️",
                    "key": "e",
                },
                0,
            ),
        )
    )


@dataclass
class PlainFileEditRunner:
    """Edit a file that has no bundle behind it, accepting whatever is written.

    There is nothing to validate against and nothing to hold a draft, so an
    edit is always accepted and there is never a draft to discard.
    """

    app: Any
    path: Path

    def run_edit(self, operation_id: str) -> GateEditOutcome:
        del operation_id
        editor = os.environ.get("EDITOR") or "nvim"
        with self.app.suspend():
            subprocess.run([editor, str(self.path)], check=False)
        return GateEditOutcome(accepted=True, content=self.reviewed_content())

    def discard_draft(self, operation_id: str) -> GateEditOutcome:
        del operation_id
        return GateEditOutcome(accepted=True)

    def run_command(
        self, operation_id: str, on_done: Callable[[GateCommandOutcome], None]
    ) -> bool:
        del operation_id, on_done
        return False

    def reviewed_content(self) -> str | None:
        try:
            return self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None


__all__ = [
    "NotificationGateActionRunner",
    "PlainFileEditRunner",
    "legacy_plan_edit_actions",
    "load_gate_actions",
]
