# Tagged Agent Revival Sets

Research date: 2026-05-26

## Question

Should SASE support saving every Agents-tab entry with a particular user tag, dismissing that whole group, and later
restoring that same group back to the exact pre-dismissal state? If yes, what implementation shape gives the best
reliability without overbuilding?

Short answer: yes, but only if the feature is framed as a **revival set**: a frozen membership manifest created at
dismiss time, not a later query for "whatever currently has tag X". A tag is a good selection mechanism, but it is not a
stable restore handle. The restore handle should be a durable batch id that records the exact identities, bundle paths,
tag-at-capture values, and cleanup plan selected before dismissal.

## Existing System

Relevant in-repo references reviewed:

- `src/sase/ace/agent_tags.py`
- `src/sase/ace/tui/actions/agents/_tagging.py`
- `src/sase/ace/tui/models/agent_panels.py`
- `src/sase/ace/tui/actions/agents/_kill_action.py`
- `src/sase/ace/tui/actions/agents/_dismissing.py`
- `src/sase/ace/tui/actions/agents/_dismiss_persistence.py`
- `src/sase/ace/tui/actions/agents/_revive.py`
- `src/sase/ace/tui/actions/agents/_revive_artifacts.py`
- `src/sase/ace/tui/models/agent_bundle.py`
- `src/sase/ace/dismissed_agents_bundles.py`
- `src/sase/ace/dismissed_bundle_index/`
- `src/sase/core/agent_cleanup_facade.py`
- `src/sase/core/agent_cleanup_wire.py`
- `docs/troubleshooting/agent-revival.md`
- Existing research: `sdd/research/202604/agent_tags.md`,
  `sdd/research/202605/dismissed_agent_archive_and_query_language.md`,
  `sdd/research/202605/agents_tab_full_refresh_elimination.md`,
  `sdd/research/202605/agent_query_language_quickstart.md`

Current facts:

- Agent tags are persisted in `~/.sase/agent_tags.json` as one scalar tag per agent identity
  `(agent_type, cl_name, raw_suffix)`. Legacy multi-tag entries are collapsed to one tag on read.
- Tags already drive Agents-tab panels. Workflow children inherit their parent's effective panel tag.
- The cleanup panel already has a tag-scoped path: it selects tag(s), builds a Rust/Python cleanup plan with
  `CLEANUP_SCOPE_TAG`, then routes through the existing bulk kill/dismiss confirmation flow.
- Batch dismiss already exists for completed/dismissable agents. It plans side effects once, updates the in-memory
  dismissed set optimistically, then persists bundle saves, artifact deletion, notification dismissal, and dismissed
  index updates off the UI thread.
- Revive already supports selecting multiple dismissed agents and restoring their marker files in one flow.
- Dismissed bundles are now preserved on revive. `mark_bundles_revived_by_suffixes()` currently returns matching bundle
  paths/counts and deliberately does not delete bundle files.
- The dismissed bundle index is still summary-only schema v1. It indexes metadata such as suffix, CL, status, project,
  model, workflow, parent/child fields, and retry fields, but it does not have lifecycle columns like `dismissed_at` /
  `revived_at`, FTS content, tags, or revival-set membership.
- `Agent.to_bundle_dict()` excludes the live `tag` field, `attempt_history`, follow-up/runtime child lists, and stores
  file paths rather than guaranteed copies of prompt/reply/chat content.
- The revive flow restores loader marker files (`done.json`, `workflow_state.json`, `prompt_step_*.json`,
  `agent_meta.json`) so the Agents tab can rediscover rows. It does not restore a live process.

## What "Exact State" Can Mean

The phrase "exact state before dismissal" has several possible levels:

1. **Exact membership:** restore the same agent identities that were dismissed in the batch.
2. **Exact row metadata:** restore names, status, timestamps, project, workflow parent/child relations, retry fields,
   and tag grouping as they were captured.
3. **Exact durable content:** preserve prompt, reply, chat transcript, diffs, tool output, and attempts even if original
   runtime/artifact files are later deleted.
4. **Exact live process state:** resume a killed/running process, terminal PTY, in-flight tool call, and workspace state.

Levels 1 and 2 are achievable with the current dismissal/revive machinery plus a better batch manifest. Level 3 needs
the broader Agent Archive work described in the dismissed-agent archive research. Level 4 should not be promised: a
killed or dismissed running agent cannot be revived back into the same OS process.

This distinction matters because current tag cleanup can include running agents via `KILL_AND_DISMISS`. That is useful
cleanup, but it is not reversible in the same way completed-agent dismissal is reversible. A reliable bundled revival
feature should default to completed/dismissable agents and make any kill-and-dismiss mode visibly non-resumable.

## Is This A Good Idea?

Yes, with constraints.

The idea solves a real Agents-tab pain point: tags are already being used as workstream buckets, and current cleanup by
tag is one-way from a user's perspective. The missing product primitive is not "dismiss by tag"; it is "I made a named,
auditable savepoint of this tagged group before hiding it."

The feature is worth doing because it would:

- make aggressive cleanup safer when many agents belong to one workstream;
- give the user a single batch id to restore, audit, and discuss with other agents;
- avoid relying on mutable tags after dismissal;
- reuse existing cleanup planning and batch revive code instead of inventing a separate lifecycle;
- create a stepping stone toward a first-class Agent Archive collection model.

The idea is risky if implemented as "revive all current `tag:foo` agents" because tags are mutable, the bundle payload
does not include tag snapshots, archive queries by tag are not first-class in the current code, and a later query cannot
know which agents belonged to the tag at dismissal time.

## Current Gaps

### Tag Is Not A Frozen Restore Handle

`agent_tags.json` is mutable user annotation state. It is correct for live grouping, but a restore action needs frozen
membership. If the user reuses `@review` next week, a later "restore @review" should not accidentally revive a different
set.

### Bundle Payload Is Not Complete Enough For Strong "Exact"

The current bundle excludes the `tag` field and several runtime/display-only structures. It also records paths to
prompt/reply/chat content rather than copying those contents into the archive. That means today's revive is good at
restoring the Agents-tab row, but not a complete historical snapshot if source files disappear.

### Running Agents Are Not Reversible

The cleanup planner can kill running agents and dismiss terminal/pidless rows together. A bundled revival feature should
separate "dismiss completed rows and revive later" from "kill running rows and keep a historical record". Otherwise the
UI will imply a guarantee the system cannot satisfy.

### Current Revival UX Is Agent-Centric, Not Batch-Centric

The existing `R` flow loads dismissed agents by project/home/CL scope and lets the user select rows. It can revive
multiple rows, but it does not expose named batches, membership manifests, or "restore the exact set I dismissed on
Tuesday".

### Performance Must Respect The Agents-Tab Refresh Work

Prior Agents-tab research shows post-action flows are performance-sensitive. The feature should not synchronously write
N bundles, scan the archive, or rebuild every panel on the UI thread. The current cleanup flow already does the right
thing structurally: optimistic in-memory update, worker-thread persistence, and indexed projection updates.

## Implementation Options

### Option A: Use Current Tag Cleanup Plus Manual Multi-Revive

Flow:

- User opens cleanup panel, chooses tag, confirms kill/dismiss.
- Later the user opens revive, filters visually, marks the same agents, and revives them.

Pros:

- Already mostly exists.
- No new storage format.

Cons:

- Does not reliably identify the exact dismissed set.
- Restore is tedious for large groups.
- Tags are not attached to loaded dismissed bundles.
- Later tag changes can change what "tag X" means.
- No single audit object says "this batch was saved and dismissed".

Verdict: useful baseline, not sufficient for the requested guarantee.

### Option B: Revive By Re-Evaluating `tag:<tag>`

Flow:

- On restore, query dismissed/live archive rows by tag and revive all matches.

Pros:

- Simple mental model.
- Builds toward a queryable archive.

Cons:

- Still not exact membership unless tags are immutable, which they should not be.
- Current archive schema does not index tags.
- `Agent.to_bundle_dict()` excludes tags, so archived rows cannot answer tag-at-dismiss queries without consulting
  mutable external annotation state.
- Reused tags would over-restore.

Verdict: good as a browsing/query feature, bad as the core reliability mechanism.

### Option C: Revival Set Manifest Beside The Existing Archive

Flow:

- Before cleanup, create a manifest such as
  `~/.sase/agent_revival_sets/YYYYMM/<set_id>.json`.
- The manifest records the source tag, created time, selected identities, bundle paths or expected bundle paths,
  tag-at-capture values, agent summaries, cleanup plan summary, and batch status.
- Existing bulk dismiss/kill machinery runs as it does today.
- Restore loads the manifest, hydrates the corresponding dismissed bundles by suffix/path, and calls the existing batch
  revive path.

Pros:

- Freezes exact membership.
- Minimal disruption to current dismissal/revive code.
- Works before the full archive schema grows collections.
- Easy to expose in both TUI and CLI.
- Provides a useful audit artifact even if some per-agent persistence fails.

Cons:

- Adds a second archive-adjacent store.
- Needs migration or integration later if the Agent Archive becomes the single source of truth.
- JSON-only lookup is fine for MVP but eventually wants an index.

Verdict: best MVP.

### Option D: First-Class Archive Collections In SQLite/Rust Core

Flow:

- Extend the Agent Archive model with `agent_collections`, `agent_collection_members`, and lifecycle events.
- A tag-dismiss action writes one collection transaction, archives every member revision, flips visibility, and records
  the cleanup event.
- Restore uses collection id, not tag, to restore all members.

Pros:

- Clean long-term model.
- Queryable, auditable, multi-frontend friendly.
- Fits the Rust core backend boundary.
- Can support CLI/TUI/web/mobile without duplicating semantics.

Cons:

- Larger project.
- Current dismissed archive schema is not there yet.
- Requires archive schema migration, collection APIs, and more acceptance coverage.

Verdict: best long-term destination, too much for the first slice unless this is folded into a broader Agent Archive
epic.

## Suggested Product Improvements

Use the term **Revival Set** instead of "bundled revival" in UI/code. It names the durable object, not just the action.

Add two explicit modes:

- **Save + dismiss completed:** only terminal/dismissable rows are included. This is the default and the only mode that
  can claim exact revival.
- **Save + kill/dismiss all:** includes running rows, but the confirmation must say running agents cannot be resumed as
  live processes; they can only be restored as archived/historical rows if enough metadata exists.

Make restore set-based:

- `R` on Agents tab should offer "Revival Sets" alongside the current per-agent dismissed list.
- A set row should show tag, count, created time, project/scope, and status: `ready`, `partial`, `restored`,
  `partially restored`, `missing bundles`.
- Selecting a set shows the captured members and a one-key "restore all" action.

Expose CLI automation:

```bash
sase agents revival-set create --tag review --dismiss-completed
sase agents revival-set list
sase agents revival-set show <set-id>
sase agents revival-set restore <set-id>
```

If the CLI surface should stay under the archive namespace, use:

```bash
sase agents archive set create --tag review --dismiss-completed
sase agents archive set restore <set-id>
```

The standalone `revival-set` wording is clearer for users, but the archive namespace may fit better once archive
collections exist.

## MVP Data Shape

Suggested manifest:

```json
{
  "schema_version": 1,
  "set_id": "20260526_143012_review_a1b2c3",
  "created_at": "2026-05-26T14:30:12-04:00",
  "source": {
    "kind": "agent_tag",
    "tags": ["review"],
    "scope": "agents_tab_current_loaded_rows",
    "mode": "dismiss_completed"
  },
  "status": "dismissed",
  "counts": {
    "selected": 12,
    "dismissed": 12,
    "skipped": 0,
    "restored": 0
  },
  "members": [
    {
      "identity": ["run", "sase-42", "20260526142500"],
      "raw_suffix": "20260526142500",
      "agent_name": "sase-42.code",
      "display_name": "sase-42 (DONE)",
      "status_at_capture": "DONE",
      "tag_at_capture": "review",
      "project_file": "/home/bryan/.sase/projects/sase/sase.sase",
      "bundle_path": "~/.sase/dismissed_bundles/202605/20260526142500.json",
      "artifacts_dir": "~/.sase/projects/sase/artifacts/ace-run/20260526142500",
      "is_workflow_child": false,
      "parent_timestamp": null,
      "bundle_sha256": null
    }
  ],
  "events": [
    {
      "timestamp": "2026-05-26T14:30:12-04:00",
      "event": "created"
    }
  ]
}
```

Notes:

- `scope` should be explicit. For an MVP, "current loaded Agents-tab rows" matches the existing cleanup-by-tag code.
  Later, a core query can select all current non-dismissed tagged rows from the artifact index.
- `tag_at_capture` is required for exact tag restoration because dismissed bundles do not currently serialize `tag`.
- `bundle_path` can be predicted before persistence from the raw suffix, then verified after bundle save.
- `bundle_sha256` can start as null and be populated once bundle hashing exists.
- Manifest writes must be atomic. If the cleanup persistence fails after manifest creation, update status to `partial`
  and leave enough data for repair.

## Architecture Notes

Long-term shared behavior belongs in `../sase-core`, not Textual code:

- selecting targets from an agent list by tag/query;
- writing and validating revival-set manifests or collection rows;
- restoring tag annotations from a captured manifest;
- resolving manifest members to dismissed bundles;
- computing restore readiness and partial-failure reports.

The Python TUI should own:

- keybindings and modals;
- preview text;
- toasts;
- row selection after restore;
- calling existing cleanup/revive adapters.

An MVP can start with a thin Python implementation if it stays small, but the manifest schema should be designed as a
wire format that can move into Rust core without changing user data.

## Acceptance Criteria

High-value tests:

- Creating a revival set by tag freezes the exact identities even if `agent_tags.json` is later changed.
- Restoring a revival set revives exactly those identities and does not revive other agents currently sharing the tag.
- Restoring a set restores `tag_at_capture` by default so the tag panel state matches the pre-dismissal state.
- Workflow parents restore with their workflow children/follow-ups using existing child cascade behavior.
- A partial dismiss leaves a manifest with `partial` status and per-member error state.
- A partial restore records which members succeeded, failed, were already visible, or had missing bundles.
- Running-agent mode is either rejected by default or produces an explicit non-resumable warning in the confirmation
  state and tests.
- A large set, e.g. 1000 agents, does not do archive scans or bundle hydration on the UI thread.
- Manifest writes are atomic and recover cleanly from malformed/corrupt JSON.
- Revive audit events include the `set_id` when restore is set-driven.

## Recommended Solution

Build this feature, but make the durable object a **revival set** rather than treating the tag itself as the restore
handle.

For the first implementation, add a small revival-set manifest store under `~/.sase/agent_revival_sets/YYYYMM/`, with
atomic JSON writes and a schema like the MVP above. Add a tag-scoped "save + dismiss completed" action that reuses the
existing cleanup planner and batch dismiss path, but writes the manifest before persistence starts. Add a set restore
path in the existing revive UI that loads a manifest, hydrates the recorded bundles by suffix/path, restores
`tag_at_capture`, and calls the existing batch revive flow. Keep kill-and-dismiss as a separate advanced mode with a
clear warning that live process state cannot be revived.

After the MVP proves useful, promote revival sets into the Agent Archive model in Rust core as first-class archive
collections with SQLite membership tables, lifecycle events, bundle hashes, and query/CLI support. This gives immediate
user value without blocking on the broader archive migration, while still leading to the right long-term architecture.

## Followup Gap Analysis

Date: 2026-05-26 (same-day followup)

The sections below extend the original analysis after a second pass through related code and research. Each gap names
something the first draft glossed over and links it to evidence in the repo.

### Manifest Write Atomicity And Sibling Lock Pattern

The original schema sketch said "manifest writes must be atomic" without specifying how. The repo already has a working
pattern that the revival-set store should reuse rather than reinvent:

- `src/sase/ace/agent_tags.py:144-157` writes via `tempfile.mkstemp` in the parent directory, `json.dump`, then
  `os.replace`, with cleanup of the temp file on failure.
- `src/sase/ace/agent_tags.py:163-...` exposes an `_agent_tags_file_lock()` context manager using `fcntl.flock` for
  exclusive access during read-modify-write.
- `src/sase/logs/run_log.py:26-34` uses `fcntl.flock(LOCK_EX)` for append-only JSONL writes.

For the revival-set store:

- Each manifest file should be written via the same temp+rename idiom, with the temp file living in the same `YYYYMM/`
  directory so `os.replace` stays atomic on the same filesystem.
- The per-manifest status field (`created` → `dismissing` → `dismissed` / `partial` → `restoring` → `restored` /
  `partially_restored`) should be updated under `fcntl.flock` against the manifest itself.
- An optional `agent_revival_sets/.index.json` summary (cheap projection: `set_id`, tag, count, status, created_at)
  should be rebuilt from scratch or via flock-guarded merge — avoid making it the source of truth.

### Concurrency Across Multiple ACE Instances

Multi-instance is not addressed in the first draft. The repo today assumes single-machine concurrency at most:

- `sdd/research/202605/multi_machine_sync.md` discusses Syncthing/git/rclone but explicitly leaves distributed locking
  out of scope.
- Agent-name allocation and tag writes rely on local `fcntl.flock` only.

Realistic stance for the revival-set MVP:

- Treat each set's manifest file as the lock target; concurrent writers serialize at the OS level on the same machine.
- Two ACE instances on different machines syncing via Syncthing/git can produce competing manifests with the same
  human-readable suffix; mitigate by adding a short random suffix (`set_id = "20260526_143012_review_a1b2c3"` already
  has one — keep it) so collisions become file-level rather than logical.
- Document that cross-machine restore of a manifest written elsewhere is allowed but the dismissed bundles must also
  have synced; otherwise the restore reports `missing_bundles`.

### Bundle Lifecycle, GC, And Integrity

Bundle pruning is **not** implemented today:

- `src/sase/ace/dismissed_agents_bundles.py:131-141` (`mark_bundles_revived_by_suffixes()`) intentionally preserves
  bundles after revive, returning matched paths/counts only.
- `src/sase/ace/dismissed_agents_paths.py:14-22` shards bundles by `YYYYMM/` but there is no scheduled GC, TTL, or
  retention policy.

Implications for revival sets:

- A manifest can safely point at a bundle file by path because the system does not delete bundles on its own. The
  manifest is still vulnerable to manual deletion or sync conflicts.
- Add a `bundle_sha256` field to each member (nullable until bundle hashing exists). On restore, verify the hash if
  present and report mismatch as a per-member `bundle_drift` error instead of silently restoring a different revision.
- When the broader Agent Archive eventually adds retention/purge, revival sets must be a first-class "pin": purging a
  bundle that belongs to an active (un-restored) set should be refused or require an explicit override.

### Workflow Parent/Child Cascade Is Already Handled

The first draft mentions workflow children but doesn't make a recommendation about manifest membership. The existing
code answers this:

- `src/sase/ace/tui/actions/agents/_revive.py:23-42` defines `_is_child_of()` which matches workflow step children
  (`parent_workflow` set), follow-up agents (`parent_timestamp` set, `parent_workflow` is None), and spawn-on-retry
  children (`retry_of_timestamp` set).
- `src/sase/ace/tui/actions/agents/_dismissing.py:48,70` already threads an `agents_with_children_snapshot` into the
  cleanup planner; the Rust planner expands a parent's selection to include its children.

Recommendation: store **parent identities only** in the manifest by default, and rely on the existing cascade for
restore. Add an optional `members[].expand_children: true` marker so the manifest documents intent without freezing the
child list. Also record `children_at_capture: [identity, ...]` as a diagnostic field so a restore can detect when the
parent's child set has changed since capture (e.g., a follow-up appeared later) and surface that to the user.

### Per-Member Failure Reporting Is Currently Weak

The original "Acceptance Criteria" mentions partial failures but the existing batch dismiss path does not return
per-member errors:

- `src/sase/ace/tui/actions/agents/_kill_persistence.py:38-68` reports success/failure via the cleanup plan's
  `side_effects` structure, which is plan-level, not per-agent.
- `_dismissing.py` and `_dismiss_persistence.py` optimistically update memory then persist asynchronously; failures
  surface as toasts/log entries, not structured per-agent state.

Revival sets should not pretend to have this data. Add an explicit `members[].state` enum: `pending`, `dismissed`,
`dismiss_failed`, `revived`, `revive_failed`, `bundle_missing`, `bundle_drift`, `already_visible`, with an optional
`error: { code, message, timestamp }`. Also add a `sase agents revival-set repair <set-id>` command that re-attempts
dismiss or restore for members in a non-terminal failed state, since the absence of per-member errors today means the
first try is the only try.

### Audit Log Integration

The first draft hand-waves "audit events include the `set_id`". The concrete hook point exists:

- `src/sase/logs/run_log.py:17-19` defines `REVIVE_EVENTS = {"agent_revive_started", "agent_revived",
  "agent_revive_failed"}`.
- `src/sase/logs/run_log.py:76-92` (`log_event`) appends arbitrary `kwargs` to `~/.sase/logs/events.jsonl` under
  `fcntl.flock`.
- `src/sase/logs/run_log.py:106-...` (`iter_revive_events`) reads events back in reverse-chronological order with
  filters.

New events to add (do not rename the existing ones):

- `revival_set_created` — `set_id`, source kind, tags, member_count, scope, mode.
- `revival_set_dismiss_completed` / `revival_set_dismiss_partial` — counts, failed_members.
- `revival_set_restore_started` / `revival_set_restored` / `revival_set_restore_partial`.
- Existing per-agent `agent_revive_started` / `agent_revived` / `agent_revive_failed` should accept an optional
  `set_id` kwarg when the revive is set-driven, so timeline queries can correlate per-agent events to their set.

### CLI Placement Inside Existing `sase agents`

The first draft proposed `sase agents revival-set ...` without confirming the surrounding namespace. The existing CLI
already has a rich tree:

- `src/sase/main/parser_agents.py:6-...` registers `status`, `kill`, `show`, plus subgroups `tag {set, unset, list}`,
  `archive {rebuild-index, verify}`, `index {gc, rebuild, status, verify}`, and `names {migrate-auto}`.

Two natural placements:

- `sase agents revival-set {create, list, show, restore, repair, delete}` — discoverable, sibling of `tag`.
- `sase agents archive set {create, list, show, restore, repair, delete}` — fits the long-term archive namespace and
  matches the eventual "archive collections" model.

Recommendation: ship under `sase agents revival-set` for the MVP since the archive subgroup is still focused on index
maintenance. When archive collections land, add `sase agents archive set` as an alias that points at the same
underlying store, and keep `revival-set` as a stable user-facing name (it reads better in docs and toasts).

### Selection Source Generalization

The MVP schema's `source.kind: "agent_tag"` is too narrow. The same primitive is useful for several capture sources:

- Tag (`source.kind: "tag"`, `source.tags: [...]`).
- Manual mark/visual-selection from the Agents tab (`source.kind: "manual_selection"`).
- Agent query language predicate (`source.kind: "query"`, `source.query: "status:DONE project:sase tag:review"`).
- Filter/panel state (`source.kind: "panel"`, `source.panel_id: ...`).

Keep `source` as a tagged union from day one so future entry points (query-driven cleanup, automation) don't require a
schema bump.

### Reused-Tag Detection On Restore

A subtle but important UX gap: after a set is dismissed, the user can reassign the same tag to a new group of agents.
At restore time, three different populations exist:

1. The exact identities frozen in the manifest (the truthful restore target).
2. Currently-live agents that also have `tag_at_capture` because the tag was reused.
3. Other dismissed agents that share the tag in the archive.

Restore should:

- Only revive members from group (1).
- Warn (not block) when group (2) is non-empty: "Tag `review` is currently assigned to 4 other live agents; they will
  not be touched."
- Offer a one-key "merge into current tag" option that re-tags restored agents to whatever the tag now means, vs. the
  default of restoring `tag_at_capture` verbatim (which can create two distinct live groups sharing one tag name).

### Cross-References Missed By The Original Draft

The original draft cites the archive/query research file but does not absorb several of its decisions. The revival-set
implementation should align with these to avoid future churn (see
`sdd/research/202605/dismissed_agent_archive_and_query_language.md`):

- **Stable `agent_id`**: the archive work expects a stable identifier independent of the
  `(agent_type, cl_name, raw_suffix)` tuple. Manifests should record the stable id when available and fall back to the
  tuple, so a later identity migration does not orphan revival sets.
- **Archive revisions**: the archive plans to keep revisions of an agent rather than overwriting. Manifests should
  reference a revision id where applicable, and a restore should be able to choose "latest revision" vs. "captured
  revision".
- **FTS over agent text**: when archive FTS lands, the `source.query` form above should accept the same query syntax,
  not invent its own.
- **Retention/purge/privacy**: the archive research calls out user-driven purge. Active revival sets must act as a pin
  (see the GC subsection above); revival-set deletion should be a deliberate user action with a confirmation that the
  underlying bundles may also be eligible for purge afterward.
- **Tag schema migration**: the archive's tag column needs a migration plan; revival-set `tag_at_capture` should be
  serialized in a form the archive can ingest without translation.

### Forward-Compatible Manifest Versioning

`schema_version: 1` is in the sketch but there is no migration story. Two cheap additions now:

- A top-level `produced_by: { sase_version, host, ace_session_id }` block so a future reader can identify the writer.
- An explicit `reader_min_schema_version` field so a future writer can mark "older readers should refuse this file"
  without negotiating compatibility.

### Dry-Run / Preview And Export

Two affordances were missing entirely:

- **Dry-run restore**: `sase agents revival-set restore <set-id> --dry-run` should print the resolved per-member
  outcome (`would_revive`, `bundle_missing`, `already_visible`, `bundle_drift`) without writing anything. This is the
  cheapest way to make a destructive-looking action feel safe.
- **Export/import**: a revival-set manifest is small JSON and is portable across machines if the bundles travel with
  it. Add `sase agents revival-set export <set-id> --bundles -o <tar>` and a matching `import` that places the manifest
  and bundles into the right `YYYYMM/` shards. This becomes the natural sharing format until archive collections grow
  their own export.

### Updated Acceptance Criteria

Additions to the original list:

- Manifest writes use temp+rename and survive a kill -9 mid-write without leaving a half-written file in place.
- Concurrent dismiss-then-restore on the same set from two TUI instances on the same machine produces a deterministic
  status (one wins, the other observes `restored` and no-ops).
- Restore of a set whose tag was later reused does not touch the newly-tagged live agents and surfaces a clear warning.
- Restore with `--dry-run` produces the same per-member outcome map as a real restore would, with no side effects on
  bundles, the dismissed index, the Agents tab, or `agent_tags.json`.
- Manual deletion of a bundle file between dismiss and restore yields `bundle_missing` for that member and leaves the
  rest restorable.
- A `repair` invocation can advance members from `dismiss_failed`/`revive_failed` to terminal states without rebuilding
  the manifest from scratch.
- Audit events for set-driven revives include `set_id`, and per-agent revive events also carry `set_id` when invoked
  through a set restore.

### Recommended Solution Refinements

Keeping the MVP shape from the original recommendation, but layered with the refinements above:

1. Use the in-repo temp+rename + `fcntl.flock` pattern (`agent_tags.py:144-157`) for every manifest write.
2. Generalize `source` into a tagged union now (`tag` / `manual_selection` / `query` / `panel`).
3. Persist parent identities only in `members`, but capture `children_at_capture` as diagnostic-only.
4. Add `members[].state` + `members[].error` and ship `revival-set repair` from day one.
5. Hook the existing `log_event` audit stream with new `revival_set_*` events and add an optional `set_id` kwarg to
   the existing `agent_revive_*` events.
6. Ship under `sase agents revival-set` with a future `sase agents archive set` alias.
7. Add `--dry-run` to restore and `export`/`import` to the CLI from the first cut; both are cheap and unlock real
   workflows (sharing, debugging, cross-machine moves).
8. Treat every active manifest as a pin against the eventual archive GC; do not defer this decision until GC ships,
   because the manifest format needs the `bundle_sha256` and revision fields now to make the pin enforceable later.
