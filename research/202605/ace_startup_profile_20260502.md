# `sase ace` Startup Profile Review (2026-05-02)

## Source

- Profile artifact: `~/.sase/home/tmp/sase/ace_profile_20260502_130540.txt`
- Tool: pyinstrument v5.1.2
- Recorded: 13:05:34, **Duration: 6.583s**, **CPU time: 6.758s**, samples: 2394
- Profile root: `src/sase/main/ace_handler.py:39` (entire `handle_ace_command` invocation)

## TL;DR

The profile **does not show 4s of CPU-bound startup work**. True synchronous startup CPU work is
roughly **0.7–1.0s**; the rest of the 6.4s is the running TUI sitting idle on `epoll` (3.16s) and
re-rendering on every timer tick (2.2s) until the user pressed a key that fired `action_quit` (0.26s).

If the user perceives "~4s before the app is usable," the culprit is **not** a single hot path but the
combination of several modest costs that all happen serially before the first interactive frame:

1. Initial `AceApp.__init__` config + state loading (~0.15s)
2. `on_mount` filtering changespecs through the Rust query corpus (~0.13s)
3. Widget compose cascade (~0.05s)
4. Repeated, heavy panel re-renders driven by `Syntax`/Pygments markdown highlighting after mount

Below is the breakdown by phase.

## Top-level branches under `handle_ace_command` (6.582s)

| Branch                          | Time   | What it is                                                                       |
| ------------------------------- | ------ | -------------------------------------------------------------------------------- |
| `AceApp.run`                    | 6.408s | Whole textual app lifecycle (event loop + first frame + idle + quit).            |
| `AceApp.__init__`               | 0.146s | Construct app object; load config + state before the loop starts.                |
| `detect_graphics_capability`    | 0.028s | Kitty graphics terminal probe (`select` on stdin for ~28ms).                     |

Inside `AceApp.run` (6.408s), the asyncio loop's `_run_once` splits into:

| Inside event loop               | Time   | Meaning                                                                          |
| ------------------------------- | ------ | -------------------------------------------------------------------------------- |
| `EpollSelector.select` / `epoll.poll` | **3.156s** | **Idle wait** for input — not actual work.                                |
| `Handle._run` (timer ticks etc.)| 3.250s | Cumulative timer-driven callbacks during the running app.                        |
| `run_app` / `AceApp.run_async`  | 0.729s | The startup-critical async setup (mount, compose, post-mount hooks).             |

So real CPU work attributable to "startup" lives in the 0.729s `run_app` branch plus the 0.146s
`__init__` outside it. The 3.156s `epoll.poll` and most of the 3.250s timer-ticks are **post-startup
running-app cost**, not synchronous boot.

## Phase 1 — `AceApp.__init__` (0.146s, before event loop)

```
0.146 AceApp.__init__              ace/tui/app.py:175
├─ 0.138 AceApp._init_app_state    ace/tui/actions/_state_init.py:38
│  ├─ 0.065 load_merged_config     config/core.py:361
│  │  ├─ 0.034 _load_default_config (yaml.safe_load)   ← default_config.yml parsing
│  │  ├─ 0.021 _load_yaml_file     (second YAML file)
│  │  └─ ~0.010 other YAML/merge work
│  ├─ 0.034 load_dismissed_agents  ace/dismissed_agents.py:84
│  │  ├─ 0.017 json.loads
│  │  ├─ 0.006 [self]
│  │  └─ 0.004 AgentType.__call__  (enum hydration on each entry)
│  ├─ 0.001 parse_query            (cold-imports sase_core_rs the first time)
│  └─ 0.001 build_app_bindings
└─ 0.008 textual.App.__init__      (driver import + CSS variable generation)
```

Headline: **PyYAML is the single largest cost** in the constructor — ~0.055s split across two YAML
files via `safe_load` (the pure-Python `SafeLoader.compose_*` chain dominates the trace).

## Phase 2 — `on_mount` (0.131s, first thing inside the running app)

```
0.131 AceApp.on_mount              ace/tui/actions/startup.py:104
├─ 0.101 AceApp._apply_changespecs  ace/tui/actions/changespec/_loading.py:49
│  └─ 0.097 AceApp._filter_changespecs_impl
│     ├─ 0.091 AceApp._get_query_corpus_for_changespecs
│     │  └─ 0.091 compile_query_corpus  core/query_corpus_facade.py:41
│     │     ├─ 0.040 to_json_dict (dataclasses.asdict over every spec)
│     │     ├─ 0.030 compile_corpus  <built-in>      ← Rust call
│     │     └─ 0.018 changespec_to_wire (per-spec wire conversion)
│     ├─ 0.004 build_query_context
│     └─ 0.001 module import (lazy-ish)
├─ 0.017 reactive.__set__ → watch_current_tab → CSS update_styles cascade
├─ 0.006 _try_startup_fallback_async (a second `_filter_changespecs_impl` pass)
├─ 0.005 _apply_startup_loading_state (LoadingIndicator stylesheet apply)
└─ 0.001 write_tui_pid + query_one
```

Headline: changespec query-corpus compilation is the heaviest single mount step. Within that,
`dataclasses.asdict` over every changespec (0.040s) is pure Python overhead being paid right before
the same data is handed to a Rust `compile_corpus` (0.030s) — a candidate for skipping Python
serialization and constructing the wire form once.

## Phase 3 — `_on_compose` widget cascade (0.050s)

```
0.050 AceApp._on_compose
└─ 0.046 AceApp.mount_all → Screen.mount → AceApp._register
   └─ 0.040 Horizontal._on_compose → … → recursive Horizontal/Vertical/AgentDetail _on_compose
```

A deeply-nested compose tree (Horizontal → Horizontal → Vertical → AgentDetail → Vertical → …) where
each level pays for `_start_messages` / `create_task` / message-pump setup. This is mostly textual
internals, but the depth of nesting amplifies per-widget overhead.

## Phase 4 — post-mount background loads (0.036s)

```
0.036 AceApp._start_post_mount_background_loads  ace/tui/actions/startup.py:242
├─ 0.034 AceApp._start_artifact_watcher  → ArtifactWatcher.start
│  ├─ 0.025 [self]  ace/tui/util/fs_watcher.py
│  ├─ 0.005 _libc → ctypes.util.find_library  (subprocess to ldconfig!)
│  ├─ 0.002 Thread.start (waits on Event)
│  └─ 0.001 PosixPath.exists
└─ 0.002 AceApp.run_worker (axe status loader spawn)
```

Headline: `ArtifactWatcher.start` runs `ctypes.util.find_library` which `Popen`s `ldconfig` (5ms
just to locate `libc`). Cheap, but easy to cache.

## Phase 5 — first agent-list refresh (0.015s, on a worker)

```
0.015 AceApp._run_agents_async_refresh  ace/tui/actions/agents/_loading.py:399
└─ 0.014 finalize_agent_list  ace/tui/actions/agents/_loading_finalize.py:71
   ├─ 0.005 _refresh_agents_display → AgentList styles cascade
   ├─ 0.005 filter_agents_by_fold_state
   └─ 0.003 get_or_parse_agent_query (cold-imports ace/agent_query/* modules)
```

Off the main thread, but still part of "time until first useful frame".

## Phase 6 — running-app rendering (the 2.2s Timer._tick branch)

This is **not** startup, but it's where most of the visible 6.4s sits and it likely contributes to a
"sluggish startup feel":

```
2.207 Timer._run_timer
└─ 2.202 Timer._tick
   └─ 2.201 invoke → _invoke
      └─ 2.162 Screen._on_timer_update
         ├─ 1.133 Screen._refresh_layout
         │  └─ 0.671 Screen._compositor_refresh
         │     └─ 0.651 Compositor.render_update
         │        └─ ~0.65 Compositor._render_chops / _get_renders
         │           └─ 0.573 AgentPromptPanel.render_lines
         │              └─ Rich Console.render → Syntax.__rich_console__
         │                 └─ Syntax._get_syntax / Pygments MarkdownLexer
```

Headline: every refresh cycle re-renders the `AgentPromptPanel` through Rich's `Syntax` /
Pygments Markdown lexer (`MarkdownLexer.get_tokens_unprocessed` ate 0.081s in one tick window;
`Syntax._get_syntax` 0.270s cumulative). Combined with another ~0.105s/tick going through
`AceApp._display` → ANSI segment emission, the app pays a substantial render bill on every redraw.
Caching the highlighted `Segments` (e.g. via the existing `lazy_renderable`/`AgentArtifactCache`
plumbing) or invalidating only on real content change would cut this dramatically.

## Phase 7 — quit (0.259s)

```
0.259 AceApp.action_quit → AceApp._do_quit → AceApp._stop_artifact_watcher
└─ 0.259 ArtifactWatcher.stop → Thread.join → _ThreadHandle.join
```

The artifact-watcher background thread takes 0.26s to drain on shutdown — perceived as slow exit,
not slow startup. Likely a poll-interval / `select` timeout in `fs_watcher.py:162` that could be
woken via a self-pipe or shorter timeout.

## Leading causes — ranked

1. **Per-frame Rich/Pygments syntax rendering of `AgentPromptPanel`** (~0.5s/tick × many ticks = the
   2.2s `Timer._tick` cost). Biggest perf lever for "feels sluggish after launch."
2. **Changespec query-corpus compilation in `on_mount`** (0.091s) — `dataclasses.asdict` (0.040s)
   plus `changespec_to_wire` (0.018s) before the Rust `compile_corpus` (0.030s).
3. **YAML config loading in `__init__`** (0.055s) — pure-Python `SafeLoader` over two files;
   candidates: cached parse, `CSafeLoader` if libyaml is available, or moving to JSON/TOML.
4. **`load_dismissed_agents` JSON + enum hydration** (0.034s).
5. **`ArtifactWatcher.start` invoking `ldconfig` via ctypes** (0.005s) and **0.259s blocking
   `Thread.join` on quit** — small, but trivially fixable.
6. **Deeply nested `_on_compose` widget tree** (0.050s) — bounded by the layout itself, but worth
   noting the recursion depth.
7. **`detect_graphics_capability` kitty probe** (0.028s on stdin `select`) — runs unconditionally
   pre-loop.

## Caveats

- pyinstrument is a **statistical sampler**; sub-millisecond figures are noise. Trends matter, exact
  values do not.
- The 6.4s wall-clock is dominated by `epoll.poll` (3.16s **idle**) and `Timer._tick` rendering
  (2.2s), neither of which is "startup". A separate measurement should bound the time from
  `handle_ace_command` entry until the first frame is presented (e.g. by stopping pyinstrument in
  `on_ready` / first `_compositor_refresh`).
- Synchronous startup CPU is ~0.32s (`__init__` 0.146s + `on_mount` 0.131s + `_on_compose` 0.050s
  + graphics probe 0.028s + post-mount kicks 0.036s, with overlap). The remaining "feels like 4s"
  is most plausibly the agent-list async loader + repeated heavy panel re-renders before the UI
  settles.

## Suggested next steps (research-only, not actioned)

- Re-profile with the sampler stopped at first paint to isolate startup from runtime cost.
- Memoize the highlighted `Segments` for the active agent prompt; invalidate on content hash change.
- Skip `dataclasses.asdict` in `compile_query_corpus` — convert directly to the Rust wire form, or
  push the corpus build into Rust.
- Try `yaml.CSafeLoader` (libyaml) for `_load_default_config` / `_load_yaml_file`; falls back
  cleanly when libyaml is missing.
- Cache `ctypes.util.find_library("c")` result at module scope in `fs_watcher.py`.
- Make `ArtifactWatcher.stop` interrupt its select loop via a self-pipe so `Thread.join` returns
  promptly.
