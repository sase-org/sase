# `sase ace` Responsiveness Profile Review (2026-05-15)

## Source

- Profile artifact: `/home/bryan/tmp/sase/ace_profile_20260515_004214.txt`
- Command: `sase ace --profile`
- Tool: pyinstrument v5.1.2
- Recorded: 2026-05-15 00:41:22
- Duration: 51.864s wall, 58.924s CPU, 7,463 samples
- Profile root: `src/sase/main/ace_handler.py:74`

This capture is a live interactive session, not only startup. The largest bucket
is event-loop wait (`epoll.poll`, 41.95s of 51.86s wall ≈ 81% idle), but the
actionable CPU samples point to repeated detail-pane rendering and several
main-thread discovery and serialization paths that make the TUI feel
unresponsive while the app is otherwise "running".

## TL;DR

The May 2 startup profile found hidden cold-load time in off-thread agent
loading. This May 15 profile shows a different problem: **the selected agent
detail pane is expensive to render repeatedly**, and a handful of background
refreshes complete by doing significant synchronous work on the UI thread:

1. **Repeated Pygments syntax rendering** of the prompt body. Textual asks for
   the panel's content height *and then* paints it, and Rich's `Syntax` does
   not cache lexed tokens between those two passes — so the markdown lexer
   tokenizes the same content twice for one frame (`get_content_height` 1.019s
   + `render_lines` 1.763s for the same widget).
2. **ChangeSpec query-corpus rebuild on the UI thread**. The background
   changespec refresh hands the loaded list back to the main thread, which
   calls `_filter_changespecs_impl` → `_get_query_corpus_for_changespecs`.
   That keys its Python cache on `id(list)`, so every reload misses the cache
   and recompiles via `dataclasses.asdict()` (0.521s) + the Rust
   `compile_corpus` call (0.338s). Total 1.079s on the UI thread, every reload.
3. **Header text rebuilds re-scan entry points**. Every agent-detail header
   render calls `append_model_field()` → `_llm_metadata_payload()`, which is
   **not** memoized, and which calls `_llm_metadata_cache_policy()` that
   re-scans `importlib.metadata.entry_points(group="sase_llm")` and rebuilds
   the metadata payload from scratch. Cost per render varies 0.011–0.089s
   depending on Python's internal FastPath cache state.
4. **Header artifact / delta discovery re-runs on every header rebuild**. The
   debounced full detail update can spend 0.572s in `build_header_text()` on
   one selection, dominated by `list_agent_artifacts()` (0.231s),
   `append_model_field()` (0.089s), and `get_agent_diff()` (0.063s).
5. **LLMOverrideIndicator's first refresh is a 0.655s cold-cache hit** on the
   UI thread; subsequent 30s-interval refreshes are ~0.008s. This is a startup
   problem, not an ongoing periodic stall.
6. **Background → UI hand-back is synchronous**. After
   `_load_agents_async` returns, `_apply_loaded_agents_prepared` runs 0.475s
   synchronously inside the main thread to finalize the list, refresh panels,
   and propagate to widgets — visible as a hitch shortly after launch.

Highest-value fixes are ranked in the [Recommended Fix Plan](#recommended-fix-plan).

## Phase 6 Verification (2026-05-15)

### Source

- Profile artifact: `/home/bryan/tmp/sase/ace_profile_sase-3l6_20260515_workspace.txt`
- Trace artifacts:
  - `/home/bryan/tmp/sase/ace_trace_sase-3l6_20260515_workspace.jsonl`
  - `/home/bryan/tmp/sase/ace_jk_sase-3l6_20260515_workspace.jsonl`
- Query benchmark artifact: `/home/bryan/tmp/sase/bench_core_query_sase-3l6_20260515.json`
- Profile command:
  `SASE_TUI_TRACE=1 SASE_TUI_TRACE_PATH=/home/bryan/tmp/sase/ace_trace_sase-3l6_20260515_workspace.jsonl SASE_TUI_PERF=1 SASE_TUI_PERF_PATH=/home/bryan/tmp/sase/ace_jk_sase-3l6_20260515_workspace.jsonl .venv/bin/sase ace --profile /home/bryan/tmp/sase/ace_profile_sase-3l6_20260515_workspace.txt`
- Recorded: 2026-05-15 09:25:54
- Duration: 13.217s wall, 9.590s CPU, 1,637 samples
- Interaction sequence: first top-bar indicator render, initial agent load, `j/k`
  over the Agents tab, manual refresh, tab switch through AXE to CLs, ChangeSpec
  refresh/filter, then quit.

### Result

The combined phases removed the dominant interactive hot paths from the May 15
baseline:

| Path | Baseline | Phase 6 verification |
| --- | ---: | ---: |
| Async ChangeSpec refresh/filter continuation | 1.079s, including 1.021s `compile_query_corpus` on the UI thread | Trace refresh/filter spans after tab switch: 2.8-5.1ms. The remaining profiled corpus compile is startup/on-mount, 0.089s inside a 0.101s `_apply_changespecs` path. |
| Agent-load UI apply | 0.475s `_finalize_agent_list` | 0.062s `_apply_loaded_agents_prepared` / `_finalize_agent_list` in the measured refresh; trace `agents.refresh_display` 7.6ms after worker load. |
| Full agent detail/header update | 0.572s `build_header_text` on one j/k selection, including artifact listing, deltas, and provider metadata | Trace `widget.agent_detail.update_display` 10.6ms and `widget.prompt_panel.update_display` 4.0ms for the selected done agent. Profile samples for later full updates were 0.003-0.010s. |
| Prompt markdown paint | 1.763s `AgentPromptPanel.render_lines` plus 1.019s height calculation | No `AgentPromptPanel.render_lines` or `MarkdownLexer` hot path appeared in this profile; prompt rendering went through `LazySyntaxRenderCache` and stayed below sampling significance. |
| First LLM indicator render | 0.655s synchronous resolver | `LLMOverrideIndicator.on_mount` scheduled a worker in 0.001s. The first provider metadata fill still appeared once through agent header rendering at 0.029s. |

One quit-time `ArtifactWatcher.stop` join sampled at 0.287s. That is outside
ordinary navigation/reload responsiveness and was not counted against the Phase
6 target.

### Query Corpus Benchmark

Command:
`just bench-query --runs 5 --warmup 1 --spec-sizes 100,1000 --skip-home-tree --output /home/bryan/tmp/sase/bench_core_query_sase-3l6_20260515.json`

Key rows:

| Workload | `rust_persistent_corpus_compile` median | `rust_persistent_query_keystroke_evaluate_many` median |
| --- | ---: | ---: |
| synthetic_100_specs | 6.408ms | 0.010ms |
| synthetic_1000_specs | 67.297ms | 0.068ms |

The corpus compile cost is still mostly Python wire serialization, but the
measured UI path no longer repeatedly pays that cost during async reload/filter
interaction. The remaining startup compile is just under the roughly 100ms
target on this machine, so the data does not justify a Rust-core serialization
phase yet. If a future real project profile shows startup/on-mount
`_apply_changespecs` or corpus compile above 100ms, the next step is a
separate Rust-core design to reduce `dataclasses.asdict()` / wire-dict
allocation across `../sase-core`, `sase_core_rs`, and the Python callers.

## Captured Hot Paths

### 1. Prompt Panel Render Cost

Main render branch:

```text
5.091 Timer._run_timer
└─ 4.343 Screen._on_timer_update
   └─ 4.088 Screen._refresh_layout
      └─ 2.696 Compositor.render_partial_update
         └─ 2.685 Compositor._render_chops
            └─ 2.385 Compositor._get_renders
               └─ 1.763 AgentPromptPanel.render_lines
                  └─ RichVisual.render_strips
                     └─ Segment.split_and_crop_lines
                        └─ Console.render
                           └─ Syntax.__rich_console__
                              └─ Syntax._get_syntax
                                 └─ MarkdownLexer.get_tokens_unprocessed
```

The prompt panel builds `Syntax` objects via `lazy_renderable()` for prompt,
reply, response, attempt, bash/python, and JSON step output content
(`src/sase/ace/tui/widgets/prompt_panel/_agent_display.py:137-245`).
`lazy_renderable()` only skips syntax highlighting above 64 KiB or 1,500 lines
(`src/sase/ace/tui/util/lazy_syntax.py:17-18`), so medium-sized markdown can
still be re-tokenized during Textual render/layout.

The capture also shows a parallel branch where Textual reflows the layout and
asks the same widget for its content height by *also* rendering it:

```text
1.243 Compositor.reflow
└─ 1.025 VerticalScroll.arrange
   └─ 1.021 resolve_box_models
      └─ 1.021 AgentPromptPanel._get_box_model
         └─ 1.019 AgentPromptPanel.get_content_height
            └─ 1.018 RichVisual.get_height
               └─ ... 0.914 Syntax.__rich_console__ → 0.906 Syntax._get_syntax
```

This is the same `Syntax._get_syntax` call (and therefore the same
`MarkdownLexer.get_tokens_unprocessed`) that the paint path on line 1.763 also
hits. Rich's `Syntax` builds `Segments` lazily per call to `__rich_console__`
and does not cache the lexed result between sizing and painting passes — so
each frame that needs a height-and-paint of the same renderable pays for
Pygments tokenization twice.

**Interpretation:** the visible 1.763s + 1.019s ≈ 2.78s spent here is repeated
*per-frame, per-widget* work, much of which is redundant within a single frame.
A user perceives this as sluggish navigation or delayed repaint after row
selection; the smaller terminal width or smaller selection makes very little
difference because the cost scales with content size, not frame area.

### 2. Header Detail Rebuild Does Main-Thread I/O

The debounced full detail update calls:

```text
AgentDetail.update_display
└─ AgentPromptPanel.update_display
   └─ build_header_text
      ├─ append_agent_artifacts_section
      ├─ append_agent_deltas_section
      ├─ append_model_field
      └─ format_agent_bead_display
```

In this profile, a post-artifact-discovery refresh spent 0.290s on the UI
thread:

```text
0.290 AceApp._run_agent_artifact_discovery
└─ 0.290 AceApp._fire_debounced_detail_update
   └─ 0.289 AgentDetail.update_display
      └─ 0.285 AgentPromptPanel.update_display
         └─ 0.282 build_header_text
            ├─ 0.179 append_agent_artifacts_section
            │  └─ list_agent_artifacts
            ├─ 0.050 append_agent_deltas_section
            │  └─ get_agent_diff
            ├─ 0.027 append_model_field
            └─ 0.025 format_agent_bead_display
```

The issue is not that artifact discovery lacks a background path. It has one:
`_run_agent_artifact_discovery()` calls `asyncio.to_thread(...)` and stores a
per-row cache (`src/sase/ace/tui/actions/agents/_panel_artifacts.py:300-317`).
The problem is that the continuation calls `_fire_debounced_detail_update()`
(`src/sase/ace/tui/actions/agents/_panel_artifacts.py:328-331`), and the prompt
header path ignores that cache:

- `build_header_text()` appends deltas and artifacts whenever `cheap=False`
  (`src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py:385-390`).
- `append_agent_artifacts_section()` calls `_agent_artifact_paths()`, which
  calls `list_agent_artifacts(artifacts_dir)` synchronously
  (`src/sase/ace/tui/widgets/prompt_panel/_agent_artifacts.py:34-67`).
- `append_agent_deltas_section()` calls `get_agent_diff()`, which can read a
  diff file, resolve a VCS provider, and run `provider.diff_with_untracked(...)`
  for active agents (`src/sase/ace/tui/widgets/file_panel/_diff.py:95-159`).

**Interpretation:** the detail header has become a second artifact/diff
discovery surface. Even when the footer probes artifacts safely, the header
re-enters expensive synchronous work.

### 3. Top-Bar LLM Indicator Blocks Once (Cold Cache, Not Periodic)

The profile captured one expensive `LLMOverrideIndicator.refresh()` costing
0.655s:

```text
0.655 LLMOverrideIndicator.refresh
└─ _build_default_content
   └─ resolve_effective_default_provider_model
      └─ get_provider
         └─ _create_provider_for
            └─ _find_plugin_class
               └─ importlib.metadata.entry_points
```

The widget calls `_build_content()` in `__init__`, again in `on_mount()`, and
then every 30 seconds (`src/sase/ace/tui/widgets/llm_override_indicator.py:45-57`).
`get_provider()` always creates a fresh provider through `_create_provider_for()`
(`src/sase/llm_provider/registry.py:172-193`), which calls `_find_plugin_class()`
that scans `importlib.metadata.entry_points(group="sase_llm")` each time
(`src/sase/llm_provider/registry.py:157-169`).

**Important correction:** this 0.655s call is the *cold* entry-points scan.
Other `LLMOverrideIndicator` invocations in the same trace cost 0.008s each
(`__init__` and `on_mount`). Python's `importlib.metadata` internally
memoizes `FastPath` scans, so once the disk distributions are read once the
follow-up calls in the same process are cheap. The fix here is not "cache
provider resolution forever"; it is **don't pay the first cold scan on the UI
thread**. Resolve the default provider/model in a worker started during
`AceApp.__init__` and have the indicator display a placeholder until the
worker posts a `Message` back.

### 4. `_llm_metadata_payload()` Is Not Memoized and Re-Scans Entry Points

This is a separate problem from #3 and the existing note understated it.
`_llm_metadata_payload()` (`src/sase/llm_provider/registry.py:114-116`) is a
plain function with no `@functools.cache`. It always calls
`_direct_llm_metadata_payload()`, which builds a dict that includes the result
of `_llm_metadata_cache_policy()` (`registry.py:313-336`). The cache-policy
helper *itself* iterates `importlib.metadata.entry_points(group="sase_llm")`
and `sorted(...)`s them to compute an invalidation fingerprint.

In this profile, every render of the agent-details header pays this cost
through `append_model_field()` → `resolve_model_provider()` →
`model_to_provider_map()` → `_llm_metadata_payload()`:

| Header rebuild | `append_model_field` | Of which entry-points scan |
| --- | ---: | ---: |
| Post-discovery refresh | 0.027s | 0.026s |
| First j/k detail update | 0.089s | 0.074s |
| Cached / warm subsequent renders | 0.008–0.012s | 0.005–0.011s |

The "cache_invalidation" key returned by `_llm_metadata_cache_policy` looks
like a cache fingerprint, but nothing actually consumes it as a cache key —
the function rebuilds the full metadata payload from plugins every call.

**Interpretation:** the field naming makes this look intentional, but it
behaves as an unmemoized rebuild. Add `@functools.cache` to
`_llm_metadata_payload()` (matching `_build_llm_pm`'s memoization model) and
expose a `cache_clear()` for tests. The cache-policy fingerprint can still
be computed once and reused.

### 5. ChangeSpec Query Corpus Rebuild Runs on the UI Thread

The largest single hot path the prior version of this note missed entirely.
After `_reload_and_reposition_async` returns from its
`asyncio.to_thread(find_all_changespecs_cached)` await, the continuation
runs `_apply_reloaded_changespecs` → `_filter_changespecs_impl` →
`_get_query_corpus_for_changespecs` *synchronously on the UI thread*:

```text
1.079 AceApp._run_changespecs_async_refresh
└─ 1.079 AceApp._reload_and_reposition_async
   └─ 1.079 AceApp._apply_reloaded_changespecs
      └─ 1.079 AceApp._filter_changespecs
         └─ 1.079 AceApp._filter_changespecs_impl
            └─ 1.036 AceApp._get_query_corpus_for_changespecs
               └─ 1.021 compile_query_corpus
                  ├─ 0.538 to_json_dict          (core/wire.py:167)
                  │  └─ 0.521 dataclasses.asdict (recursive)
                  ├─ 0.338 compile_corpus        (Rust binding)
                  └─ 0.132 changespec_to_wire    (per-spec wire conversion)
```

`_get_query_corpus_for_changespecs` caches its compiled corpus keyed on
`id(changespecs)` (`src/sase/ace/tui/actions/changespec/_loading.py:130-160`).
That key is **structurally guaranteed to miss on every reload** because
`_apply_reloaded_changespecs` always hands in a freshly-loaded list object.
So every refresh — file-watcher tick, manual reload, post-edit
notification — pays:

- a full Python recursion through `dataclasses.asdict()` over every
  `ChangeSpec` (and its nested `CommitEntry`, `HookEntry`, `MentorEntry`,
  `SourceSpanWire`, etc.);
- a JSON-dict-shaped allocation per spec, just to feed the Rust binding;
- the Rust `compile_corpus` build on the new dicts.

**Interpretation:** this is the highest-value background-to-UI handoff fix in
the profile because the work runs entirely on the event loop. It is mostly
pure CPU + Python allocation; it has no I/O dependency on the live agent or
selection state and could run in the worker thread that already loaded the
ChangeSpecs from disk.

### 6. Largest Single Detail-Update Path (Not the Post-Discovery One)

The original version of this note focused on the 0.290s
post-artifact-discovery refresh that fires as the continuation of
`_run_agent_artifact_discovery()`. That is a real bug, but the bigger detail
update in the profile is unrelated to artifact discovery:

```text
0.718 AceApp._fire_debounced_detail_update
└─ 0.686 AgentDetail.update_display
   └─ 0.686 AgentDetail._update_display_impl
      ├─ 0.588 AgentPromptPanel.update_display
      │  └─ 0.572 build_header_text
      │     ├─ 0.231 append_agent_artifacts_section
      │     │  └─ 0.228 list_agent_artifacts
      │     ├─ 0.089 append_model_field
      │     │  └─ 0.089 _llm_metadata_payload (entry-points scan)
      │     └─ 0.063 append_agent_deltas_section
      │        └─ 0.062 get_agent_diff
      └─ 0.092 AgentFilePanel.update_display
         └─ 0.092 _update_display_body
```

This is a single j/k navigation event that triggered the debounced full detail
build. Of the 0.572s `build_header_text` cost: 40% is artifact listing, 16% is
LLM entry-point scanning, 11% is VCS diff discovery, 16% is the file-panel
update, and the remaining ~17% is pure Rich text building. The header
synchronously calls four kinds of expensive resolvers, each of which has its
own per-call cost story above.

**Interpretation:** this confirms that the prompt-header's I/O surface is the
biggest single moving cost for "feels slow after I press j/k". Fixing only the
post-discovery hitch (existing P0) does not address the much larger cost on
ordinary navigation.

### 7. Post-Load Apply Step Stalls the UI Thread for ~0.5s

After `asyncio.to_thread(load_agents_from_disk)` returns its results, the
continuation runs synchronously on the UI thread to install them:

```text
0.998 AceApp._run_agents_async_refresh
└─ 0.964 AceApp._load_agents_async
   └─ 0.884 AceApp._apply_loaded_agents_prepared
      └─ 0.475 AceApp._finalize_agent_list
         └─ 0.475 finalize_agent_list
            ├─ 0.253 AceApp._refresh_agents_display
            │  └─ 0.252 _refresh_agents_display_impl
            │     └─ 0.243 _refresh_panel_widgets_impl
            │        ├─ 0.183 AgentList.update_list
            │        │  └─ 0.180 build_list
            │        │     └─ 0.121 AgentList.add_option
            │        │        └─ 0.111 _update_lines
            │        │           └─ 0.046 _get_visual / 0.042 Content.from_rich_text
```

This is the UI-side glue that runs after the May 2 research's primary worker
work (the actual 3.28s disk scan). The disk scan was already moved to a
thread, but `_apply_loaded_agents_prepared` then spends almost half a second
on the event loop turning the loaded data into Textual option-list entries
and refreshing panel widgets.

**Interpretation:** the May 2 note's wins were real, but a separate UI-side
chunk still blocks paint for ~0.5s shortly after the app starts. This is the
main source of the "footer stopwatch keeps running for a beat after the
window paints" complaint observed in earlier work.

### 8. Startup `__init__` Costs Are Present But Not Dominant Here

`AceApp.__init__` was only 0.182s:

- `load_merged_config`: 0.071s, mostly PyYAML default config parsing.
- `load_dismissed_agents`: 0.055s.
- `load_keymap_registry`: 0.042s, again PyYAML.

Post-first-paint watcher setup was 0.088s, mostly artifact watch path scans and
`ctypes.util.find_library("c")`. These remain worth improving, but this profile
does not support treating them as the main responsiveness problem.

## Recommended Fix Plan

### P0 - Move ChangeSpec Query Corpus Build Off the UI Thread

The largest single UI-thread stall in the trace (1.079s) is the
post-`to_thread` continuation in `_reload_and_reposition_async`. The current
code does the cheap disk scan in a worker thread, then performs the expensive
`asdict()` + Rust `compile_corpus` work on the event loop. Two complementary
changes:

1. **Build the corpus inside the worker.** Have
   `_reload_and_reposition_async` return both the loaded ChangeSpec list and a
   pre-built `QueryCorpus` keyed by `id(list)`. The corpus build is pure CPU
   over data the worker already owns; doing it in the worker keeps the event
   loop free.
2. **Replace the dataclass `asdict()` serialization.** `compile_query_corpus`
   builds wire dicts only to ship them across the Rust binding. Either teach
   the Rust binding to accept the existing dataclass instances directly
   (matching how `changespec_to_wire` already produces wire records), or have
   the worker memoize wire dicts per `ChangeSpec` identity so unchanged specs
   don't pay `asdict()` on every reload. The 0.521s `_asdict_inner` cost is
   the largest item in this stall.

If only one change can ship first, the first one — running the existing build
inside the worker — already eliminates the UI-thread cost. The second is the
deeper fix.

Expected impact: removes the 1.079s UI-thread continuation per ChangeSpec
reload, eliminating a class of stalls that fire on every file-watcher tick
during heavy editing.

### P0 - Remove Full Detail Refresh From Artifact Discovery Completion

Change `_run_agent_artifact_discovery()` so completion updates only the
artifact cache and footer binding state. Do not call
`_fire_debounced_detail_update()` unless the prompt header is explicitly able to
consume the cached artifact list without touching disk.

Concrete options:

- Add an `artifacts` parameter to prompt header rendering and pass the cached
  result through the detail update.
- Split the header into cheap metadata plus async append-only "artifact/delta"
  sections.
- For a minimal first fix, keep ARTIFACTS out of the prompt header and rely on
  the footer/artifact viewer affordance.

Expected impact: removes the 0.290s UI-thread continuation seen in this
profile and prevents background artifact work from causing a visible hitch when
it finishes.

### P1 - Make Prompt Body Rendering Cacheable

Two layers are paying for the same Pygments tokenization:

1. `Compositor.reflow` → `VerticalLayout.arrange` → `get_content_height` →
   `RichVisual.get_height` → `Syntax.__rich_console__` (~1.02s).
2. `Compositor._get_renders` → `render_lines` → `RichVisual.render_strips` →
   `Syntax.__rich_console__` (~1.76s).

These render the same `Syntax` instance twice in one frame because Rich's
`Syntax` does not memoize tokenized segments between calls. Three orthogonal
fixes:

- **Replace `Syntax` with a memoizing wrapper for the prompt-body path.**
  Have `lazy_renderable()` return a small custom renderable that caches the
  generated `Segments` list keyed by `(width, no_wrap, theme, lexer,
  content_id)` for the lifetime of the visible selection. The next frame's
  `get_height` and `render_lines` both hit the cache.
- **Lower the syntax-highlight caps for markdown prompt/reply content.**
  `SYNTAX_HIGHLIGHT_MAX_BYTES = 64_000` and `SYNTAX_HIGHLIGHT_MAX_LINES =
  1_500` are reasonable for diffs and source files but generous for prompt
  markdown — most prompts that feel slow are well under the cap and still
  pay full Pygments cost. Consider a separate, tighter markdown cap (e.g.
  8 KiB / 200 lines), with plain `Text` above that.
- **Cache at the prompt-panel level by selected-agent content identity.**
  Key on selected agent identity, prompt/reply/response path + mtime/size or
  content hash, attempt view mode / pinned attempt, and render width. The
  cached value can be a `Group` of pre-rendered `Text` lines.

Expected impact: attacks the largest CPU hot path (1.763s prompt-panel
`render_lines` plus ~1.02s content-height work) and removes the in-frame
double tokenization between height-sizing and painting.

### P1 - Use Header Summary Fields Loaded With the Agent

Move header-only fields that require I/O into the agent load/prep path or an
async detail-summary worker:

- artifact availability/list;
- parsed delta summary;
- bead display text;
- provider/model display text.

`build_header_text()` should become pure over the `Agent` plus optional cached
summary. The current `cheap=True` path proves the UI already tolerates a staged
header; make the full path staged too.

Expected impact: prevents row selection from synchronously opening artifact
indexes, resolving paths, running VCS provider detection, running git commands,
or opening bead DBs.

### P1 - Memoize `_llm_metadata_payload()` and Defer the Indicator's First Refresh

Two related but separate fixes:

1. **Memoize `_llm_metadata_payload()`.** Add `@functools.cache` to
   `src/sase/llm_provider/registry.py:114`, matching the existing
   `_build_llm_pm` pattern (`registry.py:38-51`). Expose a `cache_clear()`
   shim for tests that mock entry points (the same convention already used
   elsewhere). The `_llm_metadata_cache_policy` fingerprint can be computed
   once at cache-fill time. This removes the per-header-render entry-points
   scan triggered by `append_model_field()`.
2. **Off-thread the LLMOverrideIndicator's first resolution.** Don't call
   `resolve_effective_default_provider_model()` from `__init__` or `on_mount`.
   Render a placeholder (e.g. `" … "`), kick off
   `asyncio.create_task` / `run_worker` to resolve the default in the
   background, then `update()` with the real label when the worker completes.
   The 30s periodic refresh already finds the cache warm, so this change is
   only about hiding the cold scan.

Expected impact: removes the 0.655s top-bar stall observed once in this
profile and cuts the recurring header-rebuild cost by ~0.027-0.089s per
`build_header_text()` invocation.

### P1 - Replace UI-Thread Apply Step With a Streamed/Chunked Apply

`_apply_loaded_agents_prepared` spent 0.475s on the event loop in this
profile, of which 0.183s was `AgentList.update_list` rebuilding Textual
option-list rows for every agent. Options:

- Build the option-list rows (Rich `Text` → `Content`) inside the same
  worker that loaded the agents, and only call into Textual to install the
  prepared rows. `Content.from_rich_text` and `Style.from_rich_style` are
  pure-Python and safe off the UI thread.
- Apply in chunks via `call_after_refresh()` so paint can intervene between
  batches.
- Skip rebuilding the entire list when only a small delta changed; the
  workers already know which agents were added/removed.

Expected impact: removes the ~0.5s post-launch hitch after the disk scan
completes.

### P2 - Keep Delta Diff Work Out of the Prompt Header

`get_agent_diff()` is appropriate for the file panel worker, but it is too
expensive for prompt-header rendering. Use one of:

- a cached diff summary populated by the file panel worker;
- a loader-computed persisted diff summary for completed agents;
- a "Deltas loading..." placeholder with an async summary update.

Expected impact: avoids `get_vcs_provider()`, entry-point scans, workspace
detection, and `diff_with_untracked()` on the UI thread during agent selection.

## Profiling Caveats

Read this profile with three caveats in mind so the next round of fixes
targets the real wins:

- **Pyinstrument is a statistical sampler.** It is excellent at finding *hot*
  CPU paths but under-represents very short, frequent calls and over-counts
  long blocking primitives (`epoll.poll`, `to_thread` waits). The 41.95s
  "idle" bucket is not 41.95s of true user inactivity — much of it is the
  main thread sleeping while worker threads do disk I/O or while Pygments
  runs inside a separate awaited render.
- **One profile, one user session.** The hot paths here are the ones that
  fired in 51.86s of *this* interaction. Different selections (a workflow
  with many child rows, a project agent without artifacts, a freshly-created
  ChangeSpec) will produce different traces. Use this list as a starting set,
  not a final ranked list.
- **`pyinstrument` overhead is small but not zero.** With `interval=0.001`
  the sampler itself adds 1–3% noise. Don't chase sub-1% items.

When evaluating fixes, prefer A/B traces from `sase ace --profile` with the
same selection sequence over micro-benchmarks of individual functions.

## Verification Strategy

Use three measurement tracks:

1. Re-run `sase ace --profile` and repeat the interaction that produced this
   trace. Success criteria: `AgentPromptPanel.render_lines`,
   `build_header_text`, and `compile_query_corpus` no longer dominate CPU
   samples during idle/selection.
2. Add a targeted Textual harness or `SASE_TUI_PERF=1` scenario for selecting an
   agent with artifacts, deltas, bead metadata, and a medium markdown reply.
   Track time to first cheap header paint, full detail paint, and frame gaps
   over 50–100 `j/k` movements.
3. Add a microbenchmark for `compile_query_corpus()` on a realistic
   ChangeSpec list (the trace's 1.079s is roughly proportional to spec
   count × per-spec dataclass depth). The fix is only worthwhile if the
   per-reload cost stays below ~50ms after moving the work into the worker.

Also keep the earlier startup trace work from
`sdd/research/202605/ace_startup_profile_20260502.md`; this note is about
interactive responsiveness after the TUI is open, not a replacement for
shell-to-first-use startup profiling.

## Open Questions

- Was the prompt panel expanded during most of the profile? The render hot path
  strongly suggests yes; collapsed/file-priority layout should be profiled
  separately.
- Was the selected row an agent with many explicit artifacts? The
  `read_explicit_agent_artifact_index()` branch consumed 0.107s inside the
  0.179s artifact header cost.
- Should ARTIFACTS/DELTAS live in the prompt header at all? They are useful, but
  the file panel and footer already own related interactions. Moving these to a
  separate async summary line would simplify the hot path.
- Does memoizing `_llm_metadata_payload()` break any test that mocks
  `entry_points` mid-process? `_build_llm_pm.cache_clear()` already exists for
  this pattern; the same convention should work, but confirm before shipping.
- For the ChangeSpec corpus fix: would teaching the Rust binding to consume
  dataclass instances directly remove the need for `to_json_dict()` entirely,
  or is the wire layer required for cross-process serialization elsewhere?
  The Rust binding contract lives in `../sase-core/crates/sase_core` per the
  Rust core boundary policy.
