---
plan: sdd/epics/202605/artifacts_panel_epic6_rollout.md
status: completed
bead_id: sase-24.6.5
---

# Artifacts Panel Epic 6 Rollout

Epic 6 closes the artifacts panel redesign with documentation, checked-in performance evidence, and an operational
contract for users and future agents.

## What Shipped

Across Epics 1-6, the unified artifact graph is the default artifact discovery model for SASE:

- File artifacts keep `kind = "file"` and expose the semantic file taxonomy through `metadata.artifact_type`: `plan`,
  `diff`, `chat`, `project`, `prompt`, and `misc`.
- Directory artifacts are sparse: `/` is always present, and non-root directories exist only when they contain visible
  non-directory artifacts.
- `sase artifact sync` is the explicit historical backfill alias for `sase artifact rebuild`; neither command runs from
  `sase ace` startup or artifact-panel open.
- Newly-created artifacts are indexed through bounded targeted refresh paths when SASE observes changed project files,
  bead stores, agent artifact directories, created files, or direct directory targets.
- The artifact panel opens with paged detail, counted relationship groups, local `/` filtering, bounded `S` global
  search, apostrophe row jumping, history navigation, parent/root navigation, and bounded graph preview/export.
- CL and Agent artifact indicators are compact summaries loaded in one batch per visible-list refresh, not by querying
  per row or during hot `j`/`k` navigation.

## Benchmark Evidence

The Epic 6 benchmark command is:

```bash
.venv/bin/python tests/perf/bench_artifact_graph.py --runs 3 --output /tmp/artifacts-panel-epic6.json
```

The checked-in smoke target is:

```bash
just artifact-perf-smoke
```

Current local smoke evidence is stored at
`sdd/tales/202605/perf_artifacts/artifact_graph_perf_smoke.json`. The final Phase 6.6 run used `just
artifact-perf-smoke`, which expands to `--runs 1 --projects 2 --beads 10 --agents 10 --modal-linked 120`, and reported
no benchmark errors. Representative timings from that run:

| Operation | Latency ms | Calls/counts |
| --- | ---: | --- |
| `startup_contract:no_broad_artifact_graph_calls` | 0.28 | 0 broad graph calls |
| `startup_contract:missing_index_no_broad_artifact_graph_calls` | 0.06 | 0 broad graph calls |
| `full_graph_rebuild` | 114.36 | 97 nodes added, 482 nodes updated, 168 links added, 395 links updated |
| `targeted_agent_artifact_burst` | 12.67 | 1 targeted mutation call |
| `artifact_show_paged:high_degree_children` | 2.30 | 1 query, 10 rows returned |
| `artifact_search:global_limited` | 1.69 | 1 query, 12 rows returned |
| `artifact_summary:visible_rows_batch` | 1.28 | 1 query, 11 summaries |
| `modal_open:paged:/` | 175.30 | 1 `artifact_show_paged`, 0 `artifact_show`, 12 rows |
| `modal_open:paged:changespec:current` | 143.86 | 1 `artifact_show_paged`, 0 `artifact_show`, 38 rows |
| `modal_open:paged:agent:current` | 156.43 | 1 `artifact_show_paged`, 0 `artifact_show`, 15 rows |
| `modal_open:missing_artifact_targeted_refresh:changespec:current` | 183.55 | 2 paged queries, 1 targeted refresh |
| `modal_open_legacy_compat:/` | 145.25 | 1 legacy `artifact_show` compatibility query |

These numbers are descriptive local evidence, not a workstation-sensitive latency gate. The gate is boundedness: no
broad startup graph calls, one paged modal detail query per open, explicit limits on search and high-degree navigation,
one targeted refresh for the missing-artifact modal case, legacy all-detail behavior isolated to the compatibility
measurement, and no benchmark errors.

## Final Phase 6.6 Gate

Traceability from the Epic 6 acceptance criteria to final evidence:

| Acceptance criterion | Final evidence |
| --- | --- |
| `sase ace` startup does not run broad artifact graph rebuild/list/show/search/summary calls | Startup contract tests and benchmark rows `startup_contract:*` report 0 broad graph calls. |
| Newly-created artifacts use bounded targeted refresh | `tests/ace/tui/test_artifact_graph_refresh.py` and benchmark targeted upsert rows report one targeted mutation call per scenario. |
| Existing users have explicit manual sync/rebuild paths | CLI parser/docs tests, `docs/artifacts.md`, and `/sase_artifact` skill text document `sync`/`rebuild` as manual historical backfill. |
| Directory invariant and file type taxonomy remain stable | Rust artifact tests plus Python real-extension and wire tests cover sparse directories and `plan`, `diff`, `chat`, `project`, `prompt`, `misc`. |
| Artifact panel uses paged rows, counted groups, local filter, global search, and apostrophe navigation | Modal tests cover paged loading, local `/`, bounded `S`, show-more rows, persistent header, recoverable errors, and jump mode. |
| CL/Agent indicators avoid startup and hot-navigation summary queries | Indicator/action/widget tests cover shared rendering, batched summary loading, cache signatures, startup skip, and j/k navigation skip. |
| Benchmark harness measures the rollout scenarios without touching live indexes | `just artifact-perf-smoke` writes the checked-in smoke JSON from temporary indexes and deterministic fixtures. |

Phase 6.6 validation commands run from this workspace:

```bash
just install
.venv/bin/pytest -m slow tests/perf/bench_artifact_graph.py -q
.venv/bin/pytest tests/test_core_facade/test_artifact.py tests/test_core_facade/test_artifact_wire.py tests/test_core_facade/test_artifact_facade_bindings.py tests/test_core_facade/test_artifact_real_extension.py tests/main/test_artifact_cli_parser.py tests/main/test_artifact_cli_read_commands.py tests/main/test_artifact_cli_maintenance_commands.py tests/main/test_artifact_cli_real_extension.py tests/main/test_artifact_cli_real_extension_sync.py -q
.venv/bin/pytest tests/ace/tui/modals/test_artifact_panel_modal.py tests/ace/tui/modals/test_artifact_panel_paging_search.py tests/ace/tui/modals/test_artifact_panel_jump.py tests/ace/tui/modals/test_artifact_panel_renderers.py tests/ace/tui/modals/test_artifact_panel_rows.py tests/ace/tui/modals/test_artifact_panel_states.py tests/ace/tui/test_artifact_panel_launch.py tests/ace/tui/test_artifact_graph_refresh.py tests/ace/tui/test_agent_artifact_indicators.py tests/ace/tui/actions/test_agent_artifact_startup_contracts.py tests/ace/tui/actions/test_artifact_summary_loading.py tests/ace/tui/widgets/test_agent_display.py tests/ace/tui/widgets/test_changespec_list_grouped.py -q
just artifact-perf-smoke
just check
```

No sibling Rust files were changed during Phase 6.6. The residual operational risk is stale historical user indexes; the
mitigation remains the explicit manual `sync`, `rebuild`, and `doctor` workflow below.

## Operational Caveats

Existing users may have stale or incomplete historical indexes until they run an explicit sync or rebuild. `sase ace`
startup, modal open, missing-state rendering, global search, and CL/Agent indicator loading must not silently perform a
broad historical backfill.

The old `~/.sase/agent_artifact_index.sqlite` can remain for startup compatibility and legacy agent-list paths. Do not
delete it as part of unified graph migration.

When debugging, prefer a temporary index with `-i` and bounded `list`, `show`, `search`, or `graph` commands. Use the
default `~/.sase/artifacts.sqlite` only when intentionally operating on the user's live artifact graph.

## Rollback And Mitigation

For stale or missing historical rows:

```bash
sase artifact sync -j
sase artifact doctor -j
```

For a known changed source, prefer targeted repair:

```bash
sase artifact rebuild -j -t <project_or_file_path>
sase artifact rebuild -j -S bead_store -b <workspace>/sdd/beads
sase artifact sync -j -a <artifact_dir> -S agent_artifact -S agent_created_file
```

For suspected stale derived rows after source removal:

```bash
sase artifact rebuild -j -c mark
sase artifact doctor -j
```

If a regression is isolated to the TUI panel or indicators, users can still inspect the same graph with bounded
`sase artifact list`, `show`, `search`, `graph`, and `doctor` commands while the UI issue is fixed.
