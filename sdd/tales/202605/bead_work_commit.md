---
create_time: 2026-05-12 21:58:39
status: done
prompt: sdd/prompts/202605/bead_work_commit.md
---
# Plan: Commit bead launch state after `sase bead work`

## Goal

Make live `sase bead work` launches persist the bead-state mutation they already perform by staging
`sdd/beads/issues.jsonl` and creating a git commit after the agents have launched successfully.

The relevant mutation is:

- epic work: mark the epic ready and preclaim phase beads as `in_progress` with agent-name assignees
- legend work: mark the legend ready before launching epic-planning agents

Dry runs, aborted confirmations, collision failures, plan validation failures, preclaim failures, and launch failures
must continue to avoid committing anything.

## Current Behavior

`src/sase/bead/cli_work.py` owns the `sase bead work` live-launch flow.

For epic beads it:

1. builds and renders the phase/land multi-prompt
2. confirms launch unless `--yes`
3. marks the epic `is_ready_to_work`
4. preclaims phase beads
5. launches agents through `sase.agent.launcher.launch_agent_from_cwd`
6. rolls bead changes back if the launch raises

For legend beads it follows the same shape, except it marks the legend ready and launches epic-planning plus land
agents.

The bead store is JSONL-backed through the Rust facade. Those mutations update `sdd/beads/issues.jsonl`. Existing
`src/sase/bead/sync.py::git_sync` stages that JSONL file but intentionally does not commit. Existing VCS commit helpers
stage bead directories as part of unrelated commit workflows, but using those helpers here would be too broad because
`sase bead work` needs a narrow, local metadata commit after launch.

## Design

Add a small bead-specific git helper that commits exactly the JSONL file for the active bead store:

- resolve the containing git root using the existing `_find_git_root`
- compute the pathspec for `beads_dir / "issues.jsonl"` relative to that root
- stage only that file with `git add -- <relative-jsonl>`
- check whether that path has staged changes
- commit only that path with a concise message

The helper should not stage or commit unrelated files. It should also avoid accidentally consuming a user’s pre-existing
index entries by using a path-limited commit path rather than a plain `git commit` over the whole index.

Suggested API:

```python
def commit_bead_work_launch(beads_dir: Path, bead_id: str, title: str, *, kind: str) -> bool:
    ...
```

Return `False` for benign no-op cases such as not being in a git repo, missing `issues.jsonl`, or no staged JSONL
change. Raise or return a structured failure for actual git command failures; the CLI should report those clearly.

Commit messages:

- epic: `chore: mark bead work launched for <epic_id>`
- legend: `chore: mark legend work launched for <legend_id>`

Keep the subject stable and short. The title can stay in CLI output rather than the commit subject to avoid escaping and
length problems.

## CLI Flow Changes

In `_handle_epic_bead_work`:

1. leave dry-run/confirmation/collision behavior unchanged
2. keep existing mutation and rollback behavior before/during launch
3. after `launch_agent_from_cwd` returns successfully, call the new commit helper
4. print launch success as today, plus a short commit/no-op/warning line if useful

In `_handle_legend_bead_work`, do the same after a successful legend launch. This is slightly broader than the phrase
“phase agents,” but it keeps `sase bead work` consistent: every successful live launch that mutates `issues.jsonl`
persists that mutation.

If the post-launch commit fails, do not kill or roll back already-launched agents. Instead, surface a clear error like:

```text
Error: agents launched for epic <id>, but committing sdd/beads/issues.jsonl failed: <reason>
```

and exit non-zero. The important invariant is that launch failure still rolls back bead mutations, while commit failure
does not pretend the already-started agents were not launched.

## Tests

Add focused tests around the helper and the CLI success boundaries.

Helper tests in `tests/test_bead/test_sync.py`:

- commits `sdd/beads/issues.jsonl` in a real temporary git repo
- no-ops outside git
- no-ops when there is no JSONL change
- commits only `sdd/beads/issues.jsonl` and leaves unrelated staged files staged/uncommitted

CLI tests in `tests/test_bead/test_cli_work_epic.py` and `tests/test_bead/test_cli_work_legend.py`:

- epic live launch calls the commit helper after successful launch
- legend live launch calls the commit helper after successful launch
- dry run does not call it
- launch failure does not call it and still rolls back as before
- commit failure after successful launch reports the “agents launched, commit failed” condition

Existing tests already cover prompt rendering, readiness marking, preclaim rollback, stale owner rewrite, and launch
failure rollback; keep those behaviors unchanged.

## Verification

After implementation:

1. run the focused bead tests:

   ```bash
   just test tests/test_bead/test_sync.py tests/test_bead/test_cli_work_epic.py tests/test_bead/test_cli_work_legend.py
   ```

2. because this changes repo code, run the repo-required check:

   ```bash
   just check
   ```

Per workspace memory, run `just install` first if this workspace has not been installed recently.
