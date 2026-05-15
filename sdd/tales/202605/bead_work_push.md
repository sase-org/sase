---
create_time: 2026-05-14 21:37:14
status: done
---
# Plan: `git push` after `sase bead work` commit

## Goal

After `sase bead work` successfully commits `sdd/beads/issues.jsonl` (marking a bead/legend as work-launched),
automatically run `git push` so the JSONL state is published to the remote without a manual follow-up step.

## Context

- `sase bead work` finishes by calling `_commit_successful_work_launch` in `src/sase/bead/cli_work.py:474`, which
  delegates to `commit_bead_work_launch` in `src/sase/bead/sync.py:30`.
- `commit_bead_work_launch` directly invokes `git add` + `git commit` via `subprocess` on `repo_root` and returns `True`
  when a commit was created, `False` for benign no-ops (no git repo, no JSONL, no staged delta).
- This commit happens in the user's **main repo** (not the ephemeral `sase_<N>` workspace) — `beads_dir` is the
  persistent `sdd/beads/` path.
- There is currently **no push** anywhere in the bead flow. The only `git push` in the codebase is in the VCS provider
  plugins (used by `sase mail`).
- Tests (`tests/test_bead/test_cli_work_epic.py`, `tests/test_bead/test_sync.py`) cover the commit path. The CLI tests
  monkeypatch `commit_bead_work_launch` directly, so they will not need changes if the push lives inside that function.

## Design

### Where the push lives

Add the push as the **last step inside `commit_bead_work_launch`**, immediately after the successful `git commit` (after
`sync.py:77`). Reasons:

- The function already owns the post-commit boundary and has `repo_root` in scope.
- Existing tests that mock `commit_bead_work_launch` continue to pass without modification.
- Callers don't need to know whether a push happened — `committed=True` will still mean "a new commit was made" and the
  user-facing print in `_commit_successful_work_launch` can be extended to mention push status.

### Failure semantics

The commit succeeded by the time we reach the push. Failing the whole command on a push failure would leave the user
with a committed-but-unmailed bead state and an error exit code, which is worse than the current "commit only" behavior.
Therefore:

- **No remote configured / no upstream branch / push rejected / network failure** → print a clear warning to stderr
  explaining the push failed and how to push manually (`cd <repo_root> && git push`). Return `True` from
  `commit_bead_work_launch` (commit still succeeded).
- **Detached HEAD** → same handling as no-upstream (warn, don't fail).
- **No git repo / no JSONL change** → already returns `False` before we get to the push; nothing to push.

We will **not** raise `BeadWorkLaunchCommitError` for push failures — that exception is reserved for commit-stage
failures where the bead state on disk is out of sync with the user's expectations.

### Detecting "no remote"

Before attempting `git push`, run `git remote` (or `git config --get branch.<current>.remote`). If empty, skip the push
silently (no warning) — matches the existing pattern of "no git repo → benign no-op". A repo with no remote configured
is a legitimate local-only workflow and warning every time would be noise.

### Push command form

Use plain `git push` (no `-u`, no explicit refspec). Rationale:

- The branch typically already tracks an upstream after the first push by the user. Plain `git push` is the
  most-conservative form.
- We do **not** want to silently create an upstream binding the user did not intend. If `git push` fails because no
  upstream is set, the warning will tell the user to run `git push -u origin <branch>` themselves once.

### Config gating

Add a top-level config knob:

```yaml
bead:
  push_after_commit: true
```

Default: `true` (matches the user's stated intent — they want this on). Loaded via the existing `sase.config` mechanism.
`commit_bead_work_launch` takes a new keyword-only parameter `push: bool` so the function stays pure and unit-testable;
`_commit_successful_work_launch` is the only caller and reads the config flag before invoking.

Reasons to gate:

- A future user with a local-only or pre-push-hook-heavy workflow can opt out via their `~/.config/sase/sase.yml`
  without code changes.
- Tests can pass `push=False` to exercise the commit-only path explicitly.

### User-facing output

Extend the existing `print(f"Committed sdd/beads/issues.jsonl for {kind} {bead_id}.")` at `cli_work.py:494` so a
successful push appends `" Pushed to remote."`, and a skipped push (no remote) adds nothing. A failed push prints a
separate warning line to stderr.

## Files to change

1. **`src/sase/bead/sync.py`** — extend `commit_bead_work_launch` to take `push: bool = False` and, when true, run the
   remote-check + `git push`. Return a richer signal — either change the return type to a small `CommitResult` dataclass
   (`committed: bool, pushed: bool | None`) or add a second helper `push_bead_work_launch(repo_root) -> PushOutcome`
   that the caller invokes. **Recommended:** new helper, keep `commit_bead_work_launch`'s signature stable to minimize
   test churn.
2. **`src/sase/bead/cli_work.py`** — in `_commit_successful_work_launch`, after a successful commit, call the new push
   helper if the config flag is true, and emit the appropriate stdout/stderr line.
3. **`src/sase/default_config.yml`** — add the new `bead.push_after_commit` section with a comment explaining what it
   gates.
4. **Config schema/dataclass** — wherever `default_config.yml` is parsed into a typed object (likely
   `src/sase/config/…`), add the new field. To be confirmed during implementation.
5. **`tests/test_bead/test_sync.py`** — add unit tests for the new push helper covering: no-remote skip, successful push
   (against a local bare remote created via `git init --bare`), and push-failure-returns-warning.
6. **`tests/test_bead/test_cli_work_epic.py`** (and legend counterpart) — add one test that verifies the push helper is
   called when the config flag is on and not called when it is off. Existing tests keep monkey- patching
   `commit_bead_work_launch` and remain green.

## Edge cases / open questions

- **Pre-push hooks that take a long time** — `git push` will block the CLI. This is acceptable; the same is true today
  when the user pushes manually.
- **Push prompts for credentials interactively** — `subprocess.run` will inherit stdin/stdout/stderr from the user's
  terminal (we should **not** pass `capture_output=True` for the push step so credential prompts work). This is a
  deliberate departure from the captured-output pattern used for `git add`/`git commit`.
- **Concurrent `sase bead work` runs racing on push** — the second push may fail as non-fast-forward. The
  warning-not-failure semantics handle this gracefully; the user re-runs `git pull --rebase && git push` once.
- **Should the push also run when `commit_bead_work_launch` returns `False` (no new commit)?** No. If there is nothing
  to commit, there is nothing new from this command to push. Avoids surprise pushes of unrelated local commits.

## Out of scope

- Pushing in any other `sase bead` subcommand (e.g. `sase bead close`, `sase bead create`). This plan is narrowly scoped
  to the `work` flow per the user's request.
- Reworking the `git_sync` helper (`sync.py:13`) — separate codepath used for staging without committing; not in the
  bead-work flow.
