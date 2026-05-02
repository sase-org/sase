---
create_time: 2026-04-12 12:40:39
status: done
prompt: sdd/prompts/202604/mentor_review_status_header.md
---

# Mentor Review Panel: Status Header & Acceptance Progress

## Problem

The Mentor Review modal has three UX gaps that make it harder to work through comments efficiently:

1. **No global comment position** — `n/p` navigation crosses mentor boundaries seamlessly, but the header only shows
   per-mentor position ("Comment 2/4"). You lose track of where you are in the full review.
2. **Acceptance count is buried** — "Accepted: 2/7" sits in the footer alongside 8 keybinding hints. It's easy to miss,
   especially when the footer is the last thing you scan.
3. **Title bar is wasted space** — " Mentor Review" occupies the most prominent line of the modal but carries zero
   dynamic information.

## Design

### 1. Title Bar → Rich Status Header

Transform the static title into a dynamic status header that surfaces the two most important pieces of information:
where you are and how many you've accepted.

**Before:**

```
 Mentor Review
```

**After:**

```
 ── Mentor Review ────── 3 / 7 ────── ✓ 2 accepted ──
```

Details:

- **Global position** (`3 / 7`): bold white text flanked by decorative `──` lines in dim blue. Computes the absolute
  index across all mentors' comments.
- **Acceptance count** (`✓ 2 accepted`): green checkmark + count when > 0, dim when 0. At-a-glance feedback on progress.
- The title updates dynamically on every `_refresh_all()` call (navigation, toggle, mount).
- When there are no comments (all mentors passed/failed/running), fall back to just `── Mentor Review ──`.

### 2. Main Panel Header: Inline Acceptance + Mentor Name

Consolidate the per-mentor comment position, mentor name, and acceptance state onto one line.

**Before:**

```
 Comment 2/4
 ────────────────────────────────────────
  Focus: style    Severity: warning

  File: src/foo.py:42

  Description text here...

  [✓ ACCEPTED]

  <code snippet>
```

**After:**

```
 Comment 2/4 · code_quality                    [✓ ACCEPTED]
 ────────────────────────────────────────────────────────
  Focus: style    Severity: warning
  ...
```

Details:

- Mentor name appended after comment number, separated by `·`, in dim style.
- Acceptance indicator moved to the right side of the header line — bold green `[✓ ACCEPTED]` or dim `[ ]`.
- The standalone acceptance block between description and code snippet is removed, saving vertical space and putting the
  acceptance state where your eye naturally lands first.

### 3. Footer: Visual Acceptance Progress Bar

Replace the text-only footer counters with a compact visual progress bar, and drop the "Read" counter (already visible
per-mentor in the side panel).

**Before:**

```
 Read: 3/7  Accepted: 2/7  │  n/p: comments  j/k: mentors  ␣: toggle  ...
```

**After:**

```
 ■■□□□□□ 2/7 accepted  │  n/p: comments  j/k: mentors  ␣: toggle  ...
```

Details:

- Progress bar uses filled (`■`) and empty (`□`) blocks, 7 chars wide (capped at 10).
- Green (`#00D7AF`) when all accepted, themed blue (`#87D7FF`) otherwise. Empty blocks dim.
- Acceptance fraction follows the bar.
- "Read" counter removed from footer to reduce noise (per-mentor read bars in side panel are sufficient).

## Implementation

### New helper: `_global_comment_index()`

Computes the 1-based absolute position of the current comment across all mentors:

```
sum(len(m.comments) for m in mentors[:_mentor_idx]) + _comment_idx + 1
```

Returns `(current, total)` tuple. Returns `(0, 0)` when there are no comments.

### Changes to `mentor_review_modal.py`

| Method                         | Change                                                                                                                                                       |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `_build_title()`               | Becomes `_update_title()` called from `_refresh_all()`. Builds the rich status header with global position and acceptance count.                             |
| `_update_main_panel()`         | Header line: append ` · {mentor_name}` after "Comment X/Y", add acceptance indicator on same line. Remove the standalone acceptance block below description. |
| `_update_footer()`             | Replace `Read: X/total  Accepted: X/total` with visual progress bar + `X/Y accepted`.                                                                        |
| `_refresh_all()`               | Add `_update_title()` call.                                                                                                                                  |
| `compose()`                    | Title widget still created with placeholder; `_update_title()` fills it dynamically.                                                                         |
| New: `_global_comment_index()` | Returns `(current_1based, total)` across all mentors.                                                                                                        |

### Changes to `tests/test_mentor_review_modal.py`

- Add `test_global_comment_index_*` tests covering: single mentor, multiple mentors, mentors with zero comments
  interspersed, edge case of no comments at all.
