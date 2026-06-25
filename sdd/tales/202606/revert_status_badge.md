---
create_time: 2026-06-25 17:34:02
status: wip
prompt: sdd/prompts/202606/revert_status_badge.md
---
# Make the Agent-Row Revert Indicator Visible (and Partial-Aware)

## Goal

When you revert an agent's commits from the Agents tab (`,r`), the agent row should carry an **unmistakable, beautiful
badge** that tells you at a glance what happened:

- the commits were **fully reverted**,
- the revert was **partial** (some repos/commits were undone, others were blocked or failed), or
- the revert **failed** (a revert was attempted and recorded, but nothing was actually undone).

Today there is a revert indicator, but it falls short on both counts the user raised:

1. **It is easy to miss.** It is a single thin glyph `↺` in a muted rusty-orange (`#D7875F`), tucked between the
   provider emoji and the (struck-through) agent name. On a busy row it reads as decoration, not a status.
2. **It is binary.** Detection is "does `revert_result.json` exist?" — a bool. There is no notion of a partial revert at
   all, even though the marker file already records everything we need to tell full from partial.

This plan makes the indicator loud and legible, and teaches it to distinguish full / partial / failed reverts using data
the backend already persists.

## Current Behavior (what exists today)

- **Marker (already rich).** `src/sase/ace/revert_agent_marker.py` writes `<artifacts_dir>/revert_result.json` after a
  revert. The payload already includes `complete: bool`, `reverted_shas`, `pushed`, and a per-repo `repos[]` array where
  each entry has `success`, `reverted_shas`, `error`, `skipped_reason`, `push_skipped_reason`. All the signal needed for
  full-vs-partial is here.
- **Detection (lossy).** `agent_is_reverted(artifacts_dir)` only checks that the file _exists_ and returns `bool`. The
  `complete` flag and the per-repo outcomes are read by no one.
- **Model.** `Agent.reverted: bool` is the only revert state on the row model. It is set at load time by
  `_enrich_agent_revert_state(...)` in `src/sase/ace/tui/models/_loaders/_done_loaders.py`.
- **Render.** `format_agent_option(...)` in `src/sase/ace/tui/widgets/_agent_list_render_agent.py` renders the lone
  glyph (`_REVERTED_GLYPH = "↺"`, style `bold #D7875F`, defined in `_agent_list_styling.py`) and strikes the name in
  teal when `agent.reverted and not agent.is_workflow_child`.
- **Cache.** The per-row render cache key in `_agent_list_render_cache.py` includes `agent.reverted` (so a new status
  field must be added to the key, or the badge will not repaint when status changes).
- **Refresh.** After a revert task completes, `_on_complete` in `src/sase/ace/tui/actions/agents/_revert.py` schedules
  an agents refresh when the revert succeeded _or_ produced commits even if the push failed — i.e. partial reverts
  (which do produce commits) already trigger a repaint.

## Design

### 1. A real three-state revert status (backend, this repo)

Introduce a small classification that reads the marker the backend already writes and collapses it to one of three
states. This lives next to the marker logic in the existing Python revert backend, **not** in the Rust core: the marker
is a Python-owned artifact produced and consumed entirely by `revert_agent_*` in this repo, so classifying it stays
here. (The Rust-core boundary applies to shared domain behavior other frontends must match; this is reading a local
TUI-owned artifact. The badge rendering is presentation-only Textual and also stays here.)

- Add a `RevertStatus` enum to `src/sase/ace/revert_agent_models.py`: `FULL`, `PARTIAL`, `FAILED`.
- Add `read_revert_status(artifacts_dir) -> RevertStatus | None` to `src/sase/ace/revert_agent_marker.py`.
  Classification rules:
  - **No file / unreadable** → `None` (no badge).
  - **`complete is True`** and every `repos[]` entry (if present) has `success: true` → `FULL`.
  - **Some commits were undone but not all** — i.e. at least one `reverted_sha` exists _and_ (`complete is False` or any
    `repos[]` entry has `success: false` / a `skipped_reason` / an `error`) → `PARTIAL`.
  - **A marker exists but nothing was actually undone** (`reverted_shas` empty across the board) → `FAILED`.
  - Keep `agent_is_reverted(...)` as a thin wrapper (`read_revert_status(...) is not None`) so existing callers and the
    low-level API keep working.
- **Scope note on "partial":** classification is about _commit/repo completeness_, not push propagation. A clean revert
  whose push was skipped because there is no remote is still `FULL`. Push failures are surfaced in the detail panel
  (existing behavior), not encoded into the row badge, to keep the badge's meaning crisp.

### 2. Carry the status on the row model

- Replace the single bool with a status on the `Agent` model (`src/sase/ace/tui/models/agent.py`): add
  `revert_status: RevertStatus | None = None` and keep `reverted` as a derived convenience (`property` returning
  `revert_status is not None`) so no existing reader breaks. (If keeping both a field and a property is awkward, keep
  `reverted` as a plain field set alongside `revert_status`; either way both stay in sync.)
- `_enrich_agent_revert_state(...)` reads the marker **once** via `read_revert_status(...)` and sets `revert_status`
  (deriving `reverted`). One file read, richer result.

### 3. Make the badge loud and beautiful (the visible redesign)

Replace the thin lone glyph with a **filled "pill"** — a reverse-video label (`fg on bg`), the same high-visibility
technique the codebase already uses for the unread badge (`#1a1a1a on #FFD700`). A solid color block with a word reads
as a status at a glance and cannot be mistaken for decoration. Each state is a distinct pill with a severity-graded warm
palette (clean undo → incomplete → failed):

| State     | Pill label        | Style (`fg on bg`)        | Name treatment           |
| --------- | ----------------- | ------------------------- | ------------------------ |
| `FULL`    | `↺ REVERTED`      | `bold #1A1008 on #D7875F` | struck-through teal      |
| `PARTIAL` | `↺ PARTIAL`       | `bold #1A1400 on #FFAF00` | normal teal (not struck) |
| `FAILED`  | `↺ REVERT FAILED` | `bold #1A0808 on #FF5F5F` | normal teal (not struck) |

Design rationale:

- **Reverse-video pill** = maximum contrast against the dark TUI background; impossible to miss, and it looks like a
  deliberate, polished status chip rather than a stray glyph.
- **Color semantics reuse the codebase's own language:** `#D7875F` keeps the existing "revert = rusty orange" identity
  (now as a bold fill), `#FFAF00` is the established warning amber (matching the retry badge), `#FF5F5F` is the
  established failure red. Orange → amber → red is an intuitive severity gradient.
- **Leading `↺` inside the pill** keeps the recognizable revert glyph while the word removes all ambiguity. Dark
  foreground text on the bright fill keeps the label crisp.
- **Name strike only for `FULL`:** a struck name says "these commits are gone." For `PARTIAL` the commits are _not_ all
  gone, so striking the name would be misleading — the amber pill carries the whole signal and the name stays readable.
  Same for `FAILED`.
- **Placement** stays where the glyph is today (after the provider emoji badges, before the name), so the row's
  left-to-right rhythm is preserved; only the glyph becomes a pill.

Implementation surface:

- `src/sase/ace/tui/widgets/_agent_list_styling.py`: replace the two `_REVERTED_GLYPH*` constants with a single
  mapping/helper, e.g. `revert_badge_for(status) -> (label, style)`, holding the three pill labels and styles above. One
  source of truth for the badge look.
- `src/sase/ace/tui/widgets/_agent_list_render_agent.py`: drive the badge + name style from `agent.revert_status`
  instead of the bool. `_should_render_reverted_badge(...)` becomes "status is not None and not `is_workflow_child`."
- `src/sase/ace/tui/widgets/_agent_list_render_cache.py`: add `agent.revert_status` to the row cache key (next to /
  replacing `agent.reverted`) so the badge repaints when status changes.

### 4. Confirm the badge actually fires (close the "I see no badge" gap)

A gorgeous badge is useless if detection never triggers, and the user reports seeing _nothing_ today. As the first
implementation step, verify the write/read directory parity:

- The execute path writes the marker to the **intent's** `artifacts_dir` (`revert_agent_execute.py` /
  `revert_agent_workspace.py`).
- The loader reads via the agent's resolved artifacts dir (`get_artifacts_dir(agent)` in
  `tui/models/agent_artifacts.py`).

If these two directories ever disagree, the marker is written where the row never looks and **no badge can render**
regardless of styling. Confirm they resolve to the same path for a normal revert; if they do not, fix the write side to
target the resolved artifacts dir (or the read side to consult the same dir the intent captured). This is the concrete
candidate root cause for "I'm not seeing any badge," and it must be settled before the redesign is meaningful.

### 5. (Optional, recommended) Spell out partial reverts in the detail panel

The row badge is intentionally compact. For partial/failed reverts, the agent detail / info panel is the natural place
for specifics ("reverted N of M commits; `repo X` blocked: <reason>"). The marker already has the per-repo breakdown.
This is a small, additive enhancement and can be deferred if scope is tight, but it pairs well with the partial badge
and turns "something went sideways" into an actionable explanation.

## Implementation Steps

1. Verify marker write dir (intent `artifacts_dir`) and loader read dir (`get_artifacts_dir`) agree for a standard
   revert; repair if they diverge (Section 4).
2. Add `RevertStatus` enum (`revert_agent_models.py`) and `read_revert_status(...)` (`revert_agent_marker.py`); keep
   `agent_is_reverted` as a wrapper.
3. Add `revert_status` to the `Agent` model and keep `reverted` in sync; update `_enrich_agent_revert_state` to populate
   it from one marker read.
4. Add the three-state pill badge (`_agent_list_styling.py` helper) and drive rendering + name styling from
   `revert_status` (`_agent_list_render_agent.py`).
5. Add `revert_status` to the render cache key (`_agent_list_render_cache.py`).
6. (Optional) Surface the per-repo partial breakdown in the detail/info panel.
7. Update the `?` help popup if it describes the revert indicator (per ace AGENTS.md help-sync rule), and the glossary
   "badge" mentions if appropriate (memory-file edits require user approval — propose, do not silently edit).

## Tests

- **Backend classification** (`tests/ace/test_revert_agent_marker.py` or the existing marker test module):
  `read_revert_status` returns `FULL` / `PARTIAL` / `FAILED` / `None` across marker payloads — complete all-success,
  complete with a failed/skipped repo, `complete: false` with some `reverted_shas`, marker with empty `reverted_shas`,
  and missing file.
- **Loader** (`tests/.../_done_loaders` coverage): `_enrich_agent_revert_state` sets `revert_status` (and the derived
  `reverted`) from a real marker on disk for both full and partial cases.
- **Render unit** (`tests/ace/tui/widgets/...`, using `assert_span_covers`): `format_agent_option` emits the
  `↺ REVERTED` pill with the full style + struck name for `FULL`; the `↺ PARTIAL` amber pill + non-struck name for
  `PARTIAL`; the failed pill for `FAILED`; and no badge for `None`.
- **PNG visual snapshots** (`tests/ace/tui/visual/`):
  - Regenerate the existing `agents_reverted_indicator_120x40` golden for the new full-revert pill (intentional visual
    change; accept via `--sase-update-visual-snapshots`), and update its `assert_page_svg_contains(page, "↺")` to also
    assert `"REVERTED"`.
  - Add a new `agents_partial_revert_indicator_120x40` golden plus a partial-revert agent in the snapshot helper
    (`_ace_png_snapshot_helpers.py`), asserting `"PARTIAL"`.
  - The snapshot tests can set `revert_status` directly on the fixture agent (as the current test sets
    `reverted = True`), keeping classification and rendering independently testable.

Run the targeted revert/marker and TUI render/visual tests first, then `just install` followed by `just check` after
implementation changes.

## Risks and Mitigations

- **Badge still doesn't appear** because the marker is written somewhere the loader never reads. Mitigation: Step 1
  settles write/read dir parity before anything else.
- **Orange (full) vs amber (partial) confusable** for some users. Mitigation: the pills carry distinct words (`REVERTED`
  vs `PARTIAL`), not just color; reverse-video makes both unmistakable.
- **Row horizontal crowding** from a wider labeled pill on narrow terminals. Mitigation: the pill is short (`↺ REVERTED`
  ≈ 11 cols, `↺ PARTIAL` ≈ 10); if width pressure proves real, the helper is the single place to fall back to a compact
  reverse-video chip (`↺` filled) while keeping the per-state color.
- **Cache desync** if the new field is not added to the render key, leaving a stale badge after a status change.
  Mitigation: Step 5 adds `revert_status` to the key (the key is intentionally explicit for exactly this reason).
- **Backward compatibility** for the many `reverted`-bool readers and the visual test that sets it directly. Mitigation:
  keep `reverted` working (derived/synced) and have status subsume it.
