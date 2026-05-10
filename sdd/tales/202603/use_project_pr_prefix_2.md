---
status: wip
create_time: 2026-03-29 10:54:46
prompt: sdd/prompts/202603/use_project_pr_prefix_2.md
---

# Plan: `use_project_pr_prefix` Config Field

## Problem

When creating PRs via `sase commit --method create_pull_request`, there's no way to automatically prefix the PR
title/description with the project name. Google users want `[<project>] ` prepended to PR messages so CLs are easily
identifiable by project in code review tools.

## Constraints

- The `[<project>] ` prefix must appear on the PR title (GitHub) or the first line of the CL description (Hg).
- The prefix must NOT appear in the ChangeSpec DESCRIPTION field — not at creation time and not after TUI reword sync.
- The git commit message must stay clean (no prefix) — only the PR/CL-level description gets it.

## Design: `_pr_title_prefix` Payload Field

The workflow computes the prefix and stores it in an internal payload field `_pr_title_prefix`. Each VCS plugin consumes
this field when creating the PR/CL, applying it to the appropriate location. The original `message` payload field stays
clean, so downstream consumers like `_create_changespec` naturally use the unprefixed message.

### Data flow

```
CommitWorkflow.run()
  ├── _apply_project_pr_prefix()  →  sets payload["_pr_title_prefix"] = "[<project>] "
  ├── _append_pr_tags()           →  appends tags to payload["message"]  (no prefix)
  ├── _build_pr_body()            →  sets payload["_pr_body"] from message (no prefix)
  └── dispatch to VCS provider
        ├── GitHub plugin: git commit uses message (no prefix)
        │                  gh pr create --title = _pr_title_prefix + first_line(message)
        └── Hg plugin: hg commit uses _pr_title_prefix + message (local copy only)
                       payload["message"] stays clean

_create_changespec()  →  uses payload["message"]  (no prefix)  ✓
_sync_description_bg() →  strips prefix via strip_project_pr_prefix()  ✓
```

### Why the Hg case needs extra care

In GitHub, the PR title is separate from the commit message — prefix goes on the title only, commit message stays clean.
In Hg, the CL description IS the commit message. The retired Mercurial plugin plugin must prepend the prefix to a **local copy** of
the message for `hg commit`, but the payload's `message` field stays unprefixed. When the TUI reword syncs the
description back (`_sync_description_bg`), the prefix must be stripped since the Hg CL description now contains it.

For git/GitHub, `_sync_description_bg` reads from the git commit message (no prefix), so stripping is a safe no-op.

## Phases

### Phase 1: Config infrastructure

**`src/sase/default_config.yml`** — Add `use_project_pr_prefix: false` under `vcs_provider`.

**`src/sase/vcs_provider/config.py`** — Add:

- `get_use_project_pr_prefix() -> bool` accessor
- `strip_project_pr_prefix(description: str) -> str` helper — if config is enabled, strips a leading `[...] ` from the
  first line using regex `^\[.+?\] `

### Phase 2: Workflow integration

**`src/sase/workflows/commit/workflow.py`** — Add `_apply_project_pr_prefix()` method:

- Reads config via `get_use_project_pr_prefix()`
- If true, gets project name (already resolved as `project_name` in the existing try block at ~line 114)
- Sets `payload["_pr_title_prefix"] = f"[{project_name}] "`
- Called in `run()` before `_append_pr_tags()` inside the existing `if self._method == "create_pull_request":` block at
  line 126

### Phase 3: VCS plugin consumption

**`../sase-github/src/sase_github/plugin.py`** — In `vcs_create_pull_request`, read `_pr_title_prefix` from payload and
prepend to the `--title` argument passed to `gh pr create`.

**`../retired Mercurial plugin/src/retired_mercurial_plugin/plugin.py`** — In `vcs_create_pull_request`, read `_pr_title_prefix` from payload and
prepend to the first line of the **local** `message` variable before writing to the logfile. Do NOT modify the payload
dict.

### Phase 4: Reword sync protection

**`src/sase/ace/handlers/reword.py`** — In `_sync_description_bg`, call `strip_project_pr_prefix()` after
`strip_pr_tags()` to remove the prefix before writing back to the ChangeSpec DESCRIPTION. This handles the Hg case where
the commit message contains the prefix; for git it's a safe no-op.

### Phase 5: retired Mercurial plugin default config

**`../retired Mercurial plugin/src/retired_mercurial_plugin/default_config.yml`** — Add `use_project_pr_prefix: true` under `vcs_provider`.

### Phase 6: Tests

- `strip_project_pr_prefix()`: strips when enabled, no-op when disabled, handles multiline, handles missing prefix
- `get_use_project_pr_prefix()`: reads config correctly
- GitHub plugin: `_pr_title_prefix` prepended to title, body unchanged
- retired Mercurial plugin plugin: `_pr_title_prefix` prepended to first line of local message
- Workflow: `_apply_project_pr_prefix()` sets `_pr_title_prefix` correctly, no-ops when disabled
