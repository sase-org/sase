# SASE VCS XPrompt Workflow Critique

Date: 2026-05-02

## Question

Critique SASE's VCS xprompt workflows, justify why they should or should not be x prompts, and recommend an
improvement.

## Current Shape

SASE's VCS xprompts split into five categories, not the two the original framing suggests:

1. **Workspace wrappers** (`vcs` tag, `rollover`): `#git`, `#gh`, `#hg`.
   YAML workflows with `setup`/`prepare`/`checkout` pre-steps, an empty `prompt_part`, and `release`/`diff` post-steps
   in a `finally` block. The `vcs` tag is load-bearing: the embedded-workflow executor runs vcs pre-steps first and vcs
   post-steps last (`workflow_executor_steps_embedded_expand.py:165-172, 293-320`), and validates that at most one
   `vcs`-tagged workflow appears per prompt (`workflow_executor_steps_embedded_expand.py:157-163`). Both `#gh` and
   `#hg` set `wraps_all: true`, which is what gives them outermost-bracket semantics.

2. **Workspace selector** (`vcs` tag only, no `rollover`): `#cd`.
   Resolves a workspace via `workspace_provider`, emits a `_chdir` output, and skips checkout/diff. It deliberately
   does not propagate to follow-up agents because it is a one-shot directory selection, not an enduring VCS context.

3. **Commit intent markers** (`rollover`, no `vcs` tag): `#commit`, `#propose`, `#pr`.
   YAML workflows with a small injected prompt, `environment:` values like `SASE_COMMIT_METHOD`, and post-steps that
   read `commit_result.json` from `SASE_ARTIFACTS_DIR`. The actual mutation path is not in the xprompt. It flows
   through `sase_commit_stop_hook`, `/sase_git_commit` or `/sase_hg_commit`, `sase commit`, `CommitWorkflow`, and VCS
   provider hooks. `#pr` additionally sets `SASE_PR_NAME`, `SASE_BUG_ID`, `SASE_PR_STATUS` from inputs.

4. **Tag-driven context appenders**: `#prdd` (`append_to_commit_and_propose`), `#pr_diff` (`diff_file`).
   These are not user-typed. They are discovered by tag during embedded expansion when a commit-intent workflow runs
   and conditionally append PR/branch context to the agent prompt. `#prdd` is the canonical consumer of
   `append_to_commit_and_propose`: when the current branch is not `main`/`master`, it injects diff and description
   references for the open PR.

5. **Sync and composite VCS workflows** (untagged or domain-tagged): `#sync`, `#new_pr_desc`, `#pr_diff`,
   `#refresh_cl_desc`, `#split`, `#crs`, `#prdd`.
   These are first-class user-invocable xprompts that operate on VCS state but are not commit-intent and not workspace
   wrappers. `#sync` is a HITL conflict-resolution loop (up to 20 iterations) that handles git or hg pulls.
   `#new_pr_desc` and `#refresh_cl_desc` regenerate descriptions from ChangeSpec metadata. `#split` orchestrates
   parent-child CL splitting on Mercurial. `#crs` reads unresolved critique comments and ends with `#propose`. These
   are the genuine "agent does multi-step VCS work" cases — and they are well served by being xprompt workflows.

Relevant implementation points:

- Built-in intent xprompts: `src/sase/xprompts/commit.yml`, `src/sase/xprompts/propose.yml`,
  `src/sase/xprompts/pr.yml`.
- Built-in workspace wrappers: `src/sase/xprompts/git.yml`, `src/sase/xprompts/cd.yml`.
- Plugin wrappers/context: `../sase-github/src/sase_github/xprompts/gh.yml`,
  `../retired Mercurial plugin/src/retired_mercurial_plugin/xprompts/hg.yml`,
  `../sase-github/src/sase_github/xprompts/prdd.yml`,
  `../retired Mercurial plugin/src/retired_mercurial_plugin/default_config.yml`.
- Embedded workflow environment injection and commit-specific append logic:
  `src/sase/xprompt/workflow_executor_steps_embedded_expand.py:157-269`.
- XPromptTag enum and tag lookup: `src/sase/xprompt/tags.py:12-147`.
- Stop hook: `src/sase/scripts/sase_commit_stop_hook.py`.
- Commit CLI and orchestration: `src/sase/main/cl_handler.py`, `src/sase/workflows/commit/workflow.py`.
- Provider dispatch: `src/sase/vcs_provider/plugins/_git_commit_dispatch.py`,
  `../sase-github/src/sase_github/plugin.py`, `../retired Mercurial plugin/src/retired_mercurial_plugin/plugin.py`.
- Other commit-intent injection sites (not just xprompts): `src/sase/axe/fix_hook_runner.py` sets
  `SASE_COMMIT_METHOD=create_proposal`; mentor and CRS workflows set it via `workflows/crs.py`. Direct
  `sase commit --type ...` invocation also bypasses xprompt entirely and is the path the docs recommend for scripted
  use.
- Design docs: `docs/xprompt.md`, `docs/workflow_spec.md`, `docs/commit_workflows.md`, `docs/vcs.md`.

## Should These Be XPrompts?

### Workspace wrappers should stay xprompt workflows

`#git`, `#gh`, `#hg`, and `#cd` are good fits for embeddable xprompt workflows.

They are selected as part of prompt composition, not as standalone commands. A user naturally writes prompts like
`#gh:sase #commit fix the failing test`, where the VCS wrapper establishes which workspace the agent should operate in
and the rest of the prompt describes the work. The xprompt workflow layer is also the right place to run pre-agent setup
and post-agent cleanup around the model turn: checkout, sync, workspace release, and diff artifact capture.

The empty `prompt_part` is slightly awkward, but it is semantically correct: the workflow contributes execution context
rather than natural-language text. The `vcs` tag gives the executor the ordering rule this kind needs. This is exactly
what embeddable YAML workflows are good at.

Recommended stance: **keep them as xprompt workflows**, but continue moving bulky shell/Python bodies into provider or
script modules. `#git` and `#gh` still duplicate a fair amount of checkout/sync/diff behavior, and that behavior is more
testable in Python modules than in long inline YAML steps.

### Commit intent markers should be xprompt front doors, not VCS workflow engines

`#commit`, `#propose`, and `#pr` are valid as xprompt references because they affect the agent-facing contract:

- They inject "make changes, but do not commit/branch/PR yourself."
- They compose inline with workspace wrappers and user prose.
- They configure the stop-hook/skill/CLI path for the chosen commit outcome.
- They let provider plugins append VCS-specific context (`append_to_commit_and_propose`, `append_to_pr`) without the
  user naming plugin-specific prompts.

They should **not** own the actual VCS mutation workflow. That logic is already better placed in `sase commit` and
provider hooks because it needs typed validation, checkpoint/resume, ChangeSpec updates, bead handling, provider-specific
dispatch, and consistent behavior across agent runtimes. Keeping mutation in `CommitWorkflow` is the correct direction.

Recommended stance: **keep them as xprompt front doors**, but make them less like ad hoc workflows. They are currently
using the workflow system mostly to set hidden process state and read a result marker. That is a smell: the role is
"commit intent", not "multi-step agent workflow".

### `#pr` is semantically too provider-specific

`#pr` sets `SASE_COMMIT_METHOD=create_pull_request`, but the same method creates a Google CL in the Mercurial plugin.
The docs already describe `create_pull_request` as the shared method, while the actual concept is "create a new reviewed
change". That naming leaks GitHub terminology into Mercurial behavior.

Recommended stance: **keep `#pr` as an alias for GitHub muscle memory**, but introduce a VCS-agnostic `#change` intent
for the canonical operation. If the Google plugin wants a user-facing `#cl` alias, it should point to the same intent.
The provider should decide whether the result is a PR, CL, or plain branch.

## Problems With The Current Design

### 1. Intent is encoded as stringly process environment

The commit intent is `SASE_COMMIT_METHOD` plus related variables (`SASE_PR_NAME`, `SASE_BUG_ID`, `SASE_PR_STATUS`).
This works because xprompt environment variables persist into the agent, stop hook, post-steps, and skill invocation.
It is also hard to reason about:

- The state is global to the process once injected.
- There is no single structured record saying "this run selected commit intent X with args Y".
- Conflicting `#commit #pr` style prompts are not rejected by a first-class uniqueness rule. Today, both workflows
  expand and `SASE_COMMIT_METHOD` is set by whichever runs second (last-write-wins on env injection); no error is
  surfaced and the resulting behavior depends on embedded-workflow ordering. Contrast with the `vcs` tag, which
  *is* validated to at most one per prompt.
- Generic xprompt expansion code knows about commit method names so it can append plugin-specific context.

The CLI has a useful guard that rejects conflicting `--type` vs `SASE_COMMIT_METHOD` (`main/cl_handler.py`), but the
upstream selection remains hidden mutable state — and the env var is also written from non-xprompt sites
(`axe/fix_hook_runner.py`, `workflows/crs.py`), so there is no single chokepoint to reason about either.

### 2. The xprompt executor contains commit-specific routing

`workflow_executor_steps_embedded_expand.py:245-269` maps `create_commit` and `create_proposal` to
`append_to_commit_and_propose`, and `create_pull_request` to `append_to_pr`. That puts VCS commit semantics inside the
generic xprompt expansion engine.

The tag lookup itself is a good mechanism — and notably, it is dynamic: any plugin can ship a workflow tagged
`append_to_pr` or `append_to_commit_and_propose` and it will be discovered automatically by `get_by_tag()`
(`tags.py:74-119`). The only hard-coded part is the two-line `method → tag` switch. The fix is small: have the intent
workflow declare its own append-tag (see Recommendation), so the executor stays method-agnostic.

`get_by_tag()` already supports a `vcs_hint` for plugin disambiguation, which is the right primitive to build the
typed intent layer on top of.

### 3. The three intent xprompts duplicate plumbing

`commit.yml`, `propose.yml`, and `pr.yml` repeat the same `check_changes`, `_has_commit_result`, result-reading, and
metadata-emitting structure. The differences are mostly method, names, and emitted metadata fields.

Some duplication is acceptable in YAML, but this is not user-facing workflow logic. It is adapter plumbing around
`commit_result.json`, so it should be shared.

### 4. The documented fail-fast behavior is stronger than the YAML

`docs/commit_workflows.md` says missing `commit_result.json` should fail explicitly when post-steps run. The current
xprompts mostly print `success=false` or `{}` when the result file is missing. The stop hook usually prevents that state
when uncommitted changes remain, but the xprompt post-step itself is not a strong fail-fast boundary.

That makes debugging harder in edge cases: disabled hooks, unsupported runtimes, hook deduplication mistakes, or a failed
agent-side commit skill can leave the xprompt metadata path looking like a no-op rather than an explicit workflow
failure.

### 5. Test coverage is uneven across the routing layer

There are tests for rollover-tag filtering (`tests/test_xprompt_tags_rollover.py`), per-step embedded loading
(`tests/test_embedded_workflows_per_step.py`), post-step collection ordering, and embedded env injection. There are
no tests covering:

- The `method → append-tag` switch in `workflow_executor_steps_embedded_expand.py:245-269`, including the case where
  no plugin provides a matching tagged workflow.
- The behavior when both `#commit` and `#pr` (or `#commit` and `#propose`) appear in one prompt — currently undefined
  by design.
- The fail-fast contract for missing `commit_result.json` (see #4).

Adding the typed intent layer below would make all three of these directly testable, since intent selection becomes
a discrete step rather than emergent env-var behavior.

### 6. `#sync` and `#cd` blur the "VCS xprompt" boundary

`#sync` is a HITL conflict-resolution loop that is structurally a VCS workflow but carries no `vcs` tag and no
`rollover` tag. It does not fit either the workspace-wrapper or commit-intent shape. It is in fact the strongest
example of a workflow that genuinely belongs in xprompt YAML — it has agent steps, repeated turns, and per-VCS
branching that would be awkward to express in `sase commit` or a provider hook.

`#cd` has the `vcs` tag (so it competes with `#git`/`#gh`/`#hg` for the at-most-one-vcs slot) but no `rollover` tag
(so it does not propagate). This is intentional but undocumented. Worth surfacing in `docs/vcs.md` so users can reason
about why `#cd #commit fix bug` works but `#cd` does not carry through to a follow-up agent.

### 7. Commit method names are implementation-oriented

`create_commit`, `create_proposal`, and `create_pull_request` are provider dispatch methods. They are not the best
surface vocabulary:

- `create_commit` means "append/amend the current reviewed change" for Mercurial, but "commit on current branch" for
  Git.
- `create_pull_request` means "new reviewed change", not necessarily a pull request.
- `create_proposal` is a SASE-specific parking operation that only makes sense with ChangeSpec tracking.

The provider methods can keep those names internally, but the prompt/user-facing layer should use intent names:
`commit`, `propose`, `change`.

## Recommendation

Introduce a first-class **VCS intent** layer, while keeping xprompt references as the user-facing syntax.

The design goal is to preserve the good part of the current system: users can write `#gh:sase #commit ...`, plugins can
contribute provider-specific context, and all actual mutations go through `sase commit`. The change is to replace
implicit environment state and hard-coded executor routing with structured intent metadata.

### Proposed model

Add a small typed metadata block for intent xprompt workflows:

```yaml
tags: rollover, vcs_intent

vcs_intent:
  name: commit
  method: create_commit
  append_context_tag: append_to_commit_and_propose
  result_kind: commit

environment:
  SASE_COMMIT_METHOD: create_commit # compatibility only
```

For a new reviewed change:

```yaml
tags: rollover, vcs_intent

vcs_intent:
  name: change
  method: create_pull_request
  append_context_tag: append_to_pr
  result_kind: change
  required_inputs: [name]

environment:
  SASE_COMMIT_METHOD: create_pull_request # compatibility only
```

Then teach embedded expansion to:

1. Collect workflows tagged `vcs_intent`.
2. Reject more than one intent in a prompt — symmetric with the existing at-most-one-`vcs` validation, which closes
   the current `#commit #pr` ambiguity.
3. Render the prompt text as it does today.
4. Append provider-specific context from `vcs_intent.append_context_tag`, rather than hard-coding method names.
5. Write a durable artifact such as `$SASE_ARTIFACTS_DIR/vcs_intent.json`:

```json
{
  "intent": "change",
  "method": "create_pull_request",
  "args": { "name": "my_feature", "bug_id": 123 },
  "source_workflow": "change"
}
```

The stop hook should prefer this artifact when present and fall back to `SASE_COMMIT_METHOD` for compatibility. The
commit skill can still call `sase commit` exactly as today, but the hook message can be generated from structured intent
data instead of reconstructing meaning from environment variables.

### Near-term implementation steps

1. Add `XPromptTag.vcs_intent`.
2. Add optional workflow metadata parsing for `vcs_intent`.
3. Refactor `commit.yml`, `propose.yml`, and a new `change.yml` to use `vcs_intent`.
4. Keep `pr.yml` as a compatibility wrapper or alias to `change.yml`; optionally let provider plugins expose `#cl`.
5. Move duplicated result-marker reading into a shared imported workflow step or Python helper, e.g.
   `sase.workflows.commit.result_marker`.
6. Make missing `commit_result.json` an explicit failure when the intent expected a result and local changes existed.
7. Keep setting `SASE_COMMIT_METHOD` for one compatibility window, but document it as a legacy transport.

### Why this is better

- **Clearer type boundary**: xprompt references express user intent; `CommitWorkflow` executes mutations; VCS providers
  implement backend specifics.
- **Less executor coupling**: generic xprompt expansion no longer needs to know that `create_pull_request` maps to
  `append_to_pr`.
- **Better diagnostics**: the artifact can be shown in logs, workflow metadata, and failure messages.
- **Conflict prevention**: a first-class `vcs_intent` tag makes "only one commit intent per prompt" enforceable.
- **Provider-neutral vocabulary**: `#change` works for GitHub PRs and Google CLs without forcing either backend's terms
  onto the other.
- **Backward compatible**: `#commit`, `#propose`, `#pr`, `SASE_COMMIT_METHOD`, and the existing skill contract can keep
  working during migration.

## Final Position

The VCS workspace wrappers (`#git`, `#gh`, `#hg`, `#cd`) should remain xprompt workflows. They are genuinely
prompt-composition-time execution wrappers and the `vcs` tag plus `wraps_all: true` already give them correct
ordering semantics.

The composite VCS workflows (`#sync`, `#new_pr_desc`, `#refresh_cl_desc`, `#split`, `#crs`) should also remain
xprompt workflows. They are the exact case xprompts were designed for: multi-step agent work over VCS state with
HITL turns. No changes needed here beyond a `vcs_workflow` tag for discovery and documentation.

The commit/propose/new-change operations should remain invokable through xprompt syntax, but only as thin, typed
intent markers backed by a `vcs_intent` tag and a `vcs_intent.json` artifact. The current implementation has the
right architectural instinct by moving real VCS mutation into `sase commit`; the improvement is to make that intent
explicit and structured instead of encoding it as environment variables plus commit-specific logic inside the generic
xprompt executor.

The `append_to_*` mechanism is already a solid dynamic-tag system — the only fix it needs is for the intent workflow
to declare its own append-tag rather than the executor hard-coding a `method → tag` switch.
