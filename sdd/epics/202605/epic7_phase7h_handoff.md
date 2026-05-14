---
create_time: 2026-05-14
bead_id: sase-3e.7.8
---
# Epic 7 Phase 7H Handoff

Phase 7H added the rollout gate layer for daemon scheduler enablement.

Changed surfaces:

- `sase daemon status` and `sase daemon doctor` now surface scheduler health from daemon RPC details: queue depth,
  active/running/starting counts, stale starts, host bridge availability, and scheduler projection lag.
- `sase daemon scheduler status --project <id> --batch <batch>` prints a batch and per-slot state.
- `sase daemon scheduler cancel --project <id> --batch <batch> [--slot <slot>]` provides an idempotent operator recovery
  path for stuck queued, starting, running, or stale host-bridge tasks.
- `../sase-core` now exports a scheduler health summary and Prometheus metrics for scheduler submit/status/cancel
  latency plus startup recovery repairs.
- `tests/perf/daemon_scheduler_rollout.py` records the Epic 7 scheduler rollout budget names and target p95s.

Flags and fallback:

- Launch routing remains controlled by `daemon.scheduler.launch_mode` / `SASE_DAEMON_SCHEDULER_LAUNCH_MODE`.
- Lifecycle routing remains controlled by `daemon.scheduler.lifecycle_mode` /
  `SASE_DAEMON_SCHEDULER_LIFECYCLE_MODE`.
- Axe routing remains controlled by `daemon.scheduler.axe_mode` / `SASE_DAEMON_SCHEDULER_AXE_MODE`.
- `--no-daemon` and `SASE_NO_DAEMON=1` remain the direct-mode escape hatch.

Verification:

- Python tests cover scheduler doctor output, parser recovery commands, client status/cancel payloads, and rollout gate
  names.
- Rust tests cover scheduler health counts and projection lag after queued/running transitions.
