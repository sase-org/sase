---
create_time: 2026-04-07 17:04:13
status: done
prompt: sdd/prompts/202604/fix_agents_revive_suffix_alias.md
---

# Fix Agents Tab Revive Not Reappearing In Panel

## Problem Statement

Reviving a dismissed agent from the Agents tab using `R` can show a success notification (`Revived ...`) but no
corresponding agent/workflow row appears in the Agents panel afterward.

## Diagnosis Summary

The revive flow currently removes dismissed state by exact identity tuple (`(AgentType, cl_name, raw_suffix)`), but the
loader’s suppression logic is broader:

- Non-running agents are filtered out if their `raw_suffix` appears in _any_ dismissed entry.
- Running agents can also be filtered by `(cl_name, raw_suffix)` fallback combinations.

This mismatch means revive can remove one identity while leaving another dismissed alias with the same `raw_suffix` (for
example from prior dedup/type/cl-name transitions or legacy/stale entries). On reload, suffix-based filtering still
hides the revived artifacts, so the UI reports revive success but no row is shown.

## Goals

1. Make revive semantics match loader suppression semantics so a revived agent reliably reappears.
2. Preserve existing child/follow-up revive behavior.
3. Add regression tests for dismissed-alias cleanup to prevent reintroduction.

## Proposed Changes

1. Update revive bookkeeping to remove dismissed aliases by suffix set, not just exact identity.

- In `_do_revive_agent`, after selecting the target + child/follow-up suffixes, remove any dismissed identities whose
  `raw_suffix` is in that revive suffix set.
- Keep existing explicit child/follow-up handling; extend it with suffix-based cleanup.

2. Apply the same suffix-based cleanup path to batch revive.

- In `_do_revive_agents`, build the union of all revived suffixes (parents + children/follow-ups), then remove any
  dismissed identities with matching suffixes before persisting.

3. Keep bundle/file restoration unchanged unless additional mismatch appears during validation.

- Current restore logic is likely correct for this symptom; fix focuses on dismissed-set/filter mismatch.

4. Add tests.

- New tests for revive cleanup behavior that simulate dismissed alias tuples sharing suffixes.
- Assert the revived suffix aliases are removed before save and that revive still calls restore/load paths.

## Validation Plan

1. Targeted tests for new revive cleanup helper/flow.
2. Run full repo checks required by project instructions:

- `just install`
- `just check`

## Risks and Mitigations

- Risk: Over-broad suffix cleanup could undismiss unrelated entries sharing the same timestamp.
  - Mitigation: Restrict cleanup to suffixes explicitly tied to the revived parent/children set and add tests around
    this behavior.

- Risk: Batch revive path diverges from single revive.
  - Mitigation: Use shared helper logic across single and batch paths.
