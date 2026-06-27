---
create_time: 2026-06-27 13:40:55
status: done
prompt: sdd/prompts/202606/prompt_history_three_word_minimum.md
---
# Plan: Raise prompt-history minimum from 2 to 3 words

## Problem

When a prompt is cancelled in the prompt input widget, it is only saved to prompt history if it has at least **two**
words. The user wants cancelled prompts to be saved only when they have at least **three** words — very short scraps
like `fix bug` are not worth re-running from history and just clutter the store.

## Decision (from clarifying questions)

**Q1 → Global (3 words).** Raise the single shared threshold to 3 everywhere rather than adding a cancel-only variant.
This is the simplest change (one constant) and keeps one consistent rule across all entrypoints.

Accepted consequences of the global scope:

- **Submitted** prompts now also require >=3 words. A normally-launched 2-word prompt (e.g. `fix bug`) will no longer
  land in history. (Short _generated/fanout_ invocations and _failed launches_ are unaffected — see "Out of scope" —
  because they bypass the threshold intentionally.)
- **Multi-agent prompt segments** of exactly 2 words are no longer saved as their own history rows (the combined prompt
  is still saved when it has >=3 words total).
- The **history-doctor** diagnostic's "short recovery" list now flags existing 2-word entries (it reports entries below
  the threshold; raising the threshold widens what it reports). This is diagnostic-only and harmless — no entries are
  mutated or pruned.

## Background: one source of truth

The threshold is a single module-level constant funnelled through one predicate, so the behavior change is genuinely one
line of source — but it ripples into many test fixtures that currently rely on 2-word prompts being recordable.

- **Definition:** `src/sase/history/prompt_store.py` — `_MIN_PROMPT_WORDS = 2` and
  `is_recordable_prompt(text, *, allow_short=False)` (`return allow_short or len(text.split()) >= _MIN_PROMPT_WORDS`).
- **Gate:** `add_or_update_prompt()` early-returns when `not is_recordable_prompt(...)`;
  `_multi_prompt_segment_mutations()` filters each segment through the same predicate.
- **Cancel path:** `src/sase/ace/tui/.../agent_workflow/_prompt_bar_mount.py::_save_text_as_cancelled()` calls
  `is_recordable_prompt(text)` to decide whether to show the "saved to history" toast.
- **Doctor:** `src/sase/history/prompt_maintenance.py` reads `store._MIN_PROMPT_WORDS` directly for the "short recovery"
  diagnostic — it auto-picks up the new value.
- **Bypass paths (must stay short-friendly):** `record_failed_launch_prompt()` (uses `text.strip()` only) and the three
  `add_or_update_prompt(..., allow_short=True)` call sites in `agent/launch_cwd_agents.py`,
  `agent/launch_cwd_bead_work.py`, and `ace/tui/.../agent_workflow/_launch_body.py`.

This logic is **Python-only**; it does not live in or cross into the Rust core (`sase-core`), so no Rust/binding changes
are needed.

## Changes

### Core change (one constant + its comment)

**`src/sase/history/prompt_store.py`**

1. Change `_MIN_PROMPT_WORDS = 2` → `_MIN_PROMPT_WORDS = 3`.
2. Update the explanatory comment above the constant. The current rationale only mentions single-token xprompt triggers
   (`#gh:sase`); reword it to explain that prompts shorter than three words (e.g. `fix bug`) are too terse to be worth
   re-running from history.

Everything else — the cancel-path toast, the multi-segment filter, the doctor diagnostic — flows through
`is_recordable_prompt` / `_MIN_PROMPT_WORDS` and needs no code edit.

### Test updates (fixtures that assume the 2-word floor)

Raising the floor breaks every test that records a 2-word prompt and expects it stored/updated, and every boundary test.
Update them to use 3-word fixtures (and add the new boundary tests). Known set:

1. **`tests/history/test_prompt_filtering.py`** — this is the canonical threshold test file:
   - `test_is_recordable_prompt_matches_word_threshold`: make 2-word (`fix bug`) assert **False**; add a 3-word **True**
     case (e.g. `fix the bug`). Keep the empty/whitespace/single-token False cases.
   - `test_two_word_prompt_is_written`: this boundary moved. Replace with a `test_two_word_prompt_not_written` (2 words
     now dropped) **and** a `test_three_word_prompt_is_written` (3 words is the new pass boundary).
   - Single-word, whitespace-only, cancelled-single-word, and "existing single-word not updated" tests still pass
     unchanged.

2. **`tests/history/test_prompt.py`**:
   - `test_add_new_prompt` (`"test prompt"`) and `test_add_duplicate_updates_timestamp` (`"test prompt"`, seed + call) →
     use a 3-word prompt.
   - Transient-JSON-error test using `add_or_update_prompt("new prompt")` → use a 3-word prompt so the test still
     exercises the error path instead of short-circuiting at the gate. (`test_concurrent_prompt_writers_*` already uses
     3-word `"prompt number N"` fixtures — no change.)

3. **`tests/history/test_prompt_cancelled.py`**:
   - `test_add_cancelled_prompt` (`"draft prompt"`), `test_cancelled_prompt_not_downgraded` (`"test prompt"`, seed +
     call), `test_cancelled_prompt_upgraded_on_launch` (`"draft prompt"`, seed + call) → 3-word prompts.
   - `test_failed_launch_*` tests use `record_failed_launch_prompt` (bypasses the gate) — no change.

4. **`tests/history/test_prompt_shards.py`**:
   - `test_write_touches_only_current_month_shard` (`"new prompt"`),
     `test_cross_month_reuse_appends_current_copy_and_dedups_newest` (`"shared prompt"`, seed + call),
     `test_cross_month_normal_cancel_newest_wins_but_preserves_prompt` (`"shared prompt"`, seed + call) → 3-word
     prompts. (Tests that seed only via `save_prompt_history()` and use 3-word fixtures are unaffected.)

5. **`tests/history/test_prompt_multi.py`** — only the 2-word _segment_ fixtures break:
   - `test_multi_prompt_saves_combined_and_segments_in_one_mutation` and `test_multi_prompt_segment_dedup`: the
     `Add tests` segment (2 words) → make it 3 words (e.g. `Add more tests`) so it is still recorded as its own row, and
     update the expected text set.
   - `test_cancelled_multi_prompt_saves_cancelled_segments`: `Draft fix` / `Draft tests` segments (2 words each) → make
     each 3 words so all three rows are still produced.
   - `test_multi_prompt_skips_short_segments` already uses a 3-word `fix auth bug` segment and a 1-word skipped segment
     — still valid, no change. Other multi-prompt tests use >=3-word segments — no change.

6. **`tests/ace/tui/test_prompt_bar_stack_submit_handlers.py`**:
   - `test_per_pane_cancel_saves_only_that_pane_and_keeps_bar`: the `"cancelled pane"` fixture (2 words) drives the
     toast via the real `is_recordable_prompt`. Make it 3 words and update the expected toast message string.
   - Whole-bar cancel tests mock the unmount return directly, so they are unaffected.

7. **`tests/ace/tui/test_prompt_bar_submit_no_cancel_save.py`**:
   - `test_save_text_as_cancelled_returns_recorded_text` (`"  fix bug  "`) exercises the real `_save_text_as_cancelled`
     → make the fixture 3 words and update the returned-text / `assert_called_once_with` expectations.

The implementer should additionally run the **full** suite after these edits to catch any 2-word fixture not enumerated
here, and fix it the same way (bump to >=3 words, or assert the new "not recorded" behavior).

### Out of scope / intentionally unchanged

- **`allow_short=True` call sites** and **`record_failed_launch_prompt`** — these deliberately bypass the threshold so
  replayable generated invocations and failed launches (including short `#gh:foo` tags) stay in history. They keep
  working as-is.
- **Rust core (`sase-core`)** — the threshold is Python-only; no wire/API/binding changes.
- **`default_config.yml`** — this is not a keymap or configurable value; nothing to update.
- **Historical SDD tales** (`sdd/tales/202604/skip_short_prompts_in_history.md`, `sdd/tales/202606/cancel_toast.md`) —
  these document the _original_ 2-word decision and its rationale; they are a historical record and are left as written.
  The new prompt/plan artifacts generated for this change document the move to 3.
- No user-facing help/docstring states a numeric word count (the `add_or_update_prompt` docstring says "shorter than the
  normal history threshold" without a number), so no doc-string edit is required.

## Verification

- `just install` first (workspaces are ephemeral and deps may have changed), then `just check` (ruff + mypy + tests).
- Run the focused suites: `tests/history/` and the two `tests/ace/tui/test_prompt_bar_*` files.
- Manual sanity in the TUI: cancelling a 2-word prompt produces **no** "saved to history" toast and no history row;
  cancelling a 3-word prompt saves it and shows the toast as before.
