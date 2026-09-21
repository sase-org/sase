"""Detached sudo answer path and internal finalize proc.

Backward-compatible entry point: the implementation moved to
:mod:`sase.sudo.detach_approve` (approve path: spawn the executor and submit
the finalize proc) and :mod:`sase.sudo.detach_finalize` (internal ``sudo
finalize`` proc) so that no single file exceeds 500 lines.

Every name below stays importable from here. Shared helpers that callers
monkeypatch on this module (runner entry points, proc submission, ledger
readers, timing constants) are resolved through this module at call time via
a function-level ``from sase.sudo import detach`` import in the
implementation modules, so ``sase.sudo.detach.<name>`` remains the seam.
``_wait_for_executor_ledger`` stays available under its historic private name
for its importers; new code should use
:func:`sase.sudo.detach_finalize.wait_for_executor_ledger`.
"""

from sase.procs.submission import submit_proc_request
from sase.sudo.answer_ops import runner_timeout_seconds
from sase.sudo.detach_approve import (
    SUDO_ANSWER_DETACH_ORIGIN,
    approve_detached,
    approve_remote_detached,
)
from sase.sudo.detach_finalize import (
    finalize,
    wait_for_executor_ledger as _wait_for_executor_ledger,
)
from sase.sudo.execution import copy_output_log, executor_is_live, read_handoff_ledger
from sase.sudo.runner import run_sudo_runner_detached
from sase.sudo.ssh import run_remote_sudo_detached

_EXECUTOR_DEATH_GRACE_SECONDS = 1.0
_STOP_GRACE_SECONDS = 5.0

__all__ = [
    "SUDO_ANSWER_DETACH_ORIGIN",
    "_wait_for_executor_ledger",
    "approve_detached",
    "approve_remote_detached",
    "copy_output_log",
    "executor_is_live",
    "finalize",
    "read_handoff_ledger",
    "run_remote_sudo_detached",
    "run_sudo_runner_detached",
    "runner_timeout_seconds",
    "submit_proc_request",
]
