---
create_time: 2026-06-24 14:52:58
status: done
---
# Plan: `@` keymap auto-restores the lone stash entry (pinned ⇒ keep, unpinned ⇒ pop)

## Goal

Change the global `@` keymap (the `restore_prompt_stash` action) so that **when the prompt stash holds exactly one
entry, `@` restores it directly instead of opening the picker**:

- **Unpinned lone entry** → restore it into the prompt bar **and pop it** (remove from the stash).
- **Pinned lone entry** → restore it into the prompt bar **but keep it** stashed (not popped/deleted).

When the stash holds **0** entries, `@` keeps its current "No stashed prompts to restore" toast. When it holds **2+**
entries, `@` keeps opening the unified picker (`StashedPromptsModal`) exactly as today.

The unified picker stays reachable in every case via the prompt-local **`Ctrl+G p`** keymap in the prompt input widget,
whose behavior is **unchanged** (it always opens the panel, even when there is a single entry). This is the explicit
requirement: auto-restore-single is specific to `@`; `Ctrl+G p` remains the way to open the panel.

## Background / Context

The prompt stash is a single per-user pile of stashed prompt drafts persisted as JSONL at `~/.sase/prompt_stash.jsonl`.
All read/append/pop/pin persistence lives in the Rust core (`sase-core`, crate `sase_core`), is exposed to Python via
the `sase_core_rs` PyO3 extension, and is fronted here by a thin Python facade. Each stash entry already carries a
persistent `pinned: bool` flag (the recently-landed "persistent prompt stash pins" work; `pinned` is on
`PromptStashEntryWire` and the store ops ship today on `master`).

Two keymaps currently funnel into the **same** panel-open flow:

- **Global `@`** — `Binding("at", "restore_prompt_stash", "Restore Prompt Stash", show=False)` in
  `src/sase/ace/tui/bindings.py` → `PromptBarStashMixin.action_restore_prompt_stash()` → `_open_prompt_stash_panel()`
  (no `bar_mode` forced).
- **Prompt-local `Ctrl+G p`** — the prompt input bar's `Ctrl+G` prefix dispatches `p` to `request_open_prompt_stash()`,
  which posts `PromptInputBar.RestoreRequested(mode)`. The app handles it in `on_prompt_input_bar_restore_requested()` →
  `_open_prompt_stash_panel(bar_mode=event.mode)`.

`_open_prompt_stash_panel(bar_mode=None)` (in `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash.py`):

1. Resolves `bar_mode` from the mounted bar when `None` (defaults to `"prompt"` when no bar is mounted).
2. Guards non-`prompt` bars (feedback / approve-prompt) with a "Restore is only available for agent prompts" toast.
3. Reads the snapshot off-thread (`asyncio.to_thread(self._read_prompt_stash_entries)`).
4. Toasts "No stashed prompts to restore" when empty.
5. Otherwise pushes `StashedPromptsModal(entries)` with `_on_prompt_stash_restore_confirmed` as the callback.

On confirm, `_apply_stash_restore(result: StashRestoreResult)` already implements exactly the two outcomes we need:

- `restore_ids = pop_ids + keep_ids` — entries **loaded** into the bar (mounted bar gets new panes via
  `restore_stashed_entries`; if no bar is mounted, the home prompt bar is mounted pre-filled). Bundle rows expand to
  multiple panes.
- `remove_ids = pop_ids + delete_ids` — entries **removed** from the store via `pop_prompt_stash`.
- The badge is refreshed only when the store actually changed; a count-aware toast ("Restored prompt", etc.) is shown.

So a `StashRestoreResult(pop_ids=[id])` is precisely "restore + pop" and a `StashRestoreResult(keep_ids=[id])` is
precisely "restore + keep" — both already covered by tests (`test_confirm_keep_only_*`, the pop tests). The `keep_ids`
transport was deliberately retained as a UI-unreachable capability when `<space>` was repurposed to pinning; **this
change is its first real driver.**

### Key facts established during exploration

1. **No `sase-core` change is needed.** This is keymap-level presentation/orchestration glue that composes existing,
   already-shipped facade primitives (`read_prompt_stash_snapshot`, `pop_prompt_stash`) and reads the already-present
   `entry.pinned` flag. The "open panel vs. auto-restore the single entry" decision is a TUI interaction choice, not
   shared domain behavior — no web/CLI/editor frontend needs a new wire/API to match it. (Per
   `memory/rust_core_backend_boundary.md`: presentation glue stays in this repo.)

2. **"Exactly one entry" means one stash _row_** (`len(self._read_prompt_stash_entries()) == 1`), matching the badge
   count and the picker's title count. A single **bundle** row (multi-prompt, `entry_is_bundle == True`) counts as one
   entry and auto-restores as multiple panes — consistent with how `<enter>` on a lone bundle row pops it in the picker
   today.

3. **Pinned ⇒ keep falls straight out of the `pinned` flag.** Bundles can't be pinned through the UI (pin toggle is
   inert on bundle rows), so a lone bundle naturally has `pinned == False` → pop. The rule
   `keep if entry.pinned else pop` needs no bundle special-casing.

4. **The mode guard is preserved for `@` too.** `@` with no `bar_mode` resolves to the mounted bar's mode; a
   feedback/approve-prompt bar still toasts the no-op. With no bar mounted it resolves to `"prompt"` and auto-restore
   mounts the home prompt bar pre-filled — identical to how panel-confirm restores into a freshly mounted home bar
   today.

5. **`Ctrl+G p` must stay panel-only.** It routes through `RestoreRequested` → `on_prompt_input_bar_restore_requested` →
   `_open_prompt_stash_panel(bar_mode=...)`. Leaving that call free of the new auto-restore flag keeps the panel
   reachable for one-entry stashes, satisfying the requirement.

6. **In-panel keys (`Ctrl+G p`, the picker keys) are documented by the picker's own hint line and the dynamic `Ctrl+G`
   hint panel, not the `?` help modal or footer.** The `?` help and footer document only the global open action (`@` /
   `restore_prompt_stash`) with the description "Restore stashed prompt", which stays broadly accurate (the `@` key
   still restores). See "Docs" for the one wording consideration.

## Design

### Behavior matrix for `@` (`restore_prompt_stash`)

| Stash state              | `@` behavior (new)                                              |
| ------------------------ | --------------------------------------------------------------- |
| 0 entries                | Toast "No stashed prompts to restore" (unchanged)               |
| 1 entry, **unpinned**    | Restore into bar **and pop** it (remove). Badge decrements.     |
| 1 entry, **pinned**      | Restore into bar, **keep** it stashed. Badge unchanged.         |
| 2+ entries               | Open `StashedPromptsModal` picker (unchanged)                   |
| non-`prompt` bar mounted | Toast "Restore is only available for agent prompts" (unchanged) |

`Ctrl+G p` (`RestoreRequested`) is unchanged across the whole matrix: it always opens the picker (or toasts the empty /
mode-guard cases).

### Implementation approach

Thread a single keyword flag through the existing shared open path so the two callers diverge only at the decision
point, and reuse the fully-tested `_apply_stash_restore` transport for the actual restore.

In `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash.py`:

1. **`action_restore_prompt_stash` (the `@` path):** call
   `await self._open_prompt_stash_panel(auto_restore_single=True)` and update its docstring to describe the new
   single-entry auto-restore (pinned ⇒ keep, unpinned ⇒ pop) vs. multi-entry picker, and note the panel stays reachable
   via `Ctrl+G p`.

2. **`_open_prompt_stash_panel(self, bar_mode=None, *, auto_restore_single=False)`:** keep the mode guard, snapshot
   read, and empty toast exactly as-is. After the empty check, insert:

   ```python
   if auto_restore_single and len(entries) == 1:
       await self._auto_restore_single_entry(entries[0])
       return
   self.push_screen(StashedPromptsModal(entries), self._on_prompt_stash_restore_confirmed)
   ```

   Update its docstring to note it may short-circuit to a direct restore when `auto_restore_single` is set and there is
   exactly one entry.

3. **`on_prompt_input_bar_restore_requested` (the `Ctrl+G p` path):** **unchanged** — it calls
   `_open_prompt_stash_panel(bar_mode=event.mode)`, leaving `auto_restore_single` at its `False` default, so it always
   opens the picker.

4. **New helper `_auto_restore_single_entry(self, entry)`:**

   ```python
   async def _auto_restore_single_entry(self, entry: PromptStashEntryWire) -> None:
       from ...modals import StashRestoreResult
       result = (
           StashRestoreResult(keep_ids=[entry.id])
           if entry.pinned
           else StashRestoreResult(pop_ids=[entry.id])
       )
       await self._apply_stash_restore(result)
   ```

   This reuses the existing load-into-bar / conditional-pop / badge-refresh / toast machinery wholesale.

5. **Comment update:** the existing comment in `_apply_stash_restore` ("The current panel does not produce keep ids…")
   is now stale — `@`'s auto-restore-single path produces `keep_ids` for pinned entries. Update that comment (and any
   matching note in the docstring) to reflect that `keep_ids` is now driven by the `@` single-pinned-entry path.

No changes to the modal, the wire, the facade, the bindings table, `default_config.yml`, or the keymap registry: the `@`
binding and the `Ctrl+G p` dispatch entry are unchanged; only the action's app-side behavior changes.

### Toast wording (decision: keep simple)

Because both outcomes load exactly one entry and delete nothing, the shared `_notify_restore_outcome` shows "Restored
prompt" for both the pop and the keep case. This is acceptable and consistent with the picker. (Optional, deferred:
distinguish the pinned/kept case with its own toast — out of scope to keep `_notify_restore_outcome` untouched and the
diff focused.)

## Scope of changes

### A. App glue — `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash.py`

- `action_restore_prompt_stash`: delegate to `_open_prompt_stash_panel(auto_restore_single=True)`; rewrite docstring for
  the new single-entry behavior.
- `_open_prompt_stash_panel`: add the `auto_restore_single: bool = False` keyword-only param; short-circuit to
  `_auto_restore_single_entry` when set and there is exactly one entry; otherwise push the modal as today; update
  docstring.
- Add `_auto_restore_single_entry(entry)` (builds `keep_ids`/`pop_ids` `StashRestoreResult` from `entry.pinned` and
  awaits `_apply_stash_restore`).
- Refresh the now-stale "panel does not produce keep ids" comment/docstring note in `_apply_stash_restore`.

### B. Docs (this repo)

- The `?` help-modal entries for `restore_prompt_stash` (`help_modal/{agents,axe,changespecs}_bindings.py`, all "Restore
  stashed prompt") stay accurate; **no required change**. Consider — within the help's 32-char description limit —
  keeping "Restore stashed prompt" as-is (it still restores) since the open-vs-restore nuance is conditional and the
  picker is documented by the `Ctrl+G` hint panel. The plan recommends **no help-text change**; flagged here per the
  AGENTS help-sync convention so the reviewer can confirm.

### C. Tests — `tests/ace/tui/actions/test_prompt_stash_restore.py`

The existing `_RestoreHarness` / `_FakeBar` / `_seed` / `_point_store_at` scaffolding already drives these handlers
without a live DOM. Add:

1. **`@` single unpinned entry auto-restores + pops:** seed one unpinned row, mount a `_FakeBar("prompt")`, call
   `action_restore_prompt_stash()`. Assert: `harness.pushed == []` (no modal), `bar.restored == [(text, fm)]`, the store
   is now empty, badge updated (`applied_counts == [0]`), toast `("Restored prompt", None)`.

2. **`@` single pinned entry auto-restores + keeps:** gate with `_skip_without_pinned_binding()`; seed one row and set
   `pinned=True` (append `PromptStashEntryWire(..., pinned=True)`, or seed then `set_prompt_stash_pinned`). Call
   `action_restore_prompt_stash()`. Assert: no modal, `bar.restored` set, the entry **remains** in the store, badge
   **not** refreshed (`applied_counts == []`), toast `("Restored prompt", None)`.

3. **`@` single entry, no bar mounted:** `_RestoreHarness(bar=None)`, one unpinned row → `home_mounts` gets the combined
   text, `home_mount_xprompt_markdown == [True]`, store popped.

4. **`@` single bundle entry (unpinned) auto-restores all panes + pops:** seed one `"alpha\n---\nbeta"` row → no modal,
   `bar.restored == [("alpha", fm), ("beta", fm)]`, store empty.

5. **`@` with 2+ entries still opens the picker:** the existing `test_action_restore_prompt_stash_opens_modal` (seeds
   two rows) already covers this; confirm it still passes unchanged. Keep
   `test_action_restore_prompt_stash_empty_store_toasts` for the empty case.

6. **`Ctrl+G p` with a single entry still opens the picker (regression guard):** seed one row, drive
   `on_prompt_input_bar_restore_requested(PromptInputBar.RestoreRequested("prompt"))`, assert `harness.pushed` contains
   a `StashedPromptsModal` and nothing was auto-restored (`bar.restored is None`). This is the core "panel stays
   reachable" assertion.

Update the module docstring to mention the `@`-only auto-restore-single behavior and that `Ctrl+G p` always opens the
picker. If `_seed` needs to set `pinned`, extend it (e.g. an optional `pinned` column or a small `_seed_pinned` helper)
rather than reworking existing callers.

No widget-level changes: `tests/ace/tui/widgets/test_prompt_stash_restore_keymap.py` still holds (the bar still posts
`RestoreRequested` on `Ctrl+G p`; only the app's handling of `@` changed).

## Out of scope / explicitly deferred

- **`Ctrl+G p` behavior** — unchanged; always opens the picker.
- **The picker (`StashedPromptsModal`) keys, layout, pin toggle, bundle inertness** — unchanged.
- **The wire (`PromptStashEntryWire`), the facade, the Rust core** — unchanged (no new field/op; `pinned` and pop
  already exist).
- **`bindings.py`, `default_config.yml`, the keymap registry, the footer** — unchanged.
- **A distinct "kept" toast for the pinned case** — deferred (keeps `_notify_restore_outcome` untouched).
- **Auto-restore for 2+ entries** (e.g. "restore the newest") — out of scope; 2+ keeps the picker.

## Verification

1. `just install` (ephemeral workspace may have stale deps), then `just check` (ruff + mypy + fast tests).
2. Targeted: `tests/ace/tui/actions/test_prompt_stash_restore.py` (new + existing) and
   `tests/ace/tui/widgets/test_prompt_stash_restore_keymap.py`.
3. No visual-snapshot impact (no rendering change); the ACE PNG suite is unaffected.
4. **Manual sanity (optional)** in `sase ace`:
   - Stash exactly one unpinned prompt → press `@` → it loads into the bar and the badge clears (popped).
   - Pin a stashed prompt so it's the only entry → press `@` → it loads into the bar and the badge still shows it
     (kept); press `@` again → it loads again (still kept).
   - With one entry, press `Ctrl+G p` → the picker opens (not auto-restore).
   - With two+ entries, press `@` → the picker opens.

## Risks / Notes

- **Boundary correctness.** Pure presentation/orchestration glue reusing shipped facade primitives and the existing
  `entry.pinned` flag; no `sase-core`, wire, or facade change (per `memory/rust_core_backend_boundary.md`).
- **`keep_ids` is now live.** The `@` single-pinned path is the first real producer of `StashRestoreResult.keep_ids`;
  the transport and its load-without-pop tests already exist, so risk is low — update the stale "not produced by the
  panel" comment so it doesn't mislead.
- **Mode guard parity.** `@` keeps the same `prompt`-mode guard and home-bar-mount fallback as the panel path, so
  auto-restore never fires in feedback/approve-prompt bars.
- **Plan-file portability.** All paths are repo-relative; no workspace-specific directories referenced.
