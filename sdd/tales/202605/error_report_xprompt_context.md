---
create_time: 2026-05-12 18:08:23
status: done
prompt: sdd/prompts/202605/error_report_xprompt_context.md
---
# Plan: Add Submitted XPrompt Context to Agent Error Reports

## Context

SASE already writes per-agent Markdown error reports through `src/sase/axe/runner_utils.py:write_error_report()`. Those
reports currently include model, workflow, CL, duration, error summary, and traceback, but they do not include the exact
xprompt/prompt the user submitted. That makes failures harder to reproduce, especially when a short top-level xprompt
expands into a large prompt or when dynamic memory, wait refs, aliases, VCS refs, retry prompts, or embedded workflows
alter the prompt before execution.

The most important product requirement is:

> Future error reports should always include the exact xprompt submitted at the launch boundary, before alias
> resolution, xprompt expansion, dynamic memory injection, agent-reference rewriting, or retry-loop mutation.

Current relevant surfaces:

- Normal TUI/background agents: `src/sase/axe/run_agent_runner.py` reads a temp prompt file, then mutates `prompt`
  through preprocessing, dynamic memory, directive extraction, wait handling, and agent-ref resolution. Failures later
  call `write_error_report()` without passing any prompt context.
- The existing `raw_xprompt.md` artifact is written by
  `src/sase/axe/run_agent_runner_setup.py:preprocess_prompt_xprompts()`, but it is saved after alias resolution. It is
  useful and should remain compatible, but it is not a reliable "exact user input" artifact.
- Fix-hook, CRS, summarize-hook, and mentor runners also call `write_error_report()`, often after building a generated
  xprompt or expanded prompt internally.
- Prompt fan-out launch failures can occur before child agents and per-agent artifacts exist; they use a separate text
  report in `src/sase/ace/tui/actions/agent_workflow/_launch_multi_model.py`.

## Goals

1. Include a dedicated **Submitted XPrompt** section in every newly written `error_report.md` when SASE has prompt
   context.
2. Preserve the exact submitted text, including whitespace and xprompt syntax, using a Markdown-safe fence.
3. Keep `raw_xprompt.md` behavior backward-compatible for display, search, revive, and retry flows.
4. Make prompt capture explicit at the earliest practical boundary instead of trying to reconstruct it from later
   mutated state.
5. Cover normal agents and generated-review runners without broad refactors.

## Non-goals

- Do not rewrite historical reports or historical artifacts.
- Do not change agent prompt execution semantics.
- Do not change how `raw_xprompt.md` is displayed or used by revive/retry unless a targeted test proves the current
  alias-resolution behavior is wrong for that surface.
- Do not force axe hourly digest reports to include xprompt text; those digest records are not necessarily tied to a
  single submitted agent prompt.

## Design

### 1. Define the canonical submitted prompt

For normal agents, the canonical value is the content read from the runner's temp prompt file at the top of
`run_agent_runner.main()`, before `setup_artifacts_directory()` and before `preprocess_prompt_xprompts()`.

Store that string in a local variable such as `submitted_xprompt = prompt` immediately after the temp file is read.
After the artifact directory is created, write it to a new artifact:

- `submitted_xprompt.md`

This artifact should be best-effort and should not replace `raw_xprompt.md`. The name is intentionally explicit: it
means "what the launch surface submitted", not "the prompt after alias normalization" or "the fully expanded prompt".

### 2. Make error report formatting prompt-aware

Extend `write_error_report()` to accept optional prompt context, for example:

- `submitted_xprompt: str | None = None`
- optional `submitted_xprompt_path: str | None = None` if useful for report metadata

If `submitted_xprompt` is not passed, the helper may fall back to reading `submitted_xprompt.md`, then `raw_xprompt.md`,
from `artifacts_dir`. The fallback keeps generated runners and future callers from silently omitting prompt context when
an artifact already exists.

Add a section after the summary table and before the error block:

````markdown
## Submitted XPrompt

```markdown
...
```
````

```

The fence writer should choose a fence length longer than any backtick run in the prompt, or use tildes, so prompts
containing fenced code blocks cannot break the report.

### 3. Add useful adjacent context without bloating the report

While touching the summary area, add high-signal fields only when available:

- Artifact directory
- Workspace directory
- Output log path
- Agent name, if known

Keep the error and traceback sections intact. This keeps reports readable while making the report self-contained enough
to debug from a notification attachment.

### 4. Wire normal agent failures

In `src/sase/axe/run_agent_runner.py`:

1. Capture `submitted_xprompt` before any mutation.
2. Write `submitted_xprompt.md` after `artifacts_dir` is available.
3. Pass `submitted_xprompt=submitted_xprompt` into `write_error_report()`.
4. Also pass useful context already in scope, such as `workspace_dir`, `output_path`, and `agent_name`.

Important edge case: multi-step workflows may write the failure report in `current_artifacts_dir`, which can differ
from the root `artifacts_dir`. Passing the prompt string directly prevents the report from depending on which directory
contains the prompt artifact.

### 5. Wire generated-review runners

Generated runners should pass their closest unexpanded invocation when they have one:

- `fix_hook_runner`: pass `prompt_ref`, not the fully expanded prompt.
- `crs`: change `_build_crs_prompt()` to return both the generated xprompt invocation and expanded prompt, or add a
  small helper that builds the invocation separately. Pass the invocation into the runner's error report.
- `mentor`: similarly expose the generated `#mentor(...)` invocation from prompt construction if available; otherwise
  pass the built prompt as "submitted" context.
- `summarize_hook_runner`: if no agent xprompt is launched, leave the prompt section absent or include a generated
  runner context section only if a prompt-like value exists.

This keeps "Submitted XPrompt" meaningful. For internally generated workflows, it means "the xprompt invocation SASE
generated for this agent-like run", not a human-typed prompt.

### 6. Handle pre-agent fan-out failures

`_write_fanout_failure_report()` currently writes a `.txt` report before child agents exist. Add the original launch
prompt to that report as well:

- Pass `source_prompt` / `submitted_xprompt` from `_run_agent_launch_body_async()` into `_launch_multi_model_agents()`
  and `_record_fanout_launch_failure()`.
- Include a **Submitted XPrompt** fenced block in the fan-out failure report.

Changing the extension from `.txt` to `.md` is optional. If changed, update tests and notification fixtures that assume
`.txt`. The safer first step is to keep the filename stable and add Markdown-compatible content.

## Tests

Add focused tests rather than relying on a full runner integration test:

1. `tests/test_error_report_context.py`
   - `write_error_report()` includes a `## Submitted XPrompt` section when `submitted_xprompt` is passed.
   - Prompt text is preserved exactly, including leading/trailing whitespace and `#xprompt(...)` syntax.
   - A prompt containing triple backticks does not break the report fence.
   - If no explicit prompt is passed, the helper falls back to `submitted_xprompt.md` before `raw_xprompt.md`.

2. `tests/test_run_agent_runner_setup.py` or an existing nearby setup test
   - The new artifact writer persists `submitted_xprompt.md` without changing `raw_xprompt.md` behavior.

3. Existing runner notification tests
   - Extend the failure-report test to assert `send_completion_notification()` still uses `ViewErrorReport` and the
     report path remains first in attachments.

4. Fan-out failure coverage
   - Extend `tests/ace/tui/test_launch_fan_out_unified.py` to assert the generated failure report includes the submitted
     prompt.

## Verification

After implementation:

1. `.venv/bin/python -m pytest tests/test_error_report_context.py -q`
2. `.venv/bin/python -m pytest tests/test_run_agent_runner_notifications.py tests/ace/tui/test_launch_fan_out_unified.py -q`
3. `.venv/bin/python -m pytest tests/test_agent_artifact_facade.py tests/test_dismissed_agent_lifecycle.py tests/test_agent_revive_meta.py -q`
4. `just check`

Per repo memory, run `just install` first if the workspace virtualenv is stale.

## Risks and Mitigations

- Risk: changing `raw_xprompt.md` would regress revive, retry, search, or display behavior. Mitigation: add
  `submitted_xprompt.md` and keep `raw_xprompt.md` compatible.
- Risk: reports leak more sensitive prompt content into notifications and attached files. Mitigation: the prompt is
  already stored in artifacts for normal agents; this change only makes the relevant failure artifact self-contained.
- Risk: generated runners do not have a true user-submitted prompt. Mitigation: pass the generated top-level xprompt
  invocation when available and omit the section only when no prompt-like context exists.
- Risk: Markdown fences break when the prompt contains fenced code. Mitigation: use a dynamic fence helper and test it.

## Implementation Order

1. Add prompt-safe Markdown fence/report helpers and tests around `write_error_report()`.
2. Capture and persist `submitted_xprompt.md` for normal agents; wire `run_agent_runner.py`.
3. Wire generated-review runners with prompt invocation context.
4. Add fan-out failure prompt context.
5. Run focused tests and then `just check`.
```
