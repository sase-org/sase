---
create_time: 2026-06-18 23:48:08
status: done
prompt: sdd/prompts/202606/prompt_search_completion.md
---
# Complete `sase-4y` Prompt Search Verification

## Context

Verification of bead `sase-4y` found that the five child phase beads are closed and the merged commits for `sase-4y.1`
through `sase-4y.5` are present on `master`. The main implementation matches the epic plan, but one documented source
layout is not actually covered from the CLI path: `sase prompt search` passes the repository root to the SDD loader, and
the loader scans `sdd/prompts`, root `prompts`, and specs aliases, but not project-local `.sase/sdd/prompts`.

## Plan

1. Extend the prompt-search SDD source loader so a normal project-root search includes `.sase/sdd/prompts` in addition
   to the existing canonical and legacy roots, while preserving de-duplication of overlapping paths.

2. Add focused regression tests for project-root discovery of `.sase/sdd/prompts`, including a CLI-level `--source sdd`
   search that proves local SDD snapshots are visible to users.

3. Align the user-facing docs with the implemented tag behavior: `--tag` searches SDD `prompt_tags` plus embedded
   xprompt chips, not low-signal runner-control `%` directives.

4. Install the workspace if needed and run targeted prompt-search tests plus the required repository checks.

5. Close epic bead `sase-4y` once verification passes.
