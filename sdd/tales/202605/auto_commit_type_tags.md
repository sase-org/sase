---
create_time: 2026-05-24 13:41:33
status: done
prompt: sdd/prompts/202605/auto_commit_type_tags.md
---
# Plan: Auto-Commit TYPE Tags

## Goal

Add a `TYPE=<auto_commit_type>` trailing commit-message tag to commits that SASE creates automatically. This should not
tag ordinary agent commits made through the normal `/sase_git_commit` / `sase commit` workflow.

The tag should be applied only where SASE owns the generated commit message. The value should be short, lowercase, and
stable enough for later analytics/filtering.

## Existing Context

The current runtime provenance tag layer lives in `src/sase/workflows/commit/runtime_tags.py`:

- `update_trailing_commit_tags()` already provides idempotent trailing `KEY=VALUE` tag updates.
- `apply_runtime_commit_tags()` adds `AGENT` and `MACHINE` for real `create_commit` and `create_pull_request` workflow
  commits.
- `create_proposal` is intentionally excluded because it does not create a real VCS commit.
- `RUNTIME_COMMIT_TAG_KEYS` currently owns only `AGENT` and `MACHINE`; `TYPE` should not be added to that set, because
  normal agent commits should not have configured or user-authored `TYPE` tags stripped just because they pass through
  `CommitWorkflow`.

The dynamic generated-skills memory says skill files are generated and `sase commit` CLI changes require skill/test
synchronization. This change should not add a new CLI argument or edit generated skill files.

## Tag Values

Use these initial short values:

- `TYPE=sdd` for generated SDD prompt/plan commits.
- `TYPE=beads` for bead store initialization commits.
- `TYPE=bead_work` for the bead metadata commit made after `sase bead work` launches agents.
- `TYPE=memory` for `sase init memory` project and chezmoi deployment commits.
- `TYPE=skills` for `sase init skills` generated-skill deployment commits.
- `TYPE=init` for consolidated `sase init` chezmoi deployment and bare-git project bootstrap commits.
- `TYPE=xprompt` for the TUI xprompt browser's generated commit after the user confirms the offered commit/push.

Do not add `TYPE` to:

- Normal agent commits through `sase commit`, except when an internal auto-commit caller explicitly puts `TYPE` into the
  generated message it passes to `sase commit`.
- `create_proposal`, because it creates a proposal diff, not a VCS commit.
- Low-level provider `commit()`, `amend()`, `reword()`, and `reword_add_tag()` APIs by default; those APIs are generic
  VCS primitives and should not infer auto-commit semantics.
- Post-commit bead `--amend --no-edit` operations, because they amend the same commit without changing its message.

## Implementation

1. Add an auto-commit tag helper in `src/sase/workflows/commit/runtime_tags.py`.
   - Keep `RUNTIME_COMMIT_TAG_KEYS = {"AGENT", "MACHINE"}` unchanged.
   - Add a helper such as `apply_auto_commit_type_tag(message: str, auto_commit_type: str) -> str`.
   - Implement it through `update_trailing_commit_tags(message, {"TYPE": auto_commit_type}, remove_keys={"TYPE"})`.
   - Reuse the existing sanitizer so empty or multiline values are handled consistently.
   - Add unit tests proving it adds `TYPE`, replaces a stale trailing `TYPE`, preserves other tags, and composes with
     `AGENT` / `MACHINE` without making `TYPE` globally runtime-owned.

2. Tag auto-commit callers that invoke `sase commit`.
   - In `src/sase/axe/run_agent_exec_plan_sdd.py`, tag the temporary message file created by
     `commit_sdd_files_for_exec_plan()` with `TYPE=sdd`.
   - Preserve the current `-M` flow; the normal commit workflow will still add `AGENT` and `MACHINE` later when running
     inside an agent context.
   - Update `tests/test_sdd_commit.py` expectations for the temp message content.

3. Tag direct internal `git commit` callers.
   - In `src/sase/sdd/files.py`, add an optional `auto_commit_type: str = "sdd"` argument to `commit_sdd_files()` and
     tag the message before `git commit -m`.
   - In `src/sase/sdd/beads.py` and `src/sase/bead/cli_common.py`, pass `auto_commit_type="beads"` for bead-store
     initialization.
   - In `src/sase/bead/sync.py`, tag the work-launch metadata commit with `TYPE=bead_work`.
   - In `src/sase/main/init_memory_handler.py`, tag the project-repo commit in `_deploy_to_project_repo()` with
     `TYPE=memory`.
   - In `src/sase/workspace_provider/plugins/bare_git_init.py`, tag the generated initial commit with `TYPE=init`.
   - In `src/sase/ace/tui/modals/xprompt_browser_actions.py`, tag the generated xprompt commit with `TYPE=xprompt`.

4. Tag shared chezmoi auto-deploy commits.
   - Extend `ChezmoiDeployBehavior` in `src/sase/main/_init_chezmoi_deploy.py` with
     `auto_commit_type: str | None = None`.
   - Apply the helper inside `deploy_to_chezmoi()` when building the message for `git commit -m`.
   - Set `auto_commit_type="init"` in `deploy_deferred_chezmoi()`.
   - Set `auto_commit_type="skills"` in `src/sase/main/init_skills_handler.py`.
   - Set `auto_commit_type="memory"` in the chezmoi path in `src/sase/main/init_memory_handler.py`.

5. Audit but avoid broad provider-level tagging.
   - Leave `GitCommitDispatchMixin.vcs_create_commit()` and `vcs_create_pull_request()` alone; those are the normal
     `sase commit` provider paths and already receive only runtime provenance tags.
   - Leave `GitCoreOpsMixin.vcs_commit()` and `vcs_amend()` alone; call sites with generated messages should tag before
     invoking provider primitives if needed.
   - Review `src/sase/ace/restore.py` separately during implementation. It currently shells out to `sase commit` as part
     of restore behavior, but it does not construct a generated commit message in the code path inspected here. If the
     active restore behavior needs a generated message, tag that message with `TYPE=restore`; otherwise do not change
     restore in this first pass.

## Tests

Add or update focused tests:

- `tests/test_commit_runtime_tags.py`
  - Helper adds/replaces `TYPE`.
  - `TYPE` is not part of `RUNTIME_COMMIT_TAG_KEYS`.

- `tests/test_sdd_commit.py`
  - Direct `.sase/sdd` git commit body includes `TYPE=sdd`.
  - The version-controlled SDD temp message passed to `sase commit -M` includes `TYPE=sdd`.

- `tests/test_bead/test_sync.py`
  - Work-launch commit body includes `TYPE=bead_work` while preserving the subject and file selection behavior.

- `tests/main/test_init_memory_commit.py`
  - Project memory commit command uses a message body with `TYPE=memory`.

- `tests/main/test_init_skills_deploy.py`
  - Shared chezmoi deploy commit message includes the caller-provided `TYPE`, including provider-filtered skills
    commits.

- `tests/test_bare_git_workspace.py`
  - Bare-git project bootstrap commit body includes `TYPE=init`.

- Add a narrow unit test for `ChezmoiDeployBehavior(auto_commit_type=...)` if the existing deploy tests do not cover the
  shared helper directly enough.

## Verification

Before implementation testing, run `just install` for this workspace.

Focused verification:

```bash
just install
.venv/bin/pytest tests/test_commit_runtime_tags.py tests/test_sdd_commit.py tests/test_bead/test_sync.py \
  tests/main/test_init_memory_commit.py tests/main/test_init_skills_deploy.py tests/test_bare_git_workspace.py
```

Final verification after code changes:

```bash
just check
```

## Risks

- Some tests currently inspect only commit subjects. Commit-message tags live in the body, so tests should use
  `git log -1 --format=%B` or inspect the exact `-m` argument rather than relying on `--oneline`.
- Adding `TYPE` inside the normal `CommitWorkflow` unconditionally would tag normal agent commits, which is explicitly
  out of scope. Keep tagging at auto-commit message construction sites.
- Adding `TYPE` to `RUNTIME_COMMIT_TAG_KEYS` would cause normal PR/commit tag filtering to strip user/config `TYPE`
  values. Keep ownership separate.
- Direct `git commit -m` accepts multiline messages, but mocked subprocess tests may need exact-message updates.
