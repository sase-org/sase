"""Generic yes/no confirmation modal for the ace TUI."""

from __future__ import annotations

from .confirm_dialog import ConfirmDefault, ConfirmDialog, ConfirmKind


class ConfirmActionModal(ConfirmDialog):
    """Generic modal for confirming an action with yes/no."""

    def __init__(
        self,
        title: str,
        message: str,
        *,
        subject: str | None = None,
        kind: ConfirmKind = ConfirmKind.NEUTRAL,
        icon: str | None = None,
        confirm_label: str = "Yes",
        cancel_label: str = "No",
        default: ConfirmDefault | None = None,
    ) -> None:
        super().__init__(
            title,
            message,
            subject=subject,
            kind=kind,
            icon=icon,
            confirm_label=confirm_label,
            cancel_label=cancel_label,
            default=default or ("cancel" if kind is ConfirmKind.DANGER else "confirm"),
        )


__all__ = ["ConfirmActionModal"]
