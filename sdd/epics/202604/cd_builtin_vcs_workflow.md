---
create_time: 2026-04-30 18:17:40
status: done
bead_id: sase-1m
prompt: sdd/prompts/202604/cd_builtin_vcs_workflow.md
---

# Plan: Built-In `#cd` XPrompt Workflow and Home-Mode Migration

## Goal

Add a built-in `#cd` VCS xprompt workflow that does not use version control. It should take a directory argument, make
that directory the agent/workflow CWD, and otherwise stay out of source-control setup, checkout, diff, and release
logic.

Also migrate the current implicit home mode to use this workflow by defaulting prompts with no embedded VCS workflow to
`#cd:~`. After the migration, `#cd:<path>` is the explicit user-facing spelling for "run here without VCS", and the old
"home mode" behavior becomes a compatibility implementation detail rather than a separate launch concept.

## Current Architecture

Existing workspace-managing workflows are discovered through the `sase_workspace` pluggy entry point and advertised via
`WorkspaceMetadata`:

- `get_workflow_names()`, `get_ref_patterns()`, and `get_vcs_tag_pattern()` drive detection of prompt prefixes such as
  `#git:sase` and plugin-provided `#gh:...` / `#hg:...`.
- Embedded workflows with `tags: vcs` run before other embedded workflows and their post-steps run last.
- `src/sase/xprompts/git.yml` is the only built-in VCS workflow in this repo. It resolves a ref, prepares/checks out a
  worktree, injects the user prompt, releases the workspace, and captures a diff.
- TUI launch starts in home mode for generic prompts, then scans the prompt for VCS workflow refs. If it resolves one,
  it flips `ctx.is_home_mode = False` and pre-allocates workspace env vars for the embedded workflow.
- CLI daemon launch (`launch_agent_from_cwd`) has a similar split: it initially resolves CWD/project context, scans for
  VCS refs, and falls back to home mode when no ref is present.
- Foreground `sase run` uses `_resolve_vcs_cwd()` to `chdir` before workflow execution when a VCS ref appears.
- "Home mode" currently means `project_file=~/.sase/projects/home/home.gp`, `workspace_dir=~`, `workspace_num=0`,
  `is_home_mode=True`, no workspace claim, and a `running.json` marker instead of workspace tracking.

The new workflow should reuse the VCS workflow parsing/detection machinery where possible, but should not allocate a
numbered workspace, call a VCS provider, or claim/release a workspace slot.

## Design Decisions

1. `#cd` is a workspace workflow, not just a plain xprompt.

   It needs to participate in the same "one workspace-managing workflow per prompt" semantics as `#git`, `#gh`, and
   `#hg`, so it should be returned by `get_workflow_names()` and matched by `get_ref_patterns()`.

2. `#cd` should accept path-like refs rather than project refs.

   Supported spellings should include `#cd:~`, `#cd:/abs/path`, `#cd:relative/path`, `#cd:../sibling`, `#cd(.)`, and
   underscore shorthand only where it is unambiguous. Because paths often contain punctuation, the ref pattern should be
   deliberately path-oriented and tested against existing xprompt shorthand syntax.

3. The resolved `#cd` context should remain "home-mode-like" for lifecycle purposes.

   The agent should not reserve a SASE workspace, should not run `prepare_workspace()`, and should still be discoverable
   through the current home-mode running marker mechanism unless a later phase intentionally introduces a clearer name
   for this lifecycle class. This minimizes risk in the agent runner and TUI loaders.

4. The embedded `cd.yml` workflow should be simple.

   Its setup step should expand and validate the path, create no VCS state, print `_chdir=<resolved path>`, and expose
   useful outputs such as `workspace_dir`, `project_name`, and `workflow_name` for metadata. It should have no checkout,
   release, or diff steps.

5. Migration should normalize missing VCS workflow refs to `#cd:~` at launch boundaries.

   Do this close to dispatch, not by changing every UI entry point. This keeps prompt history, MRU, multi-prompt,
   repeat, wait, and direct CLI behavior coherent.

## Phase 1: Register and Parse the Built-In `cd` Workspace Workflow

Owner: workspace/xprompt plumbing agent.

Add a built-in workspace provider for `cd` and a built-in xprompt workflow file.

Implementation scope:

- Extend the built-in `sase_workspace` entry points in `pyproject.toml` with a `cd` workspace plugin.
- Add `src/sase/workspace_provider/plugins/cd_workspace.py`.
- Return `WorkflowMetadata` with:
  - `workflow_type="cd"`
  - `display_name="Directory"`
  - `pre_allocated_env_prefix="SASE_CD"`
  - empty `vcs_family` and `vcs_provider_name`
  - a path-capable `ref_pattern`
- Implement `ws_resolve_ref()` for `workflow_type == "cd"`:
  - expand `~` and environment variables if consistent with local path handling
  - resolve relative paths from the process CWD at launch time
  - require the target to exist and be a directory
  - return a `ResolvedRef` whose `project_name`/`checkout_target` are stable display values and whose
    `primary_workspace_dir` is the target directory
  - use `~/.sase/projects/home/home.gp` as the project file for now, preserving home-mode storage
- Implement `ws_get_workspace_directory()` for `cd` as "return the primary workspace dir"; it should ignore
  `workspace_num`.
- Implement `ws_get_workspace_name()` only if there is a low-risk way to derive a useful name from arbitrary
  directories. Otherwise leave it unset so existing VCS project detection is not disturbed.
- Add `src/sase/xprompts/cd.yml`:
  - `tags: vcs`
  - input path/ref argument
  - setup step that validates and prints `_chdir=<resolved path>` plus typed outputs
  - `inject` prompt_part step
  - no post steps
- Keep `cd` out of VCS provider detection. `detect_vcs()` should continue to return no provider for non-repo
  directories.

Tests:

- Workspace provider unit tests for `#cd:~`, absolute paths, relative paths, nonexistent paths, and files.
- Parsing tests proving `get_vcs_tag_pattern()`, `extract_vcs_workflow_tag()`, `strip_all_vcs_refs()`, and
  `replace_vcs_workflow_tags()` handle `#cd` without regressing `#git`, `#gh`, or `#hg`.
- Workflow loader test that built-in `cd.yml` loads with the `vcs` tag and is embeddable.

Acceptance:

- `cd` appears in `get_workflow_names()`.
- `sase xprompt explain cd` shows a valid embeddable workflow.
- `#cd:~/somewhere` can be detected and resolved without touching git/hg/GitHub code.

## Phase 2: Make Launch Context Resolution Understand Non-Workspace VCS Workflows

Owner: launch-context agent.

Teach shared launch code that a workflow can be "workspace-managing" without allocating a numbered SASE workspace.

Implementation scope:

- Update `resolve_ref_from_prompt()` so `cd` returns `workspace_num=0`, `workspace_dir=<resolved dir>`, and a
  ref/display value without calling `get_first_available_axe_workspace()`.
- Avoid catching and swallowing `#cd` resolution errors silently when the prompt explicitly contains `#cd`; explicit bad
  paths should surface as launch failures rather than falling through to `~`.
- In TUI `_run_agent_launch_body()`:
  - detect `#cd` through the same workflow-name loop
  - set `ctx.workspace_dir` to the resolved directory
  - keep `ctx.is_home_mode=True` for lifecycle/no-claim behavior
  - set display/history keys to a readable path label
  - set `vcs_ref=("cd", ref_value)` so pre-allocation metadata can reach the embedded workflow when appropriate
- In `launch_agent_from_cwd()`:
  - resolve explicit `#cd` before fallback logic
  - launch with `workspace_dir=<resolved dir>`, `workspace_num=0`, `is_home_mode=True`, `vcs_ref=("cd", ref)`
  - do not set `update_target` for `cd`
- In `launch_multi_prompt_agents()`:
  - make per-segment context resolution treat `#cd` as a concrete segment CWD, not as a VCS workspace
  - preserve segment-specific `#cd` refs in multi-prompt and multi-model fan-out
- In `_resolve_vcs_cwd()` for foreground `sase run`, support `#cd` by `chdir`ing to the resolved directory and clearing
  cached project detection.

Tests:

- TUI launch-body tests with a fake `#cd:/tmp/project` prompt that assert `spawn_agent_subprocess()` receives the target
  directory, `workspace_num=0`, `is_home_mode=True`, and no update target.
- CLI daemon tests around `launch_agent_from_cwd("#cd:<tmp> do work")`.
- Multi-prompt tests with mixed `#cd:<dir-a>` and `#cd:<dir-b>` segments.
- Foreground query test proving `_resolve_vcs_cwd()` changes to the requested directory for `#cd`.

Acceptance:

- Explicit `#cd:<dir>` launches from that directory in TUI, daemon, multi-prompt, multi-model, and foreground query
  paths.
- Explicit bad `#cd` refs fail clearly.
- Existing `#git`, plugin `#gh`, and plugin `#hg` launch behavior remains unchanged.

## Phase 3: Migrate Implicit Home Mode to Default `#cd:~`

Owner: compatibility/migration agent.

Replace "no VCS workflow embedded" fallback behavior with an explicit injected `#cd:~` reference.

Implementation scope:

- Add a shared helper, likely near `sase.xprompt._parsing` or launch utilities:
  - detect whether a prompt segment already contains any registered VCS workflow ref
  - if not, prefix that segment with `#cd:~ `
  - preserve leading directives such as `%n:a`, `%model:...`, `%wait`, and frontmatter/multi-prompt separators
- Use that helper at launch boundaries:
  - TUI single prompt before history save and workflow/simple-xprompt checks
  - CLI daemon `launch_agent_from_cwd()` before VCS detection
  - multi-prompt segment expansion, applying default `#cd:~` per segment
  - repeat fan-out specs before recursive launch
  - foreground `run_query()` before `_resolve_vcs_cwd()` if foreground should mirror daemon behavior
- Ensure prompt history stores the normalized prompt if that is the desired new canonical form; otherwise document and
  test any deliberate distinction between raw user prompt and normalized dispatch prompt.
- Keep the old `is_home_mode` runner behavior in place, but make it reachable because `#cd:~` resolved, not because no
  VCS workflow was found.
- Update MRU recording policy:
  - either record `#cd:~` like other VCS refs, or explicitly filter it out if it would pollute VCS MRU cycling
  - test whichever policy is chosen

Tests:

- No-ref TUI launch now dispatches a prompt containing `#cd:~` and runs from `Path.home()`.
- No-ref CLI daemon launch now resolves through `cd` instead of the old direct fallback block.
- A prompt that already starts with `#git`, `#gh`, `#hg`, or `#cd` is not double-prefixed.
- Multi-prompt with one VCS segment and one bare segment adds `#cd:~` only to the bare segment.
- Leading directives remain before the effective VCS tag or continue to be supported by extraction functions.

Acceptance:

- Existing user behavior for bare prompts remains "run from home with no VCS".
- Internally, the dispatch path sees `#cd:~` as the default VCS workflow.
- No prompt receives two workspace-managing workflow refs.

## Phase 4: Runner, Metadata, and Artifact Semantics

Owner: runner/artifacts agent.

Polish the lifecycle semantics so `#cd` agents show correctly and do not trigger VCS-specific behavior.

Implementation scope:

- Verify `run_agent_runner.py` behavior when `is_home_mode=True` and `workspace_dir` is not exactly `~`.
  - `prepare_workspace_if_needed()` should skip.
  - `os.chdir(workspace_dir)` should still happen.
  - home-mode running markers should include the actual `workspace_dir` if needed for TUI display and terminal-opening
    actions.
- Ensure `extract_directives_and_write_meta()` does not report a misleading VCS provider for non-repo `#cd` dirs.
  - For git repos launched via `#cd:/repo`, it is acceptable for metadata to detect Git as the underlying VCS provider,
    but no workspace-management behavior should occur.
- Audit `%wait` with `#cd`.
  - Waiting should not convert a `#cd` agent into a deferred numbered workspace claim.
  - After dependencies resolve, the agent should stay in the requested directory.
- Audit retry behavior.
  - Spawn-on-retry should remain disabled for `is_home_mode=True`; this is consistent with current home behavior.
- Ensure embedded workflow pre-allocation env vars do not cause `#cd` to allocate or release anything.
- Decide whether `#cd` should write a display-only provider label such as "Directory" into `agent_meta.json`.

Tests:

- Runner setup test that `is_home_mode=True`, `workspace_dir=<tmp>` changes CWD and skips workspace prep.
- `%wait #cd:<tmp>` test proving no deferred workspace claim occurs after wait.
- Metadata test for non-repo `#cd:<tmp>` and repo `#cd:<repo>` directories.
- Regression tests for home-mode running marker loading from `src/sase/ace/tui/models/_loaders/_running_loaders.py`.

Acceptance:

- `#cd` agents are visible while running and after completion.
- No workspace slots are claimed or released for `#cd`.
- Agent terminal/open-workspace actions use the actual target directory.

## Phase 5: UX, Completion, Docs, and Cleanup

Owner: UX/docs agent.

Expose `#cd` cleanly and update documentation to make the new default understandable.

Implementation scope:

- Update `docs/xprompt.md`:
  - document `#cd:<path>` under VCS workspace references
  - state that prompts without a VCS workflow default to `#cd:~`
  - describe path examples and quoting/backtick limits
- Update `docs/ace.md` and any launch/workspace docs that describe "home mode".
- Update xprompt browser/completion expectations if `#cd` needs special insertion text or examples.
- Update prompt history / MRU docs depending on the Phase 3 MRU decision.
- Update any tests that hard-code the set of built-in workflow refs or tag counts.
- Consider renaming internal comments from "home mode" to "directory/no-workspace mode" where the code has genuinely
  changed; avoid large mechanical churn.

Tests:

- Xprompt list/catalog tests include `cd` as a built-in workflow where relevant.
- Completion/browser tests can find/insert `#cd`.
- Docs examples pass any existing markdown or command validation used by the repo.

Acceptance:

- Users can discover `#cd` from docs and xprompt browsing.
- "Home mode" docs no longer imply a separate invisible launch mode; they describe the default `#cd:~`.
- `just check` passes after all phases land.

## Cross-Phase Risks

- Path parsing is the highest-risk part. Existing colon syntax often treats spaces as terminators, so supporting paths
  with spaces may require parenthesized or backtick forms rather than raw `#cd:/path with spaces`.
- `#cd` must be included in VCS workflow names for detection, but should not cause VCS provider code to assume there is
  a source-control backend.
- Some helpers use "VCS" terminology for "workspace-managing workflow". Avoid broad renames during implementation; add
  precise comments where `cd` makes the old name misleading.
- Multi-prompt and repeat launch paths are easy to miss because they allocate/spawn before the single-agent path.
- Prompt history canonicalization needs one consistent decision. Mixing raw no-prefix prompts and normalized `#cd:~`
  prompts will make history replay harder to reason about.

## Suggested Phase Order

1. Register and parse `cd`.
2. Make explicit `#cd:<dir>` work everywhere.
3. Migrate no-ref fallback to injected `#cd:~`.
4. Tighten runner/artifact semantics.
5. Update UX/docs and sweep tests.

This order keeps every phase shippable: explicit `#cd` can be built and validated before changing the default behavior
of all no-ref prompts.
