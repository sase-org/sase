---
create_time: 2026-05-01 15:05:58
status: done
prompt: sdd/prompts/202605/fix_coder_code_timestamp.md
---
# Fix Coder Suffix Timestamp Regression

## Problem

The `sase ace` snapshot shows a plan-chain implementation child named `@te.coder`, but the selected parent plan agent's
metadata panel has no `CODE` timestamp row. The snapshot also raises the question of why new follow-up agents use
`.coder` rather than `.code`.

The current code has two overlapping historical behaviors:

- Older plan approval code used `.code` for coder follow-up agents.
- Commit `26e40d43` introduced the retained baseline `src/sase/plan_chain.py` helper and made `.coder` the canonical
  coder suffix, with `.code` treated as a legacy alias.

The later Independent Plan-Chain Agents work (`sase-1s` and `sase-1t`) temporarily added helper APIs that recognized
both suffixes in the loader. The revert in `38e1760f` correctly removed the independent rendering/model surface, but it
also restored two legacy-only `.code` checks while the retained runner still creates `.coder` artifacts. That mismatch
explains the missing `CODE` row: `_apply_status_overrides()` only propagates `code_time` from children whose
`role_suffix == ".code"`, so a `.coder` child is ignored.

There is also a cleanup gap from the revert: `38e1760f` removed the `sase-1s` and `sase-1t` bead records, but later
close commits (`a1d570be`, `ebdcaa84`) reintroduced those JSONL records as closed/reverted beads. That leaves
repository-visible traces of the reverted duplicate epics.

## Goals

- Keep `.coder` as the canonical suffix unless we intentionally decide to revert the older `26e40d43` baseline helper.
- Preserve support for legacy `.code` artifacts already on disk.
- Restore the `CODE` timestamp row for canonical `.coder` follow-up agents.
- Fix the stale resume path that still searches only for `.code` coder follow-ups.
- Remove the reintroduced `sase-1s` / `sase-1t` bead records without changing unrelated beads.
- Avoid reintroducing the Independent Plan-Chain Agents model/rendering/lifecycle surface.

## Implementation Plan

1. Add a small local coder-suffix predicate in the retained Agents-tab workflow-child path.
   - Treat `".coder"` and `".code"` as coder follow-up suffixes.
   - Keep it local to `agent_loader.py` and wait/resume code, or import only the existing constants, so we do not
     restore the removed public independent-plan-chain helper APIs.

2. Fix metadata timestamp propagation.
   - In `src/sase/ace/tui/models/agent_loader.py`, replace the `agent.role_suffix == ".code"` check with the
     coder-suffix predicate.
   - Update comments from `.code child` to coder follow-up language so future readers do not assume `.code` is the only
     supported spelling.

3. Fix resume selection for completed plan workflows.
   - In `src/sase/ace/tui/actions/agents/_wait_resume.py`, select the coder follow-up using the same suffix predicate
     instead of `role_suffix == ".code"`.
   - This keeps `R`/resume behavior consistent with the visible canonical `.coder` child names.

4. Add focused regression coverage.
   - Extend `tests/test_agent_loader_status_overrides.py` with a `.coder` child case that asserts parent `code_time` is
     populated.
   - Keep the existing `.code` tests to preserve old artifact compatibility.
   - Add or extend a small wait/resume test if there is already an ergonomic fixture; otherwise cover the predicate
     through a helper-level test rather than building a heavy TUI harness.

5. Remove reverted epic bead records.
   - Delete only JSONL records whose ids are `sase-1s`, `sase-1s.*`, `sase-1t`, or `sase-1t.*` from
     `sdd/beads/issues.jsonl`.
   - Leave `sdd/beads/config.json` alone unless inspection shows the later close commits changed allocation metadata;
     it is currently already back at `next_counter: 64`.

6. Verification.
   - Run targeted tests for plan-chain roles and status overrides.
   - Run a trace search for `sase-1s|sase-1t|Independent Plan-Chain Agents|independent_plan_chain_agents` and inspect
     any remaining matches. The existing revert plan may still mention them as historical context; the bead graph should
     not.
   - Run `just install` if needed, then `just check` before final response per repo memory.

## Risks

- There are many historical `.code` artifacts under `~/.sase`; the fix must remain backward-compatible.
- Removing bead JSONL records should be scoped by exact id prefix to avoid damaging unrelated bead state.
- Reintroducing the public helper names from `sase-1s`/`sase-1t` would blur the revert boundary, so the implementation
  should stay minimal.
