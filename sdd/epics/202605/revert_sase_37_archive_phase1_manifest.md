---
create_time: 2026-05-13 02:16:00
status: done
bead_id: sase-3b.1
parent_bead_id: sase-3b
---
# Rollback Manifest for `sase-37` Archive and Query Work

Phase 1 is audit-only. This manifest is the handoff for later implementation
phases; it intentionally makes no production code edits.

## Starting Tree

Captured before creating this manifest:

```text
## master...origin/master
```

`git status --short` was empty. The only intended Phase 1 file edits are this
manifest and the `sase-3b.1` bead metadata update used to close the phase.

## Pre-`sase-37` Reference Point

Use `7fcb5706d^` as the pre-archive-query reference. Fetch exact historical
content with:

```bash
git show 7fcb5706d^:<path>
```

Reference files to use for manual restore work:

- `src/sase/ace/dismissed_agents.py`
- `src/sase/ace/dismissed_bundle_index.py`
- `src/sase/ace/tui/actions/agents/_revive.py`
- `src/sase/ace/tui/modals/revive_agent_modal.py`
- `src/sase/ace/tui/models/agent_bundle.py`
- `src/sase/agents/cli_archive.py`
- `src/sase/main/parser_agents.py`
- `src/sase/ace/agent_query/__init__.py`
- `src/sase/ace/agent_query/evaluator.py`
- `src/sase/ace/agent_query/highlighting.py`
- `src/sase/ace/agent_query/parser.py`
- `src/sase/ace/agent_query/tokenizer.py`
- `src/sase/ace/agent_query/types.py`

Files absent at `7fcb5706d^` and therefore introduced by the archive/query
work or follow-on refactors:

- `src/sase/ace/archive_search_text.py`
- `src/sase/ace/agent_query/archive_planner.py`
- `src/sase/core/agent_archive_facade.py`
- `src/sase/core/agent_archive_wire.py`
- `src/sase/ace/dismissed_agents_bundles.py`
- `src/sase/ace/dismissed_agents_lifecycle.py`
- `src/sase/ace/dismissed_agents_migrations.py`
- `src/sase/ace/dismissed_agents_paths.py`
- `src/sase/ace/dismissed_agents_state.py`
- `src/sase/ace/tui/modals/revive_agent_filter_input.py`
- `src/sase/ace/tui/modals/revive_agent_formatting.py`
- `src/sase/ace/tui/modals/revive_agent_preview.py`
- `src/sase/ace/tui/modals/revive_agent_types.py`
- `tests/test_agent_query_archive_planner.py`
- `tests/test_agents_archive_cli.py`
- `tests/ace/tui/modals/test_revive_agent_modal.py`
- `tests/_dismissed_agents_helpers.py`
- `tests/test_dismissed_agents_state.py`
- `tests/test_dismissed_bundle_index.py`
- `tests/test_dismissed_bundle_persistence.py`
- `tests/test_dismissed_bundle_removal_migration.py`

Legacy archive surface at `7fcb5706d^`:

- `sase agents archive rebuild-index`
- `sase agents archive verify`
- `handle_agents_archive()` in `src/sase/agents/cli_archive.py` dispatches only
  those two maintenance subcommands.
- `src/sase/main/parser_agents.py` registers only `rebuild-index` and `verify`
  beneath `agents archive`.
- `src/sase/ace/dismissed_bundle_index.py` is a single SQLite summary-index
  module with `upsert_bundle_summary`, `delete_bundle_summaries_for_suffixes`,
  `query_summaries`, `query_bundle_paths_by_suffixes`, `rebuild_index`, and
  `verify_index`. It has no FTS table, payload hash verification, immutable
  revision path, lifecycle commands, or Rust archive facade.

## Rollback Decisions by Commit

| Commit | Files touched | Added symbols/options/tests | Decision |
| --- | --- | --- | --- |
| `7fcb5706d` `feat: add v2 dismissed bundle archive index (sase-37.2)` | `src/sase/ace/dismissed_bundle_index.py`, `tests/test_dismissed_agents.py`, bead metadata | v2 summary fields: stable `agent_id`, archive metadata, query-facing columns, schema version migration tests | Restore previous behavior. Return the index to the `7fcb5706d^` summary schema and remove v2-only columns unless a later non-archive caller demonstrably needs a field. |
| `bea1750ad` `feat: add searchable archive bundle projections (sase-37.3)` | Adds `src/sase/ace/archive_search_text.py`; changes `dismissed_bundle_index.py`, `agent_bundle.py`, `tests/test_agent_model_bundle.py`, `tests/test_dismissed_agents.py` | `build_archive_search_text`, `normalize_archive_bundle_projection`, `scrub_archive_text`; bundle keys `archive_search_text`, `archive_search_scrubber_version`, `bundle_schema_version`, `archive_revision`; projection/backfill tests | Remove. Delete `archive_search_text.py`, remove projection writes from `to_bundle_dict()` and normalization from `from_bundle_dict()`, and remove projection tests. |
| `085e86d92` `feat: add archive query planner (sase-37.4)` | Adds `src/sase/ace/agent_query/archive_planner.py`, `tests/test_agent_query_archive_planner.py`; changes agent query parser/tokenizer/types/evaluator, dismissed agents/index | `ArchiveQueryError`, `ArchiveQueryResult`, `ArchiveQueryPage`, `search_archive`, `select_archive_results`, `archive_facet_counts`, `NumericCompare`, archive keys `archived_before`, `archived_after`, `revived`, `step_type`, `retry_of`, `parent`, `error`, numeric keys `step_index`, `retry_attempt`, `cost`, `input_tokens`, `output_tokens`, `tokens`; FTS query support | Remove archive planner. Restore live-agent query exports. Remove archive-only grammar and numeric comparisons unless live query tests prove a non-archive use. Delete archive planner tests and trim parser/tokenizer/evaluator archive expectations. |
| `08b9111ae` `feat: add dismissed agent archive CLI (sase-37.5)` | `src/sase/agents/cli_archive.py`, `src/sase/main/parser_agents.py`, `dismissed_agents.py`, archive planner, `tests/test_agents_archive_cli.py` | CLI subcommands `search`, `show`, `stats`, `revive`; exact selectors `--agent-id`, `--name`, `--suffix`; output `--json`; query/limit/cursor/facet options; `_revive_archive_rows`, `_result_to_dict`, `_format_result_line`; CLI tests | Split manually. Restore CLI/parser to only `rebuild-index` and `verify`; remove archive query/show/stats/revive code and tests. Preserve any unrelated parser changes outside `agents archive`. |
| `0ef1b84cd` `feat: add archive-backed revive search (sase-37.6)` | `dismissed_agents.py`, `_revive.py`, `revive_agent_modal.py`, `tests/ace/tui/modals/test_revive_agent_modal.py` | `_ScopedArchiveQueryProvider`, `search_dismissed_archive`, archive-backed modal rows, query input, invalid-query result preservation, load-more behavior, lazy hydrate path | Remove. Restore revive flow to legacy dismissed-agent selection/preview without archive query provider, pagination, or FTS search. Remove query-backed modal tests. |
| `ce8cb9e37` `feat: harden dismissed agent archive storage (sase-37.7)` | `dismissed_agents.py`, `dismissed_bundle_index.py`, `src/sase/core/agent_cleanup_execution.py`, cleanup and dismissed-agent tests | Immutable archive revision directories, `next_archive_revision`, `archive_bundle_path`, immediate SQLite transactions, maintenance lock, atomic fallback writes, revision preservation tests | Split manually. Remove immutable revision behavior and archive-revision schema. Keep atomic-write or cleanup execution improvements only if they still apply to legacy bundle paths and do not require revisions. |
| `ac5487d67` `feat: add archive lifecycle commands (sase-37.8)` | `archive_search_text.py`, `dismissed_agents.py`, `dismissed_bundle_index.py`, `cli_archive.py`, `parser_agents.py`, archive CLI/index tests | CLI subcommands `purge`, `scrub`, `export`; `purge_dismissed_archive`, `scrub_dismissed_archive`, `export_dismissed_archive`; payload hash diagnostics; FTS verification; lifecycle audit/report helpers | Remove. Delete lifecycle commands, parser options, facade exports, lifecycle tests, payload-hash verification, FTS diagnostics, and scrubber versioning. |
| `b9954bb0a` `feat: route archive operations through Rust facade (sase-37.9)` | Adds `src/sase/core/agent_archive_facade.py`, `src/sase/core/agent_archive_wire.py`; changes archive planner and dismissed agents | `AgentArchiveQueryRequestWire`, `AgentArchiveFacetRequestWire`, `AgentArchiveReviveMarkRequestWire`, `try_query_agent_archive`, `try_agent_archive_facet_counts`, `try_mark_agent_archive_bundles_revived`, `try_verify_agent_archive_index` | Remove. Delete Python Rust archive facade and wire modules, remove all imports, and ensure no Rust archive binding is required by dismissed bundle maintenance. |
| `4f216979a` `chore: Add SDD prompt and plan for sase_37_completion (sase-37)` | `sdd/prompts/202605/sase_37_completion.md`, `sdd/tales/202605/sase_37_completion.md`, bead metadata | Historical completion prompt/tale | Keep historical SDD records unless a later explicit cleanup phase updates rollback documentation. Do not mutate historical `sase-37` closure records. |

## Follow-On Repair and Refactor Decisions

| Commit | Files touched | Added symbols/options/tests | Decision |
| --- | --- | --- | --- |
| `3edabc3be` `fix: preserve archive bundles on revive` | `dismissed_agents.py`, `_revive.py`, revive tests, dismissed bundle index tests, SDD records | `mark_bundles_revived_by_suffixes` behavior that marks bundles instead of removing them; removes destructive bundle-removal helper expectations | Split manually. Restore pre-query revive semantics. If legacy revive still requires persisted bundles for future revive visibility, keep non-query bundle preservation, but remove `revived_at`/`times_revived` archive lifecycle marking and tests tied to immutable archive history. |
| `fa970b1d6` `ref: split dismissed bundle index module` | Deletes `src/sase/ace/dismissed_bundle_index.py`; adds package modules `_api.py`, `_bundle_io.py`, `_models.py`, `_schema.py`, `_summary.py` | Package facade preserving imports; separates schema, summary projection, bundle IO, API | Restore previous behavior. Collapse back to single-file legacy module if no unrelated post-split imports need package internals. If package facade is kept temporarily, strip v2/FTS/revision internals first. |
| `ab1b897e7` `ref: split revive agent modal modules` | Adds `revive_agent_filter_input.py`, `revive_agent_formatting.py`, `revive_agent_preview.py`, `revive_agent_types.py`; changes `revive_agent_modal.py` | Helper modules for query-aware modal formatting, filter input, preview hydration, archive row types | Remove or collapse manually. Keep only helper code that is useful for the legacy modal after archive-query removal; otherwise restore the monolithic `revive_agent_modal.py` from `7fcb5706d^` and merge current unrelated modal conventions by hand. |
| `a1228da5f` `fix: drop O(N) bundle scan from dismiss persistence path` | `dismissed_agents.py`, `dismissed_bundle_index/_api.py`, `tests/test_dismissed_agents.py`, `sdd/tales/202605/dismiss_freeze.md` | `next_archive_revision()` optimization and perf smoke around avoiding filesystem scans | Remove with revisions. The performance fix is compensating for immutable archive revisions. It should disappear when the legacy single-bundle path is restored. Preserve the SDD tale as history. |
| `4173b39e0` `ref: split dismissed agent tests` | Adds `_dismissed_agents_helpers.py`, `test_dismissed_agents_state.py`, `test_dismissed_bundle_index.py`, `test_dismissed_bundle_persistence.py`, `test_dismissed_bundle_removal_migration.py`; deletes `test_dismissed_agents.py` | Test-only split | Split manually. Later phases may keep the split if it reduces churn, but test contents must describe legacy storage/index/revive semantics and not archive query/lifecycle behavior. |
| `d8d28113f` `fix: keep revive modal responsive while archive search runs` | `dismissed_agents.py`, `_revive.py`, `revive_agent_modal.py`, modal and bundle-index tests, SDD tale | `ensure_dismissed_archive_ready`, worker prewarm, debounced archive search, PgDn/load scheduling path | Remove. This is query-aware modal stabilization and should vanish with the archive provider. |
| `f1d4f3513` `ref: split dismissed agents module` | `dismissed_agents.py`, new `dismissed_agents_bundles.py`, `dismissed_agents_lifecycle.py`, `dismissed_agents_migrations.py`, `dismissed_agents_paths.py`, `dismissed_agents_state.py`, `Justfile` pyvision allowlist | Facade plus split modules for archive state, paths, lifecycle, migrations, bundles | Split manually. Remove lifecycle/query modules. Either collapse back to the `7fcb5706d^` single-file shape or keep a small facade only if it avoids unrelated churn. Revisit the `Justfile` pyvision allowlist separately because it may be an unrelated refactor cleanup. |
| `4d4fce3b6` `fix: avoid revive modal pagination key conflict` | `revive_agent_modal.py`, modal tests, `sdd/tales/202605/agent_revival_keymaps.md` | Archive pagination moves from `ctrl+n` to `PgDn`; pagination regression tests | Remove. Archive pagination is deleted; preserve normal row navigation behavior. Keep the SDD tale as historical unless Phase 6 explicitly updates rollback docs. |
| `c307d265c` archive portions of `fix: harden audit edge cases` | `archive_planner.py`, `tests/test_agent_query_archive_planner.py`, plus unrelated commit-hook/test files | Zero-limit archive search cursor behavior | Remove archive portions only. Preserve `src/sase/scripts/sase_commit_stop_hook.py`, `tools/sase_sibling_commit_stop_hook`, and commit/sibling hook tests. |
| `bbdc04b29` archive portions of `fix: repair archive audit regressions` | `archive_planner.py`, `dismissed_agents_lifecycle.py`, `_revive.py`, archive planner/CLI/revive tests | Export collision handling for repeated archive revisions, zero-limit query fix, revive modal scheduling ownership | Remove archive portions. Preserve no changes from this commit unless `_revive.py` contains non-query revive correctness that overlaps with `179cf50b9`. |
| `179cf50b9` `fix: revive surfaces agents when artifact index is empty` | `_loading.py`, `_revive.py`, revive helper/tests, loader self-heal tests, SDD tale | `_load_agents(full_history=True)` from revive, `_preserve_revived_agents_for_incomplete_load` fallback to `_dismissed_agent_objects` | Keep unless Phase 5 proves it only compensates for archive-query modal state. The bug description is independent of archive query: a revived agent can stay hidden when Tier 1 artifact index is empty-but-valid. Preserve this behavior during revive rollback. |

## Symbols and Surfaces to Remove

Remove these unless a later phase proves an independent live-agent need:

- `src/sase/ace/agent_query/archive_planner.py`
- `ArchiveQueryError`, `ArchiveQueryResult`, `ArchiveQueryPage`
- `search_archive`, `select_archive_results`, `archive_facet_counts`
- `src/sase/ace/archive_search_text.py`
- `build_archive_search_text`, `normalize_archive_bundle_projection`,
  `scrub_archive_text`
- `src/sase/core/agent_archive_facade.py`
- `src/sase/core/agent_archive_wire.py`
- `AgentArchiveQueryRequestWire`, `AgentArchiveFacetRequestWire`,
  `AgentArchiveReviveMarkRequestWire`
- `try_query_agent_archive`, `try_agent_archive_facet_counts`,
  `try_mark_agent_archive_bundles_revived`, `try_verify_agent_archive_index`
- `purge_dismissed_archive`, `scrub_dismissed_archive`,
  `export_dismissed_archive`, `search_dismissed_archive`,
  `ensure_dismissed_archive_ready`
- `next_archive_revision`, `archive_bundle_path`, `archive_payload_hash`
- bundle/index fields `archive_revision`, `bundle_schema_version`,
  `archive_search_text`, `archive_search_scrubber_version`,
  `archive_payload_sha256`, `revived_at`, `times_revived` when used only for
  archive lifecycle/query semantics
- FTS table `dismissed_bundle_search_fts`
- archive CLI subcommands `search`, `show`, `stats`, `revive`, `purge`,
  `scrub`, `export`
- revive modal archive-query provider, query input semantics, load-more
  pagination, archive summary rows, archive lazy hydrate path
- archive-only query keys `archived_before`, `archived_after`, `revived`,
  `step_type`, `retry_of`, `parent`, `error`
- archive numeric query support `NumericCompare` and numeric keys
  `step_index`, `retry_attempt`, `cost`, `cost_usd_micros`, `input_tokens`,
  `output_tokens`, `tokens`, unless retained for live-agent query behavior

## Tests to Remove or Rewrite

Remove outright:

- `tests/test_agent_query_archive_planner.py`
- archive-search/show/stats/revive/purge/scrub/export cases in
  `tests/test_agents_archive_cli.py`; delete the file if no legacy
  `rebuild-index`/`verify` coverage remains.
- query-backed modal cases in `tests/ace/tui/modals/test_revive_agent_modal.py`
  if the legacy modal does not need a dedicated split test file.

Rewrite around legacy semantics:

- `tests/test_dismissed_bundle_index.py`
- `tests/test_dismissed_bundle_persistence.py`
- `tests/test_dismissed_bundle_removal_migration.py`
- split dismissed-agent state tests created from `tests/test_dismissed_agents.py`
- `tests/test_agent_model_bundle.py` bundle projection expectations
- query parser/tokenizer/evaluator/canonicalization tests that only exercise
  archive keys or numeric comparators
- revive tests that assert archive lifecycle markers instead of visible restore
  behavior

Keep or preserve carefully:

- `tests/test_agent_loader_self_heal.py` and `tests/test_agent_revive.py`
  coverage for the `179cf50b9` empty artifact-index revive visibility fix,
  unless Phase 5 proves it is archive-query-specific.
- SASE-38, Qwen, pyvision, workspace, fix_just, display-panel, and commit-hook
  test changes listed below.

## Unrelated Work to Preserve

Do not roll back these commits or their file changes just because they are in
the same May 12 window.

SASE-38 and starting-agent status:

- `2ac00dca4`, `f3bfc064f`, `4bba22bbd`, `85305d599`, `3e5cf34c9`,
  `47575609b`, `c76f6c660`, `138742da1`, `ae9ef6588`
- Preserve `src/sase/axe/run_agent_phases.py`,
  `src/sase/axe/run_agent_runner.py`, `src/sase/ace/tui/actions/agents/*`
  starting-status changes, `src/sase/agent/status_buckets.py`,
  `src/sase/agent/running.py`, `src/sase/agents/cli_status.py`,
  `src/sase/core/agent_scan_wire_markers.py`,
  `src/sase/integrations/_mobile_agent_summary.py`, related tests, and
  `sdd/epics/202605/agents_starting_status.md`.

Qwen/opencode runtime, color, and hook work:

- `3b1a4f8eb`, `74d1e54e6`, `3fa3aa5f3`, `0dd0130ba`, `47dae48a6`,
  `6f164e20d`, `2b97e5867`, `3ff74da2b`
- Preserve `.qwen/settings.json`, `QWEN.md`, `docs/llms.md`,
  `memory/long/llm_provider_hooks.md`, `src/sase/llm_provider/qwen.py`,
  `src/sase/scripts/sase_commit_stop_hook.py`,
  `tools/sase_sibling_commit_stop_hook`, and Qwen/commit-hook tests.

Pyvision, fix_just, and workspace fixes:

- `c8cd634d1`, `559f7baf2`, `01847ad31`, `f6fb8dc1d`, `28c8459ea`,
  `1f982945d`, `62dff89a7`, `060a53142`, `e8140ce38`, `336bc7e86`
- Preserve pyvision vendoring/tooling changes in `Justfile`, `tools/*`, and
  `src/sase/ace/testing/__init__.py`; fix_just workflow tests and
  `xprompts/fix_just.yml`; workspace env spawn changes in
  `src/sase/agent/launch_spawn.py`, `src/sase/axe/run_agent_exec_retry.py`,
  `src/sase/axe/run_agent_phases.py`, `src/sase/axe/run_agent_runner.py`,
  `src/sase/axe/run_workflow_runner.py`, and related tests.

Generic display, runner, timestamp, ChangeSpec, and audit workflow work:

- `288320521`, `19b81ecbd`, `5fa84b827`, `3b5cbe6bb`, `5d6f62346`,
  `3db050b23`, `ca9c5bfa2`, `351b6a970`
- Preserve display panel split files, retry test split files, submitted xprompt
  error-report changes, DONE timestamp label changes, starting-agent sort order,
  removal of unused `with_options`, ChangeSpec test target removal, and bundled
  audit workflow validation.

## Later Phase Editing Guidance

- Use `git show 7fcb5706d^:<path>` as reference content, but do not overwrite
  whole files blindly. Later refactors and unrelated work are interleaved.
- Start with the narrow archive removals: archive planner, archive search text,
  archive CLI subcommands, Rust archive facade, FTS/revision/payload-hash
  schema, and query-aware revive modal.
- After each file group, run `rg` for removed symbols before broad tests.
- Treat `src/sase/ace/tui/actions/agents/_revive.py` and
  `src/sase/ace/tui/modals/revive_agent_modal.py` as split-manual files because
  they contain both archive-query work and possibly independent revive
  correctness from `179cf50b9`.
- Do not edit memory files. The Qwen hook commit touched
  `memory/long/llm_provider_hooks.md`; it is unrelated and must remain intact.
- Do not close parent epic `sase-3b` during phase work.
