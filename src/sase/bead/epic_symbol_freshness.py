"""Early freshness refusal for closed-bead Symvision whitelist rows."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import sys
from typing import Any

from sase.bead.epic_symbols import (
    default_branch_ref,
    discover_justfile,
    fetch_default_branch,
    parse_epic_symbol_entries,
    repo_root_for,
    run_git,
)
from sase.bead.operation_context import resolve_operation_context_for_targets
from sase.core import bead_read_facade
from sase.core.rust import require_rust_binding


def _assess_local_checkout(
    start: Path | None = None,
) -> list[dict[str, Any]]:
    """Assess local Justfile rows using live status and fresh Git evidence."""
    justfile = discover_justfile(start)
    if justfile is None:
        return []
    try:
        local_entries = parse_epic_symbol_entries(
            justfile.read_text(encoding="utf-8"), source=justfile
        )
    except OSError:
        return []
    if not local_entries:
        return []

    bead_ids = sorted({entry.bead_id for entry in local_entries})
    repo_root = repo_root_for(justfile.parent)
    statuses = _read_statuses(repo_root, bead_ids)
    if not any(status == "closed" for status in statuses.values()):
        return []

    local_head = _git_revision(repo_root, "HEAD") if repo_root else None
    relative_justfile = _relative_justfile(repo_root, justfile)
    head_rows = (
        _rows_at_revision(repo_root, local_head, relative_justfile)
        if repo_root is not None and local_head is not None
        else None
    )
    upstream_revision, upstream_rows, fetched, fetch_error = _fresh_upstream_rows(
        repo_root,
        relative_justfile,
    )
    descends = (
        _is_ancestor(repo_root, local_head, upstream_revision)
        if repo_root is not None
        and local_head is not None
        and upstream_revision is not None
        else None
    )

    request = {
        "local_rows": _rows_wire(local_entries),
        "head_rows": None if head_rows is None else _rows_wire(head_rows),
        "statuses": statuses,
        "local_head": local_head,
        "upstream_revision": upstream_revision,
        "upstream_fetch_succeeded": fetched,
        "upstream_rows": (None if upstream_rows is None else _rows_wire(upstream_rows)),
        "upstream_descends_from_head": descends,
    }
    assessments: list[dict[str, Any]] = require_rust_binding(
        "bead_assess_epic_symbol_freshness"
    )(request)
    if fetch_error is not None:
        for assessment in assessments:
            if assessment.get("classification") == "uncertain":
                assessment["reason"] = (
                    f"{assessment['reason']} (upstream observation: {fetch_error})"
                )
    # Missing status remains Symvision's responsibility. Never infer that a
    # missing or unreadable bead is open or closed in this preflight.
    return [
        assessment for assessment in assessments if assessment.get("status") == "closed"
    ]


def _read_statuses(repo_root: Path | None, bead_ids: list[str]) -> dict[str, str]:
    if repo_root is None:
        return {}
    grouped: dict[Path, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for requested_id in bead_ids:
        try:
            context = resolve_operation_context_for_targets(
                [requested_id], cwd=repo_root
            )
        except Exception:  # noqa: BLE001 - preserve Symvision's lookup behavior.
            continue
        if not context.resolved_ids:
            continue
        grouped[context.beads_dir][context.resolved_ids[0]].add(requested_id)

    statuses: dict[str, str] = {}
    for beads_dir, canonical_to_requested in grouped.items():
        canonical_ids = sorted(canonical_to_requested)
        try:
            resolved = bead_read_facade.statuses_for_ids(beads_dir, canonical_ids)
        except Exception:  # noqa: BLE001 - preserve Symvision's lookup behavior.
            continue
        for canonical_id, requested_ids in canonical_to_requested.items():
            status = resolved.get(canonical_id)
            if status is not None:
                for requested_id in requested_ids:
                    statuses[requested_id] = status
    return statuses


def _rows_wire(entries: list[Any]) -> list[dict[str, str]]:
    return [{"bead_id": entry.bead_id, "symbol": entry.symbol} for entry in entries]


def _relative_justfile(repo_root: Path | None, justfile: Path) -> str | None:
    if repo_root is None:
        return None
    try:
        return justfile.relative_to(repo_root).as_posix()
    except ValueError:
        return None


def _git_revision(repo_root: Path, revision: str) -> str | None:
    result = run_git(
        repo_root,
        "rev-parse",
        "--verify",
        f"{revision}^{{commit}}",
        timeout=15,
    )
    if result is None or result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _rows_at_revision(
    repo_root: Path,
    revision: str,
    relative_justfile: str | None,
) -> list[Any] | None:
    if relative_justfile is None:
        return None
    tree_entry = run_git(
        repo_root,
        "ls-tree",
        "-z",
        revision,
        "--",
        relative_justfile,
        timeout=15,
    )
    if tree_entry is None or tree_entry.returncode != 0:
        return None
    if not tree_entry.stdout:
        return []
    content = run_git(
        repo_root,
        "show",
        f"{revision}:{relative_justfile}",
        timeout=15,
    )
    if content is None or content.returncode != 0:
        return None
    return parse_epic_symbol_entries(content.stdout)


def _fresh_upstream_rows(
    repo_root: Path | None,
    relative_justfile: str | None,
) -> tuple[str | None, list[Any] | None, bool, str | None]:
    if repo_root is None:
        return None, None, False, "current checkout has no Git root"
    if relative_justfile is None:
        return None, None, False, "Justfile is outside the Git root"
    ref = default_branch_ref(repo_root)
    if ref is None:
        return None, None, False, "default branch ref is unavailable"
    fetch_error = fetch_default_branch(repo_root, ref)
    if fetch_error is not None:
        return None, None, False, fetch_error

    revision = _git_revision(repo_root, "FETCH_HEAD")
    if revision is None:
        return None, None, True, "fetch succeeded but FETCH_HEAD is unavailable"
    rows = _rows_at_revision(repo_root, revision, relative_justfile)
    if rows is None:
        return revision, None, True, "fetched revision's Justfile is unreadable"
    return revision, rows, True, None


def _is_ancestor(
    repo_root: Path,
    local_head: str,
    upstream_revision: str,
) -> bool | None:
    result = run_git(
        repo_root,
        "merge-base",
        "--is-ancestor",
        local_head,
        upstream_revision,
        timeout=15,
    )
    if result is None:
        return None
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    return None


def _describe(assessment: dict[str, Any]) -> str:
    bead_id = assessment["bead_id"]
    symbol = assessment["symbol"]
    classification = assessment["classification"]
    local_head = assessment.get("local_head") or "unknown"
    upstream_revision = assessment.get("upstream_revision") or "unknown"
    reason = assessment["reason"]
    prefix = (
        f"--epic-symbol '{bead_id}({symbol})' ({classification}): {reason}. "
        f"local HEAD {local_head}; observed upstream revision {upstream_revision}. "
    )
    if classification == "stale_checkout":
        return prefix + (
            "Preserve local work, integrate the upstream cleanup through the normal "
            "workspace workflow, then rerun verification."
        )
    if classification == "local_invalid_row":
        return prefix + (
            "Resolve the row under Symvision's existing cleanup or legitimate re-keying "
            "policy, then rerun verification."
        )
    if classification == "upstream_unresolved":
        return prefix + (
            "The row still exists upstream; resolve the symbol and row under the "
            "existing Symvision policy, then rerun verification."
        )
    return prefix + (
        "Upstream cleanliness is unproven. Preserve local work and resolve the closed "
        "row under Symvision's existing cleanup or legitimate re-keying policy; do not "
        "treat cached evidence as proof that the default branch is clean."
    )


def _run_preflight(start: Path | None = None) -> int:
    """Print a closed-row refusal and return a nonzero status, when needed."""
    assessments = _assess_local_checkout(start)
    if not assessments:
        return 0
    print(
        "epic-symbol freshness preflight refused verification: known closed-bead "
        "whitelist rows remain in this checkout.",
        file=sys.stderr,
    )
    for assessment in assessments:
        print(f"  {_describe(assessment)}", file=sys.stderr)
    return 1


def main() -> int:
    return _run_preflight()


if __name__ == "__main__":
    raise SystemExit(main())
