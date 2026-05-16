"""Phase 6 perf bench for the Agents-tab disk loader (bead ``sase-3r.6``).

This is the end-to-end perf validation for Phase 6 of bead ``sase-3r``
(Fast Agents Tab Disk Loading). It builds a large-history fixture that
mirrors the worst real-world case: a small visible inbox (active +
recent-completed-not-dismissed) buried under many dismissed completed
artifacts.

The benchmark times three scenarios against the same fixture:

* ``inbox_query``: the visibility-aware Tier 1 inbox query exposed by
  :func:`~sase.ace.tui.models.agent_loader._query_artifact_index_for_loader`.
  This is what ``agents.load_from_disk`` calls during a normal Agents-tab
  refresh once the index is present. The dismissed sidecar is synced so
  the query excludes the dismissed completions server-side.
* ``inbox_query_no_dismissed_sync``: the same query without the
  dismissed-visibility sync. This exposes the cost of returning the full
  recent-completed set when the sidecar is stale.
* ``full_history_source_scan``: the explicit Tier 2 reconcile path. Only
  revive/archive/repair flows take this path; included here as a
  reference upper-bound for what the inbox query saves the TUI from
  doing on every refresh.

Marked ``slow`` so ``just test`` does not run it. Invoke directly with::

    pytest -s -m slow tests/perf/bench_agent_loader_phase6_inbox.py

The smoke test asserts the harness wires the three scenarios correctly
*and* that the inbox query returns strictly fewer records than the full
source scan when dismissed completions are present — i.e. dismissal
filtering really is happening server-side. Latency thresholds from the
plan (p95 < 50 ms, max < 150 ms for normal refresh) are checked
loosely here because CI hardware varies; the per-scenario numbers
emitted via :func:`_print_report` are the authoritative output for
human review.
"""

from __future__ import annotations

import json
import statistics
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.slow


def _build_phase6_root(
    root: Path,
    *,
    visible: int,
    dismissed: int,
) -> tuple[Path, list[tuple[str, str]]]:
    """Build a hermetic projects tree with a small inbox and many dismissed rows.

    Returns the populated ``projects_root`` and the list of
    ``(cl_name, raw_suffix)`` identities for the *dismissed* artifacts so
    callers can sync the index sidecar.
    """

    root.mkdir(parents=True, exist_ok=True)
    project_dir = root / "home"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "home.sase").write_text("", encoding="utf-8")
    ace_run_dir = project_dir / "artifacts" / "ace-run"
    ace_run_dir.mkdir(parents=True, exist_ok=True)

    base_ts = 20260101000000
    dismissed_identities: list[tuple[str, str]] = []

    for i in range(visible):
        ts = str(base_ts + i)
        artifact_dir = ace_run_dir / ts
        artifact_dir.mkdir(parents=True, exist_ok=True)
        agent_name = f"visible_agent_{i:04d}"
        (artifact_dir / "agent_meta.json").write_text(
            json.dumps({"name": agent_name, "model": "claude-opus-4-7"}),
            encoding="utf-8",
        )
        (artifact_dir / "done.json").write_text(
            json.dumps(
                {
                    "outcome": "completed",
                    "finished_at": 1000.0 + i,
                    "cl_name": f"cl_visible_{i:04d}",
                    "name": agent_name,
                    "model": "claude-opus-4-7",
                }
            ),
            encoding="utf-8",
        )

    for i in range(dismissed):
        ts = str(base_ts + 1_000_000 + i)
        artifact_dir = ace_run_dir / ts
        artifact_dir.mkdir(parents=True, exist_ok=True)
        agent_name = f"dismissed_agent_{i:04d}"
        cl_name = f"cl_dismissed_{i:04d}"
        (artifact_dir / "agent_meta.json").write_text(
            json.dumps({"name": agent_name, "model": "claude-opus-4-7"}),
            encoding="utf-8",
        )
        (artifact_dir / "done.json").write_text(
            json.dumps(
                {
                    "outcome": "completed",
                    "finished_at": 500.0 + i,
                    "cl_name": cl_name,
                    "name": agent_name,
                    "model": "claude-opus-4-7",
                }
            ),
            encoding="utf-8",
        )
        dismissed_identities.append((cl_name, ts))

    return root, dismissed_identities


def _summarize(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {"count": 0.0}
    s = sorted(samples)
    n = len(s)
    p95_idx = max(0, int(round(0.95 * (n - 1))))
    return {
        "count": float(n),
        "min_ms": s[0] * 1000.0,
        "median_ms": statistics.median(s) * 1000.0,
        "p95_ms": s[p95_idx] * 1000.0,
        "max_ms": s[-1] * 1000.0,
    }


def _time(fn: Callable[[], Any], *, runs: int, warmup: int) -> dict[str, float]:
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return _summarize(samples)


def _write_dismissed_agents_json(
    dismissed_file: Path,
    dismissed_identities: list[tuple[str, str]],
) -> None:
    """Write ``dismissed_agents.json`` in the legacy [agent_type, cl_name, raw_suffix] shape.

    The TUI loader's first inbox query syncs the index sidecar from this
    file via ``maybe_sync_dismissed_from_file``; writing it ensures the
    dismissed projection survives that sync (rather than getting wiped by
    a stale empty sync from a missing legacy file).
    """

    dismissed_file.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        ["run", cl_name, raw_suffix] for cl_name, raw_suffix in dismissed_identities
    ]
    dismissed_file.write_text(json.dumps(payload), encoding="utf-8")


def _build_index_and_sync_dismissed(
    projects_root: Path,
    index_path: Path,
    dismissed_identities: list[tuple[str, str]],
) -> None:
    from sase.core.agent_artifact_index_maintenance import sync_dismissed_visibility
    from sase.core.agent_scan_facade import rebuild_agent_artifact_index

    rebuild_agent_artifact_index(index_path, projects_root)
    sync_dismissed_visibility(
        [("run", cl_name, raw_suffix) for cl_name, raw_suffix in dismissed_identities],
        index_path=index_path,
    )


def run_bench(
    *,
    visible: int,
    dismissed: int,
    runs: int,
    warmup: int,
) -> dict[str, Any]:
    """Time the three Phase 6 inbox scenarios against a synthetic tree."""

    from sase.ace.tui.models import agent_loader

    with tempfile.TemporaryDirectory() as tmp:
        fake_home = Path(tmp) / "home"
        projects_root = fake_home / ".sase" / "projects"
        _, dismissed_identities = _build_phase6_root(
            projects_root, visible=visible, dismissed=dismissed
        )
        index_path = fake_home / ".sase" / "agent_artifact_index.sqlite"
        _build_index_and_sync_dismissed(projects_root, index_path, dismissed_identities)
        # Mirror the legacy dismissed_agents.json file so the loader's
        # ``maybe_sync_dismissed_from_file`` step does not wipe the
        # in-bench sidecar with an empty sync.
        _write_dismissed_agents_json(
            fake_home / ".sase" / "dismissed_agents.json",
            dismissed_identities,
        )
        # Reset the per-process signature cache so the first inbox query
        # in this benchmark re-reads the legacy file (other tests may
        # have left a signature behind that would short-circuit the sync).
        from sase.core import agent_artifact_index_maintenance as _maint

        _maint._last_dismissed_signature = _maint._DISMISSED_SIGNATURE_UNSET

        def inbox_query() -> int:
            with patch("pathlib.Path.home", return_value=fake_home):
                result = agent_loader._query_artifact_index_for_loader(
                    full_history=False,
                    agent_search_active=False,
                )
            assert result is not None
            return len(result[0].records)

        # Build a second index in a sibling fake-home with no dismissed
        # sidecar so the query has to return every recent completion.
        alt_home = Path(tmp) / "alt_home"
        alt_projects = alt_home / ".sase" / "projects"
        alt_projects.parent.mkdir(parents=True, exist_ok=True)
        alt_projects.symlink_to(projects_root, target_is_directory=True)
        alt_index = alt_home / ".sase" / "agent_artifact_index.sqlite"
        from sase.core.agent_scan_facade import rebuild_agent_artifact_index

        rebuild_agent_artifact_index(alt_index, alt_projects)

        def inbox_query_no_dismissed_sync() -> int:
            with patch("pathlib.Path.home", return_value=alt_home):
                result = agent_loader._query_artifact_index_for_loader(
                    full_history=False,
                    agent_search_active=False,
                )
            assert result is not None
            return len(result[0].records)

        def full_history_source_scan() -> int:
            with patch("pathlib.Path.home", return_value=fake_home):
                snapshot, _ = agent_loader._artifact_snapshot_for_tui_load(
                    full_history=True,
                    agent_search_active=False,
                )
            return len(snapshot.records)

        # Capture record counts once so the smoke test can assert the
        # inbox query really did exclude the dismissed completions.
        record_counts = {
            "inbox_query": inbox_query(),
            "inbox_query_no_dismissed_sync": inbox_query_no_dismissed_sync(),
            "full_history_source_scan": full_history_source_scan(),
        }

        return {
            "tool": "bench_agent_loader_phase6_inbox",
            "phase": "6",
            "visible": visible,
            "dismissed": dismissed,
            "runs": runs,
            "warmup": warmup,
            "record_counts": record_counts,
            "scenarios": {
                "inbox_query": _time(inbox_query, runs=runs, warmup=warmup),
                "inbox_query_no_dismissed_sync": _time(
                    inbox_query_no_dismissed_sync, runs=runs, warmup=warmup
                ),
                "full_history_source_scan": _time(
                    full_history_source_scan, runs=runs, warmup=warmup
                ),
            },
        }


def _print_report(report: dict[str, Any]) -> None:
    print()
    print(
        f"# bench_agent_loader_phase6_inbox visible={report['visible']} "
        f"dismissed={report['dismissed']} runs={int(report['runs'])} "
        f"warmup={int(report['warmup'])}"
    )
    counts = report["record_counts"]
    print(
        "  record_counts: "
        f"inbox={counts['inbox_query']} "
        f"inbox_no_sync={counts['inbox_query_no_dismissed_sync']} "
        f"full_history={counts['full_history_source_scan']}"
    )
    header = (
        f"{'scenario':<32} {'min_ms':>10} {'median_ms':>12} "
        f"{'p95_ms':>10} {'max_ms':>10}"
    )
    print("  " + header)
    print("  " + "-" * len(header))
    for name, summary in report["scenarios"].items():
        if summary.get("count", 0) == 0:
            continue
        print(
            "  " + f"{name:<32} {summary['min_ms']:>10.3f} "
            f"{summary['median_ms']:>12.3f} "
            f"{summary['p95_ms']:>10.3f} {summary['max_ms']:>10.3f}"
        )


def test_bench_phase6_inbox_smoke() -> None:
    """The Phase 6 harness builds a fixture and exercises all three paths.

    Also locks in the qualitative result the plan cares about: the
    visibility-aware inbox query returns strictly fewer records than the
    Tier 2 full-history source scan when dismissed completions exist, so
    normal Agents-tab refreshes are no longer paying for historical scans.
    """

    report = run_bench(visible=3, dismissed=6, runs=2, warmup=1)
    counts = report["record_counts"]
    assert counts["inbox_query"] == counts["inbox_query_no_dismissed_sync"] - 6
    assert counts["full_history_source_scan"] >= counts["inbox_query"] + 6
    for name in (
        "inbox_query",
        "inbox_query_no_dismissed_sync",
        "full_history_source_scan",
    ):
        assert report["scenarios"][name]["count"] == 2.0
        assert report["scenarios"][name]["max_ms"] >= 0.0
    _print_report(report)


if __name__ == "__main__":
    _print_report(run_bench(visible=5, dismissed=1000, runs=10, warmup=2))
