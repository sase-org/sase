---
create_time: 2026-04-12 13:29:12
status: done
prompt: sdd/prompts/202604/mentor_review_accepted_nav.md
---

# Plan: Add `N` / `P` Accepted-Comment Navigation to Mentor Review Modal

## Problem

The Mentor Review modal lets users navigate all comments with `n`/`p` and toggle acceptance with `<space>`. Once a user
has accepted several comments across multiple mentors, there's no way to quickly cycle through just the accepted ones —
e.g. to do a final review before hitting `a` (apply+propose) or `A` (apply+commit). The user must manually step through
every comment with `n`/`p` to re-find the accepted ones.

## Design

Add `N` (next accepted) and `P` (prev accepted) keymaps that mirror `n`/`p` but skip any comment that hasn't been
accepted via `<space>`.

### Navigation algorithm

Build a flat list of all `(mentor_idx, comment_idx)` pairs across all mentors (preserving display order). Find the
current position in that list, then scan forward (`N`) or backward (`P`) with wraparound, checking `is_accepted()` for
each candidate. Land on the first accepted comment found. If no accepted comments exist anywhere, do nothing (position
unchanged).

This flat-list approach avoids duplicating the mentor-boundary wrapping logic from `action_next_comment` /
`action_prev_comment` and naturally handles edge cases (empty mentors, single accepted comment, wraparound).

### Changes

**`src/sase/ace/tui/modals/mentor_review_modal.py`**

1. **BINDINGS** — Add two entries after the `n`/`p` pair:

   ```python
   ("N", "next_accepted_comment", "Next accepted"),
   ("P", "prev_accepted_comment", "Prev accepted"),
   ```

2. **Helper `_all_comment_positions`** — Returns `list[tuple[int, int]]` of `(mentor_idx, comment_idx)` for every
   comment across all mentors. This is a short comprehension over `self._data.mentors`.

3. **`action_next_accepted_comment`** — Uses the flat position list, finds current position, scans forward with modular
   wraparound, checks acceptance, navigates if found, calls `_refresh_all()`.

4. **`action_prev_accepted_comment`** — Same but scans backward.

5. **Footer** — Add `("N/P", "accepted")` to the bindings display list so users discover the feature.

**`tests/test_mentor_review_modal.py`**

Seven new tests covering:

- Basic forward/backward navigation to accepted comments
- Wrapping across mentor boundaries in both directions
- No-op when nothing is accepted
- Skipping mentors with zero comments
