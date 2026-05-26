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
