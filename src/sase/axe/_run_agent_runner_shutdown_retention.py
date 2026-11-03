"""Workspace-retention policy for the run-agent shutdown lifecycle."""

from sase.core.dismissed_agent_completion import GATE_OUTCOME
from sase.axe._run_agent_runner_shutdown_types import RunnerShutdownState


_NON_HOLD_FAILURE_OUTCOMES = {
    GATE_OUTCOME,
    "killed",
    "failed_retried",
    "plan_rejected",
    "plan_committed",
    "epic_approved",
    "epic_launch_failed",
    "setup_materialization_failed",
    "setup_workspace_failed",
}


def should_hold_workspace(
    state: RunnerShutdownState,
    *,
    was_killed: bool,
    auto_dismiss: bool,
    steps_hidden: bool,
    has_deferred_commit: bool,
) -> bool:
    """Return whether this run has a visible dismissal path.

    A failed run always needs one. A completed run needs one too when the
    host upheld a commit deferral: the tree is dirty on purpose and someone
    still has to finish the commit by hand.

    Staged turns reach here with ``failed`` after a held adoption (unresolved
    stage, failed finalization, or provider failure), so the existing failed
    branch already retains dirty failed work through the failure hold. An
    explicit user kill discards the stage first, so ``was_killed`` correctly
    releases. Adopted staged turns settle as ordinary completions.
    """
    if state.exec_outcome == "hijacked":
        return True
    if (
        was_killed
        or auto_dismiss
        or steps_hidden
        or state.suppress_completion_notification
    ):
        return False
    if state.success:
        return has_deferred_commit
    return state.exec_outcome not in _NON_HOLD_FAILURE_OUTCOMES
