# sase-3e No-Daemon Value Review

Date: 2026-05-14 (revised same day to add per-command probe-overhead analysis, M0–M5 rollout phase
definitions with default enablement, daemon-only command inventory, cross-repo Rust impact, an irreversibility
analysis, test-coverage notes, and an expanded direct-mode config inventory)
Bead: `sase-3e`
Legend: `sdd/legends/202605/rust_daemon_indexed_projections_1.md`

## Question

Should the `sase-3e` legend work be reverted because the user does not run `sase daemon` and does not plan to?

## Short Answer

No, not as a blanket conclusion.

The assumption is partly right: if `sase daemon` is never running, the main runtime wins from `sase-3e` are dormant.
Warm projection reads, daemon-owned scheduler queues, provider-host routing through the daemon, projection rebuild and
diff workflows, and mobile HTTP serving do not provide their intended performance/operational value without a running
daemon.

But the broader assumption that the work is pointless is not supported by the current codebase. The legend also added a
large amount of compatibility scaffolding, direct fallback behavior, rollback controls, tests, diagnostics, docs, and
source-store preservation rules. Those pieces matter specifically for no-daemon operation because they prevent the
daemon migration from making normal SASE workflows require a daemon.

## Current Bead State

`sase bead show sase-3e` reports the legend as closed, with 11 closed child epics:

- Epic 1: baseline, contracts, and compatibility inventory
- Epic 2: event model and projection storage core
- Epic 3: daemon runtime, ownership, and local transport
- Epic 4: shadow indexers and file watch ownership
- Epic 5: daemon-backed read APIs for CLI, editor, and ACE
- Epic 6: transactional writes
- Epic 7: daemon scheduler, agent lifecycle, and durable workflow execution
- Epic 8: plugin and provider host isolation
- Epic 9: incremental ACE and UI data virtualization
- Epic 10: multi-machine sync, recovery, and operations
- Epic 11: release sequencing and rollout controls

The linked legend plan explicitly required existing Python commands to keep working during migration through shadow
mode, direct fallback paths, and compatibility adapters.

## Evidence

### Source Stores Remain Authoritative

`docs/local_daemon.md` states that project files, notifications, pending actions, artifacts, chats, beads, repo
metadata, and workflow state remain source-store state under `SASE_HOME`. The daemon stores rebuildable runtime state
under host-local `run_root`, such as `~/.sase/run/<host>/`.

This matters because no-daemon operation is not supposed to lose the authoritative data model. The daemon projections
are caches/views, not the only source of truth.

### Read Paths Fall Back Directly

`src/sase/daemon/read_facade.py` implements `read_or_fallback(...)`. It checks daemon disablement and capabilities, then
falls back to the direct loader on fallbackable daemon transport/RPC errors.

The tests include `test_read_or_fallback_uses_direct_loader_when_daemon_unavailable`, which verifies a missing daemon
socket returns the direct result with fallback reason `daemon_not_running`.

Surfaces wired through this facade include agents, notifications, ChangeSpecs, beads, editor/catalog helpers, and ACE
providers.

### Write Paths Fall Back Directly Where Safe

`src/sase/daemon/write_facade.py` implements `write_or_fallback(...)`. It checks `--no-daemon` / `SASE_NO_DAEMON`,
daemon capabilities, and fallbackable errors before choosing either daemon write-through or the direct writer.

The tests verify direct fallback for unsupported mutations and capability misses. They also deliberately avoid direct
fallback for stale source conflicts, which is the right conservative behavior because blindly writing around a stale
projection/source conflict could hide data loss.

### Scheduler Defaults Are Daemon-Preferred But Opportunistic

`src/sase/default_config.yml` defaults scheduler launch, lifecycle, and axe routing to `daemon`. However,
`src/sase/agent/launch_executor_scheduler.py` catches `LocalDaemonError` and returns `None`, which lets the existing
direct launch path continue.

`src/sase/axe/scheduler_tasks.py` similarly returns a non-submitted outcome when scheduler routing is disabled or the
daemon call fails, allowing direct execution paths to remain available.

This means the defaults may incur a daemon-probe cost, but they are not a hard requirement for ordinary launches.

### Provider Host Routing Is Host-Preferred, Not Host-Required

`src/sase/host/routing.py` defaults provider-host modes to `host-preferred` for low-risk operations and configured
daemon provider-host operations. That mode is designed to use the daemon host-call path when available and fall back
direct when unavailable.

The immediate rollback controls are `SASE_PROVIDER_HOST_MODE=direct`,
`SASE_DISABLE_PROVIDER_HOST_ROUTING=1`, and the broader `SASE_NO_DAEMON=1`.

### Live Local Check Confirms No Daemon Requirement For Beads

On 2026-05-14, `sase daemon status --json` reported daemon state `stale`, with message `metadata pid 380537 is not
live`.

With `SASE_NO_DAEMON=1`, `sase bead show sase-3e` still rendered the legend and children from the direct bead store.
That is a concrete no-daemon proof for the bead path.

### Daemon Probe Overhead Is Paid Per Command, Uncached

`src/sase/daemon/client.py` connects to the Unix socket on each call. The default RPC timeout is 1.0s for most
operations and 5.0s for recovery commands (`rebuild`, `verify`, `diff`). There is no in-process or on-disk cache of a
"daemon not running" verdict, and `retryable=True` on transport errors is used only for error reporting, not to
short-circuit subsequent calls within the same process.

For a user who never runs the daemon, this means:

- Each daemon-probing CLI invocation (`sase agents list`, `sase notify ...`, `sase bead show`, `sase changespec ...`)
  pays a socket-connect attempt that fails fast with `ENOENT`/`ECONNREFUSED` rather than the full 1.0s timeout — so
  the typical per-call cost is small, not seconds. But it is not zero, and it happens for every read surface enabled
  in the default config.
- Workflows that fan out many CLI invocations (scripts, mobile bridges, CI) accumulate this cost linearly.
- Surfaces that wait on the full timeout (network-mounted socket paths, hung daemons, partial sockets) can stall.

This is the strongest concrete argument for explicitly opting out via `SASE_NO_DAEMON=1` instead of relying on
fallback-on-error, even if the legend itself is not reverted. A latency micro-benchmark is the right follow-up
research; the file paths to baseline are `src/sase/daemon/client.py:74` (default timeout), `:372–390` (connect),
and `:450–493` (recovery RPCs).

### Rollout Phases M0–M5 and Their Default Enablement

`src/sase/daemon/rollout_gates.py` defines six milestones. Default enablement comes from `src/sase/default_config.yml`.

| Phase | Owner Epic | Scope | Default |
|---|---|---|---|
| M0 | Epic 1 | Shadow indexing, `rebuild`/`verify`/`diff` diagnostics | `m0_shadow_indexing: true` |
| M1 | Epic 5 | CLI/editor daemon reads (agents, notifications, changespecs, beads) | `m1_read_through: true`; per-surface read switches all on |
| M2 | Epic 9 | ACE daemon reads (ace_agents, ace_changespecs, ace_notifications, ace_artifacts) | on by per-surface read flags |
| M3 | Epic 3 (write) | Selected daemon writes with source export | gated; daemon must be capable |
| M4 | Epic 7 | Daemon-owned scheduler / workflow state | `launch_mode: daemon`, `lifecycle_mode: daemon`, `axe_mode: daemon` |
| M5 | Epic 8 | Provider/plugin/workflow host fallback posture | `provider_host.default_mode: host-preferred` |

Each phase has a corresponding rollback knob (env var or config flag). The rollout-gates module exists specifically so
that operators can pin a surface to direct mode regardless of daemon capability.

### Daemon-Only Surfaces With No Direct Equivalent

Most user-facing commands have a direct fallback. The exceptions, useful to enumerate explicitly:

- `sase mobile gateway start` (`src/sase/integrations/mobile_gateway.py:200–202`, `main/mobile_handler.py:23–27`)
  launches the Rust gateway binary directly; there is no direct-mode mobile bridge. If you never run the daemon,
  mobile HTTP serving is simply unavailable — this is intentional (the gateway *is* the daemon).
- `sase daemon rebuild` / `verify` / `diff` (`src/sase/daemon/client.py:450–493`) raise
  `LocalDaemonUnavailableError` rather than falling back, but they are diagnostics/recovery for the daemon itself, so
  this is by design.
- Write paths for daemon-owned conflict resolution refuse to fall back on stale-source conflicts (correctly — see
  earlier write-facade evidence).

Outside those, no ordinary user command was found that requires the daemon.

### Cross-Repo Rust Impact

The sibling `../sase-core` crates split daemon-side from shared parsing code:

- `sase_gateway` (daemon and contracts: `crates/sase_gateway/src/daemon.rs`,
  `crates/sase_gateway/contracts/local_daemon/v1/local_daemon_v1.json`) is dormant without the daemon.
- `sase_core` provides bead codecs, project-file parsing, query parsing, and notification-store reads used through
  `sase_core_rs` bindings (`src/sase/core/rust.py`). These are called directly from Python in no-daemon mode and are
  not part of the dormant set. Reverting `sase-3e` would not unbind the Python from `sase_core_rs`.

### No Irreversible Source-Store Changes

The legend deliberately preserved source-store formats. Concretely:

- No schema migrations to bead JSONL, ChangeSpec `.gp`, notifications, agents, artifacts, or chats.
- Projection databases live only under host-local `run_root` (`~/.sase/run/<host>/`) and are rebuildable.
- No previously-direct loader was deleted; daemon-capable code paths sit above existing loaders.

This means a future revert (or selective revert of M-phase defaults) does not face data-migration risk; it is purely
a code change.

### Test Coverage Of No-Daemon Mode

No-daemon paths are exercised primarily by injecting transport errors, not by running with `SASE_NO_DAEMON=1` end-to-end:

- `tests/test_daemon_read_facade.py::test_read_or_fallback_uses_direct_loader_when_daemon_unavailable` covers the
  missing-socket case for reads.
- `tests/test_changespec_daemon_reads.py` covers ChangeSpec direct fallback.
- `tests/test_daemon_client_core.py` covers socket errors and timeouts.
- `tests/test_daemon_rollout_diagnostics.py` covers rollout gate evaluation.

Gaps worth noting:

- No CLI-integration test runs the full command surface with `SASE_NO_DAEMON=1` set in the environment.
- No latency benchmark for the per-command probe cost identified above.
- Scheduler `launch_executor_scheduler.py` fallback (returns `None` on `LocalDaemonError`) is implicit; no test
  directly asserts that direct launch proceeds when the daemon socket is missing.

These are coverage gaps for a no-daemon-default user, not implementation bugs.

### Rollout Diagnostics Report Blocked Surfaces, Not Broken Direct Mode

`sase daemon rollout --json` reported daemon capabilities and compatibility as unavailable because the daemon is not
running/stale. The rollout surfaces were marked blocked for daemon use, and most listed fallback commands such as
`SASE_NO_DAEMON=1`, `SASE_DAEMON_M1_READ_THROUGH=0`, or direct provider-host modes.

That is consistent with a design where daemon-backed acceleration is unavailable, while direct operation remains the
recovery mode.

## What Is Dormant Without `sase daemon`

If the daemon is never started, these `sase-3e` outputs mostly do not deliver their intended runtime value:

- Warm SQLite projection reads for CLI/editor/ACE.
- Shadow indexing, `verify`, `diff`, and full backfill through a running daemon.
- Daemon write-through event/outbox behavior.
- Daemon scheduler queues for launches, lifecycle operations, workflows, and axe tasks.
- Provider-host isolation through daemon `host_call`.
- Mobile HTTP serving from the local daemon.
- Projection backup/checkpoint/list-backups through live daemon RPC.
- Most M0-M5 rollout gates that require live capabilities.

Some recovery commands remain useful in a limited offline form, such as stopped/stale `rebuild --reset-storage` and
offline projection restore, but projection maintenance is naturally less important if the daemon is not part of the
workflow.

## What Still Has Value Without `sase daemon`

The non-daemon value is mostly defensive and architectural:

- Direct fallback keeps existing commands working while daemon-capable paths exist in the code.
- `SASE_NO_DAEMON=1`, `--no-daemon`, `SASE_DAEMON_FORCE_DIRECT`, per-surface read switches, direct scheduler modes, and
  direct provider-host modes give explicit no-daemon controls.
- Compatibility inventories and fixtures document current behavior across ChangeSpecs, agents, notifications, beads,
  workflows, catalogs, artifacts, mobile state, editor helpers, and axe inputs.
- Tests now encode that unavailable daemon reads/writes fall back where safe.
- Docs clarify that source stores are authoritative and host-local runtime/projection files are disposable/excludable.
- Rollout diagnostics make it visible when daemon-backed surfaces are blocked instead of silently assuming they work.
- ACE/data-provider abstractions and paged/lazy interfaces can still be useful as architecture cleanup, even when the
  direct loader is the selected backend.

## Revert Risk

Reverting all work associated with `sase-3e` would be broad and high-risk. The legend touched config, docs, CLI routing,
read/write facades, provider-host routing, scheduler fallback, daemon lifecycle commands, tests, fixtures, perf gates,
and sibling Rust daemon contracts.

The most likely bad outcome from a blanket revert is not just "remove unused daemon code"; it is accidentally removing
the no-daemon fallback guarantees that make current default-on daemon-capable configuration tolerable.

If the real goal is "I never want normal commands to try the daemon", a smaller change is safer. A complete direct-mode
config override looks like:

```yaml
daemon:
  reads:
    force_direct: true            # short-circuits every M1/M2 read surface
  scheduler:
    launch_mode: "direct"         # agent launches stay in Python
    lifecycle_mode: "direct"      # agent lifecycle ops stay in Python
    axe_mode: "direct"            # axe tasks run direct
  provider_host:
    default_mode: "direct"        # or set per-operation modes to "direct"
```

Plus, for belt-and-suspenders, `SASE_NO_DAEMON=1` in the shell environment. That env var is checked early in the
read/write facades and bypasses the daemon probe entirely, which also addresses the per-command socket-probe cost
identified above.

A product-level alternative is to change bundled defaults from daemon-preferred to direct-preferred while leaving the
implementation and tests intact. That would avoid daemon probes for users who opt out without discarding the work, and
it is reversible per release.

## Recommendation

Do not revert all of `sase-3e` solely because you do not run `sase daemon`.

Treat the daemon runtime benefits as unused in your workflow, but keep the fallback, diagnostics, docs, and tests unless
there is concrete evidence that they slow down, complicate, or break direct-mode SASE. If no-daemon operation is the
desired default, prefer a focused direct-mode/defaults change over a legend-wide revert.

The strongest follow-up research would be a no-daemon latency audit: run representative commands with current defaults
versus `SASE_NO_DAEMON=1` and measure whether the per-call socket-probe cost in `src/sase/daemon/client.py` adds
enough overhead to justify changing bundled defaults. If it does, the lowest-risk product change is a default flip on
`daemon.reads.force_direct` and the scheduler/provider-host modes, not a code revert.

## Blast Radius Summary

Per-epic commits from `sase bead show sase-3e.N` are concentrated in `src/sase/daemon/`, `src/sase/agents/daemon_reads.py`,
`src/sase/ace/` provider layers, `src/sase/host/`, `default_config.yml`, `docs/local_daemon.md`, and tests. The
read/write facades (`81f042019`, `2f7f942b9`), scheduler routing (`21975e0b7`, `a4aadd798`), ACE provider abstraction
(`d2e2f4825`, `e33b74db1`), and notification/bead read routing (`cac918039`, `9bdb8fdaf`) all sit *above* preserved
direct loaders rather than replacing them. That compartmentalization is what makes selective config-level rollback
(rather than a code revert) the cheaper lever.
