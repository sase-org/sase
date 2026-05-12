# Dismissed Agent Archive and Query Language Research

Research date: 2026-05-12

## Question

How should SASE handle dismissed agents when they must remain revivable forever, scale to a large historical corpus, and
support a precise agent query language for browsing dismissed/historical agents?

Short answer: SASE should treat historical agents as an immutable, versioned archive — including the prompt/response/chat
transcript text, not just bundle metadata — with materialized SQLite + FTS indexes, mutable visibility/annotation state
as a separate projection, and explicit retention/purge policy. "Dismissed", "visible", and "revived" should be
projections over that archive rather than destructive lifecycle states. The MVP for dismissed-agent queries should
reuse the existing `sase.ace.agent_query` grammar (including its highlighter and saved-queries store), evaluate
metadata predicates against the SQLite summary index, hydrate full bundles only for preview/revival, and grow the
archive payload so `text:` queries can run against an FTS projection instead of being a best-effort scan.

## Current Shape

Primary code and docs reviewed:

- `src/sase/ace/dismissed_agents.py`
- `src/sase/ace/dismissed_bundle_index.py`
- `src/sase/ace/agent_tags.py`
- `src/sase/ace/saved_queries.py`
- `src/sase/ace/tui/actions/agents/_revive.py`
- `src/sase/ace/tui/actions/agents/_revive_artifacts.py`
- `src/sase/ace/tui/actions/agents/_loading.py`
- `src/sase/ace/tui/actions/agents/_loading_compute.py`
- `src/sase/ace/tui/actions/agents/_loading_finalize.py`
- `src/sase/ace/tui/modals/revive_agent_modal.py`
- `src/sase/ace/agent_query/` (parser, tokenizer, evaluator, highlighting, types)
- `src/sase/ace/tui/models/agent_loader.py`
- `src/sase/ace/tui/models/agent_bundle.py`
- `src/sase/ace/tui/models/agent_content_search.py`
- `../sase-core/crates/sase_core/src/agent_cleanup/{wire,planner,execution,mod}.rs`
- `docs/ace.md`
- `docs/troubleshooting/agent-revival.md`

The implementation already moved beyond a single monolithic JSON file:

- A compact identity set lives at `~/.sase/dismissed_agents.json`.
- Per-agent bundle JSON files live under `~/.sase/dismissed_bundles/YYYYMM/`, sharded by `raw_suffix` timestamp.
- `src/sase/ace/dismissed_bundle_index.py` maintains `index.sqlite` (schema v1, WAL, busy_timeout 30s) with one row per
  bundle summary.
- Dismiss writes a bundle, updates the compact identity set, deletes/restores artifact marker files, and upserts the
  SQLite summary row.
- Revival loads dismissed bundles, removes identities from `dismissed_agents.json`, restores minimal artifact files,
  removes the bundle file, and writes JSONL audit events to `~/.sase/logs/events.jsonl`.
- The Agents tab already has a structured query language in `src/sase/ace/agent_query/` (parser + closed property-key
  allowlist + duration comparators + content-cache evaluator + highlighter), wired to live rows in
  `_loading_finalize.py`. Numbered saved-query slots live in `src/sase/ace/saved_queries.py`.
- A Rust cleanup planner/executor in `../sase-core/crates/sase_core/src/agent_cleanup/` produces a pure
  `AgentCleanupPlanWire` and writes bundles/index entries from JSON values supplied by Python.

That means SASE has the right raw ingredients: sharded durable files, an index, a query grammar with a highlighter,
saved-query infrastructure, lazy archive loading, audit events, and a Rust-core seam for the cleanup decision. The
problem is that ownership boundaries are not clean enough for "historical agents are a major product surface".

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
for rows missing from live artifacts. `_loading_compute.py` even has a "recovered bundle" path that re-adds
loader-sourced dismissed identities. This creates confusing responsibility:

- source artifacts are the source of truth for visible agents;
- bundles are the source of truth for dismissed agents;
- revived agents become source artifacts again;
- the compact dismissed set decides which source wins.

That model can work for small numbers of rows, but it makes global historical browsing, query planning, and retention
policy hard to reason about.

### Bundle Payload Misses Prompt/Response/Chat Content

`Agent.to_bundle_dict()` (in `src/sase/ace/tui/models/agent_bundle.py`) serializes the `Agent` dataclass fields but
explicitly **excludes** `attempt_history`, `tag`, and runtime-only internals; more importantly, it persists only
references (`response_path`, attempt `live_reply_path`s) — not the prompt, response, chat, or `raw_xprompt.md`
contents themselves.

Meanwhile, the live `AgentContentSearchCache` builds the `text:`/bare-word haystack from files on disk:

- `artifacts_dir/raw_xprompt.md`
- `artifacts_dir/live_reply.md`
- `agent_meta.json.chat_path` (a path that frequently points outside `~/.sase/`, e.g. into
  `~/.claude/projects/...` or another runtime's transcript store)
- per-attempt `live_reply_path`s
- `agent.response_path`

The dismiss flow then deletes `done.json`, `workflow_state.json`, and `prompt_step_*.json` from `artifacts_dir`, and
nothing in the archive guarantees the remaining files (`raw_xprompt.md`, `live_reply.md`, chat transcript) survive — they
can be garbage-collected by per-runtime cleanup, by `~/.claude` history retention, or by manual deletion.

The practical consequence: even today, a "text search over dismissed agents" is best-effort at best — once the artifact
dir / chat file is gone, the dismissed bundle alone cannot answer it. A first-class historical query surface needs the
archive to either (a) copy a bounded text projection into the bundle/SQLite at dismiss time, or (b) move the
prompt/reply/chat files into the archive payload (with hashing/dedup if needed). The previous version of this note
treated `text:` search as a planner concern, but the deeper issue is missing input data.

### Missing Bundle Schema Version And Forward-Compatibility Story

`to_bundle_dict()` and `from_bundle_dict()` rely on dataclass-field name overlap with `.get()` defaults; there is no
`schema_version` key in the bundle JSON. For an archive that must remain readable forever:

- field renames silently lose data;
- removed fields silently disappear;
- new required fields are indistinguishable from old bundles that legitimately omit them;
- the `_LEGACY_AGENT_TYPES` mapping is a one-off hack for the only migration that has been needed so far.

The historical archive needs an explicit `bundle_schema_version`, a migration registry, and a "rebuild" path that
applies migrations and re-derives the SQLite index. Bundles older than a certain version may need an explicit upgrade
step before they are query-addressable.

### The Compact Identity Set Is Not An Archive Index

`dismissed_agents.json` stores only `(agent_type, cl_name, raw_suffix)`. It is enough to suppress rows, but not enough
to answer historical questions. The real summary is in `index.sqlite`, but that index is currently auxiliary: revival
still tends to load bundles into `Agent` objects, and the compact identity set can be repaired as a side effect of
archive loading.

A scalable architecture needs the reverse relationship:

- archive bundles are immutable payloads;
- SQLite indexes are authoritative query/materialization indexes;
- visibility state is a small mutable projection keyed by stable agent IDs;
- loader/TUI code consumes query results, not raw filesystem scans.

### Query Semantics Are Live-Agent-Centric

The live agent query language is useful and should be kept. It supports:

- Boolean expressions with `AND`, `OR`, `NOT`, parentheses, and implicit `AND`;
- metadata keys: `status`, `cl`, `project`, `name`, `model`, `provider`, `tag` (substring/enum/bool);
- enum keys: `type` (workflow/run/running), `source` (axe/manual), `needs` (input);
- bool keys: `pinned`, `hidden`, `attention`;
- duration comparisons: `age<`, `age<=`, `age>`, `age>=`, `age=`, plus `age:` as sugar for `age>=`;
- content search via `text:` / bare terms using `AgentContentSearchCache`.

But the evaluator works against hydrated `Agent` objects and live content paths. The revive modal still uses its own
free-text filter over label text and cached `get_response_content()`. A dismissed-agent query language should not need
to hydrate every archived bundle on each keystroke, and several keys (`hidden`, `attention`, `needs`) are intrinsically
live-only.

### Historical Metadata Is Incomplete

`Agent.to_bundle_dict()` intentionally omits runtime-only internals and also omits `tag`. That is reasonable for some
live UI state, but it means historical queries like `tag:foo` are not reliable after dismissal. If historical agents are
first-class, the archive schema needs an explicit policy for mutable user annotations:

- preserve the tag value at dismissal time;
- keep current mutable annotations in a separate `agent_annotations` table;
- or both, with different query keys such as `tag:` and `dismissed_tag:`.

The important point is that the decision should be explicit, not an accident of dataclass serialization exclusions.

### Multi-Process Concurrency Is Implicit

The index opens SQLite with `journal_mode = WAL`, `synchronous = NORMAL`, and a 30 s `busy_timeout`. That handles
single-writer/many-reader well. But the production pattern is:

- the TUI process upserts on dismiss;
- `sase axe` worker processes upsert on completion or kill-and-dismiss;
- the CLI (`rebuild-index`, future `archive search`) reads or rewrites;
- the Rust executor writes bundle JSON via `try_save_dismissed_bundle` independently of the index path.

There is no advisory locking around bundle writes themselves, so two processes finalizing the same agent (e.g. retry +
late axe sweep) can race the bundle file and the index row. The Rust executor and Python fallback both `fs::write` to
the same path, so concurrent writers will produce a torn final state without an atomic rename. The architecture should
state explicit concurrency rules (single canonical writer per `agent_id`, atomic-rename for payload writes, SQLite
write inside the same transaction as visibility flip).

### Re-Archive Round-Trip Is Undefined

A revived agent may run again, generate new artifacts, and be dismissed again. Today this overwrites the bundle file
(same `raw_suffix`) and the index row. There is no record that the second run had different content, status, or
duration than the first. If history is a first-class product surface, the archive should treat each dismissal as a new
immutable lifecycle snapshot, keyed by `(agent_id, revision)` or `(agent_id, dismissed_at)`. Revive is a "checkout" that
creates a working copy; the next archive write is a new revision, not an overwrite.

### No Retention, Purge, Or Privacy Story

"Revivable forever" cannot literally mean forever — prompts and replies routinely contain secrets, PII, customer data,
and credentials. The current code never deletes a bundle except via revive. There is no:

- per-tenant TTL;
- size cap or LRU eviction;
- `sase agents archive purge --before <date>` operation;
- secret-scrubbing pass (e.g. redacting `sk-`, `ghp_`, `AKIA`, `xoxb-`, JWTs, RSA blocks);
- GDPR-style identity purge;
- export-then-purge for offsite archival.

The architecture needs explicit policy and tooling, even if the default policy is "keep everything until manual purge".

## Recommended New Architecture

### Core Model

Introduce an Agent Archive subsystem with five layers:

1. **Immutable payload store**

   Evolve `~/.sase/dismissed_bundles/YYYYMM/` (or rename to `~/.sase/agent_archive/payloads/YYYYMM/`) into a
   complete normalized snapshot per agent lifecycle:

   - `bundle.json` — current serialized Agent dataclass plus a `bundle_schema_version` and `archive_revision` field;
   - `prompt.md`, `reply.md`, `chat.json` (or `chat.jsonl`) — bounded text projections copied at archive time;
   - `attempts/<n>/reply.md` — per-attempt history;
   - `meta.json` — capture-time facts (runtime, model fingerprint, source machine, tenant, secret-scrubber version,
     content sizes, hashes);
   - optional `raw/` — pointers to or copies of original artifact files for full fidelity.

   Once written, payload directories are never deleted by revive. Atomic-rename `<id>.tmp` → `<id>` on write; bundle
   files include a content hash so the index can detect tampering.

2. **Mutable state tables (SQLite)**

   Promote `index.sqlite` to a richer schema. Suggested tables:

   - `agent_archive_entries`: stable `agent_id`, `archive_revision`, lifecycle timestamps, model/provider/runtime/
     status/project/CL/name/workflow, parent/child/retry fields, payload directory path, payload hash, bundle
     schema version, content-size facets.
   - `agent_visibility`: `agent_id`, `visible_in_live_view`, `dismissed_at`, `revived_at`, `last_action`.
   - `agent_annotations`: user tags, pinned, notes, manual unread/read, archive labels.
   - `agent_archive_events`: append-only lifecycle events (created, dismissed, revived, restored, renamed,
     annotated, migrated, purged). Replaces today's `events.jsonl` for archive-relevant events.
   - `agent_archive_aliases`: alternate `(agent_type, cl_name, raw_suffix)` tuples mapping back to canonical
     `agent_id`, including dismissed-name-prefix aliases.

3. **Search indexes**

   Keep query-facing materializations separate from payloads:

   - B-tree indexes for `raw_suffix`, `agent_name`, `cl_name`, `project_name`, `status`, `model`, `llm_provider`,
     `runtime`, start/stop timestamps, parent/retry fields.
   - SQLite **FTS5** virtual table populated from the bounded prompt/reply/chat text written into the payload at
     dismiss time. FTS5 supports BM25 ranking, prefix queries, and `phrase` matching — enough for `text:` and
     bare-word search without scanning JSON.
   - JSON1 `json_extract` over the bundle JSON for ad-hoc rare-field queries (escape hatch for keys that aren't
     yet promoted to columns).
   - A payload-hash column so `verify` can detect stale rows.

4. **Projection APIs (Rust core)**

   Shared archive/query semantics belong in `../sase-core` per the Rust backend boundary memory. Suggested surface
   (exposed through `sase_core_rs` bindings, called from Python adapters):

   - `archive_agent_snapshot(snapshot) -> ArchiveAgentId`
   - `set_agent_visibility(agent_id, dismissed|visible)`
   - `query_agent_archive(query, scope, limit, cursor) -> summary rows + next-cursor + facet counts`
   - `hydrate_agent_archive_rows(agent_ids) -> Agent-like objects` (bounded payload reads)
   - `restore_agent_artifacts(agent_id) -> RestoreReport`
   - `verify_archive_index() / rebuild_archive_index()`
   - `purge_archive(predicate, dry_run) -> PurgeReport` (drives retention)
   - `scrub_payload(agent_id, scrubber_version) -> ScrubReport`

   The TUI should only own modal state, rendering, keybindings, and conversion of `Agent` ↔ wire snapshots.

5. **Annotation & visibility ownership**

   `agent_tags.json` (the user's tag store) and saved-query state should be readable by the archive subsystem so
   that:

   - dismissal copies the live tag into the immutable bundle and also leaves the mutable `agent_annotations` row
     authoritative for future re-tagging;
   - query keys like `tag:` resolve against the mutable annotation; `dismissed_tag:` (or `tag_at_dismiss:`) resolves
     against the frozen value.

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
- revive can clear visibility by `agent_id` while still matching legacy suffix-based rows during migration;
- multiple lifecycle snapshots per agent (`archive_revision`) compose cleanly with the stable id.

### Dismiss Flow

New dismiss flow:

1. Build the immutable archive payload directory: bundle JSON (with schema version + revision number), copied
   `prompt.md`/`reply.md`/`chat.*` (size-capped, with hashes), per-attempt replies, capture-time `meta.json`. Write to
   `<id>.tmp.<rev>/` and atomic-rename to `<id>.<rev>/`.
2. Upsert summary/index/FTS rows in one SQLite transaction. Include payload hash and bundle schema version.
3. Set `agent_visibility.dismissed_at` and `visible_in_live_view = false`.
4. Append an `agent_archive_events` row (`dismissed`, with cause: `manual` / `axe-cleanup` / `kill-and-dismiss`).
5. Optionally delete live marker files as a cache-space optimization, but treat deletion as a projection cleanup, not
   as the only way to hide the row.

If marker deletion fails, the visibility table should still suppress the row. If bundle writing fails, dismissal should
fail or degrade to "hide only" with an explicit warning, because durable history is now the invariant. Payload writes
should fsync and use atomic rename so partial archives are never observable.

### Revive Flow

New revive flow:

1. Query archive summaries and let the user choose one or more rows.
2. Restore artifacts from the latest immutable payload revision (and, if the user requests, an older revision).
3. Set `visible_in_live_view = true` and write a `revived` event.
4. Keep the archive payload and index rows. Subsequent dismissal writes a new revision; the prior revision remains
   queryable.

Revive should be a restoration/projection operation, not an archive deletion. A revived agent remains historical and
can still be found by archive queries.

### Live Loader Relationship

The Agents tab should become a projection over:

- active source artifacts / running claims;
- archive visibility state;
- optional historical archive rows when the user explicitly asks for history.

That removes the need for suffix-heavy suppression heuristics in normal refresh. It also means the same query language
can operate over `scope:live`, `scope:dismissed`, or `scope:all-history` with different query planners.

### Cross-Runtime Field Coverage

Per the uniform-runtimes gotcha, the archive schema must not assume Claude-shaped agents. Required normalized fields:

- `runtime` (claude/codex/gemini/qwen/...): currently inferred from `model`/`provider`; should be persisted at archive
  time.
- `model` + `model_fingerprint` (provider-specific revision string).
- `provider_metadata_json` (free-form per-runtime blob; ad-hoc query via JSON1).
- `cost_usd_micros` / `total_input_tokens` / `total_output_tokens` (where the runtime reports them).
- `chat_format` (per-runtime — Claude JSONL, Codex protobuf-as-JSON, Gemini SDK shape).

The query planner should expose these as first-class keys (`runtime:`, `cost>`, `tokens>`), with consistent semantics
across runtimes.

### Retention, Purge, And Privacy

Default policy: keep payloads indefinitely; provide tooling to scope-down:

- `sase agents archive purge --before <date>` — bulk delete payloads + index rows + visibility/annotation/event rows.
- `sase agents archive purge --id <agent_id>` — single-agent GDPR-style purge.
- `sase agents archive scrub --before <date>` — re-run secret scrubber on payload text without deleting rows. Record
  `scrubber_version` so future scrubber improvements know which payloads need rescanning.
- Secret scrubber runs at archive write time, with a documented list of patterns (API keys, JWTs, RSA blocks, AWS/GCP
  credentials, common cloud provider tokens). The scrubber is versioned and idempotent.
- `sase agents archive export --query <q> --out <path>` for offsite archival before purge.

`purge` must remove both payload files and index rows in a single logical transaction (delete payload, then SQLite
DELETE inside a transaction; on failure, rollback or re-queue). Events for purge are themselves retained in a smaller
"redacted" form so audit history remains.

### Concurrency And Atomicity

- One canonical writer per `agent_id`/`archive_revision`: write `<id>.tmp.<rev>/` and atomic-rename. Concurrent
  finalizers can race the rename loser, which should detect and back off.
- Index writes inside `BEGIN IMMEDIATE` transactions; the visibility flip and the index upsert share one transaction.
- Long-running maintenance (`rebuild-index`, `purge`) takes an advisory lock (a `.lock` file in the archive root) so
  the TUI/CLI don't both rewrite the FTS table simultaneously.
- The Rust executor exposes a single `archive_write_snapshot` entry point so Python no longer writes the bundle file
  directly during the fallback path; the fallback becomes "Rust unavailable → defer write, log warning". Cuts torn
  writes.

### Migration Strategy

Migrate incrementally:

1. **Phase 0 (quick win, today):** stop deleting bundles on revive (`remove_bundle_by_identity` becomes
   `mark_revived_in_index`); keep summary row, mark `revived_at` populated. This single change preserves history with
   no schema upheaval and immediately makes the archive durable. Bundle file is left in place; index gains
   `revived_at`. Live loader already suppresses by visibility set, so behavior is unchanged.
2. Add bundle `schema_version` field and a migration registry; old bundles read at version 0 and upgrade on next
   write.
3. Add a new SQLite schema version (v2) that adds: `agent_id`, `archive_revision`, `runtime`, `cost`/`tokens`,
   `dismissed_at`, `revived_at`, `project_name`, `search_text`, an FTS5 side table, and the
   `agent_visibility`/`agent_annotations`/`agent_archive_events` tables.
4. At dismiss time, also write `prompt.md`/`reply.md`/`chat.*` projections into the payload directory.
5. Add a compatibility layer where `load_dismissed_bundles()` delegates to `query_agent_archive` + hydrate.
6. Add CLI surface (next section).
7. Add a dedicated **Archive tab** in `sase ace` TUI for browsing history (vs. revive modal only).
8. Later, move the canonical root from `dismissed_bundles` to `agent_archive` or leave the on-disk path but rename the
   API concept to "archive".

Each phase is independently shippable and reversible.

## Recommended MVP For Dismissed-Agent Query Language

### Product Behavior

Add structured filtering to the revive modal and archive browsing path:

```text
status:failed project:sase model:codex age>7d
cl:foo OR name:planner
provider:openai NOT status:done
text:"migration error"
runtime:codex cost>0.5
```

The MVP should support the same surface grammar as the existing Agents tab query language where possible. Users should
not need to learn two dialects.

### MVP Scope: Reuse the Parser, Add an Archive Planner

Use the existing `src/sase/ace/agent_query/` parser/tokenizer/canonicalizer/highlighter. Add a second
evaluator/planner:

- `evaluate_agent_query()` remains the hydrated `Agent` evaluator for live rows.
- Add `plan_archive_agent_query(expr) -> SQLPlan | HydrationPlan`.
- Metadata-only predicates compile to SQL over the summary index.
- `text:` and bare string searches compile to FTS5 `MATCH` queries once Phase 4 writes the search-text projection;
  before then, they fall back to bounded bundle hydration after applying all SQL metadata predicates.

For MVP, support these keys (initially compiled to SQL):

- `status`, `cl`, `project`, `name`, `model`, `provider`, `runtime`, `type` (workflow/run), `age`, `text`
- `workflow:<name>`, `step:<name>`, `step_type:<bash|python|agent|parallel>`, `step_index<N>`
- `retry_attempt>N`, `retry_of:<suffix>`, `parent:<suffix>`
- `archived_before:<date>`, `archived_after:<date>` (absolute date complements `age`)
- `revived:true|false`, `times_revived>N`
- `error:<substring>` (over `error_message` / `error_traceback`)

Defer or clearly define these:

- `tag:` until historical tags/annotations are persisted; ship `dismissed_tag:` (frozen at dismiss) and `tag:` (mutable
  annotation) once `agent_annotations` lands;
- `pinned:` only via `agent_annotations`;
- `hidden:` is rejected — "hidden" is live UI projection state, not archive state;
- `attention:` and `needs:` are rejected for archive scope unless their status mappings are made archive-stable.

Provide explicit error messages when a live-only key is used in archive scope, rather than silently returning empty.

### MVP Storage Work

Extend `dismissed_bundle_index.py` before inventing a separate database:

- Add summary columns the query planner needs but the current schema lacks: `dismissed_at`, `revived_at`,
  `times_revived`, `archive_revision`, `project_name` (normalized), `runtime`, `cost_usd_micros`,
  `input_tokens`, `output_tokens`, `error_message_excerpt`.
- Add a `search_text` column **or** an FTS5 side table populated from bounded prompt/response/chat text extracted
  during upsert/rebuild (start with up to 64 KiB per agent; document the cap).
- Add indexes for `(status)`, `(agent_name)`, `(model)`, `(llm_provider)`, `(runtime)`, `(start_time)`,
  `(project_name, cl_name)`, `(dismissed_at)`, `(revived_at)`.
- Bump schema version and run a one-shot migration during `_run_dismissed_archive_maintenance()`.
- Keep `rebuild-index` and `verify` as the repair path; `verify` should now also check payload hashes.

This is not the final architecture, but it gives the query language a scalable backend immediately and avoids loading
every bundle for every filter keystroke. Coupled with the Phase 0 quick win, no bundle is ever silently lost.

### MVP TUI Flow

Replace `DismissedAgentSelectModal._get_filtered_agents()` with a query-aware provider:

- Empty input shows the default scoped archive rows, still sorted newest-first.
- Valid query filters via `query_dismissed_bundle_summaries(query, scope, limit, cursor)`. Page size 200 with a
  "load more" affordance avoids hydrating large archives.
- Invalid query shows an inline parse error (reusing `agent_query.parser` errors) and keeps the previous result set.
- Reuse `agent_query.highlighting.tokenize_agent_query_for_display` to syntax-highlight the input box.
- Preview hydrates the selected bundle lazily and reads `prompt.md`/`reply.md`/`chat.*` from the payload (no live
  artifact dependency).
- Revival accepts summary IDs / raw suffixes and hydrates only selected rows.
- Saved-query slots from `saved_queries.py` are reused with an archive-scope prefix (e.g. `archive:0`..`archive:9`) so
  history queries can be pinned without overwriting live slots.
- Faceting strip below the input shows per-status / per-project / per-model counts for the current result set, driven
  by `GROUP BY` in the SQL plan. Users can click a facet to extend the query.

The same modal can keep a simple substring fallback if the user types a single bare word, because bare words are
already valid query terms.

A follow-up MVP+ adds a dedicated **Archive tab** parallel to the Agents tab, with persistent query, saved queries,
sort controls, and the same preview pane.

### MVP CLI Flow

Add a CLI that uses the same query path:

```bash
sase agents archive search 'status:failed project:sase age>30d'
sase agents archive show --name planner
sase agents archive show --id <agent_id>
sase agents archive stats --query 'project:sase' --by status,model
sase agents archive revive --query 'name:planner status:failed'
sase agents archive export --query 'archived_before:2025-01-01' --out ./old_runs.tar.zst
sase agents archive purge --before 2025-01-01 --dry-run
sase agents archive scrub --since-scrubber-version 3
sase agents archive rebuild-index
sase agents archive verify
```

The TUI should not be the only way to verify query semantics. CLI output also gives agents (yes — agents querying their
own history) a stable automation surface, and the `stats` subcommand is what powers TUI facet counts.

### MVP Acceptance Criteria

- Querying 10k dismissed bundles does not hydrate all bundle JSON files for metadata-only queries; p95 archive search
  latency < 100 ms on a synthetic 10k-row fixture.
- `sase agents archive rebuild-index` backfills queryable rows from existing bundles, including FTS rows.
- Reviving an agent no longer deletes its archive bundle (Phase 0 quick win).
- A re-dismissed agent produces a new `archive_revision` rather than overwriting the prior one.
- Existing `#resume:<name>` and name registry lookup still find historical dismissed bundles (and use SQL, not a
  filesystem scan).
- The revive modal supports structured queries, faceted counts, syntax highlighting, lazy preview, and saved-query
  slots.
- The query parser tests are reused; archive-query planner tests cover every supported key, including null/missing
  values and live-only-key rejection messages.
- A compatibility test proves old sharded bundles and legacy top-level bundles remain queryable after migration to
  schema v2.
- A retention test exercises `purge --before` and verifies payloads, index rows, FTS rows, and visibility rows are all
  removed in one transaction (or all rolled back on failure).
- A multi-process stress test (TUI + axe + CLI) shows no torn payload writes and no index/payload divergence.
- A privacy test exercises secret-scrubber patterns end-to-end (prompt with `sk-...` → archived payload has
  `[REDACTED]`).

## Open Questions

- **Chat-file ownership.** Should the archive copy the full chat transcript at dismiss (largest disk cost, simplest
  semantics) or store a reference plus a fallback excerpt? Default: copy with a configurable cap; fallback excerpt if
  the cap is exceeded.
- **Tag-history semantics.** Should `tag:` over archive scope mean the *current* mutable tag (annotation table) or
  *at-dismiss* tag (bundle)? Default: mutable; introduce `dismissed_tag:` for the frozen value.
- **Index home.** Stay inside `~/.sase/dismissed_bundles/index.sqlite` (path-stable, simple) or move to
  `~/.sase/agent_archive/archive.sqlite` next to a renamed payload root? Renaming has migration cost; the index can
  stay where it is until the rest of the surface stabilizes.
- **FTS analyzer.** Default `unicode61` is fine for English-shaped logs; if prompts contain code, the tokenizer should
  be tuned (e.g. `tokenize="unicode61 remove_diacritics 2 separators '/_-.'"`) so identifiers and paths are
  searchable.
- **Live-only keys in archive scope.** Reject with a parse-error-like message, or silently treat as "no match"? Reject
  is friendlier.
- **Re-archive granularity.** A revision per dismissal can produce many revisions for noisy retry-heavy agents. Cap at
  N revisions per agent and roll up older revisions into a compressed history blob? Default: keep last N=10, archive
  older revisions into a `history.jsonl` inside the payload dir.

## Concrete Recommendation

**Recommended architecture:** build a first-class Agent Archive subsystem owned by Rust core, with immutable per-
revision payload directories (bundle + prompt/reply/chat projections), mutable visibility/annotation tables, append-
only lifecycle events, SQLite + FTS5 + JSON1 materialized indexes, explicit bundle schema versioning, atomic-rename
payload writes, single-transaction index updates, and explicit retention/purge/secret-scrubbing tooling. Dismiss should
archive (writing a new revision) and hide; revive should restore from the latest revision and mark visible; neither
should delete the historical payload.

**Recommended MVP, in order of shippability:**

1. **Phase 0 (one-line quick win):** stop deleting bundles on revive; add `revived_at` to the index and have the live
   loader honor it. Immediately preserves history with zero schema upheaval.
2. Bump the index schema, add the columns and indexes the planner needs (`dismissed_at`, `revived_at`,
   `project_name`, `runtime`, cost/tokens, an FTS5 side table), and rebuild the index in place.
3. At dismiss time, copy a bounded `prompt.md`/`reply.md`/`chat.*` projection into each payload directory so `text:`
   queries have something to search.
4. Add `plan_archive_agent_query` that compiles the existing `sase.ace.agent_query` grammar into SQL/FTS plans, with
   explicit rejection of live-only keys; reuse the highlighter and saved-query slots.
5. Wire the revive modal to the archive query path with faceted counts and lazy preview; add a small
   `sase agents archive {search,show,stats,revive,rebuild-index,verify}` CLI.
6. Land retention/purge/scrub tooling and a dedicated TUI Archive tab once the query surface is stable.
