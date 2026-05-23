---
create_time: 2026-05-23 14:10:03
status: done
prompt: sdd/prompts/202605/skills_list_table_redesign.md
---
# Plan: Render `sase skills list` as a beautiful table with rich provider chips

## Problem

The current `Skill Sources` section (delivered by the previous redesign in
`sdd/tales/202605/skills_list_full_descriptions.md`) succeeded at one thing — nothing is truncated. But the layout it
shipped is not really a table:

- The left "metadata" cell stacks `name` / `providers` / `status` on three consecutive lines. It reads like a mini
  info-card per row, not a column the eye can scan vertically.
- Providers collapse to `claude +4`, hiding **which** providers a skill actually supports. For a CLI whose whole point
  is "show me what's installed where," this is the most important field — and it is the most degraded.
- The source path is shown as a wrapped two-line URL under every description. When the source is a normal
  `…/xprompts/skills/<name>.md` it duplicates the skill name, and it always eats two lines of vertical space.
- Status is verbose (`6 current`) and only ever shows the cumulative count; there is no quick visual signal for
  "fully-deployed" vs. "drifted."

The user explicitly asked for a **table** (with a real grid of columns the eye can scan) and a **better display of
supported LLM providers**, and gave me license to lead the design.

## Design intent

A skills-list view is fundamentally an **inventory matrix**: rows are skills, columns are facets, and the eye should be
able to ask "which skills support gemini?" or "which skills are drifted?" by reading down a single column.

So: make it a real table. Each column carries one fact, columns line up vertically, and the row separator
(`show_lines=True`) keeps multi-line cells legible. Width is taken by the description, which is the only field that
genuinely needs to wrap.

### Resulting shape (illustrative)

```
╭─ SASE Skills ──────────────────────────────────────────────────────────────────╮
│ Sources           11                                                            │
│ Providers         5                                                             │
│ Generated targets 62                                                            │
│ …                                                                               │
╰─────────────────────────────────────────────────────────────────────────────────╯
                                  Skill Sources
┏━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Skill                 ┃ Providers               ┃ Status  ┃ Description        ┃
┡━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ /sase_changespecs     │ ● claude  ● gemini      │ ✓ 6     │ Analyze and work   │
│                       │ ● codex   ● amp         │         │ with SASE Change-  │
│                       │ ● cursor                │         │ Specs. Use when…   │
│                       │                         │         │ ~/…/skills/sase_…  │
├───────────────────────┼─────────────────────────┼─────────┼────────────────────┤
│ /sase_hg_commit       │ ● gemini                │ ✓ 2     │ Commit changes…    │
├───────────────────────┼─────────────────────────┼─────────┼────────────────────┤
│ /sase_git_commit      │ ● claude  ● gemini      │ ✓ 5 ⚠ 1 │ Commit changes…    │
│                       │ ● codex   ● amp         │         │                    │
│                       │ ● cursor                │         │                    │
└───────────────────────┴─────────────────────────┴─────────┴────────────────────┘
```

(The above is a sketch — actual widths follow Rich's auto-fit based on content and terminal size.)

### Columns

1. **Skill** — bold-cyan `/name`, full width (no truncation, wraps if needed). Min-width matches the longest known skill
   name so the column doesn't keep reflowing as rows scroll past.
2. **Providers** — see the dedicated section below. Wraps when too many providers to fit on one line at the current
   terminal width.
3. **Status** — compact "icon + count" tokens, one per non-zero state: `✓ 6` for fully current, `✓ 4 ⚠ 2` when stale,
   `✓ 4 ✗ 2` when missing, `–` only if a skill has zero targets. Colors mirror the existing green/yellow/red
   `_STATUS_STYLES` mapping. This is short enough to fit in a single visual token while still conveying drift at a
   glance.
4. **Description** — full description text, wrapped on word boundaries. Below the description, a single dim line
   carrying a **compact** source path — `~` for `$HOME`, `…/skills/<basename>` when inside the standard xprompts tree,
   and special prefixes (e.g. `config_overlay:…`) preserved verbatim because they actually carry distinct information.
   The dim line is omitted entirely when the source path is just the canonical `…/xprompts/skills/<skill_name>.md`
   (redundant with the skill name).

### Provider chips — the headline change

Providers are the most important facet of this view and currently the worst rendered. The redesign treats each provider
as a **colored chip**:

- A small unicode bullet (`●`) in the provider's brand color, followed by the provider name in the same color (slightly
  dimmed so the bullet "pops").
- Chips render in a fixed canonical order (claude, gemini, codex, amp, cursor, then alphabetical for any unknown
  providers) so the same provider always appears in the same column-position across rows, which is what makes the matrix
  scannable.
- Multiple chips per cell are space-separated and wrap inside the cell when necessary. No `+N` collapse, ever — the
  whole point is showing which providers are supported.
- A single brand-color palette mapped in code:

  | Provider  | Color                        |
  | --------- | ---------------------------- |
  | claude    | `#cc785c` (Anthropic orange) |
  | gemini    | `#4285f4` (Google blue)      |
  | codex     | `#10a37f` (OpenAI green)     |
  | amp       | `magenta`                    |
  | cursor    | `cyan`                       |
  | (unknown) | `white`                      |

  Brand colors are chosen for instant recognition; they're standard Rich-supported hex/named values and degrade fine on
  16- and 256-color terminals.

### Why a real table beats the previous stacked layout

- **Vertical scanning works.** With a dedicated Providers column the user can scan straight down to find every skill
  that supports `gemini`. With the old layout they had to read every cell.
- **Density.** Most rows fit on 1–2 wrapped lines instead of the previous 3–6, so the entire inventory is on one screen.
- **Honesty.** The grid lines tell the truth — this is structured tabular data. The old stacked layout pretended each
  row was a card; in reality the three stacked fields had no relationship except sharing a row.

### Layouts I considered and rejected

- **Sparkline / bar instead of icon+count for status.** Cute, but adds visual noise and requires the eye to estimate
  proportions; "✓ 4 ⚠ 2" is faster to read.
- **Per-provider boolean columns** (one column per provider, ✓/✗ in each). True matrix view, but breaks horribly on
  terminals narrower than the product of provider count × column gutter, and shifts every time a new provider is added.
  The chips approach gives the same information with graceful wrapping.
- **Initials-only chips** (`[C][G][X][A][U]`). Maximally compact, but the letters need a legend and the visual delta
  between `[C]laude` and `[C]ursor` is too subtle to trust at a glance. Full names + brand colors win.

## Scope

### In scope

- Rewrite `_sources_table()` in `src/sase/skills/cli_list.py` to produce the 4-column table described above, with
  `show_lines=True`, `expand=True`, and per-column overflow set to `fold` (no ellipsis).
- Replace `_provider_labels` with a new chip renderer that produces a `Text` containing per-provider styled bullet+name
  tokens, in canonical order, with the brand-color palette in a module-level constant.
- Replace `_source_status_summary` with a compact `✓ N ⚠ N ✗ N` renderer (only non-zero terms shown).
- Inline a small compact-path helper for the description-cell footer: replace `$HOME` with `~`, collapse the standard
  xprompts path prefix to `…`, omit the footer entirely when the path is the canonical
  `xprompts/skills/<skill_name>.md`.
- Keep the empty-state `Panel("No generated skill source entries found.")` branch unchanged.
- Update `tests/main/test_skills_handler.py` so its substring assertions match the new structure: it should still find
  each skill name, each provider name, the description text, and the new status tokens. Add a new assertion that all
  configured providers appear verbatim for a multi-provider skill (locking in the "no `+N` collapse" behavior).
- Add a focused test that synthesizes a `SkillsInventory` with one skill supporting all known providers and another with
  a single provider, and asserts every provider name appears in the rendered output without collapse, and that the
  status column renders compact tokens (`✓`, `⚠`, `✗`) for mixed-status targets.

### Out of scope

- Summary panel, drift panel, and notes panel — untouched.
- Sorting / filtering / new CLI flags.
- Changes to the `SkillsInventory` / `SkillSourceEntry` data model or to the provider plugin discovery in
  `init_skills_handler`.
- A `--verbose` flag for the now-omitted-in-some-cases source path. We trust that compacting is sufficient and that the
  canonical path is reconstructable from the skill name when needed.
- Per-target drill-down (which provider is stale on which path) — the Drift panel below already serves that need.

## Risks and mitigations

- **Narrow terminals (≤80 cols).** A 4-column table with wrapping cells is still legible at 80 cols because the Skill,
  Providers, and Status columns have natural shrink-floors (longest skill name, "✓ N ⚠ N ✗ N", longest provider name)
  and Description takes the remainder. Rich's auto-layout handles the rest. Tested informally at 80, 100, 140 cols
  during implementation.
- **Color choices on light backgrounds.** All chosen brand colors stay readable on both dark and light terminals; the
  bullet adds non-color redundancy so colorblind users still see a token per provider.
- **Tests that assert the old `claude +4` collapse string.** Easy to find and delete; existing test already asserts no
  ellipsis, the new test asserts no `+N` collapse and full provider list.

## Acceptance criteria

- `sase skills list` renders a 4-column bordered table (Skill, Providers, Status, Description) with `show_lines=True`
  between rows.
- Every supported provider for every skill appears as a colored chip, in the canonical column order, with no `+N`
  collapse.
- Status renders as compact icon+count tokens, color-coded.
- Description cell contains the full description and, where the source path carries distinct information, a single dim
  compact-path footer.
- Summary, Drift, and Notes panels are unchanged.
- `just check` passes.
- New test asserts the no-collapse provider rendering and compact status rendering on a synthetic mixed-status
  inventory.

## Implementation steps

1. Edit `src/sase/skills/cli_list.py`:
   - Add a `_PROVIDER_COLORS` mapping and a `_PROVIDER_ORDER` canonical list.
   - Add `_provider_chips(providers)` → `Text` renderable producing bullet
     - name tokens in canonical order.
   - Replace `_source_status_summary` with a compact `_status_tokens` helper that yields `✓ N` / `⚠ N` / `✗ N` for
     non-zero counts only.
   - Add `_compact_source_path(source_path, skill_name)` → `Text | None`, returning `None` when the path is the
     canonical xprompts file.
   - Rewrite `_sources_table` to build a 4-column `Table`, dropping the metadata-stack cell.
   - Rewrite `_details_cell` to combine description and optional dim footer.
   - Remove the now-unused `_metadata_cell` and `_provider_labels` helpers.
2. Update `tests/main/test_skills_handler.py`:
   - Adjust substring assertions for the new structure.
   - Add the new full-provider-render test.
3. Run `just install && just check`.
4. Eyeball `sase skills list` at 100-col and 140-col widths to confirm the layout reads as intended.
