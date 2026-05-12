# Dismissed Agent Archive and Query Language Research

Research date: 2026-05-12

## Question

How should SASE handle dismissed agents when they must remain revivable forever, scale to a large historical corpus, and
support a precise agent query language for browsing dismissed/historical agents?

Short answer: SASE should treat historical agents as an immutable archive with materialized indexes, and treat
"dismissed", "visible", and "revived" as projections over that archive rather than as destructive lifecycle states. The
MVP for dismissed-agent queries should reuse the existing `sase.ace.agent_query` grammar, evaluate metadata predicates
against a SQLite summary index, and only hydrate full bundle JSON / transcript text for preview, revival, and explicit
`text:` searches.

## Current Shape

Primary code and docs reviewed:

- `src/sase/ace/dismissed_agents.py`
- `src/sase/ace/dismissed_bundle_index.py`
- `src/sase/ace/tui/actions/agents/_revive.py`
- `src/sase/ace/tui/actions/agents/_loading.py`
- `src/sase/ace/tui/actions/agents/_loading_compute.py`
- `src/sase/ace/tui/modals/revive_agent_modal.py`
- `src/sase/ace/agent_query/`
- `src/sase/ace/tui/actions/agents/_loading_finalize.py`
- `src/sase/ace/tui/models/agent_loader.py`
- `src/sase/ace/tui/models/agent_bundle.py`
- `src/sase/ace/tui/models/agent_content_search.py`
- `../sase-core/crates/sase_core/src/agent_cleanup/execution.rs`
- `../sase-core/crates/sase_core/src/agent_cleanup/planner.rs`
- `docs/ace.md`
- `docs/troubleshooting/agent-revival.md`

The implementation already moved beyond a single monolithic JSON file:

- A compact identity set lives at `~/.sase/dismissed_agents.json`.
- Per-agent bundle JSON files live under `~/.sase/dismissed_bundles/YYYYMM/`.
- `src/sase/ace/dismissed_bundle_index.py` maintains `index.sqlite` with one row per bundle summary.
- Dismiss writes a bundle, updates the compact identity set, deletes/restores artifact marker files, and upserts the
  SQLite summary row.
- Revival loads dismissed bundles, removes identities from `dismissed_agents.json`, restores minimal artifact files,
  removes the bundle file, and writes JSONL audit events to `~/.sase/logs/events.jsonl`.
- The Agents tab already has a structured query language in `src/sase/ace/agent_query/`, wired to live rows in
  `_loading_finalize.py`.

That means SASE has the right raw ingredients: sharded durable files, an index, a query grammar, lazy archive loading,
and audit events. The problem is that the ownership boundaries are not clean enough for "historical agents are a major
product surface".

## Current Structural Problems

### Dismissed Is Both Data State And Visibility State

The current model uses `dismissed_agents.json` as a suppression set, `dismissed_bundles/` as the restoration source, and
artifact deletion/restoration as the visibility mechanism. That makes dismissal a compound operation:

- save serialized agent bundle;
- add identity to compact dismissed set;
- remove source marker files from artifacts;
- show row in same-session `_dismissed_agent_objects`;
- hide row from the live loader;
- update summary index.

Revival then reverses parts of this:

- remove identities from compact dismissed set;
- restore marker files from bundle JSON;
- delete the bundle JSON;
- delete summary-index rows.

For "revivable forever", the destructive part is the core mismatch: reviving consumes the archive bundle. Once revived,
the historical record is again dependent on restored artifact files and whatever later happens to them.

### The Archive Is A Recovery Mechanism, Not A Source Of Truth

`load_dismissed_bundles()` reconstructs `Agent` objects from bundle JSON, but the archive is still treated as a fallback
for rows that are missing from live artifacts. `_loading_compute.py` even has a "recovered bundle" path that re-adds
loader-sourced dismissed identities. This creates confusing responsibility:

- source artifacts are the source of truth for visible agents;
- bundles are the source of truth for dismissed agents;
- revived agents become source artifacts again;
- the compact dismissed set decides which source wins.

That model can work for small numbers of rows, but it makes global historical browsing, query planning, and retention
policy hard to reason about.

### The Compact Identity Set Is Not An Archive Index

`dismissed_agents.json` stores only `(agent_type, cl_name, raw_suffix)`. It is enough to suppress rows, but not enough
to answer historical questions. The real summary is in `index.sqlite`, but that index is currently an auxiliary helper:
revival still tends to load bundles into `Agent` objects, and the compact identity set can be repaired as a side effect
of archive loading.

A scalable architecture needs the reverse relationship:

- archive bundles are immutable payloads;
- SQLite indexes are authoritative query/materialization indexes;
- visibility state is a small mutable projection keyed by stable agent IDs;
- loader/TUI code consumes query results, not raw filesystem scans.

### Query Semantics Are Live-Agent-Centric

The live agent query language is useful and should be kept. It supports:

- Boolean expressions with `AND`, `OR`, `NOT`, parentheses, and implicit `AND`;
- metadata keys like `status`, `cl`, `project`, `name`, `model`, `provider`, `tag`;
- enum/bool keys like `type`, `source`, `needs`, `hidden`, `pinned`, `attention`;
- duration comparisons like `age>=2h`;
- content search via `text:` / bare terms using `AgentContentSearchCache`.

But the evaluator works against hydrated `Agent` objects and live content paths. The revive modal still uses its own
free-text filter over label text and cached `get_response_content()`. A dismissed-agent query language should not need
to hydrate every archived bundle on each keystroke.

### Historical Metadata Is Incomplete

`Agent.to_bundle_dict()` intentionally omits runtime-only internals and also omits `tag`. That is reasonable for some
live UI state, but it means historical queries like `tag:foo` are not reliable after dismissal. If historical agents are
first-class, the archive schema needs an explicit policy for mutable user annotations:

- preserve the tag value at dismissal time;
- keep current mutable annotations in a separate `agent_annotations` table;
- or both, with different query keys such as `tag:` and `dismissed_tag:`.

The important point is that the decision should be explicit, not an accident of dataclass serialization exclusions.

## Recommended New Architecture

### Core Model

Introduce an Agent Archive subsystem with four layers:

1. **Immutable payload store**

   Keep bundle files under `~/.sase/agent_archive/bundles/YYYYMM/<agent_id>.json` or evolve
   `~/.sase/dismissed_bundles/YYYYMM/` in place. Once written, a historical payload is never deleted by revive.
   A payload is a complete normalized snapshot of an agent run and its recovery data.

2. **Mutable state tables**

   Store small mutable projections in SQLite:

   - `agent_archive_entries`: stable identity, lifecycle timestamps, model/provider/status/project/CL/name/workflow,
     parent/child/retry fields, payload path, payload hash, payload schema version.
   - `agent_visibility`: `agent_id`, `visible_in_live_view`, `dismissed_at`, `revived_at`, `last_action`.
   - `agent_annotations`: user tags, pinned state, notes, manual unread/read, optional archive labels.
   - `agent_archive_events`: append-only lifecycle events such as created, dismissed, revived, restored, renamed,
     annotated, migrated.

3. **Search indexes**

   Keep query-facing materializations separate from payloads:

   - B-tree indexes for `raw_suffix`, `agent_name`, `cl_name`, `project`, `status`, `model`, `provider`, start/stop
     timestamps, parent/retry fields.
   - SQLite FTS5 table for prompt/reply/chat excerpts or a bounded text projection.
   - A payload file signature/hash column so `verify` can detect stale rows.

4. **Projection APIs**

   Expose a Rust-core-backed API, with Python adapters:

   - `archive_agent_snapshot(snapshot) -> agent_id`
   - `set_agent_visibility(agent_id, dismissed|visible)`
   - `query_agent_archive(query, scope, limit, cursor) -> summary rows`
   - `hydrate_agent_archive_rows(agent_ids) -> Agent-like objects`
   - `restore_agent_artifacts(agent_id) -> restore report`
   - `verify/rebuild_archive_index()`

Shared archive/query semantics belong in `../sase-core` per the Rust backend boundary memory. The TUI should only own
modal state, rendering, and keybindings.

### Stable Identity

Use a stable `agent_id` instead of relying on `(agent_type, cl_name, raw_suffix)` everywhere. The natural first
implementation can be deterministic:

```text
agent_id = sha256(project_file + "\0" + raw_suffix + "\0" + agent_type + "\0" + step_index_or_empty)
```

Keep the current tuple as alternate keys for compatibility and lookup. This solves several current pain points:

- duplicate historical names are valid;
- workflow children can share parent timestamps without filename hacks leaking into callers;
- aliases created by old dismissed-name prefixes can be indexed as aliases, not special cases in every lookup;
- revive can clear visibility by `agent_id` while still matching legacy suffix-based rows during migration.

### Dismiss Flow

New dismiss flow:

1. Build or update immutable archive payload for the selected agent and related children.
2. Upsert summary/index/FTS rows in one transaction.
3. Set `agent_visibility.dismissed_at` and `visible_in_live_view = false`.
4. Optionally delete live marker files as a cache-space optimization, but treat deletion as a projection cleanup, not as
   the only way to hide the row.

If marker deletion fails, the visibility table should still suppress the row. If bundle writing fails, dismissal should
fail or degrade to "hide only" with an explicit warning, because durable history is now the invariant.

### Revive Flow

New revive flow:

1. Query archive summaries and let the user choose one or more rows.
2. Restore artifacts from immutable payloads.
3. Set `visible_in_live_view = true` and write a `revived` event.
4. Keep the archive payload and index row.

Revive should be a restoration/projection operation, not an archive deletion. A revived agent remains historical and can
still be found by archive queries.

### Live Loader Relationship

The Agents tab should become a projection over:

- active source artifacts / running claims;
- archive visibility state;
- optional historical archive rows when the user explicitly asks for history.

That removes the need for suffix-heavy suppression heuristics in normal refresh. It also means the same query language
can operate over `scope:live`, `scope:dismissed`, or `scope:all-history` with different query planners.

### Migration Strategy

Migrate incrementally:

1. Keep `~/.sase/dismissed_bundles/` and `dismissed_agents.json` readable.
2. Add a new SQLite schema version that can import existing bundle summaries and identity-set rows.
3. Stop deleting bundle files on revive.
4. Add a compatibility layer where old `load_dismissed_bundles()` delegates to archive query + hydrate.
5. Later, move the canonical root from `dismissed_bundles` to `agent_archive` or leave the on-disk path but rename the
   API concept to "archive".

## Recommended MVP For Dismissed-Agent Query Language

### Product Behavior

Add structured filtering to the revive modal and archive browsing path:

```text
status:failed project:sase model:codex age>7d
cl:foo OR name:planner
provider:openai NOT status:done
text:"migration error"
```

The MVP should support the same surface grammar as the existing Agents tab query language where possible. Users should
not need to learn two dialects.

### MVP Scope

Use the existing parser/tokenizer/canonicalizer in `src/sase/ace/agent_query/`. Add a second evaluator/planner:

- `evaluate_agent_query()` remains the hydrated `Agent` evaluator for live rows.
- Add `plan_archive_agent_query(expr) -> SQLPlan | HydrationPlan`.
- Metadata-only predicates compile to SQL over `dismissed_bundle_summaries`.
- `text:` and bare string searches initially use an indexed summary haystack if available; otherwise fall back to
  bounded bundle hydration after applying all SQL metadata predicates.

For MVP, keep query keys small and reliable:

- `status`, `cl`, `project`, `name`, `model`, `provider`, `type`, `age`
- `text` as best-effort content search
- `workflow`, `step`, `retry`, and `dismissed` can follow after the archive schema is normalized

Defer or clearly define these:

- `tag:` until historical tags/annotations are persisted;
- `pinned:` unless archive annotations are added;
- `hidden:` because "hidden" is live UI projection state, not archive state;
- `attention:` and `needs:` unless their status mappings are made archive-stable.

### MVP Storage Work

Extend `dismissed_bundle_index.py` before inventing a separate database:

- Add summary columns that the query planner needs but the current schema lacks, especially `dismissed_at` and a
  normalized `project_name`.
- Add a `search_text` column or FTS5 side table populated from bounded prompt/response/chat text extracted during
  upsert/rebuild.
- Add indexes for `(status)`, `(agent_name)`, `(model)`, `(llm_provider)`, `(start_time)`, and `(project_name, cl_name)`.
- Keep `rebuild-index` and `verify` as the repair path.

This is not the final architecture, but it gives the query language a scalable backend immediately and avoids loading
every bundle for every filter keystroke.

### MVP TUI Flow

Replace `DismissedAgentSelectModal._get_filtered_agents()` with a query-aware provider:

- Empty input shows the default scoped archive rows, still sorted newest-first.
- Valid query filters via `query_dismissed_bundle_summaries(query, scope, limit)`.
- Invalid query shows an inline parse error and keeps the previous result set.
- Preview hydrates the selected bundle lazily.
- Revival accepts summary IDs / raw suffixes and hydrates only selected rows.

The same modal can keep a simple substring fallback if the user types a single bare word, because bare words are already
valid query terms.

### MVP CLI Flow

Add a CLI that uses the same query path:

```bash
sase agents archive search 'status:failed project:sase age>30d'
sase agents archive show --name planner
sase agents archive revive --query 'name:planner status:failed'
```

The TUI should not be the only way to verify query semantics. CLI output also gives agents a stable automation surface.

### MVP Acceptance Criteria

- Querying 10k dismissed bundles does not hydrate all bundle JSON files for metadata-only queries.
- `sase agents archive rebuild-index` backfills queryable rows from existing bundles.
- Reviving an agent no longer deletes its archive bundle.
- Existing `#resume:<name>` and name registry lookup still find historical dismissed bundles.
- The revive modal supports structured queries and lazy preview.
- Query parser tests are reused; archive-query planner tests cover every supported key.
- A compatibility test proves old sharded bundles and legacy top-level bundles remain queryable.

## Concrete Recommendation

Recommended architecture: build a first-class Agent Archive subsystem: immutable bundle payloads, mutable visibility and
annotation state, append-only lifecycle events, and SQLite/FTS materialized indexes owned by Rust core with thin Python
TUI/CLI adapters. Dismiss should archive and hide; revive should restore and mark visible; neither should delete the
historical payload.

Recommended MVP: keep the existing `dismissed_bundles/YYYYMM` files and `index.sqlite`, stop deleting bundles on revive,
extend the dismissed bundle summary index enough to support SQL-backed metadata queries, reuse the existing
`sase.ace.agent_query` grammar, and wire the revive modal plus a small `sase agents archive search` CLI to the new
archive-query planner.
