---
create_time: 2026-05-06 00:15:46
status: done
prompt: sdd/prompts/202605/epic_phase_bead_order.md
---
# Plan: Epic Phase Bead Ordering

## Problem

The `bd/new_epic` automation asks an agent to create one phase bead per phase in an epic plan, but it does not specify
that those `sase bead create --type phase(<epic_id>)` commands must run serially in phase order. Bead child IDs are
allocated from the current maximum persisted child counter for the parent, so the suffix is creation order, not a parsed
phase number. If an agent parallelizes the phase creation commands, or simply creates them out of order, titles like
`Phase 1` can be assigned IDs like `<epic>.5`.

The example epic confirms this pattern: `sase-42.4.5` is titled `Phase 1`, while `sase-42.4.2` is titled `Phase 2`.
`sase bead work` only consumes existing phase children and pre-claims them; it is not the source of the mismatched IDs.

## Approach

Keep the fix scoped to the epic creation xprompt unless investigation finds a mandatory code-side invariant. The user’s
preferred fix should be sufficient for the observed epic-integration issue because the agent creating the epic is the
piece choosing command ordering.

1. Update the built-in `bd/new_epic` prompt in `src/sase/default_config.yml` so it explicitly requires:
   - create the epic plan bead first;
   - create phase beads one at a time, in the exact order they appear in the plan file;
   - do not run phase bead creation commands in parallel;

2. Add focused regression coverage in `tests/test_bead_xprompt_tags.py` asserting the built-in prompt contains the new
   serial phase-creation guidance. This makes future prompt edits less likely to remove the guard.

3. Update the `#bd/new_epic` docs in `docs/xprompt.md` to document that phase beads are intentionally created
   sequentially because child bead suffixes are allocated by creation order.

4. Validate with the focused xprompt-tag tests. Because this repo requires `just check` after file changes, run
   `just install` if needed and then `just check` before finishing.

## Non-Goals

Do not change the Rust bead allocator in this pass unless the prompt-level fix proves insufficient. A general
cross-process mutation lock would be a broader storage-hardening change: useful, but beyond the narrow epic integration
bug if the only bad writer is the `bd/new_epic` agent doing parallel creation.
