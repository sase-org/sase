---
create_time: 2026-04-19 16:46:54
status: done
prompt: sdd/prompts/202604/coder_xprompt.md
---

# Plan: Add `#coder` builtin xprompt

## Goal

Introduce a new builtin xprompt named `coder` that encapsulates the prompt text sent to coder agents (agents that
implement an already-approved plan). It takes a plan file path as its only required input.

## Context

- **Builtin xprompts** live in `src/sase/xprompts/` and are auto-discovered via
  `importlib.resources.files("sase").joinpath("xprompts")` (see `src/sase/xprompt/loader.py:231`
  `_load_xprompts_from_internal`). Dropping a `.md` or `.yml` file into that directory is sufficient — there is no
  registry to update.
- Existing simple-prompt builtins: `fix_hook.md`, `summarize.md`. We model `coder.md` on them (single
  `prompt_part`-style body, Jinja2 substitution, frontmatter inputs).
- Today the coder's first prompt is **hardcoded** in `src/sase/axe/run_agent_exec_plan.py:410-415`:

  ```
  {model_prefix}{resume_prefix}{vcs_prefix}@{plan_file}

  The above plan has been reviewed and approved. Implement it now.{coder_extra}
  {embedded_refs}
  ```

  The new `#coder` xprompt captures the content-bearing middle of that string (the `@{plan_file}` + the "reviewed and
  approved / implement it now" sentence) so that users can also invoke the coder framing by hand — e.g. from a chat
  prompt or another xprompt — by writing `#coder:path/to/plan.md`.

- Recent related work (commit `d38b9a01`) dropped the `#resume:<planner>` prefix from the coder prompt by default; the
  plan file itself is now the hand-off artifact, which is exactly what the new `#coder` xprompt embeds via
  `@{{ plan_file }}`.

## Design

### File: `src/sase/xprompts/coder.md`

```markdown
---
name: coder
input:
  - name: plan_file
    type: path
---

@{{ plan_file }}

The above plan has been reviewed and approved. Implement it now.
```

Rationale:

- **`.md` (single prompt part) vs `.yml` (workflow):** a coder hand-off is a single prompt fragment with one template
  variable, so `.md` is the right shape. `.yml` would only be warranted if we wanted multi-step logic (e.g. reading the
  plan file, validating it, then emitting a prompt), which the current hardcoded path does not do.
- **`plan_file` with `type: path`:** matches `fix_hook.md`'s `output_file: path` and the existing variable name
  `plan_data["plan_file"]` in `run_agent_exec_plan.py`. `path` type is validated by `InputArg.validate_and_convert` at
  expansion time.
- **Required (no default):** a coder without a plan file is not a meaningful invocation — we want a validation error,
  not a silently-empty `@`.
- **No tag:** existing tags (`commit`, `propose`, `mentor`, `fix_hook`, `rollover`, etc. in
  `src/sase/xprompt/tags.py:12`) exist to support `get_by_tag()` lookups from Python code. There is no caller that looks
  up "the coder xprompt" by tag, so adding a `coder` tag + enum variant would be dead weight right now. Easy to add
  later if a caller needs it.
- **No trailing `#propose` / other chained xprompts:** unlike `fix_hook.md` which ends with `#propose` to auto-open a
  PR, a coder invocation shouldn't force a proposal step — the existing plan-execution flow handles that separately, and
  a hand-typed `#coder:...` prompt should not surprise the user by opening PRs.

### Invocation shape

Callers will write either:

```
#coder:plans/my_plan.md
```

or the explicit-positional form:

```
#coder(plans/my_plan.md)
```

and Jinja expansion produces exactly the two lines in the body.

## Out of scope (explicit non-goals)

These are worth noting because a reader might wonder why the plan doesn't touch them:

1. **Refactoring `run_agent_exec_plan.py:410-415` to call `#coder` instead of hardcoding the string.** The user asked
   for the xprompt itself, not a migration. The hardcoded site also interleaves `model_prefix`, `resume_prefix`,
   `vcs_prefix`, `coder_extra`, and `embedded_refs` around the body, so refactoring it into `#coder(...)` is a larger,
   separate change that risks regressions in the coder execution path. **Decision point for the user:** should this
   follow-up be part of the same PR, a follow-up PR, or not done at all? Default in this plan: not done.
2. **Adding a `coder` entry to `XPromptTag`.** No caller needs it yet; adding now would be speculative.
3. **Making the body richer** (e.g. "ask questions if the plan is unclear", "implement faithfully", etc.). The existing
   hardcoded prompt is deliberately terse; matching it exactly keeps behavior identical for anyone who does later wire
   this xprompt into `run_agent_exec_plan.py`.

## Verification

- `just check` (lint + mypy + tests) — required per repo instructions for any file change.
- Manual expansion check:
  ```
  sase xprompt expand '#coder:/tmp/plan.md'
  ```
  (or the project's equivalent CLI entrypoint) — should produce the two-line body with the path substituted.

## Tests

No new tests are required:

- Builtin-xprompt discovery is already covered generically by `tests/test_xprompt_loader_config.py` — the loader walks
  `src/sase/xprompts/` and picks up any new `.md` file automatically.
- Frontmatter parsing, input validation (`path` type), and Jinja expansion are already covered by
  `tests/test_xprompt_loader_parsing.py`, `tests/test_xprompt_loader_shortform.py`, `tests/test_xprompt_models.py`, and
  `tests/test_xprompt_jinja_and_standalone.py`.
- Neither `fix_hook.md` nor `summarize.md` has a dedicated test; they ride on the generic loader/processor tests.
  `coder.md` should match that convention — adding a bespoke test just for its existence would be boilerplate with no
  signal.

If the follow-up refactor in "out of scope" #1 is ever done, **that** change would warrant new tests in
`tests/test_axe_run_agent_exec_plan.py` to pin the new expansion path — but not this change.

## Risks

- **Name collision:** if a user already has a local `~/xprompts/coder.md` or `.xprompts/coder.md`, their version wins
  (builtins are lowest priority per `loader.py:510`). That's the intended override behavior and not a problem.
- **Silent drift from the hardcoded prompt:** if `run_agent_exec_plan.py` changes its hardcoded wording later, the
  builtin `#coder` xprompt and the coder-agent's actual first prompt will diverge. Mitigated by a short comment in the
  xprompt body isn't warranted (memory says: "default to no comments"), but the plan calls this out so a future reader
  of the hardcoded site can choose to consolidate.

## Deliverables

Single new file:

- `src/sase/xprompts/coder.md` (~10 lines incl. frontmatter)

No edits to any existing file.
