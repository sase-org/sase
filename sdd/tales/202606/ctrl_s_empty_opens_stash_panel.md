---
create_time: 2026-06-24 15:01:13
status: done
prompt: sdd/prompts/202606/ctrl_s_empty_opens_stash_panel.md
---
# Plan: `<Ctrl+S>` on an empty prompt opens the prompt stash panel

## Goal

Extend the prompt-local `<Ctrl+S>` keymap so that **when the active prompt pane is empty (nothing typed), `<Ctrl+S>`
opens the unified prompt stash panel instead of toasting a "Nothing to stash" no-op**.

- **Non-empty active pane** → `<Ctrl+S>` stashes the current pane exactly as today (unchanged).
- **Empty active pane** → `<Ctrl+S>` opens the unified stash picker (`StashedPromptsModal`), identical to `Ctrl+G p`. If
  the stash store itself is also empty, the panel-open path toasts "No stashed prompts to restore" (the standard
  empty-store toast), rather than the old "Nothing to stash".

The result is a single convenient key: with text, it stashes; with no text, it lets you pull a stash back. This mirrors
how some editors overload a save key — "save what you have, or if there's nothing, show me what I saved earlier."

## Background / Context

`<Ctrl+S>` is a **prompt-widget-local** keymap (not a global app binding, not in the keymap registry). The key is
intercepted in the prompt text area's key handler and dispatched to the bar:

- `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py:171-178` — on `ctrl+s`, stops the event and calls
  `bar.stash_active_pane()`.
- `src/sase/ace/tui/widgets/_prompt_input_bar_stack_actions.py:348-377` — `stash_active_pane()`:
  1. Guards to prompt mode only: `if self._mode != "prompt": return` (feedback / approve-prompt bars: complete no-op).
  2. Syncs widget state, reads `text = self._stack.selected_item.text.strip()`.
  3. **If empty:** posts `self.Stashed([], source="current", dismiss_bar=False)` and returns.
  4. Otherwise: captures the pane as a `StashedPromptPane`, removes it, posts `Stashed([pane], ...)`.

The empty post is handled app-side in `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash.py:31-43`
(`on_prompt_input_bar_stashed`), whose empty branch toasts **"Nothing to stash"** and returns without touching the store
or badge.

### The panel already has a fully-wired open path we can reuse

The same bar mixin already exposes `request_open_prompt_stash()`
(`src/sase/ace/tui/widgets/_prompt_input_bar_stack_actions.py:408-416`), which is what `Ctrl+G p` uses:

```python
def request_open_prompt_stash(self) -> None:
    """Ask the app to open the unified prompt-stash panel. ... Posted in every
    mode so the app can toast a no-op when restore is unavailable."""
    self.post_message(self.RestoreRequested(self._mode))
```

The app handles `RestoreRequested` in `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash.py:116-122`
(`on_prompt_input_bar_restore_requested`) → `_open_prompt_stash_panel(bar_mode=event.mode)`, which:

- Guards non-`prompt` bars with the "Restore is only available for agent prompts" toast.
- Reads the stash snapshot off-thread.
- Toasts "No stashed prompts to restore" when the store is empty.
- Otherwise pushes the `StashedPromptsModal` picker (and `auto_restore_single` stays `False`, so it always shows the
  picker — never the `@`-style single-entry auto-restore).

So the empty branch of `stash_active_pane` only needs to call `self.request_open_prompt_stash()` instead of posting the
empty `Stashed`. Because that branch sits **after** the prompt-mode guard, the mode passed to `RestoreRequested` is
always `"prompt"`, which cleanly satisfies the app-side restore guard.

### Key facts established during exploration

1. **No `sase-core`, wire, or facade change.** This is pure presentation/orchestration glue reusing already-shipped
   primitives: the bar's `request_open_prompt_stash()`, the `RestoreRequested` message, and the app's
   `_open_prompt_stash_panel`. The "empty `<Ctrl+S>` opens the panel" decision is a TUI interaction choice, not shared
   domain behavior — no web/CLI/editor frontend needs a matching wire/API (per `memory/rust_core_backend_boundary.md`:
   presentation glue stays in this repo).

2. **"Empty" means the stripped active pane is blank** — `self._stack.selected_item.text.strip()` is falsy. This already
   covers whitespace-only drafts, which `.strip()` reduces to empty. No new emptiness logic is introduced; the existing
   check is simply rerouted.

3. **Panel-always, not auto-restore-single.** The user asked to "trigger the prompt stash panel," i.e. show the picker.
   Reusing `request_open_prompt_stash()` (→ `auto_restore_single=False`) gives exactly that. The `@`-style auto-restore
   of a lone entry is intentionally **not** adopted here — `<Ctrl+S>`-on-empty behaves like `Ctrl+G p`.

4. **Mode guard preserved.** In feedback / approve-prompt bars, `stash_active_pane` still returns at the top, so empty
   `<Ctrl+S>` stays a complete no-op there (it does **not** open the panel). This matches today's behavior and the
   restore-is-prompt-only rule.

5. **Empty-store wording changes for this path.** When both the prompt and the stash store are empty, empty `<Ctrl+S>`
   now routes to the panel-open path and toasts **"No stashed prompts to restore"** instead of "Nothing to stash". This
   is intended and more accurate (there is nothing to stash _and_ nothing to restore; we chose to surface the restore
   affordance). The "Nothing to stash" toast remains reachable via the `Ctrl+G s` "stash all" all-empty path (see
   scope).

## Design

### Behavior matrix for `<Ctrl+S>` (`stash_active_pane`)

| Prompt bar state                                           | `<Ctrl+S>` behavior (new)                                      |
| ---------------------------------------------------------- | -------------------------------------------------------------- |
| prompt mode, active pane has text                          | Stash current pane (unchanged)                                 |
| prompt mode, active pane empty/whitespace, stash non-empty | Open `StashedPromptsModal` picker (like `Ctrl+G p`)            |
| prompt mode, active pane empty, stash empty                | Toast "No stashed prompts to restore" (panel-open empty toast) |
| feedback / approve-prompt bar                              | No-op (unchanged; never opens the panel)                       |

`Ctrl+G p`, `@`, and `Ctrl+G s` (stash all) are all unchanged.

### Implementation approach

Reroute the single empty branch of `stash_active_pane` to the existing panel-open request. No new message, no
app-handler change.

In `src/sase/ace/tui/widgets/_prompt_input_bar_stack_actions.py`:

1. **`stash_active_pane` empty branch** — replace

   ```python
   if not text:
       self.post_message(self.Stashed([], source="current", dismiss_bar=False))
       return
   ```

   with

   ```python
   if not text:
       # Nothing to stash: surface the stash panel so an empty <Ctrl+S> can be
       # used to pull a previously stashed prompt back instead of being a no-op.
       self.request_open_prompt_stash()
       return
   ```

2. **`stash_active_pane` docstring** — update the trailing sentence ("An empty pane stashes nothing — an empty `Stashed`
   is posted so the app can toast a no-op.") to describe the new behavior: an empty active pane opens the unified stash
   panel (via `RestoreRequested`) so the user can restore a stashed prompt; in non-`prompt` bars `<Ctrl+S>` remains a
   no-op.

No other source change is required: `request_open_prompt_stash()`, the `RestoreRequested` message,
`on_prompt_input_bar_restore_requested`, and `_open_prompt_stash_panel` are all reused as-is.

## Scope of changes

### A. App/widget glue — `src/sase/ace/tui/widgets/_prompt_input_bar_stack_actions.py`

- `stash_active_pane`: reroute the empty branch from `post_message(Stashed([], ...))` to `request_open_prompt_stash()`;
  update the docstring.

### B. Docs (this repo) — required by the ACE help-sync rule

Per `src/sase/ace/AGENTS.md` ("Help Popup Maintenance": changing a `sase ace` keymap's behavior **must** update the `?`
help popup):

- `src/sase/ace/tui/modals/help_modal/binding_common.py:30` — the shared "Prompt Input" section entry
  `("Ctrl+S", "Stash current pane")` should be reworded to convey the dual behavior, within the help's **32-char
  description limit** (per `src/sase/ace/AGENTS.md` "Help Modal Box Formatting"). Suggested:
  `("Ctrl+S", "Stash pane (panel if empty)")` (27 chars). The implementer may pick equivalent wording ≤ 32 chars.
- `tests/test_keymaps_display_help.py:119` asserts `("Ctrl+S", "Stash current pane") in pairs`; update this expected
  pair to match the new wording.

This is a single shared help section (rendered on all tabs), so one edit covers agents / axe / changespecs.

### C. Tests

**Widget-level — `tests/ace/tui/widgets/test_prompt_stash_restore_keymap.py`** (extend; the existing `_RestoreApp`
harness already records `RestoreRequested`):

1. **Empty pane + `Ctrl+S` opens the panel:** `_RestoreApp("")`, `await pilot.press("ctrl+s")`; assert
   `len(app.restore_requests) == 1` and `app.restore_requests[0].mode == "prompt"`.
2. **Whitespace-only pane + `Ctrl+S` opens the panel:** `_RestoreApp("   ")`, press `ctrl+s`; assert one
   `RestoreRequested` with mode `"prompt"` (confirms `.strip()` emptiness still routes to the panel).
3. **Non-empty pane + `Ctrl+S` does NOT open the panel (regression):** `_RestoreApp("draft")`, press `ctrl+s`; assert
   `app.restore_requests == []`. To assert the stash still fires, extend `_RestoreApp` with an
   `on_prompt_input_bar_stashed` recorder (append events to a `self.stash_events` list) and assert one `Stashed` event
   with a non-empty `panes` list. (Alternatively assert the active pane text was consumed; the message recorder is
   preferred for a direct behavioral assertion.)
4. **Feedback mode + `Ctrl+S` is a no-op (mode-guard regression):** `_RestoreApp("", mode="feedback")`, press `ctrl+s`;
   assert `app.restore_requests == []` (and, with the recorder from #3, no `Stashed` event) — empty `<Ctrl+S>` never
   opens the panel outside prompt mode.

Update the module docstring to note that empty `<Ctrl+S>` now posts `RestoreRequested` (opens the panel) while a
non-empty `<Ctrl+S>` still stashes.

**App-level — no new tests required.** The change is confined to the bar widget; the app's `RestoreRequested` → panel
path (open picker / empty-store toast / mode guard) is already covered by
`tests/ace/tui/actions/test_prompt_stash_restore.py`. The empty-`Stashed` "Nothing to stash" handler
(`tests/ace/tui/actions/test_prompt_stash_handler.py`) is unchanged and still exercised by the `Ctrl+G s` all-empty
path, so it stays green.

## Out of scope / explicitly deferred

- **`Ctrl+G s` (stash all) when every pane is empty** — unchanged; it still posts an empty `Stashed(source="all")` and
  the app toasts "Nothing to stash". Only the single-pane `<Ctrl+S>` keymap gains the open-panel behavior, matching the
  user's request. (Extending the same affordance to `Ctrl+G s` is a deliberate, easy follow-up if desired, but is not
  done here to keep the change scoped.)
- **`@` / `Ctrl+G p` / the picker (`StashedPromptsModal`), the wire, the facade, the Rust core** — unchanged.
- **Auto-restore-single from `<Ctrl+S>`** — not adopted; `<Ctrl+S>`-on-empty always opens the picker.
- **`bindings.py`, `default_config.yml`, the keymap registry, the footer** — unchanged (`<Ctrl+S>` is prompt-local and
  not registry-bound).

## Verification

1. `just install` (ephemeral workspace may have stale deps), then `just check` (ruff + mypy + fast tests).
2. Targeted: `tests/ace/tui/widgets/test_prompt_stash_restore_keymap.py`,
   `tests/ace/tui/actions/test_prompt_stash_restore.py`, `tests/ace/tui/actions/test_prompt_stash_handler.py`, and
   `tests/test_keymaps_display_help.py`.
3. **No visual-snapshot impact.** There is no help-modal PNG golden, and the change only affects the empty-pane
   `<Ctrl+S>` interaction (no rendering change to any snapshotted state). The ACE PNG suite is unaffected.
4. **Manual sanity (optional)** in `sase ace`:
   - Type a prompt, press `<Ctrl+S>` → it stashes (unchanged).
   - With an empty prompt bar and at least one stashed prompt, press `<Ctrl+S>` → the stash panel opens.
   - With an empty prompt bar and an empty stash, press `<Ctrl+S>` → "No stashed prompts to restore" toast.
   - In a feedback bar, press `<Ctrl+S>` → nothing happens (no-op).

## Risks / Notes

- **Boundary correctness.** Pure presentation/orchestration glue reusing the bar's existing
  `request_open_prompt_stash()` and the app's existing panel-open path; no `sase-core`, wire, or facade change (per
  `memory/rust_core_backend_boundary.md`).
- **Toast wording shift.** The empty-prompt + empty-store case moves from "Nothing to stash" to "No stashed prompts to
  restore". Intended and documented above; the "Nothing to stash" toast remains reachable via `Ctrl+G s` on all-empty.
- **Docs-sync.** The `?` help entry and its keymap-display test are updated together so they stay in lockstep (ACE
  help-sync convention).
- **Plan-file portability.** All paths are repo-relative; no workspace-specific directories referenced.
