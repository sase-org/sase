# ChangeSpec + Git/GitHub Improvements Plan

## Context

This plan implements a set of interconnected improvements to the ChangeSpec system and VCS workflow support:

1. Restructure STATUS field values (rename existing, add new WIP)
2. Modernize git/gh branch naming and workspace management
3. Rename embedded workflows (#commit→#cl, #amend→#commit, #cl→#cldd)
4. Add git/gh submission logic and a new #pr workflow

The work is split into **4 phases**, each self-contained enough for a separate `claude` instance.

---

## Phase 1: STATUS Field Changes (Rename + New WIP + Migration)

### What

- Rename `"Drafted"` → `"Ready"` everywhere
- Rename `"WIP"` → `"Draft"` everywhere
- Add a new `"WIP"` status that uses `__<N>` suffix but has NO hooks/mentors run by axe
- Write a migration script for existing `.gp` files
- Suffix stripping now happens on transition to `"Ready"` (from either WIP or Draft)

### Transition Graph (new)

```
WIP → Draft       (status change only, suffix stays, NO suffix manipulation)
WIP → Ready       (strip suffix, revert siblings — same logic as old WIP→Drafted)
Draft → Ready     (strip suffix, revert siblings — same logic as old WIP→Drafted)
Ready → Draft     (append __<N> suffix — same logic as old Drafted→WIP)
Ready → Mailed → Submitted
```

Note: Draft→WIP is NOT a valid transition. Both WIP and Draft use `__<N>` suffixes. Only Ready has no suffix.

### Axe behavior for new WIP

- `sase axe` should completely skip WIP ChangeSpecs: no hook checks, no mentor checks, no workflow starts
- Terminal status guards (`Reverted`, `Submitted`, `Archived`) should also include `WIP` in relevant places

### Key files to modify

- `src/sase/status_state_machine/constants.py` — Update `VALID_STATUSES` and `VALID_TRANSITIONS`
- `src/sase/status_state_machine/transitions.py` — Update all status string comparisons, handle WIP↔Draft transitions
  (no suffix change), keep suffix-stripping on →Ready transitions
- `src/sase/ace/scheduler/mentor_checks.py` — Lines 322, 330, 368, 436, 448: rename "WIP" refs to "Draft"; add "WIP" to
  skip list at line 567
- `src/sase/ace/scheduler/hook_checks.py` — Line 120: add "WIP" to terminal-like statuses that don't start new hooks
- `src/sase/axe/hook_jobs.py` — Add WIP filtering in `run_hook_checks`, `run_mentor_checks`
- `src/sase/ace/display_helpers.py` — Update color map keys, add WIP color
- `src/sase/ace/query/tokenizer.py` — Update shorthands: `"w"` → `"WIP"`, `"d"` → `"DRAFT"`, add shorthand for Ready
- `src/sase/commit_workflow/changespec_operations.py` — Line 200: `STATUS: WIP` → `STATUS: Draft`
- `src/sase/ace/changespec/__init__.py` — Line 118: update status tuples
- `src/sase/ace/mentors.py` — All "WIP" refs → "Draft"; docstrings
- `src/sase/change_actions.py` — "Drafted" → "Ready" in promote action
- `src/sase/ace/tui/` — Multiple widgets/modals/actions referencing status strings
- `~/.local/share/chezmoi/home/dot_config/nvim/syntax/` — Vim syntax highlighting groups
- All test files referencing "WIP" or "Drafted" string literals
- **Migration script**: New file `src/sase/scripts/sase_migrate_statuses` that scans `~/.sase/projects/**/*.gp` and
  replaces `STATUS: WIP` → `STATUS: Draft`, `STATUS: Drafted` → `STATUS: Ready`, updates `#WIP` mentor markers to
  `#Draft`

### Verification

- `just check` passes
- Migration script runs on existing `.gp` files without errors
- `sase ace` TUI loads with new status names
- Query shorthands work (`%w` for WIP, `%d` for Draft)
- `sase axe` skips WIP ChangeSpecs entirely

---

## Phase 2: Workflow Renaming + #propose for git/gh

### What

- Rename `#cl` xprompt (in chezmoi sase.yml) → `#cldd`
- Rename `#commit` workflow (xprompts/commit.yml) → `#cl` (xprompts/cl.yml)
- Rename `#amend` workflow (xprompts/amend.yml) → `#commit` (xprompts/commit.yml)
- Add optional `wip` boolean input (default false) to new `#cl` workflow — creates ChangeSpec with WIP status when true
- Add `#propose` support for `#git` and `#gh` workflows (save diff, create ChangeSpec proposal)
- Update all references in chezmoi repo and sase codebase

### Key files to modify

- `xprompts/commit.yml` → rename to `xprompts/cl.yml`, add `wip` boolean input (default false)
- `xprompts/amend.yml` → rename to `xprompts/commit.yml`
- `xprompts/propose.yml` — Verify it works in git/gh context (currently calls `sase_propose_workflow` which may be
  hg-specific)
- `src/sase/scripts/sase_commit_workflow` — Add `--wip` flag; when set, create ChangeSpec with `STATUS: WIP` instead of
  `STATUS: Draft`
- `src/sase/commit_workflow/changespec_operations.py` — Accept `status` parameter to allow WIP vs Draft
- `~/.local/share/chezmoi/home/dot_config/sase/sase.yml`:
  - Rename xprompt `cl` → `cldd` (lines 107-114)
  - Update shortcut `c` from `"#commit(..."` → `"#cl(..."`
  - Update shortcut `a` from `"#amend(..."` → `"#commit(..."`
  - Update shortcut `b` which references `#commit` → `#cl`
  - Update any `#cl` references in inject steps of amend.yml/propose.yml → `#cldd`
- `xprompts/propose.yml` inject step references `#cl` → update to `#cldd`
- `xprompts/amend.yml` (old, now commit.yml) inject step references `#cl` → update to `#cldd`
- `src/sase/amend_workflow.py` — May need adaptation for git/gh propose support
- Any other references to `#commit`, `#amend`, or `#cl` in prompts, docs, or code

### #propose for git/gh

- The `sase_propose_workflow` script needs to detect git/gh context and save a git diff (vs. hg diff)
- In git context: `git diff HEAD` to capture uncommitted changes, save to diff file, create COMMITS proposal entry
- The `branch_local_changes` bash function (used in propose.yml's check_changes step) may need a git-compatible
  implementation

### Verification

- `just check` passes
- `#cl foo` creates a new CL (old #commit behavior)
- `#cl foo wip=true` creates a CL with WIP status
- `#commit` amends an existing CL (old #amend behavior)
- `#cldd` shows CL context (old #cl behavior)
- `#propose` works in a #git or #gh session
- Shortcuts `c`, `a`, `p` in sase.yml work with new names

---

## Phase 3: VCS Branch Naming + Workspace Management

### What

- Replace `agent_<N>` branch names with 100 pre-created human-readable names for git/gh
- Decouple branch names from workspace numbers
- Add `n` input (optional int, default null) to all VCS workflows (#git, #gh, #hg)
- Add `release` input (bool, defaults to `true` when `n` is null, `false` when `n` is given)
- Output `workspace_num` from all VCS workflows
- Add "pinned" marker to RUNNING entries when `release=false` to prevent axe cleanup
- Always create ChangeSpec associated with random branch name if agent committed

### Key files to modify

**New module for branch names:**

- Create `src/sase/branch_names.py`:
  - Hardcoded list of 100 human-readable names (e.g., `amber-falcon`, `bright-cedar`, ...)
  - `get_available_branch_name(workspace_dir: str) -> str` — run `git branch -a` to check which names from the list
    exist as branches in the repo, pick the first unused one
  - Round-robin: track the last-used index in `~/.sase/branch_state/<project>.json` and start searching from there;
    wraps around when reaching end of list

**VCS workflow xprompts:**

- `xprompts/git.yml`:
  - Add inputs: `n` (int, default null), `release` (bool, default depends on n)
  - Setup step: if `n` is given, use that workspace number; otherwise auto-claim
  - Prepare step: replace `agent_{{ setup.workspace_num }}` with branch name from `get_available_branch_name()`
  - Release step: skip if `release=false`; add `meta_workspace_num` output
  - Pass branch_name to `create_changespec_for_workflow()`
- `xprompts/gh.yml` — Same changes as git.yml
- `xprompts/hg.yml` — Add `n` and `release` inputs (branch naming stays hg-native)

**workspace_changespec.py:**

- Update `create_changespec_for_workflow()` signature: accept explicit `branch_name` parameter instead of deriving
  `f"agent_{workspace_num}"`
- Use branch_name as the ChangeSpec name basis (instead of deriving from commit subjects, since the branch name IS the
  identifier)

**Running field:**

- `src/sase/running_field.py`:
  - Add `pinned` flag to workspace claims (e.g., append `| PINNED` to RUNNING entry line)
  - `claim_workspace()`: accept `pinned=False` parameter
  - Stale running cleanup (`cleanup_stale_running_entries`): skip entries marked PINNED even if PID is dead
  - New function `unpin_workspace()` for explicit release

### Verification

- `just check` passes
- `#git sase` creates a branch like `amber-falcon` instead of `agent_105`
- `#gh bbugyi200/sase` uses random branch names
- `#git sase n=105` uses workspace 105 and doesn't auto-release
- `#git sase n=105 release=true` uses workspace 105 and releases after
- ChangeSpec creation works with random branch names
- `sase axe` does not release pinned workspaces

---

## Phase 4: Git/GitHub Submission + #pr Workflow

### What

- Add git/gh ChangeSpec submission logic: merge branch to master, delete branch, append `__YYmmdd_HHMMSS` to name
- Remove auto-PR creation from `#gh` workflow
- Create new `#pr` workflow that creates a PR with generated description
- Create `#new_pr_desc` workflow for PR title/body generation
- When new `#commit` (old #amend) is used on a branch with a PR, update the PR description
- Add `github_username` config field to sase.yml for authorizing PR merges
- Submitting a GitHub ChangeSpec with PR merges the PR if `github_username` matches

### Key files to modify

**Submission logic:**

- `src/sase/status_state_machine/transitions.py` — In the →Submitted transition handler, detect git/gh VCS type and:
  1. Checkout master in primary workspace dir
  2. Merge the branch: `git merge <branch_name>`
  3. Push: `git push`
  4. Delete branch: `git branch -d <branch_name> && git push origin --delete <branch_name>`
  5. Rename ChangeSpec: append `__YYmmdd_HHMMSS` (submission timestamp)
  6. For GitHub projects with PR: use `gh pr merge` instead of local merge
  7. For GitHub projects without `github_username`: error with clear message
- New module `src/sase/git_submit.py` (or extend `src/sase/vcs_provider.py`) with `submit_git_changespec()` function

**Remove auto-PR from gh.yml:**

- `xprompts/gh.yml` — Remove/disable the `create_pr` step (lines 101-138)
- Update `create_changespec` step to not pass `cl_url` from PR

**New workflow files:**

- Create `xprompts/pr.yml`:
  - Input: `name` (word) — branch name / ChangeSpec name
  - Steps: resolve ChangeSpec, call `#new_pr_desc` to generate title/body, run `gh pr create`, update ChangeSpec CL
    field with PR URL
- Create `xprompts/new_pr_desc.yml`:
  - A prompt-based workflow that uses the ChangeSpec description and diff to generate a PR title and body
  - Output: `title` (line), `body` (text)

**Update PR on commit:**

- `xprompts/commit.yml` (the new #commit, was #amend) — Add a post-amend step that:
  1. Checks if current branch has an existing PR: `gh pr view --json url 2>/dev/null`
  2. If PR exists, gets the current PR body and appends a bullet with the new commit message + link
  3. Updates PR: `gh pr edit --body "..."`

**Config:**

- `src/sase/config.py` (or wherever project config is loaded) — Parse `github_username` field
- `~/.local/share/chezmoi/home/dot_config/sase/sase.yml` — Add `github_username: bbugyi200` at appropriate level

### Verification

- `just check` passes
- `#gh` workflow no longer auto-creates PRs
- `#pr my_changespec` creates a PR with a well-crafted title and body
- `#commit` on a branch with existing PR updates the PR description with new commit bullet
- Submitting a git ChangeSpec merges branch to master, deletes branch, renames with timestamp
- Submitting a GitHub ChangeSpec with `github_username` set merges the PR
- Submitting without `github_username` produces clear error message

---

## Phase Dependency Graph

```
Phase 1 (STATUS changes)
   ↓
Phase 2 (Workflow renaming + #propose for git/gh)
   ↓
Phase 3 (Branch naming + workspace management)
   ↓
Phase 4 (Submission + #pr workflow)
```

Each phase must be completed before the next begins.
