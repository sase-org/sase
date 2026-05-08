# Prompt-Deterministic VCS And Workspace Launch Research

Date: 2026-05-08

## Question

A core project goal is that the VCS used by an agent workspace, and the directory SASE changes into before launching an
agent CLI, should be deterministic based solely on the prompt. This note audits the current codebase for places where
that invariant is upheld, ambiguous, or violated.

## Invariant

For this research, "prompt-deterministic launch" means:

1. The submitted prompt selects the launch directory through an explicit workspace reference such as `#cd`, `#git`,
   `#gh`, or `#hg`, or through the documented default `#cd:~`.
2. The same prompt should resolve to the same workspace provider family and launch cwd regardless of the caller's
   original cwd, `SASE_VCS_PROVIDER`, local config, plugin iteration order, or inherited preallocation env.
3. Workspace slot number can still depend on availability. The invariant is about project/provider/cwd selection, not
   the exact free slot chosen from the RUNNING field.

## Current Launch Contract

The core launch path is mostly shaped correctly:

- `src/sase/agent/launcher.py` normalizes bare daemon/mobile prompts through
  `normalize_default_vcs_workflow()` / `normalize_default_vcs_workflow_segment()`, so prompts without a workspace ref
  become `#cd:~ ...` rather than implicitly using the process cwd.
- `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py` does the same for home-mode TUI launches.
- `src/sase/ace/tui/actions/agent_workflow/_ref_resolution.py` resolves `#cd/#git/#gh/#hg` through workspace-provider
  metadata and returns `(project_file, project_name, workspace_dir, workspace_num, ref)`.
- `src/sase/agent/launch_executor.py` centralizes per-slot workspace resolution for single, multi-model, repeat, and
  multi-prompt fan-out.
- `src/sase/agent/launcher.py` scrubs inherited `SASE_*_PRE_ALLOCATED`, `SASE_*_WORKSPACE_NUM`, and
  `SASE_*_WORKSPACE_DIR` before applying the current launch's preallocation env. This prevents a child launch from
  inheriting a stale parent workspace claim.
- The Rust launch boundary in `../sase-core/crates/sase_core/src/agent_launch/mod.rs` is deterministic once Python has
  resolved the host context: it writes the prompt file, builds argv, copies explicit env deltas, and sets the child
  process cwd to `request.workspace_dir`.
- The child runner in `src/sase/axe/run_agent_runner.py` calls `os.chdir(workspace_dir)` before dynamic memory,
  xprompt/file-reference processing, and LLM invocation. The LLM providers then use this cwd implicitly, except
  OpenCode also passes `--dir os.getcwd()` and Codex sets `CODEX_PROJECT_DIR=os.getcwd()`.

The best covered behavior is `#cd`:

- `src/sase/workspace_provider/plugins/cd_workspace.py` implements a non-claiming directory workflow.
- `tests/test_cd_launch_resolution.py` pins default `#cd:~`, explicit `#cd:<path>`, stale preallocation scrubbing, bad
  paths, per-segment multi-prompt `#cd`, and foreground `_resolve_vcs_cwd()` behavior.
- `docs/xprompt.md` documents that prompts without a workspace reference normalize to `#cd:~`.

## Findings

### 1. VCS provider selection still has ambient overrides

`src/sase/vcs_provider/_registry.py` selects a provider in this order:

1. `SASE_VCS_PROVIDER`
2. `vcs_provider.provider` from merged config
3. auto-detection by walking up from cwd

That is documented in `docs/vcs.md`, and tested in `tests/test_vcs_provider.py`. It is useful for human CLI commands,
but it violates the strict prompt-only invariant for agent launches. A prompt can select `#gh:sase`, then later code such
as `prepare_workspace()` or `sase commit` calls `get_vcs_provider(workspace_dir)` and an ambient
`SASE_VCS_PROVIDER=hg` can override the provider implied by `#gh`.

This affects:

- `src/sase/axe/runner_utils.py::prepare_workspace()`
- `src/sase/workflows/commit/workflow.py`
- `src/sase/workflows/utils.py`
- `src/sase/xprompts/git.yml` checkout steps
- any provider operation that calls `get_vcs_provider(os.getcwd())`

Recommendation: for agent runs with a resolved workspace ref, pin the VCS provider in launch metadata/env from the
workspace workflow metadata (`vcs_provider_name` or `vcs_family`) and make agent-child provider resolution prefer that
launch-scoped value over global env/config. Keep global `SASE_VCS_PROVIDER` for interactive non-agent commands.

### 2. Workflow-ref detection is provider-order dependent

Several launch paths iterate `get_workflow_names()` or `get_ref_patterns()` and take the first match:

- `src/sase/agent/launcher.py::launch_agents_from_cwd()`
- `src/sase/agent/multi_prompt_vcs.py::extract_vcs_ref()`
- `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`
- `src/sase/main/query_handler/_query.py::_resolve_vcs_cwd()`

`get_workflow_names()` returns a `set`, so iteration order is not stable. `get_ref_patterns()` returns a dict from
plugin metadata order, which is more stable than a set but still not "prompt order". If a prompt contains multiple VCS
refs, preallocation/display metadata can be chosen by plugin order rather than by the text. The embedded xprompt layer
later validates at most one `vcs` workflow, but launch planning has already made decisions before that validation.

Recommendation: add one shared parser that scans the prompt once, returns all top-level workspace refs with character
positions, and either rejects more than one before launch or deterministically chooses the earliest text match. Replace
all first-match loops with that parser.

### 3. Relative and env-expanded `#cd` refs are intentionally ambient

`#cd` supports relative paths and environment variables:

- `#cd:relative/path` resolves against the launcher process cwd.
- `#cd:$SOME_DIR` depends on the launcher environment.

This is implemented in `src/sase/workspace_provider/plugins/cd_workspace.py` and tested in
`tests/workspace_provider/test_cd_workspace.py`. It is convenient, but it is not prompt-only unless the ambient cwd/env
are considered part of the prompt context.

Recommendation: either narrow the principle to "prompt plus explicit process context" for `#cd`, or make agent-launch
surfaces canonicalize `#cd` refs to absolute paths before spawn and store the canonical prompt/artifact. For strict
prompt-only behavior, disallow env expansion in launch refs.

### 4. Known-project fallback is only partially provider-independent

`resolve_known_project_vcs_launch_ref()` lets `#gh:sase` target a known project even when the matching workspace plugin
is not registered. That protects prompt shape and local xprompt discovery. However, non-wait workspace allocation later
falls through `running_field.get_workspace_directory_for_num()`, which calls `detect_workflow_type(project_file)`. If
the project really requires the missing workflow plugin, allocation can still fail or use a different fallback provider.

Recommendation: make the fallback explicit. If the workflow plugin is missing, either run from the primary
`WORKSPACE_DIR` with a clear non-claiming mode, or fail early with a message that says the prompt-selected workflow
requires a missing plugin. Avoid silently re-detecting from project files.

### 5. Deferred `%wait` workspace claiming depends on cwd at wake-up

Deferred agents initially claim workspace `0`, wait, then call `claim_deferred_workspace()`. For VCS refs it reads
`SASE_AGENT_VCS_WORKFLOW_TYPE`, but it passes `os.getcwd()` as `primary_workspace_dir` when deriving the real workspace
directory after dependencies complete.

That cwd is normally the primary workspace chosen before wait, so current behavior is usually correct. It is still a
weaker contract than carrying the resolved primary workspace directory through launch metadata.

Recommendation: include `SASE_AGENT_PRIMARY_WORKSPACE_DIR` or equivalent in the launch env for deferred VCS agents and
use that instead of `os.getcwd()` during post-wait allocation.

### 6. Bulk launch bypasses the shared launch executor

`src/sase/ace/tui/actions/agent_workflow/_launch_bulk.py` manually allocates workspace numbers and workspace dirs,
detects workflow type from the ChangeSpec project file, and calls `_launch_background_agent()` directly. It does prefix
each child prompt with `#{workflow_type}:{cl_name}`, so the prompt records the intended VCS context. But it duplicates
logic that the shared launch executor now owns, and it calls `get_workspace_directory_for_num()` rather than the
workflow-aware `resolve_ref_from_prompt()` path.

Recommendation: route bulk through the same prompt-ref parser and `execute_launch_plan()` context construction as
single and multi-prompt launch. That reduces divergence and makes tests for the invariant apply to bulk too.

### 7. Foreground `sase run` is closer, but still cwd-sensitive for artifacts/project claims

`src/sase/main/query_handler/_query.py::run_query()` normalizes default refs and calls `_resolve_vcs_cwd()` before
workflow execution. This makes foreground execution discover project-local xprompts and run in the prompt-selected dir.
After the chdir, it calls `ensure_project_file_and_get_workspace_num()`, so artifact project and workspace claiming are
derived from the post-prompt cwd.

That is acceptable for `#git/#gh/#hg/#cd`, but it means the same prompt can record different project metadata if a
relative `#cd` resolves differently. This is the same relative-path issue as finding 3.

## Existing Safeguards Worth Keeping

- Default home-mode normalization to `#cd:~`.
- Preallocation env scrubbing in `spawn_agent_subprocess()`.
- `#cd` bad-path failures before spawn.
- Multi-prompt per-segment VCS context resolution in `multi_prompt_vcs.py`.
- Launch timestamp and process-preparation determinism in Rust.
- Tests around known-project refs, `#cd`, and fan-out context snapshots.

## Highest-Value Hardening Work

1. Create one canonical workspace-ref parser that returns ordered matches and rejects ambiguous prompts before any
   workspace allocation.
2. Carry a launch-scoped VCS provider/workflow decision into the child process and make agent-run provider resolution
   use it ahead of global env/config.
3. Canonicalize `#cd` refs at launch time or explicitly document that relative/env `#cd` refs depend on launch context.
4. Pass primary workspace dir through deferred `%wait` launch metadata.
5. Move bulk launch onto the shared launch executor path.
6. Add regression tests that set hostile ambient state (`SASE_VCS_PROVIDER`, local config, alternate cwd, stale
   preallocation env, shuffled workflow metadata) and assert that the same prompt chooses the same project/workflow/cwd.

## Bottom Line

The codebase is intentionally moving toward prompt-selected launch context, and the main daemon/TUI/mobile paths mostly
follow that shape. The biggest remaining violation is not workspace allocation itself; it is VCS provider resolution
after launch, where ambient env/config/cwd can still override what the prompt-selected workflow implies. The second
largest risk is duplicate, order-dependent VCS-ref detection before embedded-workflow validation runs.
