---
create_time: 2026-05-14 03:20:00
bead_id: sase-3e.7.7
---
# Phase 7G Handoff - Lifecycle Scheduler Mutations

Implemented a Python lifecycle scheduler facade that submits kill, dismiss,
cleanup, revive, and bulk lifecycle targets to the daemon scheduler queue as
`agent_lifecycle` tasks. The rollout flag is
`daemon.scheduler.lifecycle_mode` or `SASE_DAEMON_SCHEDULER_LIFECYCLE_MODE`,
with default `direct` and `shadow`/`daemon` modes preserving direct fallback.

Changed files:

- `src/sase/daemon/lifecycle_scheduler.py`
- `src/sase/default_config.yml`
- `src/sase/agent/running.py`
- `src/sase/ace/tui/actions/agents/_dismiss_persistence.py`
- `src/sase/ace/tui/actions/agents/_dismissing.py`
- `src/sase/ace/tui/actions/agents/_kill_persistence.py`
- `src/sase/ace/tui/actions/agents/_revive.py`
- `tests/test_daemon_lifecycle_scheduler.py`

Remaining risk: daemon host execution for lifecycle tasks is still an
incremental rollout path. In `shadow`/`daemon` modes, existing Python side
effects remain authoritative while the scheduler receives durable per-target
queue events and idempotency keys.
