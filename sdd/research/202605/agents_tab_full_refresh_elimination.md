# Agents Tab Full Refresh Elimination Research

Date: 2026-05-21

## Question

The Agents tab now has a Tier 1 index-backed refresh path from the `sase-3s`
epic, but full refreshes are still common and very slow. The goal is to make a
full source scan almost never necessary for the agent entries shown in the
normal Agents tab.

## Short Answer

Treat the normal Agents tab as a visible inbox backed by the artifact index,
not as an incomplete slice of history that eventually needs Tier 2. Full
refreshes should move to explicit repair/archive/revive/debug workflows.

The current Tier 1 path is still not authoritative for the visible inbox:

- it returns `active + recent completed limit 200`, not all visible
  non-dismissed entries;
- it is always marked `complete_history=False`, so the TUI arms deferred Tier 2;
- the active query can be saturated by stale historical rows that look active
  after dismissal deletes marker files;
- normal agent search still promotes loads to `full_history=True`;
- the dismissed projection in the local index can drift badly from
  `dismissed_agents.json` and dismissed bundles.

## Code Findings

### Current Tier 1 Query

`src/sase/ace/tui/models/agent_loader.py` uses
`_query_artifact_index_for_loader(full_history=False)` when the index exists.
That constructs:

```python
AgentArtifactIndexQueryWire(
    include_active=True,
    include_recent_completed=True,
    include_full_history=False,
    recent_completed_limit=200,
    include_hidden=False,
)
```

The Rust query in `../sase-core/crates/sase_core/src/agent_scan/index.rs` runs
separate `active_where` and `completed_where` selects. The same
`recent_completed_limit` is applied to the active query and the completed query.
This is only safe if the active query already excludes stale dismissed rows
before the limit.

### Tier 1 Is Still Considered Incomplete

`AgentLoadState.needs_full_history_reconcile` is `not complete_history`.
The index path returns `complete_history=False`, and
`src/sase/ace/tui/actions/agents/_loading_apply.py` arms
`_agents_history_reconcile_pending` for every Tier 1 apply. The current manual
`y` path stays Tier 1, but idle/startup can still trigger a full Tier 2 source
scan through `_maybe_trigger_idle_tier2_reconcile()`.

That means the product contract is still "Tier 1 first paint, Tier 2 later",
not "Tier 1 is complete for what the Agents tab shows."

### Search Still Forces Full History

Both sync and async load paths in
`src/sase/ace/tui/actions/agents/_loading_disk.py` pass:

```python
full_history=full_history or bool(getattr(self, "_agent_search_query", ""))
```

So any normal Agents-tab query can still bypass the index and promote a refresh
into a Tier 2 scan. The in-memory refilter/content-index work exists, but the
subsequent scheduled disk refresh still uses full history when a query is
active.

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
the cap is applied before the Python dismissed filter has a chance to remove
stale rows.

### Dismissed Matching Is Too Identity-Shaped For Stale Rows

The Rust SQL excludes dismissed rows only when:

- raw suffix matches;
- derived agent type matches (`workflow` or `run`);
- cl name matches, dismissed cl is `unknown`, or artifact cl is null.

The Python post-load filter is broader in important cases. For RUNNING rows
with `cl_name == "unknown"`, it can hide by suffix. For terminal rows, it also
uses suffix-based filtering.

In the local sample, many stale index rows are `agent` rows with `cl_name` null,
while dismissed bundle summaries for the same suffix are often `workflow` rows
under `sase` or workflow-step cl names such as `checkout`, `diff`, `main`, and
`prepare`. The Rust query does not hide those rows. Python can hide them later,
but only after the SQL limit has already thrown away everything after the first
200 candidates.

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

The TUI should not arm Tier 2 just because `complete_history=False`. It should
arm repair only when the index is missing, stale, corrupt, or explicitly
requested.

### 2. Make The Index Query Return The Whole Visible Inbox

Replace `active + recent completed limit 200` with an inbox query:

- all live/incomplete rows that are not dismissed;
- all waiting/input-needed rows that are not dismissed;
- all completed/failed rows that are not dismissed;
- hidden rows excluded unless a hidden/include-hidden mode is active.

Do not cap before visibility filtering. If a cap is retained as a last-resort
guard, expose `truncated=True` in the load state and do not silently call the
result complete.

The important performance invariant should be:

```text
normal refresh cost = O(number of visible rows)
```

If a user has thousands of non-dismissed completed rows, showing thousands of
rows is legitimately expensive. That should be handled as visible-list UX, not
with a historical source scan.

### 3. Sync Dismissed Projection Before Trusting Tier 1

The local index had zero dismissed rows while the dismissed stores had tens of
thousands of identities. That makes the index unsuitable as an authoritative
visible-inbox source.

Recommended approach:

- store dismissed projection metadata in the index: source file signature,
  dismissed bundle index signature/version, projected identity count, and last
  sync timestamp;
- before the first Agents-tab index query, cheaply compare signatures;
- if the projection is stale, update only `dismissed_agents`, not the whole
  artifact table;
- include dismissed bundle summaries in the projection, matching the `gc`
  command's behavior;
- if projection sync is too slow, return cached rows and mark
  `repair_recommended=True`, but do not schedule a full source scan.

`sase agents index gc` already knows how to rebuild and populate dismissed
identities. The TUI needs the cheap dismissed-projection subset of that work,
not necessarily the full artifact rebuild.

### 4. Fix Dismissed Matching Semantics In Core

For stale artifact rows, raw suffix is the stable identity. Agent type and
cl-name are not stable enough after marker deletion, workflow parent/child
conversion, retry, or historical migration.

A better core model is two-level:

- precise dismissed identities: `(agent_type, cl_name, raw_suffix)`;
- dismissed suffix projection: `raw_suffix`, with flags/counts describing which
  identity shapes were dismissed.

Then the normal visible-inbox SQL can exclude rows by dismissed suffix when the
row is terminal or artifact-only stale. For rows that might be truly live, use
stronger evidence before hiding:

- current running marker plus live process check remains Python-side;
- running-field/workspace-claim rows are loaded outside the artifact index and
  can preserve actually live aliases;
- artifact rows with no reliable liveness should not consume the Tier 1 cap
  merely because `done.json` was removed.

This belongs in `../sase-core` because artifact visibility is shared backend
behavior.

### 5. Stop Search From Promoting Normal Loads To Tier 2

The normal `/` Agents filter should search the current visible inbox and cached
content. It should not imply archive search.

Suggested split:

- normal Agents search: refilter current `_agents_with_children`; background
  content indexing reads only visible inbox content;
- explicit archive/revive search: separate command/modal that opts into
  dismissed bundles or full-history index/source paths;
- if a normal search has incomplete content index state, show partial results
  and update when the worker finishes.

This removes a major remaining accidental full-history trigger.

### 6. Lazy-Load Detail-Only Data

`load_agents_from_disk_with_state()` still populates attempt history for every
loaded agent. The cache reduces JSON parsing, but every refresh still lists and
stats attempt metadata for each loaded artifact directory.

For a visible-inbox design:

- eager list row fields should be limited to status, name, model/provider,
  timestamps, tag, unread state, workflow parent/child linkage, and artifact
  path;
- attempt history should load for the selected row, attempt view, retry-edit,
  or content search worker;
- retry state can stay eager for active rows only if it affects the list status.

This is secondary to fixing the index visibility cap, but it keeps the fast
path fast once the visible set is correct.

### 7. Move Full Refresh To Explicit Repair Paths

After the visible-inbox contract exists, full source scans should be reserved
for:

- `sase agents index gc/rebuild/verify`;
- explicit doctor/debug commands;
- revive/archive flows that intentionally inspect dismissed history;
- one-shot repair after detected index corruption;
- tests/repro tools that need source truth.

Startup and idle should not automatically run Tier 2 just to make the normal
Agents tab trustworthy.

## Implementation Sketch

1. Add Rust/Python wire fields for a visible-inbox query mode and load-state
   completeness.
2. Add/maintain dismissed projection metadata in the SQLite index.
3. Update TUI startup/refresh to sync dismissed projection signatures before
   the first index-backed load when cheap.
4. Change `_query_artifact_index_for_loader()` to call the visible-inbox query
   and report `complete_visible_inbox=True`.
5. Change `_loading_apply.py` so it does not arm Tier 2 for a complete visible
   inbox.
6. Remove `or bool(_agent_search_query)` from `_load_agents()` and
   `_load_agents_async()`.
7. Add an explicit archive/full-history search path if users still need
   historical query behavior.
8. Make attempt history selected-row lazy.
9. Keep `sase agents index gc` as the manual repair hammer; optionally add a
   TUI notification when `repair_recommended=True`.

## Test Cases To Add

- Index query with 1000 stale dismissed active-like rows and 5 real visible
  rows returns all 5 visible rows and none of the stale dismissed rows.
- Dismissed projection sync populates the SQLite table from
  `dismissed_agents.json` and dismissed bundle summaries without rebuilding
  `agent_artifacts`.
- Tier 1 visible-inbox load does not arm `_agents_history_reconcile_pending`.
- Missing/corrupt/stale index marks `repair_recommended=True` but does not
  schedule a source scan on ordinary refresh.
- Normal Agents search does not pass `full_history=True`.
- Explicit revive/archive search still can opt into full-history or dismissed
  bundle loading.
- Attempt history is not listed/statted for unselected rows during normal list
  refresh.

## Recommended First Patch

The highest-value first patch is not another scheduling tweak. It is to make the
index authoritative for the visible inbox:

1. Add dismissed-projection sync from `dismissed_agents.json` and bundle
   summaries before index-backed Agents loads.
2. Change Rust dismissed matching so stale artifact rows are excluded by raw
   suffix before the active/recent limits apply.
3. Change Tier 1 load state so a healthy visible-inbox query does not request
   Tier 2.
4. Remove search-driven `full_history=True`.

After that, measure `agents.load_from_disk` with `SASE_TUI_TRACE=1` and confirm
normal refreshes stay on `artifact_source=artifact_index` without a later
`tier2/source_scan` span.
