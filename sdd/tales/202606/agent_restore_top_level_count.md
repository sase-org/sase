---
create_time: 2026-06-27 10:59:42
status: done
prompt: sdd/prompts/202606/agent_restore_top_level_count.md
---
# Plan: Show top-level agent count in the Agent Restore panel's left pane

## Problem

In the `sase ace` TUI's **Agent Restore** modal, each row in the left "Groups" pane (under "Saved groups" and "Recent
dismissals") shows an agent count that reflects the **total** number of agents in the group — including workflow-child
agents. For a group with 6 root agents that expand into 39 total agents, the row reads `39 agents from sase`.

The desired behavior: the left pane should headline the number of **top-level** (root) agents, i.e.
`6 agents from sase`. The right "Preview" pane already distinguishes the two (`Agents  39 (6 top-level)`) and should
keep doing so — only the left-pane summary is wrong.

## Background / how the panel works today

Two relevant source files:

- `src/sase/ace/tui/modals/saved_agent_group_revival_rendering.py` — renders both panes.
- `src/sase/ace/tui/actions/agents/_saved_group_records.py` — builds saved-group records (including the human title)
  from live agents at save/dismiss time.

The left-pane row (`format_saved_group_row`) shows **two** count-bearing elements, both currently derived from the total
count:

1. A compact `×N` prefix built from `summary.agent_count` (the total).
2. The group **title** (e.g. `39 agents from sase`), via `_saved_group_display_title`, which returns
   `summary.name or summary.title`.

The title is a **baked string**. It is generated once by `_saved_group_title()` in `_saved_group_records.py` (using
`count = len(agents)`), stored in the wire record's `title` field, persisted to disk, and later shown **verbatim** —
there is no recompute or migration on load. The title format is one of:

- `"{n} agents from @{tag}"`
- `"{n} agents in {cl_name}"`
- `"{n} agents from {project}"`
- `"{n} agents across {k} PRs"`
- `"{n} agents"` (bare)

Crucially, the wire summary already carries **both** counts as structured integer fields: `agent_count` (total) and
`top_level_agent_count` (roots only). The latter is computed at build time as
`sum(1 for a in agents if not a.is_workflow_child)` and is present on every persisted record (it is a required field of
the current wire schema).

Data-flow facts that shape the fix:

- **Saved groups** are read from a persisted on-disk archive; their titles are baked and never regenerated.
- **Recent dismissals** are built once (at dismiss time) into cached/persisted records; their titles are likewise baked.
- Therefore changing only the save-time title generator would fix **new** records but leave every record already on disk
  (everything in the screenshot) still showing the total.
- **Title generation is Python-only.** The sibling Rust core (`../sase-core/.../agent_group_archive`) only stores/loads
  records and copies the title string and counts through; it never generates titles. So this is a **presentation-layer
  fix in Python** — no Rust core change is required, consistent with the backend-boundary rule (the structured counts
  already live in the shared wire; only display logic changes).

## Goal

The left "Groups" pane of the Agent Restore modal should present the **top-level** agent count for every group — both
already-persisted records and newly created ones. The right "Preview" pane keeps showing the full total with the
`(N top-level)` annotation.

## Design

Two complementary changes — one fixes existing records at render time, the other keeps newly-baked data honest at the
source.

### 1. Render-time: display the top-level count (fixes existing records)

In `saved_agent_group_revival_rendering.py`:

- **`×N` prefix** in `format_saved_group_row`: source it from `summary.top_level_agent_count` instead of
  `summary.agent_count`. This is a direct structured-field swap that works for every record, old or new. (`×6` still
  fits the existing 4-char count column.)

- **Title text**: introduce a small helper that returns the group's display title with its leading count re-expressed as
  the top-level count. Because the title format is fully controlled (always `"<int> agent|agents[ <descriptor>]"`), the
  helper replaces the leading `"<int> agent|agents"` prefix with `"<top_level> agent|agents"`, preserving the descriptor
  ("from sase", "in <pr>", "across 3 PRs", "from @tag", or empty) and fixing pluralization (`1 agent` vs `N agents`).
  The helper is:
  - **defensive**: if the title does not start with `<int>` + `agent|agents`, it returns the title unchanged (covers any
    non-standard/legacy title string);
  - **idempotent**: applied to an already-top-level title it is a no-op.

  Route the title through this helper everywhere the auto-generated title is shown in this modal:
  - `_saved_group_display_title(summary)` — when there is no custom `name`, return the substituted title (this feeds
    both the row and the preview header).
  - The preview's secondary "raw title under a custom name" line — substitute there too, so a custom-named group's
    subtitle is consistent.

- **Preview "Agents" line is left unchanged**: it intentionally shows the total with the `(N top-level)` annotation and
  remains the place to see the full count.

### 2. Save-time: bake the top-level count into new titles (keeps the source honest)

In `_saved_group_records.py`, change `_saved_group_title()` so the count it embeds is the top-level count rather than
`len(agents)`. `build_saved_agent_group()` already computes `top_level_count`; pass it in so the value is computed once.
The "across {k} PRs" branch keeps using the distinct PR count `len(cl_names)`; only the agent count/word changes.

After this change, newly persisted titles already read e.g. `6 agents from sase`, and the render-time helper from step 1
becomes a no-op for them — the two changes are consistent, with step 1 covering the backlog of already-persisted records
and step 2 keeping stored data correct going forward.

### Decision to confirm: the `×N` prefix

The user's example calls out the title text specifically. The row also has the separate `×N` prefix. Leaving `×39` next
to a `6 agents from sase` title would be self-contradictory, so this plan changes **both** the `×N` prefix and the title
to the top-level count, keeping the left pane internally consistent. The total remains visible in the Preview pane. If
instead the total should be retained in the `×N` prefix, that is a one-line adjustment — flag it on plan review.

## Files to change

Production code (Python only; no Rust core change):

- `src/sase/ace/tui/modals/saved_agent_group_revival_rendering.py`
  - New `_title_with_top_level_count(title, top_level)` helper (defensive + idempotent).
  - `format_saved_group_row`: `×N` from `summary.top_level_agent_count`.
  - `_saved_group_display_title`: substitute the count for non-named groups.
  - Preview secondary raw-title line: substitute the count.
- `src/sase/ace/tui/actions/agents/_saved_group_records.py`
  - `_saved_group_title`: embed the top-level count (passed from `build_saved_agent_group`).

## Testing

- **Unit — rendering** (`tests/ace/tui/modals/test_saved_agent_group_revival_rendering.py`):
  - Row `×N` and title reflect `top_level_agent_count` when it differs from `agent_count` (e.g. summary with
    `agent_count=39, top_level_agent_count=6` renders `×6` and `6 agents from sase`).
  - The substitution helper: substitutes correctly, handles singular/plural and each descriptor form, is idempotent, and
    passes non-standard titles through unchanged.
  - Custom-named groups still show the name; their substituted subtitle is consistent.
  - Update existing assertions that hard-code totals (e.g. `×3`, `"3 agents from backend"`) where the fixture's
    top-level count differs.
- **Unit — records** (`tests/ace/tui/actions/test_saved_group_records.py`): a built group's title embeds the top-level
  count for a group mixing roots and workflow children, across the tag / cl / project / multi-PR / bare branches.
- **Visual PNG snapshots** (`tests/ace/tui/visual/test_ace_png_snapshots_saved_groups.py`): fixtures with mismatched
  counts (`"3 agents from backend"` @ top-level 2; `"6 agents across 3 PRs"` @ top-level 4) will change. Regenerate the
  affected goldens (`saved_agent_group_revival_normal`, `..._jump_mode`, `..._preview_rich`) with
  `--sase-update-visual-snapshots` and eyeball each diff to confirm the left-pane counts drop to the top-level value
  while the preview still reads `(N top-level)`.
- Scan the broader revival/marking suites (`test_dismissed_agent_groups.py`, `test_agent_marking_save.py`, the
  `test_agent_group_revival_*` set) for any title/count assertions that need the top-level value.
- Run `just check` (after `just install`) before completion.

## Out of scope

- The right "Preview" pane's `Agents  N (M top-level)` line (intentionally shows the total).
- The Rust core archive — it stores/copies titles and counts but does not generate titles.
- Any wire schema change: both counts are already present on the summary wire.
