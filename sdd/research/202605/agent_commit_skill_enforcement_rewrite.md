# Agent Commit Skill Enforcement Rewrite

Date: 2026-05-13

## Question

If SASE were rewritten from scratch, what is the best way to ensure agents that make file changes always commit through
their `/sase_git_commit` skill?

## Short Answer

Make commit enforcement a first-class part of the SASE agent run lifecycle, not a provider-native stop-hook side effect.

The simplest reliable design is:

1. SASE launches an agent run with a structured `RunContext`.
2. The agent may edit files, but prompt instructions tell it not to run raw VCS commit commands.
3. When the model turn exits, SASE itself checks the workspace for changes.
4. If the workspace is dirty, SASE starts an in-band finalization turn that contains only the commit-skill instruction:
   use the resolved VCS skill, e.g. `/sase_git_commit`, with the selected commit intent.
5. SASE repeats the finalization check until the workspace is clean, the commit result marker is written, or the agent
   explicitly declares the changes are not its own.
6. `sase commit` remains the only supported mutation path behind the skill, and it writes durable commit/result markers
   that the finalizer verifies.

Native Claude/Gemini/Qwen/Codex hooks can still exist as optional adapters for interactive UX, but they should not be
the source of truth. The source of truth should be a SASE-owned post-run finalizer that runs uniformly for every
runtime.

## Why The Current Shape Feels Complicated

The current implementation spreads one conceptual requirement across too many surfaces:

- The xprompt intent workflows set `SASE_COMMIT_METHOD` and related environment variables.
- Generic embedded xprompt expansion contains commit-specific routing from `SASE_COMMIT_METHOD` to append-context tags
  (`workflow_executor_steps_embedded_expand.py:272-285`).
- `sase_commit_stop_hook` resolves changed files, chooses `/sase_<provider>_commit`, emits different block shapes for
  Codex, Gemini/Qwen, and Claude, manages one-shot markers, and relies on runtime-native hook delivery
  (`sase_commit_stop_hook.py:51-84`, `150-166`).
- Codex already needs a SASE-managed fallback after a successful subprocess turn because native stop-hook delivery can
  be absent (`codex.py:372-469` and `sdd/tales/202605/codex_commit_stop_hook_fallback.md`).
- The commit CLI resolves method from either `--type` or `SASE_COMMIT_METHOD`, then builds a dict payload
  (`cl_handler.py:60-104`).
- `CommitWorkflow` handles validation, beads, plans, precommit, PR name suffixing, parent detection, diff capture,
  checkpoints, provider dispatch, result markers, COMMITS entries, and ChangeSpec creation
  (`workflow.py:80-226`).
- Git dispatch performs the actual staging, committing, bead amend, push, proposal save/clean, and PR branch creation
  (`_git_commit_dispatch.py:147-260`).

Most of those responsibilities are legitimate. The complicated part is the enforcement path: "make sure the agent
commits" is currently delegated to runtime-specific stop hooks plus environment state, with a separate Codex fallback
because the hook is not dependable enough as the only gate.

## Current Evidence

### A wrapper layer already exists but is host-wide, not per-run

`/sase_git_commit` is currently a thin shell wrapper (`src/sase/scripts/sase_git_commit`) that:

- Appends a `script_start` / `commit` / `script_exit` event triple to `~/.sase_git_commit.jsonl`.
- Delegates argv to `sase commit "$@"`.
- Records the post-commit short hash on success.

This is useful for incident forensics, but it does not satisfy the "did this run use the skill" question, because the
log is a single host-wide JSONL with no `SASE_RUN_ID` correlation, no artifacts-dir path, and no per-session marker.
Any rewrite should keep this wrapper shape but write a per-run `commit_skill_invoked.json` into `SASE_ARTIFACTS_DIR`
alongside the existing JSONL.

The corresponding hook log `~/.sase_commit_stop_hook.jsonl` (`sase_commit_stop_hook.py:17-35`) has the same shape
problem: structured events, host-wide file, no correlation ID.

### Stop hook is an adapter, not a durable finalizer

`build_commit_details()` inspects the workspace, resolves a commit skill, reads `SASE_COMMIT_METHOD`, adds bead/name
instructions, and returns the message that blocks the agent (`sase_commit_stop_hook.py:51-84`). `_emit_block()` then
has runtime-specific transport behavior: Codex gets `{"decision": "block"}`, Gemini/Qwen get
`{"decision": "deny"}`, Claude gets stderr plus exit 2 (`sase_commit_stop_hook.py:150-166`).

This is useful adapter code, but it means the invariant depends on each runtime delivering its hook correctly.

### Codex fallback proves SASE needs a supervisor-owned path

`CodexProvider.invoke()` now calls `_maybe_run_commit_fallback_turn()` after a successful Codex turn
(`codex.py:372-382`). That helper reuses `build_commit_details()`, creates fallback/native one-shot markers, and runs a
second Codex subprocess turn containing the stop-hook details when changes remain (`codex.py:384-469`).

The plan that introduced this fallback says the target Codex session ended with uncommitted changes, no hook prompt, and
no `~/.sase_commit_stop_hook.jsonl` entry near the end time. The root cause was missing native hook delivery, not a
failed commit hook.

This is the key architectural lesson: SASE can enforce commits reliably only from the thing that owns the agent
subprocess lifecycle.

### Commit intent is still hidden mutable process state

The xprompt executor injects workflow `environment:` values into `os.environ` so agents, hooks, and post-steps can see
them (`workflow_executor_steps_embedded_expand.py:227-233`). It then special-cases `SASE_COMMIT_METHOD` to append
provider-specific context (`workflow_executor_steps_embedded_expand.py:272-285`).

The previous VCS xprompt critique already recommended a typed `vcs_intent` metadata block and a `vcs_intent.json`
artifact instead of relying on environment variables as the primary transport. That recommendation still applies here.

### `/sase_git_commit` is a prompt contract, not an enforcement boundary

The generated skill source tells agents that `/sase_git_commit` is the only way they should commit git repos and then
instructs them to call `sase commit -M ... -f ...`. The CLI is the actual executable boundary. If exact skill usage is
important, a rewrite should make the skill call a dedicated wrapper such as `sase skill-commit git ...` or
`sase_git_commit ...` that writes a per-run `commit_skill_invoked.json` marker before delegating to `sase commit`.

Without that marker, SASE can verify "a supported commit happened" but cannot reliably distinguish "the agent used the
skill" from "the agent manually ran the same CLI command."

### Resolution of the commit skill is unvalidated

`_resolve_commit_skill()` (`sase_commit_stop_hook.py:251-260`) builds `/sase_<provider_token>_commit` purely by string
substitution. It never checks that the runtime actually has that skill installed (a misconfigured runtime + VCS combo
silently produces `/sase_<unknown>_commit`). The `generated_skills.md` memory makes it clear that not every runtime
has every commit skill — e.g. Claude/Codex do not ship `/sase_hg_commit`. A rewrite should resolve the skill against
the active LLM provider's installed skill set, not against a string template, and fail loudly if the resolved skill is
absent.

### Diff detection silently degrades

`_get_changed_files()` (`sase_commit_stop_hook.py:304-335`) has three layered fallbacks that all swallow exceptions
(documented in `sdd/research/202605/vcs_xprompt_hardening_research.md` §6). The pathological combinations are:

- A provider that implements only `diff()` (not `diff_with_untracked()`) plus a working tree whose only changes are
  new files — reported as "no changes", agent exits without committing.
- A provider that raises inside `diff_with_untracked()` — caught by a bare `except Exception`, reported as "no
  changes".
- The fallback `has_local_changes()` path that surfaces a synthetic file path
  `(unable to list changed files for this VCS provider)` — looks like a real file in the JSONL.

Any "supervisor-owned finalizer" must treat detection failure as failure-to-prove-clean rather than silently passing.
A non-`True` answer from `has_local_changes()` is not the same as a confirmed clean tree.

### VCS provider plugin chain hides errors

Every VCS hookspec in `_hookspec.py` uses `@hookspec(firstresult=True)`. Plugins return `(False, "<stderr>")` rather
than `None` on failure, so pluggy stops at the first registered plugin even when it fails. The finalizer in a rewrite
should not assume "provider dispatch returned False" means "no commit happened"; it must reconcile dispatch return
value with a HEAD-hash check.

### Commit method is written from more than one site

Outside xprompts, `axe/fix_hook_runner.py` and `workflows/crs.py` also set `SASE_COMMIT_METHOD=create_proposal`
directly. There is no conflict detection between the original xprompt-written method and these later writes — the
CLI guard catches only `--type` vs env disagreement at the moment of `sase commit` invocation. A typed
`vcs_intent.json` artifact would make conflicting intent rewrites detectable instead of last-write-wins.

### There is already an escape hatch

`SASE_DISABLE_COMMIT_STOP_HOOK` short-circuits the stop hook (`sase_commit_stop_hook.py:372-374`) and the Codex
fallback (`codex.py:398-400`). A rewrite must keep this flag, or an equivalent, because:

- Non-mutating workflows (`#sync` conflict resolution, `#crs` critique loops) deliberately allow remaining unstaged
  state across turns.
- Some workflows perform their own commit dispatch and must not be double-finalized.
- Local debugging / fixture runs benefit from an off switch.

Today the flag disables enforcement entirely. A supervisor-owned finalizer should expose finer-grained
configuration: per-workflow `vcs_intent.finalize: false`, per-run `--no-finalize`, and a global `SASE_DISABLE_…`
mirror. The current single boolean is too coarse once the finalizer becomes the only enforcement path.

### `_post_commit_bead_amend` is a SASE-initiated commit

`vcs_create_commit` in `_git_commit_dispatch.py` runs `_post_commit_bead_amend()` after the primary commit, which
executes `git add <bead-pathspec>` and `git commit --amend --no-edit --quiet`. This produces a second commit-shaped
event with no direct mapping to the agent's skill invocation. The finalizer's "detect commits made outside
`sase commit`" rule has to know that amends initiated *inside* `sase commit` are legitimate. The clean way is to
emit a single `commit_result.json` whose `commit_hashes: []` covers the full set (commit + amend), and to gate
violation detection on hashes recorded there.

## Recommended From-Scratch Design

### 1. RunContext is the primary contract

Every SASE-launched agent should receive a structured run context owned by the supervisor:

```json
{
  "run_id": "260513_103000",
  "workspace": "/path/to/workspace",
  "vcs_provider": "git",
  "commit_skill": "/sase_git_commit",
  "commit_intent": {
    "name": "commit",
    "method": "create_commit",
    "args": {}
  },
  "artifacts_dir": "~/.sase/agents/.../artifacts"
}
```

This replaces environment variables as the canonical state. Environment variables can remain compatibility mirrors, but
the finalizer reads the context artifact.

### 2. VCS intent is typed

Commit/propose/change xprompts should be thin intent markers:

```yaml
tags: rollover, vcs_intent

vcs_intent:
  name: commit
  method: create_commit
  append_context_tag: append_to_commit_and_propose
  result_kind: commit
```

The xprompt executor should reject more than one `vcs_intent` in a prompt, append provider context from the declared
`append_context_tag`, and write `vcs_intent.json`. This removes the current hard-coded method-to-tag switch and closes
the ambiguous `#commit #pr` case.

### 3. Agent supervisor owns commit finalization

After every SASE-launched agent turn, the supervisor should run this state machine:

```text
agent_turn_finished
  -> inspect workspace changes
  -> if clean: finish
  -> if dirty and no commit intent: emit finalization turn with default create_commit
  -> if dirty and commit intent exists: emit finalization turn with resolved skill + intent args
  -> after finalization turn: inspect again
  -> if clean and commit_result.json exists when expected: finish
  -> if dirty and agent declared not-my-changes: record waiver and finish
  -> if dirty after max attempts: mark run blocked with changed-file list
```

This is the generalized version of the Codex fallback. It should live above all LLM providers, not inside only Codex.
The provider-specific pieces become "how do I run one more turn?" rather than "does this provider's native hook fire?"

### 4. Native hooks become optional delivery adapters

Keep native hook configuration for interactive runtimes because it can interrupt earlier and show familiar UX. But treat
it as a best-effort adapter:

- It calls the same `CommitFinalizer.build_instruction(run_context, changes)` helper.
- It writes the same dedup marker.
- It never owns the invariant.
- If it does not fire, the supervisor finalizer still runs after the subprocess exits.

This eliminates the need for one-off fallback designs per runtime.

### 5. Commit skill invocation gets a durable marker

If the product requirement is "must use `/sase_git_commit`", the skill should not be only markdown instructions. It
should call a tiny wrapper with the run id:

```bash
sase skill-commit git --run-id "$SASE_RUN_ID" -M commit_message.md -f file1.py
```

The wrapper should:

1. Resolve and validate the run context.
2. Write `commit_skill_invoked.json` with provider, skill, method, files, cwd, and timestamp.
3. Delegate to `sase commit`.
4. Let `sase commit` write `commit_result.json`.

The finalizer can then verify both:

- the skill path was invoked for this run;
- the commit workflow completed and the workspace is clean.

### 6. `sase commit` stays the one mutation engine

Do not move VCS mutation into xprompts or native hooks. `CommitWorkflow` is doing the right kind of work: payload
validation, bead/plan handling, precommit, diff capture, checkpoint/resume, provider dispatch, ChangeSpec/COMMITS
tracking, and result markers. From scratch, I would keep those stages but split the data model:

- `CommitRequest`: user/agent intent (`method`, `message`, `files`, `name`, `selection_mode`, etc.).
- `CommitContext`: run/project state (`cwd`, `run_id`, `artifacts_dir`, `project_file`, `cl_name`, `bead_id`,
  `plan_path`).
- `CommitCheckpoint`: persisted resume state.
- `CommitResult`: normalized provider result plus tracking IDs.

That keeps provider hooks from receiving a loose mixed dict of public and internal fields.

### 7. Raw VCS commits are discouraged and detectable

Preventing an agent with shell access from ever typing `git commit` is hard without a restrictive command proxy, and the
current SASE trust model gives agents broad shell access. From scratch, I would not build a brittle shell-command
blocklist first.

Instead:

- Prompt instructions say raw VCS commits are forbidden.
- The finalizer checks dirty state and result markers.
- `sase commit` writes a result marker with the HEAD commit hash.
- The supervisor can detect a new HEAD commit without `commit_result.json` and mark it as a policy violation.
- A later hardening phase can route shell through a command policy that blocks `git commit`, `git push`, `gh pr create`,
  `hg commit`, and similar commands unless the process is `sase commit`.

This gives enforcement and diagnostics without coupling correctness to shell parsing.

## Alternative Enforcement Seams

A from-scratch design has more than one place to put the enforcement logic. Each seam fires earlier in the cycle and
catches a different class of failure. The supervisor-owned finalizer described above is the load-bearing one, but a
rewrite should also decide which complementary seams to enable.

### Seam A — Pre-tool-use shell-command policy

Runtimes that expose pre-tool-use hooks (Claude `PreToolUse`, Gemini/Qwen equivalent, Codex `before_tool_call`, and
opencode's tool gating) can intercept shell invocations *before* they execute. A SASE-managed policy could:

- Block `git commit`, `git push`, `gh pr create`, `hg commit`, and `hg amend` when invoked by the agent.
- Whitelist process trees rooted at `sase commit` so the legitimate workflow continues to function.
- Surface the block to the agent with a structured instruction to use `/sase_git_commit` instead.

This is the only seam that prevents a raw `git commit` from happening in the first place. Without it, the finalizer
can detect a policy violation only retroactively (new HEAD without `commit_result.json`), which is useful for audit
but does not roll the commit back. Trade-off: pre-tool hooks are runtime-specific, so they re-introduce the same
fragility as the current stop hook unless the supervisor finalizer remains the source of truth and the pre-tool hook
is treated as an optional adapter.

### Seam B — Per-edit / post-tool-use hook capture

Most runtimes also expose post-edit hooks (Claude `PostToolUse` on `Edit`/`Write`, opencode `tool_complete`, Gemini's
edit confirmation hook). A SASE-managed post-edit hook could:

- Maintain an in-memory list of paths the agent has edited during the turn.
- Record those edits to `agent_edits.jsonl` in the artifacts dir, with timestamps and tool-call IDs.
- Allow the finalizer to compare *agent-attributed edits* with *VCS-detected dirty paths* — closing the "did the
  agent make these changes or were they pre-existing" question more cleanly than asking the model to answer it.

This makes the "not-my-changes" waiver inferable rather than self-reported, which is faster and more reliable. The
finalizer can default to "agent made edits → must commit through skill" without an extra turn.

### Seam C — Sandbox / overlayfs snapshot

Stronger isolation: launch the agent inside a workspace overlay (Linux `overlayfs`, container, or `git worktree` with
a sentinel commit) so SASE can observe the exact set of mutations independent of VCS provider behavior. This works
even when the agent reaches outside the working tree or modifies files the VCS does not track.

Cost: setup complexity, slower launches, breaks tools that expect a real path. Recommended only if the trust model
tightens; for the current open-shell trust model, Seams A + B + the supervisor finalizer are the right combination.

### Recommended seam composition

1. **Always on**: supervisor-owned finalizer (Section 3 above).
2. **Always on, best-effort**: per-edit hook capture (Seam B) — primary mechanism for attributing changes to the
   agent so the finalizer does not need to ask the model.
3. **Optional, opt-in via config**: pre-tool shell-command policy (Seam A) — for stricter deployments, environments
   that share workspaces, or compliance-driven setups.
4. **Out of scope for V1**: filesystem-overlay sandboxing (Seam C).

## Reliability and Edge Cases

The current Codex fallback proves how much edge-case logic the finalizer has to carry. The following are concrete
cases a rewritten finalizer must handle correctly; the existing implementation handles some, misses others.

### Sub-agent / multi-turn workflows

Several SASE workflows make commits across multiple agent turns:

- `#sync` runs a conflict-resolution agent loop up to 20 iterations (`xprompts/sync.yml`).
- `#crs` ends with `#propose` after multiple turns of comment-resolution.
- `#split` orchestrates parent/child CL splitting.
- Spawn-on-retry (`run_agent_retry_spawn.spawn_retry_agent`) transfers an in-flight workspace claim to a new agent
  process.

The finalizer must distinguish "agent turn ended, workflow continues" from "workflow ended, working tree should be
clean". The cleanest contract is: `RunContext.finalize_policy ∈ {"per_turn", "on_workflow_complete", "never"}`,
default `per_turn`, and `#sync`/`#crs` set `on_workflow_complete` in their `vcs_intent` metadata. Without an explicit
policy, the finalizer either forces premature commits in mid-workflow turns or skips them entirely after the workflow
ends.

### Provider sub-agents

Claude's `Task` tool and similar provider sub-agents can edit files without producing a `Stop` event in the same
shape as the top-level agent. The current stop hook fires only at the outermost session boundary. The finalizer
should run after the parent agent's invoke completes, regardless of how many internal sub-agent turns happened, and
the per-edit hook (Seam B) should capture sub-agent edits when the runtime exposes them.

### Re-entrant finalizer turns

If the finalization turn itself edits files (because the agent decides the commit needs accompanying changes), the
finalizer must run again rather than declaring success on a still-dirty tree. The existing one-shot marker
(`fallback_marker_path`, `native_marker_path`) is the wrong primitive for this — it prevents re-runs even when re-runs
are correct. The rewrite should use bounded re-entrancy: up to N finalization passes per workflow turn (default 2),
then block the run if still dirty.

### Mid-run process death

If the agent process is killed between the model turn and finalization, the workspace can be left dirty with no
record. The finalizer should be invokable from an outer scope (Python `atexit`, supervisor `try/finally`) and idempotent.
The same applies to spawn-on-retry: the new agent process must inherit not just the workspace claim but the finalize
intent, so the dirty state is resolved by the child rather than silently forgotten.

### Detection failure ≠ clean tree

As noted under Current Evidence: `provider.diff_with_untracked()` not implemented, `provider.diff()` ignoring
untracked, `has_local_changes()` raising — all currently degrade to "no changes". The rewrite's contract:

- `is_clean(workspace) → Clean | Dirty(files) | Unknown(reason)`.
- `Unknown` blocks the run, surfaces a diagnostic, and does not satisfy the finalizer.

### Workflow precommit dirties the tree

`CommitWorkflow.run_precommit(cwd)` (`workflow.py:111-113`) executes `precommit_command` (e.g. `just fix`) before
dispatch. The agent's commit skill turn therefore must tolerate the working tree being modified by SASE itself before
the commit fires. The finalizer must use `commit_result.json`'s recorded commit hashes (including the bead-amend
hash) as the success signal, not a post-commit working-tree diff alone.

### Bead amend produces a second commit

`_post_commit_bead_amend` creates a `git commit --amend` after the primary commit. The finalizer's policy-violation
detection rule ("new HEAD without `commit_result.json`") must read the full commit-hash list out of
`commit_result.json`, including the amend hash. Recording a single hash is insufficient.

### `create_proposal` does not produce a commit

For `create_proposal`, the working tree is cleaned via `provider.clean_workspace()` and the diff is parked into a
proposal file. There is no HEAD movement. The finalizer's success condition must depend on `result_kind` from the
intent: `commit` → expect new HEAD; `proposal` → expect saved proposal artifact and clean tree; `change` (PR/CL) →
expect new branch with at least one commit.

### Hooks dedup across workflow runs

The current native-marker dedup (`native_marker_path`, `fallback_marker_path`) keys off `SASE_AGENT_TIMESTAMP`. The
rewrite's run id should be the same key, and the finalizer should write a fresh per-run marker that intentionally
ignores host-wide markers — otherwise back-to-back runs in the same shell session can suppress legitimate finalize
turns.

### Skills that legitimately write files but don't commit

`/sase_plan` writes a plan markdown file; `/sase_questions` may write transcripts; `/sase_artifact` materializes SDD
artifacts. Some of these are intentionally committed later in the workflow, not at the end of the current turn.
`RunContext.finalize_policy` plus `vcs_intent` metadata is enough to model this, but the rewrite must enumerate the
non-commit-producing skills so a default `per_turn` policy does not force every plan-only turn to commit.

## Interaction With Adjacent Subsystems

A clean rewrite cannot ignore that commit enforcement sits in the middle of several other in-flight redesigns.
Coordinating with them keeps the change set small.

### `vcs_intent` typed metadata (recommended in `vcs_xprompt_workflows_critique.md`)

That research argues for a `vcs_intent` workflow tag, an `XPromptTag.vcs_intent` enum value, and a
`vcs_intent.json` artifact emitted by the embedded-workflow expansion stage. The finalizer reads exactly that
artifact. The two designs share an artifact and should land together.

### `SASE_RUN_ID` correlation (recommended in `vcs_xprompt_hardening_research.md`)

The hardening research recommends adding a single run id to `workflow_state.json`, `embedded_workflows*.json`,
`prompt_step_*.json`, stop-hook JSONL, commit-wrapper JSONL, `commit_state.json`, and `commit_result.json`. The
finalizer's `commit_skill_invoked.json` and `vcs_intent.json` should adopt the same field. Today `SASE_AGENT_TIMESTAMP`
already plays this role informally (Codex fallback uses it) — formalize it.

### `--staged` commit selection (recommended in `staged_commit_skill_support.md`)

Staged commits intentionally leave unstaged work behind. The finalizer's "clean tree" success condition becomes
"no staged changes remain" for staged-mode commits. The simplest path is for `sase commit --staged` to write
`commit_result.json` with `selection_mode: "staged"` and `remaining_unstaged_files: [...]`, and for the finalizer to
treat that as a successful terminal state.

### Spawn-on-retry workspace transfer

`spawn_retry_agent` (`run_agent_retry_spawn.py`) and `transfer_workspace_claim` already implement supervisor-side
state transfer. The finalizer should slot into the same lifecycle: when a parent is being respawned, the parent's
unfinished finalize obligation transfers along with the workspace claim, so the new child sees `RunContext.must_finalize = true`.

### Plugin firstresult ambiguity

Recommend logging-at-registration of multiple plugins per `vcs_*` hook (already proposed in the hardening research).
The finalizer should not silently rely on whichever plugin pluggy returned first.

## Cost and UX Trade-offs

A supervisor-owned finalizer is not free.

| Concern | Trade-off |
| --- | --- |
| Token cost | Each finalization pass that produces a finalize turn costs one extra LLM round-trip and the prompt-cache miss. Per-edit attribution (Seam B) avoids the round-trip when no agent edits happened, and a HEAD-hash post-check avoids the round-trip when the agent already committed correctly. |
| Latency | The extra turn adds wall-clock latency on every run that touched files. Acceptable for the common case; pre-tool policy (Seam A) is faster but stricter. |
| Surprise | An always-on finalizer that runs even after `#sync` or `#crs` mid-workflow would force premature commits. `finalize_policy` per workflow is required. |
| Failure visibility | A run blocked by the finalizer is more visible than a run that quietly exited dirty. This is the desired direction even though it surfaces more "failures." |
| Disable footgun | `SASE_DISABLE_COMMIT_STOP_HOOK=1` currently silences everything. Once the finalizer becomes the only enforcement, an accidental disable equals no enforcement. Replace with a typed config that defaults to enabled and prints a warning when overridden. |

## Comparison With The Current Design

| Concern | Current design | Rewrite recommendation |
| --- | --- | --- |
| Dirty-workspace detection | Native stop hook plus Codex fallback | Supervisor finalizer after every SASE-launched turn |
| Runtime behavior | Hook transport differs by runtime | One finalizer state machine; providers only run extra turns |
| Commit intent | `SASE_COMMIT_METHOD` and related env vars | Typed `vcs_intent.json` in run context |
| Skill verification | Instructional only | Skill wrapper writes `commit_skill_invoked.json` |
| VCS mutation | `sase commit` / `CommitWorkflow` | Keep, but use typed request/context/result models |
| Native hooks | Primary enforcement | Optional early UX adapter |
| Failure mode | Can silently miss hook delivery | Run ends blocked if dirty state remains |

## Migration Path From Here

The rewrite can land incrementally without breaking current behavior.

1. **Extract a `CommitFinalizer` module.** Lift `build_commit_details()`, `_get_changed_files()`,
   `_resolve_commit_skill()`, `_build_commit_instruction_message()`, and `_build_name_instruction()` out of
   `src/sase/scripts/sase_commit_stop_hook.py` into a provider-neutral `src/sase/commit/finalizer.py`. The stop-hook
   script becomes a 30-line wrapper that calls `CommitFinalizer.build_instruction(...)` and emits the
   runtime-appropriate block JSON.
2. **Move the Codex fallback up.** Lift `_maybe_run_commit_fallback_turn()` from `src/sase/llm_provider/codex.py`
   into `src/sase/llm_provider/_invoke.py`, parameterized by a callable `run_followup_turn(prompt)` that each
   provider supplies. Every provider (Claude, Gemini, Qwen, Codex, opencode) gets the same finalization loop. Delete
   the Codex-specific fallback path once parity is verified.
3. **Add per-edit attribution (Seam B).** Ship a SASE-managed post-edit hook for each runtime that maintains
   `$SASE_ARTIFACTS_DIR/agent_edits.jsonl`. Wire the finalizer to default to "agent made edits → must commit"
   without asking the model.
4. **Introduce `RunContext` and `vcs_intent.json`.** Coordinate with the `vcs_xprompt_workflows_critique.md`
   recommendation: emit `vcs_intent.json` during embedded-workflow expansion, populate `RunContext` at agent launch
   in `src/sase/agent/launcher.py` and `src/sase/agent/launch_executor.py`, and persist a redacted snapshot into
   `workflow_state.json`. Continue mirroring `SASE_COMMIT_METHOD` for one compatibility window.
5. **Adopt `SASE_RUN_ID`.** Promote `SASE_AGENT_TIMESTAMP` (already used by the Codex fallback markers) to a
   first-class `SASE_RUN_ID`. Stamp it into every artifact listed in the hardening research, including
   `commit_skill_invoked.json` and `commit_result.json`.
6. **Replace `/sase_git_commit` shell wrapper with a marker-aware wrapper.** Either teach the existing bash script
   at `src/sase/scripts/sase_git_commit` to write `$SASE_ARTIFACTS_DIR/commit_skill_invoked.json` before `sase
   commit`, or replace it with a small Python entrypoint `sase skill-commit git`. The Python form is easier to keep
   in sync with CLI arg evolution (per `memory/long/generated_skills.md` — CLI/skill contract sync rule).
7. **Tighten detection.** Update `CommitFinalizer.is_clean()` to return `Clean | Dirty | Unknown` instead of the
   current swallow-and-fallback flow. `Unknown` blocks the run.
8. **Add finalize-policy plumbing.** `RunContext.finalize_policy ∈ {per_turn, on_workflow_complete, never}`,
   defaulting to `per_turn`. Workflows like `#sync` and `#crs` set `on_workflow_complete` in their `vcs_intent`.
9. **Add HEAD-hash policy-violation detection.** Compare pre- and post-turn HEAD; if HEAD moved but no
   `commit_result.json` for this `run_id`, log a `policy_violation` event and flag the run.
10. **Replace the single off-switch.** Deprecate `SASE_DISABLE_COMMIT_STOP_HOOK` in favor of explicit config in
    `default_config.yml` (`commit.finalizer.enabled`, `commit.finalizer.policy_default`,
    `commit.finalizer.max_passes`) and a `--no-finalize` CLI override. Honor the env var with a deprecation warning
    for one release.
11. **Simplify native hooks to optional adapters.** Once 1–10 land, the native stop-hook scripts in each runtime
    become thin shells around `CommitFinalizer.build_instruction()` and stop being load-bearing. The pre-tool
    policy (Seam A) can be added later behind a config flag.

A reasonable phasing for these eleven steps is: 1–3 in the first PR (finalizer extraction + universal fallback +
edit attribution), 4–6 in the second (typed context, run id, marker-writing skill wrapper), 7–9 in the third
(reliability and violation detection), and 10–11 last (config consolidation and native-hook simplification).

## Open Questions

- **How is the "not my changes" waiver expressed?** A text-only answer is fragile to model variance. Two cleaner
  options: (a) require the agent to invoke `sase skill-waive --reason "..."`, which writes a per-run
  `waiver.json`; (b) use per-edit attribution to compute the answer automatically and only fall back to a model
  question when attribution is empty but the tree is dirty. Recommend (b) as primary, (a) as the explicit override.
- **Should the finalizer block at the provider level or the supervisor level?** Provider-level (inside
  `_invoke.py`) is simpler and matches the Codex fallback pattern. Supervisor-level (inside
  `axe/run_agent_runner.py` or `agent/launch_executor.py`) survives provider crashes but is harder to instrument.
  Lean provider-level for V1; revisit if provider crashes become a real failure mode.
- **Should `--staged` skip the finalizer?** No — but the finalizer's success condition becomes "no *staged* changes
  remain" instead of "clean tree", and the run report should list deliberately-uncommitted unstaged paths.
- **Is there a place for an in-supervisor commit?** When the agent is gone (process killed, model refused, etc.)
  but `agent_edits.jsonl` shows real changes, should SASE auto-commit with a synthetic message? Probably no — that
  bypasses review intent — but a "stash and tag" rescue path is worth considering so the work is not lost.
- **What does `vcs_intent.finalize_policy = never` mean for `_post_commit_bead_amend`?** The amend runs inside
  `sase commit`, so the policy applies to the *outer* finalizer only. Worth documenting explicitly.
- **Does pre-tool policy (Seam A) belong in V1?** Decision deferred. The finalizer + edit attribution covers most
  enforcement value; Seam A adds prevention rather than detection. Recommend optional, opt-in via config, default
  off, for V1.

## Recommendation

The best from-scratch implementation is not "better hooks." It is a SASE-owned commit finalizer in the agent supervisor.
Hooks are too runtime-dependent to carry the invariant. The finalizer should own the loop, the typed intent, the
workspace verification, and the durable evidence that the commit skill and `sase commit` actually ran.

That design keeps the good part of the current system: agents still use `/sase_git_commit`, all real mutation still goes
through `sase commit`, and VCS providers stay behind the provider interface. It removes the fragile part: relying on
provider-native stop hooks and process-wide environment variables as the only path from "agent changed files" to
"agent committed correctly."

