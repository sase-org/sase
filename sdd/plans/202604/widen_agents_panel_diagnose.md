---
create_time: 2026-04-25 17:58:15
status: done
prompt: sdd/prompts/202604/widen_agents_panel_diagnose.md
---
# Plan: Make the Agents-tab side panel actually render wider

## Context

A previous change raised both `_MAX_AGENT_LIST_WIDTH` (in `src/sase/ace/tui/app.py`) and the matching `max-width:` CSS
declaration on `#agent-list-container` (in `src/sase/ace/tui/styles.tcss`) from `70` → `80`. Both edits are confirmed in
place on disk.

The user reports: **the side panel still does not look any wider in `sase ace`.** They want this fixed.

## Why the previous edit was a no-op for the user

The Agents-tab side panel uses **content-driven dynamic sizing**, not a fixed width. Walking the relevant code:

- Per-row width is `option.prompt.cell_len` accumulated as `max_width` over visible rows
  (`src/sase/ace/tui/widgets/agent_list.py:191`, `:205-208`).
- Banner width is `max(_MIN_BANNER_WIDTH, max_width)` where `_MIN_BANNER_WIDTH = 40`
  (`src/sase/ace/tui/widgets/_agent_list_styling.py:11`).
- Optimal width is `max(max_width, banner_width) + _PADDING` with `_PADDING = 8`
  (`src/sase/ace/tui/widgets/agent_list.py:285-288`).
- The handler clamps to `[_MIN_AGENT_LIST_WIDTH, _MAX_AGENT_LIST_WIDTH]` and assigns `agent_list_container.styles.width`
  (`src/sase/ace/tui/actions/event_handlers.py:329-348`).

In other words the panel width tracks the widest currently-rendered row. The cap is only the _binding_ constraint when
that widest row's `cell_len + 8` exceeds the cap. **If the user's longest visible agent row is below ~62 cells, the
panel was already settling under 70 pre-change, so raising the ceiling to 80 cannot make it wider.** That matches the
user's observation: nothing visibly moved.

The original plan assumed the cap was the binding constraint and that rows were being truncated at ~70. In the user's
real workspace this is apparently not true — most agent rows are short enough that the dynamic algorithm itself never
chooses a width near the cap.

## Goal

Make the Agents-tab side panel actually render wider for the user, in line with the spirit of the original request
("allow the side panel to be a little wider so more information fits on a single line"), while preserving the dynamic
shrink-back behavior on small terminals.

Non-goals:

- No new columns / no row-format changes.
- No changes to ChangeSpecs or Axe tab side panels.
- No removal of dynamic sizing entirely — narrow terminals must still get a usable layout.

## Diagnosis steps (do these first, before deciding the fix)

Before picking a remediation, confirm which scenario the user is actually in. The fix differs depending on the
diagnosis.

1. **Measure actual `max_width` in a real session.** Add a temporary `log.info(...)` (or `self.app.log(...)`) call next
   to `optimal_width = ...` in `agent_list.py:287` recording `(panel, max_width, banner_width, optimal_width)`. Run
   `sase ace` against a real workspace, switch to Agents tab with a representative set of agents loaded, and grab the
   logged values. (Remove the log line before committing the final fix.)

2. **Categorize the result:**
   - **Case A (cap was already non-binding):** observed `max_width + 8 < 70` consistently. Then the panel was never
     sitting at 70 pre-change. Bumping to 80 was correctly a no-op and the user actually wants the _floor_ / _default_
     raised, not the ceiling.
   - **Case B (cap was binding but new ceiling not reached):** observed `max_width + 8 ≥ 70` but the rendered container
     still measures < 80. Then the plumbing or CSS specificity is wrong and the new ceiling is not being honored.
   - **Case C (cap is now binding at 80 and panel really is 80, user just didn't notice):** observed
     `max_width + 8 ≥ 80` and the container measures 80. Then the change worked but the user expected something more
     visible — likely a default-width bump.

3. **Cross-check with ChangeSpecs tab.** ChangeSpecs uses `max-width: 80` and the user is happy with that width. If
   their ChangeSpecs panel is in fact rendering noticeably wider than their Agents panel, that confirms Case A — the
   ChangeSpecs rows are content-rich enough to drive the panel wide, while Agents rows aren't.

The likely diagnosis based on code inspection is **Case A**: agent rows commonly look like
`[A] some-agent (RUNNING) @bryan` which renders well under 60 cells. So the rest of this plan assumes Case A and
proposes the corresponding fix; if diagnosis instead lands on B or C, switch to the alternative fix described later.

## Remediation options

### Option 1 — Raise the floor (recommended for Case A)

Bump `_MIN_AGENT_LIST_WIDTH` from `40` → e.g. `60` (or `64`), and bump the matching CSS `min-width` and starting `width`
on `#agent-list-container`. Effect: the panel is **always** at least 60 cells wide, regardless of how short the visible
rows are. It can still grow up to 80 when rows demand it, and shrink back to 60 (not to 40) when they don't.

Pros:

- Directly addresses "panel doesn't look any wider" — it will be visibly wider on every workspace from the first frame.
- Preserves dynamic upper growth.
- Keeps the recent ceiling work meaningful (rows that _do_ get long can still expand to 80).

Cons:

- Reduces the right-hand detail panel's space on narrow terminals. On an 80-column terminal a floor of 60 leaves only
  ~20 cells for the detail pane. Mitigation: pick a more conservative floor (e.g. 56 or 60) rather than something
  aggressive like 70.

Files to touch:

- `src/sase/ace/tui/app.py` — `_MIN_AGENT_LIST_WIDTH = 60` (was 40).
- `src/sase/ace/tui/styles.tcss` — `#agent-list-container { width: 60; min-width: 60; max-width: 80; }`.

### Option 2 — Make the panel grow to the cap unconditionally

Remove the content-driven `max_width` measurement and just always post `_MAX_AGENT_LIST_WIDTH` as the desired width.
Effectively the panel becomes fixed-width 80 (still subject to terminal-width competition with the detail pane via
`1fr`).

Pros:

- Trivial, predictable. User definitely sees a wider panel.

Cons:

- Throws away dynamic shrink-back when only short rows are visible. On small terminals or filtered views the panel
  occupies space it doesn't need.
- Goes against the original design intent of dynamic sizing.

Not recommended unless the user explicitly says "I just want it fixed at 80, always."

### Option 3 — Tune the formula (padding/floor inside the formula)

Change `optimal_width = max(max_width, banner_width) + _PADDING` to incorporate a higher floor, e.g.
`optimal_width = max(max_width, banner_width, 60) + _PADDING`. Equivalent in effect to Option 1 but expressed inside the
formula instead of via `_MIN_AGENT_LIST_WIDTH`.

Pros:

- Keeps the public min/max constants meaningful as terminal-survival bounds (40 stays a true minimum).
- Localizes the "preferred minimum" near the measurement code.

Cons:

- Two places now declare a "minimum" (the formula floor and `_MIN_AGENT_LIST_WIDTH`), which is a footgun — future
  readers may not realize the formula floor exists.

Slightly worse than Option 1 from a maintainability standpoint. Pick Option 1 unless there is a reason to keep
`_MIN_AGENT_LIST_WIDTH=40` as a "true emergency minimum."

## Proposed change (assuming Case A diagnosis)

Apply **Option 1**:

1. `src/sase/ace/tui/app.py`: `_MIN_AGENT_LIST_WIDTH = 60` (was `40`).
2. `src/sase/ace/tui/styles.tcss`: change `#agent-list-container` to:
   ```tcss
   #agent-list-container {
       width: 60;            /* Default, will be set programmatically */
       min-width: 60;
       max-width: 80;
       height: 100%;
   }
   ```

Choice of `60` rationale:

- ChangeSpecs tab uses `min-width: 43, max-width: 80`. We want Agents at least as wide as ChangeSpecs for comparable
  workspaces, but agent rows are slightly shorter on average, so a floor a bit higher than ChangeSpecs (60 vs 43)
  compensates for that and ensures the user sees a _visibly_ wider Agents panel even with light content.
- Leaves `≥ 20` cells for the detail panel even on a hypothetical 80-column terminal — tight but functional. Real users
  routinely run at 120+ cols, where 60/1fr split leaves the detail panel >60 cells.
- Round number, easy to revert.

If Case A diagnosis instead lands at Case B (plumbing bug) or Case C (already at 80), the fix shifts:

- **Case B fix:** investigate why `agent_list_container.styles.width` isn't taking effect — probable culprits are CSS
  specificity (some other rule overriding), the `WidthChanged` handler not running for the active panel, or
  `combined = max(main_w, pinned_w)` being driven down by a stale pinned panel measurement. The plan would then add a
  diagnostic and patch the offending location instead of bumping the floor.
- **Case C fix:** the ceiling change worked and the user was just looking at a workspace that doesn't drive width to 80.
  We'd then likely still apply Option 1 anyway because the user's UX complaint is "doesn't look any wider," and a higher
  floor is what makes width changes _perceptible_ across all workspaces.

## Verification

1. Manual: open `sase ace`, switch to Agents tab on a representative workspace. Confirm the panel renders at the new
   floor width (60) immediately, even with only short rows visible.
2. Manual: induce a long agent row (e.g. an agent with a long `display_name + status + retry annotation + tag badge`)
   and confirm the panel grows up to the 80 cap, then shrinks back to 60 when that row is filtered away.
3. Manual: confirm the pinned-panel container still tracks the same width (it inherits from `#agent-list-container`).
4. Manual: visit ChangeSpecs and Axe tabs — confirm they are unchanged.
5. Manual on small terminal: resize the terminal down to ~80 cols and confirm the layout is still usable (panel at 60,
   detail panel at ~20 — cramped but not broken). If the detail panel becomes unusably narrow, drop the floor to 56
   or 54.
6. Automated: `just check`.

## Risks and reversibility

Low risk. Pure layout-bound change, no data-format or persisted-state effects. If a 60 floor turns out to feel too
aggressive on small terminals, it is a one-line revert (or step down to 56/54). The dynamic sizing infrastructure stays
intact — the change only moves a numeric bound.
