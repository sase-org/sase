---
title: "Finalizer configuration"
description: "Configuration for commit hooks and post-run finalizers."
---

# Finalizer configuration

Configuration for commit hooks and post-run finalizers.

## finalizers

Configures host-owned completion finalizers for SASE-launched agent runs. The bundled
default selects the built-in commit instance, preserving ordinary commit enforcement
without runtime-specific hooks.

```yaml
finalizers:
  defaults: [commit]
  required: []
  instances:
    commit:
      use: builtin@commit
      after: []
      max_attempts: 2
      refusal: defer
```

`defaults` is the ordered selection used when a prompt omits `%final`. `required`
instances cannot be removed by `%final:none` or `%final:!name`. `instances` is keyed by
lowercase slug; each instance names a trusted provider with `use`, optional dependency
edges in `after`, bounded attempts through `max_attempts`, refusal handling, and
provider-specific `config`.

`sase final submit` is authoring-only: every dirty repository obligation takes a
Conventional Commit message, because SASE agents work in ephemeral numbered workspace
clones where uncommitted work is lost work. There is no free-text refusal action. The
only escape hatch is `sase final defer`, a separate, deliberate command that names a
typed reason from a closed set (`protected_paths`, `foreign_work`, `unsafe_content`,
`belongs_to_another_turn`) and is adjudicated by the host against run evidence at submit
time — a deferral the host can disprove is rejected with counter-evidence so the agent
can repair and resubmit in the same turn. `refusal` controls what happens when the host
upholds a deferral: `fail` (still fails the run; the historical behavior) or `defer`
(the shipped default — the run completes with a distinct `deferred` status and the tree
stays dirty, and a notification names the repository, reason, paths, and the command to
finish the commit by hand).

Only trusted configuration can define providers, commands, cwd policy, environment
allowlists, timeouts, or retry policy. Prompt text can only select configured instances:
`%final:lint` adds `lint`, `%final:none` clears defaults unless blocked by `required`,
and repeated/comma-separated `%final` operations replay left to right before dependency
ordering. Plugin packages may advertise providers through the `sase_finalizers`
entry-point group, but installation alone is inert; a trusted config layer must declare
and select an instance. Plugin-contributed config layers cannot activate finalizers.

Use `sase final list`, `sase final show <instance>`, and `sase final doctor` to inspect
effective policy, provider provenance, and diagnostics. During an active agent turn,
generated agent instructions tell the model to finish with `/sase_final`. That skill
uses `sase final context -f json` and `sase final submit` to publish the one turn-bound
declaration required by selected finalizers, and it returns after reading context when
no payload is required. If a required submission is missing or stale, the host opens one
bounded recovery turn that explicitly requests `/sase_final`. The host executes and
verifies finalizers after the model returns.

`sase final prepare <wrapper.json>` is the conditional alternative for a long
verification handoff. It seals a completed declaration, exact verification argv, current
context, and repository observations without submitting or executing them. Bind the
returned single-use ref with `sase monitor start -f <ref>`; only an eligible successful
monitor result lets the host install that declaration and run finalizers without another
model turn. A plain monitor profile carries no completion authority. See
[Prepared host completion](../automation/monitors.md#prepared-host-completion).

The built-in `builtin@commit` provider checks the main workspace, configured linked Git
worktrees, and repositories opened through `/sase_repo`. Dirty enforced repositories
become declaration obligations; each repository must receive exactly one `commit`
decision with a Conventional Commit message, and `commit` is the only legal repository
action. Typed deferrals can name explicit paths that must not be committed, using the
adjudicated reasons `protected_paths`, `foreign_work`, `unsafe_content`, or
`belongs_to_another_turn`. When the run has an assigned bead (`SASE_BEAD_ID`), the
primary repository's commit decision also carries a `keep` or `close` bead action, which
is forwarded to `sase stitch create -B`; see
[Explicit Bead Action](../../contribute/commit-workflow-orchestrator.md#explicit-bead-action).
Commit decisions dispatch through `sase stitch create` sequentially, preserve protected
pre-existing dirt, write stitch evidence, stop on the first conflict for repair/resume,
and fail completion when a rejected deferral or unrepaired dirty state remains. Later
mutating finalizers can reactivate commit until the controller reaches its bounded fixed
point.

When `$SASE_ARTIFACTS_DIR` is set, new runs write generic finalizer artifacts:
`finalizer_baseline.json`, `final_context.json`, `final_submission.json`,
`final_submission_attempts.jsonl`, `finalizer_result.json`, and per-instance files under
`finalizers/<instance>/`. The commit provider also keeps current stitch evidence in
`commit_results.json`. Historical `commit_finalizer_*` artifacts are read only for
archived run reporting and are not a supported output format for new runs.

### commit.message

Configures the Conventional Commit subject gate that `sase stitch create` applies to
every `create_commit`, `create_proposal`, and `create_pull_request` message before any
side effect runs.

```yaml
commit:
  message:
    require_conventional_subject: true
    allowed_types:
      [build, chore, ci, deps, docs, feat, fix, perf, refactor, revert, style, test]
```

[Generated reference for `commit.message`](repositories.md#commit-message)

The subject must match `<type>[(<scope>)][!]: <description>`. The scope is optional, one
or more spaces may follow the colon, and no length or capitalization rule is applied to
the description. The type itself must be lowercase, because release tooling does not
classify capitalized types reliably. Only the first line is inspected; nothing below the
subject is validated.

Subjects beginning with `Merge `, `Revert "`, `fixup!`, `squash!`, or `amend!` are
exempt and always pass — these are mechanical git-generated or rebase-directive
subjects. An empty message is always rejected.

A rejection fails the workflow before beads are closed, plans are staged, or the
before-commit hook runs, and the `-M` message file is preserved so the same command can
be re-run after the subject is rewritten. There is no per-invocation bypass flag or
environment variable; a project that does not use Conventional Commits sets
`require_conventional_subject: false`.

Source: `src/sase/finalizers/controller.py`, `src/sase/finalizers/commit.py`,
`src/sase/commit_instructions.py`, `src/sase/workflows/commit/message_validation.py`,
`src/sase/core/commit_subject_facade.py`

<a id="commithooks"></a>

## commit_hooks

Shell commands that bracket commit-producing VCS dispatches. `before` runs in the
repository root after bead and plan mutations but before diff capture and dispatch.
`after` runs in the repository root only after `create_commit` or `create_pull_request`
succeeds, including its push where applicable. Proposals run `before` but never run
`after` because they save a diff without creating a commit.

Both fields default to an empty string. Because the object is deep-merged, a global
`before` hook and project-local `after` hook compose without either configuration
repeating the other phase.

```yaml
commit_hooks:
  before: "just fix" # default: ""
  after: "chezmoi update -a --force" # default: ""
  after_rebase: "" # default: ""
  after_rebase_timeout_seconds: 10 # default: 10
```

[Generated reference for `commit_hooks`](repositories.md#commit_hooks)

Hook output is captured and a bounded stdout/stderr tail is printed on failure; each run
also leaves per-run evidence files described in
[Commit Hook Evidence](../../contribute/commit-workflow-orchestrator.md#commit-hook-evidence).
A failing `before` hook aborts before dispatch. A failing `after` hook leaves the commit
checkpoint in place and returns failure even though the commit may already be pushed;
fix the command and run `sase stitch create --resume`. The completed after-hook step is
checkpointed so a normal resume does not rerun it. A crash after the external command
succeeds but before that checkpoint write can run it again, so `after` commands must be
safe to repeat.

`after_rebase` gates pushes that follow a rebase combining divergent work. It runs in
the repository root with `SASE_REBASE_CONTEXT` naming a temporary JSON file holding the
pending gate context (schema version, immutable input IDs, current HEAD/tree, changed
paths) and `SASE_REBASE_RESULT` naming the fresh result file the checker writes (schema
version, checked HEAD/tree, `clean`/`findings`/`error` status, findings, and
diagnostics). Changed paths travel in the context file, never interpolated into shell
text. Context preparation, command execution, teardown, and result reads share one
monotonic deadline of `after_rebase_timeout_seconds` (default 10, maximum 30); the
subprocess group is terminated on timeout. Only a valid matching `findings` report
blocks the push. Timeout, signal, spawn failure, unsupported exits,
malformed/missing/stale reports, invalid settings, and explicit `error` reports all warn
and allow the push — unlike `before`/`after`, no gate error aborts dispatch.

A confirmed finding keeps the local commit unpublished with `pushed=false`, keeps the
commit checkpoint (including the pending gate context), and returns exit 2 with repair
instructions: include the fix in the local commit through the SASE repair flow, then run
`sase stitch create --resume`. The pending context is refreshed for the repaired HEAD on
resume, so an unchanged broken tree blocks again.

Source: `src/sase/default_config.yml`, `src/sase/workflows/commit/commit_hooks.py`,
`src/sase/workflows/commit/command_hooks.py`,
`src/sase/workflows/commit/rebase_gate_coordinator.py`,
`src/sase/workflows/commit/rebase_gate_runner.py`,
`src/sase/workflows/commit/workflow.py`

## Related

- [Agents and runners configuration](agents.md) — generated finalizer keys.
- [Commit workflows](../vcs/index.md) — commit behavior.
