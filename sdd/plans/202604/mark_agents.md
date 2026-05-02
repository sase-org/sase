---
create_time: 2026-04-22 14:37:23
status: wip
prompt: sdd/prompts/202604/mark_agents.md
---

# Mark Agents on the `sase ace` "Agents" Tab

## Context & Motivation

The `sase ace` TUI "CLs" tab already supports a mark/bulk workflow keyed on `m`: each press toggles a green `[✓]`
indicator on the selected ChangeSpec and stores its index in `AceApp.marked_indices`. When marks exist, the user can run
bulk operations (today: `S` for bulk status change) against all marked entries. The footer also shows the current mark
count.

The "Agents" tab has no such affordance today. Its `x` key kills or dismisses only the single currently-selected agent
(via `AgentKillPinMixin.action_kill_agent`, `_kill_pin.py:26`). Users who want to kill/dismiss many entries at once must
do them one-by-one, or reach for the leader-mode "kill & dismiss all" (`,X` → `_kill_and_dismiss_all_agents`) which
operates on _everything_ rather than a user-curated subset.

This plan adds a mark workflow on the Agents tab that mirrors the CLs-tab pattern. Pressing `m` toggles a mark on the
selected agent/workflow entry, and pressing `x` while marks exist kills/dismisses the full marked set in one shot
(falling back to the existing single-entry behavior when no marks exist).

## Scope

In scope:

- New `m` (mark/unmark) action on the Agents tab.
- New `u` (clear all marks) action on the Agents tab (matches CLs tab for symmetry — there is no good reason to have
  marks on one tab use `u` and the other require a different key).
- Overloaded `x` (kill/dismiss) behavior on the Agents tab: operates on the marked set when any marks exist, otherwise
  preserves today's single-entry behavior byte-for-byte.
- Visual `[✓]` mark prefix in the agent list (both main and pinned panels).
- Footer updates that surface the mark count and the "unmark" affordance while marks exist, and relabel `x` to "kill N
  marked" / "dismiss N marked" when applicable.
- Help modal ("Agent Actions" section) updated so the `?` popup documents the new keymaps.
- Tests that exercise the toggle, clear, bulk-kill, and no-marks fall-through paths.

Out of scope:

- Bulk status change for agents (agents don't have CL-style statuses; the equivalent on the CLs tab is
  `S bulk_change_status` and has no analog here).
- Any change to the CLs-tab marking behavior.
- Any change to Axe-tab behavior.
- Any change to the leader-mode `,X` "kill & dismiss all" shortcut (stays as the "all agents" sledgehammer, distinct
  from the user-curated marked set).

## Behavior Design

1. **`m` (mark/unmark)**
   - Pressed on the Agents tab, toggles the mark on the currently-selected agent (using `_get_selected_agent()` so the
     currently-focused panel — main or pinned — is respected).
   - Auto-advances the cursor to the next entry within the same panel (with wraparound), mirroring the CLs-tab ergonomic
     that lets a user `m m m m` through a run of adjacent entries without a navigation key between each press.
   - No-ops with a warning notification (`"No agent selected"`) when the panel is empty.

2. **`u` (clear all marks)**
   - Pressed on the Agents tab, clears every marked agent and emits `"Cleared N mark(s)"` — identical to the CLs-tab
     semantics.
   - No-ops with `"No marks to clear"` if the set is already empty.

3. **`x` (kill/dismiss)**
   - When **no agent marks exist**, fall through to today's `action_kill_agent` logic exactly as currently implemented
     (single selected agent, DISMISSABLE → dismiss, PID None → dismiss, PID set → `ConfirmKillModal` then kill).
   - When **any agent marks exist**, operate on the marked set:
     - Partition marked agents into killables (has PID and not in `DISMISSABLE_STATUSES`) and dismissables
       (DONE/FAILED/PLAN DONE, or PID None).
     - Reuse `ConfirmKillAllModal` (already used by leader-mode `,X`) with a description that enumerates the marked
       entries, distinguishing the two groups. Confirmation is required even for pure-dismissal to make the bulk effect
       explicit.
     - On confirm: run the existing `_do_kill_agent` / `_do_dismiss_all` helpers agent-by-agent. This reuses all of the
       per-agent-type kill dispatch (workflow, hook, mentor, crs, running) and workspace-release bookkeeping that
       already exists — no new kill logic.
     - After the bulk op, clear `_marked_agents` (the agents are gone) and refresh the display.
   - Tab dispatch still goes through the existing `action_kill_agent` (changespecs → toggle_hide_submitted, axe →
     toggle_or_kill_axe_view). The new branch is introduced only inside the `current_tab == "agents"` case, before
     `_get_selected_agent()` is consulted.

4. **Auto-clear on dismissal from elsewhere**
   - Today, an agent can vanish from `_agents` between frames because the loader refilters against dismissed identities,
     or because the user triggered `,X` kill-all, etc. The marked set must not hold onto stale identities forever. The
     refresh path (`_refresh_agents_display`) will intersect `_marked_agents` with the identity set of `_agents` before
     rendering — dropped identities are pruned. This keeps the footer count honest and prevents phantom marks from
     resurrecting if an agent with the same identity reappears after revive.

5. **Pinned agents + marks**
   - Marks are an **explicit** user selection, so marking a pinned agent and then pressing `x` dismisses it even though
     `,X` (kill-all) skips pinned. Rationale: the user has already said "these specific ones." Keeping pin protection
     here would be surprising and force an awkward "unpin, then mark, then x" dance.
   - This is a deliberate asymmetry with `,X` and will be called out in the commit message and help popup line.

6. **Workflow parents + children**
   - A marked workflow parent already cascades to its children via `_do_kill_agent` / `_do_dismiss_all` today. If the
     user marks _both_ the parent and one of its children, iterate over a snapshot of the marked list and skip
     identities that `_agents_with_children` no longer contains after earlier iterations — prevents "agent already
     dismissed" errors.

## Data Model

- New `AceApp` instance field (not reactive; follows the `_pinned_agents` / `_dismissed_agents` pattern):

  ```python
  _marked_agents: set[tuple[AgentType, str, str | None]]
  ```

  Initialized to an empty set in `AceApp.__init__`, beside `_pinned_agents` and `_dismissed_agents`.

- **Why identities instead of indices?** Unlike `marked_indices` on the CLs tab (which stores `int` indices into
  `self.changespecs`), the agent list is rebuilt far more aggressively — on every refresh tick, after folding changes,
  after reordering, after dismissals in memory. Index-based marks would drift on every rebuild and would require either
  a per-refresh remap or the same "clear marks after bulk op" hack the CLs tab uses. Identity tuples are the stable
  natural key already used by `_pinned_agents`, `_dismissed_agents`, and `_agent_status_overrides`. Reusing that key
  gives us free resilience to list rebuilds.

- Not persisted to disk. Marks are ephemeral within a single TUI session. Persistence would complicate the UX (stale
  marks after restart) for no obvious benefit.

## Keymap Design

- `m` and `u` are already registered in `default_config.yml` as `toggle_mark` / `clear_marks` and in `bindings.py`.
  Today both are CLs-only (the action bodies early-return when `current_tab != "changespecs"`). The plan reuses these
  same bindings and actions, turning them into tab-dispatch actions:

  | Action key           | Today's behavior                    | New behavior                                                                 |
  | -------------------- | ----------------------------------- | ---------------------------------------------------------------------------- |
  | `action_toggle_mark` | No-op off changespecs tab           | Dispatches: changespecs → current logic; agents → new `_toggle_mark_agent()` |
  | `action_clear_marks` | No-op off changespecs tab           | Dispatches: changespecs → current logic; agents → new `_clear_agent_marks()` |
  | `action_kill_agent`  | changespecs / axe / agents branches | Same branches; agents branch gets a pre-check for `_marked_agents` non-empty |

- No new entries in `default_config.yml`, `AppKeymaps`, `_BINDING_META`, or `bindings.py`. Same keys, broader scope.

## Implementation Outline (files to change)

1. `src/sase/ace/tui/app.py`
   - Declare `_marked_agents: set[tuple[AgentType, str, str | None]]` in `__init__` beside `_pinned_agents`.
   - Add the mixin for agent marking (see #3) to the `AceApp` inheritance list.

2. `src/sase/ace/tui/actions/agents/_marking.py` _(new file)_
   - `AgentMarkingMixin` with:
     - `_toggle_mark_agent(self) -> None` — toggle selected agent's identity, advance cursor within panel, refresh
       display.
     - `_clear_agent_marks(self) -> None` — clear `_marked_agents`, notify, refresh display.
     - `_bulk_kill_marked_agents(self) -> None` — partition marked agents into killables / dismissables (handle cascade
       skips), show `ConfirmKillAllModal`, on confirm call existing `_do_kill_agent` / `_do_dismiss_all`, then clear
       `_marked_agents`.
     - `_prune_stale_marked_agents(self) -> None` — intersect `_marked_agents` with the identities present in `_agents`.

3. `src/sase/ace/tui/actions/agents/__init__.py` and `src/sase/ace/tui/actions/__init__.py`
   - Export `AgentMarkingMixin` from the agents package and surface it in the top-level `actions` re-export so `app.py`
     can import it next to `AgentsMixin`.

4. `src/sase/ace/tui/actions/agents/_core.py`
   - Add `AgentMarkingMixin` to `AgentsMixinCore`'s bases (so agent-mixin consumers of `self._marked_agents` see the
     type via `AgentsMixinCore`). Also declare `_marked_agents` in the TYPE_CHECKING block alongside `_pinned_agents`.

5. `src/sase/ace/tui/actions/marking.py`
   - In `action_toggle_mark`, replace the early return with a tab dispatch: `current_tab == "changespecs"` → existing
     body (extract to a private helper `_toggle_mark_changespec` if it makes the dispatch tidy);
     `current_tab == "agents"` → `self._toggle_mark_agent()`; else no-op.
   - Same dispatch for `action_clear_marks`.
   - Leave `action_bulk_change_status` untouched — it is CLs-only and stays that way.

6. `src/sase/ace/tui/actions/agents/_kill_pin.py`
   - In `action_kill_agent`, inside the `current_tab == "agents"` branch, add a pre-check: if `self._marked_agents` is
     non-empty, call `self._bulk_kill_marked_agents()` and return. Otherwise fall through to the existing single-agent
     body.

7. `src/sase/ace/tui/widgets/agent_list.py`
   - Add `marked_agents: set[...] | None = None` parameter to `AgentList.update_list` and thread it to
     `_format_agent_option` as a per-row `is_marked: bool`.
   - In `_format_agent_option`, render `[✓] ` (same style as CLs: `bold #00D700`) right before the existing hint/approve
     icons. Keeps the visual language identical between tabs.

8. `src/sase/ace/tui/actions/agents/_display.py`
   - `_refresh_agents_display(list_changed=True)`: prune stale marks once at entry, then pass
     `marked_agents=self._marked_agents` to both `agent_list.update_list(...)` and `pinned_list.update_list(...)` calls.
   - In `_apply_agent_detail_update`, pass a new `marked_count` kwarg to `footer_widget.update_agent_bindings(...)`.

9. `src/sase/ace/tui/widgets/keybinding_footer.py`
   - Add `marked_count: int = 0` to `update_agent_bindings` and `_compute_agent_bindings`.
   - When `marked_count > 0`:
     - Change the `x` label on the Agents tab to `kill/dismiss (N marked)` — use a single label since the bulk op may
       hit a mix of killables and dismissables.
     - Append `(self._kd("clear_marks"), f"unmark ({marked_count})")` — same treatment as the CLs-tab footer does today.

10. `src/sase/ace/tui/modals/help_modal/bindings.py`
    - In `agents_bindings` → "Agent Actions" section, add the three lines:
      - `(d(a.toggle_mark), "Mark/unmark current agent")`
      - `(d(a.clear_marks), "Clear all agent marks")`
      - Update the existing `(d(a.kill_agent), "Kill / dismiss agent")` to clarify the bulk-on-marks behavior, e.g.
        `"Kill / dismiss agent (or all marked)"`.

11. `src/sase/ace/AGENTS.md`
    - No mandatory update, but the "Footer Keybinding Convention" section is a good spot to call out that `m`/`u` now
      live on both CLs and Agents tabs via tab-dispatch actions, so future tabs adding marks follow the same pattern.

12. Tests
    - `tests/ace/tui/test_agent_marking.py` _(new)_ — snapshot-style tests against `AceApp`:
      - `m` on agents tab toggles mark, advances cursor, and second press un-toggles.
      - `m` on agents tab with no agents emits warning and does not mutate `_marked_agents`.
      - `m` on changespecs tab does not touch `_marked_agents`; `m` on agents tab does not touch `marked_indices`.
      - `u` on agents tab clears `_marked_agents`.
      - `x` with marks present invokes `ConfirmKillAllModal` (patched to auto-confirm) and leaves `_marked_agents`
        empty; `_do_kill_agent` and `_do_dismiss_all` called with the right partitions.
      - `x` with no marks falls back to the single-agent kill path (regression guard).
      - Stale-identity pruning: inject an identity not present in `_agents`, verify
        `_refresh_agents_display(list_changed=True)` prunes it.
    - Extend `tests/ace/tui/widgets/test_agent_display.py` to cover the `[✓]` prefix render when `marked_agents` is
      passed.

## Rendering Changes

- `AgentList._format_agent_option` prepends `[✓] ` in `bold #00D700` when `is_marked=True`. This slot goes immediately
  after the optional jump-hint `[X] ` prefix and before the approve/child/pin/done icons. Order is chosen so that the
  mark column visually aligns across rows — marks live at the left edge just like on the CLs tab.
- `_PADDING` / width calculations need to account for the mark prefix the same way the CLs list does. The simplest path
  is to include the `[✓] ` width in the per-row `max_width` accumulator when `is_marked=True`, which we get for free by
  rendering it into the `Text`.

## Footer Changes

- **With marks (agents tab, `marked_count > 0`)**:
  - `x` label becomes `kill/dismiss (N marked)`.
  - `u` appears with label `unmark (N)`.
  - All other agent-tab bindings render as before. (Panel-switch affordance, pin/unpin, etc., stay.)
- **Without marks**: unchanged footer.

## Help Modal Changes

- In `agents_bindings`, add two rows to "Agent Actions": `m — Mark/unmark current agent`, `u — Clear all agent marks`.
  Relabel the existing `x` row to communicate bulk fall-through. Maintain the 32-char cap on descriptions.

## Open Design Decisions (called out for user awareness)

1. **Marks override pin protection.** Explicit marks beat implicit pin protection when running `x`. If this is wrong,
   the alternative is to skip pinned agents from the bulk op and notify the user how many were skipped.
2. **Shared `m`/`u` actions, tab dispatch inside.** Alternative: introduce `toggle_mark_agent` / `clear_agent_marks` as
   distinct `AppKeymaps` entries. I chose the dispatch approach because `x` already does tab dispatch for `kill_agent`;
   keeping the same pattern across all tri-dispatched actions avoids forcing users to rebind two keys in their config to
   get consistent behavior.
3. **Identity-keyed mark set.** See "Why identities instead of indices?" above. Happy to switch to indices if alignment
   with CLs tab is more important than resilience.
4. **Single confirm modal for bulk x.** Even a pure-dismissal bulk pops the confirm modal, whereas single-agent dismiss
   today is silent. This matches `_kill_and_dismiss_all_agents` behavior and avoids "I pressed `x` once and five agents
   vanished without warning."
5. **No persistence.** Marks don't survive a TUI restart. Same as CLs-tab marks today.

## Test Plan

- Unit tests as enumerated in "Implementation Outline" #12.
- Manual smoke test with a populated agents tab:
  1. Mark two running agents + one DONE agent, press `x`, confirm → all three handled by the appropriate kill/dismiss
     path.
  2. Mark three agents, press `u` → marks cleared; footer reverts.
  3. Mark one agent, `Tab` to CLs tab, mark one CL, `Tab` back → agent mark still present and independent of CLs mark.
  4. Mark a workflow parent and one of its children, press `x`, confirm → no crash; children correctly cascaded without
     double-dismiss.
  5. Press `x` with no marks → single-agent behavior preserved.
- `just check` must pass (lint + mypy + pytest).
