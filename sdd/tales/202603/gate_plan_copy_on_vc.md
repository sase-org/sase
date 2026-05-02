---
create_time: 2026-03-27 15:51:52
status: done
prompt: sdd/prompts/202603/gate_plan_copy_on_vc.md
---

# Plan: Gate plan-file copy-into-repo on `sdd.version_controlled`

## Problem

The recent fix in commit `476e4bd` ("Copy plan file into repo when missing or outside repo during commit") added
fallback logic to `_handle_sase_plan()` in `CommitWorkflow` that:

1. Falls back to `~/.sase/plans/` archive when the plan file is missing at the expected path
2. Copies the plan file into `{cwd}/plans/` if it's outside the repo
3. Adds frontmatter if missing
4. Records `_plan_path` so the VCS provider stages the file

This logic runs unconditionally for all projects. But it should **only** apply when `sdd.version_controlled` is `true`
(where SDD files live at `plans/` and `specs/` in the project root). When `version_controlled` is `false` (the default),
SDD files live in `.sase/sdd/` with their own local git repo, and should NOT be copied into the project's `plans/`
directory.

### Impact

For any project with `sdd.version_controlled: false` (the default), the commit workflow incorrectly:

- Creates a `plans/` directory at the project root
- Copies plan files there
- Stages them for commit to the main project repo
- These files should not exist in the project repo at all

## Changes

### 1. `src/sase/workflows/commit/workflow.py` — `_handle_sase_plan()`

Read `sdd.version_controlled` from config and gate the copy-into-repo block on it:

```python
def _handle_sase_plan(self, cwd: str) -> None:
    plan_path = os.environ.get("SASE_PLAN", "")
    if not plan_path:
        return

    from sase.sdd.beads import get_sdd_config
    version_controlled = get_sdd_config()

    repo_root = self._get_repo_root(cwd)
    in_repo = bool(repo_root) and plan_path.startswith(repo_root + "/")

    # If plan file doesn't exist at the expected path, try the ~/.sase/plans/ archive
    if not os.path.isfile(plan_path):
        archive_fallback = os.path.join(
            os.path.expanduser("~"), ".sase", "plans", os.path.basename(plan_path)
        )
        if os.path.isfile(archive_fallback):
            plan_path = archive_fallback
            in_repo = False
        else:
            return  # truly missing

    # Only copy plan into repo for version-controlled SDD projects
    if version_controlled and not in_repo:
        dest = os.path.join(cwd, "plans", os.path.basename(plan_path))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(plan_path, dest)
        plan_path = dest

    # Only add frontmatter for version-controlled plans
    if version_controlled:
        plan_content = open(plan_path, encoding="utf-8").read()
        if not plan_content.startswith("---\n"):
            from sase.llm_provider._plan_utils import add_create_time_frontmatter
            with open(plan_path, "w", encoding="utf-8") as f:
                f.write(add_create_time_frontmatter(plan_content))

    # Compute repo-root-relative path
    if repo_root and plan_path.startswith(repo_root + "/"):
        plan_rel = plan_path[len(repo_root) + 1:]
    else:
        plan_rel = (
            os.path.relpath(plan_path, repo_root)
            if repo_root
            else os.path.basename(plan_path)
        )

    # Append PLAN= to commit message
    message = self._payload.get("message", "")
    self._payload["message"] = f"{message}\n\nPLAN={plan_rel}"

    # Mark plan as done
    subprocess.run(
        ["sed", "-i", "s/^status: wip$/status: done/", plan_path],
        check=False,
        capture_output=True,
    )

    # Only stage plan file if version-controlled and in-repo
    if version_controlled:
        self._payload["_plan_path"] = plan_path
```

Key behavioral changes:

- **`version_controlled: true`**: Same as current behavior (copy into repo, add frontmatter, stage file)
- **`version_controlled: false`**: Skip copy, skip frontmatter modification, skip staging. Still append `PLAN=` to
  commit message (with the external path) and mark plan as done.

### 2. `tests/test_commit_workflow.py` — Add `TestHandleSasePlan` class

Add test cases for `_handle_sase_plan()` that verify:

- **`version_controlled: true`**: Plan file is copied into `plans/` and `_plan_path` is set
- **`version_controlled: false`**: Plan file is NOT copied into `plans/`, no `_plan_path` set, `PLAN=` still appended to
  commit message
- **Archive fallback + `version_controlled: true`**: Falls back to archive and copies into repo
- **Archive fallback + `version_controlled: false`**: Falls back to archive but does NOT copy into repo

## Testing

```bash
just check
```
