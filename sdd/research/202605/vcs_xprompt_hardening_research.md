# VCS XPrompt Hardening Research

Date: 2026-05-05 (revised 2026-05-04)

## Research Question

VCS xprompt workflows have been a recurring source of bugs and troubleshooting. This note maps the current subsystem,
identifies the most likely failure modes, and recommends hardening and debugging work that would reduce time spent
diagnosing regressions.

This builds on `sdd/research/202605/vcs_xprompt_workflows_critique.md`, which argues for a first-class VCS intent layer.
The focus here is operational: what to instrument, test, and simplify next.

## Current System Map

The subsystem is not one workflow. It is a chain of contracts spanning prompt parsing, workflow embedding, workspace
claiming, agent runtime hooks, commit orchestration, and provider plugins.

1. User prompt references are parsed and normalized in `src/sase/xprompt/_parsing.py`.
   - VCS tags are recognized by a dynamic workspace-provider pattern (`extract_vcs_workflow_tag`, lines 106-120).
   - `#gh_sase`-style underscore refs are normalized before workflow matching (lines 68-89).
   - Bare prompt segments are normalized to `#cd:~` when no workspace ref is present (lines 183-216 and 285-311).
   - Nested workflow prompt steps can inherit an outer VCS tag per segment (lines 219-269).

2. Embedded workflow expansion is the main routing layer.
   - `workflow_executor_steps_embedded_expand.py` protects fenced blocks, splits multi-prompt segments, normalizes
     underscore refs, collects workflow refs, and rejects inline standalone workflows (lines 56-179).
   - It enforces at most one VCS-tagged workflow per segment (lines 181-190).
   - It runs VCS workflow pre-steps first, then non-VCS pre-steps right-to-left (lines 192-225).
   - It injects workflow environment variables into `os.environ` for the agent, stop hooks, and post-steps (lines
     227-233).
   - It hard-codes commit method to context-appender tag routing (`create_commit` / `create_proposal` ->
     `append_to_commit_and_propose`, `create_pull_request` -> `append_to_pr`) at lines 272-296.
   - It writes `embedded_workflows.json` and `embedded_workflows_<step>.json` artifacts at lines 349-370.

3. Prompt execution then invokes an agent and runs embedded post-steps.
   - `workflow_executor_steps_prompt.py` applies inherited VCS tags before preprocessing (lines 184-187).
   - It saves a running step marker before invoking the agent (lines 261-269).
   - It captures response chat history best-effort (lines 307-318).
   - It captures an uncommitted VCS diff after the agent turn (lines 395-406).
   - It runs embedded post-steps and separately runs `finally` post-steps after failures (lines 417-475).
   - It updates parent step markers with embedded `meta_*` and `diff_path` outputs after post-steps (lines 483-524).

4. The built-in VCS and commit intent workflows are YAML wrappers.
   - `src/sase/xprompts/git.yml` resolves and claims a workspace, stashes/pulls, checks out the target, injects an empty
     prompt part, then releases and captures a diff in `finally` steps.
   - `src/sase/xprompts/cd.yml` resolves a local directory and emits `_chdir`, but does not release or diff.
   - `src/sase/xprompts/commit.yml`, `propose.yml`, and `pr.yml` set `SASE_COMMIT_METHOD`, inject "do not commit
     yourself" instructions, check for changes, and later read `commit_result.json`.
   - `src/sase/xprompts/sync.yml` is a standalone conflict-resolution workflow with an agent loop.

5. Commit intent crosses into runtime hooks and `sase commit`.
   - `sase_commit_stop_hook.py` reads `SASE_COMMIT_METHOD`, detects local changes, chooses `/sase_git_commit` or
     `/sase_hg_commit`, and emits runtime-specific block/deny instructions (lines 254-340).
   - The hook logs JSONL to `~/.sase_commit_stop_hook.jsonl` (lines 17-35).
   - `src/sase/scripts/sase_git_commit` is a shell wrapper around `sase commit` that logs to
     `~/.sase_git_commit.jsonl` (lines 1-75).
   - `cl_handler.py` canonicalizes CLI/env commit method aliases and rejects conflicts unless
     `SASE_COMMIT_METHOD_ALLOW_OVERRIDE=1` is set (lines 52-79).
   - `CommitWorkflow.run()` validates payloads, runs precommit/bead/plan work, dispatches to a VCS provider, writes a
     checkpoint, and records ChangeSpec/COMMITS artifacts (lines 79-295).
   - `commit_tracking.py` writes `commit_result.json` under `SASE_ARTIFACTS_DIR` for xprompt post-steps (lines 205-231).

6. The VCS provider and workspace provider layers are pluggy based.
   - Workspace plugins declare workflow syntax and preallocated env prefixes through `WorkflowMetadata`
     (`workspace_provider/_hookspec.py`, lines 22-45).
   - The workspace registry builds the VCS tag regex dynamically from installed workflow metadata
     (`workspace_provider/_registry.py`, lines 38-103).
   - VCS providers expose core operations, sync operations, commit dispatch operations, and finalization hooks through
     `VCSProvider` (`vcs_provider/_base.py`, lines 230-353).
   - The git implementation stages, merges, commits, pushes, creates proposal diffs, and creates branches in
     `_git_commit_dispatch.py` (lines 147-260).

## Why This Keeps Breaking

### 1. Too much implicit global state

The current intent handoff depends on process environment:

- `SASE_COMMIT_METHOD` selects the commit method.
- `SASE_PR_NAME`, `SASE_BUG_ID`, and `SASE_PR_STATUS` carry `#pr` inputs.
- `SASE_ARTIFACTS_DIR` is where `commit_result.json`, workflow state, live replies, and other artifacts appear.
- `SASE_AGENT_PROJECT_FILE`, `SASE_AGENT_CL_NAME`, and `SASE_AGENT_TIMESTAMP` influence commit tracking and checkpoint
  location.

Environment inheritance is convenient, but it makes bugs hard to localize because the authoritative state is not in one
artifact. A failed run often requires inspecting workflow YAML, `workflow_state.json`, `embedded_workflows*.json`,
hook logs, commit wrapper logs, `commit_state.json`, and `commit_result.json`.

The tests confirm this stateful shape: embedded workflow environment injection is explicitly tested in
`tests/test_embedded_env_injection.py` lines 91-138, and CLI/env method conflict handling is tested in
`tests/test_commit_cli.py`.

### 2. Generic xprompt code knows commit semantics

The embedded workflow executor has a method-to-tag switch for commit-specific context appending. That makes the generic
workflow engine responsible for domain knowledge that belongs to intent metadata or provider configuration.

This is especially fragile because the routing happens during prompt expansion before the agent runs, while the result
marker is written much later by `CommitWorkflow`. There is no single object tying together:

- selected workspace ref,
- selected commit intent,
- selected provider,
- inherited VCS tag,
- appended provider context,
- commit result marker.

### 3. There are several parallel "truth" artifacts

The system already writes useful files, but they are not designed as one debug trace:

- `workflow_state.json`: step status, context, current step, pid.
- `prompt_step_*.json`: TUI-visible step markers.
- `embedded_workflows.json` / `embedded_workflows_<step>.json`: workflows found in prompt expansion.
- `commit_result.json`: final commit/propose/PR result.
- `commit_state.json`: resumable commit checkpoint.
- `~/.sase_commit_stop_hook.jsonl`: stop-hook decisions.
- `~/.sase_git_commit.jsonl`: git commit wrapper start/end.
- provider command stderr/stdout: usually lost unless surfaced in an error string.

The files are individually useful, but there is no standard correlation ID across all of them. The closest shared keys
are `SASE_AGENT_TIMESTAMP`, artifacts dir path, pid, and workflow name.

### 4. Parser behavior has a large state space

The parser supports:

- colon, underscore, parenthesized, plus, and bang standalone syntax;
- same-line and multi-line directives before VCS tags;
- multi-prompt `---` segments;
- frontmatter preservation;
- fenced code block protection;
- known-project fallback refs when a provider is not installed;
- inherited VCS tags for nested workflow steps;
- default `#cd:~` insertion.

This is the right feature set, but it makes edge regressions likely. Tests cover many primitives in
`tests/test_xprompt_parsing.py` lines 140-495 and `tests/test_cd_vcs_parsing.py`, but higher-level scenario coverage is
still thin around combinations like inherited VCS tag plus standalone workflow plus commit intent plus multi-prompt
fan-out.

### 5. The stop-hook flow is intentionally agent-mediated

The stop hook does not create commits. It blocks the agent and instructs it to use the relevant skill. This preserves
runtime consistency, but it adds a second agent turn and one more source of failures:

- hook dedup marker may skip a later needed block (`sase_commit_stop_hook.py`, lines 279-329);
- missing or stale `SASE_COMMIT_METHOD` changes what skill invocation should do;
- the agent can pass a conflicting `--type`, though the CLI now rejects that by default;
- the skill wrapper can fail before `commit_result.json` is written.

The commit checkpoint/resume work reduced one major class of failures. `CommitWorkflow.run()` now leaves
`commit_state.json` on conflict and `CommitWorkflow.resume()` replays tracking after the user/agent resolves the VCS
state. The tests in `tests/test_commit_workflow_checkpointing.py` cover conflict detection and checkpoint retention
(lines 48-69, 183-199).

### 6. The stop hook silently degrades when provider hooks fail or are missing

`sase_commit_stop_hook._get_changed_files` (lines 206-237) has three layered fallbacks that all swallow exceptions:

- `provider.diff_with_untracked` -> on `NotImplementedError`, fall back to `provider.diff` (lines 213-220). `provider.diff`
  does not include untracked files. So in a working dir whose only changes are *new* files, an older provider plugin
  reports "no changes", the hook does not block, and the agent exits without committing.
- A bare `except Exception: diff_text = None` (lines 221-222) hides any provider crash, including authentication errors,
  process timeouts, or partial output.
- The fallback `has_local_changes` path (lines 228-235) reports `(unable to list changed files for this VCS provider)` as a
  fake file name. The block message that follows is correct, but the JSONL log line records a synthetic file path that
  looks like a real change.

Combined with `_resolve_commit_skill` (lines 153-162) — which never validates that the resolved skill actually exists —
the result is that a misconfigured runtime can be told "use `/sase_<unknown>_commit`" without any error.

### 7. `firstresult=True` on every VCS hookspec hides plugin errors

Every entry in `vcs_provider/_hookspec.py` declares `@hookspec(firstresult=True)`. Pluggy stops at the first non-`None`
return. Provider plugins return `(bool, str | None)` tuples for most ops, so `(False, "<stderr>")` counts as a "result"
and prevents the next plugin from being tried. There is no error class that means "skip me, try the next plugin":
plugins must return `None` to fall through, and all current plugins return tuples on every code path.

Practical impact: if two plugins legitimately match (e.g. a custom GitHub fork plus the stock `sase-github`), the first
one loaded wins on every dispatch — including when it fails. There is no logged warning at registration. Plugin order is
whatever `importlib.metadata.entry_points()` returns, which is not stable across Python versions or environments.

### 8. Workspace claims have no TTL or crash recovery

The workspace claim list in the project file (`WORKSPACE_CLAIMS:`) is acquired by `claim_workspace` and released by
`release_workspace`. Only `accept` and `rewind` workflows wrap the agent invocation in a `try/finally` that calls
`release_workspace` (`workflows/accept/workflow.py:360-363`, `workflows/rewind/workflow.py:209-212`). All other VCS
xprompt entry points rely on the `git.yml` / `gh.yml` / `hg.yml` `finally` post-step. If the parent process is killed
between the agent turn and the `finally` post-step (SIGKILL, container OOM, host reboot, or a crash inside the embedded
executor itself), the claim stays in the project file forever and `sase accept -r` is the only way out.

There is no PID-liveness check during `claim_workspace`, no lockfile-style heartbeat, and no `sase workspace prune`
command. This is a small change with outsized impact on day-to-day frustration.

### 9. Spawn-on-retry can transfer stale or missing claims

`run_agent_retry_spawn.spawn_retry_agent` (lines 227-326) calls `transfer_workspace_claim` (`running_field/_operations.py:216-248`)
to hand the claim from the failing parent to the new child. Two gaps:

- The transfer does not check that the parent still owns the claim. If a `finally` post-step ran on the parent before
  the spawn decision (e.g. because the failure surfaced after `release_workspace`), the transfer silently moves a claim
  the parent no longer holds.
- VCS workflow `finally` blocks fire on the parent process. After spawn, the child inherits the in-progress edits via
  the transferred claim, but it does not re-run pre-steps like `setup`/`prepare`/`checkout`. If the parent died after
  the partial release of provider state (stash without unstash, sync mid-rebase), the child resumes in that partial
  state with no awareness.

### 10. Multi-agent xprompt + VCS tag inheritance lacks scoping rules

`agent/multi_agent_xprompt.py:_prepend_inherited_vcs_ref` (around lines 419-421) prepends a leading VCS tag like
`#gh:sase` to every body segment that lacks its own ref. There is no validation that:

- the workspace ref still exists or is still valid for the inherited target;
- segments that *intentionally* run outside the inherited workspace (e.g. a meta-analysis segment) can opt out;
- inheritance does not cross multi-agent xprompt nesting in a way that re-scopes refs to the wrong workspace.

Recursion depth (`max_depth <= 0`, line 404) protects against expansion loops but not against ref-reuse loops where two
multi-agent xprompts each carry the same `#gh:sase` and conflict on the same workspace.

### 11. Non-xprompt sites also write `SASE_COMMIT_METHOD`

`axe/fix_hook_runner.py:210` and `workflows/crs.py:225` set `SASE_COMMIT_METHOD=create_proposal` directly. These run in
the same process the embedded workflow already touched. Last-write-wins applies with no conflict detection. The CLI guard
in `cl_handler.py` rejects conflicting `--type` vs env, but it does not see the historical sequence of who wrote what,
so an agent that re-enters a commit path in mid-run can act on a method the user never asked for.

There is no test that covers `fix_hook_runner` or `crs.py` setting the method while an active xprompt has already set
it. The conflicts are easy to miss because they only trigger on certain hook compositions.

### 12. Diff and ChangeSpec writes degrade silently on partial failure

- `commit_tracking.capture_pre_commit_diff` (lines 48-84) returns `None` when `provider.diff(cwd)` reports `(False, ...)`
  with no log line. The COMMITS drawer then records an entry whose `diff_path` is empty, and the user has no signal that
  the diff was lost.
- `commit_tracking.append_commits_entry` (lines 127-150) has no rollback. If it fails after a successful commit, the
  ChangeSpec drawer is missing the entry while the working tree already has the commit. The next run sees an
  inconsistent COMMITS list and either resumes incorrectly or duplicates an entry.
- `workflow_executor_steps_prompt.py` lines 395-406 capture an uncommitted VCS diff after the agent turn. There is no
  branch for "cwd is not a repo" or "git/hg binary missing": failures are logged at debug level only, so a missing diff
  artifact looks identical to no work having been done.

### 13. `#sync` agent loop has weak boundary behavior

`xprompts/sync.yml` runs the `resolve` step under `repeat: { until: resolve.all_resolved, max: 20 }`. If the loop hits
20 without resolving, the workflow exits with `all_resolved=false` and the report step produces a non-success status,
but:

- there is no documented contract for what the user should do next, and no automatic escalation to `sase commit --resume`;
- there is no HITL break-out signal: a human who realises the agent is stuck cannot signal "stop iterating" without
  killing the agent, which leaves the workspace in mid-rebase state and triggers gap #8 above;
- a successive `#sync` run starts from scratch with no knowledge that a prior loop made partial progress.

### 14. Documentation drifts from code

Several documented behaviors are stronger than the implementation:

- `docs/commit_workflows.md` says missing `commit_result.json` should fail explicitly; in practice the intent xprompts
  print `success=false` or `{}` and rely on the stop hook to prevent reaching that state. (Already noted in the prior
  critique, but it remains true.)
- `docs/vcs.md` does not call out that `#cd` carries the `vcs` tag and competes with `#git`/`#gh`/`#hg` for the
  at-most-one-vcs slot. Users can be surprised when `#cd #git:sase` is rejected.
- The `#sync` 20-iteration cap is not documented anywhere user-facing.
- The list of `SASE_*` environment variables that VCS xprompts read or write is spread across YAML files, hooks, and
  Python modules with no canonical reference.

## Debugging Gaps

### Missing single-command diagnosis

There is no `sase debug vcs-xprompt <artifacts-dir>` command that reconstructs a run. Today the user has to know which
files to inspect and how to relate them.

A useful diagnosis command should print:

- workflow name, artifacts dir, pid, status, current step;
- raw prompt and expanded prompt if available;
- embedded workflows by step, with tags and explicit args;
- environment contract snapshot: `SASE_COMMIT_METHOD`, `SASE_VCS_PROVIDER`, `SASE_AGENT_*`, `SASE_PR_*`;
- workspace cwd before and after `_chdir`;
- provider detection result and workspace provider workflow type;
- stop-hook events filtered by session/artifacts dir/pid;
- commit wrapper events filtered by cwd/pid/time window;
- commit checkpoint state, if present;
- commit result marker, if present;
- likely next action: "resume commit", "missing commit_result.json", "hook did not run", "method conflict", "provider
  not detected", "workspace still conflicted".

This should be read-only and should work even if the workflow crashed before validation.

### Missing correlation ID

Add a stable `SASE_RUN_ID` or `SASE_WORKFLOW_RUN_ID` at workflow start and include it in:

- `workflow_state.json`,
- `embedded_workflows*.json`,
- `prompt_step_*.json`,
- stop-hook JSONL,
- `sase_git_commit` JSONL,
- `commit_state.json`,
- `commit_result.json`,
- provider operation telemetry/log events.

Artifacts dir can serve as a fallback, but it is too path-shaped and not always present.

### Provider command traces are too lossy

`CommandRunner._run()` returns stdout/stderr to callers, but there is no structured per-command trace. For hard cases,
especially merge/push failures, the debugging path needs exact commands, cwd, exit code, duration, and stderr.

Add an opt-in trace file under artifacts, for example `vcs_commands.jsonl`. Include sanitized command argv, cwd,
provider, operation name, exit code, duration, stdout/stderr byte counts, and stderr tail. This would materially reduce
guesswork without turning normal logs into noise.

### Pluggy `firstresult` swallows the chain

Because every VCS hook is `firstresult=True` and plugins return tuples (not `None`) on failure, there is no way to fall
through to a second matching plugin and no record that a fall-through was attempted. Add a small wrapper at registration
time that:

- logs which plugins are registered for each hook;
- emits a one-line warning when more than one plugin is registered for the same hook (potential ambiguity);
- in trace mode, records which plugin actually handled each call.

This converts what is currently undefined behavior into observable, actionable signals.

### Workspace state is invisible until you touch a project file

The current `WORKSPACE_CLAIMS:` drawer is the only authoritative source of who holds what. There is no
`sase workspace status` command and no warning when a stale claim is older than the parent process. Even surfacing
"claim held by PID 12345 (not running)" in `sase debug vcs-xprompt` would let users self-diagnose half of the
"why can't I claim this workspace" cases.

### Missing intent artifact

The current durable output tells us what happened after commit, not what was selected before the agent ran. Add
`vcs_intent.json` during embedded expansion:

```json
{
  "run_id": "...",
  "source_workflow": "pr",
  "intent": "change",
  "method": "create_pull_request",
  "args": {"name": "feature_x", "bug_id": 12345, "status": "draft"},
  "append_context_tag": "append_to_pr",
  "workspace_workflow": "git",
  "workspace_ref": "sase"
}
```

Initially this can be generated from existing YAML/environment fields. Later it should come from typed workflow
metadata.

## Test Gaps Worth Closing

1. Prompt scenario matrix.
   Add table-driven tests that expand prompts through the real anonymous workflow path, not only parser helpers:
   - `#git:sase #commit fix`;
   - `#git:sase #propose fix`;
   - `#git:sase #pr(name=feature) fix`;
   - `%model:... #git:sase #!standalone`;
   - multi-prompt with one explicit VCS tag and one inherited/default segment;
   - fenced code blocks containing fake VCS refs;
   - known-project refs when plugin metadata is absent.

2. Intent uniqueness.
   There is an at-most-one rule for VCS-tagged workflows, tested in `tests/test_wraps_all.py` lines 95-149. Add the
   symmetric rule for commit-intent workflows so `#commit #pr` and `#commit #propose` fail early with a clear error.

3. Method-to-append-tag routing.
   Until a typed intent layer removes the hard-coded switch, test that:
   - `create_commit` and `create_proposal` request `append_to_commit_and_propose`;
   - `create_pull_request` requests `append_to_pr`;
   - missing tagged appender workflows produce a visible trace but not a cryptic failure.

4. Artifact completeness.
   Add tests that execute fake workflows and assert the expected debug artifacts appear:
   `workflow_state.json`, step marker, `embedded_workflows_<step>.json`, optional `vcs_intent.json`,
   `commit_state.json`, and `commit_result.json`.

5. Stop-hook session behavior.
   Existing tests cover runtime-specific block formatting and message content in `tests/test_commit_stop_hook.py` lines
   14-122. Add tests for dedup marker behavior across `SASE_AGENT_TIMESTAMP` values and for logs containing the future
   run ID and artifacts dir.

6. Provider contract tests for command traces and conflict states.
   Git sync tests already exercise `sync_workspace`, `is_sync_in_progress`, `get_conflicted_files`, `continue_sync`, and
   `abort_sync` in `tests/test_vcs_provider_git_sync.py`. Add equivalent contract assertions that provider commit
   dispatch failures expose enough structured state for diagnosis.

7. Stop-hook fallback semantics.
   Add tests where:
   - the provider only implements `diff` (not `diff_with_untracked`) and the working tree has only untracked files;
   - the provider raises an exception inside `diff_with_untracked`;
   - `_resolve_commit_skill` is asked to resolve a runtime+VCS combo that has no installed skill.
   Each case should produce a visible diagnostic, not a silent no-op.

8. Workspace lifecycle tests.
   - Kill the agent process between the agent turn and the `finally` post-step; assert the next `claim_workspace` either
     prunes the dead claim or fails with an actionable message.
   - Spawn-on-retry while the parent's `finally` has already released; assert `transfer_workspace_claim` either
     re-acquires or refuses with a clear error.
   - Two parallel `#git:sase` claims on the same workspace; assert the second blocks or fails fast.

9. Multi-agent xprompt VCS inheritance.
   - One body segment with explicit `#cd:~`, leading multi-agent has `#gh:sase`; assert the explicit ref wins.
   - Inherited ref pointing at a workspace that no longer exists; assert a clear error rather than silent dispatch.

10. ChangeSpec rollback.
    Inject a failure in `append_commits_entry` after `vcs_commit` succeeds; assert that the COMMITS drawer is either
    rolled back or that the inconsistency is surfaced as a workflow error rather than masked by the next run.

11. Non-xprompt method writers.
    Run a VCS xprompt that sets `SASE_COMMIT_METHOD=create_pull_request`, then trigger `fix_hook_runner` /
    `workflows/crs.py` mid-session; assert the conflict is either rejected or recorded in `vcs_intent.json`.

## Hardening Recommendations

### Phase 1: Observability First

This is the highest leverage because it shortens every future debugging session without requiring a semantic redesign.

- Add `SASE_RUN_ID` at workflow launch and persist it everywhere listed above.
- Add `vcs_intent.json` generated from current commit workflow YAML/environment fields.
- Add `vcs_commands.jsonl` behind an env flag like `SASE_TRACE_VCS_COMMANDS=1`, then enable it automatically when
  `SASE_ARTIFACTS_DIR` is set for workflow-launched agents.
- Add `sase debug vcs-xprompt [ARTIFACTS_DIR]` to reconstruct the run from existing and new artifacts.
- Extend `workflow_state.json` with a redacted environment snapshot for known `SASE_*` keys that affect VCS xprompt
  behavior.
- Log a warning at registration when more than one plugin is registered for the same `vcs_*` hook. This costs nothing
  and turns the silent "first plugin wins" into a visible signal.
- Add `sase workspace status` (or fold into `sase debug`) that lists current `WORKSPACE_CLAIMS:` entries with PID
  liveness and age, so stale claims can be triaged without grepping the project file.

### Phase 2: Make Commit Intent Explicit

This aligns with the prior critique but can be incremental.

- Add a `vcs_intent` metadata block to `commit.yml`, `propose.yml`, and `pr.yml`.
- Add an `XPromptTag.vcs_intent` tag.
- Validate at most one `vcs_intent` workflow per prompt segment, mirroring the VCS wrapper validation.
- Move `method -> append context tag` out of `workflow_executor_steps_embedded_expand.py` and into workflow metadata.
- Keep `SASE_COMMIT_METHOD` as compatibility output until stop hooks and skills read `vcs_intent.json` directly.

### Phase 3: Collapse Repeated YAML Plumbing

`commit.yml`, `propose.yml`, and `pr.yml` repeat result-marker reading and metadata emission. Move that into a shared
Python helper or shared workflow step.

Concrete target:

- `sase.scripts.commit_result_report.main(kind=...)`
- returns typed fields for commit/propose/pr;
- fails with an explicit diagnostic when `check_changes.has_changes` was true but neither `commit_result.json` nor a
  retained `commit_state.json` exists.

That makes "hook did not run" and "commit skill failed" visible as workflow failures rather than silent empty metadata.

### Phase 4: Scenario Test Harness

Build a tiny fake workflow executor harness that can run prompt expansion and embedded pre/post steps without invoking a
real LLM or real git. Use fake provider/workspace plugins and a temporary artifacts dir.

The harness should exercise the full contract:

`raw prompt -> parser/default/inheritance -> embedded workflows -> env injection -> fake agent -> stop-hook-like marker
-> commit result report -> final workflow_state`

This is where most regressions will be caught earlier than integration tests.

### Phase 5: Lifecycle Hardening

The deepest source of recurring frustration is workspace state outliving the process that owns it. After Phase 1 makes
this visible, address the substance:

- Tag every claim with the owner PID and start time.
- During `claim_workspace`, prune entries whose owner PID is no longer alive (after a short grace window).
- Make `transfer_workspace_claim` verify the source PID still owns the claim before mutating, and refuse with a clear
  error otherwise.
- Make `release_workspace` idempotent and safe to call from anywhere, including a top-level `atexit` handler in the
  workflow runner. The `try/finally` in `accept` and `rewind` should become the default, not the exception.
- Add a documented `--abort` path for `#sync` that aborts the in-progress rebase/merge cleanly when the loop hits its
  iteration cap, rather than leaving the workspace mid-conflict.

## Suggested Debugging Workflow Until Then

When a VCS xprompt workflow misbehaves, inspect in this order:

1. `workflow_state.json`: did the workflow validate, which step failed, what context was recorded?
2. `embedded_workflows_<step>.json`: did the expected workspace wrapper and commit intent appear?
3. `prompt_step_*.json`: did the prompt step receive `meta_*`, `diff_path`, and response path?
4. `commit_result.json`: did `sase commit` finish tracking?
5. `commit_state.json`: did `sase commit` stop at a resumable conflict?
6. `~/.sase_commit_stop_hook.jsonl`: did the hook run, dedup, detect changes, and emit a block?
7. `~/.sase_git_commit.jsonl`: did the skill wrapper call `sase commit`, and what was the exit code?
8. Provider detection: run `sase debug` once it exists; until then, compare `SASE_VCS_PROVIDER`, repo markers, and
   `detect_vcs()` behavior.

## Bottom Line

The root issue is not that VCS xprompt workflows are inherently wrong. The root issue is that the subsystem uses prompt
syntax as a front door for a distributed state machine, but the state machine is spread across environment variables,
YAML post-steps, hook instructions, provider dispatch, and loosely related artifacts.

The fastest hardening path is:

1. make runs debuggable as one trace;
2. make commit intent a first-class typed artifact;
3. enforce uniqueness and fail-fast contracts;
4. replace repeated YAML result plumbing with a tested helper;
5. add scenario tests that exercise parser, embedded workflow, env, hook, and commit-result contracts together;
6. close the lifecycle gaps: workspace claims with PID-aware pruning, default `try/finally` release, verified
   `transfer_workspace_claim`, and an explicit `#sync` abort path so failures stop leaving the workspace in mid-rebase
   state.

The sub-systems most likely to be hiding the next class of bugs are the parts that fail silently today: provider
plugins returning `(False, ...)` under `firstresult=True`, stop-hook fallbacks that downgrade to "no changes",
diff/COMMITS-drawer writes that succeed-with-empty, and `SASE_COMMIT_METHOD` writers outside the xprompt path. Each of
these warrants both an observability change (so the failure is visible) and a contract change (so it stops happening).
