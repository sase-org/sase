# Performance Recipes

## Agent Artifact Startup

Use this recipe when changing `sase ace` startup loading, dismissed archive queries, revive, run-log loading, or
artifact-index rebuilds.

Capture cold-process timings from a checkout with the same `HOME` and artifact tree the user normally runs:

```bash
just install
.venv/bin/python - <<'PY'
import time

from sase.ace.tui.actions.agents._loading_helpers import load_agents_from_disk
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
timed("load_agents_from_disk", lambda: load_agents_from_disk(dismissed))
timed("load_dismissed_bundles(all)", load_dismissed_bundles)
timed("run_log_open(sample)", lambda: _load_agents_for_cl("replace_with_cl_name"))
PY
```

For revive modal checks, run the same process and time `load_dismissed_bundles({raw_suffix})` for a parent workflow
suffix with known `__c{idx}` child bundles. For index work, capture full rebuild wall time and a second query
immediately after rebuild so the cold rebuild and warm lookup costs are visible separately.
