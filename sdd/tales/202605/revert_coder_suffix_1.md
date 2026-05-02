---
create_time: 2026-05-01 15:25:06
status: done
prompt: sdd/prompts/202605/revert_coder_suffix_1.md
---
# Revert Plan-Chain Coder Suffix To .code

## Goal

Return SASE plan-chain implementation follow-up agents to the original `.code` suffix everywhere that affects new
runtime behavior, tests, and this machine's local runtime artifacts.

This is intentionally stricter than the earlier compatibility fix:

- New approved plans must create `<name>.code`, not `<name>.coder`.
- Runtime code should not retain `.coder` as a supported alias.
- Local artifacts on this machine that currently identify agents as `.coder` must be normalized back to `.code` before
  the code stops recognizing `.coder`.

## Findings

The change cannot be handled by a blind `git revert c165bf15`:

- Commit `26e40d43` first introduced `src/sase/plan_chain.py` with `PLAN_CHAIN_CODER_SUFFIX = ".coder"` and changed the
  approve path from hard-coded `.code` to the shared constant.
- Commit `c165bf15` then hardened that decision by canonicalizing `.code` inputs into `.coder` writes. Most helper-side
  canonicalization from that commit has already been removed by later revert work; the remaining live issue is the
  shared canonical suffix and tests that still assert `.coder`.
- Commit `a7391fbb` fixed the fallout by making the TUI accept both `.coder` and `.code` for `CODE` timestamp
  propagation and `PLAN DONE` resume. Once local artifacts are migrated, that compatibility path should be removed so
  `.code` is the only recognized coder follow-up suffix.

Current local artifact scan found operational `.coder` identities in:

- 17 `agent_meta.json` files under `~/.sase/projects/sase/artifacts/ace-run`.
- 23 `done.json` files under the same artifact tree.
- 3 chat filenames under `~/.sase/chats/202605` with `.coder` in the saved agent name.
- A small number of `workflow_state.json` and prompt/chat artifacts that include `.coder` references from prior prompts
  or linked-chat sections.

Historical repo plans/specs also mention `.coder`, but those are documentary history. They should not be mass-rewritten
unless they assert current behavior or are part of the new tests/source surface.

## Design

Make `.code` the only plan-chain coder suffix.

- `PLAN_CHAIN_CODER_SUFFIX` becomes `.code`.
- Remove `LEGACY_PLAN_CHAIN_CODER_SUFFIX` and any `.coder` branch from plan-chain classification.
- `canonical_plan_chain_suffix(".coder")` should return `None`.
- `plan_chain_agent_name("agent", ".coder")` should raise `ValueError`.
- TUI status/resume code should treat only `.code` as a coder follow-up.

The artifact migration should happen before removing local runtime support in the implementation sequence, so any live
TUI scan after the code change sees `.code` metadata and names.

## Implementation Plan

1. Snapshot and normalize local artifacts.
   - Create a timestamped backup of the affected local artifact/chat files before modifying them.
   - Use a structured JSON migration for `agent_meta.json`, `done.json`, `waiting.json`, `workflow_state.json`, and
     `prompt_step*.json` under `~/.sase/projects/sase/artifacts/ace-run`.
   - In JSON string values, replace the operational suffix segment `.coder` with `.code`; this covers names such as
     `te.coder`, nested names such as `ma.code.r1...coder.r1.plan`, `role_suffix: ".coder"`, chat paths, resume/wait
     references, and linked-chat sections.
   - Rename chat files whose filename embeds `.coder` to the corresponding `.code` filename, and update JSON/chat links
     that point at those filenames.
   - Do not rewrite repository historical plans/specs as part of the artifact migration.

2. Revert the source behavior to `.code`.
   - Update `src/sase/plan_chain.py`:
     - set `PLAN_CHAIN_CODER_SUFFIX = ".code"`;
     - remove `LEGACY_PLAN_CHAIN_CODER_SUFFIX`;
     - remove `.coder` from `_KNOWN_SUFFIXES`;
     - make coder classification accept only `.code`.
   - Leave plan suffix `.plan`, question suffix `.q`, feedback suffixes `.2+`, and `PLAN_CHAIN_PARENT_TIMESTAMP_FIELD`
     unchanged.
   - `src/sase/axe/run_agent_exec_plan.py` should naturally emit `.code` after the constant change; verify no call site
     passes `.coder` directly.
   - `src/sase/axe/run_agent_exec.py` should likewise save linked chats under `.code` through the same constant.

3. Revert the recent `.coder` compatibility fix.
   - In `src/sase/ace/tui/models/agent_loader.py`, remove the legacy/canonical set predicate and propagate `code_time`
     only when `agent.role_suffix == PLAN_CHAIN_CODER_SUFFIX` or directly `.code`.
   - In `src/sase/ace/tui/actions/agents/_wait_resume.py`, make `PLAN DONE` resume choose only `.code` follow-ups.
   - Remove imports of `LEGACY_PLAN_CHAIN_CODER_SUFFIX`.

4. Update tests to assert `.code` only.
   - `tests/test_plan_chain_roles.py`: canonical coder names are `agent.code`; `.coder` is unrecognized.
   - `tests/test_axe_run_agent_helpers.py`: follow-up metadata fixtures use `.code` and expect `.code`.
   - `tests/test_agent_loader_status_overrides.py`: remove the `.coder` timestamp case and keep `.code` coverage.
   - `tests/ace/tui/test_resolve_vcs_tag.py`: remove the `.coder` suffix acceptance test.
   - Sweep `src` and `tests` for remaining `.coder` literals. Keep only unrelated generic words such as `coder_prompt`,
     `coder_model`, or intentionally historical non-runtime examples if any are justified.

5. Verify local artifact cleanup.
   - Run a focused search over operational artifact files:
     - `agent_meta.json`, `done.json`, `waiting.json`, `workflow_state.json`, `prompt_step*.json`;
     - chat filenames and linked chat paths under `~/.sase/chats/202605`.
   - Expected result: no operational identity remains with `.coder`; remaining `.coder` hits, if any, must be historical
     prose in old prompts/chats and documented explicitly before finalizing.

6. Run checks.
   - `just install`
   - `.venv/bin/pytest tests/test_plan_chain_roles.py tests/test_axe_run_agent_helpers.py tests/test_agent_loader_status_overrides.py tests/ace/tui/test_resolve_vcs_tag.py`
   - `just check`

## Risks And Mitigations

- Removing `.coder` support before migrating local artifacts would make existing `.coder` children invisible to
  timestamp and resume logic. The migration must happen first.
- A broad textual replacement can corrupt historical prompts by making old user questions inaccurate. Prefer structured
  JSON rewrites and targeted chat filename/link updates; report any remaining historical prose hits separately.
- A raw commit revert could touch reverted independent-plan-chain code or bead records unnecessarily. Keep the source
  diff scoped to current runtime suffix behavior, the recent compatibility predicate, tests, and local artifact cleanup.
