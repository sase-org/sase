"""Classifier inputs assembled from one failed agent's markers.

For each failed agent, :func:`assemble_done_row_input` reads the raw
``done.json`` / ``agent_meta.json`` pair plus the runner log tail and
builds the three classifier arguments: structured failure facts (when
the row has them), the context wire, and the W1-W3 witnesses.
:func:`assemble_bundle_input` does the same for dismissed bundles whose
artifact directory was already wiped.

Legacy and log-only rows carry no breadcrumbs or facts: they assemble
``facts=None`` with the error, traceback, and log tail in the context,
so the classifier's regex fallback and legacy phase heuristic apply.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Mapping

from sase.agent.auto_restart.managed_roots import ManagedRoot
from sase.agent.auto_restart.witnesses import WitnessInputs, collect_witnesses
from sase.core.agent_auto_restart_wire import (
    AgentFailureFactsWire,
    AutoRestartContextWire,
    AutoRestartManagedRootWire,
    AutoRestartWitnessesWire,
    agent_failure_facts_from_dict,
)

#: Runner log lines kept per row (the plan's last-200-lines contract).
LOG_TAIL_LINES = 200

#: At most this many bytes are read from one marker file.
MAX_MARKER_BYTES = 1_048_576


@dataclass(frozen=True)
class AssembledInput:
    """One failed agent's classifier inputs plus display metadata."""

    name: str
    project: str
    artifacts_dir: str | None
    died_at: float | None
    facts: AgentFailureFactsWire | None
    context: AutoRestartContextWire
    witnesses: AutoRestartWitnessesWire
    lifecycle_phase: str | None


def read_json_dict(path: Path) -> dict[str, Any] | None:
    """Read a small JSON object file; ``None`` on any problem."""
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > MAX_MARKER_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_log_tail(log_path: Path | None) -> str:
    """Return the last :data:`LOG_TAIL_LINES` lines of a runner log."""
    if log_path is None:
        return ""
    try:
        if not log_path.is_file():
            return ""
        with log_path.open("rb") as stream:
            try:
                stream.seek(0, 2)
                size = stream.tell()
                stream.seek(max(0, size - MAX_MARKER_BYTES))
                raw = stream.read()
            except OSError:
                return ""
    except OSError:
        return ""
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    return "\n".join(lines[-LOG_TAIL_LINES:])


def find_runner_log(
    artifacts_timestamp: str | None,
    output_path: str | None,
    workflows_root: Path | None = None,
) -> Path | None:
    """Locate a run's log via ``done.json``, else by timestamp glob.

    ``output_path`` (written by current runners) wins. Older rows only
    carry the artifacts timestamp, which maps onto the runner filename
    suffix ``YYmmdd_HHMMSS`` (``20261009112914`` → ``261009_112914``).
    """
    if output_path:
        candidate = Path(output_path).expanduser()
        if candidate.is_file():
            return candidate
    if not artifacts_timestamp:
        return None
    digits = "".join(ch for ch in artifacts_timestamp if ch.isdigit())
    if len(digits) == 14:
        suffix = f"{digits[2:8]}_{digits[8:14]}"
    elif len(digits) == 12:
        suffix = f"{digits[0:6]}_{digits[6:12]}"
    else:
        return None
    if workflows_root is None:
        from sase.core.paths import sase_subdir

        workflows_root = sase_subdir("workflows")
    try:
        matches = sorted(workflows_root.glob(f"*/gh_*_ace-run-{suffix}.txt"))
        matches.extend(sorted(workflows_root.glob(f"*/*_ace-run-{suffix}.txt")))
    except OSError:
        return None
    for match in matches:
        if match.is_file():
            return match
    return None


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _managed_root_wires(
    roots: tuple[ManagedRoot, ...],
) -> tuple[AutoRestartManagedRootWire, ...]:
    return tuple(
        AutoRestartManagedRootWire(name=root.name, root=root.source_root or "")
        for root in roots
    )


def _pending_question(artifacts_dir: Path | None, meta: Mapping[str, Any]) -> bool:
    """Return whether a pending question marker survives for this row."""
    if artifacts_dir is not None:
        try:
            if (artifacts_dir / "pending_question.json").is_file():
                return True
        except OSError:
            pass
    if _text(meta.get("question_request_path")) and not _text(
        meta.get("question_response_path")
    ):
        return True
    return bool(meta.get("question_session_id"))


def _pending_handoff(artifacts_dir: Path | None) -> bool:
    """Return whether a plan/question/monitor/gate/pipe handoff is pending."""
    if artifacts_dir is None:
        return False
    try:
        from sase.agent.pending_handoff import has_pending_handoff

        return bool(has_pending_handoff(str(artifacts_dir)))
    except Exception:
        return False


def _is_remote(done: Mapping[str, Any], meta: Mapping[str, Any]) -> bool:
    """Return whether the row was imported from another machine.

    ``source_machine`` is only written by the import path, so its bare
    presence marks a remote row the healer must never restart.
    """
    return bool(done.get("source_machine") or meta.get("source_machine"))


def assemble_done_row_input(
    *,
    artifacts_dir: Path,
    done: Mapping[str, Any],
    meta: Mapping[str, Any],
    managed_roots: tuple[ManagedRoot, ...],
    project: str,
    died_at: float | None,
    log_tail: str,
    journal_path: Path | None = None,
    enable_file_proof: bool = True,
    done_mtime: float | None = None,
) -> AssembledInput:
    """Assemble classifier inputs for one failed ``done.json`` row."""
    facts = agent_failure_facts_from_dict(done.get("failure_facts"))
    boot_identity = meta.get("code_identity")
    boot_identity_map = boot_identity if isinstance(boot_identity, Mapping) else None
    booted_at = meta.get("booted_at")
    finished_at = done.get("finished_at")
    finished: float | None = None
    if isinstance(finished_at, bool):
        finished = None
    elif isinstance(finished_at, (int, float)):
        finished = float(finished_at)
    error_text = _text(done.get("error"))
    traceback_text = _text(done.get("traceback"))
    lifecycle = (
        facts.lifecycle_phase
        if facts is not None and facts.lifecycle_phase
        else _text(meta.get("lifecycle_phase")) or None
    )
    workspace_dir = _text(done.get("workspace_dir")) or _text(meta.get("workspace_dir"))
    outcome = done.get("outcome")
    context = AutoRestartContextWire(
        managed_roots=_managed_root_wires(managed_roots),
        workspace_dir=workspace_dir or None,
        outcome=str(outcome) if outcome is not None else None,
        kill_source=None,
        lifecycle_phase=lifecycle,
        has_pending_question=_pending_question(artifacts_dir, meta),
        has_pending_handoff=_pending_handoff(artifacts_dir),
        is_remote=_is_remote(done, meta),
        error_text=error_text,
        traceback_text=traceback_text,
        log_tail=log_tail,
    )
    if done_mtime is None:
        try:
            done_mtime = artifacts_dir.stat().st_mtime
        except OSError:
            done_mtime = None
    witnesses = collect_witnesses(
        WitnessInputs(
            facts=dict(done["failure_facts"])
            if isinstance(done.get("failure_facts"), dict)
            else None,
            boot_identity=boot_identity_map,
            booted_at=booted_at if isinstance(booted_at, str) else None,
            finished_at=finished,
            artifacts_timestamp=artifacts_dir.name,
            done_mtime=done_mtime,
            error_text=error_text,
            traceback_text=traceback_text,
            log_tail=log_tail,
            managed_roots=managed_roots,
            journal_path=journal_path,
            enable_file_proof=enable_file_proof,
        )
    )
    name = _text(done.get("name")) or _text(meta.get("name")) or artifacts_dir.name
    return AssembledInput(
        name=name,
        project=project,
        artifacts_dir=str(artifacts_dir),
        died_at=died_at,
        facts=facts,
        context=context,
        witnesses=witnesses,
        lifecycle_phase=lifecycle,
    )


def assemble_bundle_input(
    *,
    bundle: Mapping[str, Any],
    managed_roots: tuple[ManagedRoot, ...],
    project: str,
    died_at: float | None,
    log_tail: str,
    journal_path: Path | None = None,
    enable_file_proof: bool = True,
    done_mtime: float | None = None,
) -> AssembledInput:
    """Assemble classifier inputs for one dismissed bundle.

    The artifact directory is usually wiped, so there are no marker
    files to consult: pending-question/handoff markers read ``False``,
    and the boot snapshot is unknown (legacy path). The W2 window runs
    from the artifact timestamp to the bundle file's mtime (the
    dismissal bound, which postdates the failure).
    """
    error_text = _text(bundle.get("error_message"))
    traceback_text = _text(bundle.get("error_traceback"))
    artifacts_dir = _text(bundle.get("artifacts_dir")) or None
    context = AutoRestartContextWire(
        managed_roots=_managed_root_wires(managed_roots),
        workspace_dir=_text(bundle.get("workspace_dir")) or None,
        outcome=None,
        kill_source=None,
        lifecycle_phase=None,
        has_pending_question=False,
        has_pending_handoff=False,
        is_remote=False,
        error_text=error_text,
        traceback_text=traceback_text,
        log_tail=log_tail,
    )
    witnesses = collect_witnesses(
        WitnessInputs(
            facts=None,
            boot_identity=None,
            booted_at=None,
            finished_at=None,
            artifacts_timestamp=(Path(artifacts_dir).name if artifacts_dir else None),
            done_mtime=done_mtime,
            error_text=error_text,
            traceback_text=traceback_text,
            log_tail=log_tail,
            managed_roots=managed_roots,
            journal_path=journal_path,
            enable_file_proof=enable_file_proof,
        )
    )
    name = _text(bundle.get("agent_name")) or "unknown"
    return AssembledInput(
        name=name,
        project=project,
        artifacts_dir=artifacts_dir,
        died_at=died_at,
        facts=None,
        context=context,
        witnesses=witnesses,
        lifecycle_phase=None,
    )


__all__ = [
    "LOG_TAIL_LINES",
    "AssembledInput",
    "assemble_bundle_input",
    "assemble_done_row_input",
    "find_runner_log",
    "read_json_dict",
    "read_log_tail",
]
