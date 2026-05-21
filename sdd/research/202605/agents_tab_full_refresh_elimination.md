# Agents Tab Full Refresh Elimination Research

Date: 2026-05-21 (initial), revised 2026-05-21

## Question

The Agents tab now has a Tier 1 index-backed refresh path from the `sase-3s`
epic (`sdd/epics/202605/agent_artifact_index_lifecycle.md`), but full refreshes
are still common and very slow. The goal is to make a full source scan almost
never necessary for the agent entries shown in the normal Agents tab.

## Short Answer

Treat the normal Agents tab as a visible inbox backed by the artifact index,
not as an incomplete slice of history that eventually needs Tier 2. Full
refreshes should move to explicit repair/archive/revive/debug workflows.

The current path is still not authoritative for the visible inbox, for five
distinct reasons that compound:

1. The manual `y` refresh promotes to Tier 2 whenever
   `_agents_history_reconcile_pending` is set, which is essentially always
   after first paint (see below).
2. Every Tier 1 apply re-arms `_agents_history_reconcile_pending=True`, so
   the flag is re-armed after *every* user action that triggers a reload — even
   after a successful Tier 2 reconcile.
3. Tier 1 has no concept of "complete for what is visible." `complete_history`
   is binary; `_agents_seen_complete_history` is recorded but is never used to
   suppress re-arming.
4. The Tier 1 query is `active + recent completed limit 200`, with the same
   200-row cap applied to both selects, and the active predicate counts stale
   historical rows whose marker files were removed.
5. The dismissed-projection table in the index is never synced at startup,
   and never sees the dismissed-bundle store at all, so the SQL predicate
   that excludes dismissed rows is starved.

The previous draft of this note treated (1) as already fixed and missed
(2)–(5). The revisions below back-fill those.

## Code Findings

### Current Tier 1 Query

`src/sase/ace/tui/models/agent_loader.py:121` uses
`_query_artifact_index_for_loader(full_history=False)` when the index exists.
That constructs:

```python
AgentArtifactIndexQueryWire(
    include_active=True,
    include_recent_completed=True,
    include_full_history=False,
    recent_completed_limit=_TIER1_RECENT_COMPLETED_LIMIT,  # 200
    include_hidden=False,
)
```

In `../sase-core/crates/sase_core/src/agent_scan/index.rs`,
`query_agent_artifact_index()` calls `select_records()` once for the active
predicate and once for the completed predicate. Both calls pass
`query.recent_completed_limit`. The "recent_completed_limit" is therefore the
**active** limit as well — the name is misleading, and there is no way to
request all active rows while bounding completed rows. The 200-row cap is
applied before the visible-inbox filter, so any stale predicate match consumes
a slot.

### Manual `y` Currently Promotes To Tier 2 (Correction)

`src/sase/ace/tui/actions/base.py:364`:

```python
def action_refresh(self) -> None:
    if self.current_tab == "agents":
        full_history = bool(
            getattr(self, "_agents_history_reconcile_pending", False)
        )
        if full_history:
            self._agents_history_reconcile_pending = False
        self._schedule_agents_async_refresh(full_history=full_history)
    ...
```

A short-lived fix (`919d57d62 fix: keep manual agents refresh on tier1`) made
`y` stay on Tier 1, but it was reverted (`9392bfc3e Revert ...`). So today, any
manual `y` after the first Tier 1 paint promotes to `full_history=True`.
Combined with the feedback loop below, that means `y` is almost always Tier 2
in practice — which matches the user's observed pain.

### Feedback Loop: Pending Flag Re-Arms Every Tier 1 Apply

`src/sase/ace/tui/actions/agents/_loading_apply.py:318`:

```python
if load_state is not None and load_state.complete_history:
    self._agents_seen_complete_history = True
    self._agents_history_reconcile_pending = False
self._agent_load_state = load_state
if (
    load_state is not None
    and load_state.needs_full_history_reconcile  # i.e. not complete_history
    and not getattr(self, "_agents_history_reconcile_pending", False)
):
    self._agents_history_reconcile_pending = True
    self._agents_history_reconcile_armed_mono = time.monotonic()
    if not getattr(self, "_agents_startup_tier2_scheduled", False):
        self._agents_startup_tier2_scheduled = True
        self.set_timer(
            STARTUP_TIER2_RECONCILE_DELAY_S,
            self._fire_startup_tier2_reconcile,
        )
```

Because the index path always returns `complete_history=False`, this branch
re-arms the pending flag on *every* Tier 1 apply. So:

- Tier 2 reconcile completes → `_pending=False`, `_seen_complete_history=True`.
- User dismisses/kills/revives, or a notification triggers a refresh, or any
  action calls `_load_agents()` → Tier 1 applies → `_pending=True` again.
- Next manual `y` → promotes to Tier 2 again. Slow refresh returns.

`_agents_seen_complete_history` is set but is never read as a gate. A one-line
change to skip re-arming when `self._agents_seen_complete_history` is true (or
when the change since the last Tier 2 reconcile is bounded by lifecycle
deltas) would eliminate the recurring promotion entirely.

The startup Tier 2 timer (`_fire_startup_tier2_reconcile`) is also armed every
time the pending flag is re-armed, but it bails when
`_agents_startup_tier2_scheduled` is already True — so the timer fires only
once, but the manual escape hatch keeps re-arming forever.

### Search Still Forces Full History

Both sync and async load paths in
`src/sase/ace/tui/actions/agents/_loading_disk.py:189,236` pass:

```python
full_history=full_history or bool(getattr(self, "_agent_search_query", ""))
```

So any non-empty `/` query bypasses the index. The in-memory refilter +
`_agent_content_search_cache` already exists, so this promotion is doing work
the content index already does in cache.

### Active Predicate Is Too Permissive For Stale Rows

`active_where()` in core:

```text
WHERE hidden = 0 AND (
    has_done_marker = 0
    OR workflow_status NOT IN ('completed','failed','cancelled','noop')
)
AND NOT EXISTS ( ... dismissed_agents match ... )
ORDER BY timestamp DESC
```

`has_done_marker` flips to 0 when `done.json` is removed, which is exactly
what dismissal does. `workflow_status` is null for non-workflow agent rows.
So a stale dismissed historical row whose `done.json` is gone re-enters the
active set unless the `dismissed_agents` exclusion subquery catches it. The
local index sample showed 7599 rows with `status='starting'` (most likely
abandoned launch artifacts) plus 2978 `running`, the great majority of which
are not actually live processes.

PID liveness is enforced only in Python by `_filter_dead_pids()` in
`agent_loader.py:345` — *after* the 200-row cap has been applied. Dead-PID
running rows therefore consume Tier 1 slots, then get dropped, and any
non-stale visible entries that fell off the cap stay missing until Tier 2.

### Tier 1 Is Still Considered Incomplete

`AgentLoadState.needs_full_history_reconcile` is `not self.complete_history`
(`models/agent_loader.py:86`). The index path returns
`complete_history=False` unconditionally. There is no `complete_visible_inbox`
distinction; any non-Tier-2 load is treated as incomplete and arms Tier 2.

### Local Index Drift Sample

On this workstation, `~/.sase/agent_artifact_index.sqlite` exists, but the
SQLite CLI is not installed, so I inspected it with Python's stdlib `sqlite3`.
The sample was read-only.

Observed counts:

```text
agent_artifacts total: 12385
active-like rows:      10752
done rows:             1635
hidden rows:           2265
dismissed_agents rows: 0
visible-not-dismissed: 10120
```

Status breakdown:

```text
starting:        7599
running:         2978
completed:       1680
waiting:           80
failed:            47
LEGEND APPROVED:    1
```

But SASE's actual dismissed stores are large:

```text
dismissed_agents.json identities: 25536
dismissed bundle summaries:      22102
```

In the top 250 active-like index rows, 243 shared a dismissed raw suffix, even
though none matched the Rust dismissed table exactly because that table was
empty. In the top 1000 active-like rows, 954 shared a dismissed raw suffix.

This explains why a 200-row active cap can still miss entries the user expects:
the cap is applied before the SQL dismissed predicate has anything to filter
against.

### Why The Index Is Drifted: No Startup Dismissed Sync

`sync_dismissed_agent_artifact_index()` in
`src/sase/core/agent_artifact_index_lifecycle.py:47` is the right hook, and
it is wired into the lifecycle paths added in Phase 2/3 of the epic:

- `actions/agents/_dismissing.py:295,320` — after dismiss commits.
- `actions/agents/_kill_persistence.py:102` — after kill persistence.
- `actions/agents/_killing.py:538` — async kill flow.
- `actions/agents/_revive.py:366,498` — after revive.

But `grep` shows **no call from any TUI startup path, no call from
`_load_agents_async`, and no call from `sase agents index gc` other than
through the rebuild path.** A long-lived index that pre-dates dismissal hook
landing — or that received any external dismissal through CLI/Telegram — will
have a permanently stale dismissed projection until the user dismisses
something new inside the TUI session, at which point only the in-memory set
gets pushed.

The cheapest practical repair is: on TUI start, after loading
`dismissed_agents.json`, call `sync_dismissed_agent_artifact_index()` once.
That writes ≤25k rows; the table is `INSERT OR REPLACE` so it's idempotent.

### Dismissed Bundles Are Not Projected Into The Index

`sync_dismissed_agent_artifact_index()` writes only the identities passed in,
which today are derived from `dismissed_agents.json`. The dismissed-bundle
store (`src/sase/ace/dismissed_bundle_index/`) is a separate sqlite/JSON
store with about 22k bundle summaries on this workstation. None of those
identities reach the artifact index's `dismissed_agents` table, so the SQL
exclusion subquery does not see them.

In the loader, Python compensates via `dismissed_from_loader` and the
`dismissed_suffixes` suffix-match in `_loading_helpers.py:147`, but only after
the SQL limit has already kept other rows out. The bundle dismissed
identities need a projection step. Options:

- extend `sync_agent_artifact_index_dismissed()` to also walk the bundle
  index/snapshot and write a "dismissed by bundle" entry per identity;
- or add a second core table (`dismissed_bundle_identities`) and make
  `active_where`/`completed_where` exclude either one.

### Dismissed Matching Is Too Identity-Shaped For Stale Rows

The Rust SQL excludes dismissed rows only when:

- raw suffix matches;
- derived agent type matches (`workflow` or `run`);
- cl name matches, dismissed cl is `unknown`, or artifact cl is null.

The Python post-load filter is broader in important cases. For RUNNING rows
with `cl_name == "unknown"`, it can hide by suffix. For terminal rows, it
also uses suffix-based filtering.

In the local sample, many stale index rows are `agent` rows with `cl_name`
null, while dismissed bundle summaries for the same suffix are often
`workflow` rows under `sase` or workflow-step cl names such as `checkout`,
`diff`, `main`, and `prepare`. The Rust query does not hide those rows.
Python can hide them later, but only after the SQL limit has already thrown
away everything after the first 200 candidates.

### Per-Agent Hydration Still Runs On The Hot Path

`src/sase/ace/tui/actions/agents/_loading_helpers.py:122-144` iterates every
loaded agent and, for each artifact dir, calls:

- `snapshot_cache.attempt_history_for(artifacts_dir)` — lists the
  `attempts/<N>/` directory and reads its metadata;
- `snapshot_cache.retry_state_for(artifacts_dir)` for `RUNNING` rows — reads
  `retry_state.json`.

The cache hides repeated reads, but every fresh artifact dir still costs a
stat sweep, and a refresh of, say, 200 agents pays 200 stat-and-maybe-read
operations. For a visible-inbox path this should be deferred: row rendering
only needs status, name, model/provider, timestamps, tag, parent linkage,
and unread state. Attempt history can load lazily for the selected row, the
attempts modal, and the content-search worker.

### Hidden Column Comes From The Index Row

`agent_artifacts.hidden` is materialized by the indexer from the artifact's
hidden state. The Tier 1 query relies on it being kept current. There is no
visible-inbox dependency on `hidden=1` other than excluding it, but: if
hidden state is ever toggled outside the TUI session, the index row needs an
upsert through `update_agent_artifact_index_for_marker_mutation`. Worth a
spot-check that all hidden-toggle paths route through that helper.

### Notification-Driven Refreshes Still Use The Same Path

Commit `b04684e38 fix: refresh agents when notifications arrive` wires
notification arrival → refresh. Those refreshes go through
`request_agents_refresh()`/`_schedule_agents_async_refresh()` and end up at
`_load_agents_async()`, which inherits the same Tier-1-then-arm-Tier-2 logic
and the search-promotion `or _agent_search_query` branch. No special
treatment is needed if the underlying loader is fixed; this is mostly a
reminder that the action surface that *triggers* refreshes is broader than
"user pressed `y`."

## Proposed Direction

### 1. Define A Visible-Inbox Contract

Add a loader/index contract that is not "complete history" but is complete for
normal Agents-tab visibility.

Suggested state fields:

```text
complete_visible_inbox: bool
complete_history: bool
repair_recommended: bool
repair_reason: str | None
```

Then normal Tier 1 index loads can be:

```text
complete_visible_inbox=True
complete_history=False
repair_recommended=False
```

`needs_full_history_reconcile` should derive from `not complete_visible_inbox`,
not `not complete_history`. Action `y` should promote to Tier 2 only when the
user has invoked the explicit archive/full-history command (see §5).

### 2. Stop The Pending-Flag Feedback Loop

Two complementary fixes:

- In `_loading_apply.py`, do not re-arm `_agents_history_reconcile_pending`
  when `self._agents_seen_complete_history` is already True and no lifecycle
  event has occurred since the last Tier 2. Or, simpler: drive the re-arm
  off `complete_visible_inbox` (per §1) instead of `complete_history`.
- In `actions/base.py::action_refresh`, default `y` to Tier 1 in the
  normal case. Keep an explicit modifier (`Y`, prefixed `:reconcile`, or a
  visible "Reconcile history" command) for the rare Tier 2 case.

### 3. Make The Index Query Return The Whole Visible Inbox

Replace `active + recent completed limit 200` with an inbox query:

- all live/incomplete rows that are not dismissed;
- all waiting/input-needed rows that are not dismissed;
- all completed/failed rows that are not dismissed;
- hidden rows excluded unless `include_hidden` is true.

Do not cap before visibility filtering. Split the cap so the active limit and
the completed limit are different parameters — at minimum rename
`recent_completed_limit` (since it currently bounds active too) and add an
`active_limit` distinct from it. If a cap is retained as a last-resort guard,
expose `truncated=True` in the load state and do not silently call the result
complete.

The important performance invariant should be:

```text
normal refresh cost = O(number of visible rows)
```

If a user has thousands of non-dismissed completed rows, showing thousands of
rows is legitimately expensive. That should be handled as visible-list UX, not
with a historical source scan.

### 4. Sync Dismissed Projection At Startup And Include Bundles

The local index had zero dismissed rows while the dismissed stores had tens of
thousands of identities. That makes the index unsuitable as an authoritative
visible-inbox source until a sync runs.

Recommended approach:

- store dismissed projection metadata in the index: `dismissed_agents.json`
  signature (mtime + size already used by
  `dismissed_agents_file_signature()`), dismissed bundle index version,
  projected identity count, and last sync timestamp;
- on TUI start (before the first index-backed load) compare the signatures
  and call `sync_dismissed_agent_artifact_index()` if any changed;
- extend that sync to *also* project dismissed-bundle identities (from
  `src/sase/ace/dismissed_bundle_index/`) into a dedicated table or into
  `dismissed_agents` with a source flag;
- if projection sync is too slow, return cached rows and mark
  `repair_recommended=True`, but do not schedule a full source scan.

`sase agents index gc` already knows how to rebuild and populate dismissed
identities. The TUI needs the cheap dismissed-projection subset of that work,
not necessarily the full artifact rebuild.

### 5. Fix Dismissed Matching Semantics In Core

For stale artifact rows, raw suffix is the stable identity. Agent type and
cl-name are not stable enough after marker deletion, workflow parent/child
conversion, retry, or historical migration.

A better core model is two-level:

- precise dismissed identities: `(agent_type, cl_name, raw_suffix)`;
- dismissed suffix projection: `raw_suffix`, with flags/counts describing
  which identity shapes were dismissed.

Then the normal visible-inbox SQL can exclude rows by dismissed suffix when
the row is terminal or artifact-only stale. For rows that might be truly
live, use stronger evidence before hiding:

- running marker plus live PID check remains Python-side;
- running-field/workspace-claim rows are loaded outside the artifact index
  and can preserve actually live aliases;
- artifact rows with no reliable liveness should not consume the Tier 1 cap
  merely because `done.json` was removed.

This belongs in `../sase-core` because artifact visibility is shared backend
behavior.

### 6. Stop Search From Promoting Normal Loads To Tier 2

The normal `/` Agents filter should search the current visible inbox and
cached content. It should not imply archive search.

Suggested split:

- normal Agents search: refilter current `_agents_with_children`; background
  content indexing reads only visible inbox content (already mostly the
  case via `_agent_content_search_cache`);
- explicit archive/revive search: separate command/modal that opts into
  dismissed bundles or full-history index/source paths;
- if a normal search has incomplete content index state, show partial
  results and update when the worker finishes.

Concretely, remove `or bool(self._agent_search_query)` from both call sites
in `_loading_disk.py:189,236`.

### 7. Lazy-Load Detail-Only Data

`load_agents_from_disk_with_state()` still populates attempt history for
every loaded agent (`_loading_helpers.py:127`) and retry state for every
RUNNING agent (`_loading_helpers.py:133`). The cache reduces JSON parsing,
but every refresh still lists and stats attempt metadata for each loaded
artifact directory.

For a visible-inbox design:

- eager list row fields should be limited to status, name, model/provider,
  timestamps, tag, unread state, workflow parent/child linkage, and artifact
  path;
- attempt history should load for the selected row, attempt view,
  retry-edit, or content search worker;
- retry state can stay eager for active rows only if it affects the list
  status (which today it can, via `status = "RETRYING"` rewrite).

This is secondary to fixing the index visibility cap, but it keeps the fast
path fast once the visible set is correct.

### 8. Move Full Refresh To Explicit Repair Paths

After the visible-inbox contract exists, full source scans should be
reserved for:

- `sase agents index gc/rebuild/verify`;
- explicit doctor/debug commands;
- revive/archive flows that intentionally inspect dismissed history;
- one-shot repair after detected index corruption;
- tests/repro tools that need source truth.

Startup, notifications, and idle should not automatically run Tier 2 just to
make the normal Agents tab trustworthy. The `STARTUP_TIER2_RECONCILE_DELAY_S`
timer and `_maybe_trigger_idle_tier2_reconcile()` should be removed (or
gated on `repair_recommended=True`).

## Implementation Sketch

1. Add Rust/Python wire fields for a visible-inbox query mode and load-state
   completeness (`complete_visible_inbox`, `repair_recommended`,
   `truncated`).
2. Add/maintain dismissed projection metadata in the SQLite index.
3. Update TUI startup to sync dismissed projection (JSON + bundles) before
   the first index-backed load when signatures changed.
4. Change `_query_artifact_index_for_loader()` to use the new query mode
   and report `complete_visible_inbox=True`.
5. Change `_loading_apply.py` so it does not arm Tier 2 for a complete
   visible inbox, and never re-arms after the first complete result unless
   a lifecycle event has invalidated the visible inbox.
6. Restore the `keep manual agents refresh on tier1` semantics in
   `action_refresh`, and add an explicit `Y`/command for archive reconcile.
7. Remove `or bool(_agent_search_query)` from `_load_agents()` and
   `_load_agents_async()`.
8. Add an explicit archive/full-history search path if users still need
   historical query behavior.
9. Make attempt history selected-row lazy.
10. Keep `sase agents index gc` as the manual repair hammer; optionally add
    a TUI notification when `repair_recommended=True`.

## Test Cases To Add

- Index query with 1000 stale dismissed active-like rows and 5 real visible
  rows returns all 5 visible rows and none of the stale dismissed rows.
- Dismissed projection sync populates the SQLite table from
  `dismissed_agents.json` and dismissed-bundle summaries without rebuilding
  `agent_artifacts`.
- Tier 1 visible-inbox load does not arm
  `_agents_history_reconcile_pending`.
- A Tier 2 reconcile followed by 100 dismiss/kill/revive actions does not
  silently re-promote the next `y` to Tier 2.
- Missing/corrupt/stale index marks `repair_recommended=True` but does not
  schedule a source scan on ordinary refresh.
- Normal Agents search does not pass `full_history=True`.
- Explicit revive/archive search still can opt into full-history or
  dismissed-bundle loading.
- Attempt history is not listed/statted for unselected rows during normal
  list refresh.

## Recommended First Patch

The highest-value first patch is not another scheduling tweak. It is to make
the Tier 1 path authoritative for the visible inbox:

1. **Stop the feedback loop.** In `_loading_apply.py`, gate the re-arm on
   "no Tier 2 has succeeded since the last lifecycle delta" (or simply
   `not self._agents_seen_complete_history`).
2. **Keep manual `y` on Tier 1.** Re-land the reverted
   `919d57d62 fix: keep manual agents refresh on tier1` with the gating
   above, so `y` becomes a normal index refresh.
3. **Sync dismissed projection at startup**, including bundle summaries.
4. **Exclude stale rows by suffix in core** so the 200-row cap stops being
   saturated by dismissed-historical rows.
5. **Remove search-driven `full_history=True`** in both load paths.

After that, measure `agents.load_from_disk` with `SASE_TUI_TRACE=1` and
confirm normal refreshes stay on `artifact_source=artifact_index` without a
later `tier2/source_scan` span.

## Open Questions

- Should `complete_visible_inbox` be invalidated by any lifecycle event
  (dismiss/kill/revive/launch/finalize) or only by events the index hooks
  could not catch? The current lifecycle wiring already upserts on those
  events, so in principle Tier 1 stays complete across them — but only if
  every mutation path also updates `dismissed_agents` (it does for the four
  TUI paths checked; external CLIs and the Telegram kill path need
  verification).
- How should `repair_recommended=True` be surfaced to the user? A subtle
  badge on the Agents tab title plus a `?`-help entry pointing at
  `sase agents index gc` may be enough.
- The Rust `recent_completed_limit` is shared between active and completed
  selects. Renaming is a wire-breaking change; can it be done as a
  backward-compatible add (`active_limit` and `completed_limit`, with
  `recent_completed_limit` deprecated)?
- Is there a quick-win heuristic for "active-but-actually-stale" that core
  could apply without the full dismissed projection — e.g., rows where
  `has_done_marker=0` AND `running.json` missing AND `started_at` older
  than N days? That would degrade gracefully when the dismissed projection
  is missing or out of date.

## Related Research

- `sdd/research/202605/agent_artifact_loading_startup.md` — Tier 1 startup
  scan reduction.
- `sdd/research/202605/active_agent_artifacts_for_tui.md` — earlier framing of
  the visible vs historical distinction.
- `sdd/research/202605/agents_tab_reproduction_harness.md` — replay harness
  for reproducing list-state bugs.
- `sdd/research/202605/dismissed_agent_archive_and_query_language.md` — how
  dismissed bundles relate to the artifact index.
- `sdd/research/202605/rebuild_from_scratch_performance.md` — costs of full
  index rebuild.
- `sdd/epics/202605/agent_artifact_index_lifecycle.md` — the `sase-3s` epic
  this work continues.
