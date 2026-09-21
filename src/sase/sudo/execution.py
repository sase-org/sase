"""Detached sudo execution records, handoff directories, and liveness.

Backward-compatible entry point: the implementation moved to
:mod:`sase.sudo.execution_state` (record, validation, and persistence),
:mod:`sase.sudo.execution_handoff` (handoff directories and output IO), and
:mod:`sase.sudo.execution_attempts` (liveness and attempt lifecycle) so that no
single file exceeds 500 lines.

Every name below stays importable from here. Shared helpers that callers
monkeypatch on this module (``_proc_is_live``, ``_pid_is_running``,
``executor_is_live``, ``process_identity_matches``) are resolved through this
module at call time via a function-level ``from sase.sudo import execution``
import in :mod:`sase.sudo.execution_attempts`, so ``sase.sudo.execution.<name>``
remains the seam.
"""

from sase.core.process_identity import process_identity_matches
from sase.sudo.execution_attempts import (
    abandon_unstarted_attempt,
    claim_execution_record,
    execution_is_live,
    execution_liveness,
    executor_is_live,
    live_execution_error,
    pid_is_running as _pid_is_running,
    proc_is_live as _proc_is_live,
    project_execution,
    recover_dead_attempt,
)
from sase.sudo.execution_handoff import (
    cleanup_handoff,
    copy_output_log,
    create_handoff_dir,
    handshake_from_runner_payload,
    read_handoff_ledger,
    write_stop_file,
)
from sase.sudo.execution_state import (
    EXECUTION_STATE_FILENAME,
    EXECUTION_STATE_SCHEMA_VERSION,
    HANDOFF_DIR_MODE,
    HANDOFF_FILE_MODE,
    LEDGER_FILENAME,
    LOG_FILENAME,
    MANIFEST_FILENAME,
    STOP_FILENAME,
    SUDO_EXEC_STARTED_KIND,
    SudoExecutionState,
    clear_execution_state,
    execution_lock,
    load_execution_state,
    write_execution_state,
)

__all__ = [
    "EXECUTION_STATE_FILENAME",
    "EXECUTION_STATE_SCHEMA_VERSION",
    "HANDOFF_DIR_MODE",
    "HANDOFF_FILE_MODE",
    "LEDGER_FILENAME",
    "LOG_FILENAME",
    "MANIFEST_FILENAME",
    "STOP_FILENAME",
    "SUDO_EXEC_STARTED_KIND",
    "SudoExecutionState",
    "abandon_unstarted_attempt",
    "claim_execution_record",
    "cleanup_handoff",
    "clear_execution_state",
    "copy_output_log",
    "create_handoff_dir",
    "execution_is_live",
    "execution_liveness",
    "execution_lock",
    "executor_is_live",
    "handshake_from_runner_payload",
    "live_execution_error",
    "load_execution_state",
    "project_execution",
    "read_handoff_ledger",
    "recover_dead_attempt",
    "write_execution_state",
    "write_stop_file",
]
