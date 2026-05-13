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

1. Extract the common dirty-check and instruction-building code from `sase_commit_stop_hook.py` into a provider-neutral
   `CommitFinalizer` module.
2. Move the Codex fallback up into the generic LLM invocation layer so every SASE-launched provider gets the same
   post-turn finalization check.
3. Add `vcs_intent` metadata and `vcs_intent.json`, while continuing to mirror `SASE_COMMIT_METHOD` for compatibility.
4. Make `/sase_git_commit` call a marker-writing wrapper before `sase commit`.
5. Teach the finalizer to require `commit_skill_invoked.json` plus `commit_result.json` for runs with SASE-owned
   changes.
6. Add policy-violation detection for commits made outside `sase commit`.
7. After compatibility, simplify native stop hooks to thin adapters around the finalizer helper.

## Recommendation

The best from-scratch implementation is not "better hooks." It is a SASE-owned commit finalizer in the agent supervisor.
Hooks are too runtime-dependent to carry the invariant. The finalizer should own the loop, the typed intent, the
workspace verification, and the durable evidence that the commit skill and `sase commit` actually ran.

That design keeps the good part of the current system: agents still use `/sase_git_commit`, all real mutation still goes
through `sase commit`, and VCS providers stay behind the provider interface. It removes the fragile part: relying on
provider-native stop hooks and process-wide environment variables as the only path from "agent changed files" to
"agent committed correctly."

