---
create_time: 2026-05-06 10:04:30
status: done
prompt: sdd/prompts/202605/legend_agent_tag_persistence.md
---
# Plan: Fix Legend Agent Tag Persistence

## Problem

Legend work already renders `%tag:<legend_id>` in every generated segment. The snapshot shows the affected agent's
stored xprompt still contains `%tag:sase-26`, which means rendering and prompt preservation worked. The visible failure
is later: the ACE loader grouped the agent under `(untagged)`.

The likely root cause is concurrent tag persistence. Each spawned runner extracts `%tag`, writes it to
`agent_meta.json`, then performs a separate load-modify-save against `~/.sase/agent_tags.json`. Legend launches start
many agents close together, so those independent read/modify/write cycles can clobber each other. This leaves some
agents without an entry in `agent_tags.json` even though their own `agent_meta.json` still contains the correct tag.

## Goals

- Agents launched with `%tag:<name>` should consistently appear under that tag, including high-fanout legend work.
- Existing affected agents should recover automatically when their artifacts contain `"tag"` in `agent_meta.json`.
- Manual tag edits should remain authoritative over stored directive metadata when both exist.
- The fix should be narrow and preserve the current one-tag-per-agent model.

## Implementation Approach

1. Add an atomic update helper for the tag store.
   - Add a public helper in `src/sase/ace/agent_tags.py`, for example `update_agent_tag(identity, tag)`.
   - Validate the tag, acquire an exclusive lock beside `agent_tags.json`, load the latest file while holding the lock,
     update the one identity, and atomically save the full list before releasing the lock.
   - Keep existing `load_agent_tags`, `save_agent_tags`, `set_tag`, and `unset_tag` behavior for callers/tests that
     already operate on in-memory stores.

2. Use the atomic helper from the runner directive path.
   - In `extract_directives_and_write_meta()`, replace the current `load_agent_tags()` / `set_tag()` /
     `save_agent_tags()` sequence with the new atomic helper.
   - Preserve the existing identity shape: `(AgentType.WORKFLOW, cl_name, raw_suffix)`.

3. Recover directive tags from `agent_meta.json`.
   - Extend metadata enrichment so a valid `tag` field in `agent_meta.json` populates `agent.tag`.
   - Apply persisted manual/user tags after metadata enrichment, so `~/.sase/agent_tags.json` continues to override the
     directive tag when the user has manually retagged an agent.
   - Mirror this in the wire/snapshot enrichment path if the wire model already carries tag metadata, or add the field
     if the wire contract needs it.

4. Add focused regression tests.
   - `tests/test_agent_tags.py`: cover the new atomic update helper, including preserving existing unrelated entries.
   - `tests/test_axe_run_agent_phases...` or a focused runner test: verify `%tag` persistence calls the atomic helper
     with the expected workflow identity.
   - Loader/meta enrichment tests: verify an agent with `agent_meta.json` containing `"tag": "sase-26"` loads with that
     tag when no manual tag exists, and that `agent_tags.json` overrides the metadata value when present.

5. Verification.
   - Run focused tests around directives, tag persistence, and loader enrichment first.
   - Because this repo requires it after edits, run `just install` if needed and then `just check`.

## Risks And Notes

- The lock should cover the whole read-modify-write cycle, not just the final replace. Atomic rename alone does not
  prevent lost updates.
- Metadata fallback fixes already-created affected agents without requiring users to hand-edit `agent_tags.json`.
- This stays in Python/TUI glue because it is local persistence and presentation state, not shared Rust core behavior.
