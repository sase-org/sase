"""Per-pane first-paint benchmark for the Artifacts sub-tabs.

Measures, per pane (Agent, Bead, Plan, File), the split between:

- **snapshot-load**: the pane's off-thread data loader (``load_agents_snapshot``,
  ``load_beads_snapshot``, ``build_plan_inventory``, ``load_files_snapshot``).
- **query-index**: building the Rust-backed query index over that snapshot
  (``build_*_query_index`` in ``query_rows.py``), when the pane's current code
  builds one at all.
- **first-paint**: what a default ``limit:100`` blank-query view actually
  costs *today*, before this epic's sibling phases land. For panes that
  already short-circuit past the query index (Agent) or already bound their
  index build (File), first paint is cheaper than snapshot-load +
  query-index. For panes that do not yet have that short circuit (Bead,
  Plan), first paint equals (or, for Plan, approximates) snapshot-load plus
  whatever index cost the pane's current code pays before it can render —
  that gap is exactly what this epic's sibling phases close, and this bench
  reports it plainly rather than inventing a shortcut that does not exist
  yet (``plan:202608/artifacts_query_performance.md`` §1.4, §3).

This bench calls the same plain-Python functions the panes' Textual workers
call, never ``AcePage``/the mounted TUI: driving the real async/worker
machinery would make this benchmark slow and flaky for no measurement
benefit (see ``src/sase/ace/tui/widgets/artifacts/snapshot_pane.py``).

Corpus sizes mirror the plan's measured live-scale reference point (§1.1):
12,525 Agent registry names (reusing ``bench_agent_catalog``'s fixture),
4,346 beads, 1,900 archived plan files, 8,099 File rows. None of the panes
are expected to already hit the epic's ~400ms/~700ms targets (§2.1) — this
phase (``bench``) only builds honest measurement infrastructure; the
sibling phases (``registry``, ``agent-paint``, ``core-corpus``,
``entry-projection``, ``plans``, ``beads``) are what make those targets
reachable.

Assertions are structural, not tight wall-clock budgets, mirroring
``tests/ace/tui/bench_admin_center_open.py``'s stated philosophy.

Run with ``pytest -s -m slow tests/perf/bench_artifacts_first_paint.py`` or
directly as ``python -m tests.perf.bench_artifacts_first_paint``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.query.limit_token import apply_limit, extract_limit
from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.ace.tui.widgets.artifacts import beads_data, files_data
from sase.ace.tui.widgets.artifacts.agents_data import load_agents_snapshot
from sase.ace.tui.widgets.artifacts.beads_data import load_beads_snapshot
from sase.ace.tui.widgets.artifacts.files_data import (
    FILES_FIRST_PAGE_LIMIT,
    load_files_snapshot,
)
from sase.ace.tui.widgets.artifacts.query_rows import (
    build_agents_query_index,
    build_beads_query_index,
    build_files_query_index,
)
from sase.agents.catalog import _build as agent_catalog_build
from sase.bead import db as db_mod
from sase.bead.config import save_config
from sase.bead.jsonl import export_to_jsonl
from sase.bead.model import Issue, IssueType, Status
from sase.core.paths import sase_home
from sase.main.plan_inventory import build_plan_inventory
from sase.project_display_names import ProjectRefDisplaySnapshot
from tests._plan_inventory_helpers import archived_plan
from tests.ace.tui._artifacts_files_helpers import artifact_file
from tests.perf.bench_agent_catalog import (
    _REFERENCE_REGISTRY_SIZE,
    _write_synthetic_artifact_index,
    _write_synthetic_registry,
    build_synthetic_catalog_sources,
)

pytestmark = pytest.mark.slow

_RUNS = 5
_WARMUP = 1
_BEAD_ISSUE_COUNT = 4346
_PLAN_ARCHIVE_COUNT = 1900
_FILE_CORPUS_SIZE = 8099
_DEFAULT_LIMIT = 100
_FILE_PROJECTS = ("gh_sase-org__sase", "gh_bobs-org__bob-cli", "home")


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, round(percentile * (len(ordered) - 1)))
    return ordered[index]


def _summarize(values_seconds: list[float]) -> dict[str, float]:
    values_ms = sorted(v * 1000.0 for v in values_seconds)
    return {
        "count": float(len(values_ms)),
        "min_ms": values_ms[0],
        "median_ms": statistics.median(values_ms),
        "p95_ms": _percentile(values_ms, 0.95),
        "max_ms": values_ms[-1],
    }


# --------------------------------------------------------------------------
# Agent pane
# --------------------------------------------------------------------------


def bench_agent_pane(
    *,
    runs: int,
    warmup: int,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """Agent pane: full registry/artifact-index load, then a blank ``limit:100`` view.

    Reuses ``bench_agent_catalog``'s repaired (real ``source`` + real on-disk
    artifact tree) fixture so the Agent corpus pays the same registry
    revalidation cost the live pane pays, rather than reinventing it.
    """

    entries, index_rows, dismissed_summaries = build_synthetic_catalog_sources(
        _REFERENCE_REGISTRY_SIZE, with_real_sources=True
    )
    _write_synthetic_registry(entries)
    _write_synthetic_artifact_index(index_rows)
    monkeypatch.setattr(
        agent_catalog_build, "load_dismissed_top_level", lambda: dismissed_summaries
    )
    monkeypatch.setattr(
        agent_catalog_build, "load_dismissed_child_fallback", lambda _suffixes: {}
    )

    profile = compiled_profile_for_builtin_pane("agents")
    assert profile is not None
    project_ref_display = ProjectRefDisplaySnapshot()

    def _sample() -> tuple[float, float, float, int]:
        start = time.perf_counter()
        snapshot = load_agents_snapshot(None)
        load_s = time.perf_counter() - start

        start = time.perf_counter()
        index = build_agents_query_index(
            snapshot,
            pane_id="agents",
            generation=0,
            profile=profile,
            project_ref_display=project_ref_display,
        )
        index_s = time.perf_counter() - start
        del index  # only the build cost is measured; first paint never uses it

        # Mirrors agents_query.py's _filtered_agents_snapshot: a blank query
        # remainder (the default "limit:100" view) slices snapshot.rows
        # directly and never consults the query index at all.
        start = time.perf_counter()
        remainder, cap = extract_limit(f"limit:{_DEFAULT_LIMIT}")
        assert remainder == ""
        capped, _truncated = apply_limit(snapshot.rows, cap)
        first_paint_s = load_s + (time.perf_counter() - start)
        return load_s, index_s, first_paint_s, len(capped)

    for _ in range(warmup):
        _sample()
    loads: list[float] = []
    indexes: list[float] = []
    first_paints: list[float] = []
    default_view_row_count = 0
    for _ in range(runs):
        load_s, index_s, first_paint_s, row_count = _sample()
        loads.append(load_s)
        indexes.append(index_s)
        first_paints.append(first_paint_s)
        default_view_row_count = row_count

    return {
        "pane": "agents",
        "corpus_size": _REFERENCE_REGISTRY_SIZE,
        "snapshot_load_ms": _summarize(loads),
        "query_index_ms": _summarize(indexes),
        "first_paint_ms": _summarize(first_paints),
        "first_paint_needs_index": False,
        "default_view_row_count": default_view_row_count,
    }


# --------------------------------------------------------------------------
# Bead pane
# --------------------------------------------------------------------------


def _write_bead_corpus(beads_dir: Path, *, issue_count: int) -> None:
    """Write a real bead store at live scale.

    Same on-disk shape ``tests/perf/bench_bead.py``'s ``_write_project``
    uses (a real ``beads.db`` plus the ``issues.jsonl`` export the Rust
    ``bead_read_facade`` bindings read) — a bare ``beads.db`` alone is not
    the on-disk shape ``load_beads_snapshot`` expects in production.
    """

    beads_dir.mkdir(parents=True, exist_ok=True)
    save_config(
        beads_dir,
        {"issue_prefix": "bench", "next_counter": issue_count + 1, "owner": ""},
    )
    conn = db_mod.init_db(beads_dir / "beads.db")
    try:
        plan_count = max(1, issue_count // 40)
        statuses = (
            Status.OPEN,
            Status.READY,
            Status.IN_PROGRESS,
            Status.CLOSED,
            Status.CLAIMED,
        )
        for idx in range(issue_count):
            if idx < plan_count:
                issue = Issue(
                    id=f"bench-{idx + 1}",
                    title=f"Plan {idx + 1}",
                    status=Status.OPEN,
                    issue_type=IssueType.PLAN,
                    created_at="2026-01-01T00:00:00Z",
                    updated_at="2026-01-01T00:00:00Z",
                )
            else:
                issue = Issue(
                    id=f"bench-task-{idx + 1}",
                    title=f"Task {idx + 1}",
                    status=statuses[idx % len(statuses)],
                    issue_type=IssueType.TASK,
                    created_at="2026-01-01T01:00:00Z",
                    updated_at="2026-01-01T01:00:00Z",
                )
            db_mod.create_issue(conn, issue)
        export_to_jsonl(conn, beads_dir / "issues.jsonl")
    finally:
        conn.close()


def bench_bead_pane(
    *,
    runs: int,
    warmup: int,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """Bead pane: real bead-store reads, then the pane's always-built query index.

    ``load_beads_snapshot`` resolves projects, beads directories, and
    document roots through several layers
    (``get_project_beads_dirs_for_project`` -> ``resolve_primary_workspace_for_project``
    -> a real managed-checkout marker) that this bench does not need to
    prove; those seams are already covered by
    ``tests/ace/tui/test_artifacts_beads_loading.py``. This bench
    dependency-injects them (matching that test's own pattern) so it can
    point straight at a real bead store, while leaving
    ``_load_project_beads`` -- the Rust ``bead_read_facade`` reads that are
    the Bead pane's honest floor per the epic plan §1.3 -- untouched and
    real. The external ``gh``-issue network call
    (``_load_external_issue_caches``) is a separate, already-documented
    problem (plan §1.3, fixed by the sibling ``beads`` phase, not this one);
    it is stubbed to return instantly so this bench measures the Python-side
    costs cleanly.
    """

    beads_dir = sase_home() / "bench_beads_store"
    _write_bead_corpus(beads_dir, issue_count=_BEAD_ISSUE_COUNT)

    resolved = (
        SimpleNamespace(
            project="bench",
            display_name="Bench",
            workspace_dir=str(beads_dir.parent),
        ),
    )
    monkeypatch.setattr(beads_data, "_resolve_projects", lambda _project: resolved)
    monkeypatch.setattr(beads_data, "_project_beads_dir", lambda _project: beads_dir)
    monkeypatch.setattr(beads_data, "_project_document_roots", lambda _project: {})
    monkeypatch.setattr(
        beads_data,
        "_load_external_issue_caches",
        lambda *_args, **_kwargs: {},
    )

    profile = compiled_profile_for_builtin_pane("beads")
    assert profile is not None

    def _sample() -> tuple[float, float, int]:
        start = time.perf_counter()
        snapshot = load_beads_snapshot("bench", patches=())
        load_s = time.perf_counter() - start

        start = time.perf_counter()
        _filter_index, index = build_beads_query_index(
            snapshot,
            pane_id="beads",
            generation=0,
            profile=profile,
        )
        index_s = time.perf_counter() - start
        del index

        capped, _truncated = apply_limit(snapshot.tasks, _DEFAULT_LIMIT)
        return load_s, index_s, len(capped)

    for _ in range(warmup):
        _sample()
    loads: list[float] = []
    indexes: list[float] = []
    default_view_row_count = 0
    for _ in range(runs):
        load_s, index_s, row_count = _sample()
        loads.append(load_s)
        indexes.append(index_s)
        default_view_row_count = row_count

    # beads_pane.py's _build_snapshot calls build_beads_query_index
    # unconditionally before any row can render -- there is no blank-query
    # short circuit like the Agent pane's _filtered_agents_snapshot. First
    # paint is therefore blocked on the full-corpus index today; that gap is
    # exactly what the sibling `beads`/`agent-paint`-style phases close.
    first_paints = [
        load_s + index_s for load_s, index_s in zip(loads, indexes, strict=True)
    ]

    return {
        "pane": "beads",
        "corpus_size": _BEAD_ISSUE_COUNT,
        "snapshot_load_ms": _summarize(loads),
        "query_index_ms": _summarize(indexes),
        "first_paint_ms": _summarize(first_paints),
        "first_paint_needs_index": True,
        "default_view_row_count": default_view_row_count,
    }


# --------------------------------------------------------------------------
# Plan pane
# --------------------------------------------------------------------------


def bench_plan_pane(*, runs: int, warmup: int) -> dict[str, Any]:
    """Plan pane: ``build_plan_inventory(limit=50, statuses=("proposed",))`` directly.

    This is what ``load_proposals`` (``plans_data_sources.py``) calls, and
    per the epic plan §1.3 it is the pane's actual cost driver: pre-fix, it
    always computes the rejected section too, YAML-parsing every archived
    plan file the caller never asked for. No separate query-index
    measurement is taken: the plan's own baseline table (§1.1) puts Plan's
    query-index cost at 12ms, negligible next to the multi-hundred-ms
    snapshot-load cost measured below, and ``plans_pane.py`` builds its full
    ``PlansSnapshot`` (notifications, active documents, archive matches)
    through a materially different path than the plain
    ``build_plan_inventory()`` call this bench times directly. Fabricating a
    from-scratch ``PlansSnapshot`` here to feed ``build_plans_query_index``
    would not measure the pane's real cost driver, so ``query_index_ms`` is
    reported as ``None`` rather than a fabricated number.
    """

    for index in range(_PLAN_ARCHIVE_COUNT):
        archived_plan(f"plan_{index:05d}.md", minutes_ago=index + 1)

    def _sample() -> tuple[float, int]:
        start = time.perf_counter()
        inventory = build_plan_inventory(limit=50, statuses=("proposed",))
        load_s = time.perf_counter() - start
        capped, _truncated = apply_limit(inventory.proposed, _DEFAULT_LIMIT)
        return load_s, len(capped)

    for _ in range(warmup):
        _sample()
    loads: list[float] = []
    default_view_row_count = 0
    for _ in range(runs):
        load_s, row_count = _sample()
        loads.append(load_s)
        default_view_row_count = row_count

    return {
        "pane": "ref:plan",
        "corpus_size": _PLAN_ARCHIVE_COUNT,
        "snapshot_load_ms": _summarize(loads),
        "query_index_ms": None,
        "first_paint_ms": _summarize(loads),
        "first_paint_needs_index": None,
        "default_view_row_count": default_view_row_count,
    }


# --------------------------------------------------------------------------
# File pane
# --------------------------------------------------------------------------


def _synthetic_artifact_files(count: int) -> list[Any]:
    return [
        artifact_file(
            f"perf-file-{index:06d}",
            artifact_id=f"perf-file-{index:024d}",
            created_at=f"2026-08-{1 + index % 28:02d}T12:00:00-04:00",
            project=_FILE_PROJECTS[index % len(_FILE_PROJECTS)],
        )
        for index in range(count)
    ]


def bench_file_pane(
    *,
    runs: int,
    warmup: int,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """File pane: the shipped two-stage pattern the rest of this epic generalizes.

    ``query_artifact_files``/``query_ref_file_versions`` are Rust-backed
    readers over real on-disk indexes (a sqlite artifact-files index plus a
    ref-files JSONL projection); faithfully seeding 8,099 real rows through
    both at this scale is significant infra work unrelated to what this
    bench measures. Like ``bench_agent_catalog.py``'s dependency-injected
    dismissed-archive loaders, they are dependency-injected here to return a
    synthetic corpus instantly. This still exercises
    ``load_files_snapshot``'s real Python-side merge/sort/bound logic
    (``files_data._merge_rows``/``_files_snapshot``) over a live-scale
    corpus, and the real ``build_files_query_index`` call -- which is what
    this bench needs to measure.
    """

    corpus = _synthetic_artifact_files(_FILE_CORPUS_SIZE)

    def _query_artifact_files(
        *, project: str | None, limit: int | None, **_kwargs: Any
    ) -> list[Any]:
        del project
        return list(corpus) if limit is None else corpus[:limit]

    monkeypatch.setattr(files_data, "query_artifact_files", _query_artifact_files)
    monkeypatch.setattr(files_data, "query_ref_file_versions", lambda **_kwargs: ())

    profile = compiled_profile_for_builtin_pane("files")
    assert profile is not None
    project_ref_display = ProjectRefDisplaySnapshot()

    def _sample() -> tuple[float, float, Any]:
        start = time.perf_counter()
        snapshot = load_files_snapshot(None, FILES_FIRST_PAGE_LIMIT)
        load_s = time.perf_counter() - start

        # files_pane.py's _build_snapshot builds the query index over
        # whatever snapshot.rows already is -- the bounded first-page
        # snapshot on the non-"full" pass -- not the full corpus. That
        # bound is what makes this pane's first paint cheap today.
        start = time.perf_counter()
        index = build_files_query_index(
            snapshot,
            pane_id="files",
            generation=0,
            profile=profile,
            project_ref_display=project_ref_display,
        )
        index_s = time.perf_counter() - start
        del index
        return load_s, index_s, snapshot

    for _ in range(warmup):
        _sample()
    loads: list[float] = []
    indexes: list[float] = []
    last_snapshot = None
    for _ in range(runs):
        load_s, index_s, snapshot = _sample()
        loads.append(load_s)
        indexes.append(index_s)
        last_snapshot = snapshot

    assert last_snapshot is not None
    first_paints = [
        load_s + index_s for load_s, index_s in zip(loads, indexes, strict=True)
    ]
    capped, _truncated = apply_limit(last_snapshot.rows, _DEFAULT_LIMIT)

    return {
        "pane": "files",
        "corpus_size": _FILE_CORPUS_SIZE,
        "snapshot_load_ms": _summarize(loads),
        "query_index_ms": _summarize(indexes),
        "first_paint_ms": _summarize(first_paints),
        "first_paint_needs_index": "bounded",
        "default_view_row_count": len(capped),
        "snapshot_complete": last_snapshot.complete,
        "snapshot_row_count": len(last_snapshot.rows),
    }


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def _print_report(reports: list[dict[str, Any]]) -> None:
    print(
        "\nArtifacts sub-tab first paint (live-scale synthetic corpus)",
        file=sys.stderr,
    )
    print(
        f"  {'pane':<10} {'phase':<14} {'n':>4} "
        f"{'p50_ms':>10} {'p95_ms':>10} {'max_ms':>10}",
        file=sys.stderr,
    )
    for report in reports:
        pane = str(report["pane"])
        for phase in ("snapshot_load_ms", "query_index_ms", "first_paint_ms"):
            stats = report[phase]
            label = phase.removesuffix("_ms")
            if stats is None:
                print(
                    f"  {pane:<10} {label:<14} {'N/A':>4} "
                    f"{'-':>10} {'-':>10} {'-':>10}",
                    file=sys.stderr,
                )
                continue
            print(
                f"  {pane:<10} {label:<14} {int(stats['count']):>4} "
                f"{stats['median_ms']:>10.2f} {stats['p95_ms']:>10.2f} "
                f"{stats['max_ms']:>10.2f}",
                file=sys.stderr,
            )
        print(
            f"    corpus_size={report['corpus_size']} "
            f"first_paint_needs_index={report['first_paint_needs_index']!r} "
            f"default_view_row_count={report['default_view_row_count']}",
            file=sys.stderr,
        )


def run_benchmark(*, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    return [
        bench_agent_pane(runs=_RUNS, warmup=_WARMUP, monkeypatch=monkeypatch),
        bench_bead_pane(runs=_RUNS, warmup=_WARMUP, monkeypatch=monkeypatch),
        bench_plan_pane(runs=_RUNS, warmup=_WARMUP),
        bench_file_pane(runs=_RUNS, warmup=_WARMUP, monkeypatch=monkeypatch),
    ]


def test_bench_artifacts_first_paint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Structural invariants only -- no tight wall-clock budgets.

    None of the four panes are expected to already meet the epic's §2.1
    targets; the sibling phases that make them reachable have not landed.
    This test only asserts what is verifiably true of each pane's current
    code today, plus the printed report for humans to compare against the
    plan's baseline numbers.
    """

    reports = run_benchmark(monkeypatch=monkeypatch)
    _print_report(reports)

    by_pane = {report["pane"]: report for report in reports}

    # Correctness invariant, distinct from the perf ones above: every pane's
    # default limit:100 view never renders more than 100 rows, regardless of
    # corpus size.
    for report in reports:
        assert report["default_view_row_count"] <= _DEFAULT_LIMIT, report["pane"]

    # The Agent pane already short-circuits past the query index for a blank
    # query (agents_query.py's _filtered_agents_snapshot); first paint must
    # not require it.
    assert by_pane["agents"]["first_paint_needs_index"] is False

    # The Bead pane has no such short circuit yet: its _build_snapshot
    # always builds the full query index before any row can render. This is
    # the honest gap the epic's sibling phases close, not something to hide.
    assert by_pane["beads"]["first_paint_needs_index"] is True

    # File pane: the one pane that already ships a bounded first page
    # (files_data.FILES_FIRST_PAGE_LIMIT) with a background extension to the
    # full index. At a corpus larger than the cap, the loaded snapshot must
    # stay capped and report itself incomplete.
    files_report = by_pane["files"]
    assert files_report["corpus_size"] > FILES_FIRST_PAGE_LIMIT
    assert files_report["snapshot_row_count"] == FILES_FIRST_PAGE_LIMIT
    assert files_report["snapshot_complete"] is False


def main(argv: list[str] | None = None) -> int:
    import tempfile

    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.parse_args(argv)
    with (
        pytest.MonkeyPatch.context() as monkeypatch,
        tempfile.TemporaryDirectory() as tmp,
    ):
        monkeypatch.setenv("SASE_HOME", str(Path(tmp) / ".sase"))
        reports = run_benchmark(monkeypatch=monkeypatch)
    _print_report(reports)
    return 0


if __name__ == "__main__":
    sys.exit(main())
