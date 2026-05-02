---
create_time: 2026-05-01 11:12:32
status: done
prompt: sdd/prompts/202605/recent_chat_cleanup.md
---
# Recent SASE Chat Cleanup Plan

## Context

Recent chats from 2026-05-01 cluster around `fix_just`, `pylimit_split`, `refresh_docs`, and the rollback/postmortem for
the `sase-1p` agent-loader Rust migration. The `fix_just` and `pylimit_split` chats report green checks and no required
source changes. The postmortem chats identify two cleanup concerns after the Rust migration revert:

- `sdd/research/202604/rust_core_next_candidates.md` still recommends the same agent-loader orchestration migration that was
  attempted under `sase-1p` and then reverted.
- `sase bead show sase-1p` still resolves a closed bead through merged multi-workspace bead discovery because
  `/home/bryan/projects/github/sase-org/sase_100/sdd/beads/issues.jsonl` still contains the stale reverted bead rows.

Current source evidence confirms the product rollback is otherwise clean: only rollback documentation, a refresh-docs
screenshot spec, and the stale research recommendation mention `sase-1p` / `agent_compose`.

## Goals

1. Prevent a future agent from re-attempting the reverted `agent_compose` migration by following stale research
   guidance.
2. Remove the stale `sase-1p` bead rows from the old `sase_100` workspace so merged bead discovery no longer resurrects
   the reverted epic.
3. Keep the rollback plan/spec as historical documentation.
4. Verify the current checkout remains healthy after changes.

## Implementation Plan

1. Update `sdd/research/202604/rust_core_next_candidates.md`:
   - Add a prominent 2026-05-01 status note near the top explaining that the agent-loader orchestration recommendation
     was attempted as `sase-1p` and reverted.
   - Mark the candidate as "do not retry as written" in the table and section heading.
   - Replace the active `agent_compose` port instructions with a postmortem-aware alternative: keep Python composition
     as product/oracle, migrate smaller colder slices first, require real TUI/status parity, preserve a kill switch, and
     do not delete the Python path until live-ish end-to-end evidence passes.
   - Update ranking/sequence language so candidate #3 is not treated as a straightforward next migration.

2. Clean stale bead metadata in `/home/bryan/projects/github/sase-org/sase_100/sdd/beads/issues.jsonl`:
   - Remove only rows with IDs `sase-1p` and `sase-1p.1` through `sase-1p.8`.
   - Preserve all unrelated bead rows.
   - Leave the old workspace checkout itself untouched.

3. Verify cleanup:
   - Run `rg -n "sase-1p|agent_compose|compose_agent_list|AgentCompose|SASE_AGENT_COMPOSE"` in the current checkout and
     confirm remaining hits are either rollback/history docs, the refresh-docs screenshot spec, or the new warning.
   - Run `sase bead show sase-1p` and confirm it no longer resolves, or capture the next remaining source if it still
     does.
   - Run `git status --short` to review tracked/untracked changes.
   - Because this repo changed, run `just install` if needed and `just check` before finishing.

## Non-Goals

- Do not delete rollback plans/specs from `plans/202605` or `specs/202605`; they are useful historical context.
- Do not edit unrelated sibling workspaces except for the specific stale bead rows in `sase_100`.
- Do not rework SASE bead discovery behavior in this cleanup pass.
