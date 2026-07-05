---
create_time: 2026-07-05 06:57:49
status: wip
prompt: sdd/prompts/202607/slow_tool_calls_root_child_scoping.md
---
# Plan: Scope SLOW TOOL CALLS per selected agent row (child = own calls; root = all children, attributed)

## Problem

The SLOW TOOL CALLS section in the agent metadata panel (Agents tab, `sase ace` TUI) misbehaves around root/child agent
rows:

1. **Root entries show nothing.** For a plan-chain family like `04` (an appears-as-agent workflow whose children are the
   `04--plan` main prompt step and the `04--code` follow-up agent), selecting the root row shows no SLOW TOOL CALLS
   section even when children made slow calls. The root's tool-call fetch (`fetch_tool_calls_cached`) reads the root's
   own `tool_calls.jsonl` (plus whatever the lineage-index discovery returns), which typically contains only the root
   run's own fast calls. Verified against real artifacts: the root dir had 60 calls / 0 slow, while the `--code` child
   dir had 132 calls / 1 slow — so the root renders no section.

2. **Child entries can show calls they never made.** Related-dir discovery (`discover_related_tool_artifact_dirs` + the
   Rust-index query) seeds on lineage timestamps including `parent_timestamp`, so a child row's fetch can pull
   **sibling** artifact dirs. A slow call made by `04--code` can appear in `04--plan`'s SLOW TOOL CALLS section with no
   indication it came from a different agent.

Desired behavior (user request):

- **Child agent row selected** → show only the slow tool calls made by _that_ agent.
- **Root entry selected** → show slow tool calls from **all** child agents, each row carrying an indicator of which
  child made the call.

## Key facts discovered (grounding for the design)

- Every `ToolCallEntry` records the `artifact_dir` it was parsed from (`src/sase/ace/tui/tools/_entry.py`). This is the
  reliable attribution key.
- A root row's child rows are already linked in memory: `Agent.runtime_children` (`src/sase/ace/tui/models/agent.py`,
  populated by `_attach_runtime_children` in `models/_agent_ordering.py`) holds the visible main agent steps + family
  follow-ups.
- The main prompt step row (displayed e.g. `04--plan`) **shares the root's artifacts dir** — its `prompt_step_main.json`
  marker points `artifacts_dir` at the root's timestamp dir. Follow-up agents (`04--code`, `--commit`, feedback rounds
  …) have their own dirs. Attribution must therefore claim dirs with child-precedence (see below).
- Child rows carry short role identity: `agent_family_role` ("plan", "code", "q", "feedback"), `role_suffix`,
  `agent_name` (e.g. `04--code`), and workflow steps carry `step_name`.
- Slow-call selection/rendering lives in `src/sase/ace/tui/tools/slow.py` and
  `src/sase/ace/tui/widgets/prompt_panel/_agent_slow_tools.py`; candidates are produced off the event loop by
  `build_detail_header_summary` (`widgets/prompt_panel/_agent_display_header_summary.py`, gated on
  `agent.is_agent_entry`) and carried via `DetailHeaderSummary.slow_tool_candidates` / `.slow_tool_end_reference`.
- A 5s render tick (`AgentPromptPanel._configure_slow_tool_render_tick` in `widgets/prompt_panel/__init__.py`) keeps
  running-call durations live; it gates on `agent.is_agent_entry` + `cached_tool_calls_have_pending(agent)` (peek-only
  cache helpers in `tools/cache.py`).
- The `]` tools timeline panel (`widgets/tools_panel.py`, cycling gated on `is_agent_entry` in
  `widgets/_agent_detail_panels.py`) is referenced by the section's overflow hint ("+ N more · press ] for the full
  tools timeline").

## Design overview

Introduce an explicit **source-scoped** model for slow tool calls. Scoping and attribution happen at display time from
`entry.artifact_dir`, which makes behavior deterministic regardless of how broadly the related-dir discovery (Python
fallback or Rust index) fetches. No changes to discovery, caching keys, or sase-core.

### New data model: `SlowToolSource`

New module `src/sase/ace/tui/tools/sources.py`:

```python
@dataclass(frozen=True)
class SlowToolSource:
    label: str | None                    # None → selected row itself (leaf view, no chip column)
    entries: tuple[ToolCallEntry, ...]   # already filtered to this source's claimed dir(s)
    agent_is_active: bool                # per-source activity (not the selected row's!)
    end_reference: datetime | None       # per-source end reference for "did not complete"
    palette_index: int                   # stable per-source color assignment
```

Builder (worker-thread only; may stat/read files):

```python
def build_slow_tool_sources(agent: Agent) -> tuple[SlowToolSource, ...] | None
def supports_slow_tool_sources(agent: Agent) -> bool
    # agent.is_agent_entry OR any(child.is_agent_entry for child in agent.runtime_children)
```

**Leaf/child row** (no agent-entry `runtime_children`): one unlabeled source. Fetch via the existing
`fetch_tool_calls_cached(agent)`, then filter entries to `entry.artifact_dir` == the row's own resolved
`get_artifacts_dir()`. This is the fix for problem 2: sibling calls pulled in by discovery are dropped at display time.

**Root row** (has agent-entry `runtime_children`): build one source per _claimed artifact dir_:

1. Rows considered: `[root] + [c for c in root.runtime_children if c.is_agent_entry]`.
2. Children claim their resolved artifacts dirs first (in `runtime_children` order); the root claims its own dir only if
   no child claimed it. This attributes the shared root/main-step dir to the "plan" child (matching what the user sees
   as the row that did that work) instead of double-counting or mislabeling it as the root.
3. For each claimed dir: fetch via that row's `fetch_tool_calls_cached`, filter to entries from exactly that dir, and
   record per-source `agent_is_active` (via `agent_is_active_for_slow_tool_calls(row)`) and `end_reference`
   (`row.stop_time` or `cached_tool_calls_end_reference(row)`).

Path comparison uses the same normalization as the reader (`Path.resolve(strict=False)` semantics, mirroring
`_path_identity` in `tools/reader.py`).

Per-source activity fixes a real correctness gap in any naive aggregate: a pending call from a child that died must
render "did not complete" (using that child's end reference), not tick as "running" forever just because the root is
still active.

### Child indicator labels

Precedence for a source's short label:

1. `agent_family_role` when set — "plan", "code", "q", "epic", "legend", "commit"; feedback rounds render their round
   number (via `plan_chain_feedback_round`), e.g. "fb2".
2. Workflow steps: `step_name`.
3. `agent_name` with the root's name + `--` separator prefix stripped (`04--commit` → "commit"; use `sase.plan_chain`
   helpers rather than ad-hoc string slicing where they fit).
4. Fallback: the child's `display_name`.

The root's own (unclaimed-dir) source gets the label `root`. Labels are truncated to the chip column width with the
existing `truncate_display` helper.

### Rendering (`_agent_slow_tools.py`)

`append_slow_tool_calls_section` changes to accept `sources: tuple[SlowToolSource, ...] | None` (replacing
`candidates`/`agent_end_reference`; keep `agent` + `now` for the leaf fast path and header context):

- Run `select_slow_tool_calls` **per source** with that source's `agent_is_active`/`end_reference`, tag each
  `SlowToolCall` with the source, then merge and re-sort globally: running first, then by effective duration descending
  — same ranking philosophy as today ("worst offenders first"), never grouped by child (grouping would hide the ranking,
  which is the point of this section).
- **Chip column**: shown only when at least one source has a label (i.e. root view). Layout per row:

  ```
    10:21:44  ⏳ code   Bash          just test                       2m 41s ● running
    10:35:12  ✔ code   Bash          gh pr checks --watch               58s
    10:18:03  ✔ plan   WebFetch      https://docs.python.org/3/…        24s
    10:19:55  ◼ root   Read          src/sase/ace/tui/app.py            21s did not complete
    + 1 more · press ] for the full tools timeline
  ```

  Chip sits between the status glyph and the tool name, fixed width (7 cells, cell-aware padding like the existing
  `_pad_cells`). To keep total row width unchanged, the target column shrinks in labeled mode (`_TARGET_WIDTH` 44 → 35).
  Leaf view renders exactly as today (no chip column, no width change).

- **Chip colors**: a small fixed palette of ~6 muted, mutually distinguishable hues consistent with the section's
  existing warm-accent scheme (e.g. drawn from the tones already used in this panel: `#87D7FF`, `#5FD75F`, `#D7AF5F`,
  `#AF87FF`, `#5FD7D7`, `#D787AF`), assigned by source order (`palette_index`) so a child keeps its color across
  re-renders. Style italic/normal weight so the chips read as metadata, not as status.
- **Summary line**: in root view append an agent count, e.g. `SLOW TOOL CALLS · ≥20s · 4 calls · 1 running · 2 agents`
  (count = sources contributing ≥1 slow call). Leaf view summary unchanged.
- Threshold (`SLOW_TOOL_CALL_THRESHOLD_MS` = 20s) and `MAX_VISIBLE_SLOW_TOOL_CALLS` (8) unchanged; overflow line
  unchanged.

### Plumbing

- `DetailHeaderSummary` (`_agent_display_state.py`): replace `slow_tool_candidates` + `slow_tool_end_reference` with
  `slow_tool_sources: tuple[SlowToolSource, ...] | None`.
- `build_detail_header_summary` (`_agent_display_header_summary.py`): gate on `supports_slow_tool_sources(agent)` and
  call `build_slow_tool_sources(agent)` (worker thread — same enrichment worker as today; no new refresh paths).
- `build_header_text` (`_agent_display_header.py`): pass `summary.slow_tool_sources` through.
- **Render tick** (`widgets/prompt_panel/__init__.py`): add peek-only helper `slow_tool_sources_have_pending(agent)` to
  `tools/cache.py` (checks the root's cache key and each agent-entry runtime child's key via `peek_cached_tool_calls`;
  no filesystem I/O — safe on the event loop). Tick config + tick callback use `supports_slow_tool_sources` +
  `slow_tool_sources_have_pending` in place of the current `is_agent_entry` + `cached_tool_calls_have_pending` pair.

### `]` tools timeline alignment (keeps the overflow hint honest)

When a root row is selected, the tools panel (`widgets/tools_panel.py`) currently shows only what the root's own fetch
returns — which may omit the children's calls the metadata section now surfaces, breaking the "press ] for the full
tools timeline" promise.

- In the panel's existing background fetch, when the agent is a root (`supports_slow_tool_sources` and has agent-entry
  children), build the same claimed-dir sources, merge all entries chronologically (existing sort), and render each row
  with the same short child chip (reusing label + palette assignment) ahead of the tool name.
- Extend the tools-panel availability predicate in `widgets/_agent_detail_panels.py` (`toggle_tools`, currently
  `is_agent_entry`) to `supports_slow_tool_sources`, so pure `[workflow]` roots can open the timeline too.
- Per `src/sase/ace/AGENTS.md`: audit the footer conditional keymaps (`widgets/keybinding_footer.py`) and the `?` help
  modal for any text describing tools-panel availability, and update if the predicate change makes them stale.

### Top-level `[workflow]` roots (separate render path)

Plain workflow roots (not `appears_as_agent`) render via `_update_workflow_display`
(`widgets/prompt_panel/_workflow_display.py`), which never consults `DetailHeaderSummary`. For uniform behavior on every
root entry: in the workflow detail snapshot worker (`_load_workflow_detail_snapshot` / `render_task`), build the same
sources and append the same SLOW TOOL CALLS section to the rendered group. This is a self-contained step; if it proves
noisy it can ship behind the same helper with a follow-up, but the design intends parity for all root rows.

## Explicitly out of scope / boundary notes

- **No sase-core (Rust) changes.** Related-dir discovery, the artifact index, and cache keys are untouched;
  scoping/attribution is presentation-layer selection over data the reader already returns, and the slow-call selection
  logic this extends already lives in the Python TUI layer. If a second frontend ever needs slow-call scoping, that is
  the moment to lift `select_slow_tool_calls` + `SlowToolSource` into `sase_core`.
- No new keymaps or config values → no `default_config.yml` changes.
- No change to the 20s threshold, row cap, or section placement in the header.

## Reliability & performance constraints (per tui_perf memory)

- All file I/O (per-child fetches) stays in the existing worker paths: the detail-header enrichment worker and the
  tools-panel worker. Event-loop code only peeks in-memory caches.
- Per-child fetch cost is bounded: `runtime_children` is small; `fetch_tool_calls_cached` already throttles (0.5s min
  re-read) and short-circuits on mtime watermarks. Shared dirs are fetched once per claimed dir, not once per row.
- The summary cache TTL (1s) and the 5s slow-tick cadence are unchanged; per-source `agent_is_active` computed at
  summary-build time is at most ~TTL stale and heals on the next tick.
- Render-time work stays O(cached entries): per-source selection + merge sort, no filesystem access.

## Edge cases

- Child without a resolvable artifacts dir → contributes no source (nothing to attribute).
- Retried children: each retry row is its own source; identical labels across attempts are acceptable (ranking,
  timestamps, and durations disambiguate).
- Entries from dirs no considered row claims (e.g. dismissed rows' dirs pulled in by discovery) are dropped —
  deterministic over guessing.
- Root with zero agent-entry children behaves exactly like a leaf (single unlabeled source).
- Attempt-pinned view: unchanged (enrichment already skips when `attempt_pinned_number` is set).
- All agent runtimes are treated uniformly (no provider-specific branching).

## Files to change

| File                                                                     | Change                                                                                                |
| ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| `src/sase/ace/tui/tools/sources.py` (new)                                | `SlowToolSource`, `build_slow_tool_sources`, `supports_slow_tool_sources`, label + dir-claiming logic |
| `src/sase/ace/tui/tools/cache.py`                                        | `slow_tool_sources_have_pending` peek helper                                                          |
| `src/sase/ace/tui/tools/slow.py`                                         | (minor) allow per-source selection reuse; export types                                                |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_slow_tools.py`             | source-based rendering, chip column, palette, summary agent count                                     |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_display_state.py`          | `DetailHeaderSummary.slow_tool_sources`                                                               |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_display_header_summary.py` | build sources in enrichment worker                                                                    |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_display_header.py`         | pass sources to renderer                                                                              |
| `src/sase/ace/tui/widgets/prompt_panel/__init__.py`                      | tick gating via new predicates                                                                        |
| `src/sase/ace/tui/widgets/tools_panel.py`                                | root-aggregated timeline with chips                                                                   |
| `src/sase/ace/tui/widgets/_agent_detail_panels.py`                       | tools availability predicate                                                                          |
| `src/sase/ace/tui/widgets/keybinding_footer.py`, help modal              | only if predicate change makes text/conditions stale                                                  |
| `src/sase/ace/tui/widgets/prompt_panel/_workflow_display.py`             | append section for `[workflow]` roots                                                                 |

## Testing

- **`tests/ace/tui/tools/test_slow_sources.py` (new)**: builder unit tests over temp artifact dirs with real
  `tool_calls.jsonl` fixtures — leaf own-dir scoping (sibling entries dropped); root aggregation; shared root/main-step
  dir claimed by the child; label precedence (family role, feedback round, step name, stripped agent name, `root`
  fallback); per-source activity and end references; missing-dir children skipped.
- **`tests/ace/tui/widgets/test_agent_slow_tools.py`**: extend for chip column rendering, merged running-first/duration
  sort across sources, `· N agents` summary, no chip column in leaf view, per-source did-not-complete vs running states,
  width invariants.
- **`tests/ace/tui/widgets/test_agent_slow_tool_tick.py`**: `slow_tool_sources_have_pending` gating (pending call in a
  child keeps the root's tick alive; no pending anywhere cancels it).
- **`tests/ace/tui/widgets/test_prompt_panel_header.py`**: root header renders the section from children's calls; child
  header excludes sibling calls (regression for both reported symptoms).
- **`tests/ace/tui/widgets/test_tools_panel.py`**: root timeline aggregates children with chips.
- **PNG visual snapshot**: add a root-selected metadata-panel scenario with a populated SLOW TOOL CALLS section (chips +
  running badge) to the visual suite (`tests/ace/tui/visual/`, goldens under `tests/ace/tui/visual/snapshots/png/`),
  following the existing fixture patterns; run `just test-visual` and accept via `--sase-update-visual-snapshots` only
  for the new golden.
- Full `just check` before completion.

## Implementation order

1. `SlowToolSource` model + `build_slow_tool_sources` + predicates + cache peek helper, with unit tests (pure logic, no
   UI).
2. Wire through `DetailHeaderSummary` → header renderer; implement chip rendering + merged sort + summary count; update
   existing renderer/summary/tick tests.
3. Tick gating updates.
4. Tools panel root aggregation + availability predicate (+ footer/help audit).
5. `[workflow]` root snapshot path.
6. Visual snapshot + polish pass (palette/truncation tuning at narrow widths).
