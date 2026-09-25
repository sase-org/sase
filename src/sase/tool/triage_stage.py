"""Hidden mid-run stage triage for known-gated continuation.

``sase tool _triage-stage`` answers one question for a failed ``run_silent``
stage while its recipe is still running: is every extracted failure item
already KNOWN or FLAKY? Only an explicit ``continue`` answer lets the
recipe proceed; every other outcome — including a crash of this verb —
is fail-fast by construction in the ``run_silent`` helper.

The verb gathers the same bounded evidence the settle path uses, minus
bead candidates (possible owners are attached once, at settle), and
persists the stage's items and labels through ``tool_run_triage_stage``
so the later settle reuses them instead of recomputing them.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from sase.core.tool_run import tool_run_show, tool_run_triage_stage
from sase.tool.triage_inputs import (
    gather_ancestry,
    gather_flake_baseline,
    gather_selection_records,
    triage_knobs,
)

_CONTINUE_CLASSES = frozenset({"known", "flaky"})
_CLASS_KEYS = ("new", "known", "flaky", "unknown")
_OUTPUT_BYTES = 256 * 1024
# A soft per-verb evidence deadline. Missing inputs only remove KNOWN or
# FLAKY evidence, never manufacture it, so skipping a slow gatherer stays
# fail-open; the helper's hard timeout is the outer bound.
_GATHER_SOFT_SECONDS = 8.0


def stage_decision(items: object) -> tuple[str, str, dict[str, int]]:
    """Reduce stored stage items to a ``(decision, reason, counts)`` triple.

    ``continue`` requires at least one item with every item KNOWN or
    FLAKY. Anything else — including an empty or unreadable item list —
    is ``stop``.
    """

    counts = dict.fromkeys(_CLASS_KEYS, 0)
    entries = list(items) if isinstance(items, (list, tuple)) else []
    if not entries:
        return "stop", "no_items", counts
    classes: list[str] = []
    for entry in entries:
        label = entry.get("label") if isinstance(entry, dict) else None
        class_name = str(label.get("class") or "") if isinstance(label, dict) else ""
        normalized = (
            class_name
            if class_name in _CONTINUE_CLASSES
            else ("new" if class_name == "new" else "unknown")
        )
        counts[normalized] += 1
        classes.append(class_name)
    if all(name in _CONTINUE_CLASSES for name in classes):
        return "continue", "all_known_or_flaky", counts
    if any(name == "new" for name in classes):
        return "stop", "new_item", counts
    return "stop", "unknown_item", counts


def _base_head(fingerprint: object) -> str:
    if not isinstance(fingerprint, dict):
        return ""
    repos = fingerprint.get("repos")
    if not isinstance(repos, (list, tuple)):
        return ""
    for repo in repos:
        if not isinstance(repo, dict):
            continue
        head = repo.get("head")
        if isinstance(head, str) and head:
            return head
    return ""


def _bounded_output(path: Path) -> tuple[str | None, bool]:
    try:
        data = path.read_bytes()
    except OSError:
        return None, False
    if len(data) <= _OUTPUT_BYTES:
        return data.decode("utf-8", "replace"), False
    return data[-_OUTPUT_BYTES:].decode("utf-8", "replace"), True


def _output_path_for(output: Path, events_path: str) -> str | None:
    """Return the events-relative output path, or None when not relocatable.

    The store must never hold an absolute checkout path, so an output
    outside the run's events directory keeps no output path at all.
    """

    try:
        root = Path(events_path).parent.resolve()
        return output.resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return None


def _gather_stage_inputs(
    root: Path, base: str, project: str, tool: str, extra_args: str
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Gather ancestry, baseline, and witnesses inside one soft deadline."""

    deadline = time.monotonic() + _GATHER_SOFT_SECONDS

    def _remaining() -> bool:
        return time.monotonic() < deadline

    ancestry: list[str] = []
    if base and _remaining():
        ancestry, _ = gather_ancestry(root, base)
    baseline: list[dict[str, Any]] = []
    if base and _remaining():
        baseline, _ = gather_flake_baseline(root, base)
    selection: list[dict[str, Any]] = []
    if _remaining():
        selection, _ = gather_selection_records(
            project,
            project=project,
            tool=tool,
            extra_args_digest=extra_args,
        )
    return ancestry, baseline, selection


def execute_triage_stage(
    run_id: str,
    *,
    stage_id: str,
    description: str,
    output: str | None,
) -> int:
    """Classify one failed stage and print one JSON decision line.

    Exits 0 only for ``continue``; every stop or refusal exits 1 and
    every usage error exits 2. Standard output carries exactly one JSON
    line so the ``run_silent`` helper can parse it without ambiguity.
    """

    run_id = run_id.strip()
    stage_id = stage_id.strip()
    description = description.strip()
    if not run_id or not stage_id or not description:
        print(
            "Usage: sase tool _triage-stage RUN "
            "--stage-id ID --description TEXT [--output PATH]",
            file=sys.stderr,
        )
        return 2
    try:
        shown = tool_run_show(run_id)
    except Exception as exc:  # noqa: BLE001 - an unreadable store stops.
        _emit("stop", "helper_error", {})
        print(f"sase tool _triage-stage: cannot load run ({exc})", file=sys.stderr)
        return 1
    run = shown.get("run") if isinstance(shown, dict) else None
    if not isinstance(run, dict):
        _emit("stop", "helper_error", {})
        print(f"sase tool _triage-stage: run {run_id} was not found", file=sys.stderr)
        return 1
    fingerprint = run.get("fingerprint_before")
    base = _base_head(fingerprint)
    extra_args = ""
    if isinstance(fingerprint, dict):
        extra_args = str(fingerprint.get("extra_args_digest") or "")
    project = str(run.get("project") or "")
    tool = str(run.get("tool_name") or "")
    root = Path(os.getcwd())
    output_text: str | None = None
    truncated = False
    output_path: str | None = None
    if output:
        candidate = Path(output)
        output_text, truncated = _bounded_output(candidate)
        if output_text is not None:
            events_path = os.environ.get("SASE_TOOL_RUN_EVENTS") or ""
            if events_path:
                output_path = _output_path_for(candidate, events_path)
    ancestry, baseline, selection = _gather_stage_inputs(
        root, base, project, tool, extra_args
    )
    try:
        result = tool_run_triage_stage(
            {
                "run_id": run_id,
                "stage": {
                    "stage_key": description,
                    "stage_id": stage_id,
                    "output": output_text,
                    "truncated": truncated,
                    "output_path": output_path,
                },
                "project_root": str(root),
                "workspace_roots": [str(root)],
                "ancestry": ancestry,
                "flake_baseline": baseline,
                "selection_records": selection,
                "owner_candidates": [],
                "knobs": triage_knobs(),
                "now_ts": int(time.time()),
            }
        )
    except Exception as exc:  # noqa: BLE001 - triage must always fail open.
        _emit("stop", "helper_error", {})
        print(f"sase tool _triage-stage: triage failed ({exc})", file=sys.stderr)
        return 1
    if not isinstance(result, dict) or result.get("refused"):
        _emit("stop", "helper_error", {})
        return 1
    decision, reason, counts = stage_decision(result.get("items"))
    _emit(decision, reason, counts)
    return 0 if decision == "continue" else 1


def _emit(decision: str, reason: str, counts: dict[str, int]) -> None:
    print(
        json.dumps(
            {"decision": decision, "reason": reason, "counts": counts},
            sort_keys=True,
        )
    )


__all__ = ["execute_triage_stage", "stage_decision"]
