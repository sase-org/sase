---
bead_id: sase-cel
---

# Plan: Add `create_changespec` Post-Step to `#gh` and `#git` Workflows

## Context

The `#gh` and `#git` embedded workflows set up git workspaces, run agent prompts, and clean up afterward. But when
invoked with a project shorthand or repo path (not an existing ChangeSpec name), they don't create a ChangeSpec to track
the work. This means agent runs that create PRs or push commits have no corresponding ChangeSpec in the project file.

This change adds a `create_changespec` post-step that automatically creates a ChangeSpec with a meaningful DESCRIPTION
(from git commit messages) and as many other fields as practical (PR URL, HOOKS, initial COMMITS entry with chat/diff).
For git-based projects, the URL field is labeled "PR:" instead of "CL:" in the `.gp` file.

## Files to Modify

| File                                                | Change                                                         |
| --------------------------------------------------- | -------------------------------------------------------------- |
| `src/sase/workspace_changespec.py`                  | **NEW** - shared helper module                                 |
| `xprompts/gh.yml`                                   | Add `create_changespec` step between `create_pr` and `release` |
| `xprompts/git.yml`                                  | Add `create_changespec` step between `inject` and `release`    |
| `src/sase/commit_workflow/changespec_operations.py` | Add `cl_label` param to `add_changespec_to_project_file`       |
| `src/sase/ace/changespec/parser.py`                 | Recognize `PR:` as alias for `CL:`                             |
| `src/sase/ace/display.py`                           | Show "PR:" for git projects                                    |
| `src/sase/ace/tui/widgets/changespec_detail.py`     | Show "PR:" for git projects                                    |
| `src/sase/ace/tui/actions/clipboard.py`             | Show "PR:" for git projects                                    |
| `src/sase/status_state_machine/field_updates.py`    | Handle both `CL:` and `PR:` prefixes                           |

---

## Part 1: "PR:" Field Support

### 1a. Parser — recognize `PR:` (`src/sase/ace/changespec/parser.py:149`)

Add `PR:` as an alternative to `CL:`. Both map to `state.cl`:

```python
    if line.startswith("CL: ") or line.startswith("PR: "):
        state.save_pending_entries()
        state.cl = line.split(": ", 1)[1].strip()
        state.reset_section_flags()
        return True
```

### 1b. Writer — `cl_label` param (`src/sase/commit_workflow/changespec_operations.py:55`)

Add `cl_label: str = "CL"` parameter to `add_changespec_to_project_file`. Use it on line 193:

```python
cl_line = f"{cl_label}: {cl_url}\n" if cl_url else ""
```

### 1c. Display — VCS-aware label

Add a helper function (e.g. in `src/sase/gh_workspace.py` or a small util):

```python
def get_cl_field_label(project_file: str) -> str:
    """Return 'PR' for git projects, 'CL' for hg projects."""
    return "PR" if detect_vcs_type_for_project(project_file) == "git" else "CL"
```

Update these four display locations to use it:

- **`src/sase/ace/display.py:106-108`**: `text.append(f"{label}: ", ...)` where
  `label = get_cl_field_label(changespec.file_path)`
- **`src/sase/ace/tui/widgets/changespec_detail.py:336-339`**: same pattern
- **`src/sase/ace/tui/actions/clipboard.py:472-473`**: `lines.append(f"{label}: {cs.cl}")`
- **`src/sase/ace/tui/modals/command_history_modal.py:252`**: Leave as-is (this displays a CL _name_, not a URL — it's
  not the same field)

### 1d. Field updates — handle both prefixes (`src/sase/status_state_machine/field_updates.py:69`)

Change `line.startswith("CL:")` to `line.startswith(("CL:", "PR:"))` so updates to the CL/PR field work regardless of
which label the file uses. When inserting a new line (line 78), use `get_cl_field_label` to pick the right label.

---

## Part 2: New Module `src/sase/workspace_changespec.py`

Shared helper module used by both `#gh` and `#git` workflow post-steps.

### `_get_commits_ahead(checkout_target, branch_name) -> list[str]`

- Runs `git log --format=%s {checkout_target}..{branch_name}`
- Returns commit subjects oldest-first (reversed from git output)

### `_derive_cl_name(project_name, commit_subjects) -> str`

- Takes first commit subject, strips conventional-commit prefixes (`feat:`, `fix:`, etc.)
- Converts to snake_case (lowercase, non-alphanum → underscore), truncates to 50 chars
- Prefixes with `{project_name}_`
- Fallback: `{project_name}_agent_changes`

### `_build_description(commit_subjects) -> str`

- Single commit → its subject line
- Multiple commits → numbered list (`1. Subject\n2. Subject\n...`)
- No commits → `"Agent changes"`

### `_save_committed_diff(cl_name, checkout_target, branch_name, timestamp) -> str | None`

- Runs `git diff {checkout_target}...{branch_name}` to capture committed changes
- Saves to `~/.sase/diffs/{safe_name}-{timestamp}.diff`
- Returns path with `~` prefix, or None if no diff
- Note: can't use existing `save_diff()` since that captures _uncommitted_ changes

### `create_changespec_for_workflow(...) -> str | None`

Arguments: `project_name`, `project_file`, `checkout_target`, `workspace_num`, `prompt`, `response`, `workflow_name`,
`cl_url=None`

Logic:

1. Get commits ahead via `_get_commits_ahead(checkout_target, f"agent_{workspace_num}")`
2. Return None if no commits
3. Derive name via `_derive_cl_name`
4. Build description via `_build_description`
5. Save chat history via `save_chat_history(prompt, response, workflow_name, timestamp=ts)` → chat_path
6. Save diff via `_save_committed_diff` → diff_path
7. Get hooks via `get_initial_hooks_for_changespec(verbose=False)`
8. Call
   `add_changespec_to_project_file(project, cl_name, description, parent=None, cl_url, initial_hooks, initial_commits=[(1, "[run] Initial Commit", chat_path, diff_path)], cl_label="PR")`
9. Return suffixed name

Reused functions:

- `save_chat_history` from `sase.chat_history`
- `add_changespec_to_project_file` from `sase.commit_workflow.changespec_operations`
- `get_initial_hooks_for_changespec` from `sase.workflow_utils`
- `generate_timestamp`, `ensure_sase_directory`, `make_safe_filename` from `sase.sase_utils`

---

## Part 3: Workflow YAML Changes

### `xprompts/gh.yml` — new step after `create_pr` (line 138), before `release` (line 140)

```yaml
- name: create_changespec
  if: "{{ setup.should_create_branch }}"
  hidden: true
  python: |
    from sase.workspace_changespec import create_changespec_for_workflow

    pr_url = {{ create_pr.pr_url | tojson }}
    cl_url = pr_url if pr_url.startswith("http") else None

    try:
        result = create_changespec_for_workflow(
            project_name={{ setup.project_name | tojson }},
            project_file={{ setup.project_file | tojson }},
            checkout_target={{ setup.checkout_target | tojson }},
            workspace_num={{ setup.workspace_num }},
            prompt={{ _prompt | tojson }},
            response={{ _response | tojson }},
            workflow_name="gh",
            cl_url=cl_url,
        )
    except Exception:
        result = None

    if result:
        print(f"changespec_name={result}")
        print(f"meta_changespec={result}")
    else:
        print("changespec_name=")
  output: { changespec_name: word }
```

### `xprompts/git.yml` — new step after `inject` (line 100), before `release` (line 102)

```yaml
- name: create_changespec
  if: "{{ setup.should_create_branch }}"
  hidden: true
  python: |
    from sase.workspace_changespec import create_changespec_for_workflow

    try:
        result = create_changespec_for_workflow(
            project_name={{ setup.project_name | tojson }},
            project_file={{ setup.project_file | tojson }},
            checkout_target={{ setup.checkout_target | tojson }},
            workspace_num={{ setup.workspace_num }},
            prompt={{ _prompt | tojson }},
            response={{ _response | tojson }},
            workflow_name="git",
        )
    except Exception:
        result = None

    if result:
        print(f"changespec_name={result}")
        print(f"meta_changespec={result}")
    else:
        print("changespec_name=")
  output: { changespec_name: word }
```

---

## ChangeSpec Fields Populated

| Field       | Value                                                                      |
| ----------- | -------------------------------------------------------------------------- |
| NAME        | Derived from first commit message, snake_cased, prefixed with project name |
| DESCRIPTION | Git commit subjects (single line or numbered list)                         |
| PARENT      | None (branching from default branch)                                       |
| PR          | PR URL for `#gh`, omitted for `#git` (written as `PR:` in `.gp` file)      |
| STATUS      | "WIP" (default)                                                            |
| HOOKS       | From `get_initial_hooks_for_changespec()`                                  |
| COMMITS     | `(1) [run] Initial Commit` with CHAT and DIFF paths                        |
| BUG         | Omitted (not available)                                                    |

## Key Design Points

- **Condition gating**: `if: "{{ setup.should_create_branch }}"` skips the step when an existing ChangeSpec name was
  passed
- **No-commits guard**: `create_changespec_for_workflow` returns None if no commits ahead of base
- **Error resilience**: Wrapped in try/except so failures don't prevent `release` step from running
- **`meta_changespec` output**: Updates the TUI Agents tab to show the new ChangeSpec name
- **`hidden: true`**: Infrastructure step, not shown in default TUI view
- **PR field label**: Git projects use `PR:` in `.gp` files; parser accepts both `CL:` and `PR:`; display uses VCS-aware
  label via `get_cl_field_label()`

## Verification

1. `just check` — run linting and tests
2. Manual test with `#gh(bbugyi200/sase)`:
   - ChangeSpec appears in `~/.sase/projects/sase/sase.gp`
   - Field says `PR: https://github.com/...` (not `CL:`)
   - NAME is snake_cased from first commit subject
   - DESCRIPTION contains commit messages
   - COMMITS has `(1) [run] Initial Commit` with CHAT/DIFF
   - HOOKS populated
3. Manual test with `#gh(existing_changespec_name)` — verify no new ChangeSpec created
4. Verify `sase ace` display shows "PR:" for git projects, "CL:" for hg projects
5. Verify existing `.gp` files with `CL:` still parse correctly
