---
name: research_yyyymm_migration
description: Migrate flat sdd/research/ markdown files into sdd/research/YYYYMM/ date-stamped
  subdirs, mirroring the structure of specs/ and plans/.
create_time: 2026-04-28 12:50:33
status: done
prompt: sdd/prompts/202604/research_yyyymm_migration.md
---

# Migrate `sdd/research/` to date-stamped `sdd/research/YYYYMM/` subdirs

## Problem

`sdd/research/` currently holds ~47 markdown design notes in a flat layout (plus three small topical subdirectories:
`plugins/`, `telegram/`, `texts/`). The other planning-artifact directories — `specs/` and `plans/` — are organized into
date-stamped subdirectories of the form `YYYYMM` (e.g. `specs/202604/`, `plans/202603/`), one per calendar month, based
on the month each artifact was first committed.

Note on terminology: the user's request says "YYmmdd", but the existing pattern in `specs/` and `plans/` is **YYYYMM**
(year + month, 6 digits — e.g. `202604` = April 2026). This plan follows the established `YYYYMM` convention.

We want `sdd/research/` to follow the same convention so that:

- The three planning directories are visually and structurally consistent.
- `ls sdd/research/` does not return a 40+ entry wall of files.
- Older research notes naturally fall to the bottom of file pickers / completion lists.

## Scope

- Reorganize every `.md` file currently under `sdd/research/` (including those in the three topical subdirs) into
  `sdd/research/YYYYMM/` based on each file's git creation month.
- Update cross-references to those files in tracked Markdown so links don't go stale.
- Preserve git history for each moved file (use `git mv`).

Out of scope:

- Renaming or rewriting the content of any research note.
- Changing how `sdd/research/` is consumed by tooling — there is none. (`grep` confirmed no `src/` code paths reference
  `sdd/research/`; only docs and other planning artifacts do.)
- Touching `.prettierignore` — it already ignores `sdd/research/` recursively, so the new subdirs inherit the rule.

## Design

### Date assignment

For each file, the YYYYMM bucket is determined by the file's **first-commit date** in git history (matching how new
specs/plans are filed: a spec committed on 2026-04-25 lands in `specs/202604/`).

Concretely:

```
YYYYMM = $(git log --diff-filter=A --format='%ai' -- <path> | tail -1 | cut -c1-7 | tr -d '-')
```

A pre-flight pass over `sdd/research/**/*.md` produces this distribution (already computed during planning):

- `202602` — 4 files (all currently in topical subdirs: `plugins/`, `telegram/`, `texts/`)
- `202603` — 21 files
- `202604` — 22 files

Total: **47 files**.

### Flattening the topical subdirs

`specs/` and `plans/` use a flat layout inside each `YYYYMM/`, with no topical subgrouping. The migration mirrors that:
the three existing subdirectories (`sdd/research/plugins/`, `sdd/research/telegram/`, `sdd/research/texts/`) are flattened — their
contents move directly into the appropriate `sdd/research/YYYYMM/` directory by date, and the now-empty topical dirs are
removed.

A pre-flight check confirms there are **no filename collisions** after flattening (all 47 basenames are unique within
their target month).

### Cross-reference updates

`grep -rE 'sdd/research/[a-zA-Z0-9_/]+\.md'` finds **64 references** across **46 tracked files** (mostly under `plans/`,
`specs/`, `docs/`, plus a handful inside `sdd/research/` itself, plus `sdd/beads/issues.jsonl`).

For each moved file, rewrite occurrences of its old path (e.g. `sdd/research/202604/sase_perf_research.md`,
`sdd/research/202603/telegram_improvements.md`) to its new path (`sdd/research/202604/sase_perf_research.md`,
`sdd/research/202603/telegram_improvements.md`) in:

- All tracked `*.md` under `plans/`, `specs/`, `sdd/research/`, `docs/`.
- `sdd/beads/issues.jsonl` (one match — keep the data accurate).

Skip:

- `memory/` files — none reference `sdd/research/`.
- Anything outside the repo.

### Git history preservation

Use `git mv <old> <new>` for every move so blame and `git log --follow` continue to work. Create the destination
directories first (`mkdir -p sdd/research/202602 sdd/research/202603 sdd/research/202604`).

## Plan

1. **Confirm date map.** Re-run the YYYYMM computation in a single pass and write the (target_dir, source_path) pairs to
   a plain text manifest in the workspace (not committed). Sanity-check the totals match (4 / 21 / 22).
2. **Create destination dirs** with `mkdir -p`.
3. **Move files** via `git mv` per the manifest. Remove the now-empty `plugins/`, `telegram/`, `texts/` directories.
4. **Rewrite cross-references** in tracked Markdown + `sdd/beads/issues.jsonl`. A simple `sed` pass keyed off the
   manifest works because each old path is unique. After the pass, re-run the grep and confirm zero `sdd/research/<flat>.md`
   matches remain (every hit should now include a `YYYYMM/` segment).
5. **Verification.**
   - `git status` shows only renames + the cross-reference edits — no untracked or deleted-without-rename files.
   - `ls sdd/research/` shows only the three `YYYYMM/` directories.
   - `git log --follow sdd/research/202604/sase_perf_research.md` walks back through the original flat-path history.
   - `just check` passes (no code changed, but this catches any doc-link checker we may have missed).
6. **Commit** as a single CL titled along the lines of `chore: organize sdd/research/ into YYYYMM subdirs`. The diff is
   almost entirely renames + ~64 path edits in cross-references.

## Risks & mitigations

- **Stale link in an untracked / out-of-tree consumer.** `sdd/research/` is doc-only and not referenced from `src/`, so the
  blast radius is limited to local notes. Mitigation: the commit message explicitly calls out the path change so anyone
  reading recent history can find-and-replace.
- **Filename collision after flattening topical dirs.** Pre-checked; none exist. If one is introduced before
  implementation, the conflicting file gets a disambiguating suffix (e.g. `_telegram`) — no silent overwrites.
- **Wrong YYYYMM bucket** (e.g. a file rewritten months after its initial commit). The first-commit date is the intended
  convention (matches how specs/plans are filed at creation time), so this is by design.

## Files affected (summary)

- 47 file moves under `sdd/research/`.
- ~46 tracked Markdown files updated (cross-reference rewrites).
- 1 line update in `sdd/beads/issues.jsonl`.
- 0 source code changes.
