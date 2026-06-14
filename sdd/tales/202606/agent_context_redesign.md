---
create_time: 2026-06-14 12:20:02
status: done
prompt: sdd/prompts/202606/agent_context_redesign.md
---
# Plan: Make the "AGENT CONTEXT" panel section beautiful

## Goal

Polish the visual design of the `AGENT CONTEXT` section in the `sase ace` Agents-tab metadata panel (the `MEMORY` +
`SKILLS` sub-sections). The data, loaders, and overall two-lane structure are correct and stay as-is — this is a
**presentation-only** redesign to make the section read as a cohesive, color-coded, beautifully aligned whole, and to
fix small polish bugs (ungrammatical counts, asymmetric rows, redundant lines).

**Scope guardrails:** TUI rendering only. No changes to the skill-use audit log, the `sase skills log` CLI, the skill
generator, or any generated `SKILL.md` files. No `chezmoi`/skill regeneration. The loaders
(`load_memory_reads_for_agent`, `load_skill_uses_for_agent`) and their mtime-cache/throttle are untouched, so the j/k
hot path is unaffected (`memory/long/tui_perf.md`).

---

## Current state (what it renders today)

`append_agent_context_section()` (`_agent_context.py`) emits a gold-underline `AGENT CONTEXT` major header, then calls
`append_agent_memory_reads_section()` and `append_agent_skills_section()`. Reconstructed output:

```
──────────────────────────────────────────────────
AGENT CONTEXT

▸ MEMORY                                  ← bold #5FD7FF (cyan)
  5 reads · 3 files · last 14:22:08       ← dim, standalone summary line

  14:22:08  long/generated_skills.md      ← no glyph; path #87D7FF
            ↳ needed generated skill rules
  14:18:30  short/gotchas.md  ↩ frontmatter
            ↳ avoid the double-install gotcha
  + 3 more  (14:05 earliest)

▸ SKILLS                                  ← bold #5FD7FF (cyan — SAME as MEMORY)
  1 uses · 1 skills · last 14:23:08        ← "1 uses · 1 skills" (ungrammatical)

  14:23:08  ◆ sase_plan                   ← glyph #5FD75F, name #87FF87 (green)
            ↳ needed an implementation plan
```

### Design problems

1. **No lane identity.** `▸ MEMORY` and `▸ SKILLS` are the _same cyan_. Only the row bodies hint that skills are a green
   lane. The two sub-sections tonally blur together.
2. **Asymmetry.** Memory rows start with a bare path; skill rows start with a `◆` glyph. The lanes don't rhyme.
3. **Ungrammatical counts.** `1 uses · 1 skills`, `1 reads · 1 files` — plurals are hardcoded.
4. **Vertical bulk.** Each lane spends a full line on its summary plus a trailing blank line before rows.
5. **Redundant "last".** Rows are newest-first, so `last 14:22:08` in the summary just repeats the first visible row's
   timestamp.
6. **Fragile indent.** `_REASON_PREFIX` is a hardcoded 14-char string tied to the old `  HH:MM:SS  ` column width.
7. **Unguarded visuals.** No PNG snapshot renders this section, so color/glyph/alignment regressions are invisible to
   CI.

---

## Proposed design

Two principles drive the redesign:

- **Two color-coded lanes.** MEMORY is a fully _cyan_ lane; SKILLS is a fully _green_ lane. The accent flows through the
  sub-header, the row glyph, and the primary content, so the eye groups each lane at a glance. Reasons stay khaki in
  both — they're the same kind of "why" metadata, so a shared color reads as one consistent column.
- **Symmetric, self-describing rows.** Every row is `HH:MM:SS  <lane-glyph> <primary>` with a hanging `↳ <reason>`.
  Memory gains a glyph so the lanes rhyme: a **hollow** diamond `◇` for memory (context the agent _pulled in_) paired
  against the **filled** diamond `◆` for skills (a capability it _actively invoked_).

### Target rendering

```
──────────────────────────────────────────────────
AGENT CONTEXT

▸ MEMORY · 5 reads · 3 files              ← "▸ MEMORY" cyan bold; " · …" dim
  14:22:08  ◇ long/generated_skills.md    ← ◇ cyan; path light-blue
              ↳ needed generated skill rules
  14:18:30  ◇ short/gotchas.md  ↩ frontmatter
              ↳ avoid the double-install gotcha
  + 3 more · 14:05 earliest

▸ SKILLS · 1 use · 1 skill                ← "▸ SKILLS" GREEN bold; " · …" dim
  14:23:08  ◆ sase_plan                   ← ◆ green; name light-green
              ↳ needed an implementation plan
```

Empty lanes collapse to a single inline line (so the two-part structure stays legible and honest about the audit
caveat):

```
▸ MEMORY · none recorded                  ← "▸ MEMORY" cyan; " · none recorded" dim italic
```

### What changes, precisely

- **SKILLS sub-header → green** (`bold #5FD75F`), matching its glyph/name. This is the single highest-impact change: it
  turns SKILLS into a real green lane instead of a cyan header over green rows. MEMORY stays cyan.
- **Memory rows gain a `◇` glyph** in the lane accent (`bold #5FD7FF`), placed exactly where skills' `◆` sits, so the
  two lanes align column-for-column.
- **Counts pluralize correctly** via a small shared helper: `1 read` / `2 reads`, `1 file` / `3 files`, `1 use`,
  `1 skill`.
- **Stats fold into the sub-header line** (`▸ MEMORY · 5 reads · 3 files`), removing the standalone summary line and its
  trailing blank line — tighter, and each sub-header becomes self-describing.
- **Drop the redundant `last HH:MM:SS`** from the stats (the newest row, always visible, already shows it). The overflow
  footer keeps `+ N more · HH:MM earliest` for the hidden tail.
- **Reason hanging-indent recomputed** from the new row anatomy and centralized, preserving the existing "reason text
  sits 2 columns past the primary" offset (now shifted right by the 2-col glyph).
- **Spacing tightened:** one blank line after `AGENT CONTEXT`, lanes separated by one blank line, no blank between a
  sub-header and its rows.

### Style reference

| Element                | MEMORY (cyan lane)       | SKILLS (green lane)  |
| ---------------------- | ------------------------ | -------------------- |
| Sub-header `▸ NAME`    | `bold #5FD7FF`           | `bold #5FD75F` (new) |
| Inline stats ` · …`    | `dim`                    | `dim`                |
| Row glyph              | `◇` `bold #5FD7FF` (new) | `◆` `bold #5FD75F`   |
| Timestamp              | `dim`                    | `dim`                |
| Primary                | path `#87D7FF`           | name `bold #87FF87`  |
| `↩ frontmatter` marker | `dim italic`             | —                    |
| `↳ reason`             | `#D7D7AF` (khaki)        | `#D7D7AF` (khaki)    |
| Overflow / empty       | `dim italic`             | `dim italic`         |

Parent `AGENT CONTEXT` header is unchanged (`bold #D7AF5F underline`) — it stays a peer of `OUTPUT VARIABLES` /
`AGENT DELTAS` / `AGENT ARTIFACTS`, with the two color-coded lanes beneath supplying the container feel.

---

## Implementation

### 1. Extract shared context-formatting helpers (`_agent_context_common.py`)

The skills renderer already reaches into `_agent_memory_reads` for shared formatting (`append_context_reason`,
`format_local_hhmmss`, etc.). Centralize these into one small **public-API** module to make the symmetric redesign DRY
and to drop the "skills depends on memory" coupling (which previously forced those helpers to be made public to satisfy
`pyvision`'s private-cross-import rule). Move/own here:

- `format_local_hhmmss`, `format_local_hhmm`, `normalize_context_display`, `truncate_display(value, limit)`.
- `append_context_reason(text, reason, *, indent)` — parameterized so both lanes share one hanging-indent implementation
  derived from the new row anatomy.
- `count_phrase(n, singular)` — the new pluralization helper (`count_phrase(1, "file") == "1 file"`).
- `append_lane_row(...)` (or shared constants) for the common `HH:MM:SS  <glyph> <primary>` prefix, so memory and skills
  rows align by construction.
- Shared/lane color constants and glyphs (`◇`, `◆`, `↳`, `↩ frontmatter`).

`_agent_memory_reads.py` re-exports the moved names if any external caller/test imports them, to avoid churn.

### 2. `_agent_memory_reads.py` — MEMORY sub-section

- Header line: `▸ MEMORY` (cyan) + ` · {count_phrase(n,"read")} · {count_phrase(k,"file")}` (dim); rows follow directly.
- Rows: `HH:MM:SS  ◇ <path>` with the cyan glyph; keep `↩ frontmatter` and path truncation; reason via the shared
  indent.
- Empty: `▸ MEMORY · none recorded` (inline).

### 3. `_agent_skill_uses.py` — SKILLS sub-section

- SKILLS sub-header → green (`bold #5FD75F`); stats pluralized and inline; `last …` dropped.
- Rows keep `◆` + green name, now using the shared row/reason helpers for guaranteed column alignment with memory.
- Empty: `▸ SKILLS · none recorded` (inline).

### 4. `_agent_context.py` — parent section

- Tighten inter-lane spacing to a single blank line; keep the major divider + gold `AGENT CONTEXT` header and the
  render-nothing-when-both-empty behavior.

---

## Tests

- **Update unit assertions** for the new strings/styling:
  - `test_agent_memory_reads.py`: `1 reads · 1 files` → `1 read · 1 file`; new `◇` glyph in row assertions; recomputed
    reason-continuation indent; drop `last …` from summary assertions; overflow footer `· … earliest` form.
  - `test_agent_skill_uses.py`: `1 uses · 1 skills` → `1 use · 1 skill`; SKILLS-header-is-green assertion (inspect the
    `Text` span style, not just `.plain`); inline-stats / no-`last` assertions.
  - `test_agent_context.py`: inline empty-state phrasing; lane ordering unchanged.
- **Add focused tests:** `count_phrase` pluralization; a style-level assertion that the MEMORY and SKILLS sub-headers
  carry _different_ accent colors (guards the core "two lanes" intent); memory↔skills row-column alignment.
- **Add a PNG visual snapshot** that actually renders `AGENT CONTEXT` populated (it is currently never captured). Add a
  dedicated agents snapshot (e.g. `agents_context_zoom_modal_120x40`) that seeds representative memory + skill events by
  **patching the two loaders** (no global `~/.sase` writes — keeps the test isolated, mirroring
  `patch_startup_loaders`). Generate the golden with `just test-visual --sase-update-visual-snapshots` and review it by
  eye for the intended look.

---

## Out of scope / non-goals

- No backend, CLI, generator, or generated-`SKILL.md` changes; no skill regeneration / `chezmoi apply`.
- No change to detection, attribution, capping, ordering, or the loader cache/throttle.
- No new help-popup entry — these metadata sub-sections aren't enumerated in the `?` modal.

## Risks & mitigations

- **`◇` (U+25C7) glyph rendering.** It's the only new glyph; `◆`/`▸`/`↳`/`↩`/`·` are already used in the panel. The new
  PNG snapshot will confirm it renders in the pinned Fira Code; if it tofus, fall back to a known-good alternative (e.g.
  `▫`/`◦`).
- **Indent regression.** Centralizing `append_context_reason` + the row prefix is the main correctness risk; the
  recomputed-continuation-indent unit tests guard it.
- **Hot-path perf.** Neutral — string building only, in the existing off-hot-path summary; no new disk reads.

## Verification

- `just install` then `just check`.
- `just test-visual --sase-update-visual-snapshots` to (re)generate the new AGENT CONTEXT golden, then eyeball it.
