---
create_time: 2026-06-15 20:52:12
status: done
prompt: sdd/prompts/202606/prompt_stack_visual_polish.md
---
# Plan: Make the Stacked Prompt Input Widgets Beautiful

## Context

The `sase-4p` "Multi-Agent Prompt Stack" epic shipped a stacked prompt UI: typing `---` (or loading a multi-prompt)
turns the bottom-docked `PromptInputBar` into a vertical stack of compact prompt panes, one per agent, with a floating
`agent N` label above each pane and a thick left accent bar marking the active pane.

It works and it's clean — but the user wants it to look _even nicer_. They've explicitly asked me to **lead the design**
and make it **beautiful**. This plan is a focused visual-polish pass on top of the finished, working feature. **No
behavior, keymaps, submit/cancel semantics, or launch wiring change.**

### Where it lives (all presentation-only, this repo)

- `src/sase/ace/tui/widgets/prompt_input_bar.py` — builds the per-pane `Static` separator rows and `PromptTextArea`
  panes; sets `border_title` / `border_subtitle`.
- `src/sase/ace/tui/styles.tcss` (≈ lines 1160–1245) — `PromptInputBar`, `.prompt-pane`, `.prompt-stack-separator`,
  `.prompt-input.solo`, completion panel, `feedback-mode`.
- `tests/ace/tui/visual/test_ace_png_snapshots_prompt_stack.py` + 4 goldens under `tests/ace/tui/visual/snapshots/png/`
  (`prompt_stack_two_panes`, `prompt_stack_active_upper`, `prompt_stack_compact_inactive_80x30`,
  `prompt_stack_completion_panel`).

**Rust-core boundary check:** this is pure Textual rendering (TCSS + a render string). It is _not_ shared backend
behavior — no web/CLI frontend needs it to match — so per `memory/short/rust_core_backend_boundary.md` it correctly
stays in this repo. No `sase-core` changes.

### What the current design does well (keep)

- The thick left accent bar is a strong, quiet active-pane cue — **keep it**.
- A label per pane is good for orientation — **keep the concept, upgrade the execution**.
- Solo (single-pane) mode is visually identical to the pre-stack bar — **this must stay pixel-identical**; only
  multi-pane styling changes.

### What holds it back (the design problems to solve)

1. **No figure/ground depth.** Every pane shares `$background`; the bar is `$surface`. Active vs inactive differ only by
   bar color, label weight, and dimmed text. The focused editing surface doesn't _pop_ — it should be unmistakable at a
   glance.
2. **Floating labels read as orphaned text.** `agent N` is centered text with nothing tying it to the pane. The epic
   design doc explicitly wanted "a dim line with an `agent N` cue" — i.e. a **structural divider**, not floating text.
   We never delivered the line.
3. **The bar forgets it's a stack.** Title says `Prompt` whether there's 1 agent or 5. The stack size is exactly the
   kind of state a polished tool surfaces quietly.
4. **Inactive panes don't recede far enough.** Dimmed text alone is subtle; the inactive bar color
   (`$surface-lighten-2`) is a flat gray with no relationship to the active accent.

## Design Vision: "Quiet structure, clear focus"

Four coordinated changes. The north star: the active pane should feel like a lit editing surface lifting off a quiet,
well-organized stack — depth and structure, not more color or chrome.

### 1. Give the active pane real depth (the highest-impact change)

Create genuine figure/ground between the editing surface and the rest of the stack using **only tokens already proven in
this theme**:

- **Active pane background → `$surface`** (lifts to the bar's own surface level, reading as "raised/lit").
- **Inactive panes stay `$background`** (darker; they recede into the bar floor).
- Active left bar stays `thick $accent`. Inactive left bar shifts from flat `$surface-lighten-2` to a quieter member of
  the same family so inactive bars read as "same control, muted" rather than unrelated gray.

This single depth cue does most of the work: focus becomes obvious without adding a single new color or glyph. (Optional
extra lift: layer Textual's theme-agnostic translucent `$boost` over the active pane if `$surface` alone reads too flat
in testing — decided by eye against the regenerated snapshots.)

### 2. Turn floating labels into hairline divider rules

Deliver the divider the epic doc actually intended. Replace the bare `Static("agent N")` with a small
`PromptStackSeparator(Static)` whose `render()` builds a **full-width centered label flanked by `─` hairline rules**,
recomputed from its own width (so it stays correct on resize):

```
────────────────────  agent 2  ────────────────────
```

- **Active** separator: label **bold `$accent`** with a discreet leading marker (`▍ agent 2`) so the send-target is
  glanceable; flanking rules a soft accent tint.
- **Inactive** separator: label and rules `$text-muted` / dim — quiet, structural, recessive.
- Active/inactive styling is driven by an `active` flag the existing `_apply_active_classes` already toggles per pane,
  so navigation/reorder restyle the rules with zero new wiring.

The rule visually _connects_ each label to its stack slot and gives the whole bar a calm horizontal rhythm instead of
floating fragments.

### 3. Surface the stack size in the bar title

When stacked, the border title becomes:

```
Prompt · 3 agents
```

Single-pane prompt mode stays plain `Prompt`; `feedback` / `approve_prompt` modes are untouched (they're never stacks).
A tiny `_refresh_title()` recomputes this from `len(self._stack)` and is called wherever the stack count can change
(rebuild, add pane, live-split, remove, load). Orienting, intentional, zero noise.

### 4. Recede inactive panes more gracefully

With depth (#1) doing the heavy lifting, inactive panes get a light, coordinated touch: keep `$text-muted` body text,
and pair the recessed `$background` with the muted-family left bar from #1 so an inactive pane reads as a single
coherent "quiet" object rather than three independently-dimmed parts.

**Explicit non-goal:** the relative-line-number gutter colors in `_line_rendering.py` (`#4385BE` / `#8B7EC8` /
`#D0A215`) are shared with the solo vim editor and encode vim relative-line direction, _not_ pane active-state. They
stay untouched.

## Variants considered (and why the recommendation wins)

- **A — Depth + hairline rules + title (RECOMMENDED).** Maximum elegance-per-change; uses existing tokens; keeps the
  proven left-bar cue; solo mode untouched.
- **B — Boxed/framed panes (each pane a full border).** Rejected: the epic doc explicitly warns against nested-card
  styling; full borders eat two content rows per pane and fight the docked bar's own frame.
- **C — Color-coded panes (per-agent hue).** Rejected: pretty in a mock, noisy in practice, and breaks down past ~3
  agents and across themes. Depth + one accent reads better and scales.

## Implementation Phases

### Phase 1 — Depth & inactive refinement (TCSS only)

- In `styles.tcss`: active `.prompt-pane.active` background `$surface` (+ optional `$boost`); confirm inactive
  `.prompt-pane.inactive` sits on `$background`; retune the inactive left-bar color to the muted-family tone; verify
  `.prompt-input.solo` is **completely unchanged**.
- Sanity-check focus background interplay (`PromptTextArea:focus`) so the active pane keeps its lift while focused.

### Phase 2 — Hairline divider separator

- Add `PromptStackSeparator(Static)` (in `prompt_input_bar.py` or alongside the stack widgets) with a width-aware
  `render()` producing the centered-label + `─` rule, an `active` flag, and a leading marker on the active label.
- Swap `_build_pane_widgets()` to emit it instead of the bare `Static`; have `_apply_active_classes` set `.active` (and
  refresh) on it.
- Add/keep `.prompt-stack-separator` TCSS for active/inactive color + the soft-accent rule tint.

### Phase 3 — Stack-size title

- Add `_refresh_title()`; call it from `on_mount`, `_after_rebuild`, `focus_item`, and the stack-mutation paths
  (`add_bottom_pane`, live-split, reorder, remove, `load_stack_from_text`). Single-pane and non-prompt modes keep the
  plain base title.

### Phase 4 — Snapshots, verification, checks

- Regenerate the 4 prompt-stack PNG goldens with `just test-visual --sase-update-visual-snapshots` and **inspect each
  rendered PNG by eye** (read the images back) to confirm the new look is actually beautiful — not just green.
- Confirm non-stack visual snapshots and the prompt-bar/stack unit + widget tests still pass unchanged (solo mode
  regression guard).
- `just install` (ephemeral workspace) → `just check` before completion, per project instructions.

## Risks / Notes

- **Solo-mode regression** is the main risk: every change must be gated to multi-pane classes so single-prompt rendering
  stays byte-identical. The existing single-pane tests + non-stack PNG goldens are the guard.
- **Width-aware separator on resize:** `render()` reads the live width and `Static` re-renders on resize, so rules stay
  full-width; covered by the existing 80×30 compact snapshot.
- `$boost` is a standard theme-agnostic Textual token but isn't yet used in this repo — it's optional and only kept if
  it visibly helps against `$surface` alone.
- Snapshot determinism is already pinned (color, fontconfig, Fira Code) by the visual fixtures; regen + eyeball is the
  loop.

## Deliverable

A more beautiful multi-agent prompt stack: a lit, depth-raised active pane; elegant hairline divider labels that read as
structure; a quietly self-aware `Prompt · N agents` title; gracefully recessive inactive panes — with solo mode
untouched, all tests green, and 4 refreshed PNG goldens verified by eye.
