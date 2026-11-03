"""Classify one instruction-readout artifact dir via the Rust core.

Python gathers staged records/receipts, host lifecycle facts, declaration
evidence, prepared-intent evidence, and bounded legacy tail strings. Class
precedence belongs to the Rust core through
``sase.core.instruction_readout``; this module never reimplements it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase.core.instruction_readout import classify_instruction_readout
from sase.instructions._readout_shared import CLASSES, TAIL_SCAN_BYTES, read_json

# Only ``propose`` stages a handoff: ``validate`` and ``decide`` never leave
# the turn, so a mere plan validation must not establish a handoff.
_PLAN_MARKERS = ("sase plan propose",)
_MONITOR_MARKER = "sase monitor start"
_PREPARE_MARKER = "sase final prepare"
_OTHER_MARKERS = ("sase pipe", "sase questions", "sase handoff")

_STAGED_RECORD_FILENAME = ".sase_handoff_staged.json"
_STAGED_RECEIPT_FILENAME = ".sase_handoff_adopted.json"


def _tail_text(path: Path, *, max_bytes: int = TAIL_SCAN_BYTES) -> str:
    try:
        size = path.stat().st_size
        with open(path, "rb") as stream:
            if size > max_bytes:
                stream.seek(size - max_bytes)
            raw = stream.read()
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace")


def _has_accepted_submission(artifact_dir: Path) -> bool:
    payload = read_json(artifact_dir / "final_submission.json")
    return bool(payload)


def _is_not_required(artifact_dir: Path) -> bool:
    payload = read_json(artifact_dir / "final_context.json")
    if not payload:
        return False
    if payload.get("submission_required") is False:
        return True
    selected = payload.get("selected_instances")
    if isinstance(selected, list) and selected:
        flags = [
            item.get("submission_required")
            for item in selected
            if isinstance(item, dict)
        ]
        if flags and all(flag is False for flag in flags):
            return True
    context = payload.get("context")
    if isinstance(context, dict):
        reqs = context.get("requirements")
        if isinstance(reqs, list) and reqs:
            flags = [
                item.get("submission_required")
                for item in reqs
                if isinstance(item, dict)
            ]
            if flags and all(flag is False for flag in flags):
                return True
    return False


def _find_real_marker(tail: str, marker: str) -> int:
    """Return the index of a real *marker* invocation (not ``-h``), or -1."""
    idx = tail.find(marker)
    while idx != -1:
        following = tail[idx + len(marker) : idx + len(marker) + 16]
        if following.startswith(" -h") or following.startswith(" --help"):
            idx = tail.find(marker, idx + 1)
            continue
        return idx
    return -1


def _has_real_prepare(tail: str) -> int:
    """Return the index of a real ``sase final prepare`` (not ``-h``), or -1."""
    return _find_real_marker(tail, _PREPARE_MARKER)


def _has_handoff_phase(meta: dict[str, Any]) -> bool:
    phases = meta.get("lifecycle_phases")
    if not isinstance(phases, list):
        return False
    return any(
        isinstance(entry, dict) and entry.get("phase") == "handoff" for entry in phases
    )


def _has_prepared_completion(artifact_dir: Path) -> bool:
    payload = read_json(
        artifact_dir / "continuation" / "completion_intents" / "index.json"
    )
    intents = payload.get("intents")
    return isinstance(intents, dict) and bool(intents)


def _declaration_evidence(artifact_dir: Path) -> str:
    """Return the Rust declaration wire value for one artifact dir."""
    if _has_accepted_submission(artifact_dir):
        return "accepted"
    if _is_not_required(artifact_dir):
        return "not_required"
    return "missing"


def _read_staged_record(artifact_dir: Path) -> dict[str, Any] | None:
    """Return the staged-handoff record dict, or ``None`` when absent/corrupt."""
    payload = read_json(artifact_dir / _STAGED_RECORD_FILENAME)
    return payload or None


def _read_staged_receipt(artifact_dir: Path) -> dict[str, Any] | None:
    """Return the staged adoption receipt dict, or ``None`` when absent/corrupt."""
    payload = read_json(artifact_dir / _STAGED_RECEIPT_FILENAME)
    return payload or None


def _is_staged_evidence(
    meta: dict[str, Any],
    record: dict[str, Any] | None,
    receipt: dict[str, Any] | None,
) -> bool:
    """Return True when durable facts show the handoff staged (not legacy).

    A staged record, an adoption receipt, or a ``staged`` handoff protocol
    marks new-protocol evidence. Historical ``killed``/unspecified evidence
    stays legacy so old runs keep their archived scoring.
    """
    if record is not None or receipt is not None:
        return True
    return meta.get("handoff_protocol") == "staged"


def _staged_prepared_ref(payload: Any) -> str | None:
    """Return the prepared-intent ref in a staged monitor payload, if any."""
    if not isinstance(payload, dict):
        return None
    raw = payload.get("prepared_intent_ref")
    if isinstance(raw, str) and raw.strip():
        return raw
    resources = payload.get("resources")
    if isinstance(resources, dict):
        nested = resources.get("prepared_intent_ref")
        if isinstance(nested, str) and nested.strip():
            return nested
    return None


def _staged_kind_wire(artifact_dir: Path, record: dict[str, Any] | None) -> str | None:
    """Map a staged record to the Rust handoff wire value, or ``None``."""
    if not record:
        return None
    kind = record.get("kind")
    if kind == "plan":
        return "plan"
    if kind == "monitor":
        # Prepared-monitor evidence uses the validated context/intent
        # contract, not merely a tool-call substring.
        if _staged_prepared_ref(record.get("payload")) and _has_prepared_completion(
            artifact_dir
        ):
            return "monitor_prepared"
        return "monitor_plain"
    if kind in ("questions", "pipe", "gate"):
        return "other"
    return None


def _host_handoff_wire(
    artifact_dir: Path,
    meta: dict[str, Any],
    tail_text: Callable[[], str],
) -> str | None:
    """Classify an adopted handoff from host records, or ``None``.

    ``None`` means there is no host-evidence handoff (no ``handoff``
    lifecycle phase). Callers skip this step when
    ``handoff_aborted.json`` exists, then fall through to the tool-call
    tail scan used for older runs.
    """
    if not _has_handoff_phase(meta):
        return None
    if (artifact_dir / "plan_path.json").is_file():
        return "plan"
    if meta.get("monitor_id") or meta.get("monitor_member_agent_name"):
        prepared = _has_prepared_completion(artifact_dir)
        if prepared or _has_real_prepare(tail_text()) != -1:
            return "monitor_prepared"
        return "monitor_plain"
    return "other"


def _legacy_tail_wire(text: str) -> str | None:
    """Classify historical runs from bounded tool-call evidence, or ``None``.

    Command mentions, help invocations, and mere plan validations never
    establish a handoff: only real staging commands count.
    """
    if any(_find_real_marker(text, marker) != -1 for marker in _PLAN_MARKERS):
        return "plan"
    monitor_at = _find_real_marker(text, _MONITOR_MARKER)
    if monitor_at != -1:
        prepare_at = _has_real_prepare(text)
        if prepare_at != -1 and prepare_at < monitor_at:
            return "monitor_prepared"
        return "monitor_plain"
    for marker in _OTHER_MARKERS:
        if _find_real_marker(text, marker) != -1:
            return "other"
    return None


def _handoff_evidence(
    artifact_dir: Path,
    meta: dict[str, Any],
    tail_text: Callable[[], str],
) -> tuple[str | None, bool, dict[str, Any] | None]:
    """Return ``(handoff_wire, is_staged, staged_record)`` for one run.

    Durable host facts win over tool-call strings: the staged record comes
    first, then adopted lifecycle facts, then the bounded legacy tail scan.
    """
    record = _read_staged_record(artifact_dir)
    receipt = _read_staged_receipt(artifact_dir)
    if _is_staged_evidence(meta, record, receipt):
        wire = _staged_kind_wire(artifact_dir, record)
        if wire is None:
            wire = _host_handoff_wire(artifact_dir, meta, tail_text)
        if wire is None:
            wire = _legacy_tail_wire(tail_text())
        return wire, True, record
    wire = _host_handoff_wire(artifact_dir, meta, tail_text)
    if wire is None:
        wire = _legacy_tail_wire(tail_text())
    return wire, False, record


def _final_context_requires_submission(artifact_dir: Path) -> bool:
    """Return True when final_context shows a required declaration."""
    payload = read_json(artifact_dir / "final_context.json")
    if not payload:
        return False
    if payload.get("submission_required") is True:
        return True
    selected = payload.get("selected_instances")
    if isinstance(selected, list):
        for item in selected:
            if isinstance(item, dict) and item.get("submission_required") is True:
                return True
    context = payload.get("context")
    if isinstance(context, dict):
        requirements = context.get("requirements")
        if isinstance(requirements, list):
            for item in requirements:
                if isinstance(item, dict) and item.get("submission_required") is True:
                    return True
    return False


def _has_dirty_obligations(artifact_dir: Path, record: dict[str, Any] | None) -> bool:
    """Return True when staged or finalizer facts show dirty obligations."""
    if record is not None:
        dirty = record.get("dirty_obligations_at_stage")
        if isinstance(dirty, list) and any(
            isinstance(entry, str) and entry.strip() for entry in dirty
        ):
            return True
    # An absent/corrupt final context is not proof that no declaration was
    # required; only an explicit not-required context clears the obligations.
    return _final_context_requires_submission(artifact_dir)


def _classify_via_core(
    handoff: str | None, declaration: str, has_dirty_obligations: bool
) -> str:
    """Score gathered evidence with the Rust readout policy."""
    result = classify_instruction_readout(
        {
            "handoff": handoff,
            "declaration": declaration,
            "has_dirty_obligations": bool(has_dirty_obligations),
        }
    )
    if result not in CLASSES:
        raise ValueError(f"unknown readout class from Rust core: {result!r}")
    return result


def classify_artifact_dir(
    artifact_dir: Path, meta: dict[str, Any] | None = None
) -> str:
    """Classify one artifact dir, delegating precedence to the Rust core."""
    if meta is None:
        meta = read_json(artifact_dir / "agent_meta.json")
    declaration = _declaration_evidence(artifact_dir)
    if (artifact_dir / "handoff_aborted.json").is_file():
        # An aborted handoff is never a handoff; the declaration still counts.
        return _classify_via_core(None, declaration, False)
    tail: str | None = None

    def tail_text() -> str:
        nonlocal tail
        if tail is None:
            tail = _tail_text(artifact_dir / "tool_calls.jsonl")
        return tail

    handoff, staged, record = _handoff_evidence(artifact_dir, meta, tail_text)
    dirty = _has_dirty_obligations(artifact_dir, record) if staged else False
    return _classify_via_core(handoff, declaration, dirty)


__all__ = ["classify_artifact_dir"]
