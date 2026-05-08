---
create_time: 2026-05-08 13:14:28
status: done
prompt: sdd/prompts/202605/revived_agent_visibility_resume.md
---
# Plan: Stabilize Revived Agent Visibility and Resume Lookup

## Problem

After reviving an old dismissed agent (`abb_3` / dismissed name `260504.abb_3`), the agent can appear and disappear from
the Agents tab, and `#resume:abb_3` can fail with "No agent found".

The observed local state confirms two separate root causes:

- The dismissed bundle for `20260504224829` stores `agent_name: "260504.abb_3"`, but the surviving artifact
  `agent_meta.json` for that artifact directory contains no `name` field. Revive recreates `done.json`, but
  `find_named_agent()` resolves names from `agent_meta.json`, not from `done.json`, so the revived `abb_3` remains
  visible to the TUI loader but invisible to `#resume` lookup.
- The persistent artifact index is missing/empty (`sase agents index verify --json` reports `indexed_rows: 0`,
  `missing_rows: 9079`). The TUI therefore uses the bounded Tier 1 source scan (`max_records=200`) before scheduling a
  full-history reconcile. A revived May 4 completed agent is outside that recent window, so normal Tier 1 refreshes can
  temporarily drop it and the later Tier 2 full scan can bring it back.

## Implementation

1. Make revive rewrite existing metadata instead of skipping it.
   - Change `_restore_agent_meta()` so it reads an existing `agent_meta.json`, merges the loader/name fields from the
     revived `Agent`, and writes the file back when fields changed.
   - Preserve unrelated existing metadata fields.
   - Ensure `name`, provider/model fields, workspace, chat path, wait fields, parent/role/plan metadata, and timestamps
     are present when available on the revived `Agent`.

2. Add focused regression coverage for resume lookup after revive.
   - Build a dismissed/revived fixture where `agent_meta.json` exists but lacks `name`.
   - Revive the agent and assert `agent_meta.json["name"] == "abb_3"`.
   - Assert `find_named_agent("abb_3")` resolves after revive.

3. Keep revived historical agents visible across incomplete Tier 1 refreshes.
   - Introduce a small in-memory set of revived raw suffixes on the Agents app state.
   - When revive succeeds, record the revived parent/child suffixes.
   - During `_compute_apply_loaded_agents`, merge previously visible revived agents whose suffixes are missing from an
     incomplete Tier 1 load, so the list does not flicker between Tier 1 and Tier 2.
   - Clear entries when a complete full-history load includes them or when the agent is dismissed again.

4. Add loader regression coverage for the Tier 1/Tier 2 flicker.
   - Simulate a current visible revived historical agent.
   - Apply an incomplete Tier 1 load that omits it and assert it remains in the filtered list.
   - Apply a complete load or dismissal and assert the pin is cleared/ignored.

5. Verify.
   - Run the focused tests for revive/name lookup and loader preservation.
   - Run `just install` if needed, then `just check` per repo instructions because this changes repo files.
