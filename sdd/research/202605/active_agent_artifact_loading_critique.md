# Active Agent Artifact Loading Critique

Date: 2026-05-20

## Question

The Agents tab can become inefficient when it loads years of agent artifact history. One proposed mitigation is to store
active agent artifacts in a separate directory, scan only that active directory for normal Agents-tab loads, and move an
agent's artifacts out of that active directory when the user dismisses it.

This note critiques that plan against the current implementation and recommends a high-level path.

## Short Answer

The plan is feasible, but physically moving canonical artifact directories is not the best first implementation. The
advisable version is to make "active artifacts" a maintained materialized view, not a new source-of-truth directory.

SASE already has most of the right machinery:

- the TUI loader has a Tier 1 path that queries `~/.sase/agent_artifact_index.sqlite` before falling back to source
  scans (`src/sase/ace/tui/models/agent_loader.py:121`);
- Rust core has rebuild, upsert, delete, and query APIs for that index
  (`../sase-core/crates/sase_core/src/agent_scan/index.rs:73`);
- dismissal already runs asynchronously and removes loader-visible marker files instead of deleting whole artifact
  trees (`src/sase/ace/tui/actions/agents/_killing_utils.py:12`);
- revive already restores marker files into the canonical artifact location
  (`src/sase/ace/tui/actions/agents/_revive_artifacts.py:24`).

The high-level solution should be: keep canonical artifacts where they are, maintain an active/recent artifact index
incrementally, and make dismissal remove or mark rows inactive in that index. If a filesystem-visible "active"
directory is still wanted, implement it as symlinks or small pointer files generated from the index, not by moving the
canonical artifact trees.

## Current Scale

On this workstation at research time:

| Corpus | Count / size |
| --- | ---: |
| `~/.sase/projects` artifact timestamp directories | 13,508 |
| JSON marker files under `~/.sase/projects` | 50,113 |
| `~/.sase/dismissed_bundles/**/*.json` | 22,469 |
| `~/.sase/projects` size | 831 MB |
| `~/.sase/dismissed_bundles` size | 187 MB |
| `~/.sase/agent_artifact_index.sqlite` size | 76 MB |

This validates the underlying concern. Any normal TUI refresh that scales with all historical timestamp directories will
get worse with years of daily use. The target should be `O(active + recent completed)` for normal Agents-tab loads, with
explicit full-history operations paying the archival cost.

## Current Loading Model

`src/sase/ace/tui/models/agent_loader.py` already uses a tiered design:

- Tier 1 queries `default_agent_artifact_index_path()` when the index exists.
- The Tier 1 query includes active rows and a bounded recent-completed window of 200 rows.
- If the index is missing or bad, Tier 1 falls back to a bounded source scan.
- Tier 2 forces a full source scan for deliberate full-history needs.

Relevant code:

- `_TIER1_RECENT_COMPLETED_LIMIT = 200` and bounded fallback options are defined at
  `src/sase/ace/tui/models/agent_loader.py:67`.
- `_query_artifact_index_for_loader()` builds an `AgentArtifactIndexQueryWire` with active plus recent completed rows at
  `src/sase/ace/tui/models/agent_loader.py:121`.
- `_artifact_snapshot_for_tui_load()` makes full history an explicit Tier 2 path at
  `src/sase/ace/tui/models/agent_loader.py:171`.

Rust core's index is also already shaped like the desired active set:

- `agent_artifacts` has one row per artifact directory and stores denormalized status, marker-presence, hidden,
  timestamp, model/provider, parent/step, retry, and marker-signature fields
  (`../sase-core/crates/sase_core/src/agent_scan/index.rs:241`).
- `query_agent_artifact_index()` can combine active, recent completed, and full-history slices
  (`../sase-core/crates/sase_core/src/agent_scan/index.rs:160`).
- The active predicate is currently marker/status based: no `done.json`, or workflow status not terminal
  (`../sase-core/crates/sase_core/src/agent_scan/index.rs:442`).

## Dismissal Today

Dismissal is already close to the desired lifecycle hook:

1. The TUI optimistically removes rows in memory.
2. The worker saves dismissed bundles for revive.
3. The worker releases workflow workspaces where needed.
4. The worker removes loader-visible marker files from artifact directories.
5. The worker dismisses matching notifications.
6. The worker saves the compact dismissed identity index.

The side-effect path lives in `src/sase/ace/tui/actions/agents/_dismiss_persistence.py:18` and
`src/sase/ace/tui/actions/agents/_dismiss_persistence.py:94`.

The important detail is that dismissal does not currently move or delete the artifact directory. It deletes marker files
that cause rediscovery: `workflow_state.json`, `done.json`, and `prompt_step_*.json`
(`src/sase/ace/tui/actions/agents/_killing_utils.py:12`). Rust's cleanup execution has the same semantic shape.

This keeps dismissal relatively cheap and gives it a simple failure model. A failed marker cleanup is recoverable because
the dismissed identity index can still hide the row.

## Critique Of Physical Moves

A physical active directory can work, but it would force a storage migration into many contracts that currently assume
canonical artifact paths:

- The scanner walks `~/.sase/projects/<project>/artifacts/<workflow>/<timestamp>` and validates that exact relative
  layout (`../sase-core/crates/sase_core/src/agent_scan/scanner.rs:219`).
- The candidate enumeration walks every timestamp directory before marker parsing
  (`../sase-core/crates/sase_core/src/agent_scan/scanner.rs:107`).
- Revive reconstructs marker files in the original canonical project/artifacts layout
  (`src/sase/ace/tui/actions/agents/_revive_artifacts.py:50`).
- Dismissed bundles, notifications, explicit artifacts, retry metadata, wait/resume lookup, name lookup, and run logs
  can contain raw suffixes or artifact paths that assume stable locations.

The largest product risk is not that `rename(2)` is impossible. It is that artifact paths are part of the runtime API.
Moving directories would add a second lifecycle transition at the most failure-prone moment: done -> dismissed -> archived
or revived.

It also complicates the "save chats and artifacts for all time" goal. Moving a directory preserves more marker files
than today's marker deletion, but it also makes embedded absolute paths stale unless every reader tolerates old paths or
the move layer rewrites metadata. A long-lived archive needs stable references more than it needs a physically separate
active tree.

## Index Nuance

The current index must be handled carefully. It cannot simply rebuild from source and treat "no done marker" as active.

The Rust scanner enumerates all supported timestamp directories, then parses whatever marker files exist
(`../sase-core/crates/sase_core/src/agent_scan/scanner.rs:51`). If a dismissed artifact directory still exists but its
`done.json` or `workflow_state.json` was removed, a naive rebuilt index can classify the row as active-like because the
active predicate includes `has_done_marker = 0`.

That means dismissal/index integration should choose one explicit invariant:

- either remove dismissed artifact rows from the normal index and teach rebuild/verify to exclude dismissed identities;
- or add a `dismissed` / `visible_in_agents_tab` column and compute it from `dismissed_agents.json` plus bundle/index
  state;
- or leave historical rows indexed but make the normal query filter them with a durable dismissed flag.

Deleting the index row during dismissal is good enough only if a later rebuild will not reintroduce the row as active.

## Recommended Implementation

### 1. Keep canonical artifacts in place

Do not move `~/.sase/projects/<project>/artifacts/<workflow>/<timestamp>` as the primary optimization. Keep the
artifact tree as the source of truth and keep dismissed bundles as the revive/archive representation.

### 2. Promote the artifact index to the active materialized view

Use the existing Rust APIs exposed by `src/sase/core/agent_scan_facade.py:91`:

- `rebuild_agent_artifact_index()`
- `upsert_agent_artifact_index_row()`
- `delete_agent_artifact_index_row()`
- `query_agent_artifact_index()`
- `verify_agent_artifact_index()`

Add a small Python/Rust lifecycle wrapper with project defaults so callers do not hand-roll index paths:

- `record_artifact_changed(artifact_dir)`
- `record_artifact_dismissed(artifact_dir, identity)`
- `record_artifact_revived(artifact_dir)`
- `rebuild_artifact_index_if_missing()`

Because this behavior is shared backend semantics for TUI, CLI, mobile, and future web surfaces, the durable visibility
rules belong in `../sase-core` behind the Rust core boundary.

### 3. Wire index updates at lifecycle mutation points

Update the index when:

- an artifact directory is created and `workflow_state.json` or initial metadata is written;
- `agent_meta.json`, `running.json`, `waiting.json`, `pending_question.json`, `workflow_state.json`,
  `prompt_step_*.json`, `plan_path.json`, or `done.json` changes;
- an agent is dismissed and marker files are removed;
- a workflow parent dismissal affects child prompt-step rows;
- a dismissed agent is revived and marker files are restored;
- CLI/mobile/external kill paths dismiss agents outside the live TUI;
- index rebuild or verification runs.

Dismissal should remain optimistic in memory. The worker transaction should save bundles and the dismissed index, update
artifact visibility in the SQLite index, and then remove loader markers. If index update fails, schedule a bounded
refresh/rebuild rather than blocking the UI.

### 4. Make normal Agents-tab loads trust Tier 1

The existing query shape is the right product contract:

```text
include_active = true
include_recent_completed = true
recent_completed_limit = 200
include_full_history = false
include_hidden = false
```

When the index is missing, use the current bounded fallback and schedule an async rebuild. Full source scans should be
reserved for explicit full-history operations such as archive/revive/search diagnostics or `sase agents index verify`.

### 5. Optional active directory as a cache

If a filesystem-visible active set remains useful, make it rebuildable and non-authoritative:

```text
~/.sase/active_agent_artifacts/<project>/<workflow>/<timestamp>.json
```

Each file should be a pointer to the canonical artifact directory, or a symlink if portability concerns are acceptable.
The TUI should not require this directory for correctness. Dismissal removes the pointer; revive recreates it; rebuild
can regenerate it from the index.

## Edge Cases

- Done but not dismissed agents are active for the TUI and must stay visible until dismissal or auto-dismissal.
- Running-state liveness still needs PID checks; an index row is not proof a process is alive.
- Workflow parents and children share timestamps, and parent dismissal must update child/prompt-step visibility.
- Home-mode agents use `running.json`; completion and cleanup must update the same materialized row.
- Revive should upsert rows after restoring marker files.
- Search and full-history views should explicitly opt into archival cost.
- Index corruption must remain recoverable with `sase agents index rebuild` and `sase agents index verify`.
- Any design must tolerate external dismissals from CLI/mobile/notification paths, not just TUI keybindings.

## Verdict

The plan is directionally right: normal Agents-tab loading should enumerate only active and bounded recent artifacts.
The safer implementation is not to relocate canonical artifact directories, but to finish and harden the existing
artifact-index lifecycle. Add durable dismissed/visible state to the index or rebuild inputs, update it on dismissal and
revive, and keep the canonical artifact tree stable for long-term history.

