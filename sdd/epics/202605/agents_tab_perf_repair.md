---
create_time: 2026-05-16 12:43:48
status: wip
prompt: sdd/prompts/202605/agents_tab_perf_repair.md
---
# Fix Agents Tab Performance And Correctness

## Context

Recent work under bead `sase-3r` moved the Agents tab toward a SQLite-backed artifact index, but the live behavior still
has two serious problems:

- Normal `agents.load_from_disk` refreshes are still slow. The current trace in `~/.sase/perf/tui_trace.jsonl` shows
  `agents.load_from_disk` dominating runtime: 81 calls, about 146 seconds total, max about 3.4 seconds, and repeated
  Tier 1 index loads around 1.5-2.1 seconds.
- The Agents tab projection is incomplete. Real `sase-3r` artifact directories exist and are not dismissed, but they are
  absent from `~/.sase/agent_artifact_index.sqlite`, so they cannot appear through the new Tier 1 path. The current `l`
  fold behavior also needs explicit parent/child contract tests, because child prompt-step rows are only useful if the
  loader, sorter, fold state, and rendered list all agree on the same unfiltered tree.

Useful proof commands from the investigation:

```bash
jq -r 'select(.span != null) | [.span, (.duration_ms // 0)] | @tsv' ~/.sase/perf/tui_trace.jsonl \
  | awk '{c[$1]++; s[$1]+=$2; if($2>m[$1]) m[$1]=$2} END {for (k in c) printf "%8.1f %8.1f %6d %s\n", s[k], m[k], c[k], k}' \
  | sort -nr | head -30
```

This showed `agents.load_from_disk` at `146110.7ms` total and `3442.2ms` max, with `agents.async_refresh` close behind.

```bash
jq -r 'select(.span=="agents.load_from_disk") | [.duration_ms, .tier, .complete_history, .artifact_source, .used_artifact_index, .snapshot_records, .loaded_agent_count, .loaded_workflow_step_count, .artifact_dirs_visited, .marker_files_parsed, .prompt_step_markers_parsed] | @tsv' \
  ~/.sase/perf/tui_trace.jsonl | tail -30
```

This showed every recent load as Tier 1/index-backed, but still reading about `9178` snapshot records and `6980`
workflow step markers per refresh.

Because `sqlite3` is not installed locally, Python's stdlib `sqlite3` module was used read-only to inspect the index.
The live index currently has about `11395` artifact rows, `23097` dismissed sidecar rows, and the current inbox SQL
matches about `9178` rows. The largest offender is the active/incomplete branch, which matches about `7040` rows because
it treats `has_done_marker = 0` as active even for old sparse artifacts.

The `sase-3r` phase artifacts exist on disk:

```bash
find ~/.sase/projects -type f \( -name 'agent_meta.json' -o -name 'done.json' -o -name 'workflow_state.json' -o -name 'prompt_step_*.json' \) -print0 \
  | xargs -0 rg -l 'sase-3r' | head -100
```

But the index has no rows for the key phase timestamps `20260516095501`, `20260516095502`, `20260516095503`,
`20260516095504`, `20260516095505`, `20260516095520`, or `20260516095525`, and `~/.sase/dismissed_agents.json` has no
matching `sase-3r` dismissed entries. Those agents are missing because the fast path is stale, not because the user
dismissed them.

## Goal

Make ordinary `sase ace` Agents-tab refreshes fast and correct:

- Normal refresh p95 under 50ms and max under 150ms on the user's large real history, excluding explicit repair,
  rebuild, archive, and revive paths.
- The Agents tab shows every non-dismissed row it should show, including the `sase-3r` epic and phase agents.
- Pressing `l` on expandable workflow/agent rows reveals the expected child rows.
- The index is kept fresh enough that normal startup and refresh do not depend on full source-tree scans, while repair
  paths can still reconcile from source of truth.

## Phase 1 - Reproduce, Contract, And Trace Harness

Owner: one distinct agent instance.

Purpose: lock the failures down before changing behavior.

Deliverables:

- Add a targeted diagnostic command or test helper that compares source artifact timestamps against index timestamps for
  a selected name/pattern, initially proving the `sase-3r` artifact rows are missing from the index.
- Add a loader contract test with a fixture that has:
  - completed non-dismissed phase agents,
  - prompt-step child rows,
  - stale sparse no-`done.json` artifacts,
  - dismissed completed rows.
- Assert the normal Tier 1 query includes the non-dismissed phase agents, includes valid children, excludes dismissed
  completed rows, and excludes stale sparse history.
- Tighten trace fields so each normal refresh records enough to distinguish:
  - index query time,
  - JSON record decode/hydration time,
  - Python model conversion/sort/fold time,
  - source/index row counts,
  - final visible parent and child counts.
- Add a small repeatable perf assertion that fails if a normal index-backed refresh loads thousands of historical rows
  for a fixture with a small visible inbox.

Verification:

- Targeted pytest for the new contract tests.
- Existing `tests/ace/tui/actions/test_agent_loader_phase*_*.py` suites.
- No product behavior changes in this phase except trace/diagnostic additions.

## Phase 2 - Correct The Rust Index Inbox Predicate

Owner: one distinct agent instance, primarily `../sase-core`.

Purpose: stop the fast path from returning thousands of stale historical rows.

Deliverables:

- Replace the current broad active predicate:
  - `has_done_marker = 0 OR workflow_status NOT IN (...)` with a stricter "currently actionable" predicate based on
    explicit active signals:
  - `running.json`,
  - `waiting.json`,
  - pending question markers,
  - workflow state in an active/waiting status,
  - any other explicit lifecycle marker already understood by the scanner.
- Do not classify old sparse rows as active merely because they lack `done.json`.
- Keep completed non-dismissed rows visible, but define a bounded or generation-aware strategy if the user has a very
  large number of non-dismissed completions. If all non-dismissed completions must remain visible, the query still needs
  to avoid hydrating unrelated prompt-step-heavy records that are not top-level rows.
- Fix dismissed matching to use the full available identity, not only `cl_name`, so unrelated agents sharing a
  CL/project name cannot hide each other.
- Add Rust tests for:
  - stale no-marker/no-`done.json` rows are not active,
  - running/waiting/pending/workflow-active rows stay visible,
  - completed non-dismissed phase rows stay visible,
  - dismissed filtering does not cross-contaminate by `cl_name`,
  - prompt-step children are returned only for visible parents or via a dedicated child query.
- Update Python wire records if the query needs a new mode such as `include_children_for_visible_parents`.

Verification:

- Rust unit tests and parity tests in `../sase-core`.
- Python facade/wire tests in this repo.

## Phase 3 - Make Index Freshness Authoritative

Owner: one distinct agent instance, cross-cutting Python plus Rust facade.

Purpose: ensure real artifacts like `sase-3r.1` through `.6` reach the index before the TUI trusts it.

Deliverables:

- Add an index verification/reconcile path that detects missing source artifact rows without requiring every normal
  refresh to source-scan.
- Repair startup behavior:
  - if the index exists but is stale, schedule rebuild/repair and preserve cached UI rows until repair completes,
  - if a selected source artifact is missing from the index, upsert that row or trigger a targeted rebuild,
  - after repair, refresh the Agents tab projection.
- Ensure lifecycle writes update the index reliably for all runtimes uniformly:
  - agent launch/start,
  - prompt-step marker creation,
  - workflow state updates,
  - done marker creation,
  - dismiss,
  - revive,
  - artifact deletion.
- Add targeted upsert calls around the artifact-writing paths instead of relying only on later full rebuilds.
- Make dismissed sidecar synchronization versioned/signature-gated but not destructive when the legacy file read fails.
- Add a one-shot user-facing diagnostic or trace event when the TUI had to repair a stale index.

Verification:

- Tests with a temp projects root where source has rows absent from the index; normal refresh schedules repair and the
  next refresh sees them.
- Tests for each lifecycle mutation calling the index maintenance adapter.
- Manual read-only check against the user's real `sase-3r` timestamps before and after repair.

## Phase 4 - Preserve Parent/Child Projection Through The TUI

Owner: one distinct agent instance, Python/TUI.

Purpose: fix the `l` key behavior and prevent future data-loss regressions at the apply/fold/render boundary.

Deliverables:

- Define the Agents tab projection contract explicitly:
  - `_agents_with_children` is the unfiltered tree payload,
  - `_agents` is the current fold/search/group-visible projection,
  - every expandable parent has child rows addressable by raw suffix/parent timestamp,
  - `l` and `h` operate on the same parent keys used by the sorter and renderer.
- Add tests around `sort_and_reorder`, `filter_agents_by_fold_state`, and `_apply_loaded_agents_prepared` proving:
  - a workflow parent keeps its prompt-step children after index-backed loading,
  - collapsed state hides children,
  - `l` reveals children,
  - search/grouping does not permanently drop children from `_agents_with_children`,
  - incomplete or stale loads cannot overwrite a richer parent/child projection.
- Audit `dedup_workflow_entries`, `dedup_running_vs_workflow`, and `dedup_by_pid` for accidental removal of phase agents
  or workflow children that share `cl_name="sase"`.
- Ensure current hidden-row and axe-spawned behavior stays unchanged for intentionally hidden rows.

Verification:

- Existing fold/filter/render tests plus new regression tests for a `sase-3r`-shaped fixture.
- A Textual `AcePage` test that starts on the Agents tab, focuses a parent row, presses `l`, and asserts child rows are
  rendered.

## Phase 5 - Reduce Hydration And Render Cost

Owner: one distinct agent instance, Python/TUI with possible Rust query support.

Purpose: after correctness is restored, make the hot path cheaply hydrate only what the list actually needs.

Deliverables:

- Split top-level row query from child/detail hydration if Phase 2 still returns too much JSON.
- Load child prompt-step rows lazily or parent-scoped when expanding with `l`, unless the existing UI requires child
  counts up front. If counts are needed, store cheap child summaries in the index and defer full prompt-step payloads.
- Keep selected-row details lazy:
  - attempt history,
  - large prompt/reply content,
  - file/tool panels,
  - archive content search.
- Ensure normal Agents-tab search filters the current inbox projection and does not trigger archive/full-history scans.
- Add trace thresholds for JSON decode count, prompt-step hydration count, and list render time.

Verification:

- Perf fixture with thousands of stale/history artifacts and a small visible inbox.
- Tests proving normal refresh does not read attempt directories, prompt/reply content, or full child payloads unless
  selected/expanded/search mode requires them.

## Phase 6 - Real E2E Validation With `sase ace`

Owner: one distinct agent instance.

Purpose: prove the fix in the real app, not only through unit tests.

Deliverables:

- Run `just install` first in this workspace, then run focused and broad tests.
- Launch a real `sase ace` process from this checkout under a PTY, with trace enabled, for example:

```bash
SASE_TUI_TRACE=1 SASE_TUI_PERF=1 sase ace --initial-tab agents
```

- Drive the running TUI with real keypresses:
  - wait for startup load,
  - verify the Agents tab is populated,
  - search or navigate to `sase-3r`,
  - verify `sase-3r` and `sase-3r.1` through `sase-3r.6` are visible,
  - press `l` on expandable rows and verify child steps render,
  - press navigation keys repeatedly and confirm key-to-paint remains responsive.
- Capture and summarize fresh `~/.sase/perf/tui_trace.jsonl` evidence after the run:
  - `agents.load_from_disk` p50/p95/max,
  - loaded snapshot rows,
  - loaded top-level rows,
  - loaded/hydrated child rows,
  - render/fold/final display timings.
- Run an explicit index verification/repair command against the user's real `~/.sase` and confirm it no longer reports
  missing `sase-3r` timestamps.
- Document the expected operational behavior: normal refresh is index-only; repair/rebuild/archive/revive may scan
  source; stale index repairs are observable in traces.

Verification:

- `just check` in this repo.
- Appropriate Rust checks/tests in `../sase-core` for core changes.
- Manual E2E transcript or generated test artifact containing:
  - command used to start `sase ace`,
  - key sequence,
  - trace summary,
  - `sase-3r` visibility result,
  - child expansion result.

## Phase Ordering

1. Phase 1 must land first so later workers share a reproducible failure contract.
2. Phase 2 and Phase 3 are both required for the product fix: Phase 2 makes the index query small; Phase 3 makes the
   index trustworthy.
3. Phase 4 can begin after Phase 1 but should integrate after Phase 2/3 semantics are clear.
4. Phase 5 should wait until correctness is stable, because lazy child/detail loading changes the projection shape.
5. Phase 6 is the final validation gate and should not be treated as optional.

## Non-Goals

- Do not modify memory files.
- Do not add runtime-specific branches for Claude/Gemini/Codex/Qwen/OpenCode.
- Do not reintroduce normal-refresh full source scans as the steady-state fix.
- Do not rely only on mocked `AcePage` tests; the final validation must spin up real `sase ace`.
