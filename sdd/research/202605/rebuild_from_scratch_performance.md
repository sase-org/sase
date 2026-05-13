# Rebuilding SASE From Scratch for Performance

Research date: 2026-05-13

## Question

If SASE were rebuilt from scratch, what would preserve today's functionality while producing drastically better
performance?

Short answer: keep the product model, but invert the implementation around a long-lived Rust state engine. The current
system has already moved many deterministic operations into `sase-core`; a from-scratch design should make that the
default shape for everything latency-sensitive instead of routing hot paths through cold Python processes, ad hoc file
scans, and per-view hydration.

The highest-impact move is not "rewrite every line in Rust." It is:

1. Store durable SASE state as append-only events plus indexed SQLite projections.
2. Keep a long-lived local daemon responsible for indexing, scheduling, notifications, and agent lifecycle state.
3. Make CLI, TUI, editor, mobile, and future web surfaces thin clients over a stable local API.
4. Move deterministic parsing, query planning, state transitions, and index maintenance into pure Rust crates.
5. Keep Python only for compatibility/plugin execution and user-authored workflow steps, isolated from startup and UI
   render paths.

## Current Evidence

The existing repo already points in this direction:

- `docs/architecture.md` defines SASE as a Python orchestration layer backed by a required Rust core for deterministic
  data operations. Shared backend behavior is already expected to live in `../sase-core/crates/sase_core`.
- `docs/rust_backend.md` lists Rust-backed ChangeSpec parsing, query corpus evaluation, notification JSONL operations,
  agent scan/index operations, launch prep, cleanup planning, and bead operations. The Python side remains the host for
  subprocesses, plugins, TUI rendering, VCS/workspace side effects, and user confirmation.
- `sdd/research/202605/startup_time.md` found parser/help paths around 155-200 ms, `sase run --help` around 370-418 ms,
  and `sase file list -t s` around 750-800 ms in one editable venv because a leaf editor helper imported the TUI package
  and Textual. That is a structural import-shape problem, not one slow function.
- `sdd/research/202605/agent_artifact_loading_startup.md` found `load_agents_from_disk()` around 3.0s on a machine with
  years of history, dominated by artifact scanning and dismissed bundle hydration. The note already recommends persistent
  agent artifact and dismissed bundle indexes.
- `sdd/research/202604/rust_backend_phase7_performance.md` records an important caveat: Rust wins when the boundary is
  coarse and amortized, but fine-grained PyO3 calls and repeated Python wire conversion can lose to optimized Python.
- `docs/perf_runbook.md` defines ACE responsiveness targets: j/k p95 under 16 ms, key-to-paint p95 under 33 ms, warm
  ChangeSpec reload under 100 ms at 1k specs, and no-change auto-refresh near 0 ms.
- `sdd/research/202604/sase_perf_v2_research.md` documents async/launch fan-out and bulk kill/dismiss bottlenecks that
  the daemon's task queue is meant to absorb. The rebuild inherits the requirement to keep kill, dismiss, and bulk
  operations non-blocking on UI threads.
- `sdd/research/202604/rust_core_next_candidates.md` enumerates the next deterministic operations queued for Rust:
  notification store, query batch evaluation, archive search expansion, agent index maintenance. These map directly to
  daemon-owned components below and should not be deferred behind another Python facade.
- `sdd/research/202605/rust_tui_plugin_migration.md` surveys WASM (Extism/Wasmtime) and async-in-trait constraints for a
  Rust plugin host; it is the canonical reference for the plugin-sandbox decision in §8.
- `sdd/research/202605/multi_machine_sync.md` shows runtime logs can dwarf state (one machine had ~64 GiB of `axe/logs/`)
  and that users do mirror `~/.sase/` across hosts. That has direct implications for daemon locking and projection
  storage (§Multi-Machine Sync Interaction below).

The sibling Rust workspace at `../sase-core/` already commits to a stack that the rebuild can reuse rather than choose
again:

- `sase_core` (Cargo.toml:22) depends on `rusqlite` with the bundled SQLite, so SQLite-as-projection is already a settled
  dependency choice, not a new one. The existing usage is read-mostly over archive JSONL — the rebuild's lift is schema
  + write-path, not introducing the dependency.
- The workspace declares `tokio` (multi-thread, signal, time, net), `axum` 0.7, `tracing` + `tracing-subscriber`, and
  `serde`/`serde_json` at the root (Cargo.toml:25-36). The daemon should adopt this stack rather than picking a parallel
  one.
- `crates/sase_gateway/` is **already a long-lived local HTTP server** (axum + tokio) used for mobile auth, SSE push,
  state mutation, and agent launch. The from-scratch "daemon" should not be a greenfield component — it should be
  `sase_gateway` extended with file-watching, scheduling, and an internal Unix-socket transport for local clients, with
  the existing HTTPS surface retained for mobile/web.
- `crates/sase_xprompt_lsp/` already runs a tokio+tracing LSP for xprompts, demonstrating the "long-lived local Rust
  service" shape works in this project.
- `src/sase/main/query_handler/_daemon.py` exists today but is a thin Python "daemon-mode" agent spawner, not a
  persistent process. It is replaced, not extended.

External references support the storage/event design:

- SQLite WAL allows readers and writers to proceed concurrently in the common case, with checkpointing needed to keep
  read performance stable: https://www.sqlite.org/wal.html
- SQLite FTS5 is designed for efficient full-text lookup over document collections, and external/contentless tables can
  avoid duplicating large content when the app owns synchronization: https://www.sqlite.org/fts5.html
- Rust's `notify` crate gives cross-platform filesystem notifications over inotify, FSEvents/kqueue,
  ReadDirectoryChangesW, and polling fallback: https://docs.rs/crate/notify/latest
- Ratatui is the current Rust-native terminal UI option if SASE wants a single low-startup binary instead of a Python
  Textual shell: https://ratatui.rs/installation/
- Textual's Worker API is the right model if keeping Textual: blocking work should run in managed workers, and thread
  workers must route UI updates safely: https://textual.textualize.io/guide/workers/
- `tracing` + `tracing-subscriber` are the de facto Rust async-aware structured-log/span stack and already present in
  the workspace: https://docs.rs/tracing/ — use `tokio-console` for live task inspection during daemon work:
  https://github.com/tokio-rs/console
- FoundationDB's deterministic simulation testing is the canonical model for proving an event-sourced + concurrent
  system stays correct under crash/partition: https://apple.github.io/foundationdb/testing.html — directly applicable to
  the daemon's recovery story.

## Functional Surface to Preserve

A performant rebuild still needs the same user-facing behavior:

- `sase run`, multi-agent prompts, xprompts, workflows, plan/question/HITL pauses, resume, retry, and explicit artifacts.
- ACE/TUI functionality: ChangeSpecs, agents, notifications, artifacts, axe status, tags, grouping, filters, revive,
  cleanup, logs, and keyboard-first workflows.
- Axe scheduling: hook checks, mentor checks, workflow checks, cleanup, digests, and background automation.
- ChangeSpecs and VCS workflows: status transitions, comments, hooks, mentors, commits, PR/CL metadata, revert/archive.
- Beads and SDD: issue graph, executable epic/legend plans, durable research/tale/epic/legend artifacts.
- Notifications and mobile/editor helpers.
- Provider/plugin boundaries for LLMs, VCS, workspaces, config, and resources.

## Recommended From-Scratch Architecture

### 1. Make a Rust State Engine the Product Core

Build `sase-core` as the actual product engine, not just an acceleration library. It should own:

- data model and wire schema versions;
- ChangeSpec parser, query planner, graph index, and status transition planner;
- agent launch planning and lifecycle state machine;
- notification, pending action, archive, artifact, bead, xprompt catalog, and editor helper indexes;
- deterministic workflow planning and persisted workflow state transitions;
- cross-surface query execution for CLI, TUI, mobile, editor, and web clients.

Keep side-effect adapters outside the pure core:

- LLM CLI invocation;
- VCS/workspace provider calls;
- user-authored Python/bash workflow steps;
- interactive confirmation;
- renderer-specific UI code.

This keeps correctness reusable while letting UI and integration surfaces remain replaceable.

### 2. Add a Long-Lived Local Daemon

Cold Python process startup is a recurring tax. A daemon removes most of it.

The daemon should:

- start once per user/session/project;
- maintain open SQLite connections and prepared statements;
- subscribe to filesystem events;
- own scheduling, notification dispatch, and agent lifecycle reconciliation;
- expose a local API over Unix socket/named pipe/localhost loopback;
- stream state deltas to ACE, mobile gateway, editor helpers, and CLI watch commands;
- coordinate background rebuilds and checkpoints.

CLI commands become thin clients:

- `sase status`, `sase agents`, `sase notify`, `sase bead`, and editor completion commands should round-trip to the
  daemon when available.
- For scripts and recovery, every command needs a direct "no daemon" fallback that opens the same stores and performs
  bounded work.
- The first command can auto-start the daemon, but latency-sensitive commands should have an explicit
  `sase daemon start` path for users who care about shell/editor responsiveness.

Expected gain: eliminate repeated package import, parser construction, Rust extension load, config load, and full store
scan costs from common commands.

**Reuse the existing gateway, don't build a second daemon.** `crates/sase_gateway/` already runs axum+tokio with a
serde-JSON wire contract for mobile/web. The rebuild should extend it with: an internal Unix-socket transport (lower
latency than localhost loopback for local clients), file-watch ownership, scheduler ownership, and a delta-stream
subscription API. The external HTTPS surface stays for mobile. Two daemons would duplicate file-watching, lock
contention, and config loading; one process with two listeners avoids that.

**Wire format.** Use the existing `serde` types from `sase_core::wire` over the loopback HTTP + SSE path (already used
by mobile) and over a Unix-socket framed-JSON path for CLI/TUI. The earlier draft left this open as "Unix
socket/named pipe/localhost loopback"; pick one stack: HTTP/1.1 + SSE for streaming, framed JSON over Unix socket for
request/response, and shared serde structs so client and server cannot drift. gRPC/Cap'n Proto/msgpack would buy little
once the API is coarse-grained (§5) and would duplicate the gateway's existing wire schema.

**Single-machine ownership.** The daemon must hold a PID/lock file under `~/.sase/run/` and refuse to start if another
PID owns it. This is the precondition for the WAL/checkpoint policy below to be safe.

### 3. Use Append-Only Events Plus Materialized SQLite Projections

The current filesystem layout is inspectable and robust, but performance suffers when every view reconstructs state from
many JSON/Markdown files. The rebuild should use:

- an append-only event log for agent lifecycle, notification changes, ChangeSpec mutations, bead mutations, archive
  updates, and workflow step transitions;
- SQLite tables as rebuildable materialized projections;
- source files retained for human-readable audit/export where valuable;
- deterministic rebuild commands that can recreate indexes from source artifacts.

SQLite should run in WAL mode for local multi-reader use, with explicit checkpoint policy so long-running TUI/mobile
readers do not let WAL files grow indefinitely. Use FTS5 for prompt/reply/archive/content search, preferably with a
bounded searchable projection instead of indexing raw unbounded chat logs.

Core tables worth designing up front:

- `changespecs`, `changespec_edges`, `changespec_sections`, `changespec_search_fts`;
- `agents`, `agent_attempts`, `agent_edges`, `agent_artifacts`, `agent_search_fts`;
- `agent_archive`, `agent_archive_search_fts`, `dismissed_identities`;
- `notifications`, `pending_actions`, `notification_search_fts`;
- `beads`, `bead_dependencies`, `bead_events`;
- `workflows`, `workflow_steps`, `workflow_events`;
- `xprompt_catalog`, `memory_catalog`, `file_history`.

This preserves inspectability by making every projection disposable: if the database is corrupt or stale, rebuild it
from the event log plus source files.

**Concrete policies the original draft skipped.**

- *WAL checkpointing.* Run in `journal_mode=WAL`, `synchronous=NORMAL`, and schedule explicit
  `wal_checkpoint(TRUNCATE)` calls — opportunistically when the daemon is idle, and unconditionally on a 1 GiB or
  10-minute soft cap. Long-lived TUI/mobile readers otherwise prevent automatic checkpointing and WAL files grow
  without bound. SQLite docs: https://www.sqlite.org/wal.html#avoiding_excessively_large_wal_files.
- *Event log compaction.* Append-only is unsustainable without rotation. Define event classes: state-mutating
  ("ChangeSpec.status_changed", "agent.completed") are kept indefinitely; high-volume ephemeral events
  ("agent.log_line", "axe.tick") rotate per day and compact on a retention window (default 30 days, configurable).
  Compaction writes a snapshot row to the projection and drops the source segments. This is what prevents the 64 GiB
  log scale seen in `multi_machine_sync.md`.
- *Crash recovery.* Each write is `BEGIN IMMEDIATE` → projection update → event append → `COMMIT`. On restart, the
  daemon verifies the latest event's projection effect is applied (compare event seq vs `projection_meta.last_seq`); if
  a gap exists, reapply from the event log. A `--rebuild` flag drops projections entirely and replays from events +
  source files.
- *Backups.* `VACUUM INTO` snapshots to `~/.sase/backup/` on a daily cadence; cheap because projections are bounded.

### 4. Make File Watching First-Class, Not a Refresh Hint

Current ACE has an artifact watcher, but broad refresh paths still exist. In a rebuild, watcher events should update
specific index rows:

- close-write/create/delete in an artifact directory updates one `agents` row;
- ChangeSpec file writes reparse one project file and update affected rows;
- notification writes update notification rows and counts;
- bead JSONL/config writes update the bead projection;
- xprompt/config changes update catalog projections.

The UI should subscribe to deltas like `agent.updated`, `agent.removed`, `notification.counts_changed`, and
`changespec.row_changed`, not ask for a full reload. Polling remains only as a low-frequency reconciliation fallback.

### 5. Design Every Hot API Around Handles and Batches

The existing Rust measurements show the trap: a fast Rust function can regress if every call serializes many Python
objects or crosses FFI at row granularity.

From scratch, hot APIs should be shaped like:

- compile/query handles for repeated query edits;
- page/cursor APIs for large lists;
- batch updates for launch fan-out and cleanup;
- delta streams for UI refresh;
- immutable snapshot IDs so clients can ask "what changed since snapshot N?"

Avoid APIs that return the entire world as nested Python dictionaries. Prefer owned Rust structs inside the daemon and
small wire payloads at client boundaries.

**Async runtime choice.** `sase_core` is sync today (rusqlite is blocking); `sase_gateway` is tokio. The rebuild should
standardize on tokio for the daemon and wrap blocking SQLite/parse operations with `tokio::task::spawn_blocking`, with
a bounded blocking pool sized to the CPU count. Mixing sync and async ad hoc is a known footgun and was flagged in
`rust_tui_plugin_migration.md`.

**Agent launch fan-out.** Today the Python side spawns one thread per agent (`launch_bulk.py`-style fan-out), and
`sase_perf_v2_research.md` shows this is a UI-blocking hotspot. The daemon should expose a single batch-launch RPC that
accepts N specs, enqueues N tokio tasks behind a semaphore (default concurrency = CPU count, configurable), streams
per-agent status events, and returns a batch handle. Backpressure: when the queue exceeds a configurable depth, new
launch RPCs return a typed "queued at position K" response so the UI can render a queued state instead of blocking.

### 6. Separate Command Parsing From Business Imports

The current startup research shows import barrels and argparse defaults can dominate command latency.

A rebuild should enforce:

- root CLI parses only command name and lightweight flags;
- each subcommand owns its parser and imports lazily;
- help text is generated from static metadata, not business modules;
- no disk I/O while constructing parsers;
- latency-sensitive editor commands avoid the full CLI parser and call stable helper APIs directly.

Best version: a Rust `sase` binary with `clap` dispatch and a local daemon client. Python provider/plugin code is loaded
only after a command selects a path that truly needs it.

### 7. Keep UI Rendering Incremental and Data-Virtualized

For ACE, the core rule should be: navigation never performs I/O and never rebuilds a whole list.

Implementation choices:

- If maximum performance is the priority, build the primary TUI in Rust with Ratatui and consume daemon deltas directly.
- If Textual remains the product shell, make it a thin client: all I/O in Textual workers, no package barrels that load
  the whole app for leaf helpers, virtualized lists, row patching, and full-detail rendering only after debounced idle.

The TUI data contract should provide:

- paged/sorted list rows with stable row IDs;
- cheap row patches;
- cheap highlight-only updates;
- summary counts and facets precomputed by the daemon;
- lazy artifact/detail loads;
- cancellable background fetches keyed by selection version.

This preserves current ACE workflows while making j/k navigation and auto-refresh independent from corpus size.

### 8. Treat Plugins as Out-of-Process Host Adapters

Plugin flexibility is valuable, but plugin imports should not be on hot paths.

Recommended model:

- core provider interfaces are stable IPC contracts;
- built-in high-traffic providers can be Rust-native;
- Python plugins run in a small host process loaded on demand;
- plugin calls are async jobs with timeouts, structured logs, and explicit side-effect intents;
- plugin outputs are validated by Rust before mutating state.

This keeps the existing extensibility story while preventing one Python package import graph from slowing every CLI or
TUI operation.

**Sandbox specifics the original draft skipped.** Plugin subprocesses should run with: per-call wall-clock timeout
(default 30s, override per provider), RSS soft cap via `prlimit` (default 512 MiB), CPU-quota via cgroup v2 where
available, no network capability unless the plugin manifest declares it, and structured-log capture on stdout/stderr.
On Linux, a seccomp profile that blocks `ptrace`, `mount`, and raw socket families is appropriate; on macOS, rely on
sandbox-exec profiles. These limits keep a misbehaving provider from starving the daemon's tokio runtime.

**WASM is the v2 plugin path, not the v1.** `rust_tui_plugin_migration.md` already evaluated Extism/Wasmtime and that
remains the right long-term sandbox for native plugins. The v1 rebuild should not couple the daemon to a WASM runtime —
ship with subprocess-isolated Python plugins, design the IPC so a WASM host can be swapped in later behind the same
contract.

### 9. Make Workflow Execution Durable and Resumable by Construction

Current workflows persist step state, but a rebuild should make the event log the scheduler's truth:

- each workflow step transition is an event;
- blocking steps create pending actions;
- child agent launches are planned as one transaction and then materialized;
- retries and resume are graph operations over persisted state;
- long-running shell/Python steps stream logs into bounded append-only artifacts plus indexed summaries.

The daemon should coordinate scheduling, but actual agent/provider subprocesses can stay isolated. This preserves
recoverability while avoiding repeated filesystem discovery to answer "what is running?"

### 10. Instrument Everything From Day One

Make performance budgets part of the product contract:

- CLI cold start and warm daemon round-trip;
- ACE first paint, active-agent first paint, j/k key-to-paint, query edit p95;
- daemon event-to-index latency;
- event-to-UI paint latency;
- SQLite query p50/p95 by surface;
- index rebuild throughput;
- agent launch fan-out latency;
- notification action latency.

The existing `docs/perf_runbook.md` targets are good starting gates. A rebuild should put these into CI/perf fixtures
before feature parity is complete, because late instrumentation usually just proves the architecture is already too
expensive.

**Concrete observability stack** (the original draft only said "instrument everything"):

- `tracing` spans on every RPC handler, every file-watch event, every SQLite query, every plugin call. Use
  `tracing-subscriber` with env-filter so users can raise verbosity without redeploying.
- `tokio-console` enabled in dev builds for live task/blocking-pool inspection. This catches "one slow blocking task
  starves the runtime" classes of bugs that are invisible in span logs.
- Prometheus exporter on the daemon's loopback port. Minimum metric set: daemon RSS, tokio task count, blocking-pool
  saturation, SQLite query latency histograms keyed by surface, file-watch event lag, event-log append rate,
  projection-rebuild duration, agent-launch queue depth, plugin call durations.
- Histograms over counters wherever the user-visible metric is "p95 < X" — counters tell you it's slow but not how slow.

## Multi-Machine Sync Interaction

`multi_machine_sync.md` shows users do mirror `~/.sase/` across hosts (Syncthing/rclone), and that runtime logs can
dwarf state. This breaks the "single daemon owns SQLite" assumption:

- Two daemons writing to the same SQLite WAL across a synced filesystem will corrupt it. The PID/lock file in §2 must be
  on the local filesystem and must include a host identifier; a sync conflict on the lock file means the daemon refuses
  to start and instructs the user to run a recovery command.
- Projections (`.sqlite`/`-wal`/`-shm` files) and the event log should live in a host-local directory (e.g.
  `~/.sase/run/<hostname>/`) and be excluded from sync. Source files (`.gp`, artifacts, notifications) remain in the
  synced tree so users can keep their cross-machine workflow.
- High-volume rotating logs go under the host-local directory by default. Users who want them synced can opt in.
- Cross-host event replay (later) can subscribe to the synced source files and rebuild local projections, which gives
  the "see the same state from any machine" property without sharing a database.

## Migration Path for Existing State

Users have months-to-years of `~/.sase/` data — `.gp` files, archives, notifications, artifacts, beads, agent
directories. The rebuild must not require a flag day.

- *Phase 0 — shadow mode.* Daemon runs alongside the current Python CLI, watches the existing files, builds
  projections, but is not authoritative. Existing commands keep working unchanged. The daemon's read APIs can be
  diff-tested against the Python implementations.
- *Phase 1 — read traffic.* Latency-sensitive read paths (CLI status, ACE first paint, editor helpers) call the daemon.
  Writes still go through Python.
- *Phase 2 — write traffic.* State-mutating operations move to the daemon, which writes the source file AND appends the
  event. Source files remain the human-inspectable record.
- *Phase 3 — daemon-authoritative.* Daemon owns scheduling; Python becomes plugin/workflow host only. Source files are
  re-derivable from events for export/backup.

Each phase ships with `sase doctor` checks that compare projection state against the source files and a `sase rebuild`
that drops projections and replays.

## Test Strategy

Performance architectures fail at scale and under concurrency, not at unit-test scale. The rebuild needs:

- *Property tests* on the event-log/projection mapping: for any sequence of valid events, projections after replay must
  equal projections after live application.
- *Deterministic simulation tests* for the daemon (FoundationDB-style): inject crashes, slow I/O, file-watch event
  reordering, and concurrent client RPCs against a virtual clock; assert no projection corruption, no event loss, and
  bounded recovery time.
- *Soak tests* with synthetic event volume (e.g. 1M events, 100k agents, 5k ChangeSpecs) to catch projection-rebuild
  time, WAL bloat, and FTS query degradation that don't show up at small scale.
- *End-to-end perf gates* mapped to `docs/perf_runbook.md` targets, run in CI on a known machine class. Regressions
  block merge; the existing PNG-snapshot model is a useful precedent for "perf snapshots."
- *Sync chaos* tests for the multi-machine path: corrupt the lock file, race two daemons on a tmpfs-shared directory,
  verify both refuse to clobber data.

## What I Would Not Do

- Do not keep Markdown/JSON files as the only runtime database and try to recover performance with larger caches. Cold
  process startup and archive growth will keep reappearing.
- Do not port tiny helpers to Rust one by one without changing API granularity. The PyO3 boundary can erase the win.
- Do not make the daemon the only source of truth. It should be an indexer/coordinator over durable stores, not a fragile
  memory singleton.
- Do not force all user workflow code into Rust. Python/bash steps are part of SASE's power; isolate them instead.
- Do not optimize the TUI before the data contract. A fast renderer over a "load everything" API will still hitch.

## Likely Performance Shape

These are directional targets, not measured promises:

| Surface | Current shape from existing notes | Rebuild target |
| --- | ---: | ---: |
| Common warm CLI query via daemon | 155-200 ms parser/import floor | 5-30 ms local IPC + query |
| Editor file/helper command | up to 750-800 ms when import path hits TUI | 5-25 ms helper API |
| ACE first useful paint | scale-sensitive, then post-paint agent load | <100 ms first shell, <250 ms active data |
| Full agent history startup | ~3.0s on a large personal history | no full hydration; paged/indexed |
| No-change auto-refresh | polling fallback can still do broad work | no UI reload; reconciliation only |
| Agent/archive search | SQLite index exists for archive; live still hydrates rows | unified indexed live/archive query |
| Daemon resident memory | n/a (Python TUI ~150-300 MiB after warmup) | <80 MiB resident at idle, <250 MiB under load |
| SQLite projection size | n/a | <500 MiB for 5 years of history at p95 user |
| Agent launch fan-out (50) | thread-per-agent, UI-blocking pulses | tokio semaphore, <50 ms enqueue, streaming events |

## Migration Implications

If this became a real roadmap, the best sequence would be:

1. Define the canonical event model and SQLite projections in `sase-core` (rusqlite is already a workspace dep).
2. Extend `sase_gateway` with file-watching, scheduler ownership, and a Unix-socket transport — not a new daemon binary.
3. Run in shadow mode: daemon builds projections from existing `.gp`/JSONL/artifact files; Python remains authoritative.
4. Move read-heavy CLI commands and ACE Agents/Notifications/ChangeSpecs to daemon-backed paged queries + delta streams.
5. Move launch/workflow state transitions into event transactions; daemon becomes write-authoritative for state.
6. Replace or thin the TUI shell only after the backend contract is fast and stable. Ratatui is optional, not required.
7. Keep file export/import/rebuild commands and `sase doctor` so users can recover without trusting the daemon.

The biggest architectural bet is the daemon plus indexed projections. The biggest compatibility risk is maintaining
human-inspectable artifacts and plugin behavior while changing the runtime source of truth. The safest rule is:
events/projections are authoritative for runtime queries, but every projection must be rebuildable and every destructive
operation must leave an auditable artifact trail.

## Bottom Line

For a true scratch rebuild, the best performance architecture is a Rust-first local operating system for SASE:
event-sourced durable state, SQLite/WAL/FTS projections, first-class filesystem indexing, a long-lived daemon, thin
clients, batched/handle-based APIs, and isolated Python plugin execution. That keeps the same functional model while
removing the two costs that current SASE has had to fight repeatedly: cold Python import graphs and reconstructing live
state from scattered files on every view refresh.
