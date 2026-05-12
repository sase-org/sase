---
create_time: 2026-05-12 16:07:47
status: done
prompt: sdd/prompts/202605/agent_archive_query.md
bead_id: sase-37
tier: epic
---
# Agent Archive and Query Language Implementation Plan

## Goal

Implement the dismissed-agent archive architecture recommended in
`sdd/research/202605/dismissed_agent_archive_and_query_language.md` in phases that can be handed to distinct agent
instances. The end state is that dismissed agents are durable historical records, revive is a visibility/restore
operation rather than archive deletion, and both CLI/TUI can query historical agents through the existing agent query
language without hydrating the entire archive.

## Current Context

The current archive implementation is Python-first and centered on:

- `src/sase/ace/dismissed_agents.py` for bundle save/load/remove and archive maintenance.
- `src/sase/ace/dismissed_bundle_index.py` for schema v1 SQLite summary indexing.
- `src/sase/ace/tui/actions/agents/_revive.py` for revive, which currently calls `remove_bundle_by_identity`.
- `src/sase/ace/tui/modals/revive_agent_modal.py` for the revive modal, which currently filters hydrated `Agent` rows in
  memory.
- `src/sase/ace/tui/models/agent_bundle.py` for bundle serialization, which excludes `attempt_history` and `tag`.
- `src/sase/ace/agent_query/` for the existing live-agent parser/tokenizer/evaluator/highlighter.
- `src/sase/agents/cli_archive.py` and `src/sase/main/parser_agents.py` for the existing
  `sase agents archive {rebuild-index,verify}` CLI.
- `../sase-core/crates/sase_core/src/agent_cleanup/` for Rust cleanup planning/execution. Per
  `memory/short/rust_core_backend_boundary.md`, shared backend archive semantics should eventually move here.

Important constraints:

- Preserve existing sharded bundle paths under `~/.sase/dismissed_bundles/` until a dedicated migration phase is
  explicitly scheduled.
- Keep legacy top-level and sharded bundle files readable.
- Treat all runtimes uniformly; do not add Claude-only archive behavior.
- Each phase below should be completed by a separate agent instance. Each phase must leave `just check` passing in this
  repo, after running `just install` first in the workspace.

## Phase 0: Preserve Archive Bundles on Revive

Purpose: ship the smallest behavior change that immediately stops history loss.

Scope:

- Replace destructive revive cleanup with a visibility/event mark:
  - Add `revived_at` and `times_revived` to the dismissed bundle index.
  - Add a helper such as `mark_bundle_revived_by_identity(...)` in `dismissed_agents.py` / `dismissed_bundle_index.py`.
  - Update `_do_revive_agent` and `_do_revive_agents` to call the new helper instead of `remove_bundle_by_identity`.
- Keep `remove_bundle_by_identity` as a low-level destructive helper for future `purge`, legacy tests, and explicit
  maintenance commands.
- Ensure revive still removes identities from `dismissed_agents.json`, restores artifacts, records revived suffixes, and
  reloads/selects the revived agent.
- Update tests that currently expect revive to delete bundle files, and add tests proving revive leaves bundle JSON and
  index summaries in place while setting `revived_at`.

Files likely touched:

- `src/sase/ace/dismissed_bundle_index.py`
- `src/sase/ace/dismissed_agents.py`
- `src/sase/ace/tui/actions/agents/_revive.py`
- `tests/test_agent_revive*.py`
- `tests/test_dismissed_agents.py`

Acceptance:

- Reviving one agent and a batch no longer deletes bundle files.
- `remove_bundle_by_identity` tests still cover explicit deletion.
- Existing revive behavior remains user-visible except bundles persist.

## Phase 1: Versioned Archive Index Schema and Stable Summary Model

Purpose: make the SQLite index a real archive summary table that can be migrated and queried.

Scope:

- Bump `dismissed_bundle_index.SCHEMA_VERSION` from v1 to v2.
- Replace the current "drop table on version mismatch" path with explicit migration helpers. It is acceptable for v1 to
  rebuild from bundles on first open, but this should be named and tested as migration behavior rather than silent
  schema reset.
- Extend `_DismissedBundleSummary` and the table with query-facing columns:
  - `agent_id`
  - `archive_revision`
  - `bundle_schema_version`
  - `dismissed_at`
  - `revived_at`
  - `times_revived`
  - `project_name`
  - `runtime`
  - `cost_usd_micros`
  - `input_tokens`
  - `output_tokens`
  - `error_message_excerpt`
- Use deterministic `agent_id` derived from available stable fields for now:
  `sha256(project_file + "\0" + raw_suffix + "\0" + agent_type + "\0" + step_index_or_empty)`.
- Add useful B-tree indexes for status, name, model, provider, runtime, start time, project/CL, dismissed time, and
  revived time.
- Keep the public `load_dismissed_bundle_summaries(...)` behavior compatible.

Files likely touched:

- `src/sase/ace/dismissed_bundle_index.py`
- `src/sase/ace/dismissed_agents.py`
- `tests/test_dismissed_agents.py`

Acceptance:

- Legacy v1 indexes migrate or rebuild safely.
- Existing bundles missing new fields remain indexable.
- Summary rows expose the new fields.
- `verify` still reports stale/missing/corrupt rows accurately.

## Phase 2: Bundle Schema Versioning and Searchable Payload Projections

Purpose: make archived payloads contain enough data for durable text search.

Scope:

- Add `bundle_schema_version` and `archive_revision` to `Agent.to_bundle_dict()` output.
- Add a migration/normalization path in `Agent.from_bundle_dict()` for version 0 bundles.
- Capture bounded text projections at dismiss time:
  - prompt text from `raw_xprompt.md`
  - live reply / response text
  - chat transcript excerpt from `agent_meta.json.chat_path` when available
  - per-attempt reply excerpts when available
- Store projections in a backward-compatible way. Prefer a sidecar payload directory next to the JSON only if the phase
  can do so without destabilizing existing loaders; otherwise store a bounded `archive_search_text` field in the bundle
  as an intermediate MVP.
- Introduce a shared helper for building archive search text so rebuild-index can backfill old bundles from surviving
  files when possible.
- Add a small, versioned secret scrubber for obvious high-risk token patterns. It can be conservative in this phase, but
  it must be idempotent and tested.

Files likely touched:

- `src/sase/ace/tui/models/agent_bundle.py`
- `src/sase/ace/dismissed_agents.py`
- `src/sase/ace/dismissed_bundle_index.py`
- `src/sase/ace/tui/models/agent_content_search.py` or a new non-TUI archive text helper
- `tests/test_agent_model_bundle.py`
- `tests/test_dismissed_agents.py`

Acceptance:

- New bundles include schema/revision metadata.
- New dismissed bundles contain a bounded searchable text projection even if live artifact files are later removed.
- Old bundles still load.
- Secret-like sample strings are redacted from the archived search projection.

## Phase 3: FTS and Archive Query Planner

Purpose: compile the existing agent query language into SQLite/FTS archive queries.

Scope:

- Extend the agent query tokenizer/parser for archive-supported keys without breaking live-agent behavior:
  - `runtime`
  - `archived_before`
  - `archived_after`
  - `revived`
  - `step_type`
  - `step_index`
  - `retry_attempt`
  - `retry_of`
  - `parent`
  - `error`
  - comparator support for cost/tokens if feasible without awkward grammar churn.
- Add an archive-scope planner module, for example `src/sase/ace/agent_query/archive_planner.py`.
- Compile metadata predicates to SQL over `dismissed_bundle_summaries`.
- Add an FTS5 side table or equivalent indexed search path for `text:` and bare strings from Phase 2 search text.
- Explicitly reject live-only archive keys (`hidden`, `attention`, `needs`) with actionable error messages in archive
  scope.
- Add cursor/limit support and a compact result dataclass so the TUI can page results without hydrating all bundles.
- Add facet-count helpers for status/project/model/runtime.

Files likely touched:

- `src/sase/ace/agent_query/tokenizer.py`
- `src/sase/ace/agent_query/parser.py`
- `src/sase/ace/agent_query/types.py`
- new `src/sase/ace/agent_query/archive_planner.py`
- `src/sase/ace/dismissed_bundle_index.py`
- `tests/test_agent_query_*.py`
- new archive planner tests

Acceptance:

- Metadata-only queries do not read bundle JSON files.
- `text:` queries use indexed search when the FTS/search table is populated.
- Unsupported live-only keys fail loudly in archive scope.
- Query tests cover old live behavior and new archive behavior.

## Phase 4: Archive CLI Search/Show/Stats/Revive

Purpose: expose the new query path outside the TUI so behavior is scriptable and easy to test.

Scope:

- Expand `sase agents archive` from maintenance-only to:
  - `search <query> [--limit N] [--json]`
  - `show --id <agent_id>` / `show --name <name>` / `show --suffix <raw_suffix>`
  - `stats [--query <query>] [--by status,model,project,runtime] [--json]`
  - `revive --query <query>` as a conservative MVP, requiring a single unambiguous result unless `--all` is provided.
- Keep existing `rebuild-index` and `verify`.
- Reuse the Phase 3 planner for search/stats.
- Hydrate bundles only in `show` and selected `revive` rows.
- Make JSON output stable enough for later TUI tests and external automation.

Files likely touched:

- `src/sase/main/parser_agents.py`
- `src/sase/agents/cli_archive.py`
- `src/sase/main/agents_handler.py` only if dispatch shape changes
- `tests/main/test_agents_handler.py`
- new CLI archive tests

Acceptance:

- `sase agents archive search 'status:failed project:sase'` returns summaries.
- `stats` reports grouped counts from the same planner.
- CLI revive preserves bundles, restores artifacts, and uses the same underlying revive helpers as the TUI where
  possible.
- Existing maintenance commands keep their current exit-code behavior.

## Phase 5: Query-Aware Revive Modal

Purpose: move the TUI revive flow from in-memory substring filtering to archive-backed structured queries.

Scope:

- Refactor `DismissedAgentSelectModal` to accept an archive query provider rather than only a list of hydrated agents.
- Keep the current initial list behavior for fast same-session dismissed agents, but replace archive-loaded filtering
  with the Phase 3 query API.
- Reuse `agent_query.highlighting` for input syntax highlighting if Textual input constraints make this practical; if
  not, keep plain input and surface parse errors clearly.
- Add:
  - inline parse/unsupported-key errors
  - lazy preview hydration
  - page size / load-more behavior
  - facet strip if it fits cleanly without UI churn
  - archive-scope saved-query slots if the current `saved_queries.py` shape supports namespacing cleanly.
- Preserve existing multi-select behavior and workflow child restoration.

Files likely touched:

- `src/sase/ace/tui/modals/revive_agent_modal.py`
- `src/sase/ace/tui/actions/agents/_revive.py`
- `src/sase/ace/saved_queries.py`
- TUI/modal tests under `tests/ace/tui/`

Acceptance:

- Empty input shows newest dismissed archive rows without hydrating the entire archive.
- Structured input filters via the archive planner.
- Invalid input does not erase the previous valid result set.
- Preview hydrates only the highlighted row.
- Existing keyboard behavior remains intact.

## Phase 6: Re-Archive Revisions, Atomic Writes, and Concurrency

Purpose: make repeated dismiss/revive/dismiss cycles immutable and robust under multiple writers.

Scope:

- Make each dismissal create a new `archive_revision` rather than overwriting the same `{raw_suffix}.json` payload.
- If full payload directories were deferred in Phase 2, introduce them here:
  `~/.sase/dismissed_bundles/YYYYMM/<agent_id>.<revision>/bundle.json` plus sidecars, with compatibility loading for old
  single-file bundles.
- Add atomic temp-write + rename for Python fallback writes.
- Update Rust `save_dismissed_bundle_json` to write atomically in `../sase-core`.
- Add advisory locking around rebuild/purge-like maintenance.
- Ensure index writes use transactions that update summary, FTS, and visibility/revival metadata together.

Files likely touched:

- `src/sase/ace/dismissed_agents.py`
- `src/sase/ace/dismissed_bundle_index.py`
- `src/sase/core/agent_cleanup_execution.py`
- `../sase-core/crates/sase_core/src/agent_cleanup/execution.rs`
- Rust binding exposure if needed
- tests in both repos

Acceptance:

- Re-dismissing a revived agent preserves previous revisions.
- Concurrent-like tests cannot observe torn JSON or index/payload divergence.
- Legacy single-file bundles remain queryable.

## Phase 7: Retention, Purge, Scrub, Export, and Verify+

Purpose: add explicit lifecycle controls so "forever" is operationally manageable.

Scope:

- Add CLI commands:
  - `purge --before DATE | --id AGENT_ID | --query QUERY --dry-run`
  - `scrub --before DATE | --query QUERY | --since-scrubber-version N`
  - `export --query QUERY --out PATH`
- Extend verify to check:
  - payload hashes where available
  - FTS rows match summary rows
  - visibility/revision rows are not orphaned
- Store redacted audit events for purge/scrub/export.
- Make purge remove payloads, summaries, FTS rows, visibility rows, and annotations as one logical operation.

Files likely touched:

- `src/sase/main/parser_agents.py`
- `src/sase/agents/cli_archive.py`
- `src/sase/ace/dismissed_agents.py`
- `src/sase/ace/dismissed_bundle_index.py`
- tests for CLI and archive storage

Acceptance:

- Dry-run reports exactly what would be removed.
- Purge removes all related rows/files or reports partial failure clearly.
- Scrub is idempotent and records the scrubber version.
- Export creates a restorable archive artifact for matching rows.

## Phase 8: Move Canonical Archive Backend to Rust Core

Purpose: align the final architecture with the Rust core backend boundary after the Python MVP has stabilized.

Scope:

- Design Rust wire types for archive snapshots, summaries, query requests, query results, facets, purge/scrub reports,
  and verify reports.
- Move stable storage/query/visibility operations into `../sase-core/crates/sase_core`.
- Expose bindings through `sase_core_rs`.
- Keep Python as a thin adapter for CLI/TUI presentation and `Agent` conversion.
- Preserve the Python public functions during migration to minimize churn in TUI call sites.

Files likely touched:

- `../sase-core/crates/sase_core/src/agent_archive/` or equivalent new module
- `../sase-core/crates/sase_core/src/lib.rs`
- binding crate files
- `src/sase/core/*archive*_wire*.py`
- `src/sase/ace/dismissed_agents.py`
- `src/sase/ace/dismissed_bundle_index.py` may become a compatibility adapter

Acceptance:

- Python and Rust tests agree on query results for shared fixtures.
- CLI/TUI behavior is unchanged after swapping the backend.
- The Rust API is usable by future web/editor/mobile surfaces without importing TUI code.

## Suggested Phase Ordering

Run phases sequentially. Phase 0 can ship independently. Phases 1-4 form the MVP query language. Phase 5 completes the
TUI user experience. Phases 6-8 harden the system into the recommended long-term architecture.

Minimum useful release:

1. Phase 0
2. Phase 1
3. Phase 2 with `archive_search_text` or FTS backfill
4. Phase 3 metadata + text query planner
5. Phase 4 CLI `search/show/stats`

The dedicated TUI Archive tab from the research note should wait until after Phase 5 proves the query/preview UX in the
revive modal. At that point it can be planned as a separate UI phase rather than bundled into the storage/query MVP.

## Cross-Phase Handoff Rules

- Do not remove legacy functions until all call sites have migrated.
- Each phase must document any new schema version, migration marker, or compatibility behavior in tests.
- Each phase must run `just install` before validation and `just check` before final response.
- If a phase touches `../sase-core`, validate the Rust core tests relevant to the changed crate in addition to this
  repo's `just check`.
- Commit only when explicitly requested by the user or by the repository's post-completion hook.
