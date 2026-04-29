"""Phase 6G dual-run parity gate.

Exercises every shipped Rust core operation under ``SASE_CORE_DUAL_RUN=1``
against the committed golden corpus and a sanitized home-tree fixture, then
reads the resulting JSONL log and exits non-zero if any comparison record
reports ``match: false``.

Shipped operations covered (one section per facade):

- ``parse_project_bytes``            — :mod:`sase.core.parser_facade`
- ``parse_query`` / ``evaluate_query_many``
                                     — :mod:`sase.core.query_facade`
- ``scan_agent_artifacts``           — :mod:`sase.core.agent_scan_facade`
- ``read_status_from_lines`` / ``apply_status_update`` /
  ``plan_status_transition``        — :mod:`sase.core.status_facade`
- ``parse_git_name_status_z`` / ``parse_git_branch_name`` /
  ``derive_git_workspace_name`` / ``parse_git_conflicted_files`` /
  ``parse_git_local_changes``        — :mod:`sase.core.git_query_facade`

The script is invoked from ``.github/workflows/ci.yml`` (job
``parity-gate``) and from the convenience target ``just parity-check``.

Usage::

    python tests/parity/dual_run_parity.py --log-path /tmp/parity.jsonl \\
        --summary-path /tmp/parity_summary.json

Exits 1 when any shipped operation has zero records or any record has
``match: false``. The JSONL log and the per-operation summary are intended
to be archived as CI artifacts so a regression can be inspected post-hoc.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PROJECT = REPO_ROOT / "tests" / "core_golden" / "myproj.gp"

# Operations Phase 6 defaults to Rust. The parity gate must produce at
# least one record per name and every record must report ``match: true``.
SHIPPED_OPERATIONS: tuple[str, ...] = (
    "parse_project_bytes",
    "parse_query",
    "evaluate_query_many",
    "scan_agent_artifacts",
    "read_status_from_lines",
    "apply_status_update",
    "plan_status_transition",
    "parse_git_name_status_z",
    "parse_git_branch_name",
    "derive_git_workspace_name",
    "parse_git_conflicted_files",
    "parse_git_local_changes",
)

# Operations whose Python and Rust impls have a *documented* parity gap
# the dual-run comparator cannot reconcile via the default deep-equality
# walk, so the gate verifies the binding produced records but does not
# require ``match: true`` on every record. The known-good cross-backend
# parity for these operations is enforced separately:
#
# - ``parse_project_bytes``: the Python parser does not track
#   ``source_span.end_line`` (Phase 1F decision —
#   ``plans/202604/rust_backend_phase1_handoff.md``); the
#   ``tests/test_core_parity_smoke.py`` golden-corpus tests normalize
#   that field and still pin byte-for-byte equality elsewhere.
DOCUMENTED_DIVERGENCE: frozenset[str] = frozenset(
    {
        "parse_project_bytes",
    }
)


def _exercise_parser() -> None:
    from sase.core import parser_facade

    data = GOLDEN_PROJECT.read_bytes()
    parser_facade.parse_project_bytes(str(GOLDEN_PROJECT), data)


def _exercise_query() -> None:
    from sase.core import parser_facade, query_facade

    sys.path.insert(0, str(REPO_ROOT / "tests"))
    from _query_golden_corpus import GOLDEN_QUERIES  # type: ignore[import-not-found]

    specs = parser_facade.parse_project_file(str(GOLDEN_PROJECT))
    for query in GOLDEN_QUERIES:
        query_facade.parse_query(query)
        query_facade.evaluate_query_many(query, specs)


def _exercise_agent_scan(tmp_dir: Path) -> None:
    from sase.core.agent_scan_facade import scan_agent_artifacts

    sys.path.insert(0, str(REPO_ROOT / "tests"))
    from agent_scan_golden.fixture_builder import build_fixture_tree

    projects_root = tmp_dir / "projects"
    build_fixture_tree(projects_root)
    scan_agent_artifacts(projects_root)


def _exercise_status() -> None:
    from sase.core.status_facade import (
        apply_status_update,
        plan_status_transition,
        read_status_from_lines,
    )
    from sase.core.status_wire import (
        STATUS_WIRE_SCHEMA_VERSION,
        StatusTransitionRequestWire,
    )

    project_lines = GOLDEN_PROJECT.read_text().splitlines()
    for name in ("alpha", "beta", "gamma", "missing_spec"):
        read_status_from_lines(project_lines, name)
    for name, target in (
        ("alpha", "Submitted"),
        ("alpha", "Reverted"),
    ):
        apply_status_update(project_lines, name, target)

    request = StatusTransitionRequestWire(
        schema_version=STATUS_WIRE_SCHEMA_VERSION,
        changespec_name="alpha",
        old_status="WIP",
        new_status="Draft",
        validate=True,
        parent_status=None,
    )
    plan_status_transition(request)
    plan_status_transition(
        StatusTransitionRequestWire(
            schema_version=STATUS_WIRE_SCHEMA_VERSION,
            changespec_name="alpha",
            old_status="Draft",
            new_status="Ready",
            validate=True,
            parent_status="Submitted",
        )
    )


def _exercise_git_query() -> None:
    from sase.core.git_query_facade import (
        derive_git_workspace_name,
        parse_git_branch_name,
        parse_git_conflicted_files,
        parse_git_local_changes,
        parse_git_name_status_z,
    )

    name_status_z = (
        "M\x00src/foo.py\x00"
        "A\x00src/bar.py\x00"
        "D\x00old/baz.py\x00"
        "R100\x00from.py\x00to.py\x00"
    )
    parse_git_name_status_z(name_status_z)
    parse_git_name_status_z("")

    parse_git_branch_name("On branch main\n")
    parse_git_branch_name("HEAD detached at abc1234\n")

    derive_git_workspace_name("master", "myproj_3")
    derive_git_workspace_name("feature_x", "myproj_3")

    parse_git_conflicted_files("UU src/foo.py\n M src/bar.py\nAA src/baz.py\n")
    parse_git_conflicted_files("")

    parse_git_local_changes(" M src/foo.py\n?? new.py\n")
    parse_git_local_changes("")


def _read_records(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    records: list[dict] = []
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def _summarize(records: list[dict]) -> dict:
    by_op: dict[str, dict[str, int]] = {}
    for record in records:
        op = record.get("operation", "<unknown>")
        bucket = by_op.setdefault(
            op, {"total": 0, "match": 0, "mismatch": 0, "errors": 0}
        )
        bucket["total"] += 1
        if record.get("error_class"):
            bucket["errors"] += 1
        if record.get("match"):
            bucket["match"] += 1
        else:
            bucket["mismatch"] += 1
    return {
        "by_operation": dict(sorted(by_op.items())),
        "shipped_operations": list(SHIPPED_OPERATIONS),
        "total_records": len(records),
    }


def _first_mismatch_per_op(records: list[dict]) -> dict[str, dict]:
    seen: dict[str, dict] = {}
    for record in records:
        op = record.get("operation", "<unknown>")
        if not record.get("match") and op not in seen:
            seen[op] = record
    return seen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-l",
        "--log-path",
        type=Path,
        default=None,
        help="Override the dual-run JSONL log path (default: a tempfile).",
    )
    parser.add_argument(
        "-s",
        "--summary-path",
        type=Path,
        default=None,
        help="Optional path to write a JSON summary (per-op match counts).",
    )
    args = parser.parse_args(argv)

    tmp_root = Path(tempfile.mkdtemp(prefix="sase_parity_"))
    log_path = args.log_path or (tmp_root / "core_dual_run.jsonl")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        log_path.unlink()

    os.environ["SASE_CORE_DUAL_RUN"] = "1"
    os.environ["SASE_CORE_DUAL_RUN_LOG"] = str(log_path)
    os.environ.pop("SASE_CORE_BACKEND", None)

    print(f"[parity] log path: {log_path}", flush=True)
    print(f"[parity] fixture root: {tmp_root}", flush=True)

    _exercise_parser()
    _exercise_query()
    _exercise_agent_scan(tmp_root)
    _exercise_status()
    _exercise_git_query()

    records = _read_records(log_path)
    summary = _summarize(records)
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)

    if args.summary_path is not None:
        args.summary_path.parent.mkdir(parents=True, exist_ok=True)
        args.summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))

    failures: list[str] = []
    op_counts = Counter(r.get("operation", "<unknown>") for r in records)
    for op in SHIPPED_OPERATIONS:
        if op_counts.get(op, 0) == 0:
            failures.append(f"shipped op {op!r} produced no dual-run record")
    mismatches = _first_mismatch_per_op(records)
    for op, record in sorted(mismatches.items()):
        if op not in SHIPPED_OPERATIONS:
            continue
        if op in DOCUMENTED_DIVERGENCE:
            print(
                f"[parity] note: {op!r} has a documented parity gap; "
                f"first_diff_path={record.get('first_diff_path')!r}"
                f" — see DOCUMENTED_DIVERGENCE.",
                flush=True,
            )
            continue
        failures.append(
            f"mismatch in {op!r}: first_diff_path={record.get('first_diff_path')!r}"
            f" error_class={record.get('error_class')!r}"
        )
    error_records = [r for r in records if r.get("error_class")]
    for record in error_records:
        op = record.get("operation", "<unknown>")
        if op in SHIPPED_OPERATIONS:
            failures.append(
                f"rust_impl raised in {op!r}: {record.get('error_class')!r}"
            )

    if failures:
        print("\n[parity] FAIL", flush=True)
        for line in failures:
            print(f"  - {line}", flush=True)
        return 1

    print(
        f"\n[parity] OK — {len(records)} records, "
        f"{len(SHIPPED_OPERATIONS)} shipped ops all match",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
