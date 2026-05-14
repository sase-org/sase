# Performance Recipes

## Rust Daemon Epic 1 Baselines

Use this recipe when changing cold CLI startup, local daemon client framing, ACE hot paths, agent launch preparation, or
notification-action latency for the Rust daemon/indexed-projection rebuild.

The Epic 1 command-level and mocked warm-daemon harness is hermetic by default: it creates a temporary
`HOME`/`SASE_HOME`, copies the `tests/fixtures/rust_daemon_epic1/` ChangeSpec, notification, history, and bead fixtures
into that home/workspace, and never starts or routes through a real daemon.

Regenerate the advisory baseline JSON:

```bash
just install
.venv/bin/python -m tests.perf.bench_rust_daemon_epic1 \
  --runs 5 \
  --output tests/perf/baselines/rust_daemon_epic1_current.json
```

The JSON includes `p50_ms` and `p95_ms` summaries for:

- cold subprocess startup: plain Python, importing `sase.main.entry`, and `sase --help`;
- command-level direct reads: `changespec search`, `notify list/show`, `bead list/show/ready`, and editor xprompt
  catalog helper;
- mocked warm-daemon request framing: local JSON serialization, health, paged-list, and delta/event payload round trips.

To intentionally benchmark real local state instead of the fixture corpus, add `--real-home`. Do not use that flag for
committed baselines.

Related harnesses for Epic 1 traceability:

```bash
.venv/bin/python -m tests.perf.bench_tui_trace \
  --output tests/perf/baselines/rust_daemon_epic1_ace.json
.venv/bin/python tests/perf/bench_agent_launch.py \
  --runs 5 \
  --output tests/perf/baselines/rust_daemon_epic1_agent_launch.json
.venv/bin/python tests/perf/bench_notification_store.py \
  --runs 5 \
  --output tests/perf/baselines/rust_daemon_epic1_notifications.json
```

Epic 1 thresholds are advisory only. The daemon targets recorded in the JSON are the aspirational later-epic targets
from the plan: warm daemon-backed CLI/editor reads at roughly 5-30 ms, ACE shell first useful paint under 100 ms, active
indexed data under 250 ms on large local histories, and no-change refresh near 0 ms once event-driven paths exist.

The Phase 1E readiness review at `sdd/research/202605/rust_daemon_epic1_readiness.md` maps these baselines to fixture
families, normalized snapshots, local daemon contract surfaces, and later daemon epics.

## ACE Daemon Read Rollout

Use this recipe before enabling any `ace_*` daemon read surface in `src/sase/default_config.yml`.

```bash
just install
just ace-daemon-read-perf-smoke --runs 5
sase daemon rollout --benchmark-report sdd/tales/202605/perf_artifacts/ace_daemon_reads_smoke.json --json
```

The report compares direct and daemon-backed ACE startup slices for agents, ChangeSpecs, and notification first
page/count reads. Its `perf_gates` object only passes a surface when daemon p95 is below direct p95 and below the
absolute M2 budget. The rollout diagnostics payload also surfaces request count, fallback reason, and circuit state for
the daemon scenarios.

## Agent Artifact Startup

Use this recipe when changing `sase ace` startup loading, dismissed archive queries, revive, run-log loading, or
artifact-index rebuilds.

Capture cold-process timings from a checkout with the same `HOME` and artifact tree the user normally runs:

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

For revive modal checks, run the same process and time `load_dismissed_bundles({raw_suffix})` for a parent workflow
suffix with known `__c{idx}` child bundles. For index work, capture full rebuild wall time and a second query
immediately after rebuild so the cold rebuild and warm lookup costs are visible separately.
