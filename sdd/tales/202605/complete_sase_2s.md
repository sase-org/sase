---
create_time: 2026-05-10 14:40:47
status: open
tier: epic
prompt: sdd/prompts/202605/complete_sase_2s.md
---

# Plan: Complete the sase-2s diagram-review epic

## Goal

Bring the sase-2s "Review existing docs diagrams for clarity and accuracy" epic to a clean closed state. The 10 critique
phases are committed on `master`; the 10 corresponding regeneration phases are NOT — every regen agent produced output
in its sibling workspace, but none of those PNGs / `prompt.md` files made it into `master`. Five regen beads have been
prematurely closed (with notes claiming verification) and five are still IN_PROGRESS. We need to land the work that was
already produced, close all phase beads, close the epic, and update the plan-file frontmatter.

## Current State (verified)

`sase bead show sase-2s` reports 10 closed critique beads (`sase-2s.1`..`sase-2s.10`) and 10 regen beads where 5 are
CLOSED (`.15`..`.19`) and 5 are IN_PROGRESS (`.11`..`.14`, `.20`). `git log --grep=sase-2s` shows commits only for the
critique phase. `master`'s `docs/images/*.png` for every diagram still has the 11:12 mtime from `sase-1z` / `sase-1g`
era — i.e. the originals.

The actual regen output lives in sibling workspaces:

| Bead | Diagram                      | Location of work        | Form                                                                         |
| ---- | ---------------------------- | ----------------------- | ---------------------------------------------------------------------------- |
| .11  | bead-epic-work               | `sase_106` stash@{0}    | stash (PNG + prompt.md)                                                      |
| .12  | commit-workflow              | `sase_109` stash@{0}    | stash (PNG + prompt.md)                                                      |
| .13  | rust-backend-boundary        | `sase_102` stash@{0}    | stash (PNG + prompt.md)                                                      |
| .14  | sase-component-communication | `sase_101` stash@{1}    | stash (PNG only)                                                             |
| .15  | sase-rust-core-integration   | `sase_104` working tree | uncommitted (PNG + new prompt.md, plus a stray `docs/architecture.md` embed) |
| .16  | sase-telegram-integration    | `sase_108` working tree | uncommitted (PNG + prompt.md)                                                |
| .17  | sase_tui_tabs                | `sase_106` working tree | uncommitted (PNG + prompt.md)                                                |
| .18  | xprompt-resolution           | `sase_107` working tree | uncommitted (PNG + prompt.md)                                                |
| .19  | workflow-execution           | `sase_110` working tree | uncommitted (PNG + prompt.md)                                                |
| .20  | zorg-zettel-vision           | `sase_101` stash@{0}    | stash (PNG only)                                                             |

Two beads (.14 and .20) updated only the PNG, not the `prompt.md`. The plan's regen description says "update or create
the prompt.md", so re-using the existing prompt.md verbatim is acceptable as long as the PNG is the new one. We will not
block on regenerating prompt.md.

The `sase_104` stash also touches `docs/architecture.md` to add an `<img>` embed under "Rust Core Boundary" — that line
was not part of the regen contract ("Do not touch unrelated diagrams or prose"). The image is already embedded
elsewhere; we drop that hunk.

The `sdd/beads/issues.jsonl` modifications in each workspace are stale local copies of bead state and must NOT be
brought back — `sase bead` is the source of truth.

## Plan

### Phase 1 — Salvage and commit each regenerated diagram (10 commits)

For every diagram listed above, in `sase_101` (the workspace I'm running in):

1. Copy the regenerated PNG (and prompt.md if present) from the source workspace / stash into `docs/images/`. Use the
   stash blobs via `git -C <ws> show stash@{N}:<path>` piped to a file, or `cp` for working-tree files. Do NOT pull
   `sdd/beads/issues.jsonl` or `docs/architecture.md` from the foreign workspaces.
2. Stage exactly the PNG and prompt.md.
3. Commit using the repo's commit skill (`sase commit`) with the bead-tagged message convention used by every other
   commit on this epic, e.g. `chore: regenerate <diagram> infographic (sase-2s.<N>)`.

Order: do .11 → .20 sequentially to keep commit messages tidy. Each commit is independent of the others.

### Phase 2 — Close the 5 IN_PROGRESS phase beads

`sase-2s.11`, `.12`, `.13`, `.14`, `.20` are still IN_PROGRESS. After their commits land, run
`sase bead close sase-2s.<N>` for each, with a short note linking to the commit hash.

### Phase 3 — Sanity-check the closed regen beads

`sase-2s.15`..`.19` are already CLOSED but their commits did not exist until Phase 1. No state change is needed; the
phase exists only to confirm `sase bead show <id>` shows them closed and to spot-check that the diagrams now embedded on
master match the bead notes.

### Phase 4 — Run repo checks

Per `memory/short/build_and_run.md`, file changes to this repo require `just check` before reply. The diff is binary
plus a few markdown lines, so lint/mypy should be a no-op, but we run the full gate once at the end.

### Phase 5 — Close the epic bead and run unused-symbol audit

1. `sase bead close sase-2s` with a summary note.
2. Run `just pyvision` (only available after epic close) to detect any unused symbols left behind. Fix anything it
   surfaces; this epic is docs-only so we do not expect findings.

### Phase 6 — Mark the plan file done

Edit the frontmatter of `sdd/epics/202605/diagram_review.md`, changing `status: open` to `status: done`. Commit with a
short message; this is the canonical convention used to retire epic plan files.

## Out of Scope

- Re-running GPT image generation. The artifacts already exist; we just need to land them.
- Re-evaluating each regenerated diagram against its critique. Two of the regen agents (`.18`, `.19`) recorded explicit
  verification notes; the others followed the same xprompt template. A separate audit can reopen any specific diagram
  later if it still falls short.
- Any change to `docs/architecture.md` or other prose docs — every regen description forbids that, and the existing
  embeds already point at the regenerated filenames.
