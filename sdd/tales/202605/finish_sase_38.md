---
create_time: 2026-05-12 18:54:55
status: wip
prompt: sdd/prompts/202605/finish_sase_38.md
---
# Finish sase-38 Verification And Closure

## Goal

Complete the remaining lifecycle-contract work for `sase-38`, verify the implementation, close the child and epic beads,
and mark the epic plan done.

## Findings

- The committed scan/CLI path classifies active records without `run_started_at` as `STARTING`.
- The Agents tab direct loaders still instantiate RUNNING-field and home `running.json` rows as `RUNNING`.
- Metadata enrichment parses `run_started_at`, but it does not promote a `STARTING` row to `RUNNING`, and marker
  overrides are still gated only on `RUNNING`.
- This leaves phase 1 incomplete even though later presentation work exists.

## Plan

1. Update Agents tab active-row loading so RUNNING-field and home `running.json` rows start as `STARTING`.
2. Update metadata enrichment so `run_started_at` promotes `STARTING` to `RUNNING`, while wait, question, and plan
   markers still override both `STARTING` and `RUNNING`.
3. Add focused regression tests for RUNNING-field rows, home `running.json` snapshot rows, wait-marker overrides, and
   run-timestamp promotion.
4. Run targeted tests, then `just install` and `just check`.
5. Update `sdd/epics/202605/agents_starting_status.md` frontmatter to `status: done` once verification passes.
6. Close `sase-38.1`, `sase-38.6`, and then close epic bead `sase-38`.
7. After the epic bead is closed, run `just pyvision` if the command is available.
