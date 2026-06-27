---
create_time: 2026-06-27 14:29:40
status: done
prompt: sdd/prompts/202606/prompt_history_five_word_minimum.md
---
# Plan: Raise prompt-history minimum from 3 to 5 words

## Problem

Prompt history currently records any prompt with **3 or more words** (via `_MIN_PROMPT_WORDS = 3` in
`src/sase/history/prompt_store.py`). The user wants to raise the floor to **5 words** so that short scraps no longer
clutter the store. This is the same kind of one-constant change made when the floor moved from 2 → 3, but the test
ripple is materially larger because the previous change bumped many fixtures to exactly 3–4 words, all of which now fall
below the new floor.

## Feasibility & product call (think-it-through)

**Technically:** trivially feasible and fully reversible — it is one module-level constant plus its comment. Everything
funnels through one predicate (`is_recordable_prompt`), so there is no new branching, no Rust/binding work, and no
config surface to touch.

**Product tradeoff the user should be aware of (flagging, not blocking):** a 5-word floor is aggressive. Many
legitimately re-runnable prompts are 3–4 words and would now be silently dropped from history, e.g.
`fix the failing test` (4), `run the test suite` (4), `add error handling here` (4), `fix the auth bug` (4),
`refactor this function` (3). The user has asked for 5 decisively, so this plan implements 5; the consequence is
recorded here so the choice is explicit. If this proves too aggressive in practice, reverting is a one-line change.

**What is unaffected (deliberate bypasses keep working):**

- `record_failed_launch_prompt()` records regardless of length (`text.strip()` only) — failed launches and short
  `#gh:foo`-style submissions stay recoverable.
- The three `add_or_update_prompt(..., allow_short=True)` call sites (`agent/launch_cwd_agents.py`,
  `agent/launch_cwd_bead_work.py`, `ace/tui/.../agent_workflow/_launch_body.py`) keep recording replayable generated /
  fanout invocations regardless of length.

## Background: one source of truth

The threshold is a single constant funnelled through one predicate, so the behavior change is one line of source — but
it ripples into every test fixture that relies on a 3- or 4-word prompt being recordable.

- **Definition:** `src/sase/history/prompt_store.py` — `_MIN_PROMPT_WORDS = 3` and
  `is_recordable_prompt(text, *, allow_short=False)` → `return allow_short or len(text.split()) >= _MIN_PROMPT_WORDS`.
- **Gate:** `add_or_update_prompt()` early-returns when `not is_recordable_prompt(...)`;
  `_multi_prompt_segment_mutations()` filters each multi-prompt segment through the same predicate.
- **Cancel path:** `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_mount.py::_save_text_as_cancelled()` calls
  `is_recordable_prompt(text)` to decide whether to return the recorded text (which drives the "saved to history"
  toast).
- **Doctor:** `src/sase/history/prompt_maintenance.py` reads `store._MIN_PROMPT_WORDS` directly for the "short recovery"
  diagnostic — it auto-picks up the new value, so its reported set widens to include 3- and 4-word entries.

This logic is **Python-only**; it does not live in or cross into the Rust core (`sase-core`), so no Rust/binding changes
are needed.

### Word-counting nuance the implementer MUST respect

Recordability is `len(text.split()) >= 5` over the **full segment text, including any leading VCS-tag / `%`-directive
tokens**. Examples (these matter for the multi-prompt tests):

- `#gh:sase` → 1 word.
- `%wait Review the fix and add tests` → 7 words (the `%wait` token counts).
- `#git:sase #pr:sase_feature\nstart the ChangeSpec` → 5 words (both tags + 3 words) → **already passes at 5**.
- `#git:sase_feature\ncontinue the work` → 4 words (one tag + 3 words) → **fails at 5**.

When editing fixtures, count tokens on the exact stored string, not the human-readable phrase.

## Changes

### Core change (one constant + its comment)

**`src/sase/history/prompt_store.py`**

1. `_MIN_PROMPT_WORDS = 3` → `_MIN_PROMPT_WORDS = 5`.
2. Update the explanatory comment to reflect the 5-word rationale (prompts shorter than five words are too terse to be
   worth re-running from history). Drop the now-stale `fix bug` example or replace it with a representative sub-5-word
   example.

Everything else (cancel-path toast, multi-segment filter, doctor diagnostic) flows through `is_recordable_prompt` /
`_MIN_PROMPT_WORDS` and needs no source edit.

### Test updates

Raising the floor breaks every test that records a 3- or 4-word prompt and expects it stored/updated/deduped/toasted,
plus the boundary tests and the doctor diagnostic. The fix is uniform: bump the fixture to **≥5 words** (counting all
tokens) and update any text/length/ordering assertions to match; for boundary/diagnostic tests, update the assertions
themselves. The enumerated set below was verified against the current tree; the implementer must still run the **full**
suite afterward to catch any fixture not listed here and fix it the same way.

**1. `tests/history/test_prompt_filtering.py`** (canonical threshold/boundary file — needs assertion changes, not just
bumps):

- `test_is_recordable_prompt_matches_word_threshold`: the 2-word False and empty/whitespace/`#gh:sase` False cases stay.
  The current `assert is_recordable_prompt("fix the bug") is True` (3 words) must change — at a 5-word floor that is now
  **False**. Add a 4-word **False** case (new boundary just below) and a 5-word **True** case (new pass boundary).
- `test_two_word_prompt_not_written`: still valid (2 words still dropped) — no change.
- `test_three_word_prompt_is_written`: the boundary moved up. Convert it into the new boundary pair — a
  `test_four_word_prompt_not_written` (4 words now dropped, asserts empty history) **and** a
  `test_five_word_prompt_is_written` (5 words is the new pass boundary, asserts one stored row). Keep the
  patch/timestamp scaffolding identical.
- Single-word, whitespace-only, cancelled-single-word, `allow_short` override, and "existing single-word not updated"
  tests are unchanged.

**2. `tests/history/test_prompt.py`**:

- `test_add_new_prompt` (`"test prompt now"`, 3 words) and `test_add_duplicate_updates_timestamp` (`"test prompt now"`,
  seed + call) → bump to a ≥5-word prompt and update the asserted text.
- `test_concurrent_prompt_writers_preserve_all_entries` (`f"prompt number {i}"`, 3 words each) → change the pattern to a
  ≥5-word form (e.g. `f"test prompt number {i} here"`) so all 12 entries are recorded; the `== set(prompts)` assertion
  then holds.

**3. `tests/history/test_prompt_cancelled.py`**:

- `test_add_cancelled_prompt`, `test_cancelled_prompt_not_downgraded`, `test_cancelled_prompt_upgraded_on_launch` (each
  uses a 3-word `"draft saved prompt"` / `"test prompt now"`, some as both seed and call) → bump to ≥5 words and update
  asserted text. `test_failed_launch_*` use `record_failed_launch_prompt` (bypass) — no change.

**4. `tests/history/test_prompt_shards.py`**:

- `test_write_touches_only_current_month_shard` (`"new shard prompt"`, 3 words),
  `test_cross_month_reuse_appends_current_copy_and_dedups_newest` (`"shared prompt text"`, 3 words, seed + call),
  `test_cross_month_normal_cancel_newest_wins_but_preserves_prompt` (`"shared prompt text"`, seed + call) → bump to ≥5
  words and update asserted text. Tests that seed only via `save_prompt_history()` are unaffected.

**5. `tests/history/test_prompt_multi.py`** (count tokens on the stored string per the nuance above):

- `test_multi_prompt_saves_combined_and_segments`: first segment `"Fix the auth bug"` (4) → ≥5 (e.g.
  `"Fix the broken auth bug"`). Second segment `"%wait Review the fix and add tests"` (7) is fine. Update the combined
  string and the segment in the asserted `texts` set; `len(result) == 3` then holds.
- `test_multi_prompt_saves_combined_and_segments_in_one_mutation`: both segments `"Fix the auth bug"` (4) and
  `"Add more tests"` (3) → each ≥5; update the expected 3-element set. The `load_for_write`/`save_shard` call-count-of-1
  assertions are unaffected.
- `test_multi_prompt_segment_dedup`: the seeded + targeted segment `"Fix the auth bug"` (4) → ≥5, and the other segment
  → ≥5, so the seeded row is re-found and its `last_used` bumped; keep `len(result) == 3` and the timestamp assertions.
- `test_cancelled_multi_prompt_saves_cancelled_segments`: segments `"Draft auth fix"` (3) and `"Draft test plan"` (3) →
  each ≥5 so all three cancelled rows survive (`len(result) == 3`).
- `test_multi_prompt_skips_short_segments`: prompt `"#gh:sase\n---\nfix auth bug"`. The intent is "short segment
  skipped, whole kept". `"fix auth bug"` (3) now also skips — bump the long segment to ≥5 (e.g.
  `"#gh:sase\n---\nfix the broken auth bug"`) so `#gh:sase` is still the skipped one; update the in-`texts` assertion
  and keep `len(result) == 2`.
- `test_multi_prompt_segments_do_not_derive_vcs_history_keys`: segment 1
  (`"#git:sase #pr:sase_feature\nstart the ChangeSpec"`, 5 words) already passes — leave it. Segment 2
  (`"#git:sase_feature\ncontinue the work"`, 4 words) fails — bump to ≥5 (e.g. add a word:
  `"#git:sase_feature\ncontinue the important work"`); update the prompt string and the expected `entries[...]` key.
- Other multi-prompt tests already use ≥5-word segments or seed via `save_prompt_history()` — verify, no change
  expected.

**6. `tests/history/test_prompt_maintenance.py`** — `test_doctor_flags_oversized_and_short_and_legacy`: the
`short_recovery` filter (`len(text.split()) < _MIN_PROMPT_WORDS`) widens at 5. Seeded entries are `big` (`"huge " + "x"

- 11000`, 2 words), `"#gh:foo"`(1 word), and`"legacy fielded prompt"`(3 words). At threshold 5,`"legacy fielded
  prompt"`newly qualifies.`short_recovery`is sorted by`text_chars`ascending, so the expected list becomes`[_prompt_id("#gh:foo"),
  _prompt_id("legacy fielded prompt"), _prompt_id(big)]`. The `oversized`and`legacy_field_entries` assertions are
  unchanged. (This is the cleanest fix and documents the wider diagnostic; do not mutate the fixtures away from these
  intentional cases.)

**7. `tests/ace/tui/test_prompt_bar_stack_submit_handlers.py`**:

- `test_per_pane_cancel_saves_only_that_pane_and_keeps_bar`: the per-pane fixture (`"cancelled pane text"`, 3 words)
  drives the real `is_recordable_prompt`; bump to ≥5 words so the "saved to history" toast still fires, and update the
  expected toast string if it echoes the text.
- Any all-pane / joined-stack cancel test whose joined token count drops below 5 (e.g. a `first\n---\nsecond`-style
  fixture that tokenizes to `< 5` tokens) → bump segments so the joined string is ≥5 tokens and the toast still fires.
  Tests that mock the unmount return directly are unaffected.

**8. `tests/ace/tui/test_prompt_bar_submit_no_cancel_save.py`** — the three real-path cancel tests
(`test_save_text_as_cancelled_returns_recorded_text` with `"  fix the bug  "`,
`test_save_bar_text_as_cancelled_propagates_recorded_text` and `test_unmount_prompt_bar_propagates_recorded_text` with
`_Bar("fix the bug")`, all 3 words) exercise the real `_save_text_as_cancelled` → bump each fixture to ≥5 words and
update the returned-text / `assert_called_once_with` / asserted-`stored` expectations to the new text.

### Out of scope / intentionally unchanged

- **`allow_short=True` call sites** and **`record_failed_launch_prompt`** — deliberately bypass the threshold; left
  as-is.
- **Rust core (`sase-core`)** — threshold is Python-only; no wire/API/binding changes.
- **`default_config.yml`** — not a keymap or configurable value; nothing to update.
- **Historical SDD tales** (`sdd/tales/202604/skip_short_prompts_in_history.md`,
  `sdd/tales/202606/prompt_history_three_word_minimum.md`, `sdd/tales/202606/cancel_toast.md`) — they record the prior
  2- and 3-word decisions and stay as historical record. The artifacts generated for _this_ change document the move
  to 5.
- No user-facing help/docstring states a numeric word count (the `add_or_update_prompt` docstring says "shorter than the
  normal history threshold" without a number), so no docstring edit is required.

## Verification

- `just install` first (workspaces are ephemeral and deps may have changed), then `just check` (ruff + mypy + full test
  suite). The TUI tests are not visual-snapshot tests, so no golden updates are expected.
- Focused suites while iterating: `tests/history/` and the two `tests/ace/tui/test_prompt_bar_*` files.
- After the enumerated edits, run the **full** suite to catch any 3–4-word fixture not listed above; fix each the same
  way (bump to ≥5 words, or update the assertion to the new "not recorded" behavior).
- Manual TUI sanity (optional): cancelling a 3- or 4-word prompt produces **no** "saved to history" toast and no history
  row; cancelling a 5-word prompt saves it and shows the toast as before.
