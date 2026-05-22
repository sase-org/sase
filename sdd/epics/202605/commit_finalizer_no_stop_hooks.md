---
create_time: 2026-05-21 19:11:00
status: done
bead_id: sase-3v
tier: epic
prompt: sdd/prompts/202605/commit_finalizer_no_stop_hooks.md
---
# Plan: Commit Finalizer Without Stop Hooks

## Goal

Remove SASE's dependence on provider-native agent stop hooks for commit enforcement. After this work, SASE-owned agent
execution should detect dirty main and configured sibling workspaces after model turns, run an in-band commit
finalization turn when needed, and verify the repos are clean without requiring `sase_commit_stop_hook` or
`sase_sibling_commit_stop_hook` hook configuration.

The rollout should keep `sase commit` as the only mutation engine, keep all supported runtimes uniform, and make the
SASE development sibling repos explicit configuration instead of hardcoded hook behavior.

## Phase 1: Supervisor-Owned Commit Finalizer

Owner: one agent instance.

Build a provider-neutral commit finalizer that runs from SASE's LLM invocation lifecycle, not from runtime hook config.

- Add a module such as `src/sase/commit_finalizer.py` or `src/sase/llm_provider/commit_finalizer.py`.
- Reuse the existing commit instruction behavior from `src/sase/scripts/sase_commit_stop_hook.py`, but move the reusable
  pieces out of the hook script so normal code, tests, and any temporary compatibility wrappers call the same helper.
- Replace Codex's private `_maybe_run_commit_fallback_turn()` with the common finalizer path.
- Invoke the finalizer from `src/sase/llm_provider/_invoke.py` after a successful provider call and before
  postprocessing saves the final chat. The finalizer should call the same selected provider again with a bounded
  follow-up prompt.
- Make all providers participate uniformly: Claude, Gemini, Qwen, Codex, and opencode should not need provider-specific
  enforcement branches.
- Keep a compatibility disable switch for existing workflows:
  - Honor `SASE_DISABLE_COMMIT_STOP_HOOK` during the transition.
  - Add explicit config defaults under `commit.finalizer` in `src/sase/default_config.yml`, with matching
    `config/sase.schema.json` coverage.
- Use bounded re-entry:
  - Default max passes: 2.
  - After each pass, recheck dirty state.
  - If changes remain after max passes, fail the agent run with a clear diagnostic instead of silently passing.
- Persist finalizer artifacts into `SASE_ARTIFACTS_DIR`, for example:
  - `commit_finalizer_pass_1_prompt.md`
  - `commit_finalizer_pass_1_response.md`
  - `commit_finalizer_result.json`

Tests:

- Unit test finalizer skip behavior when disabled, outside a SASE agent, and with a clean repo.
- Unit test main-workspace dirty detection causing a follow-up provider call.
- Unit test bounded retry and failure when the follow-up does not clean the repo.
- Update existing Codex fallback tests to assert the common finalizer path instead of Codex-only fallback behavior.

## Phase 2: Configured Sibling Repos and Workspace-Matched Resolution

Owner: one agent instance.

Make sibling repos first-class config so SASE can check sibling workspaces without the repo-local sibling stop hook.

- Add top-level `sibling_repos` to `src/sase/default_config.yml` and `config/sase.schema.json`.
- Add resolver code that accepts entries like:

  ```yaml
  sibling_repos:
    - name: core
      path: ../sase-core
    - name: github
      path: ../sase-github
    - name: chezmoi
      path: ~/.local/share/chezmoi
      workspace:
        strategy: none
  ```

- Resolve relative paths from the primary checkout recorded in the project file, not from a numbered workspace like
  `sase_10`.
- For adjacent git siblings, materialize and expose the same workspace number as the main agent, for example `sase_10`
  -> `sase-core_10`.
- For absolute/non-adjacent siblings such as chezmoi, support `workspace.strategy: none`.
- Export a canonical JSON env var and ergonomic aliases:
  - `SASE_SIBLING_REPOS_JSON`
  - `SASE_SIBLING_REPO_CORE_DIR`
  - `SASE_SIBLING_REPO_CORE_PRIMARY_DIR`
- Scrub stale inherited `SASE_SIBLING_REPO_*` and `SASE_SIBLING_REPOS_JSON` in `launch_spawn.py`.
- Add resolved sibling metadata to `agent_meta.json`.
- Add a concise prompt note telling agents to use workspace-matched sibling paths.
- Recompute sibling env for deferred `%wait` agents after a real workspace is claimed.
- Configure this repo's `sase.yml` with all supported sibling repos:
  - `../sase-core`
  - `../sase-github`
  - `../sase-telegram`
  - `../sase-nvim`
  - `~/.local/share/chezmoi` with `strategy: none`

Tests:

- Resolver tests for relative anchoring, suffix workspace paths, absolute paths, missing dirs, alias sanitization, and
  JSON/env serialization.
- Launch tests for env scrubbing and prompt metadata.
- Deferred workspace tests for recomputing sibling env after workspace `0` becomes a real workspace.

## Phase 3: Finalizer Checks Configured Siblings

Owner: one agent instance.

Teach the common finalizer to inspect configured sibling workspaces directly.

- When `SASE_SIBLING_REPOS_JSON` is present, inspect exactly those `workspace_dir` paths.
- If env is absent but config is available, resolve siblings from config as a fallback.
- Do not scan hardcoded `../sase-*` globs in the finalizer.
- Build finalizer instructions that list dirty repos and direct agents to `cd <workspace_dir>` before using the
  `/sase_git_commit` skill.
- Treat dirty sibling repos the same as dirty main repo for finalization: run a follow-up turn, recheck, and fail after
  max passes if dirty state remains.
- Keep main workspace VCS detection through the existing VCS provider path; sibling repos can start with git status
  checks because the current maintained sibling set is git-based.

Tests:

- Dirty configured sibling workspace triggers a follow-up turn.
- Dirty primary sibling checkout is ignored when a numbered workspace is configured.
- Dirty chezmoi repo with `strategy: none` is checked at the configured absolute path.
- Multiple dirty repos are listed together and rechecked after follow-up.

## Phase 4: Skill and Result Evidence Hardening

Owner: one agent instance.

Make the finalizer easier to audit without changing `sase commit` as the mutation engine.

- Teach `src/sase/scripts/sase_git_commit` to write a per-run `commit_skill_invoked.json` marker when
  `SASE_ARTIFACTS_DIR` is set.
- Update `src/sase/xprompts/skills/sase_git_commit.md` to invoke `sase_git_commit ...` instead of raw `sase commit ...`
  so skill use is observable.
- Keep the wrapper delegating to `sase commit`.
- Add `run_id`, `cwd`, `files`, and method metadata to the marker.
- Add `run_id` and `cwd` to `commit_result.json`.
- Run `sase init-skills --force` after modifying the skill source, then apply chezmoi changes before verification.
- Do not add `/sase_hg_commit` to Claude or Codex; keep the current runtime skill matrix.

Tests:

- Wrapper writes `commit_skill_invoked.json` in an agent artifact dir before delegating.
- Commit result marker includes the run id when run from an agent.
- Skill source tests still pass after regeneration.

## Phase 5: Remove Hook Configuration and Compatibility Dependence

Owner: one agent instance.

Remove provider-native stop hook configuration from this repo and chezmoi-managed agent config.

- Remove SASE commit stop hook entries from chezmoi-managed files:
  - `~/.local/share/chezmoi/home/dot_claude/settings.json`
  - `~/.local/share/chezmoi/home/dot_gemini/settings.json.tmpl`
  - `~/.local/share/chezmoi/home/dot_qwen/settings.json`
  - `~/.local/share/chezmoi/home/dot_codex/hooks.json`
- Remove repo-local sibling hook entries from:
  - `.claude/settings.json`
  - `.gemini/settings.json`
  - `.qwen/settings.json`
- Remove any Codex-specific sibling-hook fallback calls from `src/sase/llm_provider/codex.py`.
- Keep or delete hook scripts based on compatibility needs:
  - At minimum, no code path should depend on them.
  - If kept, mark them compatibility-only and make tests prove enforcement does not require them.
- Run `chezmoi apply --force` after editing chezmoi files.
- Run `just check` in the chezmoi repo because the memory instructions require it after modifying dotfiles.

Tests:

- Static search proves no active agent config references `sase_commit_stop_hook` or `sase_sibling_commit_stop_hook`.
- Existing hook-specific tests are removed, rewritten as finalizer tests, or explicitly scoped to compatibility
  wrappers.
- Codex fallback tests no longer symlink or execute `tools/sase_sibling_commit_stop_hook`.

## Phase 6: End-to-End Verification

Owner: one agent instance.

Verify the actual user requirement with real SASE agents after hook config has been removed and `chezmoi apply --force`
has run.

Preparation:

- Run `just install` in this workspace before checks.
- Run focused tests for finalizer, sibling resolver, launch env, and skill wrapper.
- Run `just check` in this repo.
- Run `just check` in every modified sibling repo:
  - `~/.local/share/chezmoi`
  - Any of `../sase-github`, `../sase-telegram`, `../sase-nvim`, `../sase-core` if touched.

Real-agent verification:

1. Launch a Codex agent using the `codex/gpt-5.3-codex-spark` model. Its prompt should ask it to make harmless dummy
   file changes in this repo and not mention committing. The finalizer must detect the dirty workspace and get the agent
   to use the commit infrastructure.
2. Launch a Claude agent using the `claude/sonnet` model. Its prompt should ask it to remove the dummy changes and not
   mention committing. The finalizer must again detect the dirty workspace and get the agent to commit through SASE.
3. Inspect the two agent artifacts:
   - Finalizer pass artifacts exist.
   - `commit_skill_invoked.json` exists when the skill wrapper path is used.
   - `commit_result.json` exists for commit-producing runs.
   - The workspace is clean afterward.
4. Confirm no provider-native stop hook was responsible:
   - Active chezmoi-applied configs no longer reference the old hook scripts.
   - The run succeeds even without the hook entries.

Suggested launch prompts:

```text
%model:codex/gpt-5.3-codex-spark
%name:commit_finalizer_verify_add
Create a harmless verification file under tmp/ or another ignored scratch location in this repo, then stop. Do not make
any commits and do not mention commit commands unless SASE asks you to.
```

```text
%model:claude/sonnet
%name:commit_finalizer_verify_remove
Remove the harmless verification file created by the previous verification agent, then stop. Do not make any commits and
do not mention commit commands unless SASE asks you to.
```

Acceptance criteria:

- No configured Claude, Gemini, Qwen, or Codex stop hook invokes `sase_commit_stop_hook` or
  `sase_sibling_commit_stop_hook`.
- Dirty main workspaces are committed through SASE after the initial prompt omits commit instructions.
- Dirty configured sibling workspaces are also detected and finalized.
- The SASE repo and configured sibling repos are clean at handoff except for intentional uncommitted work owned by the
  current implementation agent.
- `just check` passes for every modified repo.
