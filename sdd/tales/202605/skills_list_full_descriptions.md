---
create_time: 2026-05-23 13:58:13
status: done
prompt: sdd/prompts/202605/skills_list_full_descriptions.md
---
# Plan: Make `sase skills list` show full names and wrapped descriptions

## Problem

Today the `Skill Sources` table inside `sase skills list` truncates almost everything that matters:

- `Skill` column is fixed `width=18` with `no_wrap=True, overflow="ellipsis"`, so any name longer than 17 chars
  (`/sase_agents_status`, `/sase_changespecs`, `/sase_git_commit`, etc. — i.e. _most_ real skills) is cut with `…`.
- `Source` column is `width=18` and the path is pre-compacted to `.../<tail>` by `_compact_path` (cli_list.py:226).
- `Description` is forced to one line by `_one_line(..., limit=120)` and the column is
  `no_wrap=True, overflow="ellipsis"` (cli_list.py:204–223 + cli_list.py:107–109). Long descriptions are silently
  chopped, even though many real ones (`sase_git_commit`, `sase_chats`, `sase_changespecs`, `update-config`) carry
  multi-sentence usage guidance that the reader needs to see in order to decide whether to invoke the skill.

The goal of this command is to give a human a quick read of every installable skill and what it is for. Truncation
defeats that goal.

## Design intent

Keep the three outer panels (`SASE Skills` summary, `Drift`, `Notes`) untouched — they are already compact and useful.
Redesign the middle section so:

1. **Every skill name is shown in full**, in bold cyan with a leading `/`, matching how skills are invoked.
2. **Every description is shown in full**, soft-wrapped on word boundaries so long blurbs read like prose instead of a
   truncated row.
3. **The source path is shown in full** as a dim, secondary line — not a competing column.
4. **Status and providers stay compact** so the eye can still scan a column of metadata at the left.
5. The whole thing still terminates at a sensible width (defaults to terminal width, just like today) and degrades
   gracefully on a 80-column terminal.

I considered three layouts:

- **(A) Same Table with `no_wrap=False` everywhere.** Rejected: Rich tables with five wrapping columns look ragged —
  descriptions wrap into a too-narrow column while three other columns sit nearly empty next to a tall cell.
- **(B) One `Panel` per skill.** Beautiful for 3 skills, becomes visually noisy with 10+ skills (lots of border
  characters, hard to scan vertically).
- **(C) A two-column Table: a compact metadata column on the left, a wide prose column on the right, with
  `show_lines=True` to separate skills.** This is the choice. The metadata column is naturally narrow (skill name +
  providers + status, each on its own line), and the prose column gets all remaining width for the wrapped description
  plus a dim `source:` footer. `show_lines=True` gives a clean horizontal rule between skills so multi-line rows stay
  readable.

### Resulting shape (illustrative, not exact)

```
╭─ SASE Skills ─────────────────────────────────────────────────╮
│ Sources             10                                         │
│ Providers           1                                          │
│ Generated targets   10                                         │
│ Target status       10 current, 0 stale, 0 missing             │
│ Deploy mode         home                                       │
│ Output paths        home paths                                 │
╰────────────────────────────────────────────────────────────────╯

  Skill Sources

  /sase_changespecs        Analyze and work with SASE ChangeSpecs. Use when
  claude                   inspecting CL/PR status, dependencies, commits,
  2 current                hooks, comments, mentors, or `.sase` project files.
                           source: src/sase/xprompts/skills/sase_changespecs.md
  ────────────────────────────────────────────────────────────────────────────
  /sase_git_commit         Commit changes using sase commit for git-based VCS
  claude                   (bare git and GitHub). This is the ONLY way you
  2 current                should EVER commit to git repos. NEVER invoke this
                           skill unless the user explicitly asks you to commit
                           or a post-completion finalizer triggers it.
                           source: src/sase/xprompts/skills/sase_git_commit.md
```

The left column shows three stacked lines per skill (name / providers / status) so the metadata reads as a compact
block, not a wide row of narrow cells. The right column carries the full wrapped description and a dim `source:` footer.

## Scope

### In scope

- Rewrite `_sources_table()` in `src/sase/skills/cli_list.py` to produce the two-column wrapping layout described above,
  with `show_lines=True`.
- Replace `_description_cell` and the `_one_line(..., limit=120)` truncation with a renderable that emits the **full**
  description as wrapped Rich `Text` (whitespace normalized, no length cap), followed by a dim `source: <full path>`
  line.
- Drop the dedicated `Source` column from the sources table (the source path moves into the prose cell as the dim
  footer). Remove `_compact_path` if it becomes unused, or keep it only where the drift panel still calls it.
- Build the left-hand metadata cell as a small `Table.grid` or stacked `Text` so name / providers / status sit on
  consecutive lines under a single row.
- Keep the empty-state `Panel("No generated skill source entries found.")` branch.
- Keep the `Markdown`-ish content path: if a description contains backticks / brackets we still want them rendered, but
  with word-wrap enabled. Easiest win: drop the `Syntax(..., word_wrap=False)` path entirely and just use Rich `Text`
  for descriptions — markdown markers will render as literal characters, which is acceptable and matches what the
  `description:` field is (plain prose with the occasional backtick). Revisit only if we decide inline code styling is
  worth the extra complexity.
- Update the existing test `test_skills_list_dashboard_renders_summary_and_drift` in `tests/main/test_skills_handler.py`
  so its assertions reflect the new structure. The substring assertions for skill name, provider, status, description
  text, and source filename should continue to hold; only the column-header assertions (`"Skill Sources"` heading) and
  any assertion that depends on the old column layout need to be adjusted. Add one new assertion that a long description
  appears in full (no `…` suffix) to lock in the no-truncation behavior.
- Add a focused unit test that feeds a synthetic `SkillsInventory` with a pathologically long description (e.g., 400
  chars) and a long skill name (e.g., 30 chars) and asserts both appear in the rendered output verbatim.

### Out of scope

- The summary panel, drift panel, and notes panel — untouched.
- Sorting, filtering, or any new CLI flags for `sase skills list`.
- Changes to the underlying `SkillsInventory` / `SkillSourceEntry` data model.
- Markdown rendering inside descriptions (we accept that backticks render as literal characters).
- Width / theming knobs exposed to users.

## Risks and mitigations

- **Tests that grep stdout might depend on the old column-aligned format.** The only known test
  (`test_skills_list_dashboard_renders_summary_and_drift`) uses substring matching for content, not layout, so it should
  keep passing with minor tweaks. We will run `just check` after editing.
- **Very narrow terminals (≤60 cols).** Rich's wrapping handles this; the left metadata column has a sensible min width
  and the description column takes the remainder. Empty state and drift table already coexist with the same console
  width, so no new constraint is introduced.
- **Loss of `Syntax`-styled markdown previews.** Acceptable trade-off — the description field is short prose, not code,
  and the previous styling was applied opportunistically (any cell with `` ` `` / `*` / `[`). The new output is more
  consistent.

## Acceptance criteria

- Running `sase skills list` in this repo shows every skill name in full (no `…`) and every description in full, wrapped
  on word boundaries.
- The summary panel, drift panel, and notes panel are byte-identical to today's output (modulo whatever Rich computes
  for the new console width).
- `just check` passes.
- The updated test asserts no-truncation behavior for a long synthetic description and a long synthetic skill name.

## Implementation steps

1. Edit `src/sase/skills/cli_list.py`:
   - Rewrite `_sources_table` to build a two-column `Table` with `show_lines=True`, `box=box.SIMPLE` (or `None` with
     explicit row dividers), `expand=True`, no `no_wrap`, no ellipsis overflow.
   - Build a left-cell renderable (stacked name / providers / status) via `Table.grid` or a `Group` of `Text` lines.
   - Build a right-cell renderable: wrapped description `Text` + blank line + dim `Text("source: " + full_path)`.
   - Remove `_description_cell` length cap; drop the `Syntax` branch.
   - Remove or shrink `_one_line` usage in descriptions; keep it (or its equivalent) only for whitespace normalization
     (collapse internal whitespace, don't cap length).
   - Remove `_compact_path` if no longer referenced.
2. Update `tests/main/test_skills_handler.py`:
   - Adjust assertions to match the new structure (still substring-based).
   - Add a new test for full-text rendering of long names and long descriptions.
3. Run `just install && just check`.
4. Eyeball the real output by running `sase skills list` in this workspace and confirm it looks beautiful at 100-col and
   140-col widths.
