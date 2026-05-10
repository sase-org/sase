---
create_time: 2026-05-07 22:53:22
bead_id: sase-2d
tier: epic
status: done
prompt: sdd/prompts/202605/bead_env_commit_contract.md
---
# Plan: Require Bead Association Through Environment for `sase commit`

## Goal

Replace the optional `sase commit --bead-id/--bead` contract with an environment-driven contract:

- A single environment variable, `SASE_BEAD_ID`, carries the bead ID for the current agent's work.
- When `SASE_BEAD_ID` is set, `sase commit` always associates that bead with the commit by including the bead ID in the
  commit message and commit result metadata.
- Agents can no longer choose whether to pass a bead flag; the CLI flag is removed.
- The commit stop hook conditionally tells the agent to close the exact bead ID after committing, but only when
  `SASE_BEAD_ID` is set.
- Generated commit skills and docs stop mentioning `--bead-id`.

The implementation should preserve one invariant: if an agent is launched with `SASE_BEAD_ID=sase-x.1`, a successful
`sase commit` cannot produce a commit whose message lacks `sase-x.1`.

## Design Decisions

1. Use `SASE_BEAD_ID` as the canonical env var. It is short, not tied to one agent runtime, and mirrors `SASE_PLAN`,
   `SASE_COMMIT_METHOD`, and `SASE_BUG_ID`.

2. Keep bead-message association inside `sase commit`, not inside the skills. Skills are advisory. The CLI/workflow must
   enforce the invariant.

3. Do not infer `SASE_BEAD_ID` from arbitrary `%tag` values. Tags are a general grouping feature. Phase-specific bead
   launch code can set the env var deliberately when it already knows it is launching bead work.

4. Treat bead closure as an explicit post-commit agent action, but keep the workflow robust against dirty bead state.
   The stop hook should say: after `sase commit` succeeds, run `sase bead close <SASE_BEAD_ID>` and verify the bead is
   closed. Because version-controlled bead stores can become dirty after a post-commit close, the implementation phase
   must either make closure idempotently covered by the commit workflow or provide a clean follow-up path. The preferred
   low-risk approach is:
   - `sase commit` injects the bead ID and performs existing best-effort bead sync/COMMIT-note handling.
   - stop-hook guidance still tells the agent to close the bead explicitly after commit.
   - if the workflow already closed the bead, the explicit close is a no-op; if automatic close is later removed, the
     hook guidance is already in place.

## Phase 1: CLI Contract and Env Resolution

Owned files:

- `src/sase/main/parser_commit.py`
- `src/sase/main/cl_handler.py`
- focused CLI tests in `tests/test_commit_cli.py`

Tasks:

1. Remove `-b/--bead-id` from the `sase commit` parser.
2. Add a small helper in the commit command path that reads and validates `SASE_BEAD_ID`.
   - Empty or whitespace-only values are treated as unset.
   - A set value is copied into the payload as `bead_id`.
   - No CLI override exists.
3. Preserve `sase commit --resume` behavior by continuing to rely on the checkpoint payload captured by the original
   commit attempt.
4. Add regression tests:
   - parser rejects `--bead-id`.
   - env `SASE_BEAD_ID=sase-42` produces `payload["bead_id"] == "sase-42"`.
   - unset env omits `bead_id`.
   - env-based bead association works with method aliases and message files.

Acceptance:

- `sase commit --bead-id ...` fails at argument parsing.
- Every normal `sase commit` invocation with `SASE_BEAD_ID` set passes that bead into `CommitWorkflow`.

## Phase 2: Commit Workflow Enforcement

Owned files:

- `src/sase/workflows/commit/precommit_hooks.py`
- `src/sase/workflows/commit/workflow.py` if validation belongs there
- `src/sase/vcs_provider/plugins/_git_commit_dispatch.py` only if post-commit bead note behavior needs tightening
- workflow/artifact tests in `tests/test_commit_workflow_dispatch.py`, `tests/test_commit_workflow_artifacts.py`, and
  related commit workflow tests

Tasks:

1. Make bead message injection an enforced workflow behavior whenever payload `bead_id` is present.
   - The bead ID must be added to the first commit-message line if absent.
   - Avoid duplicate insertion when the message already includes that exact bead ID.
2. Ensure create-commit and create-pull-request paths both receive the bead-tagged message before VCS dispatch.
3. Keep create-proposal semantics intentional.
   - If proposals should not close beads, they may still record `bead_id` in result metadata.
   - Add an explicit test for the chosen behavior so it is not accidental.
4. Revisit current automatic bead close behavior in `handle_beads`.
   - If retained, document it as idempotent with the stop-hook close instruction.
   - If removed, replace it with a mechanism that does not leave `sdd/beads/` dirty after the agent closes the bead.
5. Keep post-commit COMMIT-note amend behavior wired to payload `bead_id`.

Acceptance:

- A unit test proves a payload with `bead_id` cannot dispatch a message without that ID.
- Existing post-commit bead note tests still pass.
- The result marker still includes `bead_id`.

## Phase 3: Agent Launch Propagation

Owned files:

- `src/sase/bead/work.py`
- `src/sase/bead/cli_work.py` and launch plumbing if needed
- launch/rendering tests under `tests/test_bead/`
- any agent metadata tests that validate bead fields

Tasks:

1. Set `SASE_BEAD_ID` in the environment for agents launched by `sase bead work`.
   - Phase agents get their phase bead ID, e.g. `sase-x.2`.
   - Land agents get the epic/legend bead they are responsible for closing, matching the existing land prompt semantics.
2. Preserve existing `%tag:<bead_id>` and agent-name behavior for UI grouping.
3. Add tests that inspect rendered launch plans or spawn arguments and prove `SASE_BEAD_ID` is propagated.
4. Do not set `SASE_BEAD_ID` for non-bead tags such as `%tag:review`.

Acceptance:

- Bead-work agents are launched with the bead ID in env, not only in prompt text.
- Existing Agents-tab bead display remains unchanged.

## Phase 4: Stop Hook and Skill Contract

Owned files:

- `src/sase/scripts/sase_commit_stop_hook.py`
- `tests/test_commit_stop_hook.py`
- `src/sase/xprompts/skills/sase_git_commit.md`
- `src/sase/xprompts/skills/sase_hg_commit.md`
- generated skill deployment tests under `tests/main/` if snapshots/assertions mention commit examples

Tasks:

1. Update `_build_commit_instruction_message` to read or receive the optional bead ID.
2. When `SASE_BEAD_ID` is set, append explicit guidance:
   - commit using the runtime's `/sase_*_commit` skill,
   - after `sase commit` succeeds, run `sase bead close <bead_id>`,
   - explicitly name the bead ID in the instruction text.
3. When `SASE_BEAD_ID` is unset, do not mention bead closure.
4. Remove skill instructions that ask agents to run `sase bead list --status=in_progress` or pass `--bead-id`.
5. Update commit examples to omit bead flags.
6. Run `sase init-skills --force` after changing skill source templates, then `chezmoi apply` if this workspace is
   expected to deploy generated skills.

Acceptance:

- Stop-hook tests cover both env-set and env-unset messages.
- No generated/source commit skill tells the agent to use `--bead-id`.
- The stop-hook block text explicitly includes `sase bead close <actual-bead-id>` only when `SASE_BEAD_ID` is present.

## Phase 5: External Provider and Documentation Sweep

Owned files:

- `docs/commit_workflows.md`
- `docs/configuration.md`
- any README/config docs that list commit flags or payload fields
- sibling repos only if the sweep finds live references:
  - `../retired Mercurial plugin`
  - `../sase-github`
  - `~/.local/share/chezmoi`

Tasks:

1. Remove `--bead-id` from docs and payload examples.
2. Add `SASE_BEAD_ID` to environment-variable documentation.
3. Verify the GitHub plugin remains unaffected because it consumes the already-mutated core payload.
4. Verify the Google/Hg plugin remains unaffected because it consumes the already-mutated message first line; update
   plugin docs or tests only if they mention the old flag.
5. If any sibling repo is modified, run its local `just check` before finishing that phase.

Acceptance:

- `rg -- '--bead-id|--bead|bead_id.*optional-bead'` has no stale user-facing contract references except historical SDD
  files.
- Docs explain that bead association is automatic when `SASE_BEAD_ID` is set.

## Phase 6: End-to-End Verification and Cleanup

Owned files:

- tests only unless bugs are found
- generated skill files only if Phase 4 did not regenerate/deploy them

Tasks:

1. Run focused test suites:
   - `pytest tests/test_commit_cli.py tests/test_commit_stop_hook.py`
   - relevant commit workflow tests touched in Phase 2
   - relevant bead work launch tests touched in Phase 3
   - relevant init-skills tests touched in Phase 4
2. Run `sase init-skills --force` if skill sources changed and generated outputs are not current.
3. Run `just install` and then `just check` from this workspace before final handoff.
4. Do a final grep sweep for removed CLI flags and stale examples.
5. Manually smoke-test a dry commit path with `SASE_BEAD_ID` set by mocking or using a temporary git repo if the
   existing tests do not cover the full handler-to-dispatch path.

Acceptance:

- The full repo check passes.
- The removed CLI flag is gone from code, skills, and active docs.
- The enforced env-based commit-message bead association is covered by tests.

## Suggested Phase Dependencies

1. Phase 1 must land first because it defines the public CLI/env contract.
2. Phase 2 depends on Phase 1's payload shape.
3. Phase 3 can run after Phase 1 and in parallel with Phase 4 if ownership is kept separate.
4. Phase 4 depends only on the env var name from Phase 1.
5. Phase 5 should run after Phases 1-4 so docs match the final behavior.
6. Phase 6 lands last as the integration gate.
