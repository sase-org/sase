---
status: done
create_time: 2026-04-26 03:07:27
prompt: sdd/prompts/202604/agent_row_compaction.md
---

# Compact Agent-Row Rendering for the Agents Tab

## Problem

Agent rows on `sase ace`'s **Agents** tab routinely overflow the agent-list panel (CSS: 60-cell default, 43-min, 80-max
— see `src/sase/ace/tui/styles.tcss:650-680`) and Textual's `OptionList` wraps them onto a second display line. Wrapped
rows make the list noisy, break vertical alignment, mis-count visually-selectable lines, and waste vertical space.

A representative offender from a real snapshot:

```
✘ [agent] sase (PLAN DONE) (6 steps) @sort_agents.plan   01:14:06 · 5m39s
```

That left-half is **54 cells**; with the ≥2-cell gap and the 16-cell runtime suffix `01:14:06 · 5m39s` the row needs
**~72 cells** to render unwrapped. The default panel width (60) is over-budget by ~12 cells; the narrowest configuration
(43) is over-budget by ~29.

We need to shave at least ~15 cells off the typical worst-case left-half, with graceful degradation when even more is
needed.

## Goals

1. Every realistic agent row fits on **one line** at the **default 60-cell** panel width.
2. The most-common rows (no embedded workflow, no retry annotation, no wait-until countdown) fit on one line at the
   **43-cell minimum** panel width.
3. No information becomes unreadable — terminal status, retry depth, and agent identity all remain conveyable, even if
   compressed.
4. The change is purely cosmetic: storage, beads, agent metadata, and the detail panel are untouched. Users who want
   full status words can still read them in the right-hand AGENT DETAILS panel.

## Non-Goals

- No truncation of `display_name` or `agent_name` (those are the row's _identity_ — chopping them is what produces "two
  `@` rows you can't tell apart").
- No layout/keymap changes.
- No new config knobs. The compact form ships as the only form. (See _Open Question 5_.)

## Design Overview

We unconditionally compact the _decorations_ around the row's identity (type bracket, status word, fold annotation,
dismissible icon) into single-glyph or two-glyph badges, while leaving the row's identity (`display_name`,
`@agent_name`, `@tag`) intact. The row's _colors_ already encode type and status reliably, so the textual labels are
redundant for at-a-glance scanning.

The `_DISMISSIBLE_STATUSES` `✘` prefix is removed entirely — it is strictly redundant with the status glyph.

### Cell budget after the change

For the worst realistic row above:

| Segment            | Before                    | After      | Saved |
| ------------------ | ------------------------- | ---------- | ----- |
| Dismissible prefix | `✘ ` (2)                  | (removed)  | 2     |
| Type bracket       | `[agent] ` (8)            | (removed)  | 8     |
| Display name       | `sase` (4)                | `sase` (4) | 0     |
| Status             | ` (PLAN DONE)` (12)       | ` ✓P` (3)  | 9     |
| Fold annotation    | ` (6 steps)` (10)         | ` ×6` (3)  | 7     |
| Tag/agent-name     | ` @sort_agents.plan` (18) | unchanged  | 0     |

**New left-half**: `sase ✓P ×6 @sort_agents.plan` = **28 cells**. Plus 2-cell gap + 16-cell suffix = **46 cells** total.
Comfortably under 60; under 43 if the suffix were absent.

A typical _running_ row drops from ~38 cells (`[agent] sase (RUNNING) @j`) to ~16 (`sase ▶ @j`).

## Detailed Compaction Rules

### 1. Drop the leading dismissible icon (`✘`)

Remove the `_DONE_ICON` prefix block at `src/sase/ace/tui/widgets/_agent_list_rendering.py:169-170`. The status glyph
(see #3) already conveys terminal-state.

### 2. Drop the type bracket `[agent]` (the dominant case)

`AgentType.RUNNING` (which renders as `[agent]`) accounts for the vast majority of rows. We can safely elide it because:

- The display name is already colored per type (`_AGENT_TYPE_COLORS[AgentType.RUNNING]` for agent rows, per-step-type
  for workflow children).
- For workflow-child rows, the `_CHILD_INDENT` (` └─`) and step number (`1/3 `) already mark the row as non-top-level.

For non-`RUNNING`, non-workflow-child top-level entries (e.g. raw `workflow`, `cl`), we replace the bracket with a
single leading glyph:

| `display_type`      | Old           | New                                  |
| ------------------- | ------------- | ------------------------------------ |
| `agent`             | `[agent] `    | (omit)                               |
| `workflow`          | `[workflow] ` | `≡ `                                 |
| `cl` / `changespec` | `[cl] `       | `❑ `                                 |
| anything else       | `[X] `        | `[X] ` (keep — rare, debug-friendly) |

(Open Question 1: confirm `≡` and `❑` glyph choices — alternatives include `⚙`, `▣`, `◫`. Whichever we pick, the rule is
**one cell**.)

### 3. Replace `(STATUS)` with single- or two-glyph status badge

The status segment loses its surrounding parentheses and becomes a 1–2-cell glyph(s) rendered in the existing per-status
color, with one leading space. Contractions:

| Status             | Before                  | After          | Cells saved |
| ------------------ | ----------------------- | -------------- | ----------- |
| `RUNNING`          | ` (RUNNING)`            | ` ▶`           | 8           |
| `DONE`             | ` (DONE)`               | ` ✓`           | 5           |
| `PLAN DONE`        | ` (PLAN DONE)`          | ` ✓P`          | 9           |
| `PLAN APPROVED`    | ` (PLAN APPROVED)`      | ` ▶P`          | 13          |
| `EPIC CREATED`     | ` (EPIC CREATED)`       | ` ★E`          | 12          |
| `PLANNING`         | ` (PLANNING)`           | ` ✎`           | 9           |
| `FAILED`           | ` (FAILED)`             | ` ✗`           | 7           |
| `FAILED (RETRIED)` | ` (FAILED ↻ (RETRIED))` | ` ✗↻`          | ~17         |
| `WAITING`          | ` (WAITING)`            | ` ⏳` (1 cell) | 8           |
| `QUESTION`         | ` (QUESTION)`           | ` ?`           | 9           |
| `RETRYING`         | ` (RETRYING)`           | ` ↻`           | 9           |
| any other          | ` (X)`                  | ` (X)` (keep)  | 0           |

Color mapping is preserved exactly as-is (gold/green/teal/red/pink/ amethyst/amber/orange) — colors already do most of
the disambiguation work; the glyph is the secondary cue.

For `WAITING` rows that include the `(until …, Xm)` countdown, keep the countdown but drop the inner parens and `until `
keyword: ` ⏳ 14:30·5m` instead of ` (WAITING) (until 14:30, 5m)` — saves ~14 cells.

For `RETRYING` countdown: ` ↻3s` instead of ` (RETRYING) (3s)` — saves ~13 cells.

(Open Question 2: confirm glyph choices. ✓ ✗ ▶ ↻ ⏳ ★ are the strongest candidates; `✎` for PLANNING could alternatively
be `✏` or just `…`. We must avoid glyphs we already use for _other_ meanings: `▶` is reused as the BY*STATUS bucket
"Running" glyph — that's actually _good*, it means the bucket and the row use the same vocabulary. Likewise `✓`/`✗`
reuse the `Done`/`Failed` bucket glyphs.)

### 4. Compact fold annotation

Replace ` (N steps)` with ` ×N` (3 cells regardless of N up to 99).

For expanded variants:

- `(N steps, M hidden)` → `×N −M` (5 cells)
- `(N steps, M shown)` → `×N +M` (5 cells)
- `(N attempts)` → `↻N` (2 cells, no leading space — it abuts the status glyph naturally because the badge already uses
  ↻)

### 5. Compact retry/fallback annotation (running)

Already short (` ↻N▸short_model`). Leave alone — the model name is useful diagnostic info. If a row is _still_
over-budget after all other shaves, this is the next thing to drop (see _Responsive Fallback_).

### 6. Compact embedded-workflow annotation

`  ▲ #wf_name` / `  ▼ #wf_name`: drop the leading double-space and the space after the arrow → `▲#wf_name` /
`▼#wf_name`. Saves 3 cells.

### 7. Untouched segments

- `[h] ` hint char — only present during `g`-mode chord, transient.
- `[✓] ` mark indicator — important visual selection state.
- `⚡ ` approve icon — already 2 cells, semantically dense.
- `↳ `, `_CHILD_INDENT`, retry-chain indent — structural; removing them would break the tree affordance.
- `↻N ` retry-attempt badge — already 3 cells, structural.
- `◌ ` hidden icon — already 2 cells, conditional.
- `display_name`, `@agent_name`, `@tag` — identity, never truncate.
- `_build_runtime_suffix` (timestamp + duration) — already compact (`HH:MM:SS · 5m39s`). Cross-day form
  `YYMMDDTHH:MM:SS` (15 cells) is already a worst-case but is rare; leaving it.

## Approach: A (Always-Compact), Not B (Responsive)

We chose path **A** (always render the compact form, no width-aware branching) over path **B** (progressive shortening)
for these reasons:

- **Predictability**: snapshots are stable; users learn one vocabulary.
- **Simplicity**: zero conditional rendering paths in the hot loop.
- **The compact form is _better_ even at full width** — it puts the agent's identity (name, tag) closer to the left
  margin where the eye scans, and pushes meaningful runtime data closer to the agent name.

We retain **one** small responsive escape hatch: if (and only if) the widest row in the current list still exceeds the
panel's available width _after_ compaction, the renderer drops the `▸short_model` portion of the retry/fallback
annotation (keeping just `↻N`). This is a single-line conditional in `format_agent_option`.

## Files to Change

| File                                                | Change                                                                                                                                                                                                                                                                                              |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/ace/tui/widgets/_agent_list_styling.py`   | Add new status-glyph table `_STATUS_GLYPHS: dict[str, str]`. Add `_TYPE_GLYPHS: dict[AgentType, str]` for non-`RUNNING` types. Keep `_DONE_ICON` constant unused or delete (it's no longer referenced). Remove `_DISMISSIBLE_STATUSES` if unused after edit.                                        |
| `src/sase/ace/tui/widgets/_agent_list_rendering.py` | Edit `format_agent_option()` lines 165-256: delete dismissible-icon block (169-170); replace type-bracket block (181-190) with conditional glyph; replace status block (197-256) with glyph-table lookup; rewrite WAITING/RETRYING countdown formatting; tighten embedded-workflow block (284-290). |
| (caller of fold annotation)                         | Find where `fold_annotation` strings are built (search for `"steps"`, `"attempts"`, `"hidden"`, `"shown"`); switch to `×N`, `↻N`, `±M` forms. Likely in `agent_list.py` or a fold helper.                                                                                                           |
| `src/sase/ace/tui/modals/help_modal/*.py`           | Add a new "Agent Row Glyphs" section to the help modal documenting status glyphs, type glyphs, fold form, and the meaning of `↻`/`↳`/`⚡`/`◌`. Box width 57 per the AGENTS.md rule.                                                                                                                 |

No changes needed to:

- `styles.tcss` (panel widths stay)
- agent storage/beads
- ChangeSpec suffix files (`saseproject.vim`, `display.py`, `query/highlighting.py`, `changespec_detail.py`) — those are
  ChangeSpec-suffix concerns, not agent-row concerns.

## Test Impact

Snapshot/text-assertion tests that match the old `(DONE)`/`[agent]` strings will break and must be updated. Per Explore:

| File                                                        | Likely update                                                                                                                                                                 |
| ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/ace/tui/widgets/test_agent_list_runtime.py`          | Update `.plain` substring assertions (e.g. `"(DONE)"` → `"✓"`). Right-alignment test (`assert len(rows[0]) == len(rows[1])`) should still pass — alignment math is unchanged. |
| `tests/ace/tui/widgets/test_agent_list_bindings.py`         | Update assertions referencing `[agent]` or `(STATUS)` substrings.                                                                                                             |
| `tests/ace/tui/widgets/test_agent_list_attempts.py`         | Likely unaffected (attempt rows have their own format, not changed by this plan) — verify.                                                                                    |
| Any new snapshot tests for the embedded-workflow shortening | Add small focused tests for the new `▲#wf` / `▼#wf` form and the `×N` / `↻N` fold annotation.                                                                                 |

We do NOT introduce a feature flag or a "compat mode"; tests update in the same PR.

## Roll-out

Single PR, no phased migration. The change is reversible at any time by reverting one commit. There is no on-disk
impact.

## Open Questions for the User

1. **Type-bracket replacement glyphs.** Going with `≡` for `workflow`, `❑` for `cl`. Acceptable, or do you want
   different glyphs (or no glyph at all and just rely on color)?
2. **Status-badge glyphs.** The proposed table uses `▶ ✓ ✓P ▶P ★E ✎ ✗ ✗↻ ⏳ ? ↻`. The most subjective ones are:
   - `PLANNING → ✎` (alt: `✏`, `…`, `Pn`)
   - `PLAN DONE → ✓P` (alt: `P✓`, `✓ᴾ`)
   - `PLAN APPROVED → ▶P` (alt: `▶ᴾ`, `OK`)
   - `EPIC CREATED → ★E` (alt: `★`, `E★`) Want to override any of these?
3. **Drop dismissible `✘` prefix.** Confirmed redundant with status — any reason to keep it (e.g. it visually delineated
   terminal rows from running ones in a way colors don't)?
4. **WAITING countdown form.** Going with ` ⏳ 14:30·5m` (no `until` keyword, no parens). OK to lose the word "until"?
5. **No config flag.** Plan ships compact-only. Would you prefer a `[ace] compact_agent_rows = true|false` setting
   (defaulting to true)? My recommendation: no — extra branch surface for a purely cosmetic preference.
