---
create_time: 2026-06-24 07:15:07
status: done
prompt: sdd/prompts/202606/fix_followup_agent_default_effort.md
---
# Plan: Record `default_effort` on Follow-up (Coder/Epic/Legend) Agents

## Problem

When `llm_provider.default_effort` is set (e.g. `xhigh`), **coder agents** (and other plan-chain follow-up agents)
appear not to be running at that effort level, even though the initial planner agent does. Every agent that does not
specify an explicit effort — via the `%effort:<level>` directive or the `@<effort>` suffix on a `%model` directive — is
supposed to fall back to `default_effort`.

## Diagnosis (root cause)

There are two distinct concerns, and only one of them is actually broken. The fix targets the broken one while locking
in the correct one with regression coverage.

### What is correct: the effort applied at the CLI invocation

The effort that the underlying runtime CLI actually receives is resolved at call time, independently of any persisted
metadata:

- `llm_provider/_invoke.py::invoke_agent` calls `resolve_effective_effort(result_directives)` on every invocation.
- `llm_provider/config.py::resolve_effective_effort` implements the precedence: explicit `%effort`/`@effort` → else
  `llm_provider.default_effort` → else nothing.
- The resolved level is threaded as `LLMInvocationOptions` into the provider, where `_effort_args.py::effort_cli_args`
  turns it into CLI flags (Claude `--effort`, Codex `-c model_reasoning_effort=...`). Both providers support `xhigh`.

A follow-up coder agent runs **in the same process** as the planner (the run loop in `axe/run_agent_exec.py` simply
continues with a new `current_prompt`; the prompt step in
`xprompt/workflow_executor_steps_prompt.py::_execute_prompt_step` calls `invoke_agent`). Because `invoke_agent`
re-resolves the effort from config, the coder's runtime process **does** receive the `default_effort` flag. So the
behavior is, in fact, correct.

### What is broken: the effort recorded/displayed for follow-up agents

The reasoning effort an agent is **shown** to be using comes from the `reasoning_effort` field in its `agent_meta.json`,
surfaced through the Rust artifact-index scanner and rendered by `llm_provider/model_label.py` as the
`Model: PROVIDER(model) @ <effort>` suffix (TUI agent panels and `sase agent show`).

- The **initial planner** agent gets this field written by
  `axe/run_agent_directives.py::extract_directives_and_write_meta`, which resolves the effective effort (including the
  `default_effort` fallback) and persists it.
- **Follow-up agents** (coder/epic/legend) are created by
  `axe/run_agent_helpers_artifacts.py::create_followup_artifacts`, which copies a fixed set of fields from the parent
  meta (`model`, `llm_provider`, `vcs_provider`, …) but **omits `reasoning_effort`**. Their model/provider are then
  (re)written by `axe/run_agent_exec_plan_accept.py::_write_followup_model_meta`, but there is **no effort counterpart**
  — nothing ever resolves or persists `reasoning_effort` for a follow-up agent.

Net effect: the coder agent's `agent_meta.json` has no `reasoning_effort`, so its panel renders without the `@ xhigh`
suffix and it _looks_ like it is not using the configured effort — which is exactly the reported symptom. There is also
no test asserting that a follow-up agent records/uses `default_effort`, so the gap went unnoticed.

This is an asymmetry: the follow-up pipeline persists the resolved **model/provider** but not the resolved **effort**,
even though the initial-agent pipeline persists both.

## Goals

1. Follow-up coder/epic/legend agents record a `reasoning_effort` in their `agent_meta.json` consistent with the
   precedence used everywhere else: an explicit `%effort`/`@effort` in the follow-up's own prompt wins; otherwise
   `default_effort`; otherwise nothing (field omitted).
2. The recorded value matches what the runtime CLI actually receives, so the TUI / `sase agent show` display is
   accurate.
3. Regression coverage proves both the recorded metadata and the end-to-end CLI behavior for the worker lane.

Non-goals: changing the resolution precedence, the provider support matrix, the `default_effort` schema/default (`""`),
or the Rust scanner (it already projects `reasoning_effort`).

## Approach

Mirror the existing follow-up **model** handling for **effort**, reusing the single source of truth for precedence
(`resolve_effective_effort`). Keep all logic in Python: the resolution layer is Python and the Rust scanner already
reads the field, so this does not cross the Rust core boundary.

### 1. Persist the resolved effort for plan-chain follow-ups

In `axe/run_agent_exec_plan_accept.py`, add an effort counterpart to `_write_followup_model_meta` (e.g.
`_write_followup_effort_meta`) that:

- Determines the follow-up's effective effort using the same precedence as the rest of the system: parse any explicit
  `%effort`/`@effort` from the follow-up's own prompt (notably a custom coder prompt, which is already inspected for a
  `%model` directive at lines ~417–436), then fall back to `default_effort` via `resolve_effective_effort`.
- Writes the result into the follow-up agent's `agent_meta.json` via `update_meta_field(..., "reasoning_effort", level)`
  only when a level is resolved (omit the field when both explicit and default are unset, matching today's "truthy-only"
  behavior in `extract_directives_and_write_meta`).

Invoke it for **both** follow-up branches in `handle_accepted_plan` — the epic/legend branch (alongside the existing
`_write_followup_model_meta` call ~line 339) and the coder branch (~line 437). Resolve against the finally-constructed
follow-up prompt so an explicit effort in a custom coder prompt is honored rather than silently replaced by the default.

Rationale for resolving fresh (rather than copying the planner's recorded effort): the follow-up may use a **different**
worker model/provider, and a planner that used an explicit `%effort` must not force that explicit level onto a coder
that did not request it — the coder should fall back to `default_effort`. Fresh resolution is the only option that
satisfies the stated requirement in every case.

### 2. (Consistency) Carry effort forward for other follow-up kinds

Other `create_followup_artifacts` callers (retry/fallback spawns, question resumes) continue the _same_ agent and model,
so their recorded effort should simply persist. Add `reasoning_effort` to the inherited-field list in
`create_followup_artifacts` so those follow-ups keep the parent's recorded effort as a baseline. The plan-chain path
from step 1 still authoritatively (re)writes the field for coder/epic/legend, where the model — and therefore the
correct effort resolution — may differ from the parent.

### 3. Verify the planner path is unaffected

Confirm the initial-agent path (`extract_directives_and_write_meta`) is unchanged and still records `default_effort`;
the fix only adds the missing follow-up persistence.

## Testing

- **Follow-up metadata (default):** a coder/worker-lane follow-up created with no explicit effort and `default_effort`
  configured records `reasoning_effort = <default>` in its `agent_meta.json`. Cover the epic/legend follow-up branch
  similarly.
- **Follow-up metadata (explicit wins):** a custom coder prompt carrying an explicit `%effort`/`@effort` records that
  explicit level, not the default.
- **Follow-up metadata (unset):** with `default_effort` empty and no explicit effort, the follow-up omits
  `reasoning_effort` (no regression / no spurious field).
- **End-to-end CLI behavior:** a provider-level test asserting that a worker-lane invocation with `default_effort` set
  and no explicit effort passes the default effort into the provider CLI args (e.g. Codex
  `-c model_reasoning_effort="<default>"`), locking in that the coder process genuinely runs at the configured effort.
- **Inheritance for non-plan follow-ups:** a retry/question follow-up preserves the parent's recorded
  `reasoning_effort`.

Run `just check` (after `just install`) before completion.

## Risks / Considerations

- **Display vs. behavior:** the runtime behavior is already correct; this change makes the recorded/displayed effort
  accurate and adds the regression net that was missing.
- **Effort-meta write timing:** resolve effort against the _final_ follow-up prompt (after it is assembled and any
  custom-coder-prompt `%model`/`%effort` handling has run) so the recorded value matches what `invoke_agent` will
  compute at call time.
- **Artifact index freshness:** writing `reasoning_effort` via `update_meta_field` triggers the existing artifact-index
  refresh, and the Rust scanner already projects the field (schema v6), so no index/schema change is required.
- **Uniform runtimes:** the fix is provider-agnostic — it records the resolved level for any worker provider; providers
  that cannot honor a given level still skip it as a best-effort default (existing `effort_cli_args` contract), with no
  runtime-specific branching.
