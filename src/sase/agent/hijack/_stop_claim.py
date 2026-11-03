"""Workspace claim and process effects for the hijack stop protocol."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sase.agent.hijack._stop_models import HijackTarget, StopDeps

LOG = logging.getLogger(__name__)

#: Grace period for the verified tree terminator (the existing 6 s default).
STOP_GRACE_SECONDS = 6.0


def pin_claim(target: HijackTarget) -> bool:
    from sase.running_field._hold import hold_workspace_claim

    assert target.workspace_num is not None
    result = hold_workspace_claim(
        target.project_file,
        int(target.workspace_num),
        target.workflow or "",
        target.cl_name or "",
        target.artifacts_timestamp,
        caller_tag="agent_hijack",
        expected_pid=target.claim_pid,
    )
    return bool(result.success)


def unpin_claim(target: HijackTarget) -> None:
    """Restore the pin this hijack set back to unpinned.

    Mirrors :mod:`sase.running_field._hold` under the same project lock:
    the matching RUNNING row is rewritten in place with ``PINNED`` removed.
    Only call when this hijack set the pin.
    """
    from sase.ace.patch import patch_lock, write_patch_atomic
    from sase.logs.workspace_claim_ledger import record_running_field_mutation
    from sase.running_field._model import WorkspaceClaim

    if target.workspace_num is None:
        return
    try:
        with patch_lock(target.project_file):
            with open(target.project_file, encoding="utf-8") as handle:
                content = handle.read()
            lines = content.splitlines(keepends=True)
            changed = False
            for index, line in enumerate(lines):
                claim = WorkspaceClaim.from_line(line)
                if (
                    claim is None
                    or claim.workspace_num != int(target.workspace_num)
                    or claim.artifacts_timestamp != target.artifacts_timestamp
                ):
                    continue
                if target.claim_pid is not None and claim.pid != int(target.claim_pid):
                    continue
                if not claim.pinned:
                    return
                suffix = tuple(part for part in claim.suffix_fields if part != "PINNED")
                lines[index] = (
                    WorkspaceClaim(
                        workspace_num=claim.workspace_num,
                        workflow=claim.workflow,
                        cl_name=claim.cl_name,
                        pid=claim.pid,
                        artifacts_timestamp=claim.artifacts_timestamp,
                        pinned=False,
                        suffix_fields=suffix,
                    ).to_line()
                    + "\n"
                )
                changed = True
                break
            if not changed:
                return
            write_patch_atomic(
                target.project_file,
                "".join(lines),
                f"Release hijack pin on workspace #{target.workspace_num}",
            )
            record_running_field_mutation(
                operation="unpin",
                project_file=target.project_file,
                workspace_num=int(target.workspace_num),
                success=True,
                before_content=content,
                after_content="".join(lines),
                workflow=target.workflow or "",
                cl_name=target.cl_name or "",
                artifacts_timestamp=target.artifacts_timestamp,
                claim_pid=target.claim_pid,
                caller_tag="agent_hijack",
            )
    except (OSError, BlockingIOError) as exc:
        LOG.warning("could not restore hijack pin: %s", exc)


def remove_intent(artifacts_dir: str) -> None:
    try:
        Path(artifacts_dir, ".sase_user_kill_pending").unlink(missing_ok=True)
    except OSError as exc:
        LOG.warning("could not remove hijack intent: %s", exc)


def abort_before_stop(target: HijackTarget, hijack_id: str, reason: str) -> None:
    remove_intent(target.artifacts_dir)
    try:
        from sase.agent.hijack import ledger

        path = ledger.hijack_record_path(hijack_id)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            LOG.warning("could not remove aborted hijack record: %s", exc)
    except Exception as exc:
        LOG.warning("could not remove aborted hijack record: %s", exc)
    LOG.warning("hijack %s aborted: %s", hijack_id, reason)


def terminate_tree(target: HijackTarget, *, deps: StopDeps) -> Any:
    terminate = deps.terminate
    if terminate is None:
        from sase.agent.user_kill import terminate_agent_processes

        terminate = terminate_agent_processes
    assert target.pid is not None
    return terminate(
        int(target.pid),
        artifacts_dir=target.artifacts_dir,
        grace_seconds=STOP_GRACE_SECONDS,
    )


def ensure_hijacked_settlement(
    target: HijackTarget, hijack_id: str, pinned_by_us: bool
) -> None:
    """Write the runner-equivalent settlement when the runner cannot.

    When the runner survives SIGTERM it settles itself; when it died first
    (wedged or SIGKILLED) no ``done.json`` exists, so the orchestrator writes
    the identical ``outcome: hijacked`` marker and re-asserts the pin. The
    runner path is idempotent with this one: an existing marker is kept.
    """
    from sase.agent._user_kill_intent import pending_hijack_recovery

    done_path = Path(target.artifacts_dir) / "done.json"
    if not done_path.exists():
        from sase.axe.run_agent_exec_markers import (
            write_done_marker_and_update_index,
        )
        from sase.axe.run_agent_markers import build_done_marker

        marker = build_done_marker(
            target.cl_name or "",
            target.project_file,
            target.artifacts_timestamp,
            target.artifacts_timestamp,
            int(target.workspace_num or 0),
            target.workspace_dir or "",
            "",
            "hijacked",
            agent_name=target.name,
            recovery=pending_hijack_recovery(target.artifacts_dir),
        )
        try:
            write_done_marker_and_update_index(target.artifacts_dir, marker)
        except Exception as exc:
            LOG.warning("could not write hijacked done.json: %s", exc)
    if not target.is_home and target.workspace_num is not None and pinned_by_us:
        pin_claim(target)


__all__ = [
    "STOP_GRACE_SECONDS",
    "abort_before_stop",
    "ensure_hijacked_settlement",
    "pin_claim",
    "remove_intent",
    "terminate_tree",
    "unpin_claim",
]
