I could not literally `git clone` the repo in the sandbox because DNS resolution for `github.com` failed, but I pulled
the relevant source through GitHub’s web/raw surface and built a partial local checkout for static analysis. I did
**not** run `sase ace` against real `.sase` data, so these are source-level findings, not measured flamegraph results.

## Executive summary

The TUI already has several smart performance protections: `sase ace` launches an `AceApp`, the app supports profiling,
startup work is partly asynchronous, navigation has a 250 ms idle gate, detail updates are debounced, artifact file
events are coalesced, and file/thinking panels already use background workers and caches. ([GitHub][1])

The biggest remaining opportunities are:

1. **Make j/k navigation truly cheap** by avoiding full ChangeSpec list rebuilds after every debounced selection change.
2. **Cache parsed ChangeSpecs and query evaluation data** instead of reparsing every project/archive file and rebuilding
   searchable text.
3. **Add O(1) indexes for agent panel/highlight operations** and row lookups.
4. **Make agent loading incremental** instead of rescanning ChangeSpecs, artifact dirs, attempt history, retry state,
   and dismissed bundles on every refresh.
5. **Cache or defer expensive Rich rendering**, especially Markdown `Syntax`, diffs, live replies, and AXE ANSI output.
6. **Use the file watcher to reduce periodic polling work**, rather than doing broad disk scans on every auto-refresh.

Below is an implementation-ready backlog another agent can pick up.

---

# P0 — Add tracing before changing behavior

### 1. Add a `SASE_TUI_TRACE=1` phase timer

The code already has key-to-paint instrumentation through `JKPerfTimer` and a `--profile` path in the ACE handler. Use
that as the base, but add scoped spans around the actual hot functions. ([GitHub][1])

**Implement in:** `src/sase/ace/tui/util/perf.py` or a new `util/trace.py`.

Add a lightweight context manager:

```python
with tui_trace("changespec.refresh_display", count=len(self.changespecs)):
    ...
```

Log JSONL to:

```text
~/.sase/perf/tui_trace.jsonl
```

Include:

```text
timestamp
span_name
duration_ms
current_tab
current_idx
counts: changespecs, agents, panels, options, bytes_read, syntax_blocks
```

**Add spans around:**

- `ChangeSpecDisplayMixin._refresh_display`
- `ChangeSpecList.update_list`
- `ChangeSpecDetail.update_display`
- `AncestorsChildrenPanel.update_relationships`
- `_filter_changespecs`
- `evaluate_query`
- `load_agents_from_disk`
- `AgentList.update_list`
- `AgentList.update_highlight`
- `AgentDetail.update_display`
- prompt/file/thinking panel update methods
- AXE status/log/output rendering

**Acceptance check:** after running `SASE_TUI_TRACE=1 sase ace`, `tui_trace.jsonl` should show phase timings and
counters for one startup, one query change, one auto-refresh, and a burst of 50 j/k movements.

---

# P1 — Fix the highest-impact j/k navigation path

## 2. Split ChangeSpec “detail-only” refresh from “full list” refresh

Right now, the ChangeSpec path has a debouncer, but the debounced function ultimately calls the broad refresh path. That
path updates the list, detail, search query panel, ancestors/children panel, footer, and info panel. The list widget
itself clears options and rebuilds rows. ([GitHub][2])

That means a j/k burst avoids rebuilding on every keypress, but after the burst it still does a full list rebuild even
though the list shape did not change.

**Implement in:**

```text
src/sase/ace/tui/actions/changespec_display.py
src/sase/ace/tui/widgets/changespec_list.py
```

Create a new method:

```python
def _refresh_changespec_detail_only(self) -> None:
    list_widget = self._changespec_list_widget
    detail_widget = self._changespec_detail_widget
    ancestors_widget = self._ancestors_children_widget
    footer = self._keybinding_footer_widget

    current = self.current_changespec
    detail_widget.update_display(current, ...)
    ancestors_widget.update_relationships(current, self._all_changespecs, ...)
    footer.update_bindings(...)
    self._update_info_panel()
```

Then change:

```python
_refresh_changespecs_display_debounced()
```

so it does:

```python
ChangeSpecList.update_highlight(...)
_update_info_panel()
self._changespec_detail_debouncer.schedule(self._refresh_changespec_detail_only)
```

Do **not** call `ChangeSpecList.update_list()` from the debounced selection path.

Keep the existing full `_refresh_display()` only for:

- initial load
- query/filter changes
- fold level changes that affect row content
- hint-mode changes
- mark/unmark operations
- reloaded ChangeSpec data
- terminal/submitted visibility changes

**Acceptance test:** monkeypatch `ChangeSpecList.update_list` and simulate 50 `current_idx` changes. The count should
remain `0` during pure j/k navigation after the initial render. `update_highlight` should run for each navigation event.

---

## 3. Add row patching to `ChangeSpecList`

`ChangeSpecList.update_list()` currently clears and rebuilds every option. It also computes mentor stats per ChangeSpec,
with a cache keyed by ChangeSpec identity/status-line data. ([GitHub][3])

That is okay for a true list-shape change, but wasteful for mark toggles, read-state changes, or one ChangeSpec status
update.

**Implement in:**

```text
src/sase/ace/tui/widgets/changespec_list.py
```

Add:

```python
def patch_changespec_row(
    self,
    idx: int,
    changespec: ChangeSpec,
    *,
    selected: bool,
    marked: bool,
    hint: str | None,
) -> bool:
    ...
```

Use Textual’s option replacement API, similar to how `AgentList.patch_agent_row()` already patches agent rows.

Store these during `update_list()`:

```python
self._row_widths_by_idx: dict[int, int]
self._option_idx_by_changespec_name: dict[str, int]
self._last_row_signature_by_idx: dict[int, RowSignature]
```

Only fall back to full `update_list()` when:

- width grows beyond the cached list width
- option count changed
- row order changed
- query/hint/fold state changed globally

**Acceptance test:** toggling mark on one visible ChangeSpec should call `patch_changespec_row()` once and should not
call `clear_options()`.

---

## 4. Cache widget references used in hot paths

Several refresh functions repeatedly call `query_one()` for stable widgets. CSS queries are not the biggest problem, but
they happen on the exact paths you want to keep under 16 ms.

**Implement in:**

```text
src/sase/ace/tui/startup.py
src/sase/ace/tui/actions/*.py
```

After mount, cache stable widget refs:

```python
self._w_changespec_list = self.query_one("#changespec-list", ChangeSpecList)
self._w_changespec_detail = self.query_one("#changespec-detail", ChangeSpecDetail)
self._w_ancestors_children = self.query_one("#ancestors-children", AncestorsChildrenPanel)
self._w_footer = self.query_one(KeybindingFooter)
self._w_agent_detail = self.query_one("#agent-detail", AgentDetail)
...
```

Use cached refs in:

- `_refresh_changespecs_display_debounced`
- `_refresh_changespec_detail_only`
- `_refresh_display`
- `_refresh_agents_display_debounced`
- `_refresh_panel_highlights`
- `_update_agents_info_panel`

**Acceptance test:** tracing counter for `query_one` during 50 j/k movements should drop close to zero for stable
panels.

---

# P2 — Cache ChangeSpec parsing, filtering, and graph data

## 5. Add `ChangeSpecSnapshotCache`

The current ChangeSpec discovery path scans `~/.sase/projects`, parses main `.gp` files and archive `.gp` files for
every project, and `parse_project_file()` reads each file’s full contents. ([GitHub][4])

That is likely a top startup and refresh bottleneck.

**Implement in:**

```text
src/sase/changespec/cache.py
src/sase/changespec/__init__.py
```

Create an in-process cache keyed by:

```python
(path, stat.st_mtime_ns, stat.st_size)
```

API:

```python
class ChangeSpecSnapshotCache:
    def get_file_specs(self, path: Path) -> list[ChangeSpec]:
        ...

    def find_all_changespecs_cached(self) -> list[ChangeSpec]:
        ...
```

Then change TUI loading from:

```python
find_all_changespecs()
```

to:

```python
find_all_changespecs_cached()
```

Add an optional persistent cache:

```text
~/.sase/cache/changespecs-v1.json
```

Use it only when all source file `(mtime_ns, size)` signatures match.

**Acceptance tests:**

- Warm `find_all_changespecs_cached()` should not call `parse_project_file()` for unchanged files.
- Editing one `.gp` file should reparse only that file.
- Startup trace should show separate cold and warm ChangeSpec load timings.

---

## 6. Add a `QueryEvaluationContext`

Filtering currently calls `evaluate_query(parsed_query, cs, all_changespecs)` for every ChangeSpec. The evaluator builds
searchable text from many fields, and ancestor matching rebuilds name maps when `all_changespecs` is provided.
([GitHub][5])

This is exactly the kind of work that should be done once per ChangeSpec-list version, not once per row per refresh.

**Implement in:**

```text
src/sase/query/evaluator.py
src/sase/ace/tui/actions/changespec_loading.py
```

Add:

```python
@dataclass
class QueryEvaluationContext:
    all_changespecs: list[ChangeSpec]
    name_map: dict[str, ChangeSpec]
    status_map: dict[str, BaseChangeStatus]
    searchable_text: dict[str, str]
    searchable_lower: dict[str, str]
    ancestor_memo: dict[tuple[str, str], bool]
```

New API:

```python
def build_query_context(changespecs: list[ChangeSpec]) -> QueryEvaluationContext:
    ...

def evaluate_query_with_context(
    query: QueryNode,
    changespec: ChangeSpec,
    ctx: QueryEvaluationContext,
) -> bool:
    ...
```

Use cached lowercase text for string matching:

```python
ctx.searchable_lower[changespec.name]
```

Use `ctx.name_map` and `ctx.ancestor_memo` for ancestor evaluation.

**Acceptance tests:**

- For N ChangeSpecs, `build_name_to_base_status` should run once per filter refresh, not once per row.
- `_get_searchable_text` should run at most once per ChangeSpec per ChangeSpec-list version.
- Ancestor query over 1,000 ChangeSpecs should not rebuild a name map 1,000 times.

---

## 7. Add `ChangeSpecGraphIndex` for ancestors, children, siblings, and terminal counts

The ancestors/children panel rebuilds relationship maps for the selected ChangeSpec. That is acceptable for occasional
selection, but after the detail-only path lands, it becomes the main per-selection ChangeSpec computation.

**Implement in:**

```text
src/sase/ace/tui/models/changespec_graph_index.py
src/sase/ace/tui/widgets/ancestors_children_panel.py
```

Build once whenever `_all_changespecs` changes:

```python
@dataclass
class ChangeSpecGraphIndex:
    name_map: dict[str, ChangeSpec]
    children_by_parent: dict[str, list[ChangeSpec]]
    status_by_name: dict[str, BaseChangeStatus]
    siblings_by_base_name: dict[str, list[ChangeSpec]]
    terminal_count: int
    submitted_count: int
```

Then expose:

```python
panel.update_relationships_from_index(current, graph_index)
```

**Acceptance test:** selecting 100 different ChangeSpecs should not rebuild the full children map or status map 100
times.

---

# P3 — Make agent navigation and grouping O(1)

## 8. Add `AgentPanelIndex`

The agent display path is already better optimized than the ChangeSpec path. It caches panel keys, debounces detail
updates, and has single-row patching. Still, some hot functions rebuild panel/global-index lists repeatedly.
([GitHub][2])

Build one index per `_agents` list identity and grouping/fold version.

**Implement in:**

```text
src/sase/ace/tui/models/agent_panel_index.py
src/sase/ace/tui/actions/agents_display.py
```

Suggested shape:

```python
@dataclass
class PanelSlice:
    agents: list[Agent]
    global_indices: list[int]
    global_to_local: dict[int, int]

@dataclass
class AgentPanelIndex:
    agents_ref_id: int
    grouping_signature: tuple
    keys_per_agent: list[PanelKey]
    panels: dict[PanelKey, PanelSlice]
    non_child_indices: list[int]
    completed_count: int
```

Use this in:

- `_refresh_panel_widgets`
- `_refresh_panel_highlights`
- `_try_patch_agent_row`
- `_update_agents_info_panel`
- dismiss-count/status calculation

**Acceptance tests:**

- `_refresh_panel_highlights` should not allocate a new `global_indices` list on every j/k.
- `_update_agents_info_panel` should not scan every agent to compute non-child position each time.
- Completed/dismissable count should be precomputed once per agent snapshot.

---

## 9. Add row lookup maps inside `AgentList`

`AgentList.update_list()` already does a lot of caching and has row patching, but highlight lookup still appears to scan
row entries to find the target row. The list renderer has enough information to make this O(1).

**Implement in:**

```text
src/sase/ace/tui/widgets/agent_list.py
```

During `update_list()`, build:

```python
self._row_by_agent_attempt: dict[tuple[int, int | None], int]
self._row_by_agent_idx: dict[int, int]
self._banner_row_by_key: dict[BannerKey, int]
```

Then change:

```python
update_highlight(...)
_row_index_for_agent(...)
patch_agent_row(...)
```

to use those maps.

**Acceptance test:** with 1,000 agents, 100 highlight moves should not scan `_row_entries`.

---

# P4 — Make agent loading incremental

## 10. Avoid reloading all agent-derived data on every refresh

Agent loading pulls together data from ChangeSpecs, running/done/home/workflow dirs, tags, hooks, mentors, comments,
artifact directories, attempt history, retry state, and dismissed bundles. The model loader also calls ChangeSpec
discovery again, which can duplicate the ChangeSpec parse cost already paid by the ChangeSpec tab. ([GitHub][4])

**Implement in:**

```text
src/sase/ace/tui/actions/agents_loading_helpers.py
src/sase/ace/tui/models/agent_loader.py
```

Add an `AgentSnapshotCache` keyed by:

```python
project file signatures
agent artifact dir signatures
attempt metadata file signatures
retry_state.json signatures
dismissed bundle signatures
tag file signature
```

API:

```python
class AgentSnapshotCache:
    def load_agents(
        self,
        *,
        changespec_snapshot: list[ChangeSpec] | None,
        force: bool = False,
    ) -> list[Agent]:
        ...
```

Important changes:

- Pass the current cached ChangeSpec list into the agent loader when available.
- Do not call `find_all_changespecs()` again inside agent loading unless no snapshot exists.
- Cache `load_attempt_history(artifacts_dir)` by attempt-dir/file mtimes.
- Cache retry state by `(path, mtime_ns, size)`.
- Defer dismissed bundle expansion until the dismissed panel is visible or until the row is needed.
- Use the file watcher to invalidate affected agents instead of dropping the whole snapshot.

**Acceptance tests:**

- Agent auto-refresh with no filesystem changes should perform zero ChangeSpec parses.
- Agent auto-refresh with one updated live reply should reload only that agent’s volatile artifact data.
- Attempt history should not be re-read for every agent on every refresh.

---

## 11. Do not load expensive detail panels until the selected agent is stable

`AgentDetail.update_display` updates prompt/file/thinking panels. The file and thinking panels already have background
workers and caches, but selection bursts can still schedule work that will be obsolete milliseconds later. The file
panel can fetch VCS diffs, and prompt rendering can read multiple artifact files. ([GitHub][6])

**Implement in:**

```text
src/sase/ace/tui/widgets/agent_detail.py
src/sase/ace/tui/actions/agents_display.py
```

Change agent detail update into two phases:

1. **Immediate lightweight phase**
   - Update selected title/status.
   - Render cached prompt summary if available.
   - Do not start file/thinking/diff workers yet.

2. **Idle/debounced phase**
   - After the existing detail debounce fires, start file/thinking/diff workers for the final selected agent only.

Add a monotonically increasing token:

```python
self._agent_detail_generation += 1
generation = self._agent_detail_generation
```

Workers discard results if their generation is stale.

**Acceptance test:** holding j/k across 50 agents should start file/thinking workers only for the final selected agent,
not all intermediate agents.

---

# P5 — Cache artifact reads and heavy Rich rendering

## 12. Add `AgentArtifactCache`

Agent prompt/detail rendering reads prompt files, raw xprompt content, live reply content, timestamped reply chunks,
response files, and chat response content. The prompt display then creates Rich Markdown `Syntax` blocks for several of
these. ([GitHub][7])

**Implement in:**

```text
src/sase/agent/agent_artifacts_cache.py
src/sase/agent/agent_artifacts.py
src/sase/ace/tui/prompt_panel/_agent_display.py
src/sase/ace/tui/prompt_panel/_agent_display_parts.py
```

Cache by:

```python
agent identity
artifacts_dir
file path
mtime_ns
size
attempt_number
view mode
terminal width
```

Cache:

- prompt file selection result
- prompt content
- raw xprompt content
- response content
- chat response content
- timestamped reply chunks
- live reply tail
- prebuilt Rich renderables where safe

For live replies, avoid rereading the whole file:

```python
@dataclass
class TailCache:
    path: Path
    size: int
    offset: int
    text: str
```

When size grows, read only the appended bytes. When size shrinks, reset.

**Acceptance tests:**

- Selecting the same agent twice should not re-glob prompt files.
- A live reply refresh should not reread the entire reply file when only appended content changed.
- Syntax creation count should drop on repeated selection of the same agent.

---

## 13. Add size caps and lazy syntax highlighting

Rich `Syntax(..., "markdown", theme="monokai", word_wrap=True)` is expensive for large replies, prompts, and diffs.
([GitHub][7])

**Implement in:**

```text
src/sase/ace/tui/prompt_panel/_agent_display.py
src/sase/ace/tui/file_panel/_display.py
src/sase/ace/tui/widgets/axe_dashboard.py
```

Policy:

```python
SYNTAX_HIGHLIGHT_MAX_BYTES = 64_000
SYNTAX_HIGHLIGHT_MAX_LINES = 1_500
```

For content larger than the cap:

- render initial view as plain `Text`
- show a small notice: `Large output rendered without syntax highlighting`
- optionally schedule syntax highlighting after idle if the selected item remains stable

For diffs, highlight only the visible/trimmed line range first.

**Acceptance tests:**

- A 5 MB response should not freeze the UI.
- First paint for a large selected agent should be under the j/k target.
- Syntax highlighting should not run for hidden panels.

---

## 14. Cache file diffs and dedupe in-flight diff workers

The file panel already uses a module cache and a background worker, but active agents can trigger VCS diffs through the
provider path. ([GitHub][6])

**Implement in:**

```text
src/sase/ace/tui/file_panel/_diff.py
src/sase/ace/tui/file_panel/__init__.py
```

Add:

```python
DiffCacheKey = tuple[
    agent_identity,
    workspace_path,
    vcs_provider_name,
    worktree_fingerprint,
]
```

For the fingerprint, start simple:

- workspace path
- `.git/index` mtime/size when available
- latest mtime of tracked/untracked files if cheap
- fallback TTL for active agents, for example 2 seconds

Also dedupe in-flight work:

```python
self._inflight_diff_tasks: dict[DiffCacheKey, Worker]
```

If the same diff is already running, attach the UI update to that result instead of starting another diff.

**Acceptance tests:**

- Re-selecting the same active agent should not call `diff_with_untracked()` repeatedly when the worktree did not
  change.
- Moving away before the diff completes should not update the wrong agent’s panel.

---

# P6 — Reduce background refresh cost

## 15. Make auto-refresh event-driven when the filesystem watcher is active

The event handler defers refreshes during navigation, which is good. But auto-refresh still polls AXE status, agent
completions, loads agents, and reloads ChangeSpecs when on the ChangeSpecs tab. ([GitHub][8])

Use the watcher as the primary invalidation source.

**Implement in:**

```text
src/sase/ace/tui/event_handlers.py
src/sase/ace/tui/util/fs_watcher.py
```

Track dirty flags:

```python
self._dirty_changespecs = False
self._dirty_agents = False
self._dirty_axe = False
self._last_full_sanity_refresh = 0.0
```

On file events, set the relevant dirty flag.

On auto-refresh:

```python
if watcher_active:
    if dirty_agents:
        refresh_agents()
    if dirty_changespecs and current_tab == "changespecs":
        refresh_changespecs()
    if dirty_axe or axe_running:
        refresh_axe_status()
else:
    existing polling behavior
```

Keep a slow sanity refresh:

```python
FULL_SANITY_REFRESH_SECONDS = 60
```

**Acceptance tests:**

- With no filesystem changes and watcher active, auto-refresh should not call full `load_agents_from_disk`.
- A changed agent artifact should refresh agents.
- A changed `.gp` file should refresh ChangeSpecs.
- AXE running state should still update while active.

---

## 16. Remove disk config loading from AXE list rendering

The AXE/BgCmd list path formats parent options and can load AXE config during row formatting. Since the caller already
has lumberjack names/status data, row rendering should not parse config. The README identifies AXE as part of the ACE
workflow surface, and the TUI composes AXE views alongside ChangeSpecs and agents. ([GitHub][9])

**Implement in:**

```text
src/sase/ace/tui/widgets/bgcmd_list.py
src/sase/ace/tui/actions/axe_loaders.py
```

Change parent option formatting to use precomputed data:

```python
configured_count = len(lumberjack_names)
```

not:

```python
load_axe_config()
```

**Acceptance test:** `BgCmdList.update_list()` should not perform disk config reads.

---

## 17. Cache ANSI parsing for AXE output

The AXE dashboard renders command/log output via ANSI parsing. Parsing a 500-line tail every refresh can become visible
if updates are frequent.

**Implement in:**

```text
src/sase/ace/tui/widgets/axe_dashboard.py
src/sase/ace/tui/actions/axe_loaders.py
```

Cache parsed output by:

```python
(source_id, mtime_ns, size, tail_hash)
```

For append-only logs, parse only new appended text where practical. For fixed 500-line tails, a hash cache is enough.

**Acceptance tests:**

- Refreshing unchanged AXE output should not call `Text.from_ansi`.
- Appending one log line should not reparse unrelated unchanged dashboard sections.

---

# P7 — Smaller but easy wins

## 18. Cache saved search queries in app state

`SearchQueryPanel.render` loads saved queries during render. Rendering should be pure and should not hit disk.

**Implement in:**

```text
src/sase/ace/tui/widgets/changespec_detail.py
src/sase/ace/tui/startup.py
```

Load once on startup:

```python
self._saved_queries = load_saved_queries()
```

Invalidate only when saved queries change.

**Acceptance test:** repeated detail renders should not call `load_saved_queries()`.

---

## 19. Make footer updates idempotent

The keybinding footer rebuilds display content and status text frequently. This is probably not the main bottleneck, but
it is easy to fix.

**Implement in:**

```text
src/sase/ace/tui/widgets/keybinding_footer.py
```

Store:

```python
self._last_bindings_signature
self._last_status_signature
```

Skip updates when signatures are unchanged. Cache child widget refs in `on_mount`.

**Acceptance test:** 100 j/k moves with unchanged bindings should not rebuild the full footer text 100 times.

---

## 20. Lazy-load snippets and optional startup-only data

Startup initializes config, snippets, keymaps, notifications, ChangeSpecs, and then kicks off background agent/AXE
loads. The startup code is already intentionally asynchronous for disk-heavy work. ([GitHub][10])

After tracing, consider deferring:

- xprompt snippets until prompt entry/help is opened
- expensive custom keymap resolution until footer/help needs it
- hidden AXE/agent widget data until the tab is visited, except lightweight status badges

**Acceptance test:** cold startup first paint should not depend on snippet loading unless the prompt UI is visible.

---

# Suggested implementation order

1. **P0 tracing** — without this, regressions will be hard to catch.
2. **ChangeSpec detail-only refresh** — likely the fastest visible improvement for j/k.
3. **ChangeSpec parse/query/graph caches** — likely biggest startup and reload improvement.
4. **AgentPanelIndex and AgentList row maps** — makes large agent lists feel snappy.
5. **AgentSnapshotCache** — biggest background-refresh improvement.
6. **AgentArtifactCache + lazy Rich rendering** — fixes large prompt/reply/diff stalls.
7. **Event-driven auto-refresh** — reduces idle CPU and surprise refresh jank.
8. **AXE/footer/search-query small fixes** — easy cleanup after the main path is stable.

---

# Benchmark targets for the implementing agent

Use synthetic data so regressions are reproducible:

```text
ChangeSpecs: 100, 500, 2,000
Agents:      50, 200, 1,000
Panels:      1, 5, 20
Large files: 1 MB, 5 MB, 20 MB replies/diffs/logs
```

Track:

```text
startup first paint
cold ChangeSpec load
warm ChangeSpec load
query/filter latency
50-key j/k burst p50/p95/p99
agent tab first render
agent detail render
auto-refresh with no changes
auto-refresh with one changed artifact
AXE output refresh
```

Good targets:

```text
j/k highlight p95:             < 16 ms
key-to-paint p95:              < 33 ms
debounced detail paint:        < 150–250 ms
warm ChangeSpec reload, 1k CLs:< 100 ms
no-change auto-refresh stall:  ~0 visible UI work
large reply first paint:       immediate plain render, syntax later/optional
```

---

# One-page handoff for another agent

Give the next agent this instruction:

> Start by adding `SASE_TUI_TRACE=1` scoped timings. Then implement a ChangeSpec detail-only refresh path so pure j/k
> navigation never calls `ChangeSpecList.update_list()`. Add tests proving list rebuild count stays zero during
> navigation. Next, add `ChangeSpecSnapshotCache`, `QueryEvaluationContext`, and `ChangeSpecGraphIndex` so parsing,
> searchable text, ancestor maps, status maps, and relationship maps are built once per data version. Then implement
> `AgentPanelIndex` and O(1) row lookup maps in `AgentList`. After that, build `AgentSnapshotCache` and
> `AgentArtifactCache`, and cap/lazy-load expensive Rich `Syntax` rendering for prompts, replies, diffs, and AXE output.
> Finally, make auto-refresh mostly event-driven when the filesystem watcher is active.

The highest-probability performance win is **separating selection highlight from full data/list/detail refresh**. The
second-highest is **caching parsed ChangeSpecs and query/graph indexes**. The third is **incremental agent/artifact
loading**.

[1]: https://raw.githubusercontent.com/sase-org/sase/master/src/sase/main/ace_handler.py "raw.githubusercontent.com"
[2]:
  https://github.com/sase-org/sase/blob/master/src/sase/ace/tui/app.py
  "sase/src/sase/ace/tui/app.py at master · sase-org/sase · GitHub"
[3]:
  https://github.com/sase-org/sase/raw/refs/heads/master/src/sase/ace/tui/widgets/changespec_list.py
  "raw.githubusercontent.com"
[4]:
  https://raw.githubusercontent.com/sase-org/sase/master/src/sase/ace/changespec/__init__.py
  "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/sase-org/sase/master/src/sase/ace/query/evaluator.py "raw.githubusercontent.com"
[6]:
  https://raw.githubusercontent.com/sase-org/sase/master/src/sase/ace/tui/widgets/file_panel/__init__.py
  "raw.githubusercontent.com"
[7]:
  https://raw.githubusercontent.com/sase-org/sase/master/src/sase/ace/tui/widgets/prompt_panel/_agent_display.py
  "raw.githubusercontent.com"
[8]:
  https://github.com/sase-org/sase/raw/refs/heads/master/src/sase/ace/tui/actions/event_handlers.py
  "raw.githubusercontent.com"
[9]: https://github.com/sase-org/sase "GitHub - sase-org/sase: Structured Agentic Software Engineering (SASE) · GitHub"
[10]:
  https://github.com/sase-org/sase/raw/refs/heads/master/src/sase/ace/tui/actions/startup.py
  "raw.githubusercontent.com"

