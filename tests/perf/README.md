# Performance Recipes

## Plugins Catalog Scale

Measure the Updates > Plugins sub-tab (and the shared fetch/enrich paths behind it) at
10 / 250 / 1000 / 2000 synthetic catalog entries:

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
pytest -s -m slow tests/perf/bench_artifacts_first_paint.py
```

Prints a p50/p95/max table per pane per phase and asserts only structural invariants (no
tight wall-clock budgets, per `tests/ace/tui/bench_admin_center_open.py`'s style) —
including whether each pane's first paint already short-circuits past the full query
index. Pair with the repaired `bench_agent_catalog.py` (see below) when investigating
Agent pane regressions, since both fixtures share the same synthetic registry corpus.

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
