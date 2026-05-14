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

There are two related migrations, and they should be treated differently:

1. The older `sase_core_rs` snapshot scan migration is already sealed. `scan_agent_artifacts` calls the Rust binding
   directly through `require_rust_binding`, the Python walker fallback is gone, and production source has no
   `SASE_CORE_BACKEND` / `SASE_CORE_DUAL_RUN` switch left.
2. The newer daemon/indexed-projection snapshot migration from the `sase-3e` legend is not the same kind of migration.
   It intentionally keeps direct source-store fallback and rollout flags because source JSON/JSONL/project/artifact
   files are still authoritative recovery surfaces. Fully landing this path should mean promoting specific read
   surfaces through the rollout gate model, not deleting `SASE_NO_DAEMON`, `daemon.reads.force_direct`, or direct
   loaders wholesale.

The best landing path is therefore:

- For the core Rust snapshot scan: run the hard-dependency/static audit and normal checks; no fallback removal appears
  necessary.
- For daemon-backed snapshots: choose the target surfaces, require daemon-capable tests to fail if they touch direct
  loaders, run shadow/diff/rebuild and perf gates, then flip defaults per surface. Keep direct-source fallback as a
  recovery and no-daemon path until a separate source-of-truth migration makes projections authoritative.

## Current State

### Core `sase_core_rs` Snapshot Scan

Relevant files:

- `src/sase/core/agent_scan_facade.py`
- `tests/test_core_agent_scan_facade.py`
- `docs/rust_backend.md`
- `sdd/research/202604/rust_backend_migration.md`

Findings:

- `scan_agent_artifacts` calls `sase_core_rs.scan_agent_artifacts` directly via
  `sase.core.rust.require_rust_binding`.
- `tests/test_core_agent_scan_facade.py` explicitly documents that Phase 8D removed the Python walker fallback and
  asserts that missing/stale Rust wheels raise `ImportError` / `AttributeError`.
- `rg "SASE_CORE_BACKEND|SASE_CORE_DUAL_RUN|sase\\.core\\.backend|RustBackendUnavailable|is_rust_available|dual_run"
  src tests docs README.md Justfile pyproject.toml` only found historical/documentation mentions, not production
  routing.
- `docs/rust_backend.md` states the post-Phase-8 policy: no pure-Python fallback, no backend env-var selection, and a
  package/wheel fix rather than an env-var rollback.

Conclusion: this migration is already fully landed from a source-routing perspective. The right test is to guard that it
stays landed, not to delete more production code.

### Daemon/Indexed Projection Snapshots

Relevant files:

- `sdd/legends/202605/rust_daemon_indexed_projections_1.md`
- `sdd/epics/202605/rust_daemon_epic11_rollout_controls.md`
- `src/sase/daemon/read_facade.py`
- `src/sase/daemon/write_facade.py`
- `src/sase/daemon/read_config.py`
- `src/sase/daemon/rollout_registry.py`
- `src/sase/daemon/rollout_gates.py`
- `src/sase/default_config.yml`
- `src/sase/ace/tui/data_providers/_daemon.py`
- `src/sase/ace/tui/actions/changespec/_provider.py`
- `src/sase/ace/tui/actions/agents/_notification_provider.py`
- `src/sase/ace/tui/actions/agents/_artifact_provider.py`

Findings:

- M1 daemon read-through is default-enabled for `changespecs`, `notifications`, `agents`, `beads`, and `catalogs`.
- M2 ACE daemon surfaces are present but default-off: `ace_agents`, `ace_changespecs`, `ace_notifications`,
  `ace_artifacts`, and `ace_archive_search`.
- `read_or_fallback` still falls back on explicit disablement, unavailable daemon, missing capabilities, cursor/snapshot
  expiry, projection degradation, and compatible transport/RPC errors.
- `write_or_fallback` still falls back for unsupported/fallbackable daemon write errors, but correctly refuses direct
  fallback for stale-source conflicts.
- `rollout_registry` models default policy and default enablement, and the tests intentionally block ungated ACE default
  enablement.
- `src/sase/default_config.yml` keeps scheduler launch/lifecycle/axe modes as `direct`; low-risk provider-host metadata
  paths are `host-preferred`; mutation-heavy provider paths remain `direct`.
- `docs/configuration.md`, `docs/rust_backend.md`, and `docs/local_daemon.md` describe source stores as authoritative
  and daemon runtime/projection files as rebuildable host-local state.

Conclusion: daemon direct fallbacks are not equivalent to the old Python backend fallback. They are part of the current
source-store compatibility and recovery contract.

## Testing Strategy

### 1. Static Seal Audit

Use this before making code changes and again before landing:

```bash
rg "SASE_CORE_BACKEND|SASE_CORE_DUAL_RUN|sase\\.core\\.backend|RustBackendUnavailable|is_rust_available|dual_run" \
  src tests docs README.md Justfile pyproject.toml
rg "def _.*python|python fallback|walker fallback|dispatch\\(" src/sase/core tests
rg "read_or_fallback\\(|write_or_fallback\\(|SASE_DAEMON_|daemon\\.reads\\.surfaces" src/sase tests docs
```

Interpretation:

- Any `SASE_CORE_*` production hit in `src/` should block landing.
- `read_or_fallback` / `write_or_fallback` hits are expected for daemon rollout. Do not remove them solely because they
  contain the word "fallback".
- For the target daemon surfaces, identify every direct loader and add/keep tests that prove it is not called when the
  daemon is enabled, healthy, and advertises the required capability.

### 2. Focused Python Test Set

Run these focused tests before the full suite:

```bash
.venv/bin/pytest -q \
  tests/test_core_agent_scan_facade.py \
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

Why these matter:

- Core scan tests prove the Rust binding is the only scan implementation.
- Agent loader/snapshot tests cover Python consumers of Rust scan snapshots.
- Daemon read/write facade tests cover capability checks, fallback metadata, stale conflict behavior, and no-daemon
  routing.
- Rollout registry/gate tests prevent default enablement without registered parity/perf/recovery coverage.
- ACE provider tests already patch direct JSONL/source loaders in places and should be expanded for any surface being
  promoted.

### 3. Sibling Rust Core/Gateway Tests

Because shared backend behavior lives in `../sase-core`, run the Rust checks when the landing decision touches daemon
wire contracts, projections, gateway capabilities, or PyO3 bindings:

```bash
cd ../sase-core
cargo fmt --all -- --check
PYO3_PYTHON=/usr/bin/python3.13 cargo clippy --workspace --all-targets -- -D warnings
PYO3_PYTHON=/usr/bin/python3.13 cargo test --workspace
cargo run -p sase_gateway -- \
  --local-daemon-contract-out crates/sase_gateway/contracts/local_daemon/v1/local_daemon_v1.json
git diff -- crates/sase_gateway/contracts/local_daemon/v1/local_daemon_v1.json
```

Contract snapshot diffs should be reviewed as API changes, not accepted mechanically.

### 4. Daemon Integration Soak

For daemon surfaces, add a hermetic or throwaway `SASE_HOME` integration run that exercises both daemon and direct modes
against the same fixture source stores:

```bash
just install
sase core health
sase daemon stop || true
sase daemon start
sase daemon status --json
sase daemon rebuild --surface all --json
sase daemon verify --surface all --json
sase daemon diff --surface all --limit 100 --json
```

Then compare representative commands in daemon mode and forced direct mode:

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

For ACE M2 promotion, run with each candidate ACE surface explicitly enabled first:

```bash
SASE_DAEMON_ACE_AGENTS_READS=1 sase ace
SASE_DAEMON_ACE_CHANGESPECS_READS=1 sase ace
SASE_DAEMON_ACE_NOTIFICATIONS_READS=1 sase ace
SASE_DAEMON_ACE_ARTIFACTS_READS=1 sase ace
SASE_DAEMON_ACE_ARCHIVE_SEARCH_READS=1 sase ace
```

Manual checks should focus on first indexed snapshot time, `j`/`k` responsiveness, no-change refresh behavior, lazy
detail loading, projection-degraded fallback UX, and whether provider metadata reports `source=daemon` rather than
`direct_fallback`.

### 5. Performance Gates

Recommended perf gates before flipping daemon snapshot defaults:

```bash
just phase7-perf-check
just launch-perf-check
just scheduler-rollout-perf-check
.venv/bin/pytest -q tests/perf/test_daemon_read_rollout.py tests/perf/test_ace_ui_virtualization_rollout.py
.venv/bin/python -m tests.perf.bench_rust_daemon_epic1 \
  --runs 5 \
  --output tests/perf/baselines/rust_daemon_epic1_current.json
```

For a real user-history soak, collect non-committed reports with:

```bash
.venv/bin/python tests/perf/bench_agent_scan.py --runs 5 --include-home --output /tmp/agent_scan_home.json
.venv/bin/python tests/perf/bench_notification_store.py --runs 5 --output /tmp/notification_store.json
.venv/bin/python tests/perf/bench_bead.py --runs 5 --output /tmp/bead_perf.json
```

Do not use real-home perf output as committed baselines unless it has been normalized into a deterministic fixture.

## Landing Recommendation

### If the target is only the core Rust snapshot scan

Do not make behavioral changes. It is already landed. The closeout should be:

- Keep `scan_agent_artifacts` as a direct Rust binding.
- Keep tests that assert missing/stale wheels fail loudly.
- Keep historical docs references to `SASE_CORE_BACKEND` only where they describe the migration history.
- Run `just check` plus Rust workspace tests if the PyO3 surface changed.

### If the target is daemon-backed projection snapshots

Land per surface, not globally:

1. Pick the surface group: M1 CLI/editor group or one M2 ACE group.
2. Add a regression test that enables that surface and makes the direct loader raise. The test should pass only if the
   daemon path supplies the data.
3. Verify `sase daemon rebuild/verify/diff` is clean on the fixture corpus and a real-history soak.
4. Verify perf gates for that surface.
5. Update `src/sase/default_config.yml` and `src/sase/daemon/rollout_registry.py` together if changing a default.
6. Update tests that intentionally assert the surface is opt-in, such as ACE M2 default policy tests.
7. Keep `SASE_NO_DAEMON=1`, `SASE_DAEMON_FORCE_DIRECT=1`, and direct source loaders unless the source-of-truth model is
   explicitly changed in a later plan.

The first likely default-flip candidates are the already-default M1 groups. For ACE, `ace_notifications` is a good first
M2 candidate because the existing tests already assert no JSONL snapshot read in daemon-backed count/modal paths. The
highest-risk ACE groups are `ace_agents` and `ace_archive_search`, because they affect navigation, history depth,
artifact associations, and no-change refresh behavior.

## Exit Criteria

For core snapshot scan:

- `rg "SASE_CORE_BACKEND|SASE_CORE_DUAL_RUN|sase\\.core\\.backend|RustBackendUnavailable|is_rust_available|dual_run" src`
  returns nothing.
- `tests/test_core_agent_scan_facade.py` passes.
- `sase core health` passes in the installed environment.
- `just check` passes.

For each daemon snapshot surface promoted to default:

- Rollout registry and default config agree.
- `default_gate_violations(...)` has no violations for the promoted surface.
- Daemon-enabled tests fail if the direct loader is called.
- Forced-direct tests still pass and expose stable fallback metadata.
- `sase daemon rebuild`, `verify`, and `diff` are clean on fixture data.
- The relevant parity, perf, and recovery gates pass.
- User docs name the rollback switch and recovery command.

## Decision

Do not delete daemon direct fallbacks as part of this landing. Delete only obsolete core-backend fallback code if a new
static audit finds any, and current research found none in production source. For daemon snapshots, "seal the deal"
should mean turning target surfaces from opt-in to default-on after gates pass, while preserving direct-source recovery
until projections become the authoritative store by a separate, explicit migration.
