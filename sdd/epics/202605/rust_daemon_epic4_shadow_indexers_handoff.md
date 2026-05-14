---
create_time: 2026-05-14
status: handoff
bead_id: sase-3e.4.9
---

# Rust Daemon Epic 4 Handoff: Shadow Indexers and File Watch Ownership

## Scope

Epic 4 adds daemon-owned shadow indexing for existing SASE source stores without
routing production reads through the daemon. The Rust daemon can now watch,
backfill, reconcile, rebuild, verify, and diff projection rows for supported
surfaces while the current loaders remain authoritative.

The user-visible behavior change is limited to new `sase daemon` diagnostics:
`doctor`, `rebuild`, `verify`, and `diff` expose indexing health and parity
reports. CLI, ACE, editor, mobile, bead, workflow, and xprompt read paths still
use their existing source-store loaders.

## Supported Surfaces

| Surface | Shadow inputs | Epic 5 readiness |
| ------- | ------------- | ---------------- |
| `changespecs` | Active and archive project spec files under `~/.sase/projects/<project>/`. | Ready for scoped read-migration design after pagination/detail contracts are reviewed. |
| `notifications` | Notification JSONL plus pending-action stores. | Ready for list/detail parity evaluation; keep invalid-line soft-error behavior pinned. |
| `agents` | Agent artifact directories, marker files, archives, and dismissed state. | Ready for high-volume list API design; detail pagination and archive/dismissal edge cases need explicit contracts. |
| `beads` | VC-backed `sdd/beads/` and non-VC `.sase/sdd/beads/` stores. | Ready for read-path experiments that preserve the current selected write-store rules. |
| `catalogs` | Xprompt, workflow, config, memory, artifact-index, and file-history catalog sources. | Partially ready; plugin and generated inputs may still require resync diagnostics rather than passive watching. |

## Operator Commands

Start the daemon, then inspect indexing state:

```bash
sase daemon start
sase daemon doctor --json
```

Backfill shadow projections from source stores:

```bash
sase daemon rebuild --surface all --json
sase daemon rebuild --surface beads --project sase --json
```

Verify parity and inspect bounded differences:

```bash
sase daemon verify --surface all
sase daemon diff --surface all --limit 100 --json
```

Use `--reset-storage` only for projection database recovery. With a stopped
daemon, `sase daemon rebuild --reset-storage` replays retained projection events
after resetting projection tables; source-store backfill requires a running
daemon.

## Operational Playbook

- Indexing degraded: run `sase daemon doctor --json` and inspect
  `details.indexing`. Restart the daemon if the watcher is inactive, then run a
  scoped `sase daemon rebuild --surface <surface>` for the affected source set.
- Projection/source mismatch: run `sase daemon diff --surface <surface> --json`
  and inspect `missing`, `stale`, `extra`, and `corrupt` records. Prefer scoped
  source backfill before projection reset.
- Stale watcher roots: confirm the daemon was started with the intended
  `--sase-home` and project context. Reconciliation repairs missed events, but
  incorrect roots need daemon restart plus scoped rebuild.
- Corrupt projection database: stop the daemon, run
  `sase daemon rebuild --reset-storage --json`, restart, then run
  `sase daemon verify --surface all`.
- Large rebuild in progress: use `sase daemon doctor --json` for queue counters
  and recent reports. Avoid repeated unbounded diffs while backfill is running.

## Diagnostic-Only Review

Epic 4 local daemon capabilities remain diagnostic-only:

- `health.read`, `capabilities.read`, events, and batch requests are daemon
  lifecycle surfaces.
- `indexing.status`, `indexing.rebuild`, `indexing.verify`, and
  `indexing.diff` report or repair shadow projections.
- Production list/read APIs are still mocked, empty, or source-loader backed
  outside this daemon surface. Epic 5 must add explicit routing gates before any
  CLI, ACE, editor, mobile, or helper read path consumes daemon projections.

## Epic 5 Handoff

Ready surfaces:

- ChangeSpec, notification, agent, bead, and catalog projections have shadow
  backfill and diff hooks available through the daemon RPC shape.
- The local daemon contract now names indexing request/response records,
  selectors, bounded diff paging, and per-surface summaries.
- The Python CLI can call live-daemon rebuild, verify, and diff, with clear
  errors when the daemon or socket RPC is unavailable.

Known gaps for the indexed-read epic:

- Pagination and detail response shapes still need product-level contracts per
  real read surface; current shadow diffs are operator diagnostics, not end-user
  list APIs.
- Catalog/plugin inputs can be non-watchable and should keep explicit
  resync-required diagnostics until the provider contracts are tighter.
- Agent archive and dismissed-state read migration should preserve current
  corrupt-marker tolerance and high-volume bounded behavior.
- Bead read migration must preserve VC/non-VC store selection and must not make
  daemon projections authoritative for writes.

Recommended first Epic 5 slice:

1. Pick one low-risk read-only surface, preferably a bounded ChangeSpec or bead
   list endpoint.
2. Add a `--no-daemon` or equivalent fallback gate before routing users through
   daemon projections.
3. Keep direct loader parity tests beside daemon-backed tests until the shadow
   diff is quiet on representative real stores.
4. Promote daemon projection reads only after the user-facing response contract
   is paginated, bounded, and documented.

## Verification Matrix

- Rust unit and integration coverage owns source identity, fingerprints,
  idempotency keys, projection-aware append, source backfill, diff algorithms,
  reconciliation, watcher queue behavior, and local daemon wire snapshots.
- Python tests cover the thin daemon CLI/client behavior for rebuild, verify,
  diff, doctor, and unavailable-daemon errors.
- Manual local verification for a new workspace:
  `sase daemon start`, `sase daemon doctor --json`,
  `sase daemon rebuild --surface all --json`,
  `sase daemon verify --surface all`, and
  `sase daemon diff --surface all --limit 100 --json`.
