"""Shared error type for axe workspace preparation."""


class WorkspacePreparationError(RuntimeError):
    """Raised when workspace preparation fails, carrying the underlying reason.

    Attributes:
        reason: The underlying git/update/guard failure text (command
            stderr, exit detail, or guard refusal message).
        step: Which preparation step failed (``clean``, ``checkout``,
            ``sync``, ``fetch``, ``verify``, ``heal``,
            ``sidecar-protection``, or ``agents-sync-guard``).
        workspace_dir: The workspace that could not be prepared.
        reclone_eligible: Whether the failure is a local-state failure the
            reclone phase may repair by re-creating the workspace. Fetch and
            network failures, and every failure outside self-heal mode, are
            never eligible.
    """

    def __init__(
        self,
        reason: str,
        *,
        step: str = "",
        workspace_dir: str = "",
        reclone_eligible: bool = False,
    ) -> None:
        self.reason = reason
        self.step = step
        self.workspace_dir = workspace_dir
        self.reclone_eligible = reclone_eligible
        location = f" {workspace_dir}" if workspace_dir else ""
        detail = f" during {step}" if step else ""
        super().__init__(f"Failed to prepare workspace{location}{detail}: {reason}")


__all__ = ["WorkspacePreparationError"]
