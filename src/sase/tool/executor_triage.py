"""Bounded failure-triage settlement for foreground ToolRun execution.

Extracted from ``sase.tool.executor`` along the existing seam: everything
after the recorded body settles. Persists triage evidence without changing
the child outcome and always fails open. Imported back into
``sase.tool.executor`` so existing imports keep working.
"""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import queue
import threading
import time
from typing import TYPE_CHECKING, Any

from sase.core.tool_run import (
    tool_run_triage_record,
    tool_run_triage_settle,
    tool_run_triage_show,
)
from sase.tool.stage_protocol import StageIngestor
from sase.tool.triage_inputs import (
    gather_ancestry,
    gather_flake_baseline,
    gather_owner_candidates,
    gather_selection_records,
    triage_knobs,
)

if TYPE_CHECKING:
    from sase.tool.executor import RecordedRunContext

_TRIAGE_BUDGET_SECONDS = 5.0
_TRIAGE_GATHERER_SECONDS = 1.0
_TRIAGE_OUTPUT_BYTES = 256 * 1024

_DECISION_RECORD_MIN_SECONDS = 0.3
_DIAGNOSTIC_RECORD_MIN_SECONDS = 0.2

_EXTRACTION_STATUSES = frozenset(
    {"parsed", "generic", "output_missing", "output_truncated"}
)


def settle_failure_triage(
    *,
    ctx: RecordedRunContext,
    fingerprint_before: dict[str, Any] | None,
    ingestor: StageIngestor | None,
    state: str,
) -> dict[str, Any] | None:
    """Persist bounded failure triage without changing the child outcome.

    This sits after ``tool_run_finish`` so foreground and adopted workers use
    the same settled ledger row.  It deliberately returns diagnostics for the
    optional footer rather than raising into the process-result path.
    """

    if ctx.resolved.adhoc or not ctx.resolved.tool_name:
        return None
    deadline = time.monotonic() + _TRIAGE_BUDGET_SECONDS
    root = Path(ctx.resolved.cwd or os.getcwd())
    diagnostics: list[str] = []
    stages = _failed_stage_inputs(ingestor, ctx.events_path, diagnostics)
    run_output: str | None = None
    run_output_truncated = False
    if state != "succeeded" and not stages:
        run_output, run_output_truncated = _output_of_record(ctx, diagnostics)
    base = _fingerprint_base_head(fingerprint_before)
    project = ctx.resolved.resolved_project_identity()
    extra_args = ""
    if isinstance(fingerprint_before, dict):
        extra_args = str(fingerprint_before.get("extra_args_digest") or "")
    ancestry, ancestry_notes = (
        _gather_triage("ancestry", lambda: gather_ancestry(root, base), deadline)
        if base
        else ([], ["triage ancestry unavailable: base head missing"])
    )
    flake_baseline, baseline_notes = (
        _gather_triage(
            "flake baseline", lambda: gather_flake_baseline(root, base), deadline
        )
        if base
        else ([], ["triage flake baseline unavailable: base head missing"])
    )
    selection, selection_notes = _gather_triage(
        "selection records",
        lambda: gather_selection_records(
            project,
            project=project,
            tool=ctx.resolved.tool_name,
            extra_args_digest=extra_args,
            project_root=root,
        ),
        deadline,
    )
    owners, owner_notes = _gather_triage(
        "owner candidates", lambda: gather_owner_candidates(root), deadline
    )
    diagnostics.extend(
        str(note)
        for notes in (ancestry_notes, baseline_notes, selection_notes, owner_notes)
        for note in notes
    )
    if time.monotonic() >= deadline:
        diagnostics.append("triage budget exceeded")
        persist_notes = _persist_triage_diagnostics(ctx, diagnostics, deadline)
        return {
            "triaged": False,
            "diagnostics": [*diagnostics, *persist_notes],
        }
    request = {
        "run_id": ctx.run_id,
        "stages": stages,
        "run_output": run_output,
        "run_output_truncated": run_output_truncated,
        "project_root": str(root),
        "workspace_roots": [str(root)],
        "ancestry": ancestry,
        "flake_baseline": flake_baseline,
        "selection_records": selection,
        "owner_candidates": owners,
        "knobs": triage_knobs(),
        "continuation_mode": ctx.continuation_mode,
        "recipe_finished_ts": _recipe_finished_ts(ingestor),
        "now_ts": int(time.time()),
    }
    try:
        settled = tool_run_triage_settle(
            request,
            busy_timeout_ms=max(1, int((deadline - time.monotonic()) * 1000)),
        )
        if isinstance(settled, dict) and settled.get("refused"):
            diagnostics.append(f"triage settle refused: {settled['refused']}")
        persist_notes = _persist_triage_diagnostics(ctx, diagnostics, deadline)
        diagnostics.extend(persist_notes)
        # The settle response intentionally omits stage facts. Read back the
        # stored shape so the footer and explicit show surface share it.
        triage = tool_run_triage_show(
            {"run_id": ctx.run_id},
            busy_timeout_ms=max(1, int((deadline - time.monotonic()) * 1000)),
        )
        triage, record_notes = _persist_continuation_decisions(
            ctx, ingestor, triage, deadline
        )
        triage["diagnostics"] = [
            *_string_items(triage.get("diagnostics")),
            *diagnostics,
            *record_notes,
        ]
        return triage
    except Exception as exc:  # noqa: BLE001 - triage must always fail open.
        diagnostics.append(str(exc))
        persist_notes = _persist_triage_diagnostics(ctx, diagnostics, deadline)
        return {
            "triaged": False,
            "diagnostics": [*diagnostics, *persist_notes],
        }


_DECISION_RECORD_MIN_SECONDS = 0.3
_DIAGNOSTIC_RECORD_MIN_SECONDS = 0.2


def _persist_triage_diagnostics(
    ctx: RecordedRunContext, diagnostics: list[str], deadline: float
) -> list[str]:
    """Store gatherer and settle diagnostics on the run's triage facts.

    Fail-open and inside the remaining settle budget.  An empty list is a
    no-op.  The core unions diagnostics onto the existing run-facts row.
    """

    notes: list[str] = []
    unique = [item for item in dict.fromkeys(diagnostics) if item]
    if not unique:
        return notes
    remaining = deadline - time.monotonic()
    if remaining <= _DIAGNOSTIC_RECORD_MIN_SECONDS:
        notes.append("triage diagnostics record skipped: budget exhausted")
        return notes
    try:
        tool_run_triage_record(
            {
                "run_id": ctx.run_id,
                "stages": [],
                "run_facts": {
                    "continuation_mode": ctx.continuation_mode,
                    "recipe_finished_ts": None,
                    "first_continued_exit_code": None,
                    "continuation_extra_ms": None,
                    "repeat_of_run_id": None,
                    "triaged_ts": None,
                    "diagnostics": unique,
                },
                "now_ts": int(time.time()),
            },
            busy_timeout_ms=max(1, int(remaining * 1000)),
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics must fail open.
        notes.append(f"triage diagnostics record failed: {exc}")
    return notes


_EXTRACTION_STATUSES = frozenset(
    {"parsed", "generic", "output_missing", "output_truncated"}
)


def _continuation_decision_entries(
    ingestor: StageIngestor | None,
) -> list[dict[str, Any]]:
    """Project helper continuation records onto stored stage identities."""

    if ingestor is None:
        return []
    entries: list[dict[str, Any]] = []
    for record in ingestor.continuation_records:
        kind = str(record.get("kind") or "")
        if kind == "continued":
            decision = "continue"
        elif kind == "stopped":
            decision = "stop"
        else:
            continue
        stage_id = str(record.get("stage_id") or "")
        stage = ingestor.stages.get(stage_id) if stage_id else None
        stage_key = ""
        if isinstance(stage, dict):
            stage_key = str(stage.get("description") or "")
        if not stage_key:
            stage_key = str(record.get("description") or "")
        if not stage_id or not stage_key:
            continue
        elapsed = record.get("elapsed_ms")
        decided = record.get("decided_ts")
        entries.append(
            {
                "stage_id": stage_id,
                "stage_key": stage_key,
                "mode": str(record.get("mode") or ""),
                "decision": decision,
                "reason": str(record.get("reason") or ""),
                "elapsed_ms": elapsed if type(elapsed) is int else None,
                "decided_ts": decided if type(decided) is int else None,
            }
        )
    return entries


def _continuation_run_cost(
    records: list[dict[str, Any]],
) -> tuple[int | None, int | None]:
    """Return ``(first_continued_exit_code, extra_ms)`` for a run.

    The extra cost of continuing is the wall time from the first
    continued failure to the recipe finish marker, or to settlement
    when the finish marker is missing.
    """

    continued = [r for r in records if r.get("kind") == "continued"]
    if not continued:
        return None, None
    first_code: int | None = None
    first_ts: int | None = None
    first = continued[0]
    if type(first.get("exit_code")) is int:
        first_code = int(first["exit_code"])
    if type(first.get("decided_ts")) is int:
        first_ts = int(first["decided_ts"])
    finished = [r for r in records if r.get("kind") == "recipe_finished"]
    if finished:
        last = finished[-1]
        if type(last.get("first_continued_exit_code")) is int:
            first_code = int(last["first_continued_exit_code"])
        end = last.get("decided_ts")
        end_ts = int(end) if type(end) is int else int(time.time() * 1000)
    else:
        end_ts = int(time.time() * 1000)
    extra_ms = None if first_ts is None else max(0, end_ts - first_ts)
    return first_code, extra_ms


def _persist_continuation_decisions(
    ctx: RecordedRunContext,
    ingestor: StageIngestor | None,
    triage: dict[str, Any],
    deadline: float,
) -> tuple[dict[str, Any], list[str]]:
    """Persist helper continuation decisions and run cost facts.

    Settle stores items and labels but never sees the helper's
    ``continued``/``stopped`` records, so without this call a
    ``show -j`` stage would carry no decision and no continuation cost.
    Stored rows win on replay: an entry only fills a decision that is
    still NULL, and run facts only fill columns that are still NULL.
    """

    notes: list[str] = []
    if ingestor is None or not ctx.continuation_mode:
        return triage, notes
    entries = _continuation_decision_entries(ingestor)
    first_code, extra_ms = _continuation_run_cost(ingestor.continuation_records)
    if not entries and first_code is None and extra_ms is None:
        return triage, notes
    by_id: dict[str, dict[str, Any]] = {}
    by_key: dict[str, dict[str, Any]] = {}
    for stage in _dict_items(triage.get("stages")):
        stage_id = stage.get("stage_id")
        if isinstance(stage_id, str) and stage_id:
            by_id.setdefault(stage_id, stage)
        stage_key = stage.get("stage_key")
        if isinstance(stage_key, str) and stage_key:
            by_key.setdefault(stage_key, stage)
    stages: list[dict[str, Any]] = []
    for entry in entries:
        if entry["decided_ts"] is None:
            notes.append(
                f"triage decision unmatched: {entry['stage_key']} (missing timestamp)"
            )
            continue
        stored = by_id.get(entry["stage_id"]) or by_key.get(entry["stage_key"])
        if stored is None:
            notes.append(f"triage decision unmatched: {entry['stage_key']}")
            continue
        if stored.get("extraction_status") not in _EXTRACTION_STATUSES:
            notes.append(
                f"triage decision unmatched: {entry['stage_key']} "
                "(unknown extraction status)"
            )
            continue
        stages.append(
            {
                "stage_key": stored.get("stage_key"),
                "stage_id": stored.get("stage_id") or entry["stage_id"],
                "extraction_status": stored.get("extraction_status"),
                "output_path": stored.get("output_path"),
                "decision": {
                    "mode": entry["mode"] or ctx.continuation_mode,
                    "decision": entry["decision"],
                    "reason": entry["reason"],
                    "elapsed_ms": entry["elapsed_ms"],
                    "decided_ts": entry["decided_ts"],
                },
                "items": [],
            }
        )
    if not stages and first_code is None and extra_ms is None:
        return triage, notes
    remaining = deadline - time.monotonic()
    if remaining <= _DECISION_RECORD_MIN_SECONDS:
        notes.append("triage decision record skipped: budget exhausted")
        return triage, notes
    try:
        tool_run_triage_record(
            {
                "run_id": ctx.run_id,
                "stages": stages,
                "run_facts": {
                    "continuation_mode": ctx.continuation_mode,
                    "recipe_finished_ts": _recipe_finished_ts(ingestor),
                    "first_continued_exit_code": first_code,
                    "continuation_extra_ms": extra_ms,
                    "repeat_of_run_id": None,
                    "triaged_ts": None,
                    "diagnostics": [],
                },
                "now_ts": int(time.time()),
            },
            busy_timeout_ms=max(1, int(remaining * 1000)),
        )
    except Exception as exc:  # noqa: BLE001 - decisions must fail open.
        notes.append(f"triage decision record failed: {exc}")
        return triage, notes
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        notes.append("triage decision re-read skipped: budget exhausted")
        return triage, notes
    try:
        refreshed = tool_run_triage_show(
            {"run_id": ctx.run_id},
            busy_timeout_ms=max(1, int(remaining * 1000)),
        )
    except Exception as exc:  # noqa: BLE001 - the first read still stands.
        notes.append(f"triage decision re-read failed: {exc}")
        return triage, notes
    if not isinstance(refreshed, dict):
        notes.append("triage decision re-read failed: malformed envelope")
        return triage, notes
    return refreshed, notes


def _gather_triage(
    name: str, callback: Callable[[], tuple[Any, list[str]]], deadline: float
) -> tuple[Any, list[str]]:
    """Await one optional gatherer only within its slice of the total budget."""

    remaining = min(_TRIAGE_GATHERER_SECONDS, deadline - time.monotonic())
    if remaining <= 0:
        return [], [f"triage {name} skipped: budget exhausted"]
    result: queue.Queue[object] = queue.Queue(maxsize=1)

    def run() -> None:
        try:
            result.put(callback())
        except Exception as exc:  # noqa: BLE001 - gatherers are optional evidence.
            result.put(exc)

    thread = threading.Thread(target=run, daemon=True, name=f"sase-triage-{name}")
    thread.start()
    try:
        value = result.get(timeout=remaining)
    except queue.Empty:
        return [], [f"triage {name} timed out"]
    if isinstance(value, Exception):
        return [], [f"triage {name} failed: {value}"]
    if not isinstance(value, tuple) or len(value) != 2:
        return [], [f"triage {name} returned malformed evidence"]
    items, diagnostics = value
    return items, _string_items(diagnostics)


def _failed_stage_inputs(
    ingestor: StageIngestor | None,
    events_path: Path | None,
    diagnostics: list[str],
) -> list[dict[str, Any]]:
    if ingestor is None:
        return []
    inputs: list[dict[str, Any]] = []
    for stage_id, stage in ingestor.stages.items():
        if type(stage.get("exit_code")) is not int or int(stage["exit_code"]) == 0:
            continue
        metadata = ingestor.stage_outputs.get(stage_id) or {}
        output, missing = _read_stage_output(events_path, metadata.get("output_path"))
        if missing:
            diagnostics.append(
                f"triage stage output unavailable: {stage.get('description') or stage_id}"
            )
        inputs.append(
            {
                "stage_key": str(stage.get("description") or "*"),
                "stage_id": stage_id,
                "output": output,
                "truncated": bool(metadata.get("truncated")),
                "output_path": metadata.get("output_path"),
            }
        )
    return inputs


def _read_stage_output(
    events_path: Path | None, raw_path: object
) -> tuple[str | None, bool]:
    if events_path is None or not isinstance(raw_path, str) or not raw_path:
        return None, True
    try:
        root = events_path.parent.resolve()
        path = (root / raw_path).resolve()
        path.relative_to(root)
        data = path.read_bytes()
    except (OSError, ValueError):
        return None, True
    return data[-_TRIAGE_OUTPUT_BYTES:].decode("utf-8", "replace"), False


def _output_of_record(
    ctx: RecordedRunContext, diagnostics: list[str]
) -> tuple[str | None, bool]:
    chunks: list[bytes] = []
    for path in (ctx.stdout_path, ctx.stderr_path):
        if path is None:
            continue
        try:
            chunks.append(path.read_bytes())
        except OSError as exc:
            diagnostics.append(f"triage output of record unavailable: {exc}")
    if not chunks:
        return None, False
    joined = b"".join(chunks)
    return joined[-_TRIAGE_OUTPUT_BYTES:].decode("utf-8", "replace"), len(
        joined
    ) > _TRIAGE_OUTPUT_BYTES


def _fingerprint_base_head(fingerprint: dict[str, Any] | None) -> str:
    if not isinstance(fingerprint, dict):
        return ""
    for repo in _dict_items(fingerprint.get("repos")):
        head = repo.get("head")
        if isinstance(head, str) and head:
            return head
    return ""


def _recipe_finished_ts(ingestor: StageIngestor | None) -> int | None:
    if ingestor is None:
        return None
    for record in reversed(ingestor.continuation_records):
        if record.get("kind") == "recipe_finished":
            value = record.get("decided_ts")
            if type(value) is int:
                return value // 1000
    return None


def _dict_items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_items(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item)]


__all__ = [
    "settle_failure_triage",
]
