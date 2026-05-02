---
create_time: 2026-05-01 14:20:20
status: done
---
# Revert Independent Plan-Chain Agents

## Goal

Remove all repository-visible traces of the duplicate Independent Plan-Chain Agents work tracked by epic bead `sase-1s`
and bead `sase-1t`, including the later `df4347527523ded6ce859401e1770b847e13a3b2` visibility-filter fix.

The intended final behavior is the pre-`sase-1s`/`sase-1t` behavior:

- plan-chain follow-up artifacts are treated as workflow-style children where the older code did so
- the explicit independent plan-chain model/rendering/lifecycle surface is gone
- the duplicate SDD plan/spec files and bead graph records are gone
- the active Agents tab visibility change from `df434752` is gone
- unrelated work that landed around these commits remains intact

## Current Footprint

The direct commits to unwind are:

- `f7536f3a` add SDD spec and plan for `independent_plan_chain_agents`
- `a1922897` add `sase-1s` bead graph
- `5c745659` close `sase-1s.1`
- `3b6bb78f` add duplicate `sase-1t` bead graph and `plans/202605/independent_plan_chain_agents_1.md`
- `52678545` mark independent plan-chain epic ready
- `133fca7b` split plan-chain loader model
- `c165bf15` normalize plan-chain role metadata
- `c54092e1` clarify independent plan-chain loader entries
- `f0ef34e5` render plan-chain phases as independent agents
- `a52d1a27` render plan-chain phases independently
- `2c88e98d` support independent plan-chain lifecycle APIs
- `e87f1c95` polish plan-chain coder chat history
- `df434752` hide completed agents from active agents tab

Important nuance: `src/sase/plan_chain.py` and its baseline tests were introduced earlier by `26e40d43` for bead-work
naming timeout behavior. That file should not be deleted. Only later public helper exports / independent rendering hooks
should be backed out unless they are still needed by retained baseline behavior.

## Implementation Plan

1. Snapshot and protect unrelated state.
   - Confirm `git status --short` is clean before functional edits.
   - Use history/diff inspection instead of broad checkout from an old commit because unrelated work is interleaved on
     `master`.

2. Remove bead and plan/spec traces.
   - Delete `plans/202605/independent_plan_chain_agents.md`.
   - Delete `plans/202605/independent_plan_chain_agents_1.md`.
   - Delete `specs/202605/independent_plan_chain_agents.md`.
   - Remove the `sase-1s`, `sase-1s.*`, `sase-1t`, and `sase-1t.*` records from `sdd/beads/issues.jsonl`.
   - Restore `sdd/beads/config.json` only if those bead allocations changed counters or metadata solely for these
     deleted beads.

3. Revert the code surface introduced by the independent plan-chain work.
   - Back out `plan_chain_parent_timestamp` propagation through scan wire, TUI agent models, loader enrichment, and
     status override logic where it only exists to make plan-chain phases independent.
   - Restore `Agent.is_workflow_child` / child-row semantics in affected TUI grouping, folding, rendering, panel index,
     and banner code.
   - Remove independent plan-chain lifecycle special cases in agent lookup, auto-naming, claim/rename, CLI running
     status, cleanup, dismissal, revive, wait/resume, bundle display, chat-link display, and prompt-panel display.
   - Keep the older `plan_chain.py` helper module and run-agent plan-chain naming behavior that existed before
     `sase-1s`/`sase-1t`.

4. Revert `df434752` explicitly.
   - Restore `src/sase/ace/tui/actions/agents/_loading_helpers.py` default visibility behavior to its prior hidden-only
     filtering.
   - Delete `tests/ace/tui/actions/test_agent_visibility_filter.py`.
   - Remove the `df434752` note added to `plans/202605/agents_tab_agent_explosion.md`, without deleting the unrelated
     SDD file itself.

5. Clean tests and fixtures.
   - Delete tests added only for independent plan-chain rendering, especially
     `tests/ace/tui/models/test_agent_loader_plan_chain_rendering.py`.
   - Remove independent-plan-chain cases from existing tests while keeping baseline plan-chain naming tests from
     `26e40d43`.
   - Ensure tests no longer import APIs that were made public only for independent rendering, unless retained baseline
     code still uses them.

6. Verify no repository-visible traces remain.
   - Run `rg -n "sase-1s|sase-1t|Independent Plan-Chain Agents|independent_plan_chain_agents" .`.
   - Run targeted symbol searches for removed model/API fields such as `is_independent_plan_chain_entry`,
     `is_plan_chain_followup`, and `plan_chain_parent_timestamp` and validate that any remaining references are part of
     retained baseline behavior, not independent rendering.

7. Validate behavior.
   - Run `just install` first per workspace memory.
   - Run targeted tests around agent loading, grouping/folding, running agents, cleanup, wait/resume, names, chat links,
     and the retained plan-chain helpers.
   - Run `just check` before final response because this repo requires it after changes.

## Risk Areas

- Several unrelated features landed between these commits, so a raw chronological `git revert` may conflict or
  accidentally remove unrelated TUI grouping/launch work.
- The term "plan-chain" is not wholly owned by these beads; older plan-chain handoff support remains valid and should
  survive.
- `sdd/beads/issues.jsonl` is append-style project state, but the request asks for all traces, so direct removal of
  the affected JSONL records is appropriate after confirming no other beads depend on them.
