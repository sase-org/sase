---
plan: sdd/epics/202605/artifact_epic2_fast_indexing_query_contracts.md
status: completed
bead_id: sase-24.2.6
---

# Artifact Epic 2 Phase 2.6 Handoff

Phase 2.6 closes the backend contract work for the artifacts panel redesign with
an updated optional benchmark harness and explicit handoff notes for the Epic 3
modal and Epic 4 row-indicator agents.

## Benchmark Coverage

`tests/perf/bench_artifact_graph.py` now exercises the Epic 2 integration
surface through the existing `artifact-perf-smoke` target:

- startup contract sentinel: post-mount startup schedules agent and axe workers
  plus the watcher without calling `artifact_rebuild`, `artifact_list`,
  `artifact_search`, `artifact_show`, `artifact_show_paged`, or
  `artifact_summary`.
- targeted refresh burst: multiple marker writes inside one
  `artifacts/<workflow>/<timestamp>` directory dedupe to one bounded rebuild.
- paged high-degree detail: `artifact_show_paged(..., relation="children",
  limit=10)` on a 240-child node loads 10 rows while reporting the 240 total.
- global search: `artifact_search` is measured with an explicit limit so modal
  search can remain interactive.
- batched summaries: visible CL/agent-style IDs are measured through one
  `artifact_summary` call instead of per-row `artifact_show`.

The benchmark remains descriptive rather than a machine-sensitive latency gate.
The smoke assertions only enforce boundedness, no broad startup calls, and
absence of benchmark errors.

## Epic 3 Modal Contract

Use `artifact_show_paged(index_path, artifact_id, request)` for the relationship
navigator. The backend returns the current node, payloads, path-to-root,
diagnostics, child page, outbound pages, inbound pages, and type counts.

The modal should request per-group pages with the UI default of 10 rows:

- children: `ArtifactPageRequestWire(relation="children", offset=N, limit=10)`
- outbound group: `relation="outbound"` plus `link_type`
- inbound group: `relation="inbound"` plus `link_type`

Do not call legacy `artifact_show` and slice large relationship groups locally
for the redesigned navigator.

Use `artifact_search(index_path, ArtifactQueryWire(..., limit=...,
offset=...))` for modal-global search. Keep `/` as local filtering over the
loaded neighborhood rows; global search should query the index and navigate
through the same artifact-open path.

## Epic 4 Indicator Contract

Use `artifact_summary(index_path, ArtifactSummaryRequestWire(artifact_ids=...))`
once per visible CL or Agent list refresh. The returned summaries include total
linked artifacts, file type counts, non-file kind counts, and `missing` state.

Do not issue `artifact_show` per visible row. Cache the summary batch beside the
list render state and invalidate it when targeted graph refresh events run.

## Refresh And Startup Policy

Startup must remain free of broad unified graph reads or rebuilds. Normal
indexing happens through explicit actions, modal opens/searches, and changed
source paths from the watcher.

Targeted refresh classification is the invalidation source of truth:

- agent marker or created-file paths refresh the containing
  `artifacts/<workflow>/<timestamp>` directory with agent sources.
- `.gp` paths refresh project, ChangeSpec, and commit sources.
- `sdd/beads/issues.jsonl` refreshes the bead store.
- direct existing paths refresh directory-source rows only.

Historical backfill remains manual through `sase artifact sync` or
`sase artifact rebuild`; `sase ace` startup and modal open paths should not run
a broad historical sync.
