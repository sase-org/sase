# Supporting Staged Commits in `/sase_*_commit` Skills

Date: 2026-05-04

## Question

The `/sase_git_commit` and `/sase_hg_commit` skills currently steer agents toward `sase commit -M ... -f ...`, where
`-f` means "stage/include this file" and omitting `-f` means "include everything." How could SASE start allowing a user
or agent to commit only changes that are already staged/preselected?

## Summary

The current system does not support true staged-only commits. For Git, the CLI and skill wording can name files, but the
provider always runs `git add` before committing. With no `-f` values it runs `git add -A`, so unstaged and untracked
work is swept in. With `-f` values it still restages full files, so partially staged hunks are lost.

The right first step is a new explicit commit selection mode, probably `sase commit --staged`, that means:

1. Do not stage user work before dispatch.
2. Validate that the VCS-selected set is non-empty.
3. Capture and record only the selected diff.
4. Still allow SASE-managed metadata such as bead state and plan files to be added intentionally.
5. Update the generated skills so agents can use staged mode when the user has intentionally prepared the commit set.

For Git this maps naturally to the index (`git diff --cached`, `git commit`). For Mercurial/Google, there is no matching
Git-style index in the current provider code, so staged support should either be rejected for hg at first or defined as
"file-limited commit/proposal" after the hg provider learns to honor `payload["files"]`.

## Current Behavior

### CLI contract

`sase commit` exposes a repeated `-f/--file` option with this help text:

```text
File to stage (repeat for multiple; omit to stage all changes)
```

The parser lives in `src/sase/main/parser_commit.py`. `handle_commit_command()` converts those flags into
`payload["files"] = args.files or []` and passes the dict to `CommitWorkflow` (`src/sase/main/cl_handler.py`).

There is no flag that means "use the current staged/index state."

### Git provider behavior

The shared Git dispatch mixin handles both bare Git and GitHub:

- `create_commit`: if `payload["files"]` is non-empty, run `git add -- <files>`; otherwise run `git add -A`.
- `create_pull_request`: create the branch, then use the same `git add -- <files>` or `git add -A` rule.
- The provider validates that something is staged via `git diff --cached --quiet`, then commits.
- Bead directories and extra paths are staged separately after user-file staging.

Relevant code: `src/sase/vcs_provider/plugins/_git_commit_dispatch.py`.

That behavior supports explicit file commits, but not staged-only commits:

- Partially staged hunks are expanded to whole-file commits by `git add -- <file>`.
- A user who staged file A and left file B dirty cannot omit `-f`, because that runs `git add -A` and commits B too.
- A user who staged file A and passes `-f A` still restages all of A, including unstaged hunks.

### Diff tracking makes staged-only a workflow change

`CommitWorkflow.run()` captures the diff before provider dispatch using `capture_pre_commit_diff(provider, cwd, cl_name)`.
For Git, `provider.diff(cwd)` runs `git diff HEAD`, which includes both staged and unstaged tracked edits.

That means a naive provider-only implementation of `--staged` would create the correct Git commit but record the wrong
COMMITS diff whenever unstaged edits remain. The workflow must pass selection mode into diff capture so Git can record
`git diff --cached` for staged-only commits.

### Stop hook and skill contract

The stop hook detects any remaining local changes through `provider.diff_with_untracked()` or `provider.diff()`. That
is appropriate for the normal "finish clean" workflow, but staged-only mode intentionally permits remaining unstaged
work. The generated skill currently tells agents to verify `git status --short --branch` and not declare the commit
finished while the repo is dirty. That instruction would be wrong for staged-only mode.

The skill source is generated from `src/sase/xprompts/skills/sase_git_commit.md` and
`src/sase/xprompts/skills/sase_hg_commit.md`; the live Codex skill under `~/.codex/skills/` should not be hand-edited.

### Mercurial/Google provider behavior

The hg provider in `../sase-google/src/sase_google/plugin.py` currently ignores `payload["files"]` for
`vcs_create_commit()`. It runs `hg update`, derives a one-line note from the message, and calls `sase_google_amend`.

For new CLs (`vcs_create_pull_request()`), it runs `hg addremove`, then `hg commit --name ... --logfile ...`. It also
does not use `payload["files"]`.

So `/sase_hg_commit` has a larger gap than Git:

- There is no Git-like staging index exposed in the current provider contract.
- The documented `-f` option does not appear to constrain the hg amend/new-CL provider paths.
- A staged-only flag should not silently pretend to work for hg until the provider has a real selection mechanism.

## Design Options

### Option A: `--staged` / `--cached` boolean on `sase commit`

Add a CLI flag such as:

```bash
sase commit --staged -M commit_message.md --bead-id sase-42
```

Behavior:

- Parser adds `-S/--staged` or `--cached`. Because short options are expected on SASE CLI subcommands, reserve `-S` if
  available.
- Handler adds `payload["selection_mode"] = "staged"` or `payload["staged"] = True`.
- Reject `--staged` with `-f/--file` in the CLI unless a clear composition is needed later. They represent different
  selection models.
- Git `create_commit` and `create_pull_request` skip user `git add` when staged mode is set, then validate the index.
- Git diff capture uses `git diff --cached` when staged mode is set.
- Generated Git skill documents when to use it and changes verification language for remaining unstaged files.
- Hg provider initially returns a clear unsupported error for staged mode.

Pros:

- Minimal user-facing change.
- Preserves existing `-f` behavior.
- Correctly supports partial hunks for Git.
- Easy for agents to reason about when the user says "commit only what is staged."

Cons:

- Requires plumbing through CLI, workflow, diff capture, provider hooks, tests, and skills.
- Remaining dirty state conflicts with the current stop-hook/skill mental model.
- Hg behavior must be intentionally limited or separately designed.

### Option B: reinterpret omitted `-f` as "use staged if anything is staged"

This would make `sase commit -M msg.md` commit the index when staged changes exist, and fall back to `git add -A`
otherwise.

Pros:

- No new flag.
- Matches some users' intuition from raw `git commit`.

Cons:

- Dangerous behavior change for existing agents, because omitting `-f` currently means "stage all changes."
- Ambiguous when both staged and unstaged edits exist.
- Makes the skill contract harder to teach and test.

This is not recommended.

### Option C: infer staged mode from `git diff --cached`

The provider could detect a non-empty index and skip staging automatically.

Pros:

- No CLI contract change.

Cons:

- Same compatibility problem as Option B.
- Hidden behavior makes agent mistakes harder to diagnose.
- The workflow would still need an explicit selection mode to capture the correct diff.

This is not recommended.

### Option D: file-limited selection only

Keep `-f` as the only selection mechanism and improve docs to say staged hunks are unsupported.

Pros:

- Smallest implementation.
- Works across more providers if hg starts honoring `files`.

Cons:

- Does not solve the user request for staged/partial-hunk Git commits.
- Still requires hg provider work to make current docs true.

This is useful but insufficient.

## Recommended Path

### Phase 1: Add Git staged-only support

Implement Option A for Git only, with a clear unsupported error for hg.

Concrete changes:

- `src/sase/main/parser_commit.py`: add `-S/--staged` with help like "Use already staged/preselected changes; do not
  stage user files."
- `src/sase/main/cl_handler.py`: reject `args.staged and args.files`; include selection mode in the payload.
- `src/sase/workflows/commit/workflow.py`: validate provider support or let provider fail clearly; pass selection mode
  to diff capture.
- `src/sase/workflows/commit/commit_tracking.py`: teach `capture_pre_commit_diff()` to capture the staged diff. The
  cleanest long-term shape is a provider hook like `diff_selected(selection_mode, cwd)`; a smaller first step could use
  `git diff --cached` behind a Git-specific helper if the provider exposes enough identity.
- `src/sase/vcs_provider/plugins/_git_commit_dispatch.py`: when staged mode is set, skip the user `git add` block, keep
  `_stage_bead_dirs()` and `_stage_extra_paths()`, validate staged changes, then commit normally.
- `src/sase/xprompts/skills/sase_git_commit.md`: document `--staged`, including partial-hunk and remaining-dirty-state
  semantics.
- Tests in `tests/test_vcs_provider_bare_git_plugin.py`, `../sase-github/tests/test_github_plugin.py`, commit CLI tests,
  and workflow/diff-capture tests.

Important detail: SASE-managed metadata should remain separate from user staged work. If `--bead-id` or `SASE_PLAN`
causes bead/plan file changes, the workflow may still stage those files in staged mode. The skill should say that
`--staged` controls user work, not SASE bookkeeping.

### Phase 2: Decide the hg semantics

Do not update `/sase_hg_commit` to claim staged support until the provider can honor the same concept. The likely hg
options are:

- Leave `--staged` unsupported with a specific error such as "staged selection is only supported by Git providers."
- Add file-limited hg support first by honoring `payload["files"]` in `vcs_create_commit()` and
  `vcs_create_pull_request()`, then document that hg supports explicit file inclusion, not Git-style staged hunks.
- If Google hg has an internal preselection/shelving mechanism equivalent to an index, expose it as a provider-specific
  implementation of the same `selection_mode = "staged"` contract.

### Phase 3: Relax completion verification for staged mode

Update generated skills and possibly the stop hook language:

- Normal mode: keep requiring a clean working tree and pushed branch.
- Staged mode: verify no staged changes remain (`git diff --cached --quiet`) and the branch is pushed when applicable;
  remaining unstaged/untracked files are allowed but should be reported as intentionally left uncommitted.

The stop hook may still warn on remaining changes after the commit. That is acceptable if the warning is explicit, but
the better UX is for the staged-mode skill to finish by saying what remains dirty and why it was not included.

## Open Questions

- Should the flag be named `--staged`, `--cached`, or `--index`? `--staged` is clearer for users; `--cached` mirrors
  Git's plumbing vocabulary.
- Should `create_proposal --staged` be supported? It is riskier because proposal currently saves a diff and cleans the
  workspace. A staged-only proposal must not delete unrelated unstaged work.
- Should `--staged` be allowed with `--bead-id` when bead notes are amended into the commit? Probably yes, but the docs
  should say SASE bookkeeping may be included.
- Should the provider interface grow a general `selection_mode` enum instead of another boolean? An enum is cleaner if
  we expect future modes like `files`, `staged`, `all`, and maybe `patch`.

## Bottom Line

Start with explicit `--staged` support for Git. Do not try to solve it only in the skill text: the CLI, provider, and
diff tracking layer all need to understand the selection mode. Treat hg as unsupported or file-limited until the
Mercurial provider has a real preselection mechanism.
