# `sase ace` Responsiveness Profile (2026-05-15 13:03)

## Source

- Profile artifact: `/home/bryan/tmp/sase/ace_profile_20260515_131509.txt`
- Command: `sase ace --profile`
- Tool: pyinstrument v5.1.2
- Recorded: 2026-05-15 13:03:52
- Duration: 676.248s wall, 187.306s CPU, 46,609 samples
- Profile root: `src/sase/main/ace_handler.py:74`
- Capture window: an ~11-minute live interactive session (not startup-only).

Related prior research:

- `sdd/research/202605/ace_profile_20260515_responsiveness.md` (00:42 baseline +
  Phase 6 09:25 verification). That work fixed the dominant ChangeSpec corpus
  rebuild, prompt-panel double-tokenization, and the first-mount LLM provider
  scan. This profile is a fresh capture *after* those fixes landed and exposes
  a different set of dominant costs.

## TL;DR

621.5s of 676.2s wall is idle `epoll.poll`. The 187.3s of CPU work is dominated
by **repeated full-widget rendering**, not by the one-shot stalls the May 15
baseline targeted. The biggest *new* findings:

1. **`_ring_tmux_bell` runs `subprocess.run()` synchronously on the UI thread**
   from inside `_poll_agent_completions`. Each fire that actually invokes
   `tmux` blocks the event loop for ~hundreds of ms while waiting on `poll()`.
   Profile shows 0.918s aggregated in `Popen._communicate` from this caller
   alone. This is fully eliminable by running the bell in a worker thread.
2. **`AgentList.render_lines` costs 18.8s** of the 30.3s `_render_chops`
   bucket, and **`AgentInfoPanel.render_lines` adds another 8.1s**. The
   row-content cache (`AgentRenderCache`, `cached_format_agent_option`) is
   working — repaint cost is in Textual's per-strip render of already-built
   `Content`, not in our `format_agent_option`. The repaint is being asked
   for frequently and the *invalidation* is too coarse.
3. **`Compositor.reflow` (5.16s) repeatedly re-asks for
   `AgentPromptPanel.get_content_height` (2.62s)**, which still drives a
   `Syntax._get_syntax` call (~1.1s) even with `_CachedSyntaxRenderable` in
   place — the cache is keyed/scoped in a way that misses across reflow/paint
   passes when the panel is resized or re-arranged.
4. **`_patch_agent_runtime_rows` (0.82s) fires every 1s** via the countdown
   tick and re-renders runtime-suffix rows even when only a tick suffix
   (elapsed-time text) changed. Each tick repaints active rows.
5. **`AgentInfoPanel` content is never cached** (`_update_display` rebuilds
   the Rich `Text` from scratch on every state mutation), so its 8.1s render
   bucket compounds with the auto-refresh / countdown firing rate.
6. **`_save_prompt_history` runs synchronously on the UI thread** at prompt
   bar submit (0.447s in this profile). Routinely blocking ~0.5s on submit
   matches the "feels frozen after I press enter" complaint.
7. **`find_all_changespecs` (0.491s) runs on the UI thread** via
   `_refresh_axe_display` → `get_runner_count` →
   `_runners_data.get_runner_count`. AXE tab updates currently parse every
   ChangeSpec on the event loop.
8. **`PromptTextArea._refresh_xprompt_arg_hint_from_cursor` (0.578s)** is
   invoked synchronously on **every keystroke** from `_on_key`. It calls
   `build_xprompt_assist_entries`, which scans the xprompt catalog
   in-process. This makes the prompt input feel sluggish during typing.
9. **`compute_diff_cache_key` (0.578s) runs on the UI thread** (the worker
   is started *after* the key is computed). Inside it, `get_vcs_provider`
   (0.578s) and `_resolve_vcs_name` (0.422s) walk the workspace each
   selection change.
10. **`AceApp._apply_loaded_agents_prepared` is still ~0.46s** on the UI
    thread per `_load_agents_async` completion. The May 15 baseline noted a
    0.475s version of this same hand-back; the cost has not meaningfully
    moved. Most of it is now `_finalize_agent_list` →
    `_clear_agent_unread_and_dismiss_notification` (0.244s in
    `apply_notification_state_update_counts`).

## Headline Numbers

Across the captured 676.248s:

| Bucket | Wall | Notes |
|---|---:|---|
| `epoll.poll` idle | 621.5s | true event-loop idle |
| `Timer._run_timer` tree (render + ticks) | 42.6s | dominant CPU bucket |
| `Compositor._render_chops` | 30.3s | screen redraws |
| `AgentList.render_lines` | 18.8s | row rendering |
| `AgentInfoPanel.render_lines` | 8.1s | top info panel |
| `Compositor.reflow` | 5.2s | layout, includes Syntax.get_height |
| `AceApp._on_auto_refresh` | 1.77s | every ~10s |
| `_ring_tmux_bell` subprocess | 0.92s | synchronous on UI thread |
| `AceApp._on_countdown_tick` | 1.36s | every 1s |
| `_apply_loaded_agents_prepared` | 0.46s | per agent reload |
| `_refresh_axe_display` | 0.58s | per AXE tick |
| `_refresh_xprompt_arg_hint_from_cursor` | 0.58s | per keystroke aggregate |
| `_save_prompt_history` | 0.45s | per submit |

CPU time ≈ 187.3s ≈ 27.7% of wall time. The user's "slow and unresponsive"
report is consistent with the renderer cost dominating active CPU and several
UI-thread blockers being short but timed to user actions (keystroke, submit,
tab switch, selection change, every 1s tick).

## Captured Hot Paths

### 1. `_ring_tmux_bell` Blocks the UI Thread (NEW)

```text
1.766 AceApp._on_auto_refresh  ace/tui/actions/_event_refresh.py:115
└─ 0.925 AceApp._poll_agent_completions  ace/tui/actions/agents/_notification_polling.py:13
   └─ 0.918 AceApp._ring_tmux_bell  ace/tui/actions/agents/_notification_polling.py:162
      └─ 0.916 subprocess.run  subprocess.py:512
         └─ 0.913 Popen.communicate
            └─ 0.913 PollSelector.select
               └─ 0.913 poll.poll  <built-in>
```

`_poll_agent_completions` itself is dispatched off the main thread, but the
bell call inside it runs `subprocess.run([..., "tmux", "display-message", ...])`
without `asyncio.to_thread` / `run_worker`. The synchronous `tmux` call blocks
the awaiting coroutine — and because `_poll_agent_completions` is awaited from
`_on_auto_refresh`, the entire auto-refresh cycle stalls for the duration of
the bell.

**Fix:** wrap the bell call in `asyncio.to_thread(...)` (or push it onto an
executor / fire-and-forget worker). The tmux side already buffers
`display-message`, so we do not need to await completion before continuing
the auto-refresh pipeline.

**Expected impact:** removes a recurring sub-second hitch every time agents
complete (which fires the bell). Especially noticeable when many agents
complete in a short window.

### 2. AgentList Rendering Dominates the Composite Cost (NEW shape)

```text
30.287 Compositor._render_chops
└─ 27.011 Compositor._get_renders
   ├─ 18.800 AgentList.render_lines
   │  └─ 17.867 StylesCache.render_widget
   │     └─ 15.665 StylesCache.render_line
   │        └─ 12.125 AgentList.render_line
   │           └─ 9.465 AgentList._get_option_render
   │              └─ 7.022 Padding.to_strips
   │                 ├─ 4.346 Padding.render_strips
   │                 └─ ... Strip.apply_*, _apply_link_style, etc.
   └─ 8.112 AgentInfoPanel.render_lines
      └─ 6.422 StylesCache.render
         └─ 4.714 StylesCache.render_line
            └─ 3.211 AgentInfoPanel.render_line
               └─ 3.193 AgentInfoPanel._render_content
                  └─ 3.008 Visual.to_strips
```

Important observation: the time inside `AgentList._get_option_render` is
**inside Textual** (`Padding.to_strips`, `Style.rich_style_with_offset`,
`Strip.apply_*`), not inside our `cached_format_agent_option`. The per-tick
cost inside `build_list` (line 7174 in profile) is only 0.018s. The
expensive part is Textual painting strips from already-built `Content`.

Two compounding reasons:

1. **`StylesCache.render_line` is hitting a cold cache for many lines per
   frame.** Textual caches per-line strips keyed by widget styles and
   geometry; if styles or geometry change every frame (pseudo-classes,
   scrollbar size, focus highlight), the cache misses repeatedly. The
   `AgentList._pseudo_classes_cache_key` lookup itself shows 0.717s — that
   should be near-zero with a stable cache key.
2. **Per-frame styling/`link_style` lookups are not stable.**
   `AgentList.link_style` (1.34s), `AgentList.background_colors` (1.02s),
   and `AgentList.get_visual_style` (0.78s) recompute every render line.
   They walk ancestors, fetch CSS rules, and combine colors. These are
   technically Textual costs but they fire because we ask Textual to
   re-render the whole option list more often than necessary.

**Fix candidates** (ordered by independence):

- Audit what triggers a full `AgentList` refresh. The countdown tick path
  (#5 below) repaints active rows every 1s; investigate whether the *whole*
  list is being invalidated rather than only the rows whose runtime suffix
  changed. `_patch_agent_runtime_rows` already calls `patch_agent_row` per
  row, so the invalidation surface should be small — confirm the row patch
  doesn't end up `refresh()`-ing the whole list.
- Stabilize the `pseudo_classes_cache_key` for `AgentList` so that
  StylesCache hits within a frame even when the highlighted row index
  changes (highlight is a per-line style overlay, not a widget-level
  pseudo-class).
- For `AgentInfoPanel`, see #6 below — the entire rebuilt `Text` invalidates
  the widget's `StylesCache.render` path on every state mutation.

### 3. Prompt-Panel Reflow Still Pays Pygments On Layout Passes

```text
5.158 Compositor.reflow
└─ 5.065 Compositor._arrange_root
   └─ ... add_widget (deep recursion) ...
      └─ 2.671 VerticalScroll.arrange
         └─ 2.643 resolve_box_models
            └─ 2.636 AgentPromptPanel._get_box_model
               └─ 2.617 AgentPromptPanel.get_content_height
                  └─ 2.542 RichVisual.get_height
                     └─ 2.483 Console.render
                        └─ 2.148 Console.render
                           └─ 1.173 _CachedSyntaxRenderable.__rich_console__
                              └─ 1.156 Console.render
                                 └─ 1.128 Syntax.__rich_console__
                                    └─ 1.117 Syntax._get_syntax
```

`_CachedSyntaxRenderable` (introduced as part of P1 in the previous
research) is still calling `Syntax._get_syntax` (the full Pygments lexer)
inside layout. This means the cache it builds is invalidated or scoped
wrong for the reflow code path. Two likely causes:

1. Cache keyed on width/lexer/theme but a `Console` option change between
   sizing and painting causes a miss. Confirm `_CachedSyntaxRenderable`'s
   key matches the sizing console's effective width, options, and theme.
2. The cache lives on the renderable instance, but each reflow constructs
   a fresh `Syntax`/renderable via `lazy_renderable()`.

**Fix:**

- Inspect `src/sase/ace/tui/util/lazy_syntax.py:47-100` and verify
  `_CachedSyntaxRenderable.__rich_console__` writes its segments to a cache
  keyed on `(width, lexer, theme, content_hash)` and reads from it on
  subsequent calls inside the same paint frame.
- If `lazy_renderable()` is invoked at each prompt-panel `update_display`,
  promote the cache one level up so it survives the height-pass / paint
  pass of a single Textual frame.

**Expected impact:** halves the 5.2s reflow bucket (the second 1.156s
`Console.render` inside `get_height` is the duplicate that should hit
cache).

### 4. AXE Tab `find_all_changespecs` Runs on the UI Thread (NEW)

```text
0.576 AceApp._refresh_axe_display  ace/tui/actions/axe_display/_render.py:62
└─ 0.514 get_runner_count  ace/tui/modals/_runners_data.py:436
   └─ 0.491 find_all_changespecs  ace/changespec/__init__.py:140
      └─ 0.418 parse_project_file  ace/changespec/parser.py:291
         └─ 0.417 parse_project_file_python  ace/changespec/parser.py:303
```

The AXE display refresh synchronously parses every `.gp` ChangeSpec file
through `get_runner_count` to compute the AXE tab's counter. The prior
research's P0 already moved the *main* ChangeSpec corpus rebuild off the
UI thread; this is a separate, smaller, but still UI-thread caller using
the same parse path.

**Fix:** cache `get_runner_count` on the already-loaded ChangeSpec list (a
field of the app's ChangeSpec state) rather than re-parsing from disk every
AXE refresh. If the runner count truly needs to walk fresh files, debounce
it and run via `asyncio.to_thread`.

**Expected impact:** removes a recurring ~0.5s stall per AXE tab refresh.

### 5. Countdown Tick Re-renders Active Rows Every 1s (NEW)

```text
1.355 AceApp._on_countdown_tick  ace/tui/actions/_event_activity.py:15
├─ 0.820 AceApp._patch_agent_runtime_rows  ace/tui/actions/agents/_display_panel_patches.py:79
│  └─ 0.802 AgentList.patch_active_runtime_rows  ace/tui/widgets/agent_list.py:374
│     └─ 0.706 AgentList.patch_agent_row  ace/tui/widgets/agent_list.py:347
│        └─ 0.670 patch_row  ace/tui/widgets/_agent_list_build.py:479
└─ 0.523 AceApp._update_agents_info_panel  ace/tui/actions/agents/_display_detail.py:184
   └─ 0.519 AceApp._update_agents_info_panel_impl  ace/tui/actions/agents/_display_detail.py:251
      └─ 0.515 AgentInfoPanel.update_state  ace/tui/widgets/agent_info_panel.py:140
         └─ 0.514 AgentInfoPanel.update  textual/widgets/_static.py:85
            ├─ 0.444 visualize  textual/visual.py:75
            └─ 0.443 Content.from_rich_text  textual/content.py:302
```

The 1-second countdown tick does two things every tick:

1. `patch_active_runtime_rows`: walks active agents and re-renders their row
   suffix (elapsed time). This is the intended optimization (don't repaint
   the whole list), but the cost of `patch_agent_row` itself is non-trivial
   at scale.
2. `_update_agents_info_panel`: rebuilds the top `AgentInfoPanel` fully via
   `Content.from_rich_text(...)`, even if only one tick suffix changed. The
   `AgentInfoPanel` does not memoize per-input fingerprint.

**Fix:**

- Skip `_update_agents_info_panel` on countdown ticks when only the elapsed
  suffix changed — patch only the seconds field in the existing rendered
  `Content` (matching the row-patch strategy in `AgentList`).
- Add an early-out in `update_state`: if `(state_fingerprint, countdown)`
  matches the last applied input, return without rebuilding the `Text`.
- For very large agent counts, batch row patches: only refresh rows whose
  *visible suffix* changed (e.g., when seconds rolled over), not every
  active row every tick.

**Expected impact:** removes both the 0.82s and 0.52s recurring tick costs
on most ticks. The remaining cost (when something actually changed) should
be only the changed rows.

### 6. `AgentInfoPanel` Is Not Cached (NEW shape)

`AgentInfoPanel._update_display` builds a fresh `Rich.Text` every call,
which then drives an 8.1s aggregate render bucket because the widget's
`StylesCache.render` re-tokenizes a new `Visual` each time `update()` is
called.

```text
8.112 AgentInfoPanel.render_lines
└─ 8.094 StylesCache.render_widget
   └─ 6.422 StylesCache.render
      └─ 4.714 StylesCache.render_line
         └─ 3.211 AgentInfoPanel.render_line
            └─ 3.193 AgentInfoPanel._render_content
               └─ 3.008 Visual.to_strips
                  └─ 1.489 RichVisual.render_strips
                     └─ 1.334 Segment.split_and_crop_lines
                        └─ 1.192 Console.render
                           └─ 1.093 <genexpr>  textual/widget.py:199
```

Even the work inside `_render_content` (3.2s) is split across multiple
`Console.render` calls per repaint cycle. Without an input-fingerprinted
content cache on `AgentInfoPanel`, the panel pays a full render each tick
even when nothing visible changed.

**Fix:**

- Add a `(highlighted_agent_id, mode, countdown_minute, agent_state_hash)`
  fingerprint and early-return from `update_state` when unchanged.
- Cache the built `Text` per fingerprint; only rebuild when the fingerprint
  changes.
- Consider whether the countdown granularity actually requires per-second
  refresh of this panel; many headers refresh on a coarser cadence.

**Expected impact:** drops the 8.1s render bucket roughly in proportion to
how many ticks pass without state change. For an idle minute, this is a
near-complete elimination of `AgentInfoPanel` cost.

### 7. `_save_prompt_history` Runs on the UI Thread at Submit (NEW)

```text
0.819 AceApp._on_message
└─ 0.741 invoke
   └─ 0.592 AceApp.on_prompt_input_bar_submitted  ace/tui/actions/agent_workflow/_prompt_bar_submit.py:23
      └─ 0.591 AceApp._unmount_prompt_bar  ace/tui/actions/agent_workflow/_prompt_bar_mount.py:152
         └─ 0.589 AceApp._save_bar_text_as_cancelled  ace/tui/actions/agent_workflow/_prompt_bar_mount.py:105
            └─ 0.585 _apply_prompt_mutations  history/prompt.py:280
               └─ 0.447 _save_prompt_history  history/prompt.py:162
```

The submit path (and the cancel path that shares it) writes prompt history
JSON synchronously. ~0.4s on prompt bar dismissal/submit is a noticeable
"freeze" right when the user wants to see the launched agent appear.

**Fix:**

- Move `_save_prompt_history` to `asyncio.to_thread(...)` / `run_worker` —
  the prompt history file is append-only from the user's perspective and
  doesn't need to be on disk before the agent launches.
- If the launch action needs the persisted file before continuing, split
  the write into a fast metadata write (small) and the body write (large)
  and only block on the small one.

**Expected impact:** removes the ~0.45s freeze on prompt submit/cancel.

### 8. `_refresh_xprompt_arg_hint_from_cursor` Runs on Every Keystroke (NEW)

```text
2.057 PromptTextArea._dispatch_message
└─ 1.390 PromptTextArea.on_event
   └─ ... PromptTextArea._on_key ...
      └─ 0.583 PromptTextArea._refresh_xprompt_arg_hint_from_cursor  ace/tui/widgets/prompt_text_area.py:393
         └─ 0.578 PromptTextArea._get_xprompt_arg_assist_entries  ace/tui/widgets/prompt_text_area.py:426
            └─ 0.577 build_xprompt_assist_entries  ace/tui/widgets/xprompt_arg_assist.py:94
```

The xprompt argument hint is recomputed on **every** keystroke (the call
sits in `_on_key`). Aggregate cost is small per keystroke but compounds
into a noticeable typing-feel hitch when the user types a long prompt.

**Fix:**

- Debounce the hint refresh by 50–100ms — typing at human speed will skip
  most intermediate computations.
- Only invoke `build_xprompt_assist_entries` when the cursor is in an
  xprompt-eligible position (after `#name `) — exit cheaply otherwise.
- Cache `build_xprompt_assist_entries` output per xprompt name; the
  catalog rarely changes during a session.

**Expected impact:** the cost falls roughly to zero between keystrokes; the
prompt input should feel "snappy" instead of "buffering."

### 9. `compute_diff_cache_key` Runs on the UI Thread (NEW)

```text
0.801 AgentFilePanel.update_display
└─ 0.800 AgentFilePanel._update_display_body
   └─ 0.797 AgentFilePanel._start_background_fetch
      └─ 0.796 compute_diff_cache_key  ace/tui/widgets/file_panel/_diff.py:72
         └─ 0.578 get_vcs_provider  vcs_provider/_registry.py:184
            └─ 0.422 _resolve_vcs_name  vcs_provider/_registry.py:153
```

`_start_background_fetch` runs the *fetch* in a worker, but the key it
uses to dedupe fetches is itself computed on the UI thread. The
expensive sub-step is `_resolve_vcs_name`, which scans the workspace for
VCS providers each selection change.

**Fix:**

- Cache `get_vcs_provider(workspace_root)` per process — provider identity
  for a workspace doesn't change during a session.
- Move `compute_diff_cache_key` into the worker. The dedupe check can
  happen inside the worker before doing the diff work.

**Expected impact:** removes a ~0.5s stall on every agent-selection change
that triggers a file-panel refresh.

### 10. `_apply_loaded_agents_prepared` Still Blocks the UI Thread

```text
0.593 AceApp._load_agents_async
└─ 0.456 AceApp._apply_loaded_agents_prepared
   └─ 0.455 _apply_loaded_agents_prepared_inner
      └─ 0.417 _finalize_agent_list
         └─ 0.417 finalize_agent_list
            └─ 0.417 _apply_finalize_plan
               ├─ 0.244 _sync_unread_completed_agents
               │  └─ 0.244 _clear_agent_unread_and_dismiss_notification
               │     ├─ 0.147 dismiss_notifications_matching_agents
               │     │  └─ 0.147 apply_notification_state_update_counts  (Rust)
               │     └─ 0.097 _refresh_notification_count
               └─ 0.167 _refresh_agents_display
                  └─ 0.122 AgentList.update_list (build_list)
```

The May 15 baseline noted a 0.475s `_finalize_agent_list` cost. This
profile still shows ~0.46s in the same UI-thread hand-back, now dominated
by:

1. `apply_notification_state_update_counts` Rust call (0.147s). This is
   pure CPU and could run in the worker that just loaded the agents.
2. `_refresh_notification_count` (0.097s) — also pure CPU + Rust.
3. `AgentList.update_list` rebuild (0.122s) — same row-rebuild cost the
   prior research called out.

**Fix:** in `_load_agents_async`, after the disk scan, also run the
notification reconciliation and the row-content preparation in the worker
thread. The UI thread should only install pre-built rows and dispatch
refresh.

**Expected impact:** halves the ~0.46s hitch per agent reload tick.

## Recommended Fix Plan

### P0 — Stop blocking on `tmux` subprocess

`_ring_tmux_bell` → `asyncio.to_thread(subprocess.run, ...)`, or use
`asyncio.create_subprocess_exec` with a fire-and-forget pattern.
Smallest-surface fix, eliminates a recurring sub-second UI freeze.

### P0 — Cache `AgentInfoPanel` and gate countdown updates

Fingerprint the inputs, early-return when unchanged, and re-evaluate
whether the panel needs a per-second refresh. Eliminates the 8.1s render
bucket on idle ticks.

### P0 — Move `_save_prompt_history` off the UI thread

`asyncio.to_thread` the JSON write. Removes a ~0.45s freeze on every
prompt bar submit/cancel.

### P1 — Debounce + scope `_refresh_xprompt_arg_hint_from_cursor`

Debounce 50–100ms; bail early when the cursor is not in an xprompt
context; cache catalog scans. Removes the typing-feel hitch.

### P1 — Move `compute_diff_cache_key` + cache `get_vcs_provider`

Resolve VCS once per workspace per process. Push the cache-key computation
into the worker. Removes the per-selection-change ~0.5s stall on file
panel refresh.

### P1 — Stop fully rebuilding `AgentList` rows on countdown ticks

Audit `_patch_agent_runtime_rows` to confirm the per-row patch path does
not call into `AgentList.refresh()` or invalidate `StylesCache`. If it
does, switch to a strip-level patch.

### P1 — `_apply_loaded_agents_prepared` should run notification reconcile in the worker

Move `dismiss_notifications_matching_agents` and
`_refresh_notification_count` into the worker that loaded agents. Have
the UI-thread continuation only install the prepared display state.

### P1 — Stop re-parsing ChangeSpecs in `_refresh_axe_display`

Reuse the already-loaded ChangeSpec state for `get_runner_count`, or
defer to a worker. Removes the ~0.5s AXE-tab refresh stall.

### P2 — Fix `_CachedSyntaxRenderable` cache scope

Verify the cache survives the reflow→paint pair within a single frame.
Either widen the key, hoist the cache one level, or memoize the segments
on a per-`AgentPromptPanel` selection identity.

## Verification Strategy

1. **Re-run `sase ace --profile`** with the same interaction. Success
   criteria for P0:
   - `Popen._communicate` from `_ring_tmux_bell` no longer appears in the
     UI-thread tree.
   - `AgentInfoPanel.render_lines` aggregate < 1.0s over a similar 10-min
     session.
   - `_save_prompt_history` no longer appears under
     `on_prompt_input_bar_submitted`.
2. **Targeted Textual benchmark** for keystroke latency in `PromptTextArea`
   (`SASE_TUI_PERF=1`). Measure 95p time between key event and prompt body
   repaint. Target: < 5ms with the debounce P1 fix.
3. **Microbenchmark `get_vcs_provider` cache hit rate.** Run a synthetic
   selection sweep; cache hit rate should be ≥ 99% after the cache fix.
4. **Add a `tests/ace/responsiveness/test_no_subprocess_run_on_ui.py`**
   guard that asserts none of `_ring_tmux_bell`, `_save_prompt_history`,
   or `compute_diff_cache_key` call blocking I/O from the asyncio loop
   thread. Use `inspect`/`tracemalloc`-style monkeypatches.

## Profiling Caveats

- pyinstrument samples at 1ms; sub-1% items in this profile are below the
  measurement floor. Treat hits < 0.05s aggregate with skepticism.
- This is one ~11-minute session. The interaction pattern shapes which
  hot paths surface. The previous May 15 capture (51.86s) under-counted
  countdown-tick costs because the session was too short to accumulate
  60+ ticks; this capture surfaces them clearly.
- `epoll.poll` time (621.5s) is not "wasted" — it is the loop sleeping
  while no work is queued. Don't optimize it directly; optimize the
  paths that *cause* a wake-up.

## Open Questions

- Why does `AgentList.link_style` cost 1.34s aggregate? It walks ancestors
  on each call; could it be memoized per frame?
- Is the `_CachedSyntaxRenderable` cache scoped to a single
  `_get_syntax` call or to the renderable's lifetime? The 1.17s
  `_CachedSyntaxRenderable.__rich_console__` block in the reflow tree
  suggests the cache is missing one of the two reflow→paint passes.
- Does `_on_countdown_tick` need to fire every 1s, or is 2–5s acceptable
  for the user-visible elapsed text? Halving the tick rate roughly halves
  the panel-render cost without code changes.
- For the tmux bell: is the bell still needed for every completion, or
  can we coalesce within a window to avoid both the freeze and the
  notification noise?

## Cross-References

- Prior baseline + Phase 6 verification:
  `sdd/research/202605/ace_profile_20260515_responsiveness.md`
- Earlier startup work:
  `sdd/research/202605/ace_startup_profile_20260502.md`
- TUI blocking audit playbook:
  `sdd/research/202605/tui_blocking_audit.md`
