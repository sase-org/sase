---
date: 2026-05-14
status: research
source_bead: sase-3e
---

# Rust Snapshot Migration Landing Research

## Question

How should we test and fully land the recently implemented Rust snapshot migration, including any remaining Python
fallbacks or feature flags that may be gating it?

## Short Answer

The phrase "Rust snapshot migration" covers three overlapping pieces of work that are at very different stages, and
conflating them is the main risk in this landing:

1. **Core in-process snapshot scan via `sase_core_rs`** — already sealed. `scan_agent_artifacts` calls the Rust binding
   directly through `require_rust_binding`; the Python walker fallback was removed in Phase 8D; no
   `SASE_CORE_BACKEND` / `SASE_CORE_DUAL_RUN` routing remains in production source.
2. **Persistent agent-artifact SQLite index** (`~/.sase/agent_artifact_index.sqlite`) — Rust-owned read/write API is in
   place (`rebuild_/upsert_/delete_/query_/verify_agent_artifact_index`); `verify_agent_artifact_index` performs a
   row-by-row diff against `scan_agent_artifacts`. There is no Python-side reimplementation, so nothing to delete; the
   landing decision here is whether ACE/CLI surfaces consume the index by default or only on demand.
3. **Local daemon indexed projections** (the `sase-3e` legend) — partially landed. M1 CLI/editor reads default-on for
   five surface groups; M2 ACE surfaces are wired but default-off; scheduler launch/lifecycle/axe and most
   provider-host paths default to `direct`. The remaining fallbacks here are **not** equivalent to the old Python
   backend fallback; they are the documented source-store recovery contract for a system where source JSON/JSONL and
   `.gp` files are still authoritative.

Recommended landing path:

- **(1)** No behavioral change. Add a static-audit regression test and call it done.
- **(2)** Decide whether `verify_agent_artifact_index` runs as part of `sase daemon verify` for the agents surface and
  whether ACE consumes the index directly. Either decision is small and orthogonal to the daemon rollout.
- **(3)** Promote surfaces through the registered gate model one group at a time. Do **not** remove
  `SASE_NO_DAEMON=1`, `daemon.reads.force_direct`, or the direct loaders. Removing them is a separate
  source-of-truth migration with its own legend, not part of "sealing" sase-3e.

## Current State

### Piece 1 — Core `sase_core_rs` Snapshot Scan

Relevant files:

- `src/sase/core/agent_scan_facade.py:65` — `scan_agent_artifacts` calls
  `require_rust_binding("scan_agent_artifacts")` directly.
- `src/sase/core/agent_scan_facade.py:1-15` — module docstring states the Rust extension is a hard runtime
  dependency; missing/stale wheel surfaces as `ImportError` / `AttributeError`.
- `tests/test_core_agent_scan_facade.py:106` — comment: "Phase 8D removed the Python walker fallback; the facade now
  always [calls Rust]."
- `docs/rust_backend.md` — documents the post-Phase-8 policy: no pure-Python fallback, no backend env-var selection,
  rollback is a wheel fix.

Static-audit findings:

- `rg "SASE_CORE_BACKEND|SASE_CORE_DUAL_RUN|sase\.core\.backend|RustBackendUnavailable|is_rust_available|dual_run"
  src tests docs README.md Justfile pyproject.toml` — only historical/documentation mentions; no production routing.

Conclusion: sealed. The right test is a guard, not a deletion.

### Piece 2 — Persistent Agent-Artifact SQLite Index

Relevant files:

- `src/sase/core/agent_scan_facade.py:83-237` — `default_agent_artifact_index_path`,
  `rebuild_agent_artifact_index`, `upsert_agent_artifact_index_row`, `delete_agent_artifact_index_row`,
  `query_agent_artifact_index`, `verify_agent_artifact_index`.
- `src/sase/core/agent_scan_wire.py` — `AGENT_ARTIFACT_INDEX_SCHEMA_VERSION` and the
  `AgentArtifactIndexQueryWire` / `AgentArtifactIndexUpdateWire` / `AgentArtifactIndexVerifyWire` shapes.
- Default location: `~/.sase/agent_artifact_index.sqlite`.

Observations:

- `verify_agent_artifact_index` already produces a per-row stale/missing/extra/corrupt diff against
  `scan_agent_artifacts` — this is the natural parity gate for any "snapshot" promotion that uses the index.
- All five mutation entry points already require the Rust binding; there is no Python fallback to remove.
- Callers (ACE providers, agents tab) currently read via `scan_agent_artifacts` rather than `query_agent_artifact_index`
  on the default path, which means the index is built for future consumers but is not yet the load-bearing source for
  the agents surface.

Landing decision for this piece is small and binary: keep the index as a future-consumer artifact, or wire ACE/CLI
agents reads to `query_agent_artifact_index` (and gate that flip with `verify_agent_artifact_index` parity).

### Piece 3 — Local Daemon Indexed Projection Snapshots

Relevant files:

- Legend: `sdd/legends/202605/rust_daemon_indexed_projections_1.md` — status `done`, 11 epics planned.
- Epic 11 closeout: `sdd/epics/202605/rust_daemon_epic11_rollout_controls.md` — status `done`,
  bead `sase-3e.11`.
- Daemon facade: `src/sase/daemon/read_facade.py`, `src/sase/daemon/write_facade.py`.
- Rollout: `src/sase/daemon/rollout_registry.py`, `src/sase/daemon/rollout_gates.py`,
  `src/sase/daemon/read_config.py`, `src/sase/daemon/rollout_diagnostics.py`.
- Defaults: `src/sase/default_config.yml:26-85`.
- ACE providers: `src/sase/ace/tui/data_providers/_daemon.py`,
  `src/sase/ace/tui/data_providers/_daemon_pages.py`,
  `src/sase/ace/tui/actions/changespec/_provider.py`,
  `src/sase/ace/tui/actions/agents/_notification_provider.py`,
  `src/sase/ace/tui/actions/agents/_artifact_provider.py`.

**Read surfaces** (`src/sase/daemon/read_facade.py:30-67`) — 36 surface IDs grouped under five capabilities:
`changespecs.read`, `agents.read`, `notifications.read`, `beads.read`, `catalogs.read`. ACE variants reuse the same
capability but are gated by their own rollout surface ID (`ace_*_reads`).

**Fallback decision points** (`src/sase/daemon/read_facade.py:92-136`):

- `daemon_read_disable_reason(...)` — explicit disablement (no-daemon, force-direct, surface off, args opt-out).
- Capability missing — daemon does not advertise `required_capability`.
- `LocalDaemonError` with a code in `FALLBACKABLE_RPC_CODES` (lines 20-28):
  `cursor_expired`, `projection_degraded`, `snapshot_expired`, `unsupported_capability`,
  `unsupported_client_version`, `payload_too_large`, `resource_not_found`.
- Any other `LocalDaemonError` re-raises rather than silently falling back.

**Write fallback codes** (`src/sase/daemon/write_facade.py:17-25`):
`unsupported_capability`, `unsupported_mutation`, `unsupported_client_version`, `payload_too_large`,
`host_adapter_required`, `daemon_unavailable`, `invalid_request`. Stale-source conflicts intentionally do **not**
fall back — they raise.

**Registered rollout surfaces** (`src/sase/daemon/rollout_registry.py:245-477`):

- Milestones: `milestone.m0_shadow_indexing`, `milestone.m1_read_through`.
- Daemon process: `daemon.process`.
- Reads: `read.global`, `read.fallback_diagnostics`, plus per-surface
  `read.changespecs|notifications|agents|beads|catalogs`, plus ACE
  `read.ace_agents|ace_changespecs|ace_notifications|ace_artifacts|ace_archive_search`.
- Writes: 14 `write.*` surfaces derived from `CAPABILITY_BY_WRITE_SURFACE`.
- Scheduler: `scheduler.launch`, `scheduler.lifecycle`, `scheduler.axe`.
- Provider host: `provider_host.global` plus 8 ops (`llm_metadata`, `xprompt_catalog`, `vcs_query`,
  `workspace_metadata`, `workspace_resolve_ref`, `llm_invoke`, `workflow_step`, `vcs_mutation`).
- Mobile: `mobile_gateway.contract`.
- Recovery: `recovery.projections`.

**Gate kinds** (`src/sase/daemon/rollout_gates.py:16-25`): `CAPABILITY`, `CONTRACT`, `PARITY`, `PERF`, `RECOVERY`,
`DOCS`. A surface cannot flip to default-on without coverage for every kind it declares as required.

**Current defaults** (`src/sase/default_config.yml:26-85`):

```yaml
daemon:
  reads:
    enabled: true
    force_direct: false
    surfaces:
      changespecs: true
      notifications: true
      agents: true
      beads: true
      catalogs: true
      ace_agents: false
      ace_changespecs: false
      ace_notifications: false
      ace_artifacts: false
      ace_archive_search: false
  scheduler:
    launch_mode: "direct"
    lifecycle_mode: "direct"
    axe_mode: "direct"
  provider_host:
    default_mode: "direct"
```

**Environment overrides** actually referenced in `src/`:

- `SASE_NO_DAEMON` — hard off, equivalent to `daemon.reads.enabled: false`
  (`src/sase/daemon/rollout_registry.py:48`, `paths.py:112`, `compatibility.py:21`).
- `SASE_DAEMON_READS` — global reads toggle (`rollout_registry.py:137`, `read_config.py:80`).
- `SASE_DAEMON_FORCE_DIRECT` — keep daemon running, route reads through direct loaders
  (`rollout_registry.py:52,138`, `read_config.py:127`, `rollout_diagnostics.py:477`).
- `SASE_DAEMON_M0_SHADOW_INDEXING`, `SASE_DAEMON_M1_READ_THROUGH` — milestone-level kill switches
  (`rollout_registry.py:255,281`).
- `SASE_DAEMON_<SURFACE>_READS` — per-surface override, generated by `_surface_env_name`
  (`rollout_registry.py:107-109`). Confirmed names: `SASE_DAEMON_CHANGESPECS_READS`,
  `SASE_DAEMON_NOTIFICATIONS_READS`, `SASE_DAEMON_AGENTS_READS`, `SASE_DAEMON_BEADS_READS`,
  `SASE_DAEMON_CATALOGS_READS`, `SASE_DAEMON_ACE_AGENTS_READS`, `SASE_DAEMON_ACE_CHANGESPECS_READS`,
  `SASE_DAEMON_ACE_NOTIFICATIONS_READS`, `SASE_DAEMON_ACE_ARTIFACTS_READS`,
  `SASE_DAEMON_ACE_ARCHIVE_SEARCH_READS`.
- `SASE_DAEMON_SCHEDULER_{LAUNCH,LIFECYCLE,AXE}_MODE`, `SASE_PROVIDER_HOST_MODE`,
  `SASE_PROVIDER_HOST_<OP>_MODE` — mode overrides for non-read surfaces.

## Testing Strategy

### 1. Static Seal Audit

Before changes and again before merge:

```bash
rg "SASE_CORE_BACKEND|SASE_CORE_DUAL_RUN|sase\.core\.backend|RustBackendUnavailable|is_rust_available|dual_run" \
  src tests docs README.md Justfile pyproject.toml
rg "def _.*python|python fallback|walker fallback|dispatch\(" src/sase/core tests
rg "read_or_fallback\(|write_or_fallback\(|SASE_DAEMON_|daemon\.reads\.surfaces" src/sase tests docs
```

Interpretation:

- Any `SASE_CORE_*` hit in `src/` blocks landing of Piece 1.
- `read_or_fallback` / `write_or_fallback` hits are expected for Piece 3. They are the recovery contract, not legacy
  routing. Do not delete them on the basis of the word "fallback".
- For each surface being promoted, identify every direct loader and add a daemon-on test that makes the direct loader
  raise.

### 2. Focused Python Test Set

```bash
.venv/bin/pytest -q \
  tests/test_core_agent_scan_facade.py \
  tests/test_core_agent_scan_options.py \
  tests/test_core_agent_scan_records.py \
  tests/test_core_agent_scan_wire.py \
  tests/test_agent_loader.py \
  tests/test_agent_loader_dedup_pid.py \
  tests/test_running_agents_snapshot.py \
  tests/test_daemon_read_config.py \
  tests/test_daemon_read_facade.py \
  tests/test_daemon_write_facade.py \
  tests/test_daemon_rollout_registry.py \
  tests/test_daemon_rollout_gates.py \
  tests/test_notification_catalog.py \
  tests/test_notification_tui_daemon_provider.py \
  tests/ace/tui/test_agents_data_provider.py \
  tests/ace/tui/test_changespec_daemon_provider.py \
  tests/perf/test_daemon_read_rollout.py \
  tests/perf/test_ace_ui_virtualization_rollout.py
```

What each cluster proves:

- Core scan tests — Rust binding is the only scan path; missing wheel raises loudly.
- Agent loader / running snapshot tests — Python consumers of the Rust scan wire still decode correctly.
- Daemon read/write facade tests — capability checks, fallback metadata, stale-source refusal, no-daemon path.
- Rollout registry / gate tests — no surface can default-on without registered parity/perf/recovery coverage; ACE M2
  defaults stay opt-in unless their gates exist.
- ACE provider tests — patch direct JSONL/source loaders and assert no fallback when daemon is healthy.

### 3. Sibling Rust Core / Gateway Tests

Shared backend behavior lives in `../sase-core`. Run when the landing decision touches daemon wire contracts,
projections, gateway capabilities, or PyO3 bindings:

```bash
cd ../sase-core
cargo fmt --all -- --check
PYO3_PYTHON=/usr/bin/python3.13 cargo clippy --workspace --all-targets -- -D warnings
PYO3_PYTHON=/usr/bin/python3.13 cargo test --workspace
cargo run -p sase_gateway -- \
  --local-daemon-contract-out crates/sase_gateway/contracts/local_daemon/v1/local_daemon_v1.json
git diff -- crates/sase_gateway/contracts/local_daemon/v1/local_daemon_v1.json
```

Contract snapshot diffs are API changes; review, do not accept mechanically.

### 4. Daemon Integration Soak

For daemon surfaces, exercise both modes against the same fixture corpus. The full subcommand surface
(`src/sase/main/daemon_handler.py:38-52`) is: `start`, `stop`, `status`, `rollout`, `scheduler`, `doctor`,
`rebuild`, `checkpoint`, `backup`, `list-backups`, `restore`, `verify`, `diff`.

```bash
just install
sase core health
sase daemon stop || true
sase daemon start
sase daemon status --json
sase daemon doctor --json          # rolls up gate coverage and disable reasons
sase daemon rollout --json         # per-surface eligibility report
sase daemon rebuild --surface all --json
sase daemon verify --surface all --json
sase daemon diff --surface all --limit 100 --json
sase daemon checkpoint
```

For Piece 2 specifically, also run:

```bash
.venv/bin/python -c '
from pathlib import Path
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path, rebuild_agent_artifact_index, verify_agent_artifact_index,
)
root = Path.home() / ".sase" / "projects"
idx = default_agent_artifact_index_path()
print(rebuild_agent_artifact_index(idx, root))
print(verify_agent_artifact_index(idx, root))
'
```

The `ok=True` result with `stale_rows=0, missing_rows=0, extra_rows=0, corrupt_rows=0` is the parity precondition for
wiring ACE/CLI agents reads to `query_agent_artifact_index`.

Daemon-vs-direct comparison for representative reads:

```bash
sase changespec search 'status:ready' --json
SASE_DAEMON_FORCE_DIRECT=1 sase changespec search 'status:ready' --json

sase notify list --json
SASE_DAEMON_FORCE_DIRECT=1 sase notify list --json

sase bead list --json
SASE_DAEMON_FORCE_DIRECT=1 sase bead list --json

sase agents status --json
SASE_DAEMON_FORCE_DIRECT=1 sase agents status --json
```

For ACE M2 promotion, run with each candidate surface explicitly enabled:

```bash
SASE_DAEMON_ACE_NOTIFICATIONS_READS=1 sase ace
SASE_DAEMON_ACE_CHANGESPECS_READS=1 sase ace
SASE_DAEMON_ACE_ARTIFACTS_READS=1 sase ace
SASE_DAEMON_ACE_AGENTS_READS=1 sase ace
SASE_DAEMON_ACE_ARCHIVE_SEARCH_READS=1 sase ace
```

Manual checks for ACE: first indexed snapshot time, `j`/`k` responsiveness, no-change refresh behavior, lazy detail
loading, projection-degraded fallback UX, and whether provider metadata reports `source=daemon` rather than
`direct_fallback`.

### 5. Performance Gates

Existing baselines (`tests/perf/baselines/`):

- `phase7_regression_floor.json` — floor for core Rust scan regression.
- `rust_daemon_epic1_current.json` — Epic 1 daemon round-trip floors.

```bash
just phase7-perf-check
just launch-perf-check
just scheduler-rollout-perf-check
.venv/bin/pytest -q tests/perf/test_daemon_read_rollout.py tests/perf/test_ace_ui_virtualization_rollout.py
.venv/bin/python -m tests.perf.bench_rust_daemon_epic1 \
  --runs 5 \
  --output tests/perf/baselines/rust_daemon_epic1_current.json
```

For a real user-history soak, collect non-committed reports:

```bash
.venv/bin/python tests/perf/bench_agent_scan.py --runs 5 --include-home --output /tmp/agent_scan_home.json
.venv/bin/python tests/perf/bench_notification_store.py --runs 5 --output /tmp/notification_store.json
.venv/bin/python tests/perf/bench_bead.py --runs 5 --output /tmp/bead_perf.json
```

Do **not** commit real-home perf output as a baseline. Baselines must be deterministic fixtures.

## Landing Recommendation

### Piece 1 — Core Rust snapshot scan

No behavioral changes. Closeout:

- Keep `scan_agent_artifacts` as a direct Rust binding.
- Keep tests asserting missing/stale wheels fail loudly.
- Keep historical doc references to `SASE_CORE_BACKEND` only as migration history.
- Run `just check`, plus the sibling Rust workspace tests if the PyO3 surface changed.

### Piece 2 — Persistent agent-artifact SQLite index

Pick one of:

- **(a) No-op landing.** Leave the index built but unused on the default ACE/CLI path. Document
  `verify_agent_artifact_index` as a debugging tool. Lowest risk.
- **(b) Read-promotion landing.** Wire one or both of:
  - ACE agents archive provider (`src/sase/ace/tui/actions/agents/_artifact_provider.py`) to
    `query_agent_artifact_index` for the archive/full-history path.
  - `sase agents status` to `query_agent_artifact_index` for the active/recent path.
  Gate the flip behind a parity test that runs `verify_agent_artifact_index` against a fixture corpus and refuses to
  pass with any non-zero stale/missing/extra/corrupt count, plus a perf microbench showing the index path is at least
  as fast as `scan_agent_artifacts` on real-home sized inputs.

Recommendation: **(a)** for the current landing; promote in a follow-up legend so the index promotion has its own
parity/perf gate, separate from daemon work.

### Piece 3 — Daemon-backed projection snapshots

Land per surface, not globally:

1. Pick a surface group (M1 already default-on; M2 candidates next).
2. Add a regression test that enables the surface and makes the direct loader raise; the test passes only if the daemon
   path supplies the data.
3. Run `sase daemon rebuild/verify/diff` on the fixture corpus and on a throwaway `SASE_HOME` populated from a real
   user history snapshot.
4. Run the registered perf gate for that surface.
5. Update `src/sase/default_config.yml` and `src/sase/daemon/rollout_registry.py` together when changing a default.
6. Update tests that intentionally assert the surface is opt-in (ACE M2 default policy tests in particular).
7. **Keep** `SASE_NO_DAEMON=1`, `SASE_DAEMON_FORCE_DIRECT=1`, and direct source loaders. Removing them requires an
   explicit source-of-truth migration (a different legend), because today the source JSONL/`.gp`/artifact files are
   still authoritative and projections are rebuildable host-local state.

First default-flip candidate among M2: `ace_notifications`. Existing tests in
`tests/test_notification_tui_daemon_provider.py` already assert no JSONL snapshot read on daemon-backed count/modal
paths, so the parity story is the most complete. Highest-risk: `ace_agents` and `ace_archive_search`, because they
affect navigation, history depth, artifact associations, and no-change refresh behavior.

## Exit Criteria

**Piece 1 (core snapshot scan):**

- `rg "SASE_CORE_BACKEND|SASE_CORE_DUAL_RUN|sase\.core\.backend|RustBackendUnavailable|is_rust_available|dual_run"
  src` returns nothing.
- `tests/test_core_agent_scan_facade.py` passes.
- `sase core health` passes in the installed environment.
- `just check` passes.

**Piece 2 (artifact index), if promoting:**

- `verify_agent_artifact_index` returns `ok=True` on the fixture corpus.
- `verify_agent_artifact_index` returns `ok=True` on a throwaway-home clone of a real user history.
- Microbench for the promoted call path is within the perf budget of the equivalent
  `scan_agent_artifacts`-based call.
- ACE provider test asserts `query_agent_artifact_index` is the load-bearing call on the default path.

**Piece 3, per surface promoted to default-on:**

- `rollout_registry` and `default_config.yml` agree on the new default.
- `default_gate_violations(...)` reports no violations for the surface.
- A daemon-enabled test fails if the direct loader is invoked.
- A forced-direct test (`SASE_DAEMON_FORCE_DIRECT=1` or `daemon.reads.force_direct: true`) still passes and exposes
  stable fallback metadata via `DaemonReadResult.debug_json()`.
- `sase daemon rebuild`, `verify`, and `diff` are clean on the fixture corpus.
- The relevant `PARITY`, `PERF`, and `RECOVERY` gates report covered.
- User docs name the rollback switch and recovery command.

## Risks & Open Questions

- **Vocabulary risk.** "Rust snapshot migration" is ambiguous across the three pieces above. Naming the target piece
  in the CL/PR title avoids accidental scope (e.g. someone deleting `SASE_NO_DAEMON` while landing Piece 1).
- **Stale-source semantics.** `write_or_fallback` refuses to fall back on stale-source conflicts. Promoting any
  default-on write surface must include a UI/CLI message for that refusal; otherwise users see an opaque error.
- **Recovery vs. legacy.** `recovery.projections` is itself a registered rollout surface. Removing direct loaders
  would also remove the recovery path it depends on. Treat any "delete direct fallback" PR as touching recovery.
- **Real-home perf vs. fixtures.** Baselines under `tests/perf/baselines/` are deterministic fixtures, not real-home
  numbers. A surface that passes the fixture perf gate can still be slower on a large user history; capture a
  real-home soak as a non-committed artifact before each ACE M2 default flip.
- **Index vs. daemon overlap.** If both Piece 2 and Piece 3's `agents` surface become load-bearing for ACE, the agents
  archive could read from the SQLite index, the daemon, or `scan_agent_artifacts`. Decide which is the canonical
  source for ACE archive reads before promoting either; otherwise three sources can disagree under projection
  degradation.

## Decision

Do not delete daemon direct fallbacks as part of this landing. Do not delete `SASE_NO_DAEMON`,
`SASE_DAEMON_FORCE_DIRECT`, or `daemon.reads.force_direct`. Delete only obsolete core-backend fallback code if a new
static audit finds any in production source; current audit found none. For Piece 3, "seal the deal" means promoting
target surfaces from opt-in to default-on after their registered gates pass, while preserving the direct-source
recovery contract until projections become authoritative via a separate, explicit migration.
