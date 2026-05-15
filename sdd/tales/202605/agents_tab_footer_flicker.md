---
create_time: 2026-05-14 21:25:37
status: done
prompt: sdd/prompts/202605/agents_tab_footer_flicker.md
---
# Fix Agents-tab footer flicker + leaked "/ edit query" hint

## Symptom

While the user is on the Agents tab in `sase ace`, the keybinding footer constantly flickers between the correct
agent-specific bindings and a state that shows `/ edit query` — a hint that belongs only on the CLs tab.

## Root cause

The keybinding footer is a **single shared widget** (`#keybinding-footer`, composed once in `app.py:281`), rendered for
every tab. Tab-specific code paths are responsible for writing tab-appropriate bindings into it. The bug is that the
**ChangeSpec display refresh writes to the footer regardless of which tab is active**, clobbering the Agents-tab footer
whenever a CL-side refresh fires.

Trace:

1. `_apply_reloaded_changespecs` in `src/sase/ace/tui/actions/changespec/_loading.py:211` already branches on
   `on_changespecs_tab` for state bookkeeping (lines 219–268) but unconditionally calls `self._refresh_display()` at
   line 276.
2. `_refresh_display_impl` (`actions/changespec/_display.py:343`) eventually reaches either `_apply_detail_panel_update`
   (line 250: `footer_widget.update_bindings(...)`) or `_apply_empty_footer_update` (line 269:
   `footer_widget.show_empty(project_name=...)`).
3. `show_empty()` (`widgets/keybinding_footer.py:332`) renders exactly the `<edit_query_key> edit query` hint the user
   is seeing. With no selected ChangeSpec (common when off-tab and the cursor/filter is empty) this is the branch that
   fires.
4. Immediately after, the Agents-tab's own refresh path (`actions/agents/_display_detail.py:138`,
   `footer_widget.update_agent_bindings(...)`) writes the correct bindings back. The two writers alternate → flicker.

### Triggering events (while user is on Agents tab)

The two `_refresh_display()` callers that fire off-tab:

- **Inotify watcher** — `_on_artifact_change` (`actions/_event_refresh.py:68-69`) calls
  `_schedule_changespecs_async_refresh` unconditionally; on an active project this fires constantly, which is why the
  bug manifests as steady flicker rather than a one-shot glitch.
- Any future code path that calls `_apply_changespecs` / `_apply_reloaded_changespecs` while off the changespecs tab.

The periodic auto-refresh (`actions/_event_refresh.py:181`) is already gated on `current_tab == "changespecs"`, so the
inotify path is the dominant source.

### Why this convention matters

`src/sase/ace/AGENTS.md` is explicit:

> A keymap appears in the footer if and only if it has a condition that is sometimes true and sometimes false. Global
> actions (quit, refresh, tab switch, fold, **edit query**, etc.) belong in the help modal only.

`show_empty()` already bends this rule on the CLs tab (empty-list affordance to recover from a bad query). That
trade-off is acceptable while _on_ the CLs tab, but it must not leak to other tabs.

## Fix approach

Make the changespec-display refresh **a no-op for the shared footer when called off-tab**, while preserving its job of
updating the (hidden) changespec panels and internal state.

Two complementary guards:

1. **Skip the footer write in the changespec display helpers when `current_tab != "changespecs"`.**
   - In `_apply_detail_panel_update` and `_apply_empty_footer_update` (`actions/changespec/_display.py`), early-return
     the footer-touching branch when the active tab is not "changespecs". The list / detail / ancestors widgets can
     still be updated harmlessly (they live inside the hidden `#changespecs-view`).
   - Alternative: keep the helpers tab-agnostic and gate the call in `_refresh_display_impl` /
     `_refresh_changespec_detail_only_impl` instead. Slightly cleaner because the gate lives at one well-defined
     boundary.

2. **(Optional, cheap) Skip the entire `_refresh_display()` call in `_apply_reloaded_changespecs` when off-tab**,
   mirroring the existing `_changespecs_last_idx` / `_changespecs_last_name` save-while-off-tab pattern (lines 230,
   260–268). `watch_current_tab` at `app.py:339` already re-runs `_refresh_display()` on tab return, so nothing is lost.
   This avoids the wasted hidden-widget repaint as well as the footer flicker.

The recommended combination is **#1 (defense-in-depth on the helpers) plus #2 (skip the obvious wasted work)**. #1 alone
fixes the symptom; #2 also removes the pointless widget churn that triggered it.

## Files to change

- `src/sase/ace/tui/actions/changespec/_display.py`
  - Add a `current_tab == "changespecs"` guard around the footer-touching branch in `_apply_detail_panel_update` (lines
    239–252) and around the `footer_widget.show_empty(...)` call in `_apply_empty_footer_update` (lines 254–269). The
    mode-prefix branches (fold/leader/bang/copy/custom) are still relevant cross-tab because they're driven by transient
    modal state, but on the changespecs path they're already handled by the agents-tab's own
    `_apply_agent_detail_update` and the global leader/bang/copy bindings — so the simplest, safest gate is _all_ footer
    writes from the CL display helpers.
- `src/sase/ace/tui/actions/changespec/_loading.py`
  - In `_apply_reloaded_changespecs`, only call `_refresh_display()` when `on_changespecs_tab` is True (the variable is
    already computed at line 219). When off-tab the freshly applied data sits ready and `watch_current_tab` will paint
    on switch-back.

No production-side changes to `keybinding_footer.py`, the agents display, the event-refresh loop, or `watch_current_tab`
should be needed — the bug is purely "wrong writer wins the footer race".

## Verification

1. **Manual** — launch `sase ace`, switch to the Agents tab, touch any `~/.sase/projects/**/*.gp` file (e.g. `touch` a
   CL file) in a loop and confirm the footer no longer flashes the `/ edit query` hint. Repeat with active background CL
   writes (mailing a CL, etc.) to make sure the inotify watcher cannot trigger the regression.
2. **Tab-switch correctness** — switch back to the CLs tab and confirm the footer immediately renders the correct
   CL-context bindings (including the empty-state `edit query` hint when the filtered list is empty).
3. **Snapshots / TUI tests** — run `just test` (and `just test-visual` if any footer snapshot is in scope) and add a
   targeted test for the new invariant: invoking the changespec display refresh while `current_tab == "agents"` must not
   call `KeybindingFooter.show_empty` / `update_bindings`. The cleanest seam is a unit test that monkey-patches the
   footer widget with a recording double and asserts zero calls.
4. **`just check`** before reporting completion (per workspace rules).

## Out of scope

- Re-evaluating whether `show_empty()` should display the `edit query` hint at all (the AGENTS.md convention says global
  actions belong in the help modal). That is a separate UX decision; this change only stops the hint from bleeding
  off-tab.
- Refactoring the shared `#keybinding-footer` into per-tab footer widgets. Could be revisited later as a structural fix,
  but is much larger than the reported bug warrants.
