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
3. Capture and record only the selected diff (`git diff --cached`, not `git diff HEAD`).
4. Still allow SASE-managed metadata such as bead state and plan files to be added intentionally.
5. Persist the selection mode in the workflow checkpoint so `sase commit --resume` picks the same path after a conflict.
6. Update the generated skills so agents can use staged mode when the user has intentionally prepared the commit set.

For Git this maps naturally to the index (`git diff --cached`, `git commit`). For Mercurial/Google, there is no matching
Git-style index in the current provider code, so staged support should either be rejected for hg at first or defined as
"file-limited commit/proposal" after the hg provider learns to honor `payload["files"]`.

There are also four interactions the first draft glossed over that strongly shape the design: the workflow runs the
configured `precommit_command` (e.g. `just fix`) **before** dispatch and can dirty the user's curated index; the Git
dispatch path **re-stages** bead directories after `_merge_with_master()`; `_post_commit_bead_amend()` runs
`git commit --amend` after the main commit to fold bead notes in; and `create_proposal` does not go through
`vcs_create_commit` at all — it runs `provider.add_remove()` (which `git add -A`s for Git) and then
`provider.clean_workspace()` after saving the diff. Each of these has to be addressed for staged mode to behave
correctly.

## Current Behavior

### Workflow phases (end-to-end)

`CommitWorkflow.run()` in `src/sase/workflows/commit/workflow.py` runs in this order, regardless of provider:

1. Method and payload validation (`message`, `name`-for-PR, etc.).
2. `handle_beads(payload, cwd)` and `handle_sase_plan(payload, cwd)` — skipped for `create_proposal`. `handle_sase_plan`
   writes the plan to disk and sets `payload["_plan_path"]`.
3. `run_precommit(cwd)` — runs `config["precommit_command"]` (e.g. `just fix`) as a shell command. **Aborts the
   commit on non-zero exit and may modify tracked files.**
4. PR-name suffix and parent ChangeSpec resolution (PR-only).
5. `provider = get_vcs_provider(cwd); resolve_cl_name(); resolve_project_file()`.
6. `capture_pre_commit_diff(provider, cwd, cl_name)` — runs `provider.diff(cwd)` (= `git diff HEAD` for Git) and writes
   it to disk for the COMMITS drawer entry. Runs **before** dispatch.
7. `CommitCheckpoint(...)` snapshot saved via `checkpoint_save(cp)` — this is what `sase commit --resume` replays.
8. `dispatch = getattr(provider, self._method); dispatch(payload, cwd)` — provider-specific staging, commit, push.
9. `_run_tracking_steps(cp, result)` — appends the COMMITS drawer entry, refreshes ACE deltas, etc.

Steps 3, 6, and 7 are the ones a `--staged` flag has to consciously alter.

### CLI contract

`sase commit` exposes a repeated `-f/--file` option with this help text:

```text
File to stage (repeat for multiple; omit to stage all changes)
```

The parser lives in `src/sase/main/parser_commit.py`. `handle_commit_command()` converts those flags into
`payload["files"] = args.files or []` and passes the dict to `CommitWorkflow` (`src/sase/main/cl_handler.py`).

Existing short options on `sase commit`: `-m/-M` (message / message-file, mutually exclusive), `-f/--file`, `-n/--name`,
`-b/--bead-id`, `-B/--bug-id`, `-c/--checkout-target`, `-p/--parent`, `-s/--status`, `-t/--type`, `-r/--resume`. **`-S`,
`--staged`, `--cached`, and `--index` are all free.** `-c` is taken, so `--cached` cannot use the natural `-c` short
form.

There is no flag that means "use the current staged/index state."

### Payload schema

The dict passed to `provider.<method>(payload, cwd)` today contains:

- User-set keys: `message`, `files`, `name`, `bead_id`, `bug_id`, `checkout_target`, `parent`, `status`, `type`.
- Workflow-set internal keys: `_plan_path` (from `handle_sase_plan`), `_skip_bead_amend`, `_cl_name`, `_pr_title_prefix`,
  `_pr_body`.

A staged-mode design would add one new key, e.g. `payload["selection_mode"] = "staged"` (preferable to a boolean
because the provider interface plausibly grows `"all" | "files" | "staged"` later).

### Git provider behavior

The shared Git dispatch mixin handles both bare Git and GitHub
(`src/sase/vcs_provider/plugins/_git_commit_dispatch.py`):

- `vcs_create_commit` (lines ~148-195): user-file staging → `_stage_bead_dirs(cwd)` → `_stage_extra_paths(payload, cwd)`
  → `_validate_staged(cwd)` (`git diff --cached --quiet`) → `_merge_with_master(cwd)` → **second**
  `_stage_bead_dirs(cwd)` (because the merge may modify tracked files) → `git commit -m <message>` →
  `_post_commit_bead_amend(payload, cwd)` (unless `payload["_skip_bead_amend"]`) → `_push_with_retry(cwd)`.
- `vcs_create_pull_request`: `git checkout -b <name>` → user-file staging → `_stage_bead_dirs` → `_stage_extra_paths` →
  `_validate_staged` → commit → push. Does **not** run `_merge_with_master` and does **not** clean the working tree.
- `_post_commit_bead_amend(payload, cwd)`: if bead state changed, runs `git add <bead-pathspec>` and
  `git commit --amend --no-edit --quiet`. **This is a second `git add` that staged-only mode must either skip or
  scope tightly to bead pathspecs.**

That behavior supports explicit file commits, but not staged-only commits:

- Partially staged hunks are expanded to whole-file commits by `git add -- <file>`.
- A user who staged file A and left file B dirty cannot omit `-f`, because that runs `git add -A` and commits B too.
- A user who staged file A and passes `-f A` still restages all of A, including unstaged hunks.
- The `_merge_with_master` + re-stage step can pull merge-resolution edits in tracked bead files into the index, so
  staged mode must either skip the merge for staged commits or accept that merge-driven bead deltas are folded in.

### `create_proposal` does not use `vcs_create_commit`

`vcs_create_proposal` in `_git_commit_dispatch.py` (lines ~197-208) goes through a different path: it calls
`save_diff()` (which runs `provider.add_remove()` — for Git this is effectively `git add -A` to surface untracked
files — then `provider.diff()`), writes the diff to a proposal file, and runs `provider.clean_workspace()` to revert
the working tree. Staged-only proposals are therefore a separate problem from staged-only commits: a naive
`--staged` proposal would either still `git add -A` everything (defeating the selection) or wipe the user's unstaged
work via `clean_workspace()`. The first cut should reject `create_proposal --staged` outright.

### Pre-commit command interaction

`run_precommit(cwd)` runs `config["precommit_command"]` (commonly `just fix` or a formatter) **before** dispatch
(workflow.py:111-113, precommit_hooks.py:38-54). It can edit tracked files. In normal mode this is harmless because
dispatch's `git add` step picks the formatted versions up. In staged-only mode, the formatter writes to the working
tree but the index still points at the user's pre-format snapshot, so the commit records un-formatted content while
the working tree is left dirty with format-only deltas. Options:

1. Skip `run_precommit` in staged mode (treat the user's staged set as already-formatted).
2. Run `run_precommit`, then re-stage **only the paths that were already in the index** (`git diff --cached --name-only`
   → `git add --` of those paths). This preserves "format what is being committed" without dragging in unrelated
   unstaged edits.
3. Run `run_precommit` and refuse the commit if it dirties any path in the index, making the user re-curate.

Option 2 is closest to existing behavior; option 3 is safest. The skill text must reflect whichever is chosen.

### Diff tracking makes staged-only a workflow change

`CommitWorkflow.run()` captures the diff before provider dispatch using `capture_pre_commit_diff(provider, cwd, cl_name)`.
For Git, `provider.diff(cwd)` runs `git diff HEAD`, which includes both staged and unstaged tracked edits.

That means a naive provider-only implementation of `--staged` would create the correct Git commit but record the wrong
COMMITS diff whenever unstaged edits remain. The workflow must pass selection mode into diff capture so Git can record
`git diff --cached` for staged-only commits. The cleanest provider-side surface is a new method
`provider.diff_selected(selection_mode, cwd)` (default implementation falls back to `provider.diff(cwd)`); a smaller
first cut can branch inside `capture_pre_commit_diff()` on Git providers.

### Workflow checkpoint

`CommitCheckpoint` (saved at workflow.py:178-189 and replayed by `sase commit --resume`) snapshots the post-mutation
payload. Since the new selection_mode key would live on `payload`, it round-trips automatically — but only if the
selection is set on the payload **before** `checkpoint_save(cp)` runs. A `--staged` flag added in
`handle_commit_command()` satisfies that ordering. The resume path must continue to honor the mode (no implicit
`git add -A` on retry after a conflict).

### Stop hook and skill contract

The stop hook in `src/sase/hooks/sase_commit_stop_hook.py` is a single shared script — runtime is detected from env
vars and the same diff logic runs for Claude, Codex, Gemini, and external provider. It detects remaining local changes through
`provider.diff_with_untracked()` (falling back to `provider.diff()`), extracts the changed file list, and emits a
`block`/`deny` JSON payload to the runtime. There is no awareness of payload selection mode: the hook reads only the
working tree.

This is appropriate for the normal "finish clean" workflow, but staged-only mode intentionally permits remaining
unstaged work. Two viable options:

1. Have the workflow drop a marker file (e.g. `~/.sase/last_commit_staged_only`) that the stop hook reads and treats
   as "remaining unstaged work is intentional, do not block." The marker must be tied to the commit timestamp/CL name
   so it cannot leak across commits.
2. Teach the stop hook to compare the post-commit working tree against the pre-commit index snapshot and only
   complain about changes the staged commit knew about. More precise but heavier.

Option 1 is the smaller change and is consistent with the hook's existing idempotency-marker pattern.

The generated skill currently tells agents to verify `git status --short --branch` and not declare the commit
finished while the repo is dirty. That instruction would be wrong for staged-only mode.

### Skill generation pipeline

Skill source files live at `src/sase/xprompts/skills/sase_git_commit.md` and `src/sase/xprompts/skills/sase_hg_commit.md`.
They are **per-LLM-provider Jinja2 templates**, not per-runtime: the init-skills handler renders each template with
context supplied by the active LLM provider plugin's `llm_skill_template_context()` hook (variables like
`provider_name`, `provider_tool_name`) and writes the result to `~/<provider_subpath>/skills/<skill>/SKILL.md`. Live
deployed skills should not be hand-edited; edits must go to the source template and re-deploy via
`sase init-skills`.

A `--staged` rollout therefore lands in the source template once and shows up in every runtime's deployed skill on
re-init. There is no per-runtime branch to maintain; the AGENTS.md guidance "treat all runtimes uniformly" applies.

### VCS providers in scope

Only two VCS providers are registered via the `sase_vcs` entry-point group: `bare_git` (in this repo, also used by the
`sase-github` plugin which adds GitHub-only behavior on top of the shared Git dispatch mixin) and `hg` (in
`retired Mercurial plugin`). There is no chezmoi/telegram/nvim VCS provider — the chezmoi, telegram, and nvim plugins do not
implement `vcs_create_commit`. So the staged-mode design only has to reason about Git and hg.

### Mercurial/Google provider behavior

The hg provider in `../retired Mercurial plugin/src/retired_mercurial_plugin/plugin.py` currently ignores `payload["files"]` for
`vcs_create_commit()`. It runs `hg update`, derives a one-line note from the message, and calls `retired_mercurial_plugin_amend`.

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

Implement Option A for Git only, with a clear unsupported error for hg, and reject `create_proposal --staged` for now.

Concrete changes:

- `src/sase/main/parser_commit.py`: add `-S/--staged` with help like "Use already staged/preselected changes; do not
  stage user files." `-c` is taken by `--checkout-target`, so `--cached` does not get a short alias.
- `src/sase/main/cl_handler.py`: reject `args.staged and args.files`; reject `args.staged` when the method is
  `create_proposal`; set `payload["selection_mode"] = "staged"`.
- `src/sase/workflows/commit/workflow.py`: pass selection mode through to `capture_pre_commit_diff()`. Decide the
  precommit policy (see `precommit_command` discussion above) and apply it before the diff capture; the chosen policy
  must be reflected in the skill text. Persist `selection_mode` in `CommitCheckpoint` (free, since it lives on the
  payload).
- `src/sase/workflows/commit/commit_tracking.py`: teach `capture_pre_commit_diff()` to capture the staged diff. The
  cleanest long-term shape is a provider hook like `diff_selected(selection_mode, cwd)`; a smaller first step is to
  branch on Git providers and run `git diff --cached`.
- `src/sase/vcs_provider/plugins/_git_commit_dispatch.py`:
  - In `vcs_create_commit`, when staged mode is set, skip the user `git add` block, still run `_stage_bead_dirs()` and
    `_stage_extra_paths()` (SASE bookkeeping is intentionally allowed), validate staged changes, run
    `_merge_with_master()` and the second `_stage_bead_dirs()` only if the user explicitly opts in (otherwise skip
    the merge so unrelated bead-file conflicts don't surface), then commit.
  - Restrict `_post_commit_bead_amend()` so the `git add <bead-pathspec>` only includes bead paths, never `-A`.
  - In `vcs_create_pull_request`, mirror the same staging skip when staged mode is set.
  - Reject `vcs_create_proposal` with selection_mode = "staged" until a separate design exists for it.
- `src/sase/hooks/sase_commit_stop_hook.py`: optionally consult a per-commit marker so a successful staged commit does
  not block on remaining unstaged work. If we don't take that on in Phase 1, document the temporary mismatch.
- `src/sase/xprompts/skills/sase_git_commit.md`: document `--staged`, including partial-hunk and remaining-dirty-state
  semantics, and the precommit-formatter caveat.
- Tests in `tests/test_vcs_provider_bare_git_plugin.py`, `../sase-github/tests/test_github_plugin.py`, the commit CLI
  tests (`tests/test_commit_cli.py`, `tests/test_commit_parsing.py`), workflow/diff-capture tests
  (`tests/test_commit_workflow_dispatch.py`, `tests/test_commit_workflow_checkpoint.py`), and the stop hook
  (`tests/test_commit_stop_hook.py`). Reuse `_commit_workflow_fixtures.py`.

Important detail: SASE-managed metadata should remain separate from user staged work. If `--bead-id` or `SASE_PLAN`
causes bead/plan file changes, the workflow may still stage those files in staged mode. The skill should say that
`--staged` controls user work, not SASE bookkeeping. `_post_commit_bead_amend` already isolates the amend to bead
pathspecs in spirit; the implementation should make that strict (`git add -- <bead-pathspec>` only) so the amend
cannot accidentally pick up unstaged user work.

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
  Git's plumbing vocabulary. `-S` is the obvious short option (free; `-c` is taken).
- Should `create_proposal --staged` be supported? It is riskier because proposal currently calls
  `provider.add_remove()` (Git: effectively `git add -A`) and `provider.clean_workspace()` afterward. A staged-only
  proposal must not delete unrelated unstaged work — Phase 1 should reject it explicitly.
- Should `--staged` be allowed with `--bead-id` when bead notes are amended into the commit? Probably yes, but the docs
  should say SASE bookkeeping may be included, and `_post_commit_bead_amend` should be tightened to only `git add`
  bead pathspecs.
- Should the provider interface grow a general `selection_mode` enum instead of another boolean? An enum is cleaner if
  we expect future modes like `files`, `staged`, `all`, and maybe `patch`.
- What should happen to `_merge_with_master` in staged mode? Skipping the merge keeps the user's curated index intact
  but ships a possibly-stale branch; running it can introduce unstaged hunks via merge resolution. Likely default:
  skip the merge under `--staged` and require the user to rebase/merge manually first.
- How should `run_precommit` interact with staged mode (skip / re-stage-only-indexed-paths / refuse-on-dirty-index)?
  This is a real UX decision and should be settled before the skill text is written.
- Should the stop hook learn about staged mode in Phase 1, or should we accept a transient warning until a follow-up?
  The marker-file approach is small enough to land together.

## Bottom Line

Start with explicit `--staged` support for Git, scoped to `create_commit` and `create_pull_request`. Do not try to
solve it only in the skill text: the CLI, payload schema, workflow (precommit + diff capture + checkpoint), Git
dispatch (user staging skip + merge re-stage + post-commit amend tightening), stop hook, and skill template all have
to understand the selection mode. Reject `--staged` for `create_proposal` and for hg in the first cut; revisit each
once the proposal flow and the hg provider have real preselection semantics.
