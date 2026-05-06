---
create_time: 2026-05-06 00:00:00
status: done
bead_id: sase-24.6.1
epic: sdd/epics/202605/artifacts_panel_epic6_rollout.md
---
# Artifacts Panel Epic 6 Contract Audit

## Scope

This is the Phase 6.1 audit for `sase-24.6.1`. It inventories the landed artifact-panel contract before later Epic 6
agents update benchmarks, backend/CLI tests, TUI tests, docs, and the final rollout note.

No production behavior changed in this phase.

## Prior Epic Status

Prior phase beads for Epics 1-5 are landed:

- Epic 1 phases `sase-24.1.1` through `sase-24.1.6`: closed.
- Epic 2 phases `sase-24.2.1` through `sase-24.2.6`: closed.
- Epic 3 phases `sase-24.3.1` through `sase-24.3.6`: closed.
- Epic 4 phase beads are closed, including `sase-24.4.2`, `sase-24.4.3`, `sase-24.4.4`, `sase-24.4.5`, and
  `sase-24.4.6`.
- Epic 5 phases `sase-24.5.1` through `sase-24.5.5`: closed.

Bookkeeping drift: the Epic 4 parent bead `sase-24.4` is still open even though its child phase beads are closed. This
does not block Phase 6.1 because no prior phase bead remains open, but Phase 6.6 should verify whether the Epic 4 parent
can be closed separately. Do not close it from an Epic 6 child phase.

## Traceability Matrix

| Legend acceptance criterion | Existing coverage | Notes for Epic 6 |
| --- | --- | --- |
| `sase ace` startup does not run broad artifact graph rebuild, list, show, search, or summary calls | `tests/ace/tui/actions/test_agent_artifact_startup_contracts.py`; `tests/perf/artifact_graph/startup_measurements.py` | Startup sentinel patches `artifact_rebuild`, `artifact_list`, `artifact_show`, `artifact_show_paged`, `artifact_search`, and `artifact_summary` and expects zero calls. |
| Newly-created artifacts use bounded targeted refresh | `tests/ace/tui/test_artifact_graph_refresh.py`; `tests/perf/artifact_graph/fixture_measurements.py` | Covers agent marker dirs, created files, project files, bead store, direct directory targets, missing artifact refresh, and burst dedupe. |
| Existing users have an explicit manual sync/rebuild path | `tests/main/test_artifact_cli_maintenance_commands.py`; `tests/main/test_artifact_cli_parser.py`; `docs/artifacts.md`; `src/sase/xprompts/skills/sase_artifact.md` | Parser/help/docs explicitly say `sync` is a historical backfill alias for `rebuild` and is not run on startup. |
| Directory invariant: only `/` or directories containing non-directory artifacts | Rust tests in `../sase-core/crates/sase_core/src/artifact/ingest.rs`; Python real-extension smoke in `tests/test_core_facade/test_artifact_real_extension.py` | Phase 6.3 should run the Rust artifact tests and make this coverage easy to find from Python/CLI test names. |
| Canonical file type taxonomy: `plan`, `diff`, `chat`, `project`, `prompt`, `misc` | Rust wire/ingest tests; `tests/test_core_facade/test_artifact_wire.py`; `tests/test_core_facade/test_artifact_real_extension.py`; CLI parser/read tests | Python constants mirror the Rust contract and CLI filters parse `-F/--file-type`. |
| Paged one-line relationship navigator rows | `tests/ace/tui/modals/test_artifact_panel_rows.py`; `tests/ace/tui/modals/test_artifact_panel_paging_search.py` | Product tests cover row model, per-group paging, and default paged load. |
| Persistent header with current node and counts | `tests/ace/tui/modals/test_artifact_panel_modal.py` | `test_artifact_modal_renders_persistent_header_with_counts` covers the landed header shape. |
| `/` local filter is distinct from global `S` search | `tests/ace/tui/modals/test_artifact_panel_paging_search.py` | Local filter asserts no `artifact_search`; global search asserts bounded query and history-preserving navigation. |
| Apostrophe row navigation in the artifact panel | `tests/ace/tui/modals/test_artifact_panel_jump.py` | Covers relationship rows, show-more rows, search results, escape, and repeated apostrophe behavior. |
| CL/Agent artifact indicators without hot-path summary queries | `tests/ace/tui/models/test_artifact_indicator.py`; `tests/ace/tui/actions/test_artifact_summary_loading.py`; `tests/ace/tui/test_agent_artifact_indicators.py`; `tests/ace/tui/widgets/test_changespec_list_grouped.py`; `tests/ace/tui/widgets/test_agent_display.py`; `tests/ace/tui/widgets/test_agent_render_cache.py` | Coverage checks shared renderer semantics, batched loading, startup skip, highlight refresh skip, and render-cache invalidation. |

## Stale Or Missing Coverage

Phase 6.2 should own these benchmark gaps:

- `tests/perf/artifact_graph/modal_measurements.py` still constructs `ArtifactPanelModal(..., show_func=graph.show)` as
  the benchmark's primary modal-open path. This exercises the legacy compatibility adapter instead of the default
  `artifact_show_paged` path.
- `tests/ace/tui/modals/test_artifact_panel_modal.py` still has large-graph smoke tests using `show_func` at
  `test_large_graph_open_smoke_documents_latency_and_query_counts` and
  `test_row_navigation_does_not_requery_and_open_selected_queries_once`. Those can remain as compatibility tests, but
  they should not be the primary performance signal.
- The current perf harness covers the startup no-broad-call sentinel, full rebuild, targeted upserts, high-degree
  `artifact_show_paged`, bounded search, and batched summary. It does not yet measure startup with a missing unified
  artifact index or modal open on a missing artifact that performs one targeted refresh.

Phase 6.3 should own these backend/facade/CLI audit items:

- Run and, if needed, tighten Rust coverage in `../sase-core/crates/sase_core/src/artifact/` for file type taxonomy,
  directory invariant, orphan diagnostics, paged detail, search, and summary semantics.
- Run and, if needed, tighten PyO3 coverage in `../sase-core/crates/sase_core_py/src/lib.rs` for the same exposed
  bindings.
- Keep Python facade and CLI tests focused on wire conversion, binding availability, parser/help/JSON shape, `sync`,
  `rebuild`, and `-F/--file-type`.

Phase 6.4 should own these TUI audit items:

- Move primary hot-path modal regression checks to `show_paged_func` or the facade-backed default path, while preserving
  one explicit legacy `show_func` compatibility test.
- Keep monkeypatches around broad graph calls in startup, missing-state, and hot-navigation tests so accidental broad
  sync/rebuild regressions fail loudly.
- Verify CL and Agent indicator tests cover both list refresh and hot j/k navigation after any benchmark/test renames.

Phase 6.5 should own these docs and skill audit items:

- Keep `docs/artifacts.md`, `src/sase/xprompts/skills/sase_artifact.md`, and CLI help aligned on the manual sync/rebuild
  policy.
- The docs already state that `sync`/broad `rebuild` are explicit historical backfill paths. Later docs work should
  preserve that wording and add the final Epic 6 rollout results.

## Verification Notes

An initial `pytest --collect-only` against the focused artifact suites collected the non-Textual core/CLI tests, but
Textual/Rich-dependent suites failed to collect before `just install` because this workspace environment was not yet
installed. Follow-up implementation phases should run `just install` before their focused pytest commands and before
`just check`.
