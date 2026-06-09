---
create_time: 2026-06-09 15:30:20
status: done
prompt: sdd/prompts/202606/revive_bundle_reprojection.md
---
# Plan: Revived agents get re-hidden by stale dismissed bundles

## Problem (user report)

Reviving agents with the `R` keymap on the Agents tab does not durably update the agent index/database. Agents whose
names start with `43.f1.f1.f1.cld.f1.f1.` were dismissed and later revived, but they keep disappearing from the Agents
tab and only reappear after a **full agent refresh**. The user suspects the index isn't being updated correctly on
revive — and that suspicion is correct.

## Root cause

When an agent is revived, the revive flow correctly:

- restores the live on-disk artifact markers (`_restore_agent_artifacts`),
- removes the agent's identity from the in-memory dismissed set and from `~/.sase/dismissed_agents.json`
  (`save_dismissed_agents`), and
- replaces the artifact-index `dismissed_agents` table from the authoritative set via
  `sync_dismissed_agent_artifact_index(self._dismissed_agents, added=())` (`_revive_execution.py:104,288`).

But it then calls `mark_bundles_revived_by_suffixes(...)` (`_revive_execution.py:117,314`), and **that function is a
no-op**:

```python
# src/sase/ace/dismissed_agents_bundles.py:132
def mark_bundles_revived_by_suffixes(ctx, suffixes, *, revived_at=None):
    """Preserve dismissed bundles after revive without archive lifecycle markers."""
    del revived_at
    if not suffixes:
        return 0
    return len(ctx._bundle_paths_for_suffixes(suffixes))   # counts, deletes nothing
```

It computes the matching bundle paths and returns the count, but never deletes the dismissed-bundle files nor their rows
in the dismissed-bundle summary index (`dismissed_bundles/index.sqlite`). The daemon write path that used to record
revival was removed in the sase-3e revert (commit `5a65fa4`), and even before that the non-daemon `direct_writer`
fallback also only returned a count — so this has effectively never purged revived bundles in direct mode.

Why that breaks visibility: the artifact-index **dismissed projection** is built from the in-memory dismissed set
**unioned with every dismissed-bundle summary**:

```python
# src/sase/core/agent_artifact_index_lifecycle.py:148 build_dismissed_agent_projection_inputs
identities = {_identity_to_wire(i) for i in dismissed_identities}
for summary in load_dismissed_bundle_summaries(limit=None):   # :174
    identities.add(_dismissed_summary_identity(summary))
```

This projection is what populates the index `dismissed_agents` table, and it is re-derived from bundles by:

- `sase agents index gc` (`cli_index.py:229` → `_load_dismissed_identities_for_gc` →
  `build_dismissed_agent_projection_inputs`, `cli_index.py:265`),
- cold-start archive maintenance (`ensure_dismissed_archive_ready` / `rebuild_dismissed_bundle_index`), and
- any non-authoritative `sync_dismissed_agent_artifact_index(..., added=None)` that hits projection-metadata drift
  (`agent_artifact_index_lifecycle.py:96-119`) — e.g. the normal-refresh persistence path in
  `_loading_apply.py:316-323`.

Because the revived agent's bundle is never removed, **every** projection rebuild re-inserts the revived agent into the
index `dismissed_agents` table. The index-backed (Tier 1) loader queries with `include_hidden=False` and a 200-row
recent-completed window (`agent_loader.py:155-162`), so the re-projected agent is filtered out again. A **full (Tier 2)
refresh** scans source artifacts directly, bypasses the index, and filters only by the in-memory dismissed set (which no
longer contains the revived agent) — so it is the only refresh that reliably shows the revived agent. That is exactly
the reported symptom.

Note: `sase agents index gc` (the documented repair command surfaced in the Tier 1 "repair recommended" notice) actually
makes this worse — it rebuilds the dismissed projection from the lingering bundles and re-hides the revived agents.

### Evidence from the live `~/.sase` data

- The two revived top-level agents `43.f1.f1.f1.cld.f1.f1.cld` (ts `20260609112233`) and `...cdx` (ts `20260609112234`)
  are **absent** from `dismissed_agents.json` and from the index `dismissed_agents` table (correctly revived), **yet
  both still have 7 bundle-summary rows each** in `dismissed_bundles/index.sqlite`. A single projection rebuild (gc /
  cold start / drift) would re-hide both.
- The index `dismissed_agents` table holds 36,146 rows; ~8,576 of the distinct suffixes that are _not_ in the JSON set
  trace directly back to bundle summaries — confirming the projection is dominated by bundle-derived identities.
- `_restore_agent_artifacts` restores live markers but never touches the dismissed bundle, so the bundle persists across
  the revive.

### Why deleting only summary rows is insufficient

`verify_index`/`index_signature` (`dismissed_bundle_index/_api.py:38,178`) compare the on-disk bundle count against
indexed rows. If we delete summary rows but leave the bundle files, the next `verify` fails and
`rebuild_dismissed_bundle_index` re-scans the files and re-adds the summaries. The bundle **files** must be removed too.
The correct pattern already exists in the name-wipe path (`agent/names/_wipe.py:378-382`): `path.unlink()` each bundle
file **and** `delete_bundle_summaries_for_suffixes(bundles_dir, suffixes)`.

## Proposed fix

Primary: make revive actually purge the revived agents' dismissed bundles so they stop feeding the dismissed projection.

1. **Implement `mark_bundles_revived_by_suffixes` for real** (`src/sase/ace/dismissed_agents_bundles.py:132`). For the
   given suffixes:
   - resolve bundle paths via `ctx._bundle_paths_for_suffixes(suffixes)`,
   - `unlink()` each bundle file (ignoring `FileNotFoundError`),
   - call `delete_bundle_summaries_for_suffixes(ctx.dismissed_bundles_dir(), suffixes)` to drop the summary rows,
   - return the number of bundles removed.

   This mirrors `_wipe.py` and makes the function's name accurate. Revive has already restored the live artifacts, so
   the dismissed bundle is redundant; if the user re-dismisses, the dismiss flow writes a fresh bundle.

2. **Sequence the purge before the index sync** in `_do_revive_agent` / `_do_revive_agents` (`_revive_execution.py`).
   Purge bundles, then call the authoritative `sync_dismissed_agent_artifact_index(...)`, so the projection metadata
   signature recorded reflects the post-purge bundle index and a later drift-triggered rebuild cannot re-add the revived
   agents.

3. **Pass the complete revived-suffix set.** Confirm `revived_suffixes` / `succeeded_suffixes` include every restored
   artifact (parent + all child/ descendant dirs that revive recreated) so nested bundles are purged too, not just the
   top-level parent's bundle.

Alternative considered (not recommended): keep bundle files and add a persisted `revived` marker that `query_summaries`,
`verify_index`, `rebuild_index`, and `build_dismissed_agent_projection_inputs` all skip. This preserves the archived
bundle but is far more invasive (touches the bundle scan/verify/signature surface) for no clear product benefit, since
revive already restores the live artifacts.

## Cleaning up existing stale state

The fix prevents recurrence but does not retroactively remove bundles for agents already revived before the fix. After
landing the code change, provide a one-time reconciliation so the user's current index is correct:

- Add a small maintenance step (or document the procedure) that purges dismissed-bundle files + summary rows for
  identities that are present in the bundle index but absent from `dismissed_agents.json`, then runs
  `replace_agent_artifact_index_dismissed_agents` from the corrected projection.
- Explicitly call out that `sase agents index gc` alone is **not** a fix here (it rebuilds from bundles); it is only
  safe to run _after_ the stale bundles are purged.

## Tests

- Unit: dismiss → revive an agent; assert its bundle files and summary index rows are gone and
  `build_dismissed_agent_projection_inputs()` no longer contains its identity; assert `verify_dismissed_bundle_index()`
  reports ok (no count mismatch).
- Regression (the reported bug): dismiss an agent, revive it, then trigger a projection rebuild (`sase agents index gc`
  / non-authoritative sync / cold-start path) and assert the agent is **not** re-added to the index `dismissed_agents`
  table and remains visible on an index-backed (Tier 1) load.
- Cover nested families: revive a parent whose dismissed children/descendants were restored, and assert all of their
  bundles are purged.

## Scope / boundary notes

- The dismissed-bundle storage, summary index, and projection inputs are all Python in this repo
  (`src/sase/ace/dismissed_agents_bundles.py`, `src/sase/ace/dismissed_bundle_index/`,
  `src/sase/core/agent_artifact_index_lifecycle.py`). The artifact-index query/replace is Rust in `sase-core`, but no
  Rust change is required — the fix is in how the Python projection inputs are derived (bundles purged on revive).
- Out of scope but worth a follow-up: the descendants `20260609135023` / `20260609135024` (a sub-workflow under
  `...cdx`) are still genuinely dismissed in `dismissed_agents.json`. If reviving a parent is expected to cascade to
  deeper descendants, the revive child-collection logic (`is_child_of`, single-level) may need a separate look; this
  plan does not change cascade behavior.
