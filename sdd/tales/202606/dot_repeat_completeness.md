---
create_time: 2026-06-23 18:53:41
status: done
prompt: sdd/prompts/202606/dot_repeat_completeness.md
---
# Plan: Make the prompt-input vim dot-repeat (`.`) complete and correct

## Summary

The `sase ace` prompt-input widget (`PromptTextArea`) implements a vim-style NORMAL mode, including the dot-repeat
command (`.`, "repeat last change"). A review of the implementation found that dot-repeat is built on a
**keystroke-replay** mechanism that works well for delete/transform commands but has one serious behavioral bug, one
incorrect count semantic, and two missing capabilities. The most impactful gap is that **dot-repeat does not work for
any change that types text in INSERT mode** — the single most common use of `.` in real vim usage — and worse, replaying
a change command currently leaves the editor stuck in INSERT mode.

This plan makes dot-repeat thorough and vim-faithful: it adds insert-text repeat, corrects `[count].` semantics, makes
plain insert commands repeatable, and (optionally) extends repeat to visual-mode operations — all without regressing the
currently-working commands and without adding hot-path performance cost.

## Background: how dot-repeat works today

All vim NORMAL-mode logic lives in the Python TUI widgets under `src/sase/ace/tui/widgets/` (the sibling `sase-core`
Rust crate has **no** vim / normal-mode / dot-repeat logic, confirmed by search — this is presentation-layer editor
interaction state and correctly stays in this repo).

The mechanism, spread across a mixin stack mixed into `PromptTextArea`:

- `_handle_normal_mode_key` (`_vim_normal.py`) is called per key. When not replaying and no multi-key sequence is in
  progress, it clears `_mutation_key_buffer` and then appends every key of the current command to it.
- When a text-modifying command finishes, the executing helper calls `_record_mutation` (`_vim_normal_state.py`), which
  copies `_mutation_key_buffer` into `_last_mutation_keys`. No-op commands instead clear the buffer so they don't
  clobber the register.
- `.` calls `_replay_dot(count)` (`_vim_normal_state.py`), which sets `_replaying_dot` and re-feeds the recorded keys
  through `_handle_normal_mode_key`, `count` times.

Commands that record mutations today: `d`/`c`/`y`(via paste)/`>`/`<` + motion, `dd`/`cc`, `D`/`C`/`S`, `x`/`s`/`X`, `r`,
`~`, `J`, `p`/`P`, `Ctrl+A`/`Ctrl+X`, `gu`/`gU`/`g~`, surround (`ys`/`ds`/`cs`), and text objects.

## Findings

### Bug 1 (high) — change/insert commands get stuck in INSERT mode on replay, and lose typed text

`_execute_charwise_operator` and `_execute_linewise_operator` call `_record_mutation()` for the change operator
(`op == "c"`), so `cw`, `cc`, `ciw`, `s`, `S`, `C` (and friends) record their operator keystrokes. But:

1. The text the user types in INSERT mode never reaches `_handle_normal_mode_key` (it goes straight to
   `super()._on_key`), so it is **not** part of the recorded change.
2. On `.`, `_replay_dot` re-presses the operator keys, which delete the target and call `_enter_insert_mode()` again —
   and nothing exits INSERT mode. The user is silently dropped into INSERT mode with no replayed text.

This is a real, currently-shippable bug; it is untested (no dot test exercises a change that types text).

### Bug 2 (medium) — `[count].` uses repeat-N-times instead of vim's count-override

`_replay_dot` repeats the whole keystroke sequence `count` times. Vim's `[count].` instead re-runs the last change
**with the count replaced**. Repeat-N-times diverges (and is wrong) for commands that don't self-advance or that are
inherently count-scaled:

- `rx` then `3.` replaces only **one** char (the cursor stays on the replaced char between replays) — vim replaces
  three.
- `>>` then `3.` indents the current line by **three levels** — vim indents **three lines**.
- `J` then `3.` over-joins relative to `3J`.

It happens to produce the right result for `dw`, `dd`, `x`, `p`, `~` because those advance or stack naturally — which is
why it has gone unnoticed.

### Gap 3 (high) — plain insert commands are not dot-repeatable at all

`i`, `a`, `A`, `I`, `o`, `O` only call `_enter_insert_mode()`; they never record a mutation. After `ihello<Esc>`, `.`
does nothing. In vim every one of these is repeatable (e.g. `o- item<Esc>` then `.` opens another `- item` line). This
is the most common class of dot-repeat and is entirely missing.

### Gap 4 (low/medium) — visual-mode operations are not dot-repeatable

`_enter_visual_mode` clears `_mutation_key_buffer`, and visual keys are handled by a separate path that never appends to
it, so the `_record_mutation()` calls in `_vim_visual.py` are effectively no-ops. After selecting a region and pressing
`d`/`c`/ `>`/`gu`/etc., `.` does not re-apply it. Vim repeats a visual change over a same-sized region anchored at the
cursor.

### Minor / edge observations (lower priority)

- `r<Enter>` is ignored (vim splits the line); consequently not repeatable. Likely out of scope but noted.
- `.` while an operator is pending (`d.`) currently cancels the operator and repeats. This is acceptable but
  undefined/untested; we will lock it down with a test.

## Goals

1. Dot-repeat reproduces **insert-mode text** for all change/insert commands (`c`-family +
   `i`/`a`/`A`/`I`/`o`/`O`/`s`/`S`/`C`/`cc`), exiting cleanly back to NORMAL mode. Fixes Bug 1 and Gap 3.
2. `[count].` follows vim's **count-override** semantics. Fixes Bug 2.
3. (Optional, last) Visual-mode operators become dot-repeatable over a same-size region. Closes Gap 4.
4. No regressions to any currently-passing dot-repeat (or other NORMAL-mode) test, and no new per-keystroke performance
   cost.

## Non-goals

- Full keystroke-accurate INSERT-mode replay (replaying arbitrary in-insert navigation, completion-menu interactions,
  snippet expansion, auto-pairing as discrete keystrokes). We capture the **net inserted text** at the insert point,
  which matches vim's observable result for ordinary forward typing and is robust. Cases where the user navigates the
  cursor mid-insert are treated as best-effort (and never crash or strand the user in INSERT mode).
- `r<Enter>` line splitting and any brand-new NORMAL-mode commands.
- Any change to `sase-core` (no core logic is involved).

## Design

### Part A — Insert-text capture & replay (Goals 1 & Gap 3)

Represent a recorded change as **(normal-mode keys) + (optional inserted text)** rather than keys alone:

- Add state on `PromptTextArea`: `_last_mutation_insert: str | None` (None = a normal-only change; a string, possibly
  empty, = an "insert-type" change whose replay must re-enter NORMAL mode), plus a transient
  `_dot_insert_capture_offset: int | None` marking where an in-progress insert-type change began.
- **Begin capture** at the exact sites that intentionally enter INSERT as part of a dot-recordable command, _after_ the
  cursor is finalized: the `i/a/A/I/o/O` handlers in `_vim_normal_editing.py`, and the `op == "c"` paths in
  `_execute_charwise_operator` / `_execute_linewise_operator`. A small helper records the mutation keys (for `i`-family,
  which currently records nothing) and stamps `_dot_insert_capture_offset` with the cursor's absolute offset. We
  deliberately do **not** hook `_enter_insert_mode()` itself, because it is also called from non-dot contexts
  (frontmatter editing, stack actions).
- **Finish capture** in `_enter_normal_mode()` (the Esc transition): when capturing and not replaying, compute the
  inserted text as the document slice from the captured offset to the current cursor offset, store it into
  `_last_mutation_insert`, and clear the capture marker. Guard against ambiguous captures (cursor moved before the
  start) by storing `""` rather than garbage — this still fixes the stuck-in-INSERT bug because replay always returns to
  NORMAL.
- **Replay** (`_replay_dot`): after re-feeding the keys for an insert-type change (which re-enters INSERT), insert
  `_last_mutation_insert` via the existing keyboard-replace helper, then call `_enter_normal_mode()` and place the
  cursor on the last inserted character (vim behavior). For normal-only changes, behavior is unchanged.

This single representation cleanly fixes both Bug 1 (no more stuck INSERT; text is restored) and Gap 3 (plain inserts
now record and replay).

### Part B — Correct `[count].` count-override (Goal 2)

Make the recorded keys **count-free** and carry the effective count separately, then inject the desired count at replay
time:

- When a digit is consumed purely as a count (the count-accumulation branch in `_handle_normal_mode_key`), do not leave
  it in `_mutation_key_buffer` (pop it). Data digits (e.g. the `5` in `r5`, `f5`, `t3`) flow through the pending-key
  handler, never the count branch, so they are preserved. This is a single localized change.
- Track the change's **effective count** (operator-count × motion-count for operator+motion; the plain count otherwise)
  in a new `_mutation_count` field, finalized where the count is resolved (`_consume_pending_operator`, the line-repeat
  path, the pending text-object/ operator paths, and the top-level count site). `_record_mutation` snapshots it into
  `_last_mutation_count`.
- `_replay_dot(count, has_count)`: choose the effective count = the explicit `.` count if given, else
  `_last_mutation_count`. Replay once, injecting that count as a leading numeric prefix before the recorded core keys.
  For **insert-type** changes, apply count the vim way: `i`-family multiplies the inserted **text** (insert it `count`
  times); `c`-family applies the count to the **operator** (inject the prefix so the change spans `count` units) and
  inserts the text once.
- Plain `.` (no count) replays with the **original** count — verified to keep `test_dot_repeats_d3w`,
  `test_count_dot_repeats_multiple_times`, and `test_dot_repeats_number_increment_with_count` green.

This yields vim-correct results: `rx`+`3.` → replace 3, `>>`+`3.` → indent 3 lines, `dw`+`3.` → delete 3 words,
`d2w`+`.` → delete 2 words again.

### Part C — Visual-mode dot-repeat (Goal 3 / Gap 4, optional, sequenced last)

Visual operators don't fit keystroke-replay (they depend on the selection geometry, not on keys). Record them as a small
structured "visual change": operator + kind (charwise/ linewise) + size (char span or line count) + any pending insert
text for `c`. On `.`, reconstruct an equivalent range from the current cursor and apply the operator directly, reusing
`_execute_charwise_operator` / `_execute_linewise_operator`. This is a contained, additive path; it ships last so it can
be deferred if it risks the core fixes.

## Implementation phases

1. **Spec & test scaffolding.** Write a behavior table (every dot-repeatable command and its `[count].` semantics) and
   add failing tests in `tests/` capturing the target behavior for Bugs 1–2 and Gaps 3–4. This pins intent before
   touching the hot path.
2. **Part A — insert-text repeat.** Implement capture/replay; make `c`-family and `i`-family fully repeatable and
   confirm no more stuck-INSERT.
3. **Part B — count-override.** Implement count-free core keys + effective-count tracking + injection; reconcile
   insert-type count semantics.
4. **Part C — visual-mode repeat (optional).** Add the structured visual-change path.
5. **Docs, sync, and verification.** See below.

## Testing strategy

Extend `tests/test_prompt_normal_mode_dot.py` and the per-command files (`test_prompt_normal_mode_change.py`,
`_small_commands`, `_indent`, `_join`, `_number`, `_yank_paste`, `_surround`, `_text_objects`, visual tests). The
`PromptPage` DSL already supports typing in INSERT mode and `escape` (see `test_u_undoes_cw`), so insert-text repeat is
directly testable. Cover at least:

- Insert-text repeat: `cwfoo<Esc>.`, `ciwX<Esc>.`, `A;<Esc>.`, `o- item<Esc>.`, `ihello<Esc>.`, `cc...<Esc>.`, plus that
  mode returns to NORMAL after `.`.
- Count-override: `rx`+`3.`, `>>`+`3.`, `dw`+`3.`, `d2w`+`.`, `~`+`3.`, `ihi<Esc>`+`3.`.
- Regression: every existing dot test, plus `..` (repeat the repeat) and `d.` edge.
- Visual (if Part C lands): charwise/linewise `d`/`c`/`>`/`gu` then `.`.

Run `just install` (ephemeral workspace) then `just check` before completion, per repo rules.

## Docs & sync

- Update the NORMAL-mode table in `docs/ace.md` (the `.` row at ~line 1951 and the insert-command rows) to state that
  `.` now repeats insert-mode changes and obeys count-override.
- Per `src/sase/ace/CLAUDE.md`, audit the `?` help popup / help modal and the keybinding footer for any dot-repeat
  description and keep them in sync (the set of keys is unchanged, so this is expected to be a no-op verification, but
  it must be checked).

## Risks & mitigations

- **Hot-path correctness/perf (Part B).** Changes touch `_handle_normal_mode_key` and count resolution. All additions
  are O(1) per key (a list pop, an int assignment); insert capture computes an absolute offset only once per Esc. Risk
  is correctness, not speed; mitigated by the test-first phase and by keeping plain `.` semantics identical to today.
- **Ambiguous insert capture.** Mid-insert cursor moves can make the captured slice imperfect. We bound the damage:
  capture falls back to empty text and replay always restores NORMAL mode, so the worst case is "dot inserted nothing,"
  never a crash or a stuck mode.
- **Scope creep.** Part C is explicitly last and optional so the high-value fixes (A, B) can land independently.

## Out of scope

`r<Enter>` line splitting; keystroke-accurate INSERT replay; new NORMAL-mode commands; any `sase-core` changes.
