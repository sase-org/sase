---
title: Complete prompt command epic verification
bead_id: sase-4o
create_time: 2026-06-13 16:09:34
status: wip
prompt: sdd/prompts/202606/prompt_command_completion.md
---

# Complete `sase prompt` Epic Verification

## Context

The `sase prompt` epic is implemented and all phase beads are closed, but final verification found one remaining
contract mismatch: the CLI documentation says command groups with an exact `list` child, including `sase prompt`,
default to that list view when invoked bare. The current prompt handler still treats a missing prompt subcommand as a
usage error.

## Plan

1. Make bare `sase prompt` dispatch to the same code path as `sase prompt list`, using the list command defaults.
2. Add focused parser/handler coverage so this default cannot regress.
3. Run the relevant prompt command tests, then the repository-required verification.
4. Update the epic plan frontmatter status to `done` once the verification passes.
5. Close bead `sase-4o`.
