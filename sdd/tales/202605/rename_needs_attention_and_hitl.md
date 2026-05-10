---
create_time: 2026-05-10 11:05:34
status: done
prompt: sdd/prompts/202605/rename_needs_attention_and_hitl.md
---
# Plan: Rename "Needs Attention" → "Stopped" and "hitl" → "stopped"

## Goal

In the `sase ace` TUI Agents tab:

1. **Status grouping bucket label**: Rename the `"Needs Attention"` bucket (used when grouping "by status") to
   `"Stopped"`. This is a user-facing label that already represents agents whose forward progress has halted pending
   user action (`PLANNING`, `QUESTION`).
2. **Top-strip agent count label**: Rename the `"hitl"` count label (shown in the agent info panel at the top of the
   TUI) to `"stopped"`. This count comes from `AGENT_ASKING_STATUSES` (`PLANNING`, `QUESTION`, `WAITING INPUT`) — i.e.
   agents paused awaiting human input.
3. **Shorthand letter**: The existing shorthand for the count strip is `"H"` (for hitl). Update it to `"S"` (for
   stopped). The letter `S` is currently unused in `_PANEL_METRIC_LABELS` (existing letters: H, R, W, F, U, D), so there
   is no collision.

## Background / Context

These two labels look related but live in slightly different code paths:

- `"Needs Attention"` is one entry in `AGENT_STATUS_BUCKETS` (defined in `src/sase/agent/status_buckets.py`). It groups
  statuses `PLANNING` and `QUESTION` and is rendered with the `▲` glyph. This is the section header that appears when
  the user groups the Agents tab "by status".
- `"hitl"` is an entry in `_COUNT_LABELS` (defined in `src/sase/ace/tui/widgets/agent_info_panel.py`) — it relabels the
  `asking` metric in the count strip rendered like `"2 hitl · 5 running · 2 waiting · …"` at the top of the panel. The
  shorthand letter `H` lives in `_PANEL_METRIC_LABELS` in `src/sase/ace/tui/actions/agents/_display_panels.py`.

Although the two labels currently have different names and different underlying status sets, both describe the same
user-perceptible concept ("the agent has stopped and is waiting for me"). Renaming both to the same word ("Stopped" /
"stopped") aligns the vocabulary across the TUI without altering semantics.

## Out of Scope

- The glyph `▲` for the bucket stays unchanged.
- Status set membership (which statuses fall into the bucket vs. which are counted as `hitl`/`asking`) is **not**
  changing — only display strings.
- Internal symbols `agent_is_asking`, `AGENT_ASKING_STATUSES` (and the `asking` metric key) describe the underlying
  state ("the agent is asking for input"). Those names remain accurate and stay as-is.
- Query filter aliases like `needs:input` are not touched.

## Files to Change

### Source files (user-facing label updates)

1. **`src/sase/agent/status_buckets.py`** — central definition.
   - `AGENT_STATUS_BUCKETS`: replace `"Needs Attention"` with `"Stopped"`.
   - `AGENT_STATUS_BUCKET_GLYPHS`: change key `"Needs Attention"` → `"Stopped"` (glyph `▲` unchanged).
   - `status_bucket_for_values`: return `"Stopped"` instead of `"Needs Attention"`.
   - Rename internal constant `_NEEDS_ATTENTION_STATUSES` → `_STOPPED_STATUSES` for consistency with the new label.
   - Update the doc comment block (lines 28–43) to use "Stopped" wording: "**Stopped** = the agent has stopped and is
     waiting for you to act".

2. **`src/sase/ace/tui/models/agent_groups/_tree.py`** — bucket equality check at line 417
   (`elif bucket == "Needs Attention":`) becomes `elif bucket == "Stopped":`.

3. **`src/sase/ace/tui/models/agent_groups/_buckets.py`** — docstring mention of "Needs Attention".

4. **`src/sase/ace/tui/widgets/_agent_list_render_banner.py`** — docstring/comment mention.

5. **`src/sase/ace/tui/widgets/_agent_list_styling.py`** — comment mention ("Needs Attention borrows the embedded-…").

6. **`src/sase/ace/tui/modals/help_modal/bindings.py`** — line 484: `("▲ Needs Attention", "User must act")` →
   `("▲ Stopped", "User must act")`. (Per `src/sase/ace/AGENTS.md`, help-modal box width must remain 57 chars and
   keybinding descriptions ≤ 32 chars — `"▲ Stopped"` is shorter than the current text, so width constraint is trivially
   satisfied.)

7. **`src/sase/ace/tui/widgets/agent_info_panel.py`** — `_COUNT_LABELS` dict at line 156: change `"asking": "hitl"` →
   `"asking": "stopped"`.

8. **`src/sase/ace/tui/actions/agents/_display_panels.py`** — `_PANEL_METRIC_LABELS` at line 44: change
   `("asking", "H")` → `("asking", "S")`.

### Test file updates

9. **`tests/test_agent_status_groups.py`** — expectations on lines 44, 74.
10. **`tests/ace/tui/widgets/test_agent_list_grouping_buckets.py`** — lines 100, 126, 135, 145.
11. **`tests/ace/tui/models/test_agent_groups_grouping_mode_status.py`** — lines 20, 24.
12. **`tests/ace/tui/models/test_agent_groups_grouping_mode_tree.py`** — lines 66, 90.
13. **`tests/ace/tui/models/test_agent_groups_grouping_mode_keys.py`** — line 45.
14. **`tests/ace/tui/widgets/test_agent_info_panel.py`** — lines 67, 114, 138 (`hitl` → `stopped`).
15. **`tests/ace/tui/test_startup_loading_indicators.py`** — line 68 (`"0 hitl"` → `"0 stopped"`).

A repo-wide grep for the literal strings `"Needs Attention"`, `"hitl"`, and the glyph-prefixed variants will be re-run
after edits to catch any miss (changespec/markdown docs, fixtures, generated skill scripts, etc.). The Explore pass
above did not surface any non-source/non-test occurrences, but the grep is the safety net.

## Verification

After edits:

1. `just check` — the standard pre-reply hygiene gate (lint + mypy + tests) per `memory/short/build_and_run.md`.
2. Manually skim tests that exercise the status-bucket glyphs and metric-strip rendering to confirm assertions are
   updated coherently (not just mechanically replaced).

## Risks / Things to Watch

- `"Needs Attention"` is referenced by **string equality** in `_tree.py`. If any other module (or downstream sase-core
  binding, per the Rust-core boundary memory) compares against this literal, the rename will break it silently. The
  Explore pass scanned the Python tree; before landing, also grep for the literal in `../sase-core` and any external
  config to be safe.
- Help-modal width — `"▲ Stopped"` is shorter than `"▲ Needs Attention"`, so width constraints relax rather than
  tighten; no padding logic changes expected.
- Shorthand letter `"S"` is currently unused in the metric-letters set, so no collision.
- "hitl" and the new "stopped" label have slightly different underlying status sets (`AGENT_ASKING_STATUSES` includes
  `WAITING INPUT`, `_NEEDS_ATTENTION_STATUSES` does not). This pre-existing discrepancy is intentional and out of scope
  — the rename does not unify the sets.
