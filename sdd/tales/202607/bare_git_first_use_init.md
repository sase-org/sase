---
create_time: 2026-07-06 11:45:46
status: done
prompt: sdd/prompts/202607/bare_git_first_use_init.md
---
# Fix: bare-git project first-use initialization fails on leftover on-disk state

## Problem

Launching an agent with `#git:home` fails (twice — retries fail identically) with:

```
RuntimeError: Command '['git', 'clone', '/home/bryan/.sase/repos/home.git',
'/home/bryan/projects/git/home/']' returned non-zero exit status 128.
```

(See `~/.sase/logs/launch_failures.log`, entries at 2026-07-06 11:38:40 and 11:39:13 EDT.)

## Root cause (diagnosed and verified)

Resolution chain: `#git:home` → `BareGitWorkspacePlugin.ws_resolve_ref` → `resolve_git_ref("home")`
(`src/sase/workspace_provider/plugins/bare_git_ref.py`). No project spec exists at `~/.sase/projects/home/home.sase` and
no ChangeSpec matches, so Mode 3 ("missing project shorthand") first-use auto-init runs: `_init_missing_project_ref` →
`init_bare_git_project("home")` (`src/sase/workspace_provider/plugins/bare_git_init.py`).

`init_bare_git_project` assumes a completely clean slate:

1. `git init --bare ~/.sase/repos/home.git` — **succeeds** (creates a fresh, empty bare repo).
2. `git clone ~/.sase/repos/home.git ~/projects/git/home/` — **fails with exit 128**:
   `fatal: destination path '/home/bryan/projects/git/home' already exists and is not an empty directory.` (verified by
   re-running the exact command; `safe.bareRepository` is ruled out — it is unset, and cloning the same bare repo into a
   fresh directory works).

The machine has surviving state from a previous life of the `home` project: `~/projects/git/home` is a healthy working
clone with real commit history whose `origin` already points at `~/.sase/repos/home.git`, plus numbered workspace clones
(`home_0`, `home_10`, ...). Meanwhile the sase-side state (`~/.sase/repos/home.git`, `~/.sase/projects/home/`) was lost.
First use then attempted a from-scratch init and crashed into the surviving clone. This will bite **any** bare-git
project whose working clone exists while its `~/.sase` state is missing — and, because the failed attempt leaves a fresh
_empty_ bare repo behind, retries keep failing (init is not idempotent).

Secondary defect — error opacity: every git call in `bare_git_init.py` uses `capture_output=True, check=True`, so git's
stderr (which states the exact reason) is swallowed. The launch-failure log only shows "returned non-zero exit status
128", which made this needlessly hard to diagnose.

## Fix design

### 1. Make `init_bare_git_project` adoption-aware and idempotent

In the `existing_bare is None` path, assess on-disk state before acting:

- **bare state**: missing · exists-empty (valid bare repo, no refs) · exists-with-commits · exists-but-not-a-bare-repo
  (conflict)
- **clone state**: missing-or-empty-dir · git repo with `origin` == bare_dir · git repo with a different `origin`
  (conflict) · non-git non-empty dir (conflict)

Decision table:

| clone dir                | bare repo     | action                                                                                                                                                                                                       |
| ------------------------ | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| missing/empty            | missing/empty | Fresh init — current behavior, unchanged                                                                                                                                                                     |
| missing/empty            | has commits   | Reuse the existing `existing_bare` flow: clone from it + `ensure_bare_git_sdd_initialized` (no spurious empty "Initial commit")                                                                              |
| git repo, origin matches | missing/empty | **Rebuild**: create bare repo if missing, `git push origin --all` (+ `--tags`) from the clone, point the bare's `HEAD` at the clone's current branch, write project spec. Never touches the clone's history. |
| git repo, origin matches | has commits   | **Adopt**: nothing to create — just write the project spec file                                                                                                                                              |
| any conflict state       | —             | Raise `RuntimeError` with a clear, actionable message: what exists, what was expected, and how to resolve (e.g. move the directory aside or pass an explicit path)                                           |

The empty-bare cases are what make retries (and the current machine state, where the failed attempts already created an
empty `~/.sase/repos/home.git`) self-heal: re-running `#git:home` after the fix rebuilds the bare repo from the
surviving clone and writes the project spec, with no manual cleanup.

### 2. Surface git stderr in errors

Add a small `_run_git(...)` helper in `bare_git_init.py` that raises `RuntimeError` including the command and git's
stderr on failure, and use it for all git invocations in that module. Future launch-failure log entries then show the
actual reason instead of a bare exit status.

### 3. Same-class gap in Mode 4 (`#git(<path>)` bare-repo-path refs) — secondary

`resolve_git_ref` Mode 4 writes the project spec (BARE_REPO_DIR/WORKSPACE_DIR) but never creates the working clone when
it's missing, so first use of a path ref fails obscurely later (e.g. in `ensure_bare_git_sdd_initialized` /
`ensure_workspace_checkout`). Route Mode 4 through the same init/adoption logic
(`init_bare_git_project(name, existing_bare=path)` when the clone dir is missing; adopt when it exists with matching
origin) so all bare-git first-use paths behave uniformly.

## Scope note (Rust core boundary)

Bare-git init/adoption is implemented only in this repo's Python workspace-provider plugin (verified: no parallel logic
in `sase-core`), so the fix stays in this repo.

## Tests

Extend `tests/test_bare_git_init.py` (real git in tmp dirs, matching the existing end-to-end style):

- Clone with history + matching origin, bare **missing** → init succeeds, bare repo rebuilt with the clone's commits
  (all branches), project spec written.
- Same, but bare **exists empty** (exact post-failed-attempt state) → same result, proving retry idempotence.
- Clone with matching origin + bare **has commits** → adopt: project spec written, no new commits created anywhere.
- Bare has commits, clone missing → clone created from bare, no spurious empty "Initial commit".
- Conflict cases (non-git non-empty clone dir; clone origin pointing elsewhere; bare path that isn't a bare repo) →
  `RuntimeError` with actionable message.
- Failed git commands produce errors containing git's stderr.
- Mode 4: path ref with missing clone dir → clone materialized and spec written.

## Validation

- `just install`, then `just check`.
- If the sandbox kills the full test phase, fall back to targeted runs:
  `pytest tests/test_bare_git_init.py tests/test_bare_git_workspace.py`.
- Manual heal verification on this machine: re-run a `#git:home` launch; confirm `~/.sase/repos/home.git` now contains
  the clone's history, the project spec exists at `~/.sase/projects/home/`, and the launch proceeds past `launch_task`.
