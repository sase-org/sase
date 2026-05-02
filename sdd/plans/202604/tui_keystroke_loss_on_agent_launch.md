---
create_time: 2026-04-23 14:50:14
status: done
prompt: sdd/prompts/202604/tui_keystroke_loss_on_agent_launch.md
---

# TUI Keystroke Loss on Agent Launch

## Problem

In the `sase ace` TUI, when the user presses `<enter>` to launch an agent (submitting the PromptInputBar) and then
quickly presses `j` or `k`, those `j`/`k` keystrokes appear to be lost. After a short delay (~100–300 ms), `j`/`k` work
normally and move the selection in the ChangeSpec / Agent list as expected.

This matters because the post-launch list-navigation keys are part of the natural flow — the user expects to be able to
immediately start navigating to the next ChangeSpec after kicking off an agent. Losing input breaks the "instant
refresh" promise of commit `ea03d270` ("Make `sase ace` TUI refresh feel instant").

## Root Cause

Two mechanisms combine to swallow the keystrokes:

### 1. The event loop is blocked for the entire submission path

`AgentLaunchMixin._finish_agent_launch` (at `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py:49-319`) runs
**synchronously** on the Textual event loop. On the happy path it performs:

- VCS ref resolution and agent-ref resolution (file I/O, subprocess calls)
- `record_vcs_xprompt_usage` (file I/O)
- Home-mode workspace scanning via `_resolve_vcs_from_prompt` (filesystem walk)
- `add_or_update_prompt` + `_record_prompt_file_references` (file I/O)
- `process_xprompt_references` (file I/O + parsing)
- `threading.Thread(...).start()` (`_agent_launch.py:316`) — cheap, but comes after everything above
- `self.notify(...)` at the end (cheap)

The message handler `on_prompt_input_bar_submitted` (`_prompt_bar.py:309-331`) is a plain `def`, not `async def`, so it
runs to completion inside Textual's message pump. While it runs, **no other messages drain** — including `Key` events.
Any `j`/`k` the user presses during this window is buffered at the terminal layer and delivered only once the handler
returns.

### 2. Focus is left "dangling" on a detached widget when the pump resumes

Partway through the handler, `_unmount_prompt_bar` (`_prompt_bar.py:176-196`) forcibly detaches the PromptInputBar:

```python
parent = bar._parent
if parent is not None:
    parent._nodes._remove(bar)
bar.remove()
```

The existing code comment explains why: if we only call `bar.remove()` (async removal), a subsequent `mount()` of a new
bar with the same ID races and hits `DuplicateIds`. So we synchronously yank the widget out of its parent's `_nodes`
list first.

The side effect is that **Textual's focus-transfer machinery is bypassed**. `bar.remove()` normally blurs the focused
descendant (PromptTextArea) and hands focus to the next focusable sibling. Because the widget has already been ripped
out of the tree, Textual's DescendantBlurred / focus-forwarding logic has nothing to walk; `Screen.focused` is left
pointing at the detached PromptTextArea, or cleared to `None` without assigning a new focus target.

When the handler finally returns and the message pump drains the queued `j` / `k` Key events:

- If `Screen.focused` still references the detached PromptTextArea, Textual dispatches the key to a widget that is no
  longer part of the DOM — it is silently absorbed (or would have been "typed into" the unmounted TextArea as an
  `i`/`j`/`k` character insertion, invisible because the widget isn't rendered).
- If `Screen.focused` is `None`, the App-level `j` / `k` bindings from `src/sase/ace/tui/bindings.py:8-9` would fire —
  but in practice, with the `_nodes._remove` hack, focus is left pointing at the old widget, so this path is not hit.

Either way, the keystroke does not reach `next_changespec` / `prev_changespec`, which is exactly the reported symptom.

### Why the delay "fixes" it

After `_finish_agent_launch` returns, the message pump resumes. The forcibly-detached bar's async `remove()` eventually
completes, at which point Textual runs its normal blur and focus-transfer logic, and subsequent `j`/`k` routes correctly
(to the App bindings or the newly-focused list). By the time the human reacts (≥150 ms), the system has settled.

## High-Level Design

The fix has two complementary parts. Part **A** is the root-cause fix for dropped keystrokes; Part **B** shrinks the
window in which the problem can occur and aligns with the spirit of the "feel instant" work.

### Part A — Establish focus on a concrete widget before unmounting the bar (root cause)

Before the forcible `_nodes._remove(bar)` runs, explicitly move focus to the widget that _should_ own navigation keys
after the bar disappears. This is the tab's list widget (e.g. the ChangeSpec list on the CLs tab, the AgentList on the
Agents tab).

Concretely, in `_unmount_prompt_bar` (`_prompt_bar.py:176-196`):

1. Before the `parent._nodes._remove(bar)` line, query for the appropriate post-unmount focus target (via a small helper
   that knows the active tab, or by delegating to an existing method if one is available). If a target is found, call
   `.focus()` on it.
2. Keep the `_nodes._remove(bar)` + `bar.remove()` sequence intact — that hack is still needed to avoid DuplicateIds on
   rapid re-mounts.
3. If the bar's own descendant is currently focused (`Screen.focused` is inside the bar), ensure we first transfer focus
   _out_ of the bar, then do the detach.

This guarantees that when the handler returns and queued key events drain, `Screen.focused` points at a live widget that
either handles `j`/`k` itself (lists generally have their own navigation), or cleanly falls through to the App-level
bindings. Either way, the user's keystrokes reach their intended target.

### Part B — Remove the blocking window around the launch

Reduce how long the event loop is blocked by the submit handler so fewer keys queue up and the unmount->refocus gap is
smaller:

1. **Unmount first, then do work.** Restructure `_finish_agent_launch` so it:
   - Regenerates the timestamp,
   - Calls `_unmount_prompt_bar()` (with Part A's focus fix in place),
   - Schedules the heavy work (VCS resolution, history writes, xprompt expansion, thread-start) via
     `self.call_after_refresh(...)` or an asyncio worker.
2. Move pure I/O (history writes, `record_vcs_xprompt_usage`, `_record_prompt_file_references`) off the event loop using
   Textual's `run_worker` / `@work(thread=True)`. These have no user-visible synchronous return contract.
3. Keep the existing `threading.Thread` for the subprocess launch; just make sure we get to `thread.start()` as quickly
   as possible after the bar is unmounted.

Part B alone would **not** fix the bug (the window can still be non-zero and focus would still dangle), but combined
with Part A it makes the system robust even against heavier future work in the launch path.

### Non-goals

- Don't drop or flush pending stdin — that's user-hostile and hides real latency.
- Don't introduce a "launching" modal / lockout screen — breaks the instant-refresh UX.
- Don't undo the `_nodes._remove` hack; re-mount DuplicateIds is a separate concern and the hack is correct for its
  stated purpose.
- Don't special-case `j`/`k`. The fix must also cover any other key a user types in the post-launch window.

## Files Touched

- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar.py`
  - `_unmount_prompt_bar`: transfer focus to a concrete post-unmount target _before_ detaching.
  - Possibly add a small helper `_post_unmount_focus_target()` that returns the right widget for the currently active
    tab (AgentList on Agents tab, ChangeSpec list on CLs tab, etc.).
- `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`
  - `_finish_agent_launch`: reorder so `_unmount_prompt_bar()` runs first, then push remaining I/O onto
    `call_after_refresh` / `run_worker`.
  - Apply the same ordering tweak to the bulk / multi-prompt / multi-model / repeat launch paths that also call
    `_unmount_prompt_bar` (to keep behaviour consistent across all launch flavors).
- `src/sase/ace/tui/widgets/prompt_input_bar.py` — probably untouched, but verify `PromptInputBar` doesn't have its own
  `on_unmount` logic that would interfere with the focus transfer.

## Test Plan

Automated (unit / snapshot where possible):

- Add a Textual pilot test in `tests/ace/tui/` that mounts AceApp, opens the prompt bar, types a trivial prompt, presses
  `enter`, immediately presses `j`, and asserts that the ChangeSpec list's selected index advanced by one. Run with both
  a fast happy-path and a deliberately slowed launch (monkeypatch one of the I/O helpers to `time.sleep(0.2)`) to prove
  the fix is robust against a blocked event loop.
- Add a unit test for `_unmount_prompt_bar` verifying `Screen.focused` points at a live (mounted) widget after the call,
  never at a detached node.

Manual:

- Launch `sase ace` in a real workspace. Press `space` to open a prompt, type a short prompt, press `<enter>`
  immediately followed by `jjjkk`. Confirm the selection moves by net +1.
- Repeat on the Agents tab.
- Repeat for the multi-prompt path (`---` separator), the repeat directive (`%r:3`), and the multi-model directive
  (`%m(opus,sonnet)`).
- Repeat in home mode (launched from `~`) where `_resolve_vcs_from_prompt` does extra work.
- Confirm that `just check` passes.

## Risks & Open Questions

- **Focus target selection.** The correct post-unmount focus target depends on the active tab. We need a reliable way to
  pick it — either by querying the existing "which tab is active" state on AceApp, or by focusing the nearest focusable
  sibling of the just-removed bar. Worth checking whether AceApp already exposes a helper.
- **Interaction with feedback / approve_prompt modes.** The same unmount path runs for plan-feedback and approve-prompt
  submissions, which have different return flows. The focus target for those modes may be different (a plan modal, an
  agent detail pane). The fix must either pick a correct target per mode or fall back to `self.focus_next()` so behavior
  is at worst "some live widget is focused".
- **Textual version.** The `parent._nodes._remove` hack is implementation-detail coupling. If Textual updates change
  that internal layout, the unmount helper breaks anyway — the fix should not make that coupling any tighter.
