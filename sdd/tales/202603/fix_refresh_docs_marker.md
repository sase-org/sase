---
create_time: 2026-03-29 10:28:03
status: done
prompt: sdd/prompts/202603/fix_refresh_docs_marker.md
---

# Fix refresh_docs marker to account for agent-created commits

## Problem

The `refresh_docs` workflow's `update_marker` step (step 3) writes `{{ count_commits.head }}` — the HEAD captured in
step 1 **before** the docs agent runs. When the docs agent (step 2) creates commits that get merged back into the main
repo, those commits land **after** the marker's recorded SHA. On the next run, the commit count is inflated because the
agent's own docs commits from the previous run get counted as "new" commits.

Evidence: the marker is at `96108b3` and the very first commit after it is
`5a39b23 chore: Update docs for recent features ...` — a commit created by the previous `refresh_docs` agent. So the
reported count of 28 should actually be 27.

## Root cause

In `xprompts/refresh_docs.yml`, step 3 uses the template variable `{{ count_commits.head }}` which was captured in step
1 before the agent ran. It should instead capture the current HEAD at the time step 3 executes, which would be after the
agent's commits have been merged.

## Fix

Change step 3 (`update_marker`) to run `git rev-parse HEAD` directly instead of using `{{ count_commits.head }}`. This
way the marker will be set to the HEAD **after** any agent-created commits.

### File changes

**`xprompts/refresh_docs.yml`** — step 3 (`update_marker`):

```yaml
- name: update_marker
  if: "{{ count_commits.count >= threshold }}"
  python: |
    import subprocess
    from pathlib import Path

    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    marker = Path.home() / ".sase" / "projects" / "sase" / "refresh_docs_marker"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(head)
    print("updated=true")
  output: { updated: bool }
```

### Optional: fix the current marker

Update `~/.sase/projects/sase/refresh_docs_marker` to point past the stale docs commit (`5a39b23`) so the currently
running `refresh_docs` agent isn't double-counted on its next run. However, this is moot if the currently running
workflow's step 3 will overwrite it anyway — so this is only needed if we want to correct history retroactively for
debugging purposes.
