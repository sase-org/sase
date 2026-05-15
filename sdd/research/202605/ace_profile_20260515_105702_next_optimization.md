# `sase ace` Profile 2026-05-15 10:57 - Next Optimization Decision

## Source

- Profile artifact: `~/tmp/sase/ace_profile_20260515_105702.txt`
- Recorded: 2026-05-15 10:52:46
- Duration: 255.502s wall, 125.687s CPU, 24,769 samples
- Root: `src/sase/main/ace_handler.py:74`
- Context: interactive `sase ace --profile` session after several earlier responsiveness fixes had landed.

## Revision Note

This document was rewritten on 2026-05-15 after a second pass over the same profile uncovered hot paths the first
version missed entirely. In particular the first version claimed prompt-panel rendering was "no longer a sampled
multi-second hot path"; that is wrong. There is a 21.660s Timer-driven layout/render subtree in this trace, of which
~10s is prompt-panel work and ~4.5s is the agent list. The revision below preserves the original 1.192s async refresh
finding but reranks it against the rendering chain and against per-keypress versus per-frame cost.

## How To Read the Numbers

pyinstrument totals roll up wall-clock time for each subtree across the full 255.502s capture. Two different kinds of
cost both show up as large totals:

- **Per-callback blocking cost.** A single synchronous callback runs for X seconds and blocks the event loop the whole
  time. Anything queued behind it — including `j`/`k` keypresses — waits. `_apply_loaded_agents_prepared` (1.192s in
  one continuation) is this kind.
- **Per-frame amortized cost.** A subtree runs a small amount of work many times. The roll-up looks huge but no single
  invocation blocks for long. `Timer._on_timer_update` → `Screen._refresh_layout` is this kind: dozens of repaint
  ticks over 255s.

Both matter for "blazing fast user navigation". Per-callback stalls produce visible hitches on a specific action;
per-frame amortized cost burns CPU continuously, raises ambient latency, and makes it more likely that any scheduled
work overlaps with a keypress. The ranking below names which class each item belongs to.

## Headline Summary

The two best next optimization targets, by category:

1. **Per-frame paint cost** — the Timer-driven Compositor subtree is 21.660s total in this profile. The biggest single
   win available is teaching the existing `LazySyntaxRenderCache` / `_CachedSyntaxRenderable` to survive between the
   reflow (sizing) pass and the paint pass of the same frame. Today the cache key includes `options.height`, so the
   sizing pass and the painting pass for the same widget at the same width produce different cache keys and both pay
   for `Syntax._get_syntax` + `MarkdownLexer.get_tokens_unprocessed`. Fixing this should roughly halve prompt-panel
   render cost without changing any caps.
2. **Per-callback blocking cost** — the 1.192s `_apply_loaded_agents_prepared` continuation that fires after the async
   agent loader returns. Moving `_merge_incomplete_load_after_complete_history()` (0.597s) and
   `filter_agents_by_fold_state()` (0.237s) into the worker, returning a prepared apply payload, is the second-best
   slice. This was the only target the first version of this note identified.

The 56.015s `run_editor` subtree remains a deliberate suspended-editor interaction and is not the next move for
`j`/`k` responsiveness.

## Hot Paths In This Profile

### 1. Timer-driven Screen refresh — 21.660s total (per-frame amortized)

Profile excerpt (`~/tmp/sase/ace_profile_20260515_105702.txt:4629`):

```text
21.660 Timer._run_timer  textual/timer.py:143
└─ 21.629 Timer._tick
   └─ 20.704 Screen._on_timer_update
      └─ 18.355 Screen._refresh_layout
         ├─ 13.731 Screen._compositor_refresh
         │  └─ 12.564 Compositor.render_update
         │     └─ 12.493 render_partial_update
         │        └─ 12.431 _render_chops
         │           └─ 10.244 _get_renders
         │              ├─ 5.704 AgentPromptPanel.render_lines
         │              │   └─ … _CachedSyntaxRenderable.__rich_console__ / Syntax._get_syntax …
         │              └─ 4.502 AgentList.render_lines
         │                  └─ 2.572 AgentList.render_line
         │                       └─ 1.202 AgentList._get_option_render
         │                            └─ 0.881 Padding.to_strips
         │                                 └─ 0.569 Padding.render_strips
         │                                      └─ 0.535 Content.render_strips
         │                                           └─ 0.482 _FormattedLine.to_strip
         │                                                └─ 0.233 Content.render
         └─ 4.290 Compositor.reflow
            └─ 4.247 _arrange_root
               └─ resolve_box_models
                  └─ 3.060 AgentPromptPanel._get_box_model
                     └─ 3.031 AgentPromptPanel.get_content_height
                        └─ 2.863 RichVisual.get_height
                           └─ 2.776 Console.render
                              └─ 1.506 _CachedSyntaxRenderable.__rich_console__
                                 └─ 1.448 Syntax.__rich_console__
                                    └─ 1.444 Syntax._get_syntax
                                       └─ 0.748 Console.render_lines
                                          └─ 0.314 MarkdownLexer.get_tokens_unprocessed
```

Two observations the first pass missed:

- **The reflow path independently re-renders the prompt panel to ask for its height.** `_CachedSyntaxRenderable`
  exists for exactly this case, but in the trace its `__rich_console__` is called inside `get_height` for 1.506s and
  still falls through to `Syntax._get_syntax` (1.444s) and `MarkdownLexer.get_tokens_unprocessed` (0.314s). Looking at
  `src/sase/ace/tui/util/lazy_syntax.py:47-56`, the cache key is built from
  `(max_width, min_width, legacy_windows, ascii_only, no_wrap, overflow, height)`. The sizing pass passes a different
  `options.height` (it asks "given this width, how tall do you want to be?") than the paint pass, so the same widget
  at the same width gets two cache entries per frame and pays `Syntax._get_syntax` twice. The cache cap of 4 entries
  per renderable also evicts width history across selection changes.
- **`AgentList.render_lines` is 4.502s on its own**, dominated by `_FormattedLine.to_strip` → `Content.render` →
  `get_current_style`. Each option row is re-rendered through Textual's full strip pipeline every frame the list is
  marked dirty. The pre-built `Content` objects from `AgentList.update_list` are reused, but `to_strip` per visible
  row per frame is what is sampled here.

#### Why this matters for navigation

255.502s of wall time at, say, 30 paint ticks per second is roughly 7,650 timer ticks, putting average compositor work
near ~1.6ms per tick. That is fine in isolation. The hazard is that a "dirty layout" repaint can chain across
selection changes: pressing `j` invalidates the prompt panel and the highlighted list row, which both go through this
subtree on the next paint. If a keypress lands during a paint, it is queued behind it.

### 2. Async agent refresh apply continuation — 1.192s (per-callback blocking)

Excerpt (`~/tmp/sase/ace_profile_20260515_105702.txt:121-167`):

```text
1.378 AceApp._run_agents_async_refresh
└─ 1.321 AceApp._load_agents_async
   └─ 1.192 AceApp._apply_loaded_agents_prepared
      ├─ 0.597 AceApp._merge_incomplete_load_after_complete_history
      │   ├─ 0.308 [self]
      │   ├─ 0.050 is_dismissed
      │   ├─ 0.049 Agent.identity
      │   ├─ 0.046 AgentType.__hash__
      │   ├─ 0.034 is_always_visible / Agent.is_workflow_child
      │   ├─ 0.030 dedup_running_vs_workflow
      │   └─ 0.029 _reattach_children_after_parent_dedup
      └─ 0.507 AceApp._finalize_agent_list
          └─ 0.507 finalize_agent_list
             ├─ 0.237 filter_agents_by_fold_state
             │   ├─ 0.114 [self]
             │   ├─ 0.072 Agent.is_workflow_child
             │   ├─ 0.019 <genexpr> _fold_filter.py:42
             │   └─ 0.009 <genexpr> _fold_filter.py:43
             ├─ 0.162 [self] _loading_finalize.py
             └─ 0.102 AceApp._refresh_agents_display
                └─ 0.089 _refresh_panel_widgets
                   └─ 0.069 AgentList.update_list
                      └─ 0.068 build_list
                         └─ 0.030 AgentList.add_options
                            └─ 0.029 _update_lines
                               └─ 0.016 _get_visual → 0.014 Content.from_rich_text
```

This is a single synchronous callback on the event loop. While it runs the user cannot dispatch input. Functions
involved:

- `src/sase/ace/tui/actions/agents/_loading_apply.py:_merge_incomplete_load_after_complete_history` (0.597s).
- `src/sase/ace/tui/models/_fold_filter.py:filter_agents_by_fold_state` (0.237s).
- `src/sase/ace/tui/actions/agents/_loading_finalize.py:finalize_agent_list` (0.507s incl. children).
- `src/sase/ace/tui/widgets/_agent_list_build.py:build_list` (0.068s).

`Agent.is_workflow_child` (line 460 of `models/agent.py`) is called from `_merge_incomplete_load_after_complete_history`,
`filter_agents_by_fold_state`, and `_reattach_children_after_parent_dedup` each on the same agent objects in one
refresh. It is a computed property, not a stored field.

### 3. App focus/blur stylesheet recompute — 0.289s combined (per-callback blocking, infrequent)

Excerpts (`profile lines 2062`, `~lines 2198`):

```text
0.171 AceApp._on_app_blur
└─ Reactive._set → invoke_watcher → _watch_app_focus
   └─ Screen.update_node_styles
      └─ AceApp.update_styles
         └─ 0.165 Stylesheet.update_nodes
            └─ 0.164 Stylesheet.apply
               ├─ 0.063 Stylesheet.replace_rules
               └─ … RenderStyles property reads …
```

A companion 0.118s `_on_app_focus` runs the symmetric path. A switch into and out of focus pays ~0.3s of stylesheet
recomputation. This fires whenever the terminal application loses or gains focus (alt-tab, opening a popup, etc.).
There is no protective debounce; the second focus event redoes the work even though styles cannot have changed in the
intervening millisecond.

### 4. ChangeSpec async refresh apply — 0.180s + 0.086s on_mount (per-callback blocking, residual)

The prior research note documented earlier work that moved the corpus compile off the UI thread and the headline
numbers are gone. Two residual costs remain in this profile (`profile lines 424`, `3914`):

```text
0.180 AceApp._apply_reloaded_changespecs
├─ 0.130 _filter_changespecs_impl
│   └─ 0.098 build_query_context_python
│       └─ 0.073 get_base_status
└─ 0.048 _apply_prepared_query_corpus

0.086 _compile_query_corpus_for_changespecs (on_mount)
└─ 0.084 compile_query_corpus
    ├─ 0.038 to_json_dict
    │   └─ 0.034 dataclasses.asdict
    ├─ 0.031 compile_corpus (Rust binding)
    └─ 0.014 changespec_to_wire
```

The 0.086s on_mount cost is a one-shot but it is on the UI thread during the first paint. The 0.180s `_apply` continuation
runs whenever ChangeSpecs reload. Neither is in the same league as items 1 and 2, but `dataclasses.asdict` is still
the largest unit cost in the corpus compile path and is a candidate for the Rust-core wire boundary work flagged in
the prior responsiveness note.

### 5. Per-selection model resolution does filesystem work — ~0.025s per `watch_current_idx`

Excerpt (`profile line ~883`):

```text
0.041 AceApp.update_header_only
└─ 0.032 build_header_text
   └─ 0.026 append_model_field
      └─ 0.025 resolve_model_provider
         └─ 0.025 load_merged_config
            ├─ 0.018 _get_overlay_paths
            │   └─ 0.016 glob.scandir
            └─ 0.007 PosixPath.stat / stat_token
```

`append_model_field` is on the per-row header rebuild path. Each `j`/`k` reaches `resolve_model_provider`, which calls
`load_merged_config`, which globs and `stat`s overlay paths. The cost per call is small (~25ms) but it is on the input
path. Memoizing the resolved provider/model by config overlay fingerprint would remove this from each navigation.

### 6. Quit-time `ArtifactWatcher.stop` — 0.449s

Not navigation-relevant but worth recording so future profiles do not chase it. The watcher thread join during app
shutdown sampled at 0.449s.

### 7. Editor subprocess wait — 56.015s

Deliberate suspended editor. Same conclusion as before: this is a UX question (keep ACE interactive while a graphical
editor is open?), not a responsiveness fix.

## What Is No Longer Hot

Verifying claims from `sdd/research/202605/ace_profile_20260515_responsiveness.md` against this profile:

- **Artifact-discovery completion → header rebuild**: sampled at 0.041s for header-only rebuilds, well under 50ms.
  Confirmed resolved.
- **LLMOverrideIndicator first refresh**: 0.001s `on_mount` in this profile; the cold scan is now off-thread.
  Confirmed resolved.
- **`_llm_metadata_payload` per-render scan**: not visible as a multi-tens-of-ms hot path. The remaining provider
  resolution cost surfaces under `resolve_model_provider` → `load_merged_config` (item 5), which is a different
  problem — config overlay disk access, not entry-points scanning.
- **ChangeSpec corpus compile**: largely resolved as a navigation hazard. Residual on_mount and post-reload work
  (item 4).
- **0.475s `_finalize_agent_list` on the UI thread**: still present but reshaped — now 0.507s and the dominant cost
  shifted from `AgentList.update_list` to `filter_agents_by_fold_state` and the new `_merge_incomplete_load_after_complete_history`
  step. Item 2.

## Ranked Next Options

### Option A — Fix the `_CachedSyntaxRenderable` width-vs-height cache key (P0, per-frame)

`src/sase/ace/tui/util/lazy_syntax.py:47-56` builds the cache key from
`(max_width, min_width, legacy_windows, ascii_only, no_wrap, overflow, height)`. The sizing pass (reflow) and the
paint pass for the same widget at the same width differ only in `options.height`, so the cache misses between sizing
and painting in one frame.

Proposed change:

- Drop `height` from `_render_options_key` (and any other purely-output dimension that does not affect the rendered
  segments at a given width).
- Increase `_max_width_entries` from 4 to a small ring such as 8 so that switching between selected agents does not
  evict the cached render for the previously-visible content.
- Verify that `Syntax` rendering is deterministic over `height`. If `line_range` truncation interacts with `height`,
  encode the actually-used row count separately from the options height.

Expected impact: removes ~1.5s of `Syntax._get_syntax` from the reflow path and reduces the worst-case prompt-panel
per-frame double-render. This is the cheapest concrete change in the list.

Tests:

- Add a unit test in `tests/ace/tui/util/test_lazy_syntax.py` that calls the renderable twice with the same width and
  different `options.height` values and asserts only one underlying `Syntax` console.render takes place (mock or
  capture).
- Render a known prompt at width W, capture segments, then call with the same width and a different height; assert
  segments equal.

### Option B — Move the post-load apply/finalize prep off the UI thread (P0, per-callback)

Same proposal as the prior version of this note. Snapshot the UI-owned inputs needed for reconciliation before the
await boundary, run merge + fold-filter + status overrides + selection-restoration math in a worker, and return a
`PreparedApplyData` for the UI thread to install.

First slice: `_merge_incomplete_load_after_complete_history()` only (0.597s), because it requires only cached agents,
incoming filtered agents, dismissed identities, and a few boolean flags.

Second slice: roll `filter_agents_by_fold_state()` (0.237s) into the same worker stage.

Acceptance:

- No single async agent refresh continuation should block the event loop for more than ~50ms on the profiled tree.
- A trace shows user `j`/`k` input dispatching while disk load and reconcile prep are in flight.
- Selection and fold behavior have explicit before/after tests at the snapshot/prepare/apply boundary.

### Option C — Debounce the app focus/blur stylesheet refresh (P1, per-callback)

Items 3's 0.289s combined cost on a focus toggle. Either:

- Collapse rapid blur/focus pairs (terminal multiplexers can fire both within milliseconds when switching panes).
- Skip `Stylesheet.apply` when nothing changed since the last apply (compare a hash of the active rule set).

This is small in this profile but high leverage on tiling-WM and tmux users.

### Option D — Cache merged config behind `resolve_model_provider` (P1, per-selection)

Item 5 burns ~25ms per j/k. Either memoize `load_merged_config` for the active workspace, or have the per-agent header
pull a precomputed provider/model string from the loader.

### Option E — Make `Agent.is_workflow_child` cheap (P1, per-callback)

Item 2 shows `Agent.is_workflow_child` accounting for 0.072s under `filter_agents_by_fold_state` alone, plus more
under the merge step. It is a computed property today (`src/sase/ace/tui/models/agent.py:460`). Stash the boolean on
the `Agent` dataclass at load time, or carry parent/child relationships from the loader so callers do not recompute
them.

### Option F — Treat `AgentList.render_lines` per-row cost as a follow-up (P2, per-frame)

4.502s rolled-up in this profile but with per-call cost dominated by `_FormattedLine.to_strip` and `Content.render`
inside Textual's option-list strip pipeline. Wait until Options A/B/C land and reprofile before deciding whether to
pursue a custom list renderer or a wider `Content` cache.

### Option G — Hold off on the editor subprocess UX change (P2)

Same conclusion as the prior note. Keep separate from this optimization track.

## Recommended Next Bead

Bundle Options A and B into one optimization bead, **TUI per-frame and post-load apply latency**, in that order: ship
the lazy-syntax cache key fix first because it is small and self-contained, then layer the off-thread apply prep on
top.

Suggested implementation sequence:

1. Lazy-syntax cache key fix (Option A). Tests + trace.
2. Reprofile with `SASE_TUI_TRACE=1 SASE_TUI_PERF=1 sase ace --profile ...` to confirm the reflow path is no longer
   double-rendering. Expected: `_CachedSyntaxRenderable.__rich_console__` total drops noticeably.
3. Add timing/trace spans inside `_apply_loaded_agents_prepared`, `_merge_incomplete_load_after_complete_history`,
   `filter_agents_by_fold_state`, `finalize_agent_list`, and `AgentList.update_list` so the next round can attribute
   continuation cost precisely.
4. Extract `_merge_incomplete_load_after_complete_history` into a pure worker helper, called from `_load_agents_async`
   before returning to UI-thread apply.
5. Add tests covering: incomplete Tier 1 load after complete history, newly discovered Tier 1 roots and children,
   dismissed suffix behavior, RUNNING vs WORKFLOW and PID dedup.
6. Roll `filter_agents_by_fold_state` into the same worker stage.
7. Reprofile and compare async refresh continuation against this profile's 1.192s baseline and per-frame paint cost
   against 21.660s baseline.

## Risks

- **Lazy-syntax cache correctness.** Removing `height` from the key assumes Rich `Syntax` does not change segment
  content based on requested height. This holds for the path actually used (no `line_numbers` height-dependent
  formatting in our defaults) but should be guarded by tests.
- **Selection and fold regressions.** Finalization mixes data shape, visibility, and current cursor state. Worker
  output must be a pure structure; the UI thread must own the actual mutation. Snapshot/prepare/apply boundaries need
  explicit tests.
- **Stale worker results.** Last-request-wins refresh coalescing must be preserved. Worker results should be discarded
  or re-run if the relevant UI state (selection, fold registry, hide flags) changed before apply.
- **Mutable inputs.** Some finalization inputs are app-owned mutable state. Snapshot them with explicit copies before
  passing to a worker; do not let a worker read live Textual app attributes.

## Verification Strategy

Three measurement tracks:

1. **A/B traces from `sase ace --profile`** with the same interaction sequence as this capture. Success means
   `_CachedSyntaxRenderable.__rich_console__` no longer dominates the reflow subtree and `_apply_loaded_agents_prepared`
   continuation drops below 100ms in the worst sampled case.
2. **Targeted `SASE_TUI_PERF=1` scenario** that selects an agent with a medium markdown reply, presses `j`/`k` 50-100
   times across a workflow with fold children, and reports per-keypress dispatch latency. Track p50/p95/p99 frame gaps
   over the run.
3. **Microbenchmark for `_merge_incomplete_load_after_complete_history`** on a realistic agent list (mix of completed
   history, running, workflow children). The off-thread fix is only worthwhile if the per-call cost stays above ~50ms
   on representative input.

Keep the earlier startup trace work from `sdd/research/202605/ace_startup_profile_20260502.md` and the prior responsiveness
note in scope; they document past wins that are still load-bearing.

## Open Questions

- Is the 21.660s Timer subtree dominated by a small number of layout-dirty repaints (e.g. each `j`/`k` invalidating
  the prompt panel and forcing a full reflow), or is it spread across many idle-tick repaints? Add a trace counter to
  `Compositor.reflow` and `_get_renders` to distinguish.
- Does removing `height` from the lazy-syntax cache key affect `line_range` truncation paths in the file panel? The
  file panel uses the same `lazy_renderable()` helper. Profile-driven before/after on a large diff would confirm.
- Can `Agent.is_workflow_child` become a cached property safely, or are there reload paths that mutate the underlying
  fields after construction?
- Is the per-row `_FormattedLine.to_strip` cost recoverable without a custom list renderer? A small per-content-id
  strip cache in `AgentList` might reuse strips across paints when the row content has not changed.
- For the residual ChangeSpec wire boundary: does teaching the Rust binding to consume dataclass instances directly
  remove `dataclasses.asdict()` from the on_mount and reload paths entirely? The Rust binding contract lives in
  `../sase-core/crates/sase_core` per the Rust core boundary policy.

## Decision

Ship Option A (lazy-syntax cache key fix) first as a small, self-contained change. Then ship Option B (off-thread
merge/finalize prep) as the next bead. These two together attack both per-frame paint cost and per-callback blocking
cost, which together cover the two distinct ways a TUI can feel sluggish during navigation.

Hold off on Options C-G until A and B land and a fresh profile is captured.
