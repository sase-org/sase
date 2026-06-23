---
create_time: 2026-06-23 18:09:15
status: done
prompt: sdd/prompts/202606/sharded_prompt_history.md
---
# Sharded, Lazy-Loaded Prompt History

## Problem

The prompt history store is a single JSON file at `~/.sase/prompt_history.json` (~33 MB, ~9,000 entries). Two operations
pay for that size on hot paths:

1. **Every agent launch** calls `add_or_update_prompt()`, which takes a lock, reads the whole file, mutates it, and
   rewrites + `fsync`s the whole file. Prior profiling
   (`sdd/research/202606/tui_performance_log_research_consolidated_20260620.md`) measured this `history_write` stage at
   **974.8 ms mean / 1853.9 ms p95**, on the launch path. Its top-three recommendation #3 is to "stop rewriting a 32 MB
   `prompt_history.json` before launch is visible."
2. **Every time the prompt-history modal opens**, it loads and renders all ~9,000 prompts eagerly
   (`PromptHistoryModal._load_items()` → `get_prompts_for_fzf(include_cancelled=True)` → `store.load_prompt_history()`
   reads the whole 33 MB file synchronously).

### Constraints (from the requester)

- **Never lose a user prompt, regardless of age.** Migration and all maintenance must be loss-free; older prompts stay
  permanently retrievable.
- **Do not load older prompts eagerly when the modal opens.** Load up to the most recent **250** prompts; expose a
  keymap that loads **another 250** each time it is invoked. The user must be able to see how many prompts are currently
  loaded.
- **Shard the history JSON by date** so writing a launched prompt only touches a small, current shard instead of the
  whole store.

### Decisions locked by Q&A

- **Q1 — Shard granularity: monthly** (`YYMM.json`, e.g. `2606.json`). ~12 files/year; current shard stays MB-scale.
- **Q2 — Implementation location: Python, in this repo** (`src/sase/history/`). This matches the existing all-Python
  history code and the prior `sase prompt` research, which explicitly recommends deferring a Rust-core/SQLite move until
  the contract is proven or profiling demands it. The `rust_core_backend_boundary` guidance still points at sase-core
  for shared backend behavior long-term; this plan stays Python by explicit request and treats Rust/SQLite as deferred
  future work, not a now-change.
- **Q3 — Lazy-load UX: 250 + 250.** Open the modal with up to the most recent 250 prompts; a keymap loads another 250
  each invocation.

## Goals

1. Launch-time history writes touch only the current month's shard (MB-scale, sub-100 ms), never the full corpus.
2. The prompt-history modal opens against the most recent 250 prompts and grows by 250 per keypress, with a visible
   "loaded" count and a "more available" indicator.
3. The legacy single-file store is migrated into monthly shards once, losslessly, and kept as a verified backup.
4. CLI prompt commands (`list`, `show`, `stats`, `doctor`, `prune`, `delete`, `run`, `select`, etc.) keep working with
   identical semantics over the sharded store.
5. Locking and atomic-write durability are preserved.

## Non-Goals

- No SQLite / Rust-core migration (explicitly deferred; see Q2).
- No change to prompt dedup-by-text semantics, recency-only ordering, short-prompt filtering, or the
  cancelled/force-cancelled product rules (beyond one documented cross-month edge case below).
- No new top-level CLI command; this is a storage + modal change behind existing APIs.
- No change to where launches happen or to the launch failure-recording behavior.

## Design

### Storage layout

```
~/.sase/prompt_history/                 # new directory
  2601.json                             # one shard per YYMM, schema unchanged:
  2602.json                             #   {"prompts": [{text, timestamp, last_used, cancelled}, ...]}
  ...
  2606.json                             # the "current" shard
  unknown.json                          # entries with unparseable last_used (never dropped)
  legacy-imported-<ts>.json.bak         # verified backup of the pre-shard file
~/.sase/prompt_history.lock             # single global lock (unchanged role)
```

- **Shard key = `YYMM` of an entry's `last_used`** (not creation `timestamp`). This is the key invariant: history is
  displayed recency-first by `last_used`, so sharding by `last_used` makes "newest shards first" identical to
  "most-recently-used first." It also means every entry inside a shard has a `last_used` within that month, so
  concatenating shards newest-first (each internally sorted by `last_used` desc) yields a globally recency-ordered
  stream — exactly what lazy paging needs.
- The legacy file path (`~/.sase/prompt_history.json`) and the new directory (`~/.sase/prompt_history/`) have different
  names, so they never collide.

### Write path (the hot path)

`_apply_prompt_mutations()` is rewired so a launch only ever reads/writes the **current** shard (`YYMM` of "now"):

1. Acquire the existing global lock (`locked_prompt_history()`), unchanged.
2. Ensure migration has run (idempotent; see below).
3. Load only the current shard.
4. Apply mutations against current-shard entries using the **existing** logic from `_apply_prompt_mutations()` verbatim:
   dedup by exact text within the current shard; update `last_used`; honor `force_cancelled`; let a successful write
   upgrade to non-cancelled; never let a normal cancellation downgrade an already-successful prompt. If the text is not
   in the current shard, append a fresh entry (`last_used = now`).
5. Atomically save just the current shard (same `tempfile` + `fsync` + `os.replace`).

Consequences:

- A new prompt, or re-use of a prompt already touched this month, only rewrites the small current shard. **Old shards
  are never rewritten on launch.**
- Re-using a prompt last used in an older month appends a fresh copy to the current shard and leaves a now-stale copy in
  the old shard. That stale copy is shadowed on read (below) and is prunable; it is bounded (at most one stale copy per
  text per month it was reused).

### Read path: dedup-on-read, newest-first

`load_all_prompt_history()` (the full-scan reader used by CLI list/stats/doctor/prune/selector) reads every shard
newest-first and dedups by exact text, keeping the **first occurrence** (= newest, because writes always land in the
newest shard a text appears in). Reconciliation for a deduped text:

- `last_used` = newest copy's (first seen).
- `cancelled` = newest copy's flag (newest-by-`last_used` wins).
- `timestamp` = earliest creation across copies (preserve original creation time).

**Cancelled reconciliation note.** Newest-wins is correct for the authoritative events (a later successful launch
un-cancels; a later failed launch force-cancels) because their `last_used` reflects event time. The single regressed
edge case: a prompt successfully launched in month A, then _normally_ typed-and-cancelled in month B with no intervening
launch, shows as cancelled (the writer can't see month A cheaply). Within a month this is still exact (the writer sees
the current shard). The prompt is **not lost** — it stays visible under the cancelled toggle and re-launching upgrades
it. This trade-off is accepted and documented; an optional later `prune`/compaction pass can collapse stale duplicates.

### Lazy paging for the modal (and CLI `list --limit`)

Add a presentation-neutral paged reader in the catalog layer that yields deduped records newest-first without scanning
the whole store:

- Iterate shard files newest-first; within each shard, sort by `last_used` desc.
- Maintain a `seen` text set (dedup across pages) and a resumable cursor `(shard_index, offset_within_shard)`. A heavy
  month (>250 entries) can be paged across multiple invocations.
- A page returns up to N (=250) **new** deduped records and advances the cursor; it also reports whether older
  shards/offsets remain (`exhausted`).

This mirrors the existing cursor-paged modal precedent (`src/sase/ace/tui/modals/saved_agent_group_revival_modal.py`: a
`page_loader(cursor)` callable injected into the modal, a `pagedown` `priority=True` "Load More" binding, and a
`next_cursor`). The prompt-history modal will follow the same shape so paging logic stays in the storage/catalog layer
and the modal stays presentation-only.

### Migration (loss-free, one-time, idempotent)

`_ensure_migrated()` runs under the global lock:

1. If `~/.sase/prompt_history/` already exists (or a migration marker is present), no-op.
2. Otherwise read the legacy `prompt_history.json`, bucket every entry by `YYMM` of `last_used`, and write each bucket
   as a shard via the atomic writer. Entries whose `last_used` can't be parsed go to `unknown.json` — **never dropped**.
3. **Verify**: sum of entries written across shards == entries read from the legacy file. Only on a verified match,
   rename the legacy file to `legacy-imported-<ts>.json.bak` (kept, not deleted). On any mismatch/error, abort and leave
   the legacy file as the source of truth.

Triggering: migration is lazy (first store access pays it once, under the lock — no worse than today's
per-open/per-launch full read). Recommend also kicking it proactively from an existing off-event-loop background task at
`sase ace` startup so the first UI-thread modal open doesn't pay it. Both routes call the same idempotent helper.

## Affected code

### `src/sase/history/prompt_store.py` (core)

- Add: `prompt_history_dir()`, `legacy_prompt_history_file()`, `shard_key_for_timestamp(ts)` (→ `YYMM` or `"unknown"`),
  `shard_path(key)`, `iter_shard_paths_newest_first()`, `load_shard(path)` / `load_shard_for_write(path)`,
  `save_shard(path, prompts)` (atomic, per-shard), `load_all_prompt_history()` (dedup-on-read), and
  `_ensure_migrated()`.
- Rewire `_apply_prompt_mutations()` to current-shard load/mutate/save (logic preserved).
- Keep `load_prompt_history()` as the dedup-on-read full reader (so existing importers keep working); keep
  `save_prompt_history()` available for tests/maintenance but route per-shard internally. Preserve
  `locked_prompt_history()` contract (single global lock).
- Test seam: replace the `_PROMPT_HISTORY_FILE` override with a `_PROMPT_HISTORY_DIR` override (plus legacy-file
  override), since tests currently `patch("sase.history.prompt_store._PROMPT_HISTORY_FILE", ...)`.

### `src/sase/history/prompt_catalog.py`

- `list_prompt_records(..., limit=...)` reads newest-first and stops once `limit` deduped records are gathered (no full
  scan for bounded queries); unbounded still reads all.
- Add the paged reader (cursor + `seen` set + page-of-250 + `exhausted`) backing the modal.
- `resolve_prompt_selector()` uses `load_all_prompt_history()` (full scan — selectors must see every prompt).

### `src/sase/history/prompt_stats.py` & `prompt_maintenance.py`

- `stats`/`doctor`: report the directory path, **aggregate** size (sum of shard sizes) and shard count instead of a
  single file's size; iterate all shards.
- `delete`: remove the resolved text from **every** shard it appears in (rewrite only affected shards), under the lock.
- `prune`: `--before DATE` maps cleanly onto shards (whole months below the cutoff drop out); `--keep N` keeps newest-N
  by `last_used` across shards. Both load-all, mutate, rewrite affected shards — these are maintenance paths, not hot
  paths.

### `src/sase/ace/tui/modals/prompt_history_modal.py`

- Replace eager `_load_items()` with the paged loader: load the first 250 on open.
- Add `Binding("pagedown", "load_more", "Load More", priority=True)` (mirroring the revival modal; `pagedown` is
  non-printable so the focused `FilterInput` won't swallow it). `action_load_more()` pulls the next 250, appends,
  rebuilds options preserving highlight, and refreshes the count label.
- Update `_history_count_label()` to show loaded count + a "+250 with PgDn (older)" indicator while more remain, and the
  final total once exhausted (no full scan needed — "more remain" is just "unconsumed shards/offsets exist").
- Update the hints `Static` and the `?` help modal (per `src/sase/ace/AGENTS.md` "Help Popup Maintenance"). Note that
  the filter applies to _loaded_ items; PgDn pulls in older prompts to widen the searchable set.

### Tests

- `tests/history/test_prompt*.py`, `tests/history/test_prompt_catalog.py`, `tests/prompt_command/conftest.py`: migrate
  the `_PROMPT_HISTORY_FILE` seam to the new `_PROMPT_HISTORY_DIR` seam; keep direct seeding via
  `save_shard`/`save_prompt_history`.
- New coverage: shard-key computation; write touches only the current shard (assert older shards' bytes/mtime
  unchanged); dedup-on-read newest-first; cancelled reconciliation (within-shard don't-downgrade preserved; documented
  cross-month case); migration loss-free + count-verified + idempotent + `unknown.json` fallback + retained backup;
  paged loader (page size, `exhausted`, loaded count, cross-page dedup, heavy-month split).
- `tests/ace/tui/modals/test_prompt_history_modal.py`: open loads ≤250; PgDn loads the next 250; count label reflects
  loaded/exhausted; filter operates over loaded items.
- `tests/prompt_command/` (incl. `test_large_history.py`): list/stats/doctor/prune/delete parity over shards.

## Phasing

1. **Storage core + migration.** Shard helpers, current-shard write path, dedup-on-read full reader, loss-free verified
   migration, test-seam swap. Verify `pytest tests/history`.
2. **Catalog paging + CLI parity.** Paged reader, bounded `list_prompt_records`, stats/doctor aggregate reporting,
   delete/prune across shards. Verify `pytest tests/prompt_command`.
3. **Modal lazy-load UX.** 250-on-open, PgDn +250, count label, hints + `?` help. Verify
   `pytest tests/ace/tui/modals/test_prompt_history_modal.py`.
4. **Finalize.** Optional proactive off-thread migration trigger at TUI startup; docs touch-ups for any prompt-history
   file-path wording; `just install && just check`.

## Risks / Notes

- **Loss-free is paramount.** Migration verifies counts before retiring the legacy file and keeps a backup;
  `unknown.json` guarantees unparseable entries survive.
- **Recency invariant** (shard = `YYMM` of `last_used`) is what makes lazy paging produce correct recency order; the
  write path upholds it because `last_used` is only ever updated in-place in the current shard.
- **Cross-month normal-cancel** is the one accepted semantic nuance (documented above; no data loss).
- Preserve the sidecar `flock` and atomic `os.replace` on every mutation (per the prompt-history epic's cross-phase
  notes).
- Keep all blocking file I/O off the Textual event loop where the surrounding code already does so; the modal-open read
  is now bounded to 250 records / the newest shard(s).
