---
create_time: 2026-06-23 06:03:40
status: done
prompt: sdd/prompts/202606/mark_collapsed_agent_groups.md
---
# Plan: Mark Collapsed Agent Groups on the Agents Tab

## Problem

On the Agents tab of the `sase ace` TUI, the left pane shows agent rows organized into a collapsible group tree (project
/ ChangeSpec / name-root / dotted-prefix banners). When a group is collapsed, its child rows are hidden and the
collapsed **banner row** becomes the selectable cursor stop.

Pressing `m` (mark) while a collapsed group banner is focused is broken:

- It marks only the group's _first_ agent (the banner's representative row), not the group.
- There is **no visual feedback** — banners never render a mark indicator, so the user sees nothing change and the
  action looks like it "did nothing."
- Cursor auto-advance misbehaves: marking auto-advances to the "next visible agent," but the representative agent is
  hidden inside the collapsed group, so the advance logic falls back to a raw index step and the cursor jumps
  unpredictably.

The user wants to mark a collapsed group as a unit and then run all the same marked-set bulk actions (kill/dismiss,
save, revert, tag, wait, kill-and-edit, edit chats, artifacts, unmark) that already work on individually marked rows.

## Root Cause

`AgentMarkingMixin._toggle_mark_agent()` (`src/sase/ace/tui/actions/agents/_marking.py`) resolves its target via
`_get_selected_agent()`, which returns `self._agents[self.current_idx]`. When a collapsed banner is focused,
`_current_group_key` is set and `current_idx` points at the group's first agent (this is how the selection layer
represents "cursor on a banner" — see `resolve_row()` in `widgets/_agent_list_build.py`). The mark action never consults
`_current_group_key`, so it silently degrades to "mark the first member."

The **correct pattern already exists** for the kill action: `AgentKillMixin.action_kill_agent()`
(`actions/agents/_kill_action.py`) checks `_current_group_key`, resolves the focused `GroupRow` via
`_get_focused_group()`, and bulk-acts on every agent in `group.agent_indices` (skipping workflow children, which
cascade). Marking should mirror this.

Once a group's member agents are all in `_marked_agents`, **every existing marked-set bulk action works for free** —
they all key off `_marked_agents` / `_marked_agent_order` only (verified across `_marking.py`, `_revert.py`,
`_tagging.py`, `_wait_resume.py`, `_panel_detail.py`, `_panel_artifacts.py`, `_leader_mode.py`). So the fix is
fundamentally about (a) marking the right set when a banner is focused and (b) showing the user that it worked.

## Goals

1. Pressing `m` on a collapsed group banner toggles the mark on **all top-level agents in that group** (mirroring the
   kill path's group resolution + workflow-child handling).
2. Collapsed banners render a **mark indicator** so group marks are visible — including a distinct "partially marked"
   state when only some members are marked.
3. After marking a group, every existing marked-set action (`x` kill/dismiss, `s` save, `,r` revert, `N`/tag, `,w` wait,
   `,x` kill-and-edit, `e` edit chats, `A` artifacts, `u` unmark) operates on the group's agents with no per-action
   changes required.
4. Cursor behavior after marking a group is predictable (no jump into hidden rows).

## Non-Goals

- No change to how individual (expanded) agent rows are marked.
- No new bulk-action _types_; we only make the existing ones reachable for collapsed groups.
- No change to the grouping/fold model or the `h`/`l` collapse keymaps.

## High-Level Design

### 1. Group-aware mark toggle (core fix)

In `_toggle_mark_agent()`, before the single-agent path, add a branch:

- If `self._current_group_key is not None`, resolve the focused group (reuse the exact `_get_focused_group()` logic from
  `_kill_action.py`; factor it into a shared helper or call through to it so both kill and mark agree on group
  resolution).
- Collect the group's **top-level** member identities: iterate `group.agent_indices` over `self._agents`, skipping
  `is_workflow_child` agents (same rule as `_bulk_kill_group_agents`).
- Toggle semantics: if **all** member identities are already marked, unmark them all; otherwise mark them all (so a
  partially-marked group becomes fully marked). Record/forget via the existing `_record_marked_agent()` /
  `_forget_marked_agent()` so mark **order** is preserved (iterate `agent_indices` in tree order).
- If the group key is stale / resolves to no visible group, fall through to the existing single-agent path (mirrors
  `_kill_action.py`'s fall-through behavior).

### 2. Cursor behavior after a group mark

Single-agent marking auto-advances to the next visible agent. For a banner, the analogous "next stop" must include
banner rows. Recommended: after a group toggle, advance the cursor to the next selectable navigation stop (banner **or**
agent) using the existing `_panel_navigation_stops()` ordering, so the user can mark several collapsed groups in a row
the way they mark several agents in a row. Keep the marked banner visibly marked after the cursor leaves it.

- **Decision (recommended):** advance to the next navigation stop. Acceptable alternative: leave the cursor on the
  banner (simpler, but breaks the "mark, mark, mark" cadence). The plan implements advance-to-next-stop; this is the one
  behavioral choice worth confirming during review.

### 3. Banner mark indicator (visual feedback)

Banners are rendered by `format_banner_option()` / `cached_format_banner_option()`
(`widgets/_agent_list_render_banner.py`), memoized via `banner_render_key()` (`widgets/_agent_list_render_cache.py`).
Currently neither accepts mark state.

- Compute a per-banner mark state in the build loop (`widgets/_agent_list_build.py`, where banners are emitted ~lines
  280–328). For each collapsed `GroupRow`, look at its top-level members (`agent_indices` over the panel `agents`,
  excluding workflow children) and classify as `none` / `partial` / `all` marked, using the `marked` set already in
  scope in `build_list()`.
- Thread that state through `cached_format_banner_option()` and into `banner_render_key()` (so the cache does not serve
  a stale, unmarked banner). Render an indicator consistent with agent rows, which use `"[✓] "` in bold green
  (`#00D700`, see `_agent_list_render_agent.py`):
  - `all` marked → green `[✓]` prefix.
  - `partial` → a dimmer/distinct glyph (e.g. `[~]` or dim `[✓]`) signaling "some marked."
  - `none` → no indicator (unchanged).

### 4. Refresh strategy (perf-aware)

Per `memory/tui_perf.md` (selective updates over full rebuilds; full agent-list rebuilds are the most expensive UI op),
prefer a targeted update:

- Preferred: patch only the affected banner row in place (a small `patch_banner_row` analogous to the existing
  `patch_agent_row`), updating just the banner's mark indicator.
- Acceptable baseline: fall back to `_refresh_agents_display(list_changed=True)` (the same fallback the single-agent
  mark path already uses). A group mark is a deliberate, one-off user action — not a hot j/k autorepeat path — so a
  single rebuild is tolerable if the banner patch is deferred as a follow-up. Implement the patch if it is low-risk;
  otherwise ship with the rebuild fallback and note the optimization.

### 5. Footer / help affordances

- The kill footer already shows `kill/dismiss group` when a banner is focused (`group_focused` branch in
  `_keybinding_bindings.py`) and `... (N marked)` labels when marks exist. Once a group is marked, those marked-set
  labels appear automatically.
- `m` (mark) is a global/help-only binding (not in the conditional footer), so no footer entry is added for it
  (consistent with the footer convention in `src/sase/ace/AGENTS.md`).
- Update the help-modal description for `toggle_mark` (`modals/help_modal/agents_bindings.py`, currently "Mark/unmark
  current agent") to reflect group marking, e.g. "Mark/unmark current agent or focused group." (Per ace `AGENTS.md`, the
  `?` help popup MUST stay in sync with behavior.)

## Affected Code (high level)

- `src/sase/ace/tui/actions/agents/_marking.py` — group-aware branch in `_toggle_mark_agent()`; banner-aware cursor
  advance.
- `src/sase/ace/tui/actions/agents/_kill_action.py` — extract/share `_get_focused_group()` (or expose it for reuse) so
  mark and kill resolve groups identically.
- `src/sase/ace/tui/widgets/_agent_list_build.py` — compute per-banner mark state; thread into banner rendering;
  optional `patch_banner_row`.
- `src/sase/ace/tui/widgets/_agent_list_render_banner.py` — render the mark indicator.
- `src/sase/ace/tui/widgets/_agent_list_render_cache.py` — add mark state to `banner_render_key()`.
- `src/sase/ace/tui/modals/help_modal/agents_bindings.py` — update help text.

## Edge Cases

- **Stale group key** (group no longer visible, e.g. members all dismissed): fall through to the single-agent path; no
  crash (mirror kill).
- **Workflow children**: marked at the top level only; bulk save cascades children via
  `_marked_agent_group_candidates()`, and bulk kill cascades children via the kill machinery — same as marking the rows
  by hand, so no double-marking.
- **Partial pre-existing marks** (user marked some members, then collapsed): `m` marks the rest (toggle-to-all); the
  banner shows the `partial` indicator beforehand and `all` afterward.
- **Nested groups** (e.g. project banner enclosing ChangeSpec/name-root subgroups): `m` acts on exactly the focused
  banner's `agent_indices` (which already include all descendants of that banner), matching how kill on a banner
  behaves.
- **Single-agent group** / non-grouped panels: `_current_group_key` is `None`, so the existing single-agent path runs
  unchanged.
- **`u` (clear marks)** and **`,x` mark-order**: unchanged; group marking funnels through the same
  `_record_marked_agent`/order plumbing.

## Testing

Model new tests on `tests/ace/tui/test_agent_group_kill.py` (same `_FakeApp` harness pattern, `_current_group_key` set
to a banner key):

- Marking a focused collapsed banner marks all top-level members (and records mark order).
- Re-pressing `m` on a fully-marked banner unmarks all members.
- A partially-marked group becomes fully marked on `m` (toggle-to-all).
- Workflow children are not directly marked.
- A stale `_current_group_key` falls through to the single-agent toggle.
- After a group mark, a representative marked-set action (e.g. `_bulk_kill_marked_agents`,
  `_prompt_and_save_marked_agent_group`, revert preconditions, tag/wait prefix builders) sees the full group membership.
- Banner rendering: `format_banner_option` emits the indicator for `all` and `partial` states, and `banner_render_key`
  differs across `none`/`partial`/`all` (cache correctness).
- Cursor advance lands on the next navigation stop (banner or agent), not a hidden row.

Run `just check` after implementation (Python/TUI changes are in scope, so the markdown/bead `just check` exemption does
not apply). Include the ACE PNG snapshot suite for the new banner indicator (`just test-visual`; accept intended visual
changes only with `--sase-update-visual-snapshots`).

## Rollout / Risk

- Behavior is additive and gated on `_current_group_key is not None`; the common single-agent path is untouched.
- Main risk is banner-render cache desync — mitigated by extending `banner_render_key()` with the mark state in the same
  change.
- Reuse of the proven kill-path group resolution keeps mark and kill semantics aligned, so a group that can be marked is
  exactly the group that can be bulk-killed.
