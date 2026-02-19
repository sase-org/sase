---
bead_id: sase-py2
---

> **Superseded**: This plan has been superseded by [Git Change Specs v3](git_change_specs_v3.md).

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

### Implementation tip

Before starting, run `grep -rn '"WIP"\|"Drafted"\|"wip"\|"drafted"' src/ tests/` to find every occurrence. The
comprehensive file list below was generated this way — use it as a checklist.

### Key files to modify (source — 39 files)

**Status state machine:**

- `src/sase/status_state_machine/constants.py` — Update `VALID_STATUSES` and `VALID_TRANSITIONS`
- `src/sase/status_state_machine/mail_suffix.py` — Update status string references
- `src/sase/status_state_machine/transitions.py` — Rename functions and update all status string comparisons (see
  function rename table below); handle WIP↔Draft transitions (no suffix change), keep suffix-stripping on →Ready
  transitions

**Function renames in `transitions.py`:**

| Current name                              | New name                               | Reason                                                |
| ----------------------------------------- | -------------------------------------- | ----------------------------------------------------- |
| `_handle_wip_transition`                  | `_handle_draft_transition`             | Handles Ready→Draft (was Drafted→WIP)                 |
| `_handle_non_wip_transition`              | `_handle_non_draft_transition`         | Handles Draft→Ready (was WIP→Drafted)                 |
| `_revert_sibling_wip_changespecs`         | `_revert_sibling_draft_changespecs`    | Reverts Draft siblings (was WIP siblings)             |
| `_check_siblings_for_unreverted_children` | (keep name, update docstring/comments) | References "WIP" → "Draft"                            |
| `SiblingRevertResult`                     | (keep name, update docstring)          | "sibling WIP ChangeSpec" → "sibling Draft ChangeSpec" |
| `_handle_suffix_strip`                    | (keep name, update docstring)          | "WIP to Drafted" → "Draft to Ready"                   |
| `_handle_suffix_append`                   | (keep name, update docstring)          | "Drafted to WIP" → "Ready to Draft"                   |

Also update all `set_mentor_wip_flags` / `clear_mentor_wip_flags` calls — these rename to `set_mentor_draft_flags` /
`clear_mentor_draft_flags`.

**Commit workflow:**

- `src/sase/commit_workflow/changespec_operations.py` — Line 200: `STATUS: WIP` → `STATUS: Draft`
- `src/sase/commit_workflow/changespec_queries.py` — Update status string references
- `src/sase/commit_workflow/workflow.py` — Update status string references

**ChangeSpec management:**

- `src/sase/ace/changespec/__init__.py` — Line 118: update status tuples
- `src/sase/ace/changespec/models.py` — Update status string references
- `src/sase/ace/changespec/section_parsers.py` — Update status string references

**Ace operations & display:**

- `src/sase/ace/display.py` — Update status-to-color mappings
- `src/sase/ace/display_helpers.py` — Update color map keys, add WIP color
- `src/sase/ace/operations.py` — Update status string references
- `src/sase/ace/archive.py` — Update status string references
- `src/sase/ace/revert.py` — Update status string references
- `src/sase/ace/mail_ops.py` — Update status string references
- `src/sase/ace/mentors.py` — All "WIP" refs → "Draft"; docstrings; rename `set_mentor_wip_flags` →
  `set_mentor_draft_flags`, `clear_mentor_wip_flags` → `clear_mentor_draft_flags`

**Query system:**

- `src/sase/ace/query/__init__.py` — Update status string references
- `src/sase/ace/query/evaluator.py` — Update status string references
- `src/sase/ace/query/parser.py` — Update status string references
- `src/sase/ace/query/tokenizer.py` — Update shorthands: `"w"` → `"WIP"` (stays, but now means new WIP), `"d"` →
  `"DRAFT"` (was DRAFTED), add `"y"` → `"READY"` (`%r` is already REVERTED)

**Ace handlers:**

- `src/sase/ace/handlers/mail.py` — Update status string references
- `src/sase/ace/handlers/reword.py` — Update status string references

**Ace scheduler:**

- `src/sase/ace/scheduler/mentor_checks.py` — Lines 322, 330, 368, 436, 448: rename "WIP" refs to "Draft"; add "WIP" to
  skip list at line 567
- `src/sase/ace/scheduler/mentor_runner.py` — Update status string references
- `src/sase/ace/scheduler/suffix_transforms.py` — Update status string references
- `src/sase/ace/scheduler/hook_checks.py` — Line 120: add "WIP" to terminal-like statuses that don't start new hooks

**Ace TUI widgets:**

- `src/sase/ace/tui/widgets/keybinding_footer.py` — Update status string references
- `src/sase/ace/tui/widgets/mentors_builder.py` — Update status string references
- `src/sase/ace/tui/widgets/ancestors_children_panel.py` — Update status string references
- `src/sase/ace/tui/widgets/changespec_list.py` — Update status string references

**Ace TUI modals & actions:**

- `src/sase/ace/tui/modals/project_select_modal.py` — Update status string references
- `src/sase/ace/tui/modals/rename_cl_modal.py` — Update status string references
- `src/sase/ace/tui/actions/base.py` — Update status string references
- `src/sase/ace/tui/actions/clipboard.py` — Update status string references
- `src/sase/ace/tui/actions/hints/_accept.py` — Update status string references
- `src/sase/ace/tui/actions/proposal_rebase.py` — Update status string references

**Core & configuration:**

- `src/sase/change_actions.py` — "Drafted" → "Ready" in promote action
- `src/sase/mentor_config.py` — Update status string references
- `src/sase/main/parser.py` — Update status string references
- `src/sase/axe/hook_jobs.py` — Add WIP filtering in `run_hook_checks`, `run_mentor_checks`

**Scripts:**

- `src/sase/scripts/sase_commit_workflow` — Update status string references

**External config (chezmoi):**

- `~/.local/share/chezmoi/home/dot_config/nvim/syntax/` — Vim syntax highlighting groups for WIP/Draft/Ready

**Migration script (new file):**

- `src/sase/scripts/sase_migrate_statuses` — Scans `~/.sase/projects/**/*.gp` and replaces `STATUS: WIP` →
  `STATUS: Draft`, `STATUS: Drafted` → `STATUS: Ready`, updates `#WIP` mentor markers to `#Draft`

### Key files to modify (tests — 57 files)

All test files referencing "WIP" or "Drafted" string literals need updating. Major ones include:

- `tests/test_status_state_machine_constants.py`
- `tests/test_status_state_machine_transitions.py`
- `tests/test_status_state_machine_field_updates.py`
- `tests/test_status_state_machine_mail_suffix.py`
- `tests/test_mentor_checks.py`
- `tests/test_mentors_wip.py`
- `tests/test_mentors.py`
- `tests/test_changespec_operations.py`
- `tests/test_changespec_queries.py`
- `tests/test_changespec_status_indicators.py`
- `tests/test_query_evaluator.py`
- `tests/test_query_integration.py`
- `tests/test_query_property_filters.py`
- `tests/test_display_helpers.py`
- `tests/test_hook_checks.py`
- `tests/test_change_actions.py`
- `tests/test_commit_workflow.py`
- `tests/test_keybinding_footer_status.py`
- `tests/conftest.py`

Plus ~38 more test files. Run `grep -rln '"WIP"\|"Drafted"' tests/` for the full list.

### Verification

- `just check` passes
- Migration script runs on existing `.gp` files without errors
- `sase ace` TUI loads with new status names
- Query shorthands work (`%w` for WIP, `%d` for Draft, `%y` for Ready)
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
- `xprompts/propose.yml` — Replace `branch_local_changes` bash call with VCS provider (see below)
- `src/sase/scripts/sase_commit_workflow` — Add `--wip` flag; when set, create ChangeSpec with `STATUS: WIP` instead of
  `STATUS: Draft`
- `src/sase/commit_workflow/changespec_operations.py` — Accept `status` parameter to allow WIP vs Draft
- `src/sase/amend_workflow.py` — May need adaptation for git/gh propose support
- Any other references to `#commit`, `#amend`, or `#cl` in prompts, docs, or code

### sase.yml shortcut mappings

File: `~/.local/share/chezmoi/home/dot_config/sase/sase.yml`

| Lines   | Shortcut                  | Current value                                   | New value                                   |
| ------- | ------------------------- | ----------------------------------------------- | ------------------------------------------- |
| 86-88   | `a`                       | `#amend(note='{{ note }}')`                     | `#commit(note='{{ note }}')`                |
| 102-104 | `c`                       | `#commit(name={{ name }}, bug_id={{ bug_id }})` | `#cl(name={{ name }}, bug_id={{ bug_id }})` |
| 94-96   | `b`                       | `...#commit({{ cl_name }}, {{ bug_id }})`       | `...#cl({{ cl_name }}, {{ bug_id }})`       |
| 106-114 | `cl` (xprompt definition) | `cl:` with CL context content                   | Rename to `cldd:`                           |
| 131-135 | `launch/beta`             | `...#commit(launch_beta, {{ bug_id }})`         | `...#cl(launch_beta, {{ bug_id }})`         |
| 137-139 | `launch/tests`            | `...#commit(launch_tests, {{ bug_id }})`        | `...#cl(launch_tests, {{ bug_id }})`        |

Also update `#cl` references inside inject steps:

- `xprompts/propose.yml` line 13: inject step references `#cl` → update to `#cldd`
- `xprompts/amend.yml` line 13: inject step references `#cl` → update to `#cldd`

### #propose for git/gh — detailed implementation

The `#propose` workflow currently depends on hg-specific shell commands. Three specific problems need fixing:

**Problem 1: `branch_local_changes` in `propose.yml` check_changes step**

- Location: `xprompts/propose.yml` lines 15-24
- Current: Calls `branch_local_changes` bash function (hg-specific shell command)
- Solution: Replace bash step with a python step that uses the VCS provider:
  ```python
  from sase.vcs_provider import get_vcs_provider
  provider = get_vcs_provider(os.getcwd())
  ok, changes = provider.has_local_changes(os.getcwd())
  ```
- The git provider already implements `has_local_changes()` at `_git.py:358-363` using `git status --porcelain`

**Problem 2: `workspace_name` and `branch_name` shell commands in `sase_propose_workflow`**

- Location: `src/sase/scripts/sase_propose_workflow` lines 16-34
- Current: `_get_project_from_workspace()` calls `subprocess.run(["workspace_name"])` (line 18-19);
  `_get_cl_name_from_branch()` calls `subprocess.run(["branch_name"])` (line 28-29)
- Solution: Replace both with VCS provider method calls:
  ```python
  provider = get_vcs_provider(os.getcwd())
  ok, project_name = provider.get_workspace_name(os.getcwd())
  ok, cl_name = provider.get_branch_name(os.getcwd())
  ```
- The git provider already implements both: `get_workspace_name()` at `_git.py:365-379` and `get_branch_name()` at
  `_git.py:339-347`

**Problem 3: Same `branch_local_changes` fix needed in `amend.yml` and `commit.yml`**

- Location: `xprompts/amend.yml` lines 15-24 and `xprompts/commit.yml` lines 14-23
- Both use the same `branch_local_changes` bash pattern as `propose.yml`
- Apply the same VCS provider fix from Problem 1

**Key insight — no changes needed for `save_diff()` and `clean_workspace()`:**

- `save_diff()` (`src/sase/commit_utils/workspace.py`) already calls `provider.add_remove()` and `provider.diff()`
- `clean_workspace()` (`src/sase/commit_utils/workspace.py`) already calls `provider.clean_workspace()`
- Both automatically work with git via the VCS provider abstraction

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

- Replace `agent_<N>` branch names with random adjective-noun combinations (80×80 = 6,400 unique names) for git/gh
- Decouple branch names from workspace numbers
- Add `n` input (optional int, default null) to all VCS workflows (#git, #gh, #hg)
- Add `release` input (bool, defaults to `true` when `n` is null, `false` when `n` is given)
- Output `workspace_num` from all VCS workflows
- Add "pinned" marker to RUNNING entries when `release=false` to prevent axe cleanup
- Always create ChangeSpec associated with random branch name if agent committed

### Key files to modify

**New module for branch names:**

- Create `src/sase/branch_names.py`:
  - Two curated word lists: **80 adjectives** and **80 nouns** (all 3–7 characters, distinct, pronounceable) → **6,400
    combinations** before any suffix needed
  - `generate_branch_name(workspace_dir: str) -> str`:
    1. Run `git branch -a` to get all existing branch names (local + remote)
    2. Randomly pick `adjective-noun` combinations up to 10 attempts
    3. Return the first combination not already in use
    4. **Fallback**: if all 10 random picks collide, pick a random base name and append `-2`, `-3`, ... until finding an
       unused one
  - `_get_existing_branch_names(workspace_dir: str) -> set[str]` — parses `git branch -a` output, strips
    `remotes/origin/` prefixes, skips `HEAD ->` lines
  - `_add_numeric_suffix(base_name: str, existing: set[str]) -> str` — tries `base-2`, `base-3`, ... starting at 2
    (unsuffixed is logically "1")
  - **No state file needed** — the function is stateless (queries git each time)

**VCS workflow xprompts:**

- `xprompts/git.yml`:
  - Add inputs: `n` (int, default null), `release` (bool, default depends on n)
  - Setup step: if `n` is given, use that workspace number; otherwise auto-claim
  - Prepare step: replace `agent_{{ setup.workspace_num }}` with branch name from `generate_branch_name()`
  - Release step: skip if `release=false`; add `meta_workspace_num` output
  - Pass branch_name to `create_changespec_for_workflow()`
- `xprompts/gh.yml` — Same changes as git.yml
- `xprompts/hg.yml` — Add `n` and `release` inputs (branch naming stays hg-native)

**workspace_changespec.py:**

- Update `create_changespec_for_workflow()` signature: accept explicit `branch_name` parameter instead of deriving
  `f"agent_{workspace_num}"`
- Use branch_name as the ChangeSpec name basis (instead of deriving from commit subjects, since the branch name IS the
  identifier)

**Running field — pinned workspace support:**

- `src/sase/running_field.py`:
  - Add `pinned` flag to workspace claims (e.g., append `| PINNED` to RUNNING entry line)
  - `claim_workspace()`: accept `pinned=False` parameter
  - Stale running cleanup: skip entries marked PINNED even if PID is dead
  - New function `unpin_workspace()` for explicit release

- `src/sase/ace/scheduler/stale_running_cleanup.py`:
  - Lines 30-36 contain the core cleanup loop that iterates `get_claimed_workspaces()` and releases if PID is not
    running. This loop needs a guard: `if claim.pinned: continue` before the `is_process_running` check to prevent
    releasing pinned workspaces.

### Verification

- `just check` passes
- `#git sase` creates a branch like `swift-falcon` instead of `agent_105`
- `#gh bbugyi200/sase` uses random adjective-noun branch names
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
