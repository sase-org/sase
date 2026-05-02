---
create_time: 2026-04-06 20:31:27
status: done
prompt: sdd/prompts/202604/fix_revive_bundle_collision.md
---

# Fix: Dismissed Agent Bundle Filename Collision Breaks Revive

## Problem

Pressing `R` (revive) on the Agents tab always shows "No dismissed agents in this scope" despite 769 dismissed agents
existing in `dismissed_agents.json`. This has been broken since commit ac17e11f ("Remove 500-agent limit and split
bundles into per-agent files").

## Root Cause

**Parent workflow agents and their child steps share the same `raw_suffix`** (the workflow's timestamp). When
`_save_agent_bundle` saves a parent and then iterates over its children, each call to `save_dismissed_bundle` writes to
`{raw_suffix}.json` — the **children overwrite the parent's bundle file**.

Evidence from disk:

- 85 bundle files exist in `~/.sase/dismissed_bundles/`
- ALL 85 are workflow children (0 parents)
- 50 of these match entries in the dismissed set
- When loaded, all 50 are filtered out by `_revive.py:97` (`not a.is_workflow_child`)
- Result: empty list, "No dismissed agents in this scope"

The `is_workflow_child` property is computed (`parent_workflow is not None or parent_timestamp is not None`), and for
children their `raw_suffix == parent_timestamp`, confirming the collision.

**Secondary issue**: 202 of 252 unique dismissed suffixes have NO bundle file at all. These are agents dismissed before
the per-agent bundle system existed, whose old monolithic bundles were either trimmed by the former 500-agent limit or
lost during migration. These agents are stuck in limbo — excluded from the active list but invisible in the revive list.

## Fix

### Phase 1: Fix bundle filename collision (core bug)

**`src/sase/ace/dismissed_agents.py`** — Change `save_dismissed_bundle` to use a disambiguated filename for child
agents:

- Parent agents: `{raw_suffix}.json` (unchanged)
- Child agents: `{raw_suffix}__c{step_index}.json`

Update `load_dismissed_bundles`:

- When loading for a specific suffix, also glob for `{suffix}__c*.json` child files
- When loading all (suffixes=None), the existing `*.json` glob already covers both

Update `remove_bundle_by_identity`:

- Accept a new parameter or use existing `child_raw_suffixes` to also remove child bundle files
- When removing a parent bundle, also glob-remove `{suffix}__c*.json`

### Phase 2: Fix existing broken bundles on disk

**`src/sase/ace/dismissed_agents.py`** — Add a one-time migration (`_maybe_fix_child_collisions`) that runs inside
`load_dismissed_bundles`:

- For each `{suffix}.json` file, load it and check `is_workflow_child`
- If it's a child, rename it to `{suffix}__c{step_index}.json`
- This recovers the 50 existing child-only bundles into properly-named files
- Parent data is already lost (overwritten), so no recovery possible for those

### Phase 3: Self-heal orphaned dismissed entries

For the 202 suffixes with no bundle file: these agents can't be revived (no bundle data to reconstruct them from). They
should be cleaned out of `_dismissed_agents` so they don't accumulate forever. Add self-healing logic in `_loading.py`:

- After building `_dismissed_agent_objects`, identify dismissed identities that have no corresponding agent object AND
  no bundle file
- Remove these orphaned identities from `_dismissed_agents` and save
- This is a gradual cleanup — only runs during normal TUI load, no migration step needed

## Files to Change

1. `src/sase/ace/dismissed_agents.py` — Phases 1, 2
2. `src/sase/ace/tui/actions/agents/_loading.py` — Phase 3
3. `src/sase/ace/tui/actions/agents/_killing.py` — No changes needed (it already calls `save_dismissed_bundle` per
   agent; the filename fix in `dismissed_agents.py` handles disambiguation)
4. `src/sase/ace/tui/actions/agents/_revive.py` — No changes needed (`remove_bundle_by_identity` already receives
   `child_raw_suffixes`)

## Testing

- `just check` for lint/type/test suite
- Manual: dismiss a workflow agent, verify both parent and child bundle files are created with distinct names
- Manual: press `R` on Agents tab, verify dismissed parents appear in the revive list
- Manual: revive a parent, verify both parent and child artifacts are restored
