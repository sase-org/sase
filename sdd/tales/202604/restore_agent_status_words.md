---
status: done
create_time: 2026-04-26 03:24:00
prompt: sdd/prompts/202604/restore_agent_status_words.md
---

# Restore Readable Status Words on Agent Rows

## Problem

The recent `agent_row_compaction` change (commit `34295bb2`) replaced the verbose `(STATUS)` segment on every agent row
with a single- or two-cell glyph badge (`▶`, `✓`, `✓P`, `▶P`, `★E`, `✎`, `✗`, `✗↻`, `⏳`, `?`, `↻`). The user finds the
new badges too cryptic — without re-reading the help modal, it is non-obvious that `★E` means "epic created", `✎` means
"planning", `▶P` means "plan approved", or that `✗↻` differs semantically from `✗`. Status is the most-scanned piece of
information on a row; the cost of cryptic-ness is paid every time a user looks at the list.

This plan reverts **only** the status-segment compaction. Other compactions from the same commit (dropped `[agent]`
bracket, dropped `✘` dismissible prefix, `×N` / `↻N` fold annotation, embedded-workflow tightening, WAITING/RETRYING
countdown formatting) are evaluated below — most are kept by default because they don't trade readability for brevity
the way the status glyphs did.

## Goals

1. Status segment renders as the readable word(s) it used to: `(RUNNING)`, `(DONE)`, `(PLAN DONE)`, `(PLAN APPROVED)`,
   `(EPIC CREATED)`, `(PLANNING)`, `(FAILED)`, `FAILED ↻ (RETRIED)`, `(WAITING)`, `(QUESTION)`, `RETRYING`.
2. Existing color mapping per status is preserved exactly (gold / green / sea-green / red / pink / teal / amethyst /
   amber / orange).
3. The help modal stops documenting the removed status glyphs, while still documenting any glyphs that remain (type
   glyphs, fold-annotation form, structural icons).
4. Tests that now assert the glyph forms (e.g. `"✓"`) are updated back to the word forms (e.g. `"(DONE)"`).

## Non-Goals

- Not reverting the dropped `[agent]` bracket on top-level RUNNING rows. Color + indent already convey the type, and
  this drop saves 8 cells with no semantic loss. (See _Open Question 2_.)
- Not reverting the dropped `✘` dismissible prefix. It was strictly redundant with the status word — once the status
  word is back, the `✘` adds nothing readers can't already see. (See _Open Question 4_.)
- Not reverting the embedded-workflow tightening (` ▲#wf` vs `  ▲ #wf`). Cosmetic, no readability loss. (Open Question
  5.)
- Not reverting the fold-annotation form (`×N`, `↻N`, `×N +M`, `×N −M`). These are arithmetic shorthand, not status
  words; `×5` reads as "5 of them" about as fast as "5 steps". (See _Open Question 3_.)
- WAITING countdown form is more debatable. Default: keep the new ` (until 14:30, 5m)`-restored form for parity with the
  surrounding `(WAITING)` style. (See _Open Question 6_.)

## Design Overview

Three files change. The renderer's status block goes back to writing `(STATUS)` literals; the styling module loses its
`_STATUS_GLYPHS` table; the help modal's "Agent Row Glyphs" section drops the status-glyph rows but keeps the type /
fold / structural rows.

### 1. `_agent_list_rendering.py` — `format_agent_option`

Restore the `(...)` wrapper and write the literal status word inside. The block was at lines ~206-268. The new shape
matches what was there before commit `34295bb2`:

```python
text.append(" (", style="dim")
if agent.status == "RUNNING":
    text.append(agent.status, style="bold #FFD700")
elif agent.status in ("DONE", "PLAN DONE"):
    text.append(agent.status, style="bold #5FD75F")
elif agent.status == "EPIC CREATED":
    text.append(agent.status, style="bold #5FD7AF")
elif agent.status == "FAILED":
    text.append(agent.status, style="bold #FF5F5F")
elif agent.status == "FAILED (RETRIED)":
    # split-style render: "FAILED ↻ (RETRIED)" preserves spawn-on-retry signal
    text.append("FAILED ", style="dim #FF5F5F")
    text.append("↻", style="bold #FFAF00")
    text.append(" (RETRIED)", style="dim #FF5F5F")
elif agent.status == "PLANNING":
    text.append(agent.status, style="bold #FF87AF")
elif agent.status == "PLAN APPROVED":
    text.append(agent.status, style="bold #00D7AF")
elif agent.status == "WAITING":
    text.append(agent.status, style="bold #AF87FF")
    # WAITING countdown: restore "(until HH:MM, Nm)" wording (Open Q6)
    ...
elif agent.status == "QUESTION":
    text.append(agent.status, style="bold #FFAF00")
elif agent.status == "RETRYING":
    text.append(f"RETRYING{countdown}", style="bold #FF8700")
else:
    text.append(agent.status, style="dim")
text.append(")", style="dim")
```

The retry/fallback annotation block (RUNNING + retry*count > 0) is unchanged — `↻N▸short_model` is already a separate
annotation that comes _after* the status segment, and `↻` here means "retry attempts" not the RETRYING status.

WAITING countdown reverts: ` (until 14:30, 5m)` and ` (5m)` (matching the original). Keep `format_compact_duration` for
the duration formatting.

RETRYING countdown reverts to ` (3s)`.

### 2. `_agent_list_styling.py`

- Remove the `_STATUS_GLYPHS` dict (lines 81-96).
- Keep `_TYPE_GLYPHS` (workflow → `≡`, cl → `❑`) — it isn't part of the cryptic-status complaint, and dropping the
  `[workflow] ` / `[cl] ` text is on Open Question 2.
- We do **not** restore `_DONE_ICON` / `_DISMISSIBLE_STATUSES` — once the status word is back, the `✘` prefix is again
  redundant (Open Question 4).

### 3. `_agent_list_rendering.py` — imports

Drop the `_STATUS_GLYPHS` import.

### 4. Help modal `bindings.py`

Edit the "Agent Row Glyphs" section in `agents_bindings` (lines 398-421):

- Remove the 11 status-glyph rows (`▶ Running`, `✓ Done`, `✓P Plan done`, `▶P Plan approved`, `★E Epic created`,
  `✎ Planning`, `✗ Failed`, `✗↻ Failed (retried)`, `⏳ Waiting`, `? Question`, `↻ Retrying`).
- Keep the rows that document remaining glyphs: `×N`, `×N +M / −M`, `↻N`, `≡`, `❑`, `⚡`, `◌`, `↳`.
- If only the structural rows remain, consider renaming the section to "Agent Row Markers" — but this is a polish
  decision, defer.

### 5. Tests

| File                                                   | Update                                                                                            |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| `tests/ace/tui/widgets/test_agent_list_runtime.py`     | Audit any `.plain` substring assertion that mentions `"✓"` / `"▶"` / etc., flip back to the word. |
| `tests/ace/tui/widgets/test_agent_list_bindings.py`    | Same audit.                                                                                       |
| Any new tests added by `34295bb2` that pin glyph forms | Flip the assertion to the word form.                                                              |

We are NOT changing the `×N` / `↻N` fold-annotation tests — those remain valid because the fold annotation isn't being
reverted.

## Files Summary

| File                                                | Change                                                                                                                                              |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/ace/tui/widgets/_agent_list_rendering.py` | Restore `(STATUS)` wrapping in `format_agent_option`. Drop `_STATUS_GLYPHS` import. WAITING / RETRYING countdown back to `(until …)` / `(Ns)` form. |
| `src/sase/ace/tui/widgets/_agent_list_styling.py`   | Delete `_STATUS_GLYPHS` dict.                                                                                                                       |
| `src/sase/ace/tui/modals/help_modal/bindings.py`    | Remove status-glyph rows from "Agent Row Glyphs" help section.                                                                                      |
| `tests/ace/tui/widgets/*.py`                        | Audit and revert assertions that match the glyph forms.                                                                                             |

No changes to `_agent_list_helpers.py` (fold annotation stays compact).

## Trade-off: panel width

The compaction plan claimed the verbose status wouldn't fit at the 60-cell default width. The realistic worst-case
example (` ✘ [agent] sase (PLAN DONE) (6 steps) @sort_agents.plan   01:14:06 · 5m39s` ≈ 72 cells) was largely a function
of three things:

1. The `[agent]` bracket (8 cells) — **still dropped** by this plan, so we keep that 8-cell saving.
2. The leading `✘` (2 cells) — **still dropped**, keeping that saving.
3. The fold annotation `(6 steps)` (10 cells) — **still compact** as `×6` (3 cells), keeping a 7-cell saving.

So even with the status word restored to ` (PLAN DONE)` (12 cells), the realistic worst-case row drops to ~57 cells —
**under** the 60-cell default. Wrapping at the 43-cell minimum is still possible for some rows, but per the user's
feedback the readability of status words is worth the occasional wrap; that's the right trade-off.

## Roll-out

Single PR, single commit, fully reversible.

## Open Questions

1. **Scope of restoration.** Restore all 11 status words, or only the most cryptic ones? The most-cryptic flagged in
   review were `★E`, `▶P`, `✎`, `✓P`. A targeted partial restoration could keep `▶` (RUNNING) and `✓` (DONE) — those are
   universally-understood — and restore everything else. Default to **restore all** for consistency.
2. **Type bracket `[agent]`.** Drop stays in by default (color encodes type, and the embedded-workflow indent encodes
   tree depth). Want it back too?
3. **Fold annotation form.** Default: keep `×N` / `↻N`. Want `(N steps)` / `(N attempts)` back too? Note: tests already
   pin the new form.
4. **Dismissible `✘` prefix.** Default: stays dropped (redundant with the now-restored status word). Want it back?
5. **Embedded-workflow `▲#wf` vs `  ▲ #wf`.** Default: keep the tightened form. Want the original double-space spacing
   back?
6. **WAITING countdown form.** Default: revert to ` (until 14:30, 5m)` (matches the surrounding `(WAITING)` style). The
   alternative is the new ` 14:30·5m` form (less verbose, but inconsistent with the parens-style status). I recommend
   reverting both to match.
