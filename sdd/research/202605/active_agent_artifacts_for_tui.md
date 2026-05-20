# Active Agent Artifacts For The TUI

Date: 2026-05-20

## Question

The Agents tab still has expensive disk-loading behavior. Would it be feasible and advisable to store active agents
(running, waiting, or done-but-not-dismissed) in a separate directory, scan only that active directory for the normal
Agents tab, and move artifacts out of that directory when the user dismisses an agent?

## Short Answer

The goal is sound: the normal Agents tab should not walk the full historical artifact corpus. The exact implementation
of physically moving canonical artifact directories is feasible but not advisable as the first design. SASE already has
a canonical artifact layout, dismissed bundles, a compact dismissed identity index, a Rust artifact scanner, and a
SQLite artifact index that can answer "active plus recent completed" queries. Moving canonical directories would add a
second source-of-truth transition at precisely the most failure-prone lifecycle edge: agent completion, dismissal,
external kill, revive, retry handoff, and named-agent lookup.

The better high-level solution is:

1. Keep canonical artifact directories at `~/.sase/projects/<project>/artifacts/<workflow>/<timestamp>`.
2. Treat "active" as indexed metadata, not as physical location.
3. Make the Rust-backed artifact index the maintained active materialized view.
4. Update that index on artifact creation, marker writes, completion, dismissal, revive, and external cleanup.
5. Let the normal TUI load query only active plus recent completed rows from the index.
6. Use full source scans only for explicit full-history actions, index verification/rebuild, and fallback.

If a directory-based active set is still desired, make it a non-authoritative ref directory of symlinks or small JSON
pointer files, not a move of the canonical artifact trees.

## Current Behavior

### Canonical artifact layout

Agent artifacts are created under:

```text
~/.sase/projects/<project>/artifacts/<workflow>/<YYYYmmddHHMMSS>/
```

The generic creator is `src/sase/artifacts.py:create_artifacts_directory()`. Normal TUI-launched agents use
`src/sase/axe/run_agent_runner_setup.py:setup_artifacts_directory()` to create an `ace-run` artifact directory and seed
`workflow_state.json` so the TUI can see the row before the final `done.json` exists.

The loader expects this layout. `src/sase/ace/tui/models/agent_artifacts.py:get_artifacts_dir()` reconstructs artifact
paths from project file, workflow, and raw suffix unless a marker provided an explicit `artifacts_dir`.

### Agents tab load path

`src/sase/ace/tui/models/agent_loader.py` is already tiered:

- Tier 1 tries `~/.sase/agent_artifact_index.sqlite` through `query_agent_artifact_index()`.
- If the index is missing or bad, Tier 1 falls back to a bounded source scan with `max_records=200` and `newest_first=True`.
- Tier 2 does a full source scan for deliberate full-history reconciliation.

The TUI scan options include prompt-step markers but skip raw prompt snippets. The current Rust scanner walks
`~/.sase/projects/*/artifacts/<supported workflow>/<timestamp>` and parses marker files into an
`AgentArtifactScanWire`.

### Existing performance evidence

`sdd/research/202605/ace_startup_profile_20260502.md` found the historical cold worker path around
`load_agents_from_disk()` took roughly 3-4 seconds in a large local corpus. The biggest buckets were dismissed bundle
hydration and artifact scanning/hydration:

- thousands of dismissed bundles;
- thousands of loaded agent rows;
- full artifact-tree scan and Python wire hydration.

The current code has since added a persistent artifact index and lazy/full-history tiering, so the first question should
be whether that index is maintained and queried reliably before adding another filesystem layout.

### Dismissal today

Dismissal currently does not move the artifact directory. The TUI:

- saves a dismissed bundle for revive (`src/sase/ace/dismissed_agents_bundles.py`);
- adds identities to `~/.sase/dismissed_agents.json`;
- removes loader-visible marker files from the artifact directory through
  `src/sase/ace/tui/actions/agents/_killing_utils.py:delete_agent_artifacts()`.

The Rust cleanup side-effect path has the same semantic shape:
`../sase-core/crates/sase_core/src/agent_cleanup/execution.rs:delete_agent_artifact_markers()` removes loader marker
files rather than moving directories.

Revive restores the minimal marker files needed for rediscovery in
`src/sase/ace/tui/actions/agents/_revive_artifacts.py`.

## Critique Of A Physical Active Directory

### What would work

The plan is feasible if implemented consistently:

- create new agent artifact directories under an active root;
- teach every producer and consumer to derive artifact paths from that root;
- on completion, leave done-but-not-dismissed artifacts in the active root;
- on dismiss, atomically save dismissed bundles and move the tree to an archive root;
- on revive, move it back or restore marker files in the active root;
- teach the Rust scanner to scan only the active root for normal TUI loads.

That would bound normal scan cost by active rows instead of historical rows. It also maps well to inotify: the watcher
could watch a smaller tree.

### Why it is risky

The artifact path is not just storage. It is part of several runtime contracts:

- `Agent.get_artifacts_dir()` reconstructs canonical paths from project/workflow/timestamp.
- named-agent lookup, resume, and wait resolution scan `~/.sase/projects/*/artifacts/ace-run/*`;
- the name registry rebuild scans artifact directories and dismissed bundles;
- notifications store `raw_suffix` and may include artifact-related paths;
- retry chains store parent/child timestamps and artifact metadata;
- revive expects dismissed bundles to be enough to restore loader markers;
- external kill/dismiss paths update `dismissed_agents.json` and remove markers, but do not have a full in-memory
  `Agent` object or bundle save in every path.

Moving full directories would force all of those consumers either to follow archive paths or to treat the active root as
canonical. Both choices are invasive.

There is also a correctness problem around paths embedded inside artifacts. `done.json`, `agent_meta.json`, bundle
dicts, notifications, explicit artifact indexes, and logs can carry absolute paths. Moving the directory invalidates any
field that points inside it unless the move layer rewrites data or every reader tolerates stale paths.

Finally, moving directories is not a small dismiss side effect. Dismiss currently has a good failure model: save bundle,
delete a few marker files, save the dismissed index. If marker deletion fails, the dismissed index can still suppress the
row. A directory move makes partial failure states more varied: bundle saved but move failed, move succeeded but index
write failed, active symlink stale, archive row missing from name registry, revive restoring to the wrong location, and
so on.

## Better Interpretation Of "Active Directory"

The valuable part of the proposal is not the physical directory. It is the invariant:

> Normal Agents tab loads should enumerate only active rows and a bounded recent completed set.

SASE already has the right abstraction for that invariant: `agent_artifact_index.sqlite`.

The index stores one row per artifact directory with denormalized fields such as `has_done_marker`, `workflow_status`,
`hidden`, timestamps, model/provider, and the scanner-shaped `record_json`
(`../sase-core/crates/sase_core/src/agent_scan/index.rs`). Query options already include:

- `include_active`;
- `include_recent_completed`;
- `include_full_history`;
- `recent_completed_limit`;
- `include_hidden`.

This is almost exactly the "active artifacts directory" idea, except the active set is a materialized query instead of a
new tree of files.

## Recommended High-Level Implementation

### Recommendation

Do not move canonical artifact directories for the normal TUI optimization. Instead, make the persistent artifact index
authoritative for fast TUI enumeration while keeping artifacts as the source of truth.

### Phase 1: Maintain the artifact index incrementally

Add a small core-facing lifecycle API around the existing index calls:

- `mark_artifact_changed(artifact_dir)`: upsert one row.
- `mark_artifact_removed_or_hidden(artifact_dir)`: delete one row or update row visibility.
- `rebuild_artifact_index_if_missing_or_stale()`: one-time safety net.

Wire it into these events:

- artifact directory creation after `workflow_state.json` is seeded;
- `agent_meta.json` writes;
- `running.json` writes/removals for home-mode agents;
- `done.json` writes;
- prompt-step marker writes for workflow children;
- dismissal marker deletion;
- revive marker restoration;
- external kill cleanup.

The existing Rust APIs already expose `upsert_agent_artifact_index_row()` and `delete_agent_artifact_index_row()`, so
this phase is mostly wiring, tests, and deciding whether dismissed rows should be deleted from the index or retained
with a hidden/dismissed state.

### Phase 2: Query active rows by default

Keep the current TUI Tier 1 shape, but make it the primary happy path:

```text
include_active = true
include_recent_completed = true
recent_completed_limit = configurable/default 200
include_full_history = false
```

If the index is missing, start with the existing bounded source scan, schedule an async rebuild, and show an incomplete
history state until the index is ready. Tier 2 full scans remain available for revive, search, diagnostics, and explicit
history reconciliation.

### Phase 3: Make dismissal update the index

When a user dismisses an agent:

1. Optimistically remove it from the in-memory TUI list, as today.
2. Save dismissed bundle(s), as today.
3. Save the dismissed identity index, as today.
4. Delete loader marker files, as today.
5. Delete or mark the artifact-index row(s) inactive.

This gives the desired behavior: future normal TUI loads do not scan or hydrate dismissed artifacts. The canonical
artifact directory can stay put for logs, explicit artifacts, and forensic inspection.

### Phase 4: Optional ref directory

If there is still value in a filesystem-visible active set, add:

```text
~/.sase/active_agent_artifacts/<project>/<workflow>/<timestamp>.json
```

or symlinks to canonical artifact directories. Treat this as a cache generated from the index, not as source of truth.
The TUI should be able to rebuild it from canonical artifacts or the SQLite index. Dismiss removes the pointer, not the
artifact tree.

## Edge Cases To Design Explicitly

- **Done but not dismissed**: these are active for TUI purposes and must remain in the active query until dismissed or
  auto-dismissed.
- **Running agents with stale PIDs**: liveness checks still belong outside the scanner; index rows cannot be trusted as
  proof that a process is alive.
- **Home-mode agents**: `running.json` is the running marker and is removed at shutdown. Completion writes `done.json`.
- **Workflow parents and children**: dismissing a workflow parent must update every child row/prompt-step row represented
  by the parent timestamp.
- **Appears-as-agent workflows**: some workflows live under `ace-run` but are represented as workflow entries.
- **Retries and follow-ups**: retry-chain and plan-chain pointers rely on raw suffixes and parent timestamps; index
  updates must preserve these records.
- **External tools**: `sase agents kill`, mobile integrations, Telegram/GChat, and name lookup paths must update or
  tolerate the index.
- **Revive**: after restoring markers, upsert the restored rows and force a full-history reconciliation only when needed.
- **Index corruption**: keep `sase agents index verify/rebuild` and automatic bounded fallback.

## Test Plan

Add focused tests rather than relying on full TUI runs:

- TUI Tier 1 uses the index and does not source-scan when the index is present.
- Launch/setup writes or upserts an active row.
- Completion upserts `done.json` data and keeps the row visible.
- Dismiss saves bundle, removes marker files, and removes/marks inactive the indexed rows.
- Revive restores marker files and upserts indexed rows.
- Workflow parent dismissal updates child rows.
- Missing/corrupt index falls back to bounded source scan and schedules rebuild.
- External kill path updates dismissed identity state and index state.

## Conclusion

The proposal is directionally right but should be implemented as an active materialized view, not by relocating canonical
artifact directories. This keeps the TUI fast while preserving the existing artifact path contract, dismissed-bundle
revive model, name lookup behavior, and forensic value of historical artifact directories.

The most pragmatic next implementation target is to finish the artifact-index lifecycle: make index upserts/deletes
happen at all artifact lifecycle mutation points, then let the Agents tab trust the active/recent query for normal
refreshes.
