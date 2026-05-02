---
create_time: 2026-04-11 21:20:44
status: done
prompt: sdd/prompts/202604/init_skills_migration.md
---

# Plan: Bead sase-h.3 — Migration & Cleanup

## Overview

Phase 3 of the `sase init-skills` epic. Phases 1 (XPrompt model fields) and 2 (skill sources + CLI command) are
complete. This phase replaces the manually-maintained chezmoi skill files with generated ones and documents the new
workflow.

## Context

There are 13 skill files across 3 providers (4 skills x 3 providers + 1 gemini-only `sase_hg_commit`), all currently
hand-maintained in `~/.local/share/chezmoi/home/dot_{claude,gemini,codex}/skills/*/SKILL.md`. The
`sase init-skills --force` command can now generate all of them from 5 source templates in `src/sase/xprompts/skills/`.

## Steps

### 1. Generate skill files into chezmoi

Run `sase init-skills --force` to overwrite all 13 chezmoi skill files with generated versions.

### 2. Verify generated output

Diff the generated files against the chezmoi git state to review what changed. Differences should be limited to
intentional improvements (e.g. consistent flag descriptions, unified formatting). There should be no regressions in
skill content.

### 3. Deploy via chezmoi

Run `chezmoi apply` so the generated files are copied to their live locations.

### 4. Document in AGENTS.md

Add a section to AGENTS.md documenting:

- What `sase init-skills` does
- When to run it (after changing skill source files in `src/sase/xprompts/skills/`)
- That chezmoi skill files are now generated, not hand-edited

### 5. Run checks

- `just check` in the sase repo
- `just check` in the chezmoi repo

### 6. Commit

Commit the chezmoi changes (the overwritten skill files) and the AGENTS.md update in the sase repo.
