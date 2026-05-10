---
create_time: 2026-05-10 11:43:12
status: done
prompt: sdd/prompts/202605/remove_tab_title_counts.md
---
# Plan: Remove counts from ace TUI tab titles

## Context

The ace TUI has a custom `TabBar` widget at `src/sase/ace/tui/widgets/tab_bar.py` rendering three tabs at the top of the
screen:

- **CLs** — currently rendered as e.g. `CLs (5 s2 h3)` where `5` is the main ChangeSpec count, `s2` are submitted (when
  shown), `h3` are reverted/archived (when shown)
- **Agents** — e.g. `Agents (3 d1 h2)` where `3` are manual running agents, `d1` are dismissable/done, `h2` are hidden
  running agents (when shown). During first load it shows `Agents …` (italic ellipsis).
- **AXE** — e.g. `AXE (2 d1 h3)` where `2` are running lumberjacks, `d1` are completed bgcmds, `h3` are active bgcmds
  (when shown)

The user wants every count suffix removed so each tab renders as just its bare name (e.g. `CLs`, `Agents`, `AXE`). The
motivation is a hunch that recomputing/updating these counts is contributing to TUI refresh cost.

This plan covers the main top-level `TabBar` only. Agent panel border titles (e.g. `#tag · 5 [S2 R1 W1 D1]`) and the
`agent_info_panel` top-bar metrics (`5 Agents [...]`) are panels, not tabs, and are explicitly **out of scope** unless
the user later asks for them.

## Goals

1. Tabs render as plain names: `CLs`, `Agents`, `AXE` — no count digits, no key-hint letters, no parentheses, no loading
   ellipsis.
2. All count plumbing that exists _solely_ to feed those tab-title suffixes is removed (state fields on `TabBar`, public
   update methods, callers that compute counts, and the per-query reverted/submitted bookkeeping if no other consumer
   exists).
3. Tab click hit-testing still works (the (start, end) ranges used by `on_click` must still be computed correctly for
   the simpler labels).
4. Tab-active styling (bold + colored when active, muted gray when inactive) is preserved.
5. The first-load behavior for Agents (currently `Agents …`) needs an explicit decision — see Open Questions.

## Non-goals

- No change to agent panel border titles or the `agent_info_panel` metrics bar.
- No change to keybindings, footer hints, or the help modal (the help modal documents the `s`/`h`/`d` toggles separately
  from the tab-bar suffix; only references that _describe the tab-bar suffix specifically_ need updating).
- No refactor of agent/changespec/axe loading flows beyond ripping out the count-feeding callers.

## Files to change

### Primary

- `src/sase/ace/tui/widgets/tab_bar.py` — strip count state, count parameters, and the `_append_tab_with_suffix`
  count-suffix branch. Keep the active/inactive styling and click-range computation. Likely the tab builder collapses to
  a small loop over `[(name, color, is_active), ...]` writing just `" {name} "` styled.

### Callers to remove or simplify

- `src/sase/ace/tui/actions/changespec/_display.py` — remove `_update_cls_tab_count` and its callers in
  `_apply_reloaded_changespecs` / surrounding flow. If `self._query_reverted_count` and `self._query_submitted_count`
  exist _only_ to feed this method, remove their bookkeeping too.
- `src/sase/ace/tui/actions/changespec/_loading.py` — drop the two `_update_cls_tab_count` calls (currently around lines
  68 and 290).
- `src/sase/ace/tui/actions/agents/_display.py` — remove `_refresh_tab_bar_agent_counts` and the `manual_running` /
  `hidden_running` / `done_visible` `sum()` walks over `self._agents`. Drop callsites in agent display, dismissal, and
  refresh paths.
- `src/sase/ace/tui/actions/agents/_loading_finalize.py` — drop the call near line 318.
- `src/sase/ace/tui/actions/axe_display/_loaders.py` — remove `_update_axe_tab_count` and the lumberjack-status / bgcmd
  count derivation that exists only for the tab.
- `src/sase/ace/tui/app.py` — if any reactive watcher or filter-toggle path calls one of the now-removed methods, drop
  the call. The `current_tab` watcher's `tab_bar.update_tab(new_tab)` call must be preserved.

### Tests

- `tests/` (Textual snapshot/unit tests for `TabBar` and tab counts) — search for `update_cls_count`,
  `update_agents_count`, `update_axe_count`, and any snapshot string matching `CLs (`, `Agents (`, `AXE (`. Update
  snapshots; delete tests that purely assert count behavior.

### Docs / help

- `src/sase/ace/tui/widgets/help_modal.py` — only edit if it explicitly documents the `(N s# h# d#)` suffix layout. If
  it just lists the toggle keys (`s`/`h`/`d` actions), leave it.

## Phasing

This is a single coherent change; one PR is appropriate. Suggested commit slices for review legibility:

1. **`tab_bar.py`**: collapse the widget to plain labels. Keep the public `update_*` methods as no-ops temporarily so
   callers don't break mid-PR. _(Optional — skip if doing it all in one commit.)_
2. **Caller removal**: delete the count-computing callers in changespec / agents / axe display modules and any per-query
   count bookkeeping that becomes dead.
3. **API cleanup**: delete the now-unused `update_cls_count` / `update_agents_count` / `update_axe_count` methods and
   TabBar count state fields.
4. **Tests + snapshots**: regenerate snapshots, drop count-specific tests.

If doing it as a single commit, the order inside the commit is: callers first, then the TabBar rewrite, so
dead-method-removal lands cleanly.

## Open questions for the user

1. **Agent loading state** — today the Agents tab renders `Agents …` (dim italic ellipsis) until the first agent load
   completes, distinguishing "still loading" from "no agents". With counts gone, do you want:
   - (a) Drop the ellipsis too (simplest — tab is always just `Agents`), or
   - (b) Keep the ellipsis-while-loading affordance (small bit of state preserved on `TabBar`)?

   Recommendation: **(a)** — it's consistent with "do less on refreshes" and matches the user's framing.

2. **Hide-toggle discoverability** — the suffix doubles as a reminder that `s`/`h`/`d` toggle visibility. After removal,
   those keys are still in the help modal but no longer hinted on the tab bar. Acceptable, or do you want a one-time
   hint elsewhere?

## Performance reality check

Worth being honest with the user about expected impact:

- The count update methods (`update_cls_count` / `update_agents_count` / `update_axe_count`) all early-exit when nothing
  changed, so a steady-state TUI already does ~zero work here per refresh.
- The `sum(...)` walks over `self._agents` in `_refresh_tab_bar_agent_counts` are O(n) but only fire on agent-list
  mutation events (load, dismissal, refresh), not per-keystroke.
- The most likely real win is **avoiding the rich-text rebuild in `_build_content` + the Static.update redraw** that
  fires whenever any of those counts changes. If counts are removed entirely, `_build_content` runs only on tab switch
  and on registry changes — much rarer.
- Net: the change is justified on UX/simplicity grounds; the perf gain is likely small but real (one fewer Static
  repaint per agent/changespec mutation, plus the removed `sum()` walks). I'll measure with `tui_trace` instrumentation
  if the user wants concrete numbers, but I would not promise a visible perf improvement up front.

## Verification

- `just check` (lint + typecheck + tests) passes from the workspace.
- Manual TUI smoke test: launch ace, switch between tabs, kick off a few agents and a couple of axe commands, toggle
  `s`/`h`/`d`, confirm tab labels stay simple and click-to-switch still works.
- Confirm Textual snapshot tests for the tab bar are regenerated and reviewed.
