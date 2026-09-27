"""TUI-agnostic capped artifact collector for the finalizer node view.

Python supplies already-collected artifact text; the Rust
``finalizer::run_view`` projection owns every status decision. This module
never imports TUI code: the TUI-side :func:`node_run_targets` helper lives
in ``sase.ace.tui.models.finalizer_run_targets`` and adapts agent rows into
:class:`RunTarget` records.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.core.finalizer_run_view import RUN_VIEW_TAIL_LINES_DEFAULT
from sase.core.process_identity import process_identity_matches

#: Every JSON text input over this size is ``too_large`` and never parsed.
RUN_INPUT_MAX_BYTES = 4 * 1024 * 1024

#: Bytes kept for an active ``.live`` tail (plan section 3.4).
LIVE_TAIL_MAX_BYTES = 16 * 1024

#: Bytes kept for a failed op's stderr tail (plan section 3.4).
STDERR_TAIL_MAX_BYTES = 4 * 1024

#: Operation-record texts beyond this size are dropped (matches the
#: projection's ``OP_RECORD_MAX_BYTES`` ceiling).
OP_RECORD_TEXT_MAX_BYTES = 1024 * 1024

#: Step-file texts beyond this size are dropped (matches the projection's
#: ``STEPS_MAX_BYTES`` ceiling and the writer's stop-at-ceiling behavior).
STEPS_TEXT_MAX_BYTES = 64 * 1024

#: Upper bound for any single content scan. Terminal logs are capped at
#: 1 MiB per stream by the bounded runner and live sinks rotate at
#: 512 KiB, so compliant writers never approach this; it only bounds
#: non-compliant files.
_CONTENT_SCAN_MAX_BYTES = 2 * 1024 * 1024

#: Artifact-relative text inputs collected per run (plan section 3.4).
RUN_TEXT_FILES: tuple[tuple[str, str], ...] = (
    ("agent_meta", "agent_meta.json"),
    ("plan", "finalizer_plan.json"),
    ("authority_plan", "finalizer_plan.authority.json"),
    ("context", "final_context.json"),
    ("submission", "final_submission.json"),
    ("submission_attempts", "final_submission_attempts.jsonl"),
    ("journal", "finalizers/progress.jsonl"),
    ("result", "finalizer_result.json"),
)

#: Recovery files reported by presence (plan section 3.4).
RECOVERY_FILENAMES: tuple[str, ...] = (
    "final_declaration_recovery_evidence.md",
    "final_declaration_recovery_prompt.md",
    "final_declaration_recovery_response.md",
)

#: Per-instance artifact directory name.
FINALIZER_RUNS_DIRNAME = "finalizers"


@dataclass(frozen=True)
class RunnerIdentity:
    """Runner that executed the finalizer phase (journal ``runner`` fact)."""

    pid: int | None = None
    identity: str | None = None


def runner_identity_from_mapping(data: Any) -> RunnerIdentity | None:
    """Coerce a raw ``runner`` mapping tolerantly, or return None."""
    if not isinstance(data, dict):
        return None
    pid = data.get("pid")
    return RunnerIdentity(
        pid=pid if isinstance(pid, int) and not isinstance(pid, bool) else None,
        identity=data.get("identity")
        if isinstance(data.get("identity"), str)
        else None,
    )


@dataclass(frozen=True)
class RunTarget:
    """One concrete shell's finalizer execution to collect inputs for."""

    run_id: str
    artifacts_dir: str | None
    number: int = 0
    label: str = "agent turn"
    kind: str = "agent"
    turn_terminal: bool = False
    runner: RunnerIdentity | None = None


def _read_capped_text(path: Path, cap_bytes: int) -> tuple[str | None, int]:
    """Return ``(text, size)`` with ``text`` decoded UTF-8 with replacement.

    ``text`` is None when the file is missing, unreadable, empty, or
    larger than *cap_bytes*. ``size`` is the stat size, or 0 when unknown.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return None, 0
    if size > cap_bytes or size <= 0:
        return None, size
    try:
        with open(path, "rb") as handle:
            raw = handle.read(cap_bytes + 1)
    except OSError:
        return None, size
    if len(raw) > cap_bytes:
        return None, size
    if not raw:
        return None, size
    return raw.decode("utf-8", errors="replace"), size


def _text_input(path: Path, cap_bytes: int = RUN_INPUT_MAX_BYTES) -> dict[str, Any]:
    """Build one ``{text, size, too_large}`` wire input for *path*.

    ``too_large`` tracks only the projection ceiling (``RUN_INPUT_MAX_BYTES``):
    a file over its per-kind *cap_bytes* but under the ceiling degrades to no
    text without the flag, and the projection ignores the content either way.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return {"text": None, "size": 0, "too_large": False}
    if size > RUN_INPUT_MAX_BYTES:
        return {"text": None, "size": size, "too_large": True}
    if size > cap_bytes:
        return {"text": None, "size": size, "too_large": False}
    text, _ = _read_capped_text(path, cap_bytes)
    return {"text": text, "size": size, "too_large": False}


def _tail_text(path: Path, keep_bytes: int) -> str | None:
    """Return the last *keep_bytes* of *path* decoded, or None."""
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size <= 0:
        return None
    try:
        with open(path, "rb") as handle:
            if size > keep_bytes:
                handle.seek(size - keep_bytes)
            raw = handle.read(keep_bytes + 1)
    except OSError:
        return None
    if not raw:
        return None
    return raw.decode("utf-8", errors="replace")


def _line_count(path: Path) -> int | None:
    """Return the file's line count, or None when unreadable or oversized."""
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size <= 0 or size > _CONTENT_SCAN_MAX_BYTES:
        return 0 if size == 0 else None
    try:
        with open(path, "rb") as handle:
            raw = handle.read(_CONTENT_SCAN_MAX_BYTES + 1)
    except OSError:
        return None
    text = raw.decode("utf-8", errors="replace")
    return len(text.splitlines())


def _is_outcome_record(name: str) -> bool:
    return name.endswith(".outcome.json")


def _is_steps_file(name: str) -> bool:
    return name.endswith(".steps.jsonl")


def _is_diagnostics_file(name: str) -> bool:
    return name == "diagnostics.json" or name.endswith(".diagnostics.json")


def _is_live_file(name: str) -> bool:
    return name.endswith(".live") or name.endswith(".live.1")


def _is_log_file(name: str) -> bool:
    return name.endswith(".stdout") or name.endswith(".stderr")


def _collect_instance_file(path: Path) -> dict[str, Any]:
    """Build one ``{name, size, mtime_ns, ...}`` file entry (plan 3.4).

    Operation records, steps and diagnostics carry ``text``; logs carry
    ``size``/``line_count``; ``.live`` files carry a capped ``tail``; every
    stderr file additionally carries a capped ``tail`` so failed ops keep
    their failure-reason fallback. Anything else is a bare listing.
    """
    try:
        stat = path.stat()
    except OSError:
        return {"name": path.name, "size": 0}
    entry: dict[str, Any] = {
        "name": path.name,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    name = path.name
    if _is_outcome_record(name) or _is_diagnostics_file(name):
        entry["text"] = _text_input(path, OP_RECORD_TEXT_MAX_BYTES)
    elif _is_steps_file(name):
        entry["text"] = _text_input(path, STEPS_TEXT_MAX_BYTES)
    elif _is_live_file(name):
        tail = _tail_text(path, LIVE_TAIL_MAX_BYTES)
        if tail is not None:
            entry["tail"] = tail
        line_count = _line_count(path)
        if line_count is not None:
            entry["line_count"] = line_count
    elif _is_log_file(name):
        line_count = _line_count(path)
        if line_count is not None:
            entry["line_count"] = line_count
        if name.endswith(".stderr"):
            tail = _tail_text(path, STDERR_TAIL_MAX_BYTES)
            if tail is not None:
                entry["tail"] = tail
    return entry


def _plan_text_input(path: Path) -> dict[str, Any]:
    """Build the ``plan`` wire input, unwrapping the sealed envelope.

    The sealed ``finalizer_plan.json`` wraps the strict
    ``FinalizerPlanWire`` under its ``"plan"`` key alongside host metadata
    (``raw_operations``, ``diagnostics``) the projection's strict decoder
    rejects. Only the inner plan is forwarded, re-serialized without
    semantic change (the projection re-canonicalizes for its digest
    comparison). A missing inner plan forwards the raw text so the
    projection still reports the precise invalid-plan reason.
    """
    raw = _text_input(path)
    text = raw.get("text")
    if not isinstance(text, str) or not text:
        return raw
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return raw
    if not isinstance(payload, dict):
        return raw
    inner = payload.get("plan")
    if not isinstance(inner, dict):
        return raw
    try:
        return {"text": json.dumps(inner), "size": raw["size"], "too_large": False}
    except (TypeError, ValueError):
        return raw


def _collect_instances(root: Path) -> list[dict[str, Any]]:
    """List ``finalizers/<id>/`` instance inputs for one artifacts dir."""
    runs_dir = root / FINALIZER_RUNS_DIRNAME
    try:
        children = sorted(runs_dir.iterdir(), key=lambda item: item.name)
    except OSError:
        return []
    instances: list[dict[str, Any]] = []
    for child in children:
        if not child.is_dir():
            continue
        try:
            files = sorted(
                (item for item in child.iterdir() if item.is_file()),
                key=lambda item: item.name,
            )
        except OSError:
            files = []
        instances.append(
            {
                "instance_id": child.name,
                "files": [_collect_instance_file(item) for item in files],
            }
        )
    return instances


def _collect_recovery_files(root: Path) -> list[str]:
    """Return the recovery evidence/prompt/response names present on disk."""
    present: list[str] = []
    for name in RECOVERY_FILENAMES:
        try:
            if (root / name).is_file():
                present.append(name)
        except OSError:
            continue
    return present


def _journal_runner(journal_text: str | None) -> RunnerIdentity | None:
    """Return the last segment's ``phase_started`` runner, if parseable."""
    if not journal_text:
        return None
    runner: RunnerIdentity | None = None
    for line in journal_text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        if record.get("event") == "phase_started":
            runner = runner_identity_from_mapping(record.get("runner"))
        elif record.get("event") == "phase_skipped":
            runner = None
    return runner


def _runner_live(runner: RunnerIdentity | None) -> bool | None:
    """Return whether *runner* still matches this boot, or None if unknown."""
    if runner is None or runner.pid is None:
        return None
    try:
        return bool(process_identity_matches(runner.pid, runner.identity))
    except Exception:
        return None


def collect_run_input(target: RunTarget) -> dict[str, Any]:
    """Collect one run's projection inputs with capped reads (plan 3.4)."""
    run: dict[str, Any] = {
        "run_id": target.run_id,
        "number": target.number,
        "label": target.label,
        "kind": target.kind if target.kind in ("agent", "monitor") else "agent",
        "turn_terminal": bool(target.turn_terminal),
        "instances": [],
        "recovery_files": [],
    }
    if not target.artifacts_dir:
        for key, _ in RUN_TEXT_FILES:
            run[key] = {"text": None, "size": 0, "too_large": False}
        return run
    root = Path(target.artifacts_dir)
    texts: dict[str, dict[str, Any]] = {}
    for key, filename in RUN_TEXT_FILES:
        if key == "plan":
            entry = _plan_text_input(root / filename)
        else:
            entry = _text_input(root / filename)
        texts[key] = entry
        run[key] = entry
    run["instances"] = _collect_instances(root)
    run["recovery_files"] = _collect_recovery_files(root)
    runner = target.runner
    if runner is None:
        runner = _journal_runner(texts["journal"].get("text"))
    runner_live = _runner_live(runner)
    if runner_live is not None:
        run["runner_live"] = runner_live
    return run


def _stat_signature_lines(root: Path) -> list[str]:
    """Return stat-only signature lines for one artifacts dir (no reads)."""
    lines: list[str] = []
    candidates: list[Path] = [root / filename for _, filename in RUN_TEXT_FILES]
    candidates.extend(root / name for name in RECOVERY_FILENAMES)
    runs_dir = root / FINALIZER_RUNS_DIRNAME
    try:
        children = sorted(runs_dir.iterdir(), key=lambda item: item.name)
    except OSError:
        children = []
    for child in children:
        if child.is_dir():
            try:
                candidates.extend(
                    sorted(
                        (item for item in child.iterdir() if item.is_file()),
                        key=lambda item: item.name,
                    )
                )
            except OSError:
                continue
        else:
            candidates.append(child)
    for path in candidates:
        try:
            stat = path.stat()
        except OSError:
            continue
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = path.name
        lines.append(f"{rel}\0{stat.st_size}\0{stat.st_mtime_ns}")
    return lines


def run_inputs_signature(targets: tuple[RunTarget, ...] | list[RunTarget]) -> str:
    """Return a stat-only signature over every target's inputs.

    Only ``stat`` calls run here, never content reads, so the FINAL deck
    loader can skip re-projection when nothing changed.
    """
    digest = hashlib.sha256()
    for target in targets:
        header = (
            f"{target.run_id}\0{target.artifacts_dir or ''}\0"
            f"{target.number}\0{target.kind}\0{int(bool(target.turn_terminal))}"
        )
        digest.update(header.encode("utf-8"))
        if not target.artifacts_dir:
            continue
        for line in _stat_signature_lines(Path(target.artifacts_dir)):
            digest.update(line.encode("utf-8"))
            digest.update(b"\n")
    return digest.hexdigest()


def build_node_request(
    targets: tuple[RunTarget, ...] | list[RunTarget],
    tail_lines: int = RUN_VIEW_TAIL_LINES_DEFAULT,
) -> dict[str, Any]:
    """Build one node-view request from collected run inputs."""
    return {
        "schema_version": 1,
        "runs": [collect_run_input(target) for target in targets],
        "tail_lines": tail_lines,
    }


__all__ = [
    "FINALIZER_RUNS_DIRNAME",
    "LIVE_TAIL_MAX_BYTES",
    "OP_RECORD_TEXT_MAX_BYTES",
    "RECOVERY_FILENAMES",
    "RUN_INPUT_MAX_BYTES",
    "RUN_TEXT_FILES",
    "STEPS_TEXT_MAX_BYTES",
    "STDERR_TAIL_MAX_BYTES",
    "RunTarget",
    "RunnerIdentity",
    "build_node_request",
    "collect_run_input",
    "run_inputs_signature",
    "runner_identity_from_mapping",
]
