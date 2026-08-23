"""Presentation-neutral types for watching agent wait targets."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

WAIT_EXIT_SUCCESS = 0
WAIT_EXIT_FAILED = 1
WAIT_EXIT_USAGE = 2
WAIT_EXIT_BLOCKED = 3
WAIT_EXIT_TIMEOUT = 4
WAIT_EXIT_INTERRUPTED = 130


class WaitTargetKind(StrEnum):
    """The reference kind one wait target resolved to."""

    AGENT = "agent"
    CLAN = "clan"
    FAMILY = "family"
    WORKFLOW = "workflow"


class WaitState(StrEnum):
    """Current state for a target or one concrete target member."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TERMINAL_OTHER = "terminal_other"
    QUEUED = "queued"
    WAITING = "waiting"
    NEEDS_INPUT = "needs_input"
    NEEDS_REVIEW = "needs_review"
    STALLED = "stalled"
    RUNNING = "running"
    STARTING = "starting"


class WaitSettlementOutcome(StrEnum):
    """Final outcome for an entire wait run."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"
    INTERRUPTED = "interrupted"


class WaitTargetResolutionError(ValueError):
    """Raised when a wait target cannot be resolved or is unsafe to wait on."""


@dataclass(frozen=True)
class WaitCaller:
    """Identity for the agent invoking a wait command."""

    artifact_dir: str
    name: str | None = None
    workflow_name: str | None = None
    family_name: str | None = None
    clan_name: str | None = None


@dataclass(frozen=True)
class WaitTarget:
    """One user-requested wait unit resolved at command start."""

    raw_name: str
    name: str
    kind: WaitTargetKind
    artifact_dir: str | None = None
    project_name: str | None = None
    workflow_dir_name: str = "ace-run"
    family_root_timestamp: str | None = None
    clan_generation: str | None = None

    @property
    def key(self) -> tuple[str, str, str | None, str | None]:
        """Return a stable de-duplication key for target collections."""

        identity = self.artifact_dir if self.kind is WaitTargetKind.AGENT else self.name
        return (
            self.kind.value,
            identity or self.name,
            self.project_name,
            self.clan_generation,
        )


@dataclass(frozen=True)
class WaitMemberState:
    """State for one concrete artifact included in a target."""

    name: str
    artifact_dir: str
    state: WaitState
    outcome: str | None = None
    project_name: str | None = None
    timestamp: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class WaitTargetState:
    """Current state for one resolved wait target."""

    target: WaitTarget
    state: WaitState
    members: tuple[WaitMemberState, ...] = ()
    reason: str | None = None

    @property
    def blocked(self) -> bool:
        return is_blocked_state(self.state)

    @property
    def failed(self) -> bool:
        return self.state in {WaitState.FAILED, WaitState.TERMINAL_OTHER}

    @property
    def succeeded(self) -> bool:
        return self.state is WaitState.SUCCEEDED


@dataclass(frozen=True)
class WaitSettlement:
    """Terminal result for a wait run."""

    outcome: WaitSettlementOutcome
    target_states: tuple[WaitTargetState, ...]
    elapsed_seconds: float
    exit_code: int
    reason: str | None = None


@dataclass(frozen=True)
class WaitTick:
    """One poll tick emitted by the wait engine."""

    index: int
    elapsed_seconds: float
    target_states: tuple[WaitTargetState, ...]
    settlement: WaitSettlement | None = None

    @property
    def settled(self) -> bool:
        return self.settlement is not None


def is_blocked_state(state: WaitState) -> bool:
    return state in {
        WaitState.NEEDS_INPUT,
        WaitState.NEEDS_REVIEW,
        WaitState.STALLED,
    }


def _is_terminal_state(state: WaitState) -> bool:
    return state in {
        WaitState.SUCCEEDED,
        WaitState.FAILED,
        WaitState.TERMINAL_OTHER,
    }


def is_stop_state(state: WaitState, *, wait_blocked: bool) -> bool:
    return _is_terminal_state(state) or (is_blocked_state(state) and not wait_blocked)


def _exit_code_for_outcome(outcome: WaitSettlementOutcome) -> int:
    return {
        WaitSettlementOutcome.SUCCEEDED: WAIT_EXIT_SUCCESS,
        WaitSettlementOutcome.FAILED: WAIT_EXIT_FAILED,
        WaitSettlementOutcome.BLOCKED: WAIT_EXIT_BLOCKED,
        WaitSettlementOutcome.TIMEOUT: WAIT_EXIT_TIMEOUT,
        WaitSettlementOutcome.INTERRUPTED: WAIT_EXIT_INTERRUPTED,
    }[outcome]


def _settlement_outcome_for_states(
    states: Sequence[WaitTargetState],
    *,
    timed_out: bool = False,
    interrupted: bool = False,
) -> WaitSettlementOutcome | None:
    """Return the final outcome implied by target states and stop conditions."""

    if any(state.failed for state in states):
        return WaitSettlementOutcome.FAILED
    if any(state.blocked for state in states):
        return WaitSettlementOutcome.BLOCKED
    if interrupted:
        return WaitSettlementOutcome.INTERRUPTED
    if timed_out:
        return WaitSettlementOutcome.TIMEOUT
    if all(state.succeeded for state in states):
        return WaitSettlementOutcome.SUCCEEDED
    return None


def make_settlement(
    states: Sequence[WaitTargetState],
    *,
    elapsed_seconds: float,
    timed_out: bool = False,
    interrupted: bool = False,
    reason: str | None = None,
) -> WaitSettlement | None:
    outcome = _settlement_outcome_for_states(
        states,
        timed_out=timed_out,
        interrupted=interrupted,
    )
    if outcome is None:
        return None
    return WaitSettlement(
        outcome=outcome,
        target_states=tuple(states),
        elapsed_seconds=elapsed_seconds,
        exit_code=_exit_code_for_outcome(outcome),
        reason=reason,
    )


@dataclass(frozen=True)
class WaitWatchConfig:
    """Runtime knobs for the polling engine."""

    targets: tuple[WaitTarget, ...]
    interval_seconds: float | None = None
    timeout_seconds: float | None = None
    wait_blocked: bool = False
    stop_requested: Callable[[], bool] | None = field(default=None, compare=False)
