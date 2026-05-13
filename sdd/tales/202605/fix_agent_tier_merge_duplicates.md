---
create_time: 2026-05-13 10:04:14
status: done
prompt: sdd/prompts/202605/fix_agent_tier_merge_duplicates.md
---
# Fix Agent Tier-Merge Duplicate Rows

## Problem

The ACE Agents tab can show two root rows for the same live agent after the tiered agent loader has reconciled full
history. The snapshot shows this as a plain `[agent] ... @t6.cld` row next to an `appears_as_agent` workflow row with
the same name and folded children (`... ×4 @t6.cld`).

The loader has two representations for the same launch:

- Tier 1 artifact-index refreshes can surface a lightweight `AgentType.RUNNING` row from the project `RUNNING` field.
- Tier 2 source scans surface the richer `AgentType.WORKFLOW` parent plus workflow child step rows from
  `workflow_state.json` and `prompt_step_*.json`.

After a complete Tier 2 load, later incomplete Tier 1 refreshes are intentionally merged over the cached full-history
list so the UI does not shrink back to only recent indexed rows. That merge currently keys incoming rows by full agent
identity, which includes `AgentType`. A RUNNING row and WORKFLOW row for the same raw suffix therefore do not match, so
the Tier 1 RUNNING row gets inserted as a new root while the cached Tier 2 WORKFLOW parent remains.

## Technical Approach

Update the post-reconcile incomplete-load merge in `src/sase/ace/tui/actions/agents/_loading_apply.py` so raw suffixes
are treated as a stable launch identity across representation changes.

The intended behavior:

- If an incoming incomplete Tier 1 root has the same `raw_suffix` as a cached non-child root, do not add it as a new
  root.
- Preserve the cached full-history WORKFLOW parent and its child rows when that richer representation exists.
- Keep the current behavior for truly new Tier 1 roots whose suffix is not in cached full history.
- Keep existing identity-based replacement for rows whose identity really does match.
- Preserve dismissed filtering and parent/child grouping behavior.

## Tests

Add a regression test in `tests/test_agent_loader_self_heal.py` covering:

- cached complete-history list contains a WORKFLOW parent and a child step;
- incoming incomplete Tier 1 list contains a RUNNING row with the same suffix;
- the merged result contains only the cached WORKFLOW parent and child, not an extra RUNNING root.

Run focused tests for the loader merge behavior first, then run the repo check required by the workspace instructions.

## Validation

Use the live reproduction only as diagnostic evidence. The durable validation will be the regression test plus
`just check` after changes.
