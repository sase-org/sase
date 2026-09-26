"""Bounded, fail-open inputs for ToolRun failure triage.

Every gatherer returns ``(value, diagnostics)``.  Failure to read an optional
source must only remove evidence, making a KNOWN or FLAKY label less likely;
it must never manufacture one.  This module deliberately owns transport and
host-local discovery only.  The Rust core owns parsing and classification.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.bead.cli_location import resolve_beads_location
from sase.bead.model import IssueType, Status
from sase.core.bead_read_facade import list_issues
from sase.core.paths import sase_home
from sase.core.tool_run import tool_run_triage_extract


MIN_WITNESSES = 1
TOUCHED_REQUIRES_CLEAN_WITNESS = False
ANCESTRY_MAX = 2_000
LOOKBACK_SECONDS = 7 * 86400
ANCESTRY_TIMEOUT_SECONDS = 5
BASELINE_TIMEOUT_SECONDS = 5
_WORKSPACE_COMPONENT = re.compile(r"^.+_(?P<number>\d+)$")


def triage_knobs() -> dict[str, int | bool]:
    """Return the one authoritative set of conservative classifier knobs."""

    return {
        "min_witnesses": MIN_WITNESSES,
        "touched_requires_clean_witness": TOUCHED_REQUIRES_CLEAN_WITNESS,
    }


def workspace_identity(path: str | Path) -> str | None:
    """Return the numbered-workspace suffix in *path*, if it has one."""

    try:
        components = Path(path).expanduser().parts
    except (OSError, TypeError, ValueError):
        return None
    for component in reversed(components):
        match = _WORKSPACE_COMPONENT.fullmatch(component)
        if match is not None:
            return match["number"]
    return None


def _git(
    repo_root: Path, args: list[str], *, timeout: float
) -> tuple[str | None, list[str]]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, [f"git {' '.join(args[:2])} failed: {error}"]
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        return None, [
            f"git {' '.join(args[:2])} failed: {detail or completed.returncode}"
        ]
    return completed.stdout, []


def gather_ancestry(repo_root: Path, base: str) -> tuple[list[str], list[str]]:
    """Read a bounded, first-parent ancestry list, newest commit first."""

    output, diagnostics = _git(
        repo_root,
        ["rev-list", "--first-parent", f"--max-count={ANCESTRY_MAX}", base],
        timeout=ANCESTRY_TIMEOUT_SECONDS,
    )
    if output is None:
        return [], diagnostics
    return [line for line in output.splitlines() if line], diagnostics


def _active_baseline_nodeids(text: str) -> list[str]:
    retired: set[str] = set()
    active: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            comment = line.removeprefix("#").strip()
            if comment.lower().startswith("fixed-at:"):
                parts = comment.split(":", 1)[1].strip().split(None, 1)
                if len(parts) == 2:
                    retired.add(parts[1])
            continue
        active.append(line)
    return [nodeid for nodeid in active if nodeid not in retired]


def gather_flake_baseline(
    repo_root: Path, base: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract the active committed flake baseline through the Rust parser."""

    output, diagnostics = _git(
        repo_root,
        ["show", f"{base}:tests/reproducible_flake_baseline.txt"],
        timeout=BASELINE_TIMEOUT_SECONDS,
    )
    if output is None:
        return [], diagnostics
    nodeids = _active_baseline_nodeids(output)
    if not nodeids:
        return [], diagnostics
    try:
        extracted = tool_run_triage_extract(
            {
                "stage_key": "test (scoped)",
                "output": "\n".join(f"FAILED {nodeid}" for nodeid in nodeids),
                "project_root": str(repo_root),
            }
        )
    except Exception as error:  # noqa: BLE001 - gatherers are fail-open.
        diagnostics.append(f"flake baseline extraction failed: {error}")
        return [], diagnostics
    source = f"tests/reproducible_flake_baseline.txt@{base[:12]}"
    entries: list[dict[str, Any]] = []
    for item in extracted.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        signature = item.get("signature")
        extractor = item.get("extractor")
        version = item.get("extractor_version")
        if (
            isinstance(signature, str)
            and isinstance(extractor, str)
            and isinstance(version, int)
        ):
            entries.append(
                {
                    "extractor": extractor,
                    "extractor_version": version,
                    "signature": signature,
                    "source": source,
                }
            )
    diagnostics.extend(str(item) for item in extracted.get("diagnostics") or [])
    return entries, diagnostics


def _timestamp(value: object) -> int | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


def _selection_dir(project_key: str) -> Path:
    override = os.environ.get("SASE_TEST_SELECTION_HEALTH_DIR")
    if override:
        return Path(override).expanduser()
    key = os.environ.get("SASE_TEST_SELECTION_HEALTH_PROJECT_KEY") or project_key
    return sase_home() / "test-selection" / key


def _selection_evidence_items(
    failures: object, project_root: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Turn a full-run ``failures`` list into wire-valid witness items."""

    nodes = [str(item) for item in failures] if isinstance(failures, list) else []
    nodes = [node for node in nodes if node]
    if not nodes:
        return [], []
    try:
        extracted = tool_run_triage_extract(
            {
                "stage_key": "test (scoped)",
                "output": "\n".join(f"FAILED {node}" for node in nodes),
                "project_root": project_root,
            }
        )
    except Exception as error:  # noqa: BLE001 - drop only this record's items.
        return [], [f"selection record extraction failed: {error}"]
    items: list[dict[str, Any]] = []
    for item in extracted.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        extractor = item.get("extractor")
        version = item.get("extractor_version")
        signature = item.get("signature")
        if (
            isinstance(extractor, str)
            and isinstance(version, int)
            and isinstance(signature, str)
        ):
            items.append(
                {
                    "extractor": extractor,
                    "extractor_version": version,
                    "signature": signature,
                    "stage_key": "test (scoped)",
                }
            )
    diagnostics = [
        str(note) for note in extracted.get("diagnostics") or [] if str(note)
    ]
    return items, diagnostics


def gather_selection_records(
    project_key: str,
    *,
    before_ts: int | None = None,
    now_ts: int | None = None,
    project: str | None = None,
    tool: str | None = None,
    extra_args_digest: str | None = None,
    selection_dir: Path | None = None,
    project_root: str | Path | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Project full-run records into bounded witness wires.

    The caller supplies the subject's matching fields because selection-health
    records intentionally do not duplicate a ToolRun definition.  Each record's
    ``failures`` are extracted into ``items`` here so the result validates as
    ``ToolRunTriageEvidenceRunWire``.
    """

    now = int(time.time()) if now_ts is None else now_ts
    root = selection_dir or _selection_dir(project_key)
    extract_root = str(Path(project_root) if project_root is not None else Path.cwd())
    lookback = now - LOOKBACK_SECONDS
    try:
        candidates = list(root.glob("*-full-run.json"))
    except OSError as error:
        return [], [f"selection records unavailable: {error}"]
    dated: list[tuple[float, Path]] = []
    for path in candidates:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < lookback:
            continue
        dated.append((mtime, path))
    dated.sort(key=lambda item: item[0])
    records: list[tuple[int, dict[str, Any]]] = []
    diagnostics: list[str] = []
    for _mtime, path in dated:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            diagnostics.append(f"ignored selection record {path.name}: {error}")
            continue
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema") != 2
            or payload.get("kind") != "full-run"
        ):
            continue
        recorded_at = _timestamp(payload.get("recorded_at"))
        if recorded_at is None or recorded_at < lookback:
            continue
        if before_ts is not None and recorded_at >= before_ts:
            continue
        records.append((recorded_at, dict(payload)))
    records.sort(key=lambda item: item[0], reverse=True)
    out: list[dict[str, Any]] = []
    for recorded_at, record in records[:500]:
        raw_changed = record.get("changed_files")
        changed = (
            [str(path) for path in raw_changed] if isinstance(raw_changed, list) else []
        )
        tree_dirty = record.get("tree_dirty")
        items, item_notes = _selection_evidence_items(
            record.get("failures"), extract_root
        )
        raw_head = record.get("head")
        head = raw_head if isinstance(raw_head, str) else None
        diagnostics.extend(f"{note} ({head or 'unknown'})" for note in item_notes)
        out.append(
            {
                "run_id": f"selection:{recorded_at}:{head or 'unknown'}",
                "project": project or project_key,
                "tool": tool or "check",
                "extra_args_digest": extra_args_digest or "",
                "workspace": workspace_identity(str(record.get("workspace") or "")),
                "settled_ts": recorded_at,
                "base_head": head,
                "complete_fingerprint": True,
                "dirty_paths": changed,
                "dirty_unknown": raw_changed is None and tree_dirty is True,
                "clean_tree": tree_dirty is False,
                "ad_hoc": False,
                "failed": record.get("exit_status") != 0,
                "stage_completions": [],
                "items": items,
                "selection_source": True,
            }
        )
    return out, diagnostics


def gather_owner_candidates(
    project_root: Path, *, now_ts: int | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return read-only, recent CI/flake/bug bead candidates for the core."""

    del now_ts  # Rust owns recency evaluation; this keeps the gatherer deterministic.
    location = resolve_beads_location(cwd=project_root, require_existing=True)
    if location is None:
        return [], ["bead store unavailable for owner candidates"]
    try:
        issues = list_issues(
            location.root / location.beads_dirname,
            issue_types=[IssueType.TASK],
        )
    except Exception as error:  # noqa: BLE001 - optional read-only evidence.
        return [], [f"owner candidate read failed: {error}"]
    cutoff = int(time.time()) - LOOKBACK_SECONDS
    candidates: list[dict[str, Any]] = []
    for issue in issues:
        if issue.task_type not in {"ci", "flake", "bug"}:
            continue
        closed_ts = _timestamp(issue.closed_at)
        if issue.status is Status.CLOSED and (closed_ts is None or closed_ts < cutoff):
            continue
        if issue.status is not Status.CLOSED and issue.status not in {
            Status.OPEN,
            Status.READY,
            Status.CLAIMED,
            Status.IN_PROGRESS,
            Status.SNOOZED,
        }:
            continue
        fields = issue.task_type_fields
        location_text = fields.get("node_id") or fields.get("location")
        candidates.append(
            {
                "node_id": issue.id,
                "location": location_text or None,
                "title": issue.title or None,
                "status": "closed" if issue.status is Status.CLOSED else "open",
                "closed_ts": closed_ts,
            }
        )
    return candidates, []


__all__ = [
    "ANCESTRY_MAX",
    "LOOKBACK_SECONDS",
    "MIN_WITNESSES",
    "TOUCHED_REQUIRES_CLEAN_WITNESS",
    "gather_ancestry",
    "gather_flake_baseline",
    "gather_owner_candidates",
    "gather_selection_records",
    "triage_knobs",
    "workspace_identity",
]
