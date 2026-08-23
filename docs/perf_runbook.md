# `sase ace` Performance Runbook

This runbook explains how to capture and compare performance data for ACE, the
`sase ace` terminal user interface. It started as the Phase 1 deliverable for the TUI
performance overhaul (bead `sase-w.1`, `sdd/epics/202604/tui_perf_overhaul_1.md`), and
later performance phases still rely on the tracing and benchmark harness described here.

## Suite test-cost gate

The repository-wide pytest cost harness is separate from ACE trace spans. Use it when a
change may affect the whole test suite's cost model rather than one TUI interaction:

```bash
just test-cost
```

The lane runs the default fast suite, records per-file wall/CPU time, collection time,
the worker RSS curve, and attributed hot causes (now with a per-cause CPU-seconds
breakdown alongside wall seconds and count), then prints `tools/test_cost_report`.
Recordings live under `${SASE_HOME:-~/.sase}/test-selection/<project>/timings/cost/`;
set `SASE_TEST_COST_DIR` to redirect them. `tools/check_test_cost_budgets` compares the
newest recording with `tests/perf/baselines/test_cost_budgets.json`, and
`just check-full` plus the Python 3.13 CI test leg enforce that comparison.

### Severity model: hard vs. advisory

A single host regularly runs several agents' test suites at once, and Python's
`time.perf_counter()` wall-clock durations stretch under CPU contention that has nothing
to do with the suite's own cost -- a `causes.ace_page_enter` wall time can rise 17%
between a quiet host and a busy one for the exact same test run (same invocation count).
CPU seconds, invocation counts, and RSS do not move with contention, so the gate is
split by metric family instead of failing everything uniformly:

| family | metrics                                                                                    | default  | tolerance    |
| ------ | ------------------------------------------------------------------------------------------ | -------- | ------------ |
| wall   | `causes.<name>` (`limit`), `total_file_wall_seconds`, `idle_seconds`, `collection_seconds` | advisory | `ci`/`local` |
| cpu    | `causes.<name>.cpu` (`cpu_limit`), `total_file_cpu_seconds`, `collection_cpu_seconds`      | hard     | `cpu`        |
| count  | `causes.<name>.count` (`count_limit`)                                                      | hard     | none         |
| memory | `peak_worker_rss_kib`, `median_worker_rss_kib`, `post_collection_worker_rss_kib`           | hard     | `ci`/`local` |

**Advisory** failures are printed with full detail but never fail the gate and are
excluded from the exit code -- they are the "the host was probably busy" bucket.
**Hard** failures fail the gate; they are the contention-stable metrics, so an overage
there is a real signal. Any budget entry can override its dimension's family default
with an explicit `enforce` (for the wall `limit`), `cpu_enforce` (for `cpu_limit`), or
`count_enforce` (for `count_limit`) key set to `"hard"` or `"advisory"`. `--suggest`
always writes these explicitly so the committed file never silently depends on the
implicit default.

Count budgets are compared **without** the `cpu`/`ci`/`local` tolerance: a `count_limit`
already carries ~25% headroom over the worst observed invocation count
(`round_up_nice(max_observed_count * 1.25)`), because counts are near-deterministic --
the headroom belongs in the limit itself, not in a runtime tolerance. That policy trips
on a refactor that doubles a call site but tolerates a handful of newly added tests.

CPU attribution note: `CostRecorder.measure()` times `time.process_time()`, which is
process-wide, so CPU burned by other coroutines on the same event loop during an awaited
span is attributed to that span. This matches how wall time already behaves, and within
one xdist worker tests run sequentially, so the attribution stays meaningful.
Sleep-dominated causes such as `pilot_pause_delay` report near-zero CPU seconds -- that
is correct, and is exactly why the count dimension matters for them.

Run the gate with `--strict` to make advisories fatal too, for deliberate investigation
on a quiet host:

```bash
tools/check_test_cost_budgets --strict
```

`just test-cost` runs the fast suite and then `tools/check_test_cost_budgets`
(non-strict, so a wall-only advisory no longer breaks the lane). Inside
`just check-full`, `tools/run_silent` discards a wrapped command's captured output on
success, which would otherwise hide a printed advisory; `check-full` follows the wrapped
`just test-cost` line with an unwrapped
`tools/check_test_cost_budgets --report-advisories`, which re-reads the recording
`test-cost` just wrote and always exits `0`, so advisories still reach the operator.

Budget entries are either per-worker or suite-wide totals, and mixing the two up
silently defeats the gate:

- `collection_seconds` and `collection_cpu_seconds` are **per-worker** limits: every
  xdist worker collects the whole suite, so `build_cost_record()` sums the metric across
  workers before a budget entry marked `"per_worker": true` divides it back down by the
  record's worker count (falling back to the number of worker payloads that reported
  collection time, then to 1) before comparing against the limit.
- Every other summary entry (`total_file_wall_seconds`, `total_file_cpu_seconds`,
  `idle_seconds`, `peak_worker_rss_kib`, `median_worker_rss_kib`, and
  `post_collection_worker_rss_kib`) and every `causes.*` entry is a **suite-wide**
  metric, not normalized by worker count.
- Each worker records `start`, `post_collection`, `median`, and `peak` RSS summaries.
  The suite-level `worker_rss_curve_kib` takes the maximum worker value for `start`,
  `post_collection`, and `peak`; its `median` is the median of every positive worker
  summary value across those four fields, and its `sample_count` is the sum of worker
  sample counts. It is an aggregate summary, not one process's time series.
- `peak_worker_rss_kib`, `median_worker_rss_kib`, and `post_collection_worker_rss_kib`
  are flat aliases for the corresponding suite-level curve fields. The report and budget
  suggestion tools do not divide these RSS values by worker count.

Read failures by bucket:

- `total_file_wall_seconds` and `idle_seconds` point to broad suite cost or waiting, but
  are advisory-only -- pair them with `total_file_cpu_seconds` (hard) to tell contention
  from a real regression.
- `collection_seconds`, `collection_cpu_seconds`, and post-collection RSS point to
  import-time state. Median and peak RSS summarize later retained or run-time growth,
  but the suite median is over worker summary fields rather than raw time-series
  samples.
- Cause entries such as `textual_app_run_test_enter`, `ace_page_enter`, `parser_create`,
  `yaml_load`, and `subprocess_run` point to the hot pattern to audit; each reports up
  to three failures (`causes.<name>` wall/advisory, `causes.<name>.cpu` hard,
  `causes.<name>.count` hard).

For focused diagnosis, rerun the cost lane on a path or node and print more rows:

```bash
just test-cost -- tests/ace/tui/widgets/test_vim_normal_key_containment.py
tools/test_cost_report --top 20
```

The committed budgets intentionally have tolerance for host noise. Raise a limit with
this workflow, not a hand-picked number, and do not raise one to hide a one-off
regression:

```bash
just test-cost
tools/check_test_cost_budgets --suggest
```

`--suggest` reads the newest retained recordings (`--history N` to limit the sample),
derives each wall/cpu limit as `ceil(worst recorded value / (1 + tolerance))` (using the
`local`/`ci` tolerance for wall metrics and the `cpu` tolerance for CPU metrics) and
each `count_limit` as `ceil(max observed count * 1.25)` with no tolerance, rounds each
up to a round number, and prints a budget JSON -- with
`enforce`/`cpu_enforce`/`count_enforce` written explicitly on every entry -- along with
the `notes` provenance line (sample size, host, UTC date range, worker-count range,
node-count range, and per-metric min/median/max) to paste alongside the new limits.

`tools/check_test_cost_budgets --ci` defaults to
`os.environ.get("GITHUB_ACTIONS") == "true"`, not a bare `CI` variable: an agent runtime
that exports `CI=true` locally must not silently switch a local run onto the wider CI
tolerance. GitHub Actions always sets `GITHUB_ACTIONS`; nothing else does. Pass `--ci`
explicitly to force the CI tolerance on a non-GitHub-Actions host.

## Trace recorder

`SASE_TUI_TRACE=1` enables `tui_trace(...)` context managers spread across the Patch,
agents, and AXE hot paths. Each entered span emits one JSONL line to:

```text
~/.sase/perf/tui_trace.jsonl
```

Override the destination with `SASE_TUI_TRACE_PATH=/tmp/foo.jsonl`. When the env flag is
unset the context managers are near-zero-cost no-ops.

Each record contains at least:

```text
ts            unix epoch seconds
span          dotted span name (e.g. "agents.refresh_panel_widgets")
duration_ms   wall time inside the span
current_tab   "artifacts" | "agents" | "axe" | null
```

…plus any per-call counters (`count`, `agents`, `panels`, `output_bytes`, …) and any
global context fields seeded via `sase.ace.tui.util.trace.set_trace_context(...)` (the
app pushes `current_tab` and `current_idx` automatically).

Point-in-time records emitted by `trace_event(...)` contain `event` instead of
`span`/`duration_ms`. They are used for selection and highlight watcher transitions
where there is no timed block to measure.

Timed spans currently wired (by file):

- `actions/patch/_display.py` — `patch.refresh_display`, `patch.refresh_debounced`,
  `patch.refresh_detail_only`
- `actions/patch/_loading.py` — `patch.filter`
- `actions/agents/_display.py` — `agents.refresh_display`, `agents.refresh_debounced`
- `actions/agents/_display_panels.py` — `agents.refresh_panel_widgets`,
  `agents.refresh_panel_highlights`
- `actions/agents/_loading_helpers.py` — `agents.load_from_disk`
- `actions/agents/_loading_live_hints.py` — `agents.live_hint_refresh`
- `actions/agents/_display_detail_render.py` — `agents.view_hints_refresh`
- `actions/hints/_files.py` — `agents.view_files`, `agents.view_agent_files`,
  `agents.view_hint_bar_mount`
- `widgets/prompt_panel/_agent_display_hints.py` —
  `widget.prompt_panel.update_display_with_hints`
- `widgets/patch_list.py` — `widget.patch_list.update_list`,
  `widget.patch_list.update_highlight`, `widget.patch_list.patch_patch_row`
- `widgets/patch_detail.py` — `widget.patch_detail.update_display`
- `widgets/agent_list.py` — `widget.agent_list.update_list`,
  `widget.agent_list.update_highlight`, `widget.agent_list.patch_agent_row`,
  `widget.agent_list.try_remove_rows`
- `widgets/agent_detail.py` — `widget.agent_detail.update_display`,
  `widget.agent_detail.update_display_immediate`
- `widgets/artifacts/relation_panel.py` — `widget.relation_panel.update_relations`
- `widgets/prompt_panel/_agent_display.py` — `widget.prompt_panel.update_display`,
  `widget.prompt_panel.update_header_only`
- `widgets/prompt_panel/_agent_display_header_summary.py` —
  `widget.prompt_panel.build_detail_header_summary` and one child span per resolver (see
  "SASE CONTEXT enrichment" below)
- `widgets/file_panel/__init__.py` — `widget.file_panel.update_display`
- `widgets/thinking_panel.py` — `widget.thinking_panel.update_display`
- `widgets/axe_dashboard.py` — `widget.axe_dashboard.update_display`

Spans nest cleanly: a single keypress that fires `agents.refresh_debounced` will record
one outer span plus inner `widget.agent_list.update_highlight` and
`agents.refresh_panel_highlights` spans.

ACE deliberately keeps live-workspace pencil hints off the startup-critical agents
loader. The first load classifies only cheap persisted `diff_path` badges. After that
agents list has applied, `agents.live_hint_refresh` runs VCS probes for active,
non-terminal rows that do not yet have a persisted diff and patches changed rows in
place. During startup investigations, treat `agents.load_from_disk` and
`agents.live_hint_refresh` as separate costs: the former controls time to first
interactive Agents-tab paint, while the latter explains deferred pencil-badge updates.

### Reading a view-hints capture

Pressing `v` on the Agents tab nests four spans, outermost first:

```text
agents.view_files                              whole v keypath (both tabs)
└─ agents.view_agent_files                     Agents-tab branch only
   ├─ widget.prompt_panel.update_display_with_hints    the annotated render
   └─ agents.view_hint_bar_mount               mounting the HintInputBar
```

`agents.view_files` is the keypress → hint-bar-mounted interval: today the bar is
mounted last, so this span is effectively the render cost plus the mount cost.
Subtracting `agents.view_hint_bar_mount` from it gives the part of the wait the user
pays for work that is not the bar appearing.

`agents.view_hints_refresh` is the same annotated render fired again from an Agents-tab
detail repaint or from the detail-header enrichment message, rather than from a
keypress. Seeing it repeatedly with hint mode active is the signal that the document is
being rebuilt on refresh.

Useful counters:

```text
agents.view_files          tab
agents.view_agent_files    family_container, hints, commit_views,
                           header_enrichment_pending, outcome
                           (mounted | refocused | empty | no_agent |
                            detached_container)
agents.view_hints_refresh  family_container, hints, commit_views
update_display_with_hints  family_container, hints, commit_views,
                           tool_call_reports, annotated_chars,
                           header_summary (warm | cold)
```

`annotated_chars` counts every character handed to the hint scanner, summed across
fragments and family members, so it is the size term to divide a duration by.
`header_summary` says whether the render had a warm detail-header summary: a `cold`
render omits the SASE CONTEXT hints entirely and will be rebuilt when the enrichment
worker lands.

Slice one press out of a capture with:

```bash
jq -c 'select(.span | startswith("agents.view_") or . == "widget.prompt_panel.update_display_with_hints")
       | {span, duration_ms, hints, annotated_chars, header_summary, family_container, outcome}' \
   ~/.sase/perf/tui_trace.jsonl | tail -20
```

Trace events currently wired include:

- `selection.current_idx.set`
- `widget.patch_list.watch_highlighted` and `.suppressed`
- `widget.agent_list.watch_highlighted` and `.suppressed`
- `widget.bgcmd_list.watch_highlighted` and `.suppressed`

### SASE CONTEXT enrichment (detail-header summary)

`build_detail_header_summary` (`widgets/prompt_panel/_agent_display_header_summary.py`)
is the worker that resolves the `PLAN`, `BEAD`, `ARTIFACTS`, `MEMORY`, `SKILLS`, and
`WORKSPACES` lanes of the SASE CONTEXT section (bead `sase-l6.1`,
`plans/202608/sase_context_incremental.md`). It emits one parent span,
`widget.prompt_panel.build_detail_header_summary`, plus one child span per resolver, all
sharing that dotted prefix:

```text
widget.prompt_panel.build_detail_header_summary                 (parent)
  .xprompts_used
  .bead_display
  .plan_enrichment
  .slow_tool_sources
  .agent_page_url
  .linked_delta_groups
  .artifact_file_paths        the one resolver with no cache — usually the
                               most expensive lane before phase `stores` lands
  .artifact_reads
  .memory_reads
  .skill_uses
  .opened_workspaces
  .delta_entries
  .wait_bead_statuses
```

The parent span carries `agent` (the agent's `cl_name`) and `cache_state` (`"cold"` on
the first time this process has resolved that agent identity, `"warm"` after). This
marker is process-local and best-effort — it tracks whether _this worker_ has touched
the identity before, independent of and coarser than each resolver's own on-disk cache —
so it exists to make a raw capture readable without cross-referencing every resolver's
cache state.

Since phase `stream` (bead `sase-l6.4`), one selection's enrichment worker resolves its
requested lanes cheapest-first across `LANE_RESOLUTION_BATCHES`
(`_agent_display_header_summary.py`) and merges/publishes each batch as it lands, so a
single selection now emits **up to three**
`widget.prompt_panel.build_detail_header_summary` parent spans back to back — one per
non-empty batch — instead of one. All three share the same `agent`; only the first
carries `cache_state: "cold"` for a never-before-seen identity; the batches after it
reuse the same process-local seen-set and read `"warm"`. Group by `agent` and read the
spans in capture order to see which lane group landed first (typically the
free/cached-lookup batch) versus last (typically the store-backed
`ARTIFACTS`/`MEMORY`/`SKILLS` batch, before phase `stores`'s caches are warm).

Slice one selection's enrichment out of a capture with:

```bash
jq -c 'select(.span | startswith("widget.prompt_panel.build_detail_header_summary"))
       | {span, duration_ms, agent, cache_state}' \
   ~/.sase/perf/tui_trace.jsonl | tail -20
```

Reproduce the baseline table (per-resolver cold/warm cost, plus where
`artifact_file_paths` spends its time inside `list_artifact_files`) with the committed
benchmark, which drives the exact same spans read above rather than re-timing the
resolvers by hand:

```bash
pytest -s -m slow tests/perf/bench_detail_header_summary.py

python -m tests.perf.bench_detail_header_summary --include-home \
    --count 20 --output ~/.sase/perf/detail_header_summary_baseline.json
```

`--include-home` is required to measure real `~/.sase` agents; without it the script
only exercises a tiny hermetic in-memory fixture, so it stays safe to run in CI.
`--count` controls how many non-clan agents from
`load_tiered_agents(full_history=False)` are sampled.

## Quick capture

```bash
SASE_TUI_TRACE=1 sase ace
# … exercise the path you care about (cold start, query change, j/k burst,
#   auto-refresh, large reply select) …
# Quit with q.

# Inspect:
jq -c 'select(.span | startswith("widget.agent_list."))' \
   ~/.sase/perf/tui_trace.jsonl | head -20
```

To inspect point events instead of timed spans:

```bash
jq -c 'select(.event)' ~/.sase/perf/tui_trace.jsonl | head -20
```

For key-to-paint timing during j/k navigation, also enable the separate perf recorder:

```bash
SASE_TUI_TRACE=1 SASE_TUI_PERF=1 sase ace
jq -c . ~/.sase/perf/tui_jk.jsonl | head -20
```

Override the key-to-paint path with `SASE_TUI_PERF_PATH=/tmp/tui_jk.jsonl`.

Agents that launch the TUI via `sase ace --tmux` get `SASE_TUI_TRACE=1` and
`SASE_TUI_PERF=1` injected automatically; export the variable to `0` before invoking to
opt out.

## Freeze and hitch capture

ACE's always-on watchdog writes event-loop and Textual message-pump diagnostics to
`~/.sase/logs/tui_stalls.jsonl`. There are two independent severity tiers:

- `tui_hitch` / `tui_pump_hitch` fire after 1.5 seconds by default. These are compact
  records containing the current tab and selection, the last action, keypress age, and
  the main-thread stack. Recovery rows use the corresponding `*_recovered` event and
  include the episode duration. Hitch records deliberately omit full asyncio-task and
  worker thread dumps, and are rate-limited; `suppressed_count` reports episodes omitted
  since the previous admitted record.
- `tui_stall` / `tui_pump_stall` retain the existing 5-second threshold and richer
  task/thread diagnostics. A long freeze can produce both a hitch and a stall because
  the two state machines are independent.

Lower both tiers for a short verification soak with:

```bash
SASE_TUI_HITCH_THRESHOLD_SECONDS=0.25 \
SASE_TUI_PUMP_HITCH_THRESHOLD_SECONDS=0.25 \
SASE_TUI_STALL_THRESHOLD_SECONDS=0.75 \
SASE_TUI_PUMP_STALL_THRESHOLD_SECONDS=0.75 \
SASE_TUI_STALL_POLL_INTERVAL=0.02 \
SASE_TUI_PUMP_STALL_POLL_INTERVAL=0.02 \
SASE_TUI_STALL_PATH=/tmp/sase-tui-soak.jsonl \
sase ace
```

Exercise startup typing, launch and cleanup bursts, prompt-history and revive-agent
modal opens, tab switching during agent churn, and refreshes while the artifact or
dismissed-bundle indexes are contended. A fixed path should stay interactive and produce
no hitch/stall rows. Inspect any records in chronological order:

```bash
jq -c '{event, stall_seconds, duration_seconds, current_tab, current_idx,
        last_action, last_keypress_age_s, suppressed_count, main_thread_stack}' \
  /tmp/sase-tui-soak.jsonl
```

Read `main_thread_stack` from its final frame upward to find the blocking call. For a
pump-only event, the loop may still be running while one Textual message pump is
awaiting slow work; a loop event means the event loop itself stopped servicing the
watchdog beacon. Disable the compact tiers independently with `SASE_TUI_HITCH_DISABLE=1`
and `SASE_TUI_PUMP_HITCH_DISABLE=1`; the existing stall-tier disable flags remain
`SASE_TUI_STALL_DISABLE=1` and `SASE_TUI_PUMP_STALL_DISABLE=1`.

The persistent TUI diagnostic JSONL files under `~/.sase/logs/`—stall, git-operation,
launch-timing, external-tool, agent-load, and startup records—rotate independently
before appending a record would make a non-empty file exceed 2 MiB. Each keeps one `.1`
generation. Set `SASE_TUI_TELEMETRY_MAX_BYTES` to another per-file byte limit, or `0`
for no size rotation. This bound is separate from the opt-in trace files under
`~/.sase/perf/`.

## Startup telemetry capture

`~/.sase/logs/tui_startup.jsonl` (`sase/logs/tui_telemetry.py:log_tui_startup`) gets one
durable record per ACE session, written after both the Agents and AXE surfaces finish
their first load — the same point the visible startup-stopwatch badge stops. It exists
so every "startup dropped from X to Y" claim in this repo's plans and epics is checkable
against a real terminal run instead of a modelled component sum
(`plans/202608/ace_startup_critical_path.md`).

Each record carries two headline metrics, both measured from the App's `on_mount` — the
same anchor the visible stopwatch badge uses, so the two numbers should visually track
what you saw on screen:

- `all_surfaces_ready_seconds` — elapsed time until **both** the Agents and AXE tabs'
  first load finished, regardless of which tab was visible. This is today's stopwatch
  semantics.
- `visible_ready_seconds` — elapsed time until the **initially visible** tab's own
  surface was interactive. Recorded from day one even though nothing currently drives
  the stopwatch off of it, so a later change to end the stopwatch on the visible surface
  instead of both surfaces has an honest before/after rather than a redefinition that
  silently invalidates every prior capture.

The record also carries `process_start_to_on_mount_seconds` and
`on_mount_to_first_paint_seconds` (the two stages before either surface starts loading),
`agents_ready_seconds` / `axe_ready_seconds` (each surface's own elapsed time from
process start), `initial_tab`, `agent_row_count`, `index_row_count` (the Tier-1 index
query's row count when the load went through the persistent index, `null` otherwise),
and `source` / `tier` / `artifact_source` from the load's `AgentLoadState`.

To capture a before/after pair:

```bash
# baseline, before your change
git stash  # or check out the prior commit in a second workspace
sase ace   # quit once the tabs finish loading; repeat 3x for a stable read
git stash pop

# after your change
sase ace   # quit once the tabs finish loading; repeat 3x
```

Then compare the two sets of records:

```bash
jq -c '{timestamp, all_surfaces_ready_seconds, visible_ready_seconds,
        agents_ready_seconds, axe_ready_seconds, agent_row_count,
        index_row_count, source, tier, artifact_source}' \
  ~/.sase/logs/tui_startup.jsonl
```

`tui_agent_loads.jsonl`'s slow-stage records are censored below
`_SLOW_LOADER_STAGE_THRESHOLD_SECONDS` (2.0 s by default in
`src/sase/ace/tui/actions/agents/_loading_disk_support.py`); a capture run against a
tree that has already dropped under 2 s needs the sub-threshold stages too. Override the
threshold for the run instead of editing the constant:

```bash
SASE_TUI_LOADER_LOG_THRESHOLD_SECONDS=0.05 sase ace
```

## Synthetic-data benchmark harness

The harness lives at `tests/perf/bench_tui_trace.py`. It generates in-memory Patch and
agent fixtures, then drives the TUI through Textual Pilot without touching real
`~/.sase` data. It is marked `pytest.mark.slow`, so it does not run as part of
`just test`.

For the Updates > Plugins catalog-scale path, use the focused benches and the committed
measuring-stick baseline:

```bash
just bench-plugin-catalog-scale
```

That records p50/p95/max at 10 / 250 / 1000 / 2000 entries for pane open, one filter
keystroke, 20 j presses (through the queued `OptionHighlighted` handler), `'` jump-hint
allocation, and one `I` mark toggle, plus non-TUI enrich/fetch cost curves. The
committed numbers live in `tests/perf/baselines/plugin_catalog_scale_baseline.json`.
Filter-keystroke and j-press p95 must stay under 16 ms at n=2000; eager enrich fetches
must stay O(installed) and enrich's `scan_work` (catalog rows walked, counted through
`CountingEntries`) must stay linear in `n`. Rewrite the recorded rows after a capture
run with `python -m tests.perf.bench_plugin_catalog_scale --write-baseline` and
`SASE_PLUGIN_CATALOG_SCALE_WRITE_BASELINE=1 pytest -s -m slow tests/ace/tui/bench_plugins_catalog_scale.py`.
`just plugin-catalog-scale-check` is the CI regression floor.

For the Admin Center home-first path, use the focused Textual Pilot benchmark:

```bash
pytest -s -m slow tests/ace/tui/bench_admin_center_open.py
```

It reports `#` dispatch-to-paint p50/p95/max values for empty and populated
project/config stores. Treat zero mounted concrete panes and comparable results across
fixture sizes as the hard acceptance criteria; use the timing table for before/after
comparison rather than adding a unit-test wall-clock threshold.

Run via pytest:

```bash
pytest -s -m slow tests/perf/bench_tui_trace.py
```

Or as a script (writes a baseline numbers file the next phase can diff):

```bash
python -m tests.perf.bench_tui_trace --output ~/.sase/perf/tui_perf_baseline.json
```

The script also accepts explicit trace and key-to-paint output paths:

```bash
python -m tests.perf.bench_tui_trace \
  --output ~/.sase/perf/tui_perf_baseline.json \
  --trace-path ~/.sase/perf/tui_trace.jsonl \
  --perf-path ~/.sase/perf/tui_jk.jsonl
```

Fixture sizes:

```text
Patches: 100,  500, 2000   (tests/perf/fixtures.py: legacy-named CHANGESPEC_SIZES)
Agents:       50,  200, 1000   (tests/perf/fixtures.py: AGENT_SIZES)
Large reply:   1,    5,   20 MB (LARGE_REPLY_SIZES_MB)
```

Scenarios per fixture size:

- cold start
- query change
- repeated query edits
- 50-key j/k burst
- auto-refresh with no changes
- large-reply select

The per-scenario summary records wall-clock times, then aggregates p50 / p95 / max for
every trace span and key-to-paint action observed during that scenario.

### View-hints scenarios and committed baseline

The Agents-tab `v` keypath has its own scenario set, run separately because it needs
disk-backed fixtures — the hint render reads `raw_xprompt.md`, `*_prompt.md`, and
`live_reply.md` from a real artifacts dir:

```text
large_reply_first_press           v on a plain agent with a 100 KB reply, cold header summary
large_reply_repeat_press          v again on the same row after the bar is torn down
family_container_press            v on a 5-member family container at the default metadata level;
                                  conversation content is full under the shared hint cap
family_container_unfolded_press   the same row at FoldLevel.FULLY_EXPANDED; foldable metadata grows,
                                  while conversation visibility and the shared hint cap stay unchanged
hint_mode_auto_refresh            an Agents-tab refresh tick while hint mode is active
```

Spans are sliced per step rather than pooled, so the plain-agent and family-container
costs can be compared independently. Each step also carries a `hint_counters` block
(`annotated_chars`, `hints`, `commit_views`, `header_summary`, `family_container`) so a
duration change can be attributed to the document actually getting smaller rather than
to a quieter machine.

Run just these scenarios and print the table:

```bash
pytest -s -m slow tests/perf/bench_tui_trace.py::test_view_hints_scenario
```

Regenerate the committed baseline (5 runs, median per step and span, plus every raw
run):

```bash
python -m tests.perf.bench_tui_trace --view-hints-baseline
# writes tests/perf/baselines/view_hints_baseline.json
```

Compare against `tests/perf/baselines/view_hints_baseline.json` rather than a transient
capture. Two caveats when reading it:

- `wall_ms` measures key dispatch through Pilot settle, so it carries unrelated repaint
  work and is much larger and much noisier than the spans. Compare the per-step `spans`
  table, not `wall_ms`.
- An `agents.view_hints_refresh` span can appear inside a press step: a detail repaint
  often lands inside that step's settle window. That is real behavior, not bookkeeping
  noise.

Run the regression floor after changing this path:

```bash
just view-hints-perf-check
```

The floor compares traced spans against the committed baseline and ignores wall-clock
Pilot settle time. It also checks that warm repeat presses and unchanged auto-refreshes
do not rescan annotated text, and that family rows stay within the shared hint scan cap
at both metadata levels. If long output is capped, ACE shows a dim notice in the detail
panel; hints are not generated past that notice. The committed baseline remains the
synchronous pre-optimization reference and is not rewritten merely because conversation
sections became fold-inert.

## Targets per phase gate

The targets below come from `sdd/research/202604/sase_perf_research.md` and are restated
here so each phase agent has a single page to check against. A phase is green when the
relevant targets are met **without regressing** any other span.

```text
j/k highlight p95             < 16 ms
  (Stitches next/prev/up10: documented CommitsTimeline carve-out ≤ 25 ms;
  unmodified-master baseline was stitches.next 16.47 / stitches.up10 17.95,
  conform verification observed stitches.next 20.17 serial / 24.84 under xdist)
key-to-paint p95              < 33 ms
debounced detail paint        < 150–250 ms
warm Patch reload, 1k    < 100 ms
no-change auto-refresh stall  ~0 ms (event-driven path; Phase 7)
large reply first paint       immediate plain render, syntax later/optional
```

Per-phase responsibilities:

- **Phase 2** (Patch j/k hot path): `widget.patch_list.update_list` call count drops to
  zero for j/k navigation; `update_highlight` p95 < 16 ms at 500 patches.
- **Phase 3** (data layer): warm Patch reload < 100 ms at 1k specs; `patch.filter` p95
  should drop materially after the snapshot cache and query context land.
- **Phase 4** (agent panel + list): `agents.refresh_panel_highlights` and
  `widget.agent_list.update_highlight` p95 < 16 ms at 1k agents.
- **Phase 5** (incremental loader): `agents.load_from_disk` near zero on a no-change
  auto-refresh.
- **Phase 6** (artifact + render caching): `widget.prompt_panel.update_display` /
  `widget.file_panel.update_display` immediate first paint on the largest reply fixture.
- **Phase 7** (event-driven auto-refresh): no-change auto-refresh shows no agents/patch
  spans firing at all.

## Adding a new span

```python
from sase.ace.tui.util.trace import tui_trace

with tui_trace("module.name", count=len(items)):
    ...
```

Names use dotted lowercase. Counters should be ints / strs only — the emitter falls back
to `str(...)` for unknown types via `default=str`, but keeping payloads JSON-friendly
speeds downstream `jq` slicing.

When a span boundary forces a refactor (most existing hot paths split into `foo()` →
`_foo_impl()` so the wrapping context manager doesn't fight indentation rules), keep
both methods next to each other and let the public name stay the trace span name.

## Reading the Admin Center Perf view

Perf is the eighth view in the ACE Admin Center's **Statistics** tab. Open Admin Center
with `#`, press `5` for Statistics, then press `0` followed by `8`; `[` / `]` also cycle
to it. The selected Statistics range applies, and `g` groups latency by subsystem,
provider, or workflow. Perf is global rather than project-scoped: the project chip stays
visible but is marked **not applied** because the underlying telemetry and TUI logs do
not carry project attribution.

There is no CLI rendering of this dashboard. Use `sase telemetry status` for store and
configuration state or `sase telemetry health` for the related traffic-light health
assessment.

### What the view shows

Five headline tiles summarize **Startup**, **Stalls**, **Launch**, **Agent p95**, and
**LLM p95**. Startup, stalls, and launch timing come from bounded TUI diagnostic logs;
agent and LLM latency come from the local telemetry store. Each tile shows one number,
and they are deliberately not the same statistic:

| Tile          | Value                       | Detail line                             |
| ------------- | --------------------------- | --------------------------------------- |
| **Startup**   | median visible-ready time   | sessions in range · slowest initial tab |
| **Stalls**    | stall count                 | hitch count · worst freeze duration     |
| **Launch**    | p95 total launch time       | launches · slow stages                  |
| **Agent p95** | p95 agent-run duration      | agent runs                              |
| **LLM p95**   | p95 LLM invocation duration | error rate · retry rate                 |

The detailed body contains:

1. **Startup breakdown** — p50, p95, and maximum durations for process→mount,
   mount→first paint, visible ready, and all surfaces ready, plus the slowest session in
   the range. The Startup tile itself reports the _median visible-ready_ time and grades
   it OK below two seconds, warning from two to five seconds, and critical at five
   seconds or more.
2. **Stalls & hitches** — per-event counts, worst and median duration, recency,
   suppressed counts, a **Freeze records by context** ranking, and recoveries. The two
   tiers are independent watchdogs with different thresholds (hitch at 1.5 seconds,
   stall at 5, both configurable — see
   [Freeze and hitch capture](#freeze-and-hitch-capture)), so one freeze long enough to
   trip the stall threshold has already tripped the lower hitch threshold and is
   recorded as both. The two counts therefore overlap and must not be added together.
   The tile reports stalls only and names hitches separately in its detail line. Any
   hitch makes the tile warn; any stall makes it critical.
3. **Latency & reliability** — telemetry-backed p50, p95, maximum, a count, error rate,
   and retry rate. The count column is labeled by what it actually counts: **LLM
   invocations** under provider grouping, **Agent runs** under workflow grouping, and a
   plain **Count** under subsystem grouping. Provider grouping also shows input/output
   token and cache data, plus a note that provider rows without LLM invocation samples
   fall back to agent runs (which is why those rows read `—` for Err%/Retry%). Subsystem
   grouping omits the **Share** column entirely, because its rows measure different
   things and share no denominator; a subsystem with no counter renders `—` rather than
   `0`. The configured `telemetry.health_thresholds` grade every row in this panel as
   well as the Agent p95 and LLM p95 tiles, using the same rules as
   `sase telemetry health`.
4. **Data & instrumentation** — telemetry enablement, selected resolution, store size,
   raw/rollup counts, write freshness, and one coverage row per diagnostic log. Coverage
   reports file presence, records in the selected window, earliest retained record,
   truncation, and unreadable lines. A final line lists the optional probe flags; see
   [Deep profiling and probe flags](#deep-profiling-and-probe-flags) for how to read it.

The dashboard reads these files from `~/.sase/logs/` by default:

- `tui_startup.jsonl`
- `tui_stalls.jsonl`
- `tui_launch_timing.jsonl`
- `tui_agent_loads.jsonl`
- `tui_git_ops.jsonl`
- `tui_external_tools.jsonl`

Missing, disabled, truncated, or partially unreadable sources degrade independently, so
the rest of the view remains usable.

The two data sources compute percentiles differently, and the in-app `?` help names both
methods:

- **Log-derived numbers** (startup stages, launch timing, stall medians) use
  nearest-rank on the sorted sample, at index `round(q * (n - 1))` clamped to
  `[0, n - 1]`.
- **Telemetry-derived numbers** (the Latency & reliability rows and the Agent p95 / LLM
  p95 tiles) are estimated by linear interpolation between cumulative histogram bucket
  bounds. They are bucket estimates, not exact sample percentiles.

Perf counts come from the telemetry store and the TUI logs, never from the
agent-artifact index, so they are not comparable with the run counts on Overview,
Projects, or XPrompts.

Every range except **All time** also loads the immediately preceding window of the same
length; that second load is what the Startup and Agent p95 tiles compare against to show
a delta. The other three tiles never show one.

### Retention and rollups

The view's two data sources age out on entirely different rules:

- Each TUI JSONL diagnostic log is byte-bounded, not time-retained: nothing expires on a
  clock, but the oldest records fall off once the file grows. The default limit is 2 MiB
  per current file, and rotation preserves exactly one `.1` segment before discarding
  the previous one. Set `SASE_TUI_TELEMETRY_MAX_BYTES` to override the byte limit.
- The telemetry store is time-retained and rolled up: raw samples for 48 hours,
  five-minute rollups for 30 days, and hourly rollups for 365 days by default. These
  durations are configurable under `telemetry.retention`.

So a long lookback reads telemetry at the coarser rollup resolution, and reads only the
current plus rotated segment of each JSONL log. **All time** means everything still
retained under those two rules, not an unbounded history.

### Deep profiling and probe flags

Both probes are off by default and write to their own files under `~/.sase/perf/`, which
is a different directory from the `~/.sase/logs/` diagnostic logs the dashboard reads.
The dashboard only names these flags; it never parses what they produce.

- `SASE_TUI_PERF=1` records per-keystroke `j`/`k` key-to-paint samples in
  `~/.sase/perf/tui_jk.jsonl` by default. Override the path with `SASE_TUI_PERF_PATH`.
- `SASE_TUI_TRACE=1` records hot-path spans in `~/.sase/perf/tui_trace.jsonl` by
  default. Override the path with `SASE_TUI_TRACE_PATH`; see
  [Trace recorder](#trace-recorder).

Each probe records only when its variable is exactly `1`. The **Probes** line in **Data
& instrumentation** is looser: it prints `on` whenever the variable is _set_ in the
environment that started the TUI, so a deliberate `SASE_TUI_PERF=0` still displays as
`on` while nothing is being recorded. Read that line as "set / unset", and check the
value yourself when an expected probe file stays empty.

`sase ace --tmux` turns both probes on unless the caller has already set the variable,
so `SASE_TUI_TRACE=0 sase ace --tmux …` (or the `SASE_TUI_PERF=0` equivalent) opts out.
Use `just view-hints-perf-check` for the automated hint-mode regression floor.
