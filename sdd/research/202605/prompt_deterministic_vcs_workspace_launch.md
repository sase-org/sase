# Prompt-Deterministic VCS And Workspace Launch Research

Date: 2026-05-08 (revised 2026-05-08)

## Question

A core project goal is that the VCS used by an agent workspace, and the directory SASE changes into before launching an
agent CLI, should be deterministic based solely on the prompt. This note audits the codebase for places where that
invariant is upheld, ambiguous, or violated.

## Invariant

For this research, "prompt-deterministic launch" means:

1. The submitted prompt selects the launch directory through an explicit workspace reference such as `#cd`, `#git`,
   `#gh`, or `#hg`, or through the documented default `#cd:~`.
2. The same prompt resolves to the same workspace provider family and launch cwd regardless of the caller's original
   cwd, `SASE_VCS_PROVIDER`, local config, plugin iteration order, or inherited preallocation env.
3. Workspace slot number can still depend on availability. The invariant is about project/provider/cwd selection, not
   the exact free slot chosen from the RUNNING field.
4. "Prompt" includes embedded directives (`%name`, `%model`, `%wait`) and multi-prompt segments. It excludes the
   process-shell environment and current working directory unless we explicitly carve out exceptions (see finding 3).

## Current Launch Contract

The core launch path is mostly shaped correctly:

- `src/sase/agent/launcher.py::launch_agents_from_cwd()` normalizes bare daemon/TUI prompts through
  `normalize_default_vcs_workflow()` / `normalize_default_vcs_workflow_segment()` (lines 367-401, 437), so prompts
  without a workspace ref become `#cd:~ ...` rather than implicitly using the process cwd.
- `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py` (lines 202-265) does the same for home-mode TUI launches.
- `src/sase/ace/tui/actions/agent_workflow/_ref_resolution.py` resolves `#cd/#git/#gh/#hg` through workspace-provider
  metadata and returns `(project_file, project_name, workspace_dir, workspace_num, ref)`.
- `src/sase/agent/launch_executor.py` centralizes per-slot workspace resolution for single, multi-model, repeat, and
  multi-prompt fan-out.
- `src/sase/agent/launcher.py` scrubs inherited `SASE_*_PRE_ALLOCATED`, `SASE_*_WORKSPACE_NUM`, and
  `SASE_*_WORKSPACE_DIR` before applying the current launch's preallocation env. This prevents a child launch from
  inheriting a stale parent workspace claim.
- The Rust launch boundary in `../sase-core/crates/sase_core/src/agent_launch/mod.rs` is deterministic once Python has
  resolved the host context: it writes the prompt file, builds argv, copies explicit env deltas, and sets the child
  process cwd to `request.workspace_dir`. (`src/sase/core/agent_launch_wire.py:135` plumbs `cwd=str(data["cwd"])`.)
- The child runner in `src/sase/axe/run_agent_runner.py` calls `os.chdir(workspace_dir)` before dynamic memory,
  xprompt/file-reference processing, and LLM invocation. The LLM providers then use this cwd implicitly, except
  OpenCode also passes `--dir os.getcwd()` (`src/sase/llm_provider/opencode.py:159`) and Codex sets
  `CODEX_PROJECT_DIR=os.getcwd()` (`src/sase/llm_provider/codex.py:128`) — both correct *iff* the chdir succeeded.

The best-covered behavior is `#cd`:

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

That is documented in `docs/vcs.md` and tested in `tests/test_vcs_provider.py`. It is useful for human CLI commands, but
it violates the strict prompt-only invariant for agent runs. A prompt can select `#gh:sase`, then later code such as
`prepare_workspace()` or `sase commit` calls `get_vcs_provider(workspace_dir)` and an ambient `SASE_VCS_PROVIDER=hg` can
override the provider implied by `#gh`.

This affects:

- `src/sase/axe/runner_utils.py::prepare_workspace()`
- `src/sase/workflows/commit/workflow.py`
- `src/sase/workflows/utils.py` (lines 28, 42, 168)
- `src/sase/xprompts/git.yml` checkout steps (lines 57, 63, 66, 68 — all `os.getcwd()`)
- `src/sase/xprompts/steps/shared/check_changes.yml` (lines 5-6 — `get_vcs_provider(os.getcwd())`)
- `src/sase/xprompt/workflow_executor_steps_prompt.py:31-32` (post-step `diff_with_untracked(os.getcwd())`)
- `src/sase/workspace_provider/changespec.py:105-106` (`provider.committed_diff(os.getcwd())`)
- any provider operation that calls `get_vcs_provider(os.getcwd())`

Recommendation: for agent runs with a resolved workspace ref, pin the VCS provider in launch metadata/env from the
workspace workflow metadata (`vcs_provider_name` or `vcs_family`) and make agent-child provider resolution prefer that
launch-scoped value over global env/config. Keep global `SASE_VCS_PROVIDER` for interactive non-agent commands.

### 2. Workflow-ref detection is provider-order dependent

Several launch paths iterate `get_workflow_names()` or `get_ref_patterns()` and take the first match:

- `src/sase/agent/launcher.py::launch_agents_from_cwd()` (line 409, breaks on first match)
- `src/sase/agent/multi_prompt_vcs.py::extract_vcs_ref()`
- `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`
- `src/sase/main/query_handler/_query.py::_resolve_vcs_cwd()`
- `src/sase/integrations/_mobile_agent_context.py::mobile_prompt_vcs_ref()` (line 100, breaks on first match)

`get_workflow_names()` returns a `set`, so iteration order is not stable. `get_ref_patterns()` returns a dict from
plugin metadata order, which is more stable than a set but still not "prompt order". If a prompt contains multiple VCS
refs, preallocation/display metadata can be chosen by plugin order rather than by the text. The embedded xprompt layer
later validates at most one `vcs` workflow per segment, but launch planning has already made decisions before that
validation.

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

Additionally, line 258 falls back to `detect_vcs(os.getcwd())` to populate `agent_meta.vcs_provider`. Once the chdir
landed correctly this matches the prompt; if `_resolve_vcs_cwd()` was a no-op (bare prompt prior to default
normalization), the recorded provider is whatever the launching shell's cwd implied.

That is acceptable for `#git/#gh/#hg/#cd`, but it means the same prompt can record different project metadata if a
relative `#cd` resolves differently. This is the same relative-path issue as finding 3.

### 8. Project context is captured *before* prompt normalization

`launch_agents_from_cwd()` (`src/sase/agent/launcher.py:352-362`) calls `ensure_project_file_and_get_workspace_num()`
*before* `normalize_default_vcs_workflow()` runs (line 437) and before any workspace-ref resolution. That helper
(`src/sase/main/utils.py:80-107`) is purely cwd-driven:

- `_get_project_name()` (line 18-27) calls `get_workspace_name(os.getcwd())`.
- `_get_workspace_num()` (line 30-44) scans `os.getcwd()` for `${project}_<N>` suffixes.
- `ensure_project_file_and_get_workspace_num()` then *creates* `~/.sase/projects/<name>/<name>.gp` if missing.

The result is that `project_name`, `project_file`, and `workspace_num` are picked from the launching shell's cwd, not
the prompt. They flow into `add_or_update_prompt()` (line 418) and `launch_multi_prompt_agents(... project_file=...,
project_name=..., workspace_num=...)` (line 423), so:

- prompt history (`history/prompt.py`) is filed under the cwd-derived project, not the prompt-selected one;
- multi-prompt fan-out's `project_name` is locked in before any segment chooses a different VCS ref;
- a prompt like `#gh:sase fix bug` issued from inside `~/projects/github/other-org/other-repo` is *recorded* against
  `other-repo` even though the agent ultimately runs in `sase`.

The post-normalization launch executor still resolves the actual cwd and workspace from the prompt, so the agent itself
runs in the right place. The leakage is in metadata, history, and the side effect of auto-creating an unrelated
`<other-project>.gp` file.

Recommendation: parse workspace refs first; derive `project_name`/`project_file`/`workspace_num` from the resolved
ref; only fall back to cwd-derived project context when the prompt produces no ref and `#cd:~` normalization implies
home mode.

### 9. Mobile launch resolves cwd from the `project:` parameter, not the prompt

`src/sase/integrations/_mobile_agent_launch.py::launch_mobile_prompt()` (lines 80-82) wraps `launch_agents_from_cwd()`
in `mobile_launch_cwd(project_context)`. The project context is built by
`project_context_from_request()` (`_mobile_agent_context.py:25-33`), which prefers an explicit `project:` field from
the JSON request and only secondarily examines the prompt for a VCS ref.

Implications:

- The mobile JSON envelope (`{"project": "sase", "prompt": "..."}`) is treated as part of the launch context. A request
  with no `project:` and no VCS ref in the prompt produces `project_context=None`, and `launch_cwd_for_project_context`
  returns `None` → `launch_agents_from_cwd` runs from the daemon's process cwd. The cwd source becomes "wherever the
  mobile daemon happened to be started", not the prompt.
- When `project: sase` is passed but the prompt also says `#gh:other`, `mobile_launch_cwd` chdirs into the `sase`
  workspace before the launcher normalizes the prompt; downstream resolution uses the prompt's `#gh:other`, but the
  mobile-side cwd transition is a wasted side effect that touches `os.getcwd()`-sensitive code (finding 8) along the
  way.
- `persist_last_mobile_project_context()` (line 99) records the device's last `project:`, so the mobile gateway
  effectively has a sticky project state. Nothing in the codebase enforces that subsequent mobile prompts re-derive
  cwd from prompt content alone.

Recommendation: treat the mobile `project:` field as a hint for default rendering only. Require that any non-home agent
launch be selected by an in-prompt workspace ref (or explicit `#cd:~`) and refuse to chdir from the JSON envelope.

### 10. Resume mode (`sase run -r`) does not re-resolve workspace from the prompt

`src/sase/main/query_handler/_resume.py::handle_run_with_resume()` (lines 73-83) loads `previous_history` and calls
`run_query(query, previous_history)`. `run_query` then performs the same `_resolve_vcs_cwd` + project-ensure flow as a
fresh run, but the *previous_history* has already been written under whatever project the original turn used. Two
gaps:

- The resumed prompt is treated as a brand-new run for cwd/VCS purposes — there is no enforcement that the resumed
  query's workspace ref matches the original session's workspace. A user can resume a chat that started in `#gh:sase`
  with a query that says `#gh:other-repo`, and the agent will silently switch repositories mid-conversation while
  carrying forward chat history that referenced files in the original repo.
- Multi-prompt is rejected for resume (line 58), but there is no symmetric check that "if the original turn was VCS
  workflow X, the resumed turn must use the same X". Determinism here is per-turn, not per-session.

Recommendation: when resuming, capture the original session's resolved workspace_ref in chat metadata and either
require the new query to match (default) or require an explicit `--switch-workspace` flag.

### 11. Agent-retry spawn carries the parent's resolved workspace, not the prompt's

`src/sase/axe/run_agent_retry_spawn.py` ships a `RetryHandoff` that includes the parent's `workspace_num`,
`workspace_dir`, and `vcs_ref`. The child runner consumes these via `transfer_workspace_claim()` and *does not*
re-parse the prompt to verify the resolved cwd still matches.

This is correct behavior given the spec ("retry the same prompt against the same workspace"), but it sidesteps the
invariant in two ways:

- If the parent inherited a stale or wrong workspace (e.g. via finding 5's `os.getcwd()` fallback), the child inherits
  the same wrong workspace silently.
- A retry-on-retry chain can drift further from the prompt. There is no cross-check that the n-th retry's
  resolved `vcs_ref` still matches the canonical prompt-derived ref.

Recommendation: have the spawn child validate its inherited handoff by reparsing the saved prompt and refusing to start
if the resolved ref disagrees with the handoff. Failing fast keeps "same prompt → same workspace" testable.

### 12. Pre-allocation env can override the prompt's own ref

The `#cd` and `#git` workflow setup steps (`src/sase/xprompts/cd.yml:18-26` and
`src/sase/scripts/git_setup.py:32-46`) check `SASE_CD_PRE_ALLOCATED` / `SASE_GIT_PRE_ALLOCATED` *before* resolving the
ref argument:

```python
if pre_allocated:
    workspace_dir = os.environ["SASE_CD_WORKSPACE_DIR"]
    project_name = "home" if cd_ref == "~" else os.path.basename(workspace_dir)
else:
    resolved = resolve_ref(cd_ref, "cd")
```

The launcher correctly scrubs these vars before spawning (finding from prior launch contract), so a freshly launched
child cannot inherit them. But:

- An agent that re-invokes `sase run` *inside its own workspace* will inherit its own `SASE_*_PRE_ALLOCATED=1`. If that
  inner run uses a different VCS ref in its prompt, the pre-allocation env wins and the inner workflow uses the parent
  agent's workspace dir, not the inner prompt's resolved one. There is no test covering nested `sase run` from an
  agent.
- The base name passed to `project_name` when pre-allocated is `os.path.basename(workspace_dir)`. If the parent's
  workspace dir is in an oddly named directory, `project_name` diverges from what `resolve_ref(cd_ref, "cd")` would
  have produced.

Recommendation: scrub `SASE_*_PRE_ALLOCATED` once more inside the workflow setup whenever the resolved ref disagrees
with `SASE_*_WORKSPACE_DIR`, or always recompute and warn if env disagrees.

### 13. Background scheduler subprocesses use ambient cwd, not the ChangeSpec's workspace

`src/sase/ace/scheduler/` spawns several long-running subprocesses, with inconsistent cwd policies:

- **Mentor runner** (`mentor_runner.py:124`): `cwd=os.getcwd()`. The mentor evaluates a ChangeSpec but inherits the cwd
  of whatever process invoked the scheduler (typically the ACE TUI). VCS operations inside the mentor see that
  ambient cwd, not the ChangeSpec's workspace.
- **CRS runner** (`workflows_runner/starter.py:251`): `cwd=workspace_dir`. Correct — the workspace is resolved up
  front and passed explicitly.
- **Fix-hook runner** (`workflows_runner/starter.py:377`): `cwd=os.path.expanduser("~")`. The fix-hook agent is forced
  into `~`, then relies on its embedded `#hg` xprompt to chdir into the right workspace. Any cwd-sensitive operation
  *before* the embedded xprompt expands runs in `~`.
- **Summarize/checks subprocesses**: spawned without an explicit `cwd=` (inherits parent), making them dependent on
  whoever started ACE.

Recommendation: standardize on `cwd=workspace_dir` for any subprocess that inspects or mutates a ChangeSpec's workspace.
Where the subprocess will chdir later via its own xprompt, document that the initial cwd must not be observable to the
business logic.

### 14. Stop-hook resolves project_dir from runtime env, not launch metadata

`src/sase/scripts/sase_commit_stop_hook.py::_resolve_project_dir()` (lines 38-43) resolves the project dir in this
order:

1. `CLAUDE_PROJECT_DIR`
2. `GEMINI_PROJECT_DIR`
3. `CODEX_PROJECT_DIR`
4. `os.getcwd()`

Then `_resolve_commit_skill()` (lines 153-176) calls `detect_vcs(project_dir)` if `SASE_VCS_PROVIDER` is unset or
"auto", and `_normalize_provider()` (lines 83-92) silently coerces `"auto"` to `"git"`. Implications:

- The hook is keyed on runtime-injected project-dir variables that the LLM provider sets (Claude/Gemini/Codex). If the
  agent runtime drifts (e.g. Codex starts setting `CODEX_PROJECT_DIR` to a non-workspace path during tool calls), the
  commit hook silently routes to a different VCS provider.
- The `auto → git` coercion means a misconfigured hg workspace produces a git skill invocation with no warning,
  violating "the prompt selected `#hg`".
- There is no `SASE_AGENT_WORKSPACE_DIR` or `SASE_AGENT_VCS_PROVIDER` in the resolution order. The launch decision and
  the commit decision use disjoint sources of truth.

Recommendation: have the launcher write `SASE_AGENT_WORKSPACE_DIR` and `SASE_AGENT_VCS_PROVIDER` into the child env as
a launch-scoped, non-overridable record, and make the stop hook prefer those over runtime project-dir vars and over
auto-detection.

### 15. Embedded `script:` workflow steps run with `cwd=os.getcwd()`

`src/sase/xprompt/workflow_executor_steps_script.py` runs script steps with `cwd=os.getcwd()` at lines 110 and 265.
This is correct *iff* a previous step emitted `_chdir=<workspace>` and the executor honored it before the script step
ran. If a workflow author rearranges steps, or if `_chdir` came from a step whose `python:` block didn't print, the
script step runs against whatever ambient cwd the workflow inherited.

There's no defensive validation that `os.getcwd()` matches the workspace_dir output of an earlier step.

Recommendation: pass `workspace_dir` explicitly to script steps via a new `cwd:` field, defaulting to the most recent
`workspace_dir` emitted by an earlier step rather than reading process cwd.

### 16. Multi-agent xprompt VCS-tag inheritance lacks scoping rules

`src/sase/agent/multi_agent_xprompt.py::_prepend_inherited_vcs_ref()` (around lines 419-421) prepends a leading VCS tag
like `#gh:sase` to every body segment that lacks its own ref. There's no validation that the inherited workspace is
still valid, no opt-out for segments that intentionally run outside the inherited workspace (e.g. a meta-analysis
segment), and no recursion guard against multi-agent xprompt nesting that re-scopes refs to the wrong workspace.

Two multi-agent xprompts that each carry the same `#gh:sase` will both claim the same workspace; nothing in the
inheritance layer detects the conflict. (Already raised in the related VCS xprompt hardening note; included here because
it is a determinism issue: the same prompt can pick a different workspace slot depending on iteration order.)

Recommendation: validate inherited refs against the registry at expansion time, and add a `#cd:~` opt-out marker so a
segment can explicitly run outside the inherited context.

### 17. `vcs_provider` plugin order silently selects winners

`src/sase/vcs_provider/_hookspec.py` declares every hook as `@hookspec(firstresult=True)`. With multiple installed
providers, the first registered wins. Plugin order comes from `importlib.metadata.entry_points()`, which is not stable
across Python versions or environments. A workspace selected by `#gh:sase` therefore may dispatch through a different
provider on different machines if both `sase-github` and a fork plugin are installed.

This is a determinism gap by-host rather than by-prompt, but it falls under the same invariant: the same prompt should
pick the same provider in any environment.

Recommendation: require providers to declare ordered priorities in their entry-point metadata, log all matching
plugins at registration, and refuse to dispatch when two plugins both claim the same VCS family without an explicit
priority tiebreaker.

## Background And Alternate Entrypoint Inventory

| Entrypoint                                              | cwd at launch source                                                                 | Risk                                                                                                                                                |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sase run` (foreground)                                 | `_resolve_vcs_cwd()` then `run_query()`                                              | Cwd-derived project metadata before chdir (finding 7); fallback `detect_vcs(os.getcwd())` for `agent_meta`                                          |
| `sase run -d` (daemon) → `launch_agents_from_cwd`       | Prompt normalization → executor                                                      | Project context captured pre-normalization (finding 8)                                                                                              |
| `sase run -r` (resume)                                  | New cwd resolution per turn                                                          | Cross-turn workspace mismatch undetected (finding 10)                                                                                               |
| TUI `@` keymap                                          | `_agent_launch.py` normalizes then dispatches                                        | Same path as daemon                                                                                                                                 |
| TUI bulk launch                                         | `_launch_bulk.py` resolves directly from ChangeSpec                                  | Bypasses shared executor (finding 6)                                                                                                                |
| `sase bead work <id>` → `launch_agent_from_cwd`         | Multi-prompt rendered with explicit `bd/work_phase_bead`                             | Inherits findings 2/8                                                                                                                               |
| Mobile JSON gateway                                     | `mobile_launch_cwd(project_context)` chdirs from JSON `project:` field               | Cwd selection from envelope, not prompt (finding 9); sticky last-project state                                                                      |
| ACE mentor subprocess                                   | `cwd=os.getcwd()` (ACE process cwd)                                                  | Workspace context inherited from TUI (finding 13)                                                                                                   |
| ACE CRS subprocess                                      | `cwd=workspace_dir`                                                                  | Correct                                                                                                                                             |
| ACE fix-hook subprocess                                 | `cwd=~`                                                                              | Initial pre-xprompt code runs in `~` (finding 13)                                                                                                   |
| Stop-hook (`sase_commit_stop_hook.py`)                  | `CLAUDE/GEMINI/CODEX_PROJECT_DIR` env → `os.getcwd()`                                | Disjoint from launch decision (finding 14); silent `auto → git`                                                                                     |
| `sase commit` skill wrapper                             | Inherits agent process cwd                                                           | Right *if* runner chdir landed                                                                                                                      |
| Embedded VCS xprompt setup                              | `os.environ["SASE_*_WORKSPACE_DIR"]` or `resolve_ref(...)`                           | Pre-allocation env beats prompt arg (finding 12)                                                                                                    |
| Embedded `script:` step                                 | `cwd=os.getcwd()`                                                                    | Drifts from `workspace_dir` if `_chdir` not honored (finding 15)                                                                                    |
| Embedded `prompt:` post-step diff                       | `os.getcwd()`                                                                        | Same as above                                                                                                                                       |
| Retry-on-spawn child                                    | Inherited from `RetryHandoff`                                                        | Carries parent's resolved workspace without re-validation (finding 11)                                                                              |
| `%wait` deferred wakeup                                 | `os.getcwd()` passed as `primary_workspace_dir`                                      | Usually correct; weak contract (finding 5)                                                                                                          |

## Existing Safeguards Worth Keeping

- Default home-mode normalization to `#cd:~`.
- Preallocation env scrubbing in `spawn_agent_subprocess()`.
- `#cd` bad-path failures before spawn.
- Multi-prompt per-segment VCS context resolution in `multi_prompt_vcs.py`.
- Launch timestamp and process-preparation determinism in Rust (`agent_launch_wire.py:135`).
- Tests around known-project refs, `#cd`, and fan-out context snapshots.
- CRS subprocess explicit `cwd=workspace_dir`.

## Highest-Value Hardening Work

1. **Prompt parser of record.** Create one canonical workspace-ref parser that returns ordered matches and rejects
   ambiguous prompts before any workspace allocation. Replace every `for ... in get_ref_patterns(): break` loop with
   it.
2. **Resolve-then-record.** Move `ensure_project_file_and_get_workspace_num()` and any project-history side effects to
   *after* prompt normalization and ref resolution, so `project_name` / `project_file` / `workspace_num` are
   prompt-derived (finding 8). Keep cwd-derived behavior only when the prompt resolves to home mode.
3. **Launch-scoped VCS provider env.** Carry `SASE_AGENT_WORKSPACE_DIR` and `SASE_AGENT_VCS_PROVIDER` into every child
   process and make `vcs_provider._registry` and the stop hook prefer them over global env/config and over
   `CLAUDE/GEMINI/CODEX_PROJECT_DIR`.
4. **Canonicalize `#cd` refs at launch time** or explicitly document that relative/env `#cd` refs depend on launch
   context (finding 3).
5. **Pass `primary_workspace_dir` through deferred `%wait` launch metadata** (finding 5).
6. **Move bulk launch onto the shared launch executor path** (finding 6).
7. **Audit subprocess cwd policies** in `ace/scheduler/` so every subprocess that touches a ChangeSpec workspace gets
   `cwd=workspace_dir` (finding 13).
8. **Validate retry handoff** by reparsing the saved prompt in the spawned child (finding 11).
9. **Reject envelope-driven cwd in mobile launches.** Mobile `project:` becomes a hint, not a chdir source
   (finding 9).
10. **Plugin-order tiebreakers** for vcs_provider hooks; warn at registration when two plugins claim the same family
    (finding 17).
11. **Regression test matrix** that sets hostile ambient state (`SASE_VCS_PROVIDER`, local config, alternate cwd, stale
    preallocation env, shuffled workflow metadata, conflicting `CLAUDE_PROJECT_DIR`) and asserts that the same prompt
    chooses the same project/workflow/cwd through every entrypoint in the inventory above.
12. **Resume-session workspace pinning.** Record the resolved workspace in chat metadata; require future turns to match
    (finding 10).

## Bottom Line

The codebase is intentionally moving toward prompt-selected launch context, and the daemon/TUI paths satisfy the
invariant for the agent's *runtime* cwd. The largest remaining gaps are not in the spawn step; they are upstream and
downstream:

- **Upstream**: project metadata is captured from cwd before the prompt is normalized, mobile launches chdir from a
  JSON envelope, resume mode never compares the new turn's workspace ref against the original session's, and ACE
  subprocesses inherit ambient cwds.
- **Downstream**: VCS provider resolution after launch (`get_vcs_provider(os.getcwd())` in commit/diff/check_changes
  flows, the stop hook's env-chain → `auto → git` coercion, plugin first-result tiebreaks) can override what the
  prompt-selected workflow implied.

Closing the upstream gaps requires moving prompt parsing earlier in the launch pipeline. Closing the downstream gaps
requires a launch-scoped record (`SASE_AGENT_WORKSPACE_DIR` / `SASE_AGENT_VCS_PROVIDER`) that every later consumer
prefers over ambient env, config, cwd, and plugin order.
