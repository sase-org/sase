# `sase ace` Startup Profile Review (2026-05-02)

## Source

- Profile artifact: `/home/bryan/tmp/sase/ace_profile_20260502_130540.txt`
- Tool: pyinstrument v5.1.2
- Recorded: 13:05:34, **duration: 6.583s**, **CPU time: 6.758s**, samples: 2394
- Profile root: `src/sase/main/ace_handler.py:39`

Important boundary: this profile starts after `handle_ace_command()` has already imported `AceApp`
(`src/sase/main/ace_handler.py:14`) and after argparse dispatch. It does **not** include Python
process startup, parser construction, or the heavy `from sase.ace.tui import AceApp` import graph.

## TL;DR

The earlier read was directionally right that the profile is not "4s of one synchronous main-thread
startup function", but it missed the biggest hidden wall-clock bucket: **post-first-paint agent
loading runs through `asyncio.to_thread(...)`, so pyinstrument mostly shows the UI loop waiting in
`epoll.poll` while the worker thread scans agents and dismissed bundles.**

On this machine, a targeted cold-process probe of the worker path took **3.28s**:

```
dismissed=8725 load_dismissed=0.008s load_agents=3.281s agents=2413 dismissed_from_loader=8223
```

A pyinstrument probe around `load_agents_from_disk()` attributed that time to:

| Worker path | Time | Meaning |
| --- | ---: | --- |
| `AgentSnapshotCache.dismissed_bundles()` / `load_dismissed_bundles()` | 2.03s | Loads **8,223** dismissed bundle JSON files from `~/.sase/dismissed_bundles` (37M total). |
| `load_all_agents()` | 2.02s | Scans and hydrates the active/completed agent corpus. |
| `scan_agent_artifacts()` Rust call + Python wire hydration | 1.21s | Walks `~/.sase/projects/*/artifacts`; Python wire object construction is 0.26s of that. |
| Workflow-step hydration | 0.45s | Builds workflow step agents and enriches them from meta JSON. |

That explains a large part of the perceived ~4s startup: the visible TUI can paint quickly, but the
footer startup stopwatch and empty/loading agent/axe panels do not settle until the async startup
loads complete. The profile's 3.156s `epoll.poll` bucket is therefore not necessarily harmless user
idle; it can include event-loop wait time while worker-thread disk and Rust work is running.

## Top-level branches in the captured profile

| Branch | Time | What it is |
| --- | ---: | --- |
| `AceApp.run` | 6.408s | Entire Textual lifecycle after `AceApp` was imported and constructed. |
| `AceApp.__init__` | 0.146s | App state construction, config load, dismissed-agent index load. |
| `detect_graphics_capability` | 0.028s | Kitty graphics probe before Textual owns stdin. |

Inside `AceApp.run`:

| Branch | Time | Updated interpretation |
| --- | ---: | --- |
| `EpollSelector.select` / `epoll.poll` | 3.156s | Event-loop wait. Some may be real idle, but this is also where `await asyncio.to_thread(...)` gaps disappear from the main-thread tree. |
| `Timer._tick` / rendering | 2.207s | Repeated Textual refresh work while the app is open. |
| `AceApp.run_async` startup/message processing | 0.729s | Main-thread mount, compose, idle callbacks, quit handling, and UI-thread finalization. |

## Phase 0 - Cost missing from this profile

The pyinstrument timer starts at `ace_handler.py:39`, after these costs have already happened:

- argparse/parser dispatch;
- `from sase.ace.tui import AceApp`;
- `from sase.config.core import set_include_local_config`;
- the `QueryParseError` import at module import time.

Local cold-process probes in this workspace:

```
parser ace args 0.118s
import AceApp 0.568s
```

So the full user-visible command path can plausibly pay another ~0.7s before this profile even
starts. The sibling research note `sdd/research/202605/startup_time.md` already covers parser/import
startup in more detail; this file should be read as "inside the TUI handler after `AceApp` is
imported", not total shell-to-useful-state startup.

## Phase 1 - `AceApp.__init__` (0.146s captured)

```
0.146 AceApp.__init__              ace/tui/app.py:175
├─ 0.138 AceApp._init_app_state    ace/tui/actions/_state_init.py:38
│  ├─ 0.065 load_merged_config     config/core.py:361
│  │  ├─ 0.034 _load_default_config (yaml.safe_load)
│  │  └─ 0.021 _load_yaml_file      (user config)
│  ├─ 0.034 load_dismissed_agents  ace/dismissed_agents.py:84
│  ├─ 0.001 parse_query            (Rust binding import)
│  └─ 0.001 build_app_bindings
└─ 0.008 textual.App.__init__
```

The YAML cost is real but not dominant. `src/sase/default_config.yml` is 15.6KB and
`~/.config/sase/sase.yml` is 3.3KB in this environment; PyYAML's pure-Python `safe_load` accounts
for most of the 65ms config load. `load_dismissed_agents()` reads a 518KB
`~/.sase/dismissed_agents.json` with 8,725 entries and hydrates `AgentType` enums.

## Phase 2 - Mount and first ChangeSpec view (0.131s captured)

```
0.131 AceApp.on_mount              ace/tui/actions/startup.py:104
├─ 0.101 AceApp._apply_changespecs
│  └─ 0.097 _filter_changespecs_impl
│     ├─ 0.091 _get_query_corpus_for_changespecs
│     │  └─ 0.091 compile_query_corpus
│     │     ├─ 0.040 to_json_dict -> dataclasses.asdict
│     │     ├─ 0.030 compile_corpus  <built-in Rust>
│     │     └─ 0.018 changespec_to_wire
│     ├─ 0.004 build_query_context
│     └─ 0.001 lazy module import
├─ 0.017 watch_current_tab CSS update cascade
├─ 0.006 startup saved-query fallback filter pass
└─ 0.005 loading-indicator state
```

This path filters 1,986 ChangeSpecs in the local corpus. The expensive part is not query evaluation;
it is building the Rust corpus input through Python dataclass/wire conversion. The code already
caches the corpus by list identity (`_get_query_corpus_for_changespecs()`), so the startup hit is a
first-build cost.

## Phase 3 - Post-first-paint async loads (hidden wall time)

`on_mount()` deliberately defers heavier work with `call_after_refresh()`:

- `_start_post_mount_background_loads()` schedules `_run_agents_async_refresh()`;
- `_run_agents_async_refresh()` calls `_load_agents_async()`;
- `_load_agents_async()` awaits `asyncio.to_thread(find_all_changespecs_cached)`,
  `asyncio.to_thread(load_agents_from_disk)`, cleanup, and prepared filtering.

The main pyinstrument capture only shows the UI-thread apply/finalize after the awaits:

```
0.015 _run_agents_async_refresh
└─ 0.014 finalize_agent_list
   ├─ 0.005 _refresh_agents_display
   ├─ 0.005 filter_agents_by_fold_state
   └─ 0.003 get_or_parse_agent_query
```

That 15ms is misleading if used as the total agent-load cost. A direct profile of the worker path
found ~4.1s wall in a cold process, dominated by dismissed bundles and artifact scanning. This is the
strongest current explanation for the user's ~4s startup perception.

Data size in this environment:

- `~/.sase/dismissed_bundles`: 8,223 JSON files, 37M total.
- `~/.sase/dismissed_agents.json`: 8,725 identities, 518KB.
- `~/.sase/projects`: 20 project dirs, 18 artifact dirs, 1,426 `done.json` files.
- Loaded agent corpus: 2,413 agents.

## Phase 4 - Running-app rendering (2.207s captured)

The profile still shows a substantial repeated render bill:

```
2.207 Timer._run_timer
└─ 2.202 Timer._tick
   └─ 2.162 Screen._on_timer_update
      ├─ 1.133 Screen._refresh_layout
      │  └─ 0.651 Compositor.render_update
      │     └─ 0.573 AgentPromptPanel.render_lines
      │        └─ Rich Console.render -> Syntax.__rich_console__
      │           └─ Syntax._get_syntax / Pygments MarkdownLexer
      └─ 0.105 AceApp._display
```

The current prompt-panel code uses `lazy_renderable()` to cap syntax highlighting for large content,
but for content below the cap it still creates Rich `Syntax` renderables and Textual may ask Rich to
render them repeatedly. In this capture, `Syntax._get_syntax` and `MarkdownLexer` remain hot. This is
less likely to be the initial 4s wall-clock cause than agent loading, but it explains why the TUI can
feel busy or sluggish immediately after launch.

## Phase 5 - Other captured costs

- `_on_compose` widget cascade: 0.050s. Mostly Textual message-pump/register overhead amplified by
  the deep layout tree in `AceApp.compose()`.
- `_start_artifact_watcher`: 0.034s. It scans project dirs and calls `ArtifactWatcher.start()`;
  `_libc()` invokes `ctypes.util.find_library("c")`, which shells out to `ldconfig` for 5ms.
- `detect_graphics_capability`: 0.028s. The active Kitty probe waits on stdin `select`; 20ms is the
  drain timeout.
- Quit path: 0.259s in `ArtifactWatcher.stop()` -> `Thread.join(timeout=1.0)`. This affects slow
  exit, not slow startup. The worker loop uses a 0.5s idle `select` timeout; closing the fd usually
  wakes it, but this capture still waited 259ms.

## Leading Causes - Updated Ranking

1. **Async agent-load wall time hidden under event-loop wait** (~3-4s): `load_agents_from_disk()`
   loads thousands of dismissed bundles and scans/hydrates the artifact corpus. This is the biggest
   likely cause of the user's perceived startup delay.
2. **Pre-profile import and parser cost** (~0.7s local probe): `AceApp` import and argparse happen
   before this pyinstrument profile starts, so they must be included in any shell-to-usable timing.
3. **Per-frame Rich/Pygments rendering** (2.2s cumulative while the app is open): especially
   `AgentPromptPanel` markdown syntax rendering through Rich `Syntax`.
4. **ChangeSpec query-corpus first build** (0.091s): Python dataclass/wire conversion is more
   expensive than the Rust corpus compile itself.
5. **Config and dismissed-agent index load in `__init__`** (0.099s combined): PyYAML plus a large
   dismissed index.
6. **Graphics probe and watcher setup** (0.062s combined): small, but deterministic and easy to
   reduce.
7. **Quit-time watcher join** (0.259s): not startup, but visible as slow shutdown.

## Suggested Next Steps

- Add a startup trace that records wall-clock milestones: process entry, parser complete, `AceApp`
  import complete, `AceApp.__init__`, first paint, agents load done, axe load done, startup
  stopwatch end. The current pyinstrument profile cannot answer that timeline by itself.
- Re-profile `load_agents_from_disk()` in-process after a warm first call. If dismissed-bundle caching
  makes refreshes fast but cold startup remains slow, prioritize a persistent bundle index or lazy
  loading only bundles needed for visible/revivable rows.
- Avoid loading all 8K dismissed bundle JSON files on cold startup. The identity index should be
  enough for hiding; full bundle hydration can be deferred until revive/cleanup UI needs it.
- Keep the Rust artifact scanner, but reduce Python wire hydration cost (`agent_scan_wire_from_dict`)
  or return a lighter summary for the startup list.
- Push ChangeSpec query-corpus construction farther into Rust or avoid `dataclasses.asdict()` in
  `compile_query_corpus()`.
- Cache or pre-render prompt-panel syntax output by content hash and width, invalidating only when
  the selected agent content changes.
- Use `yaml.CSafeLoader` when available for config parsing.
- Cache `ctypes.util.find_library("c")` at module scope, and make `ArtifactWatcher.stop()` wake the
  worker more reliably so shutdown does not wait on the 0.5s select loop.

## Caveats

- pyinstrument is statistical; sub-millisecond details are noise.
- The main profile is a full TUI session that ends when the user presses quit. It mixes startup,
  post-first-paint loading, steady rendering, idle waiting, and shutdown.
- The worker-path timings above were local probes run after reading the code, not part of the
  original profile artifact. Treat them as strong supporting evidence, not a replacement for a
  single end-to-end trace with explicit startup milestones.
