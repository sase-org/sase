---
create_time: 2026-03-25 20:12:16
status: done
prompt: sdd/prompts/202603/commit_propose_entry_ids.md
---

# Plan: Fix #propose/#commit COMMITS entry creation and Proposal Id display

## Context

`#propose` and `#commit` workflows currently rely on `commit_result.json` for metadata, but they do not reliably append
new `COMMITS` entries to the target ChangeSpec. In Mercurial (`retired Mercurial plugin`), `create_proposal` returns a CL URL
(`http://cl/...`), which is currently passed through as `meta_proposal_id`, causing the Agents panel to show
`Proposal Id: http://cl/...` instead of the intended proposal entry id (e.g. `1a`).

## Goals

1. Ensure `#propose` appends a new proposal entry `(Na)` in ChangeSpec `COMMITS` when commit/proposal creation succeeds.
2. Ensure `#commit` appends a new numeric entry `(N)` in ChangeSpec `COMMITS` when commit creation succeeds.
3. Ensure `#propose` reports `meta_proposal_id` as the proposal entry id (e.g. `1a`) for Agents panel display.
4. Preserve current behavior where stop-hook may create `commit_result.json` before fallback steps run.

## Implementation Steps

1. Add a shared utility under `src/sase/workflows/commit_utils/` to:
   - Read env (`SASE_ARTIFACTS_DIR`, `SASE_AGENT_PROJECT_FILE`, `SASE_AGENT_CL_NAME`).
   - Load `commit_result.json` and detect success context.
   - Locate best `response_path` and `diff_path` from `prompt_step_*.json` markers.
   - Append a commit/proposal history entry via existing `add_commit_entry` / `add_proposed_commit_entry` helpers.
   - Return structured result including appended `entry_id` (for proposal mode).

2. Update `src/sase/xprompts/propose.yml`:
   - Keep creation logic intact.
   - Add post-step that invokes the new utility in `proposal` mode.
   - Emit `proposal_id`/`meta_proposal_id` from appended proposal entry id when available; fallback to existing commit
     result value only if append fails.

3. Update `src/sase/xprompts/commit.yml`:
   - Add analogous post-step in `commit` mode to append numeric history entries.
   - Keep current metadata output compatible while ensuring entry append runs in stop-hook and fallback paths.

4. Add tests:
   - Unit tests for the new utility (commit mode and proposal mode).
   - Snapshot or integration-style tests for xprompt YAML behavior where possible (focus on output fields and entry
     append side effects).

5. Validation:
   - Run `just install` (workspace bootstrap).
   - Run focused tests for new/changed files.
   - Run lint/type checks relevant to touched files.

## Risks and Mitigations

- Risk: duplicate entries if external skills already append entries.
  - Mitigation: utility should only append once per run by using current workflow artifacts context and by targeting
    workflows that currently do not append in core.
- Risk: missing marker files in unusual execution paths.
  - Mitigation: gracefully fallback to `None` for chat/diff paths and still append entry note.

## Success Criteria

- Running `#propose` after file edits creates a new `(Na)` entry and Agents panel shows `Proposal Id: <Na>`.
- Running `#commit` after file edits creates a new `(N)` entry.
- Existing commit/proposal dispatch behavior remains unchanged beyond metadata/id correctness.
