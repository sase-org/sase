"""Types and configuration lookup helpers for single chop runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .config import AxeConfig, ChopConfig, LumberjackConfig


ChopRunOutcomeStatus = Literal[
    "success",
    "failure",
    "timeout",
    "missing_script",
    "already_running",
    "skipped",
    "no_op",
    "check_error",
    "launched",
    "action_succeeded",
    "action_failed",
]


@dataclass
class ChopRunOutcome:
    """Result of running one configured chop once.

    ``run_id`` is set whenever an entry was opened in the chop run history,
    including dedupe skips (where it points at the already-running entry).
    ``error``/``traceback`` are populated for failure-shaped outcomes so
    callers can surface diagnostics without re-reading the on-disk metadata.
    """

    lumberjack_name: str
    chop_name: str
    status: ChopRunOutcomeStatus
    run_id: str | None = None
    exit_code: int | None = None
    agent_pid: int | None = None
    output_bytes: int = 0
    error: Exception | None = None
    traceback: str | None = None
    result: dict[str, Any] | None = None
    proposals: tuple[dict[str, Any], ...] = ()
    launches: tuple[dict[str, Any], ...] = ()
    dry_run: bool = False
    chop_verbose: bool = False
    reason: str | None = None
    advances_cadence: bool = True


class ChopNotFoundError(LookupError):
    """Raised when a chop name does not match any configured chop."""

    def __init__(self, chop_name: str, lumberjack_name: str | None = None) -> None:
        if lumberjack_name is None:
            super().__init__(f"chop '{chop_name}' is not configured")
        else:
            super().__init__(
                f"chop '{chop_name}' is not configured under lumberjack "
                f"'{lumberjack_name}'"
            )
        self.chop_name = chop_name
        self.lumberjack_name = lumberjack_name


class AmbiguousChopError(LookupError):
    """Raised when a chop name appears under multiple lumberjacks and none was given."""

    def __init__(self, chop_name: str, candidates: list[str]) -> None:
        joined = ", ".join(sorted(candidates))
        super().__init__(
            f"chop '{chop_name}' is configured in multiple lumberjacks: {joined}"
            " — pass --lumberjack to disambiguate"
        )
        self.chop_name = chop_name
        self.candidates = sorted(candidates)


@dataclass
class ChopMatch:
    lumberjack_name: str
    lumberjack: LumberjackConfig
    chop: ChopConfig


def find_configured_chop(
    config: AxeConfig,
    chop_name: str,
    lumberjack_name: str | None = None,
) -> ChopMatch:
    """Resolve a chop name to its configured lumberjack and chop config.

    ``lumberjack_name`` constrains the search; without it, a chop name that
    appears under more than one lumberjack raises :class:`AmbiguousChopError`.
    """
    matches: list[ChopMatch] = []
    for jack_name, jack in config.lumberjacks.items():
        if lumberjack_name is not None and jack_name != lumberjack_name:
            continue
        for chop in jack.chops:
            if chop.enabled and chop.name == chop_name:
                matches.append(ChopMatch(jack_name, jack, chop))

    if not matches:
        raise ChopNotFoundError(chop_name=chop_name, lumberjack_name=lumberjack_name)
    if len(matches) > 1 and lumberjack_name is None:
        raise AmbiguousChopError(
            chop_name=chop_name,
            candidates=[m.lumberjack_name for m in matches],
        )
    return matches[0]


_ChopMatch = ChopMatch
