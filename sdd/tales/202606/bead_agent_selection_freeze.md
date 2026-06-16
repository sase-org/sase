---
create_time: 2026-06-16 11:22:18
status: done
prompt: sdd/prompts/202606/bead_agent_selection_freeze.md
---
# Fix: TUI freeze when selecting a bead-associated agent

## Problem

In the `sase ace` TUI, selecting an agent on the **Agents** tab that has a sase **bead** associated with it sometimes
freezes the whole TUI "for a while." Plain agents (no bead) do not exhibit this. The freeze is intermittent and its
duration varies.

## Root cause

The freeze is a classic event-loop violation: a synchronous, potentially multi-second bead lookup runs on the Textual
event loop during the agent's **debounced detail update**.

### Call path (all on the event loop)

1. Highlight/selection change schedules a debounced detail refresh: `_refresh_agents_display_debounced()` →
   `DetailPanelDebouncer.schedule(...)` (`src/sase/ace/tui/util/debounce.py`). The debouncer fires via
   `app.set_timer(...)`, i.e. **on the event loop**, ~150 ms after the j/k burst settles.
2. `_fire_debounced_detail_update()` → `_apply_agent_detail_update()`
   (`src/sase/ace/tui/actions/agents/_display_detail.py`) → `AgentDetail.update_display()` →
   `AgentDisplayMixin._update_display_impl()` (`src/sase/ace/tui/widgets/prompt_panel/_agent_display.py:139`).
3. That builds the header with `build_header_text(agent, summary=build_detail_header_summary(agent))`.
4. `build_detail_header_summary()` (`src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py:106`) calls, for any
   agent whose name encodes a bead id, `format_agent_bead_display(agent, include_description=True)`.
5. With `include_description=True`, `format_agent_bead_display_for_name()` (`src/sase/agent/bead_display.py`) calls
   `_lookup_bead_issue()`, which walks a **multi-store fallback chain**: workspace-local stores → marker primary stores
   → `get_read_view()` → `get_project_beads_dirs()` → `get_all_project_beads_dirs()` (the last scans **every** project's
   bead store).
6. For **each** candidate store, `_lookup_bead_issue_in_dirs()` constructs a `BeadProject`, and `BeadProject.__init__`
   (`src/sase/bead/project.py:47`) does `rebuild_from_jsonl()` (mtime-gated JSONL→SQLite rebuild) + `load_config()` +
   `db_mod.init_db()` (SQLite connection), then `project.show()` makes a **Rust FFI** call (`bead_read_facade.show` →
   `bead_show`).

There is **no caching** of the result, so this entire storm repeats on every debounced selection _and_ on every periodic
detail refresh while the bead agent stays selected.

### Why it is intermittent and "for a while"

- Cost scales with **how deep the fallback chain must go**. If the bead resolves from the first (workspace-local) store
  it is one project open; if not, it falls through to `get_all_project_beads_dirs()` and opens/initializes a
  `BeadProject` per store across _every_ project — many `stat`s, config loads, SQLite inits, and FFI calls.
- `rebuild_from_jsonl()` is mtime-gated, but while agents are actively running (exactly when the user is browsing the
  Agents tab) the JSONL store is frequently newer than the SQLite mirror, so **real rebuilds** fire.

### Why the immediate path does NOT freeze

The cheap/immediate header path (`update_header_only` → `build_header_text(cheap=True)`) uses
`format_agent_bead_display(include_description=False)`, which only runs `derive_agent_bead_id_from_name()` — pure regex,
no store access. It already renders the bead id with no description. So only the **enriched description lookup** is
expensive, and only on the debounced/full path.

This matches the TUI perf memory: "Never block the event loop" and "Debounce detail panels, never the highlight." The
detail update _is_ debounced, but the debounced work itself blocks — debounce only collapses N keypresses into one
paint; that one paint still freezes.

## Fix (high-level design)

Keep the expensive enriched bead lookup **off the event loop** and **memoize** it, exactly mirroring the established
async worker pattern already used for workflow detail rendering (`WorkflowDisplayMixin.start_workflow_detail_render` /
`on_worker_state_changed` in `src/sase/ace/tui/widgets/prompt_panel/_workflow_display.py`). The header renders
immediately with the cheap `bead_id`; the description fills in a moment later once a background thread resolves it, and
stays cached for subsequent selections/refreshes.

### 1. Bead-display cache + resolver (TUI models layer)

In `src/sase/ace/tui/models/agent_bead.py` (TUI-specific wrapper; keeps the shared `bead_display.py` pure), add a small,
thread-safe, **TTL-bounded** cache keyed by bead id (the identity of the resolved issue):

- `cached_bead_display(agent)` → returns the cached enriched display, or a "miss" sentinel.
- `resolve_bead_display(agent)` → performs the heavy `format_agent_bead_display(include_description=True)` and stores
  the result. **Only ever called from a worker thread.**

TTL (e.g. ~60 s) lets descriptions eventually refresh without re-blocking on every tick; a bounded size prevents
unbounded growth. A stale bead title for at most the TTL window is harmless.

### 2. Make the synchronous header path cheap

In `build_detail_header_summary()` (`src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`), replace the
synchronous `format_agent_bead_display(include_description=True)` with a cache consult:

- **Cache hit** → use the enriched display.
- **Cache miss** → fall back to the cheap `bead_id`-only display (`include_description=False`, pure regex). Never call
  `_lookup_bead_issue` on the event loop.

### 3. Resolve off-thread and re-render when ready

In `AgentDisplayMixin` (`src/sase/ace/tui/widgets/prompt_panel/_agent_display.py`), after rendering the header, if the
agent has a bead id whose enriched display is not yet cached, start a `run_worker(..., thread=True)` that calls
`resolve_bead_display(agent)`. On `SUCCESS`, if the selection is still current (generation + agent-identity guard, like
the workflow worker), re-render the header — the cache is now warm, so it is cheap and shows the description.
Supersede/cancel any prior in-flight bead worker on a new selection.

**MRO note:** `AgentPromptPanel` composes `AgentDisplayMixin, AgentHintsDisplayMixin, WorkflowDisplayMixin, Static`, and
only `WorkflowDisplayMixin` currently defines `on_worker_state_changed`. Adding a handler to `AgentDisplayMixin` must
chain via `super().on_worker_state_changed(event)` (or be unified into one dispatcher) so the existing workflow-detail
worker still receives its events. Each applier already no-ops when the event's worker is not its own.

### Result

- First time a bead agent is selected: header paints instantly with the bead id; the description appears a beat later —
  **no freeze**.
- Subsequent selections / periodic refreshes of bead agents: cache hit → cheap, no store access on the event loop.

## Scope / non-goals

- **Backend inefficiency noted, not fixed here.** The deeper cause (a full `rebuild_from_jsonl` + SQLite init on _every_
  `BeadProject` open, and the broad `get_all_project_beads_dirs` fallback scan) is core-backend behavior governed by the
  Rust-core boundary memory; reworking bead-store opening/caching is a larger, riskier change in `../sase-core`/`bead`
  and is out of scope for this freeze fix. Flag as a potential follow-up.
- **Other header enrichments left as-is.** Embedded workflows, deltas, artifacts, memory reads, and skill uses in
  `build_detail_header_summary` use cached JSON/artifact loaders and are not the reported freeze. Revisit only if
  profiling shows them hot.

## Verification

Per the perf memory's "measure, don't guess":

1. **Reproduce/measure before & after** with `SASE_TUI_PERF=1 sase ace` (per-j/k key-to-paint JSONL at
   `~/.sase/perf/tui_jk.jsonl`; target p95 < 16 ms) and/or `sase ace --profile`, selecting a bead agent.
2. **Tests:**
   - Selecting a bead agent does not invoke the heavy `_lookup_bead_issue` on the event loop when the cache is cold
     (synchronous summary returns the cheap display and schedules a worker).
   - Cache hit returns the enriched display.
   - The generation/identity guard discards a stale worker result when the selection has moved on.
3. `just install` then `just check` (lint + mypy + tests). Run `just test-visual` if the header-rendering snapshots are
   affected (the Bead line now shows the id first, then the description fills in).
