---
create_time: 2026-06-25 08:34:09
status: done
prompt: sdd/prompts/202606/all_panel_agent_completion.md
---
# Plan: Source `#fork` / `%wait` agent-name completion from ALL visible Agents-tab panels

## Problem / Product Context

The ACE prompt input offers agent-name completion for two surfaces:

- `#fork:` / `#fork(` — pick a visible agent to fork/resume.
- `%wait:` / `%w:` — pick visible agent(s) to wait on (comma-separated).

Today both menus only list agents that are visible in the **currently focused** Agents-tab panel. When the Agents tab is
split into multiple tag panels, agents living in a non-focused panel are silently absent from the completion menu, so
the user cannot complete their names without first navigating focus to the panel that holds them.

The desired behavior: both `#fork` and `%wait` completion should offer **every agent name visible anywhere on the Agents
tab**, across all panels — not just the focused panel.

## Root Cause

All agent-name completion candidates ultimately come from one function:

`visible_agent_completion_agents(app)` in `src/sase/ace/tui/agent_completion.py`.

The consumer chain is:

- Prompt input (`#fork`/`%wait`) → `PromptTextArea._snapshot_agent_completion_candidates()`
  (`src/sase/ace/tui/widgets/_file_completion_base.py`) → `app.visible_agent_completion_candidates()`.
- `visible_agent_completion_candidates()` (app method, `src/sase/ace/tui/actions/agents/_wait_resume.py`) →
  `build_agent_completion_candidates(self._visible_agent_completion_agents())`.
- `self._visible_agent_completion_agents()` → `visible_agent_completion_agents(self)` (the single source function).

`visible_agent_completion_agents` reads `_panel_group.focused_idx`, queries the **one** `AgentList` widget for that
focused panel via `panel_widget_id(focused_idx)`, and returns `widget.visible_agents()`. That is the entire scoping bug:
it deliberately looks at only the focused panel. (Its model-level fallback, used when no widget can be queried, already
returns all rendered agents — so only the widget-query branch is panel-scoped.)

Because both `#fork` and `%wait` flow through this same function, fixing it once fixes both directives. The fix is
naturally general — no per-directive branching.

## High-Level Design

Change `visible_agent_completion_agents(app)` to aggregate the visible agents from **all** panels instead of just the
focused one:

1. Determine the panel count from `_panel_group.panel_keys` (the authoritative set of mounted panels; widgets are
   mounted with ids `panel_widget_id(i)` for `i in range(len(panel_keys))`, exactly the pattern already used in
   `src/sase/ace/tui/actions/agents/_display_panel_refresh.py`).
2. For each panel index `i in range(len(panel_keys))`, query its `AgentList` widget by `panel_widget_id(i)` and collect
   `widget.visible_agents()`. Skip panels whose widget can't be found (`NoMatches`).
3. Concatenate the per-panel results in panel-index order, de-duplicating by `agent.identity` while preserving first
   occurrence (each agent maps to exactly one panel key, so this is a cheap safety net rather than a real merge —
   matching the per-panel de-dup `AgentList.visible_agents()` already does).
4. Only when **no** panel widget could be queried at all (e.g. before mount, or in lightweight test harnesses without a
   real `query_one`) fall back to the existing model-level path (`_agents_visible_order` /
   `agent_is_rendered_in_agents_panel`), which is already all-agents (not panel-scoped).

`build_agent_completion_candidates` already de-duplicates by prompt name, so even if aggregation ever produced a
repeated name it is collapsed downstream; the identity de-dup in step 3 keeps the agent list itself clean and ordering
stable.

### Why "visible agents per widget" rather than the model-level all-agents path

The widget's `visible_agents()` reflects what is actually rendered — it honors hidden workflow children (the `h`/`l`
hide/reveal keymaps), search filters, and banner skipping. The model-level fallback does not. Aggregating each panel's
rendered rows therefore preserves the precise "visible on the Agents tab" semantics the user is asking for, just widened
from one panel to all panels. The model path stays only as the no-widgets fallback it already is.

### Behavior in merged-panel mode

When tag panels are merged (`merge_tag_panels`), `panel_keys == [None]` and there is a single panel at index 0.
Iterating `range(1)` collects that one merged panel — identical to today. No special case needed.

### Ordering note (intentional, minor)

Previously the menu listed only the focused panel's agents. Now it lists agents in panel-index order (panel 0 rows, then
panel 1 rows, ...). Agent names are unique per agent, so this is purely additive — no candidate that appeared before
disappears; non-focused-panel agents are appended in a deterministic, on-screen order.

## Blast Radius / Shared Consumer

`visible_agent_completion_agents` (via `_visible_agent_completion_agents()`) is also the candidate source for the **wait
modal** (the `w` key on a WAITING/active agent — `_show_wait_modal` → `_wait_modal_candidates` →
`_visible_wait_candidate_agents`). Widening the source therefore also makes the wait modal offer agents from all panels.

This is intentional and consistent: the wait modal is the modal equivalent of the `%wait` directive, and the user's
request ("all agent names visible on the agents tab") applies equally there. The plan treats this as a deliberate,
desirable consequence of fixing the single shared source rather than something to special-case away. If the user wants
the wait modal to stay focused-panel-scoped, the function would need a parameter — but that re-introduces the divergence
this change is meant to remove, so the default is to unify.

## Why This Layer (no Rust core change)

This is presentation-only Textual glue. The data source is the **live set of rendered TUI widget rows across the
on-screen panels** — which panels exist, which rows are hidden/revealed, what is scrolled/filtered. That state lives
only in the Textual widget tree of this app; no web app, CLI, or editor frontend shares "the Agents-tab panels and their
visible rows." By the `rust_core_backend_boundary.md` litmus test, this is not shared backend behavior, so no
`sase-core` wire/binding change is required. The agent-name candidate _model_ (`AgentCompletionCandidate`) and the
completion _grammar_ already live in this repo and are unchanged.

## Performance

Per `tui_perf.md`, the binding constraint is "never block the event loop with synchronous disk I/O / parsing." This
change does none: `AgentList.visible_agents()` is a pure in-memory walk of already-rendered row entries (no disk, no
JSON, no subprocess). Aggregation is O(total visible rows) across a handful of panels, and the result is already cached
per-menu in `PromptTextArea._agent_completion_candidates` (`_snapshot_agent_completion_candidates`), so it does not
recompute on every keystroke — only when a completion menu first opens. The added cost is iterating a few extra
already-built widgets, which is negligible.

## Documentation / Glossary

The glossary entry **"Agent-name Completion (`%wait` / `#fork`)"** in `memory/glossary.md` currently states candidates
come "from the agents currently visible in the **focused** Agents-tab panel." After this change that sentence is
inaccurate and should read "from the agents currently visible **across all** Agents-tab panels."

`memory/glossary.md` is a protected memory file ("You should not modify any of these memory files without approval from
the user"). This plan proposes the one-line wording update as an explicit, gated step: it will be made only with the
user's approval (approving this plan, or a separate confirmation). The implementation does not depend on it; it is a
docs-accuracy follow-up.

## Testing

- **New unit test for the source function** (best home: `tests/ace/tui/test_agent_completion.py`, which already imports
  from `sase.ace.tui.agent_completion`, or a small dedicated module). Using a minimal fake app — `_panel_group` set to a
  multi-panel `AgentPanelGroup` and a `query_one` returning a distinct fake `AgentList` per `panel_widget_id(i)`, each
  with its own `visible_agents()` — assert that `visible_agent_completion_agents(app)`:
  - returns agents aggregated from **every** panel (not just the focused one),
  - preserves panel-index then in-panel order,
  - de-dups by identity,
  - still returns the full all-agents fallback when `query_one` is unavailable / finds no panels. Model the fake-app
    harness on `_Bare` in `tests/ace/tui/test_agent_panel_index_integration.py` (which already builds
    `AgentPanelGroup.from_agents(...)` and a fake `query_one`).
- **Regression guard for the directive surfaces**: confirm the existing
  `tests/ace/tui/widgets/test_xprompt_arg_value_completion.py` (`#fork:` agent menu) and the `%wait` cases in
  `tests/ace/tui/widgets/test_directive_completion_interactions.py` still pass. These stub
  `app.visible_agent_completion_candidates` directly, so they are unaffected by the source change; they verify the
  consumer contract is intact.
- No change to `build_agent_completion_candidates` / `filter_agent_completion_candidates` behavior, so their existing
  tests stand.

## Verification

- `just install` then `just check` (ruff + mypy + tests) in the workspace.
- Manual smoke in `sase ace`: with the Agents tab split into 2+ tag panels and focus on one panel, open the prompt and
  type `#fork:` — confirm agents from the **other** panel(s) now appear in the menu. Repeat with `%wait:` / `%w:`.
  Confirm focus position no longer affects which agents are offered.

## Files Expected to Change

- `src/sase/ace/tui/agent_completion.py` — rewrite `visible_agent_completion_agents` to aggregate visible agents across
  all panels (de-duped, ordered), keeping the model-level fallback for the no-widget case; update its docstring.
- `src/sase/ace/tui/actions/agents/_wait_resume.py` — update the now-stale "focused Agents panel" docstrings on
  `_visible_agent_completion_agents`, `_visible_wait_candidate_agents`, and `visible_agent_completion_candidates` to say
  "all visible Agents-tab panels" (no behavior change; the methods just delegate to the widened source).
- `tests/ace/tui/test_agent_completion.py` (or a new focused test module) — add the multi-panel aggregation + fallback
  unit test.
- `memory/glossary.md` — **gated on user approval**: update the "Agent-name Completion" entry from "focused Agents-tab
  panel" to "across all Agents-tab panels."
