"""Benchmark for the catalog phase (sase-tj.2) of the Artifacts Agent pane epic.

Measures :func:`sase.agents.catalog.build_agent_catalog_snapshot` against a
synthetic registry sized to the epic plan's measured reference point:
12,525 registry names (``plan:202608/artifacts_agents_pane.md`` §2.4).

Two of the pipeline's four steps are pre-existing, already-optimized
infrastructure this phase does not own: :func:`sase.agent.names.load_name_registry`
and the dismissed-bundle-archive facade. Faithfully reproducing the
dismissed archive's own on-disk index at this scale (thousands of real
bundle JSON files, then a real rebuild pass) is expensive setup unrelated
to what this phase changed, so the dismissed-archive loaders are
dependency-injected with pre-built :class:`DismissedBundleSummary`
objects instead. The registry (via a real ``agent_name_registry.json``
write, so :func:`load_name_registry`'s real staleness/parse path runs) and
the artifact index (via a real, schema-matching ``agent_artifact_index.sqlite``,
so :mod:`sase.agents.catalog._sources`'s own projected-SQL reader runs) are
both exercised for real. This still measures every line this phase wrote:
``_sources.py``'s artifact-index reader, ``_family.py``, ``_derive.py``,
and ``_build.py``'s join/derivation loop, plus the real registry loader
whose cost dominates the budget.

``with_real_sources`` (see :func:`build_synthetic_catalog_sources`) controls
whether claimed-leaf entries carry a real ``source`` plus a real, on-disk
``artifacts_dir``/``bundle_path`` the way production entries always do.
Originally this fixture *always* omitted ``source`` and ran under an
isolated ``SASE_HOME`` with no artifact tree at all, so neither
:func:`sase.agent.names._registry_entries.entry_owner_missing` nor
:func:`sase.agent.names._registry_scan.source_signature_paths` had anything
real to touch. That hid the two costs that dominate the live Agent pane
load — 905ms of 1,529ms, see
``plan:202608/artifacts_query_performance.md`` §1.2/§1.4 — behind a fixture
that measured a 273ms build of a corpus whose real-world equivalent takes
1,529ms. ``with_real_sources=True`` (the default, and the primary
parametrization of :func:`test_bench_agent_catalog_budget`) repairs that:
every claimed-leaf entry gets ``"source": "artifact"`` plus a real artifact
directory (flat ``ace-run/<suffix>`` layout, written directly with
``mkdir``/``write_text`` rather than through
``tests._agent_names_fixtures``'s helpers, since those go through the Rust
``canonical_agent_artifact_path`` binding once per call — unnecessary
overhead at 12,525 calls), and roughly 5% of entries instead get
``"source": "dismissed_bundle"`` plus a real dismissed-bundle JSON file
under ``<SASE_HOME>/dismissed_bundles/<shard>/<raw_suffix>.json``, matching
:func:`sase.agent.names._registry_scan_payloads.bundle_owner`'s real shape.
``with_real_sources=False`` keeps the original fixture behavior byte-for-byte
as a second parametrization, so the split between raw parse cost and
revalidation cost stays visible (``plan`` §3).

Run with ``pytest -s -m slow tests/perf/bench_agent_catalog.py`` or
directly as ``python -m tests.perf.bench_agent_catalog``.
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from sase.ace.dismissed_bundle_index import DismissedBundleSummary
from sase.agent.names._registry_store import (
    registry_data,
    registry_path,
    write_registry,
)
from sase.agents.catalog import _build as catalog_build
from sase.agents.catalog import _sources as catalog_sources
from sase.agents.catalog import build_agent_catalog_snapshot
from sase.core.agent_scan_facade import default_agent_artifact_index_path
from sase.core.agent_scan_wire import AGENT_ARTIFACT_INDEX_SCHEMA_VERSION
from sase.core.paths import sase_projects_dir, sase_subdir

pytestmark = pytest.mark.slow

# Pre-fix baseline observed against the repaired (``with_real_sources=True``)
# fixture on the author's machine: median 328ms, max 507ms over 5 runs
# against 12,525 registry names / ~10,646 real artifact dirs / ~626 real
# dismissed-bundle files (~11,273 signature-scan paths total) — versus 176ms
# median for the ``with_real_sources=False`` variant's fast path, so the
# revalidation cost this repair restores is real and roughly doubles the
# build. This is deliberately *not* a tight gate: this phase (``bench``) only
# has to prove the fixture is now honest, not fix the cost it now reveals.
# Post-fix baseline (``registry`` phase's freshness memo from
# ``plan:202608/artifacts_query_performance.md`` §4, which lets
# ``load_name_registry()`` skip the full revalidation sweep on repeated
# calls): median 158-169ms, max 202ms over two 5-run samples on the author's
# machine. The budget below is ~2.75x the observed max to absorb host/CI
# variance, matching the pre-fix budget's margin.
_BUDGET_MS = 550.0
_REFERENCE_REGISTRY_SIZE = 12525
# ~1/20 (5%) of entries get a ``dismissed_bundle`` source instead of an
# ``artifact`` source + real artifacts_dir, matching production's mix of
# claimed names whose backing artifact directory was reclaimed but whose
# dismissed-bundle archive still exists.
_DISMISSED_BUNDLE_SOURCE_BUCKET = 2

_PROJECTS = ("gh_sase-org__sase", "gh_bobs-org__bob-cli", "home")
_MODELS = ("claude-opus-5", "claude-sonnet-5", "gpt-5.6-sol")
_PROVIDERS = ("claude", "codex", "grok")
_STATUSES = ("DONE", "FAILED", "WAITING", "RUNNING")


def _write_synthetic_registry(entries: dict[str, dict[str, Any]]) -> None:
    write_registry(registry_path(), registry_data(entries))


def _write_synthetic_artifact_index(rows: list[dict[str, Any]]) -> None:
    path = default_agent_artifact_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = catalog_sources._ARTIFACT_INDEX_COLUMNS
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute(
            "INSERT INTO meta VALUES ('schema_version', ?)",
            (str(AGENT_ARTIFACT_INDEX_SCHEMA_VERSION),),
        )
        connection.execute(f"CREATE TABLE agent_artifacts ({', '.join(columns)})")
        placeholders = ", ".join("?" for _ in columns)
        connection.executemany(
            f"INSERT INTO agent_artifacts VALUES ({placeholders})",
            [tuple(row.get(c) for c in columns) for row in rows],
        )
        connection.commit()
    finally:
        connection.close()


def _write_real_artifact_dir(project: str, raw_suffix: str) -> str:
    """Write a minimal, real, flat ``ace-run/<suffix>`` artifact directory.

    Deliberately plain ``mkdir``/``write_text`` rather than
    ``tests._agent_names_fixtures.make_agent`` or
    ``canonical_agent_artifact_path``: both go through the Rust path-layout
    binding once per call, which is needless overhead at 12,525 calls for a
    fixture whose only requirement is that the directory *exists* (for
    :func:`entry_owner_missing`) and is discoverable by
    ``iter_agent_artifact_dirs``'s own walk (for
    :func:`source_signature_paths`) — the flat legacy layout satisfies both
    with one directory per entry.
    """
    artifact_dir = sase_projects_dir() / project / "artifacts" / "ace-run" / raw_suffix
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "agent_meta.json").write_text("{}", encoding="utf-8")
    return str(artifact_dir)


def _write_real_dismissed_bundle_file(raw_suffix: str) -> str:
    """Write a minimal, real dismissed-bundle JSON file for one raw suffix.

    Matches :func:`sase.agent.names._registry_scan_payloads.bundle_owner`'s
    on-disk shape (``<SASE_HOME>/dismissed_bundles/<shard>/<suffix>.json``),
    which both :func:`entry_owner_missing` (``Path(bundle_path).is_file()``)
    and :func:`source_signature_paths` (its ``dismissed_bundles`` shard walk)
    need to see for real.
    """
    shard = raw_suffix[:6]
    bundle_path = sase_subdir("dismissed_bundles") / shard / f"{raw_suffix}.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text("{}", encoding="utf-8")
    return str(bundle_path)


def build_synthetic_catalog_sources(
    registry_size: int,
    *,
    with_real_sources: bool = True,
) -> tuple[
    dict[str, dict[str, Any]], list[dict[str, Any]], list[DismissedBundleSummary]
]:
    """Build a registry-shaped, index-shaped, and archive-shaped synthetic corpus.

    Distribution mirrors the plan's measured live-machine shape: ~14%
    family containers, ~5% clan containers, the rest claimed leaf names
    (half family members, half plain agents), ~65% artifact-index
    enrichment, ~55% of dismissed leaves getting a top-level archive match.

    When ``with_real_sources`` is true (the default), every claimed-leaf
    entry gets a real ``source`` the way production entries always do:
    ~95% ``"artifact"`` with a real, on-disk ``artifacts_dir``, and ~5%
    ``"dismissed_bundle"`` with a real, on-disk ``bundle_path`` — so
    :func:`sase.agent.names._registry_entries.entry_owner_missing` and
    :func:`sase.agent.names._registry_scan.source_signature_paths` do the
    real filesystem work production pays on every registry load (see module
    docstring). When false, entries omit ``source`` entirely and
    ``artifacts_dir``/``bundle_path`` stay synthetic, non-existent paths —
    the original fixture shape, kept so the split between raw parse cost and
    revalidation cost stays visible as a second parametrization.
    """
    entries: dict[str, dict[str, Any]] = {}
    index_rows: list[dict[str, Any]] = []
    dismissed_summaries: list[DismissedBundleSummary] = []

    for i in range(registry_size):
        project = _PROJECTS[i % len(_PROJECTS)]
        bucket = i % 20
        if bucket == 0:
            name = f"fam{i:06d}"
            entries[name] = {
                "name": name,
                "container_kind": "family",
                "reservation_kind": "family",
                "state": "dismissed" if i % 3 else "active",
                "project_name": project,
                "canonical_global_name": f"bench.athena.{name}",
                "raw_suffix": f"{20260101000000 + i}",
            }
            continue
        if bucket == 1:
            name = f"clan{i:06d}.gen"
            entries[name] = {
                "name": name,
                "container_kind": "clan",
                "reservation_kind": "clan",
                "state": "dismissed",
                "project_name": project,
                "canonical_global_name": f"bench.athena.{name}",
                "raw_suffix": f"{20260101000000 + i}",
            }
            continue

        base = f"agent{i:06d}"
        name = f"{base}--code" if bucket % 2 == 0 else base
        raw_suffix = f"{20260101000000 + i}"
        state = ("dismissed", "done", "active")[i % 3]
        is_dismissed_bundle_only = (
            with_real_sources and bucket == _DISMISSED_BUNDLE_SOURCE_BUCKET
        )
        if is_dismissed_bundle_only:
            # ~5% of entries: the backing artifact directory was reclaimed,
            # so only a dismissed-bundle archive still proves ownership.
            state = "dismissed"
            artifacts_dir: str | None = None
            bundle_path = _write_real_dismissed_bundle_file(raw_suffix)
        elif with_real_sources:
            artifacts_dir = _write_real_artifact_dir(project, raw_suffix)
            bundle_path = None
        else:
            artifacts_dir = f"/synthetic/{project}/artifacts/ace-run/{raw_suffix}"
            bundle_path = None
        entries[name] = {
            "name": name,
            "reservation_kind": "claimed",
            "state": state,
            "project_name": project,
            "canonical_global_name": f"bench.athena.{name}",
            "raw_suffix": raw_suffix,
            "collision_owners": [{"name": name}] if i % 37 == 0 else [],
        }
        if is_dismissed_bundle_only:
            entries[name]["source"] = "dismissed_bundle"
            entries[name]["bundle_path"] = bundle_path
        else:
            entries[name]["artifacts_dir"] = artifacts_dir
            if with_real_sources:
                entries[name]["source"] = "artifact"

        if artifacts_dir is not None and i % 3 == 0:  # ~65% get index enrichment
            index_rows.append(
                {
                    "artifact_dir": artifacts_dir,
                    "project_name": project,
                    "workflow_name": f"wf_{i % 5}" if i % 4 == 0 else None,
                    "agent_type": "workflow" if i % 4 == 0 else "agent",
                    "cl_name": project if i % 2 == 0 else f"bench_patch_{i % 97}",
                    "model": _MODELS[i % len(_MODELS)],
                    "llm_provider": _PROVIDERS[i % len(_PROVIDERS)],
                    "status": _STATUSES[i % len(_STATUSES)],
                    "workflow_status": None,
                    "hidden": i % 5 == 0,
                    "started_at": "2026-08-01T00:00:00Z",
                    "finished_at": float(1000 + i),
                    "retry_attempt": i % 3,
                    "agent_clan": f"clan{i % 200:06d}.gen" if i % 11 == 0 else None,
                    "clan_tribe": ("epic", "chop", "research")[i % 3]
                    if i % 11 == 0
                    else None,
                    "parent_timestamp": None,
                    "retry_of_timestamp": None,
                    "retried_as_timestamp": None,
                    "retry_chain_root_timestamp": None,
                }
            )

        if state == "dismissed" and i % 5 < 3:  # ~55% of dismissed leaves
            dismissed_summaries.append(
                DismissedBundleSummary(
                    raw_suffix=raw_suffix,
                    bundle_path=f"/synthetic/dismissed_bundles/{raw_suffix}.json",
                    shard="202608",
                    filename=f"{raw_suffix}.json",
                    agent_type="workflow" if i % 4 == 0 else "agent",
                    cl_name=project,
                    agent_name=name,
                    status=_STATUSES[i % len(_STATUSES)],
                    start_time="2026-08-01T00:00:00",
                    stop_time="2026-08-01T00:05:00",
                    project_file=f"/synthetic/{project}/{project}.sase",
                    model=_MODELS[i % len(_MODELS)],
                    llm_provider=_PROVIDERS[i % len(_PROVIDERS)],
                    vcs_provider="github",
                    workflow=None,
                    is_workflow_child=False,
                    parent_timestamp=None,
                    step_index=None,
                    step_name=None,
                    retry_of_timestamp=None,
                    retried_as_timestamp=None,
                    retry_chain_root_timestamp=None,
                    retry_attempt=i % 3,
                    meta_changespec=f"bench_patch_{i % 97}" if i % 6 == 0 else None,
                )
            )

    return entries, index_rows, dismissed_summaries


def _time_calls(runs: int, warmup: int) -> dict[str, float]:
    for _ in range(warmup):
        build_agent_catalog_snapshot()
    samples: list[float] = []
    for _ in range(runs):
        start = time.perf_counter()
        build_agent_catalog_snapshot()
        samples.append(time.perf_counter() - start)
    values = sorted(v * 1000.0 for v in samples)
    return {
        "count": float(len(values)),
        "min_ms": values[0],
        "median_ms": statistics.median(values),
        "max_ms": values[-1],
    }


def run_bench(
    *,
    registry_size: int,
    runs: int,
    warmup: int,
    monkeypatch: pytest.MonkeyPatch,
    with_real_sources: bool = True,
) -> dict[str, Any]:
    entries, index_rows, dismissed_summaries = build_synthetic_catalog_sources(
        registry_size, with_real_sources=with_real_sources
    )
    _write_synthetic_registry(entries)
    _write_synthetic_artifact_index(index_rows)

    # _build.py imports these by name, so the patch target is _build's own
    # module namespace, not _sources's — patching _sources here would leave
    # _build's already-bound reference untouched and silently no-op.
    monkeypatch.setattr(
        catalog_build, "load_dismissed_top_level", lambda: dismissed_summaries
    )
    monkeypatch.setattr(
        catalog_build, "load_dismissed_child_fallback", lambda _suffixes: {}
    )

    timings = _time_calls(runs=runs, warmup=warmup)
    snapshot = build_agent_catalog_snapshot()
    return {
        "registry_size": registry_size,
        "with_real_sources": with_real_sources,
        "artifact_index_rows": len(index_rows),
        "dismissed_top_level_rows": len(dismissed_summaries),
        "row_count": len(snapshot.rows),
        "enriched_ratio": snapshot.enriched_ratio,
        "timings_ms": timings,
    }


@pytest.mark.parametrize("with_real_sources", [True, False])
def test_bench_agent_catalog_budget(
    monkeypatch: pytest.MonkeyPatch,
    with_real_sources: bool,
) -> None:
    """Catalog snapshot builds within the pre-``registry``-fix baseline.

    ``with_real_sources=True`` is the honest measurement this phase exists to
    restore (see module docstring): it pays the real
    ``entry_owner_missing``/``source_signature_paths`` revalidation cost, so
    its budget is generous — it is the number the ``registry`` phase has to
    beat, not a tight regression gate. ``with_real_sources=False`` keeps the
    original fast-path fixture (no ``source``, no on-disk artifact tree) so
    the split between raw parse cost and revalidation cost stays visible: it
    should stay comfortably under the real-sources timing.
    """
    report = run_bench(
        registry_size=_REFERENCE_REGISTRY_SIZE,
        runs=5,
        warmup=1,
        monkeypatch=monkeypatch,
        with_real_sources=with_real_sources,
    )
    print(report)
    median_ms = report["timings_ms"]["median_ms"]
    budget = _BUDGET_MS if with_real_sources else 400.0
    assert median_ms <= budget, (
        f"catalog build took {median_ms:.1f}ms over {_REFERENCE_REGISTRY_SIZE} "
        f"registry names (budget {budget:.0f}ms, with_real_sources={with_real_sources})"
    )
    assert report["row_count"] == _REFERENCE_REGISTRY_SIZE
    if with_real_sources:
        # A loose sanity check that enrichment actually joined something, not
        # a fidelity claim against the plan's measured 91.6% live-machine
        # ratio; tests/test_agent_catalog.py covers per-fixture derivation
        # precisely.
        assert report["enriched_ratio"] > 0.25


def _argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--registry-size", type=int, default=_REFERENCE_REGISTRY_SIZE)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument(
        "--no-real-sources",
        dest="with_real_sources",
        action="store_false",
        default=True,
        help="use the original fast-path fixture (no source, no artifact tree)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    import tempfile

    args = _argparser().parse_args(argv)
    with (
        pytest.MonkeyPatch.context() as monkeypatch,
        tempfile.TemporaryDirectory() as tmp,
    ):
        monkeypatch.setenv("SASE_HOME", str(Path(tmp) / ".sase"))
        report = run_bench(
            registry_size=args.registry_size,
            runs=args.runs,
            warmup=args.warmup,
            monkeypatch=monkeypatch,
            with_real_sources=args.with_real_sources,
        )
    print(report)
    median_ms = report["timings_ms"]["median_ms"]
    budget = _BUDGET_MS if args.with_real_sources else 400.0
    print(f"median={median_ms:.1f}ms budget={budget:.0f}ms")
    return 0 if median_ms <= budget else 1


if __name__ == "__main__":
    sys.exit(main())
