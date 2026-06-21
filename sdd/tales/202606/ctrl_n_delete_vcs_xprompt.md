---
create_time: 2026-06-21 09:53:20
status: done
prompt: sdd/prompts/202606/ctrl_n_delete_vcs_xprompt.md
---
# Prompt `Ctrl+N` Deletes VCS XPrompt; `Ctrl+P` Cycles Through an Empty State

## Goal

Change the prompt input's `Ctrl+N` / `Ctrl+P` VCS xprompt behavior so:

1. **`Ctrl+N`** deletes the first VCS xprompt workflow tag (e.g. `#git:foo`) from the current prompt if one is present,
   and does nothing otherwise. It no longer cycles through MRU history.
2. **`Ctrl+P`** keeps cycling forward through launchable MRU prefixes exactly as today, but the cycle now includes a
   terminal **"no tag shown"** state: after `Ctrl+P` reaches the end of history (the oldest entry), the next press
   removes the tag so the prompt has no VCS workflow shown, and the press after that wraps back to the most-recent
   entry.

This applies to the prompt text area only. Active file-completion navigation keeps its existing precedence over both
keys, and app-level (non-prompt) `Ctrl+N` / `Ctrl+P` agent-file navigation is out of scope.

## Background / Why

A prior attempt (commit reverted as part of "Revert 2 commit(s) from agent '02z.f1'") made `Ctrl+N` delete the tag but
_also removed all MRU cycling_ — it turned `Ctrl+P` into a plain no-op. That over-reached and was reverted. This plan
keeps the good half (deterministic `Ctrl+N` deletion, reusing that attempt's clean deletion helper) **while preserving
`Ctrl+P` cycling**, and folds the deletion into `Ctrl+P`'s cycle as its natural end-of-history "empty" stop.

The reverted attempt's pure deletion function (`_delete_vcs_xprompt_text`: detect the tag via
`find_vcs_workflow_tag_span`, strip one adjacent separator, compute the new cursor) is correct and well-tested and
should be brought back as the shared primitive for both `Ctrl+N` and `Ctrl+P`'s empty stop.

## Current Behavior

The prompt widget routes `Ctrl+N` / `Ctrl+P` (when file completion is not active) to
`VcsMruCyclingMixin._handle_vcs_mru_cycle_key()` in `src/sase/ace/tui/widgets/_vcs_mru_cycling.py`. That mixin:

- loads `load_launchable_vcs_xprompt_mru()` on the keypress,
- computes a next index via `_next_vcs_mru_index()` (`Ctrl+P` steps forward `+1`, `Ctrl+N` steps backward `-1`, modulo
  `len(mru)`),
- and inserts / replaces / prepends a prefix via `_cycle_vcs_mru_text()`.

`_vcs_mru_index` tracks the active cycle position and is reset to `None` on any non-cycling keypress, on submit, and on
opening prompt history. There is no "no tag" stop in the ring today, so cycling never removes a tag — it only swaps
between entries.

## Design

### The cycle ring (for `Ctrl+P`)

Model the forward cycle as a ring of `len(mru) + 1` positions: the `len(mru)` MRU entries plus a single **EMPTY**
position (index `len(mru)`) meaning "no VCS tag in the prompt". `Ctrl+P` always advances `+1` modulo `len(mru) + 1`:

```
EMPTY → mru[0] (most recent) → mru[1] → ... → mru[n-1] (oldest) → EMPTY → mru[0] → ...
```

Starting position on a fresh press (`_vcs_mru_index is None`) is derived from the prompt text, mirroring today:

- prompt has a tag equal (after underscore normalization) to `mru[i]` → start at `i`, advance to `mru[i+1]` (and from
  the oldest `mru[n-1]` → EMPTY);
- prompt has no tag → treat as EMPTY, advance to `mru[0]`;
- prompt has a tag not in the MRU → advance to `mru[0]` (unchanged from today).

When `Ctrl+P` lands on EMPTY it produces a **deletion** edit (remove the current tag) and records the cycle index as the
EMPTY sentinel so the next `Ctrl+P` wraps to `mru[0]`. When the launchable MRU is empty, `Ctrl+P` stays a no-op exactly
as today (no history → nothing to traverse).

### `Ctrl+N` = delete

`Ctrl+N` is decoupled from cycling. Every press deletes the first VCS workflow tag if present, else does nothing. It
does **not** load MRU history or touch disk (a desirable property the reverted attempt established), and it resets the
cycle index to `None` so a subsequent `Ctrl+P` starts cleanly from the now-tagless prompt.

This satisfies the literal requirement (first press deletes the tag if one exists; "does nothing otherwise") and is
naturally idempotent: after the tag is gone, further `Ctrl+N` presses are no-ops.

### Shared deletion primitive

Reintroduce the reverted attempt's pure deletion logic as the single source of truth for "remove the first VCS tag":

- Detect the tag with `find_vcs_workflow_tag_span()` (same parser launch uses; skips fenced code blocks).
- Strip exactly one adjacent separator so no dangling whitespace remains:
  - `#git:foo fix` → `fix`
  - `%n:a #git:foo fix` → `%n:a fix`
  - `fix #git:foo` → `fix`
  - `fix #git:foo more` → `fix more`
  - tag alone on its line followed by a newline does not leave a blank first line
- Compute the resulting cursor offset (before range → unchanged; inside → snap to range start; after → shift by removed
  length; clamp to new length).
- Tags inside fenced blocks are skipped → deletion is a no-op there.

`Ctrl+N` calls this directly; `Ctrl+P`'s EMPTY stop wraps the same result into the existing cycle-edit shape (empty
replacement string, the EMPTY sentinel as the recorded index).

### Key-handling / consume semantics

After active file-completion handling (which keeps precedence for both keys), in the prompt's insert-mode handler:

- `Ctrl+N` → delete handler, then **always consume** the key.
- `Ctrl+P` → cycle handler, then **always consume** the key.

Both keys are consumed even on a no-op so that, while the prompt owns focus, a no-op never bubbles to the app-level
`Ctrl+N` / `Ctrl+P` agent-file navigation. (Today a no-op `Ctrl+P` on an empty MRU can bubble; making these consistently
prompt-local is the intended behavior and matches the dedicated-key direction of this change.) Feedback mode remains a
no-op for both, as today.

## Implementation Steps

1. **Shared deletion primitive** in `src/sase/ace/tui/widgets/_vcs_mru_cycling.py`.
   - Add a pure function that returns the edit removing the first VCS workflow tag (tag span + one separator + cursor),
     or `None` when there is nothing to delete. Reuse the reverted attempt's `_delete_vcs_xprompt_text` logic verbatim
     where possible.

2. **Extend `Ctrl+P` cycling to include the EMPTY stop.**
   - Change the ring modulus in `_next_vcs_mru_index()` from `len(mru)` to `len(mru) + 1`, with index `len(mru)` meaning
     EMPTY; keep the empty-MRU early-out as a no-op.
   - In `_cycle_vcs_mru_text()`, when the target index is the EMPTY sentinel, produce a deletion edit (via the shared
     primitive) tagged with the EMPTY sentinel index; otherwise keep the existing insert/replace/prepend logic.
   - Simplify the now forward-only cycle: drop the `Ctrl+N` direction/`-1` path and the unused direction/key plumbing
     (`_cycle_direction`, the cycle `key` parameter, and the `VcsMruCycleKey` literal where it only served `Ctrl+N`).

3. **Make `Ctrl+N` a deletion handler.**
   - Add a `_handle_vcs_xprompt_delete_key()` to the mixin that applies the shared deletion primitive, clears transient
     completion/hint state only when a deletion actually happens, and resets `_vcs_mru_index` to `None`.
   - It must not load MRU history.

4. **Wire the key handler** in `src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py`.
   - Route `Ctrl+N` to the delete handler and `Ctrl+P` to the (forward-only) cycle handler; always consume both after
     file-completion precedence. Preserve the feedback-mode guard.

5. **Leave MRU persistence and launch recording unchanged.**
   - No changes to `sase.history.vcs_xprompt_mru` semantics. `_vcs_mru_index` state stays (still used by `Ctrl+P`
     cycling and reset on submit/history). The `Ctrl+G` editor launch that reads launchable MRU entries is untouched.

6. **Tests.**
   - Pure-function tests (`tests/ace/tui/widgets/test_vcs_mru_cycling_logic.py`):
     - Rewrite the two `Ctrl+N` cycling cases as deletion-primitive cases (start, mid-body, after a directive prefix,
       tag-before-newline, fenced-block no-op, no-tag returns `None`, and the three cursor positions).
     - Add `Ctrl+P` EMPTY-stop cases: from the oldest entry → tag removed; continuing from the EMPTY sentinel index →
       most-recent entry; a body prompt at the oldest entry → tag + separator removed leaving the body.
   - Widget tests (`tests/ace/tui/widgets/test_prompt_vcs_mru_cycling.py`):
     - Rewrite `test_ctrl_n_cycles_vcs_only_prompt_to_previous_mru_entry` into `Ctrl+N` deletion (tag-only prompt →
       empty; body prompt → body without the tag; no-tag prompt → unchanged; feedback-mode no-op).
     - Add a `Ctrl+P` end-of-history sequence: e.g. MRU `[foo, bar]` from `#git:foo` → `ctrl+p` `ctrl+p` yields no tag,
       and a third `ctrl+p` yields `#git:foo` again.
     - Keep the existing `Ctrl+P` cycling/precedence/default-skip/feedback tests; confirm
       `test_file_completion_keeps_ctrl_n_precedence` still passes (file completion keeps `Ctrl+N`).
   - `tests/ace/tui/test_agent_launch_vcs.py` and `tests/ace/tui/widgets/test_prompt_history_trigger.py` should need no
     changes (cycling and `_vcs_mru_index` are retained); confirm they still pass.

7. **Docs.**
   - Update `docs/ace.md` (the prompt-input prose near the prompt-history section) to describe the new split: `Ctrl+P`
     cycles forward through workspace MRU prefixes and through a "no prefix shown" stop at the end of history before
     wrapping; `Ctrl+N` removes the first workspace prefix from the prompt (no-op when none is present) and no longer
     cycles.
   - Verify the `?` help popup and keybinding footer do not document this prompt behavior (they currently do not); if a
     reference is found, update it to match.

## Validation

```bash
pytest tests/ace/tui/widgets/test_vcs_mru_cycling_logic.py \
       tests/ace/tui/widgets/test_prompt_vcs_mru_cycling.py \
       tests/ace/tui/widgets/test_prompt_history_trigger.py \
       tests/ace/tui/test_agent_launch_vcs.py \
       tests/test_vcs_xprompt_mru.py
```

Then, because this repo requires it after source changes:

```bash
just install
just check
```

## Risks and Checks

- The keypress path for `Ctrl+N` must stay pure (no MRU load / disk access on the event loop); only `Ctrl+P` loads MRU,
  as today.
- File-completion navigation must keep `Ctrl+N` / `Ctrl+P` precedence while its menu is active.
- Always-consuming both keys in the prompt is a small, deliberate behavior change (a no-op no longer bubbles to
  app-level agent-file navigation while the prompt is focused); called out here for review.
- Deletion detection must reuse `find_vcs_workflow_tag_span()` so the removed tag matches exactly what launch parsing
  resolves (and fenced-block tags stay untouched).
- This is presentation-only TUI prompt-editing behavior; no Rust core boundary work is expected (the MRU loader and tag
  parser already live behind their existing Python/shared layers).

```

```
