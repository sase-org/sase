# Performance Recipes

## Plugins Catalog Scale

Measure the Updates tab's Plugins rows (and the shared fetch/enrich paths behind them)
at 10 / 250 / 1000 / 2000 synthetic catalog entries:

```bash
just bench-plugin-catalog-scale
```

That runs the slow pytest benches. They print p50/p95/max tables and enforce the
fetch/enrich _operation-count_ curves (page count, O(installed) eager PyPI fetches, and
an enrich catalog walk that stays linear in `n` instead of rescanning the catalog once
per fetched miss) plus filter-keystroke and j-press p95 under 16 ms at n=2000.
`just plugin-catalog-scale-check` is the CI regression floor: live enrich/fetch/
truncation gates plus the committed TUI p95 ceilings in
`tests/perf/baselines/plugin_catalog_scale_baseline.json`. The filter fixture holds the
match count at 100 rows (10 at n=10) so the keystroke curve does not invert with catalog
size.

```bash
just plugin-catalog-scale-check
pytest -s -m slow tests/ace/tui/bench_plugins_catalog_scale.py
pytest -s -m slow tests/perf/bench_plugin_catalog_scale.py
python -m tests.perf.bench_plugin_catalog_scale --write-baseline
SASE_PLUGIN_CATALOG_SCALE_WRITE_BASELINE=1 pytest -s -m slow \
    tests/ace/tui/bench_plugins_catalog_scale.py
```

## Admin Center First Paint

Measure `#` dispatch through the painted, home-first SASE Admin Center under both empty
and populated config/project fixtures:

```bash
pytest -s -m slow tests/ace/tui/bench_admin_center_open.py
```

The benchmark prints p50/p95/max tables and asserts only structural invariants (zero
concrete panes and no fixture-scaled home work), not a flaky wall-clock budget. Compare
the reported rows from the same machine and checkout.

## Artifacts Sub-Tab First Paint

Measure, per Artifacts sub-tab (Agent, Bead, Plan, File), the split between
snapshot-load, query-index build, and what a default `limit:100` blank-query view
actually costs today, over a live-scale synthetic corpus:

```bash
just install
.venv/bin/python -m pytest -s -m slow tests/perf/bench_artifacts_first_paint.py
```

Prints a p50/p95/max table per pane per phase and asserts only structural invariants (no
tight wall-clock budgets, per `tests/ace/tui/bench_admin_center_open.py`'s style) —
including whether each pane's first paint already short-circuits past the full query
index. Pair with the repaired `bench_agent_catalog.py` (see below) when investigating
Agent pane regressions, since both fixtures share the same synthetic registry corpus.

The corpus shape is live-scale synthetic data matching the `sase-tt` baseline: 12,525
agent registry names, 4,346 beads, 1,900 archived plan files, and 8,099 file rows. The
Agent fixture also writes a real synthetic artifact tree and dismissed summaries so
registry revalidation and owner-existence checks stay represented.

Certified on 2026-08-25 from this checkout:

| Pane  | Corpus | Baseline first paint |    Target | Measured first-paint p50 | Measured first-paint p95 | p50 vs target | p95 vs target |
| ----- | -----: | -------------------: | --------: | -----------------------: | -----------------------: | ------------- | ------------- |
| Agent | 12,525 |            ~3,100 ms | <= 400 ms |                171.22 ms |                311.65 ms | met           | met           |
| Bead  |  4,346 |            ~2,500 ms | <= 700 ms |                631.20 ms |                786.34 ms | met           | over          |
| Plan  |  1,900 |            ~2,500 ms | <= 400 ms |                239.33 ms |                449.52 ms | met           | over          |
| File  |  8,099 |              ~800 ms | <= 500 ms |                 39.75 ms |                 41.63 ms | met           | met           |

The `sase-tt` targets are median targets: every pane met its target at p50, and Bead and
Plan sit above it at p95 on a five-sample run. Judge a change by p50 against the numbers
above and treat a p95 move as a signal to re-run with more samples, not as a gate. The
epic accepted the p95 spread rather than chasing it, because Bead's floor is three Rust
bead reads and Plan's is a bounded archived-plan scan.

The 2026-08-25 land re-run of the same bench measured Agent 169.30 ms p50 / 298.75 ms
p95, Bead 661.78 / 704.10, Plan 202.43 / 364.32, and File 31.21 / 32.56 -- same picture,
and the run-to-run spread on Bead and Plan is itself worth about 10% of the target.

The same verification run reported Agent background query-index build p95 1,427.12 ms,
inside the epic's "available within ~1.5s after first paint" target. Re-run the repaired
agent catalog bench with:

```bash
.venv/bin/python -m pytest -s -m slow tests/perf/bench_agent_catalog.py
```

On 2026-08-25 it passed both variants: real-source median 157.82 ms and no-real-source
median 149.44 ms over the 12,525-name synthetic registry.

Artifact-link aggregates are already loaded on the Agent snapshot path through
`load_artifact_links_snapshot(project)`, but the pane benchmark does not break that cost
out. Record it separately when changing relation or artifact-link facets:

```bash
.venv/bin/python - <<'PY'
import statistics
import time

from sase.ace.tui.relations.artifact_links import _CACHE, load_artifact_links_snapshot

runs = []
row_count = 0
errors = 0
for index in range(7):
    _CACHE.clear()
    start = time.perf_counter()
    snapshot = load_artifact_links_snapshot(None)
    elapsed = (time.perf_counter() - start) * 1000
    if index > 0:
        runs.append(elapsed)
    row_count = len(snapshot.rows)
    errors = len(snapshot.errors)

print(f"artifact_links rows={row_count} errors={errors}")
print(
    "cold_load_ms "
    f"count={len(runs)} median={statistics.median(runs):.2f} "
    f"p95={sorted(runs)[round(0.95 * (len(runs) - 1))]:.2f} max={max(runs):.2f}"
)
start = time.perf_counter()
snapshot = load_artifact_links_snapshot(None)
print(f"cache_hit_ms={(time.perf_counter() - start) * 1000:.4f} rows={len(snapshot.rows)}")
PY
```

On 2026-08-25, this machine's aggregate held 185 rows with zero errors; cold load median
was 6.38 ms, p95 6.54 ms, and max 6.54 ms. The immediate cache-hit probe measured 4.8130
ms for the same 185 rows. This is the baseline to re-check when artifact-link facet
joins are added to `agent_catalog_query_entry`.

## Agent Artifact Startup

Use this recipe when changing `sase ace` startup loading, dismissed archive queries,
revive, run-log loading, or artifact-index rebuilds.

Capture cold-process timings from a checkout with the same `HOME` and artifact tree the
user normally runs:

```bash
just install
.venv/bin/python - <<'PY'
import time

from sase.ace.tui.actions.agents._loading_helpers import load_agents_from_disk_with_state
from sase.ace.dismissed_agents import load_dismissed_agents, load_dismissed_bundles
from sase.ace.tui.modals.agent_run_log_modal import _load_agents_for_cl

def timed(label, fn):
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    size = len(result) if hasattr(result, "__len__") else "n/a"
    print(f"{label}: {elapsed:.3f}s ({size})")
    return result

dismissed = timed("load_dismissed_agents", load_dismissed_agents)
timed("load_agents_from_disk_with_state", lambda: load_agents_from_disk_with_state(dismissed))
timed("load_dismissed_bundles(all)", load_dismissed_bundles)
timed("run_log_open(sample)", lambda: _load_agents_for_cl("replace_with_cl_name"))
PY
```

For revive modal checks, run the same process and time
`load_dismissed_bundles({raw_suffix})` for a parent workflow suffix with known
`__c{idx}` child bundles. For index work, capture full rebuild wall time and a second
query immediately after rebuild so the cold rebuild and warm lookup costs are visible
separately.
