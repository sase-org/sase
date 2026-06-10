---
create_time: 2026-06-09 20:14:04
status: done
prompt: sdd/prompts/202606/fast_ace_tui_startup.md
---
# Plan: Make `sase ace` Startup Fast (Eliminate Pre-Paint Dismissed-Index Sync)

## Problem

`sase ace` appears to hang for ~5–6 seconds before the TUI paints. Profiling on this machine shows:

| Stage                                              | Time                     |
| -------------------------------------------------- | ------------------------ |
| Python imports (`sase.ace.tui`, textual, widgets)  | ~1.4s                    |
| `AceApp.__init__` (`_init_app_state`)              | **~4.4–5.5s**            |
| — of which `sync_dismissed_agent_artifact_index()` | ~5.5s of 5.9s total init |

The blocking call is at `src/sase/ace/tui/actions/_state_init.py:419`, which runs **synchronously inside
`AceApp.__init__`, before Textual ever composes or paints**. Inside it:

- `verify_dismissed_bundle_index()` → `verify_index()` reads **and fully JSON-parses all ~31,500 dismissed bundle
  files** under `~/.sase/dismissed_bundles/` (~3.1s).
- `load_dismissed_bundle_summaries(limit=None)` materializes all ~31.5k summary rows just to extract identities (~1.1s).
- `replace_agent_artifact_index_dismissed_agents()` (Rust) rewrites the projection (~0.8s).

### Root cause: silent, unrepaired SQLite corruption defeats the existing fast path

`sync_dismissed_agent_artifact_index()` already has a signature-based fast path (`_projection_metadata_matches`) that
should skip all of the above when nothing changed. It never hits because `~/.sase/agent_artifact_index.sqlite` (110MB)
is **corrupted**:

- `PRAGMA integrity_check` reports "Rowid out of order" and a broken `sqlite_autoindex_meta_1` index.
- Indexed lookups on the `meta` table raise `sqlite3.DatabaseError: database disk image is malformed` (and can even
  return the _wrong row_), while full-table scans still work.
- `_read_projection_metadata()` swallows the error (`except sqlite3.Error: return None`) → fast path misses → full
  O(archive) scan, **on every single launch, forever**. The post-scan metadata write-back is likewise never visible to
  subsequent indexed reads, so the system never self-recovers, and nothing ever surfaces the corruption to the user.

### Secondary issue: even healthy installs block first paint on drift

When signatures legitimately drift (e.g. an out-of-band process dismissed agents since the last sync), the same full
blocking scan runs pre-paint. The cost is O(total bundles ever archived), not O(what changed), so it only gets worse
over time.

Verified expected win: with the sync stubbed out, `AceApp.__init__` takes **0.16s** (vs ~4.4–5.5s).

## Goals

1. First paint of `sase ace` is never blocked by dismissed-agent / artifact-index maintenance. Target: `AceApp.__init__`
   < 0.3s; command-to-first-paint ≈ imports + mount (~1.5–2s on this machine).
2. Artifact-index corruption is detected, surfaced, and self-healed instead of silently degrading every startup.
3. The maintenance pass itself becomes cheap — bounded by SQL + stats, not by JSON-parsing the entire archive — so even
   the background work stays light.

## Design

### Phase 1 — Move the sync off the cold-start critical path

- Remove the `sync_dismissed_agent_artifact_index(self._dismissed_agents)` call from `_init_app_state`
  (`src/sase/ace/tui/actions/_state_init.py`). Keep the cheap in-memory loads (`load_dismissed_agents()`, file signature
  capture) — they cost ~50ms.
- Schedule the sync as a post-mount background worker in `_start_post_mount_background_loads`
  (`src/sase/ace/tui/actions/startup.py`), alongside the existing agents/axe startup loads, running the blocking I/O via
  a thread (`asyncio.to_thread` / `run_worker(thread=True)`).
- Have the sync report whether the projection actually changed; when it did, set the agents dirty flag / nudge an agents
  refresh so any visibility corrections (agents dismissed or revived out-of-band) reconcile shortly after first paint.
- All in-session sync call sites (dismiss / revive / kill / `_loading_apply`) stay unchanged — they already use the
  cheap authoritative `added=` path and keep the metadata fresh during a session.

This phase alone guarantees the TUI paints fast regardless of corruption or drift.

### Phase 2 — Detect and self-heal artifact-index corruption

In `src/sase/core/agent_artifact_index_lifecycle.py` (the Python adapter that owns the `dismissed_projection` meta
table; used by both the TUI and CLI):

- Stop conflating corruption with "no metadata": distinguish `sqlite3.DatabaseError` ("database disk image is malformed"
  family) from transient lock/timeout errors in `_read_projection_metadata` / `_write_projection_metadata` and the sync
  entry point.
- On corruption: **quarantine + rebuild**, in the background (never pre-paint, courtesy of Phase 1):
  1. Atomically rename the index to `agent_artifact_index.sqlite.corrupt-<UTC timestamp>` (atomic rename doubles as the
     cross-process "heal lock": first renamer wins; a concurrent process sees a missing index and skips, which is
     today's harmless behavior). Keep at most one quarantine copy.
  2. Rebuild via the existing Rust facade `rebuild_agent_artifact_index(index_path, projects_root)` (already exposed by
     `sase agents index rebuild`).
  3. Run `sync_dismissed_agent_artifact_index(force=True)` to repopulate the dismissed projection and its metadata.
- Surface the event: log + a line in the TUI activity log; `sase agents index status` already has a `repair_recommended`
  concept to align with. A `sase doctor` deep-check hook for `PRAGMA integrity_check` is a natural follow-up.
- Rust-core boundary note: integrity checking/healing arguably belongs in `sase-core` long-term since the index is
  shared across frontends. This plan keeps the heal in the Python lifecycle adapter that already owns the meta-table
  read/write today, and records the Rust-side `integrity_check` API as a follow-up so we don't expand the sase-core wire
  surface in this change.

This phase fixes the user's machine automatically on first launch after the change (manual fallback:
`sase agents index rebuild`).

### Phase 3 — Make the maintenance pass cheap (no O(archive) JSON parsing)

- `verify_index()` (`src/sase/ace/dismissed_bundle_index/_api.py`): drop the `read_bundle()` JSON parse of every bundle.
  Verify with signatures only: compare indexed rows' stored `(mtime_ns, size_bytes)` against `stat()`, and set-compare
  on-disk bundle paths vs indexed paths to find missing rows. Per-file JSON validity only matters at rebuild time, and
  `rebuild_index` already tolerates and counts corrupt files. (~3.1s → ~0.6s for 31.5k bundles.)
- `build_dismissed_agent_projection_inputs()`: replace `load_dismissed_bundle_summaries(limit=None)` (which materializes
  every summary object) with a dedicated identity projection query in `_api.py` —
  `SELECT DISTINCT agent_type, COALESCE(cl_name, 'unknown'), raw_suffix FROM dismissed_bundle_summaries` — milliseconds
  instead of ~1.1s.

After this phase, even a genuine drift re-sync costs well under a second, and it runs in the background anyway.

### Out of scope (noted follow-ups)

- Import-time cost (~1.4s for textual + the widget tree). Acceptable once init is fixed; lazy-import trimming can be a
  separate effort.
- Rust-side `integrity_check`/heal API in `sase-core`.
- Archive retention policy (31.5k dismissed bundles and growing) — orthogonal, but a size cap or age-based pruning would
  bound all archive-shaped work permanently.

## Risks & Mitigations

- **Briefly stale dismissed-filtering on first paint** when out-of-band drift occurred: mitigated by the post-sync
  agents refresh nudge in Phase 1; identical to today's behavior for changes that occur mid-session.
- **Rebuild cost on heal** (110MB index, full source scan): runs in a background worker with an activity-log line;
  measure during implementation. Worst case the first launch after corruption has a slow _background_ heal while the TUI
  is already interactive.
- **Concurrent healers** (two TUIs / axe daemon): atomic-rename quarantine makes the heal first-writer-wins; losers skip
  gracefully exactly like today's missing-index path.
- **Stat-only verify misses byte-identical corruption**: same trust model the index's own `(mtime_ns, size)` staleness
  rows already use; full-parse validation remains available via rebuild and `sase agents index verify`.

## Validation

- Unit tests:
  - Corrupted index (fixture with a malformed sqlite file) → quarantine + rebuild + forced sync; metadata round-trips
    afterward and the fast path hits on the next sync.
  - Transient lock errors do NOT trigger quarantine.
  - Stat-only `verify_index` catches stale rows (mtime/size change), missing rows (new bundle on disk), and deleted
    files; parity test vs the old behavior on a healthy archive.
  - SQL identity projection returns the same identity set as the old summary-materializing path.
- TUI startup tests:
  - `AceApp.__init__` / `_init_app_state` performs no bundle reads and no artifact-index sync (counter/monkeypatch
    guard, in the spirit of the existing cold-start perf tales).
  - The post-mount background load schedules the sync, and a projection change triggers an agents refresh.
- Manual: time `sase ace` cold start on this machine (corrupted index present) before/after — expect first paint ~1.5–2s
  with a one-time background heal, then sub-second maintenance on subsequent runs.
- `just check` before completion.
