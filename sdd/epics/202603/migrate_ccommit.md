---
status: done
create_time: 2026-03-24 12:30:08
bead_id: sase-b
prompt: sdd/prompts/202603/migrate_ccommit.md
---

# Plan: Integrate ccommit into Unified Commit Workflows

Migrate all functionality from the `/commit` skill (ccommit bash script) into the unified `sase commit` system, then
delete the old artifacts.

## Context

**Current state**: Two competing commit paths exist:

1. `/commit` skill → `ccommit` bash script (530 lines, chezmoi-managed) — has rich features (fmt, merge, bead lifecycle,
   push retry, JSON logging, SASE_PLAN)
2. `/sase_git_commit` skill → `sase commit` → `CommitWorkflow` → VCS provider hooks — has clean architecture but is
   bare-bones (just add/commit/push)

**Goal**: Absorb all ccommit features into the `sase commit` path, then delete `/commit` and `ccommit`.

**Design decisions** (from `sdd/research/202603/migrate_ccommit_prompt_critique.md`):

- Migrate ccommit to `src/sase/scripts/sase_git_commit` (new bash script in this repo)
- Add `precommit_command` config field (set to `just fix` in sase repo, `sase_hg_fix` in retired Mercurial plugin)
- Merge/pull from origin/master: add to VCS providers (git: replicate ccommit logic; hg: `hg update <branch>`)
- Bead operations: performed by `sase commit` (support repos without `sdd.version_controlled`)
- SASE_PLAN in commit message + mark done: supported for all repos
- No desktop notifications
- JSON logging: supported by new `sase_git_commit` script
- Delete `/commit` skill and `ccommit` script last
- Update `/sase_git_commit` skill to use `sase commit` (not `.venv/bin/sase commit`)

---

## Phase 1: Add `precommit_command` config field and `sase_hg_fix` script

**Scope**: Config infrastructure + hg fix script. No commit logic changes yet.

### Files to create/modify

**sase repo:**

- `src/sase/default_config.yml` — Add `precommit_command: ""` under a new top-level key (or under `vcs_provider`)
- `sase.yml` — Add `precommit_command: "just fix"` to the local config
- `src/sase/config/core.py` — No changes needed (config loading already merges arbitrary keys)

**retired Mercurial plugin repo (../retired Mercurial plugin):**

- `src/retired_mercurial_plugin/default_config.yml` — Add `precommit_command: "sase_hg_fix"`
- Create a new `sase_hg_fix` script: a thin wrapper that checks if we're in an hg repo (`hg root` succeeds) and runs
  `hg fix` if so, otherwise exits 0. This should be a shell script registered as an entry point in `pyproject.toml`
  (following the same pattern as other scripts in retired Mercurial plugin — check how they register scripts there).

### Validation

- `just install && just check` passes in sase
- Verify `precommit_command` is loadable:
  `python -c "from sase.config.core import load_merged_config; print(load_merged_config().get('precommit_command'))"`
- In retired Mercurial plugin: install and verify `sase_hg_fix` is available on PATH

### Commit instructions

Use `ccommit` to commit changes in each repo after validation passes. For sase:
`cd <repo_root> && ccommit chore "Add precommit_command config field" <files...>`. For retired Mercurial plugin:
`cd <repo_root> && ccommit feat "Add sase_hg_fix script and precommit_command config" <files...>`.

---

## Phase 2: Enhance `CommitWorkflow` and git VCS provider with ccommit features

**Scope**: Add precommit_command execution, merge-with-master, push retry, SASE_PLAN handling, and bead lifecycle to the
Python commit workflow and git VCS provider.

### Files to modify

**`src/sase/workflows/commit/workflow.py`** — The `CommitWorkflow.run()` method orchestrates the commit. Add these steps
(in order), which run regardless of VCS provider:

1. **Precommit command** — Load `precommit_command` from config. If non-empty, run it via `subprocess.run()`. If it
   fails, print error and return False. This runs BEFORE dispatching to the VCS provider.
2. **Bead operations** (after precommit, before VCS dispatch):
   - If `payload` contains a `bead_id` field:
     - Run `sase bead close <bead_id>` via subprocess
     - Run `sase bead sync` via subprocess (best effort)
     - Stage `sdd/beads/` if it has changes (git-specific: only if not hg)
     - Inject bead ID into commit message headline if not already present: `"<message>" → "<message> (<bead_id>)"`
   - If no `bead_id` but `sdd/beads/` or `.beads/` directory exists, still run `sase bead sync` and stage
3. **SASE_PLAN handling** (before VCS dispatch):
   - If `SASE_PLAN` env var is set and points to an existing file:
     - Compute relative path (repo-root-relative if inside repo, otherwise `.sase/sdd/tales/<basename>`)
     - Append `\n\nPLAN=<relative_path>` to the commit message
     - Run `sed -i 's/^status: wip$/status: done/' <plan_file>` to mark done
     - Stage the plan file
4. **Post-commit bead note** (after successful VCS dispatch):
   - If `bead_id` was provided and commit succeeded:
     - Run `sase bead update <bead_id> --notes "COMMIT: <commit_hash>"`
     - Stage `sdd/beads/` and amend the commit (only for create_commit, not for create_proposal/create_pull_request)
5. **Result marker** — Already exists, just ensure `bead_id` is included in the marker JSON.

**`src/sase/vcs_provider/plugins/_git_common.py`** — Enhance the three commit dispatch methods:

- `vcs_create_commit()`:
  - After staging files, re-stage `sdd/beads/` if it has changes (to capture bead sync from workflow)
  - After staging: validate staged changes exist (`git diff --cached --quiet` → fail if empty)
  - Before commit: merge with origin/master (replicate ccommit's `merge_with_master` logic — fetch, stash staged
    changes, merge, restore stash; skip if on default branch and just pull instead)
  - After merge: re-stage `sdd/beads/` again (merge may modify tracked files)
  - Push with retry: if push fails, `git pull --no-edit`, then retry push once
- `vcs_create_proposal()` — Currently just calls `vcs_create_commit`. Keep this delegation but it inherits the
  improvements.
- `vcs_create_pull_request()` — Add validation (staged changes check). The merge-with-master doesn't apply here
  (creating a new branch). Push retry: add the same retry logic after push.

**`src/sase/vcs_provider/_hookspec.py`** — No changes needed (payload dict is flexible).

**retired Mercurial plugin repo (../retired Mercurial plugin/src/retired_mercurial_plugin/plugin.py):**

- `vcs_create_commit()` — Add `hg update <branch>` before amend to sync with remote (equivalent of merge-with-master for
  hg). Best effort — if it fails, continue.
- `vcs_create_pull_request()` — No merge-with-master needed (creating new CL).

### Validation

- `just install && just check` passes in sase
- Manual test: create a test commit in a scratch git repo using `sase commit '{"message": "test: foo", "files": [...]}'`
  and verify the new features work (fmt runs, push retries, etc.)
- In retired Mercurial plugin: `just install` or equivalent passes

### Commit instructions

Use `ccommit` to commit after validation. For sase:
`cd <repo_root> && ccommit feat "Add precommit, merge, push retry, bead lifecycle, and SASE_PLAN to commit workflow" <files...>`.
For retired Mercurial plugin: `cd <repo_root> && ccommit feat "Add hg update sync to vcs_create_commit" <files...>`.

---

## Phase 3: Create `sase_git_commit` bash script with JSON logging

**Scope**: Create a new bash script at `src/sase/scripts/sase_git_commit` that wraps `sase commit` and adds JSON logging
(like ccommit's `~/.ccommit.jsonl` logging). Register it as an entry point.

### Files to create/modify

**Create `src/sase/scripts/sase_git_commit`** (bash script):

- Accept the same JSON payload as `sase commit` (passed as first argument)
- Initialize JSON logging to `~/.sase_git_commit.jsonl` (similar to ccommit's `jlog` function)
- Log: script_start (with args, working_dir, branch, pid), commit result, script_exit (with exit code, duration)
- Delegate to `sase commit '<payload>'` for the actual work
- Parse the exit code and log accordingly
- This script exists primarily for structured logging — all actual commit logic lives in `CommitWorkflow` and VCS
  providers

**Modify `src/sase/scripts/__init__.py`**:

- Add `def sase_git_commit() -> NoReturn: _exec_script("sase_git_commit")`

**Modify `pyproject.toml`**:

- Add `sase_git_commit = "sase.scripts:sase_git_commit"` to `[project.scripts]`

### Validation

- `just install && just check` passes
- `which sase_git_commit` finds the script
- `sase_git_commit '{"message": "test", "files": []}'` logs to `~/.sase_git_commit.jsonl` (will fail on commit, but
  logging should still work)

### Commit instructions

Use `ccommit` to commit: `cd <repo_root> && ccommit feat "Add sase_git_commit script with JSON logging" <files...>`.

---

## Phase 4: Update `/sase_git_commit` skill and stop hook

**Scope**: Update the skill SKILL.md to reflect the new capabilities and tell agents to use `sase commit` (not
`.venv/bin/sase commit`). Update stop hook if needed.

### Files to modify

**Chezmoi repo (~/.local/share/chezmoi):**

`home/dot_claude/skills/sase_git_commit/SKILL.md`:

- Update step 4 (JSON payload) to document the new `bead_id` field in the payload
- Remove the manual bead close/stage instructions from step 5 — the workflow handles this now. Instead, tell the agent
  to include `"bead_id": "<id>"` in the payload if there's an associated bead.
- Update step 6 to use `sase commit '<json>'` (not `.venv/bin/sase commit`)
- Add note about SASE_PLAN being handled automatically
- Update the Notes section to mention precommit_command runs automatically

`home/dot_claude/skills/sase_hg_commit/SKILL.md`:

- Same payload updates (bead_id field)
- Update to use `sase commit` instead of `.venv/bin/sase commit`
- Remove manual bead instructions

### Validation

- Read through both updated SKILL.md files and verify they are accurate and complete
- Run `chezmoi apply` to deploy the changes

### Commit instructions

Use `ccommit` to commit changes in the chezmoi repo:
`cd ~/.local/share/chezmoi && ccommit feat "Update sase_git_commit and sase_hg_commit skills for unified workflow" <files...>`.
Then run `chezmoi apply`.

---

## Phase 5: Delete `/commit` skill and `ccommit` script

**Scope**: Remove the old artifacts now that all functionality has been migrated.

### Files to delete

**Chezmoi repo (~/.local/share/chezmoi):**

- `home/dot_claude/skills/commit/` — Delete the entire directory (SKILL.md)
- `home/bin/executable_ccommit` — Delete the ccommit script

### Files to update

**sase repo:**

- `AGENTS.md` — Remove any references to `/commit` skill or `ccommit`
- `sdd/research/202603/migrate_ccommit_prompt_critique.md` — No changes (keep as historical record)

**Chezmoi repo:**

- Any other files referencing `ccommit` or the `/commit` skill — search and update

### Validation

- `chezmoi apply` succeeds
- `which ccommit` returns nothing (or old cached version — may need to restart shell)
- `claude` agent no longer sees `/commit` as an available skill
- Verify `/sase_git_commit` skill still works correctly

### Commit instructions

Use the `sase_git_commit` script (newly created in Phase 3) to commit in sase:
`cd <repo_root> && sase_git_commit '{"message": "chore: Remove references to old /commit skill and ccommit", "files": [...]}'`.
For chezmoi: use `ccommit` one last time, then apply:
`cd ~/.local/share/chezmoi && ccommit chore "Remove /commit skill and ccommit script" <files...> && chezmoi apply`.

---

## Phase Summary

| Phase | Description                                                  | Repos affected    |
| ----- | ------------------------------------------------------------ | ----------------- |
| 1     | `precommit_command` config + `sase_hg_fix` script            | sase, retired Mercurial plugin |
| 2     | Enhance CommitWorkflow + VCS providers with ccommit features | sase, retired Mercurial plugin |
| 3     | Create `sase_git_commit` bash script with JSON logging       | sase              |
| 4     | Update skill SKILL.md files                                  | chezmoi           |
| 5     | Delete old `/commit` skill and `ccommit`                     | chezmoi, sase     |
