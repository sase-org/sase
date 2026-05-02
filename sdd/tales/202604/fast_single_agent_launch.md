---
create_time: 2026-04-24 18:01:12
status: done
prompt: sdd/prompts/202604/fast_single_agent_launch.md
---
# Make Single-Agent Launch Feel Immediate

## Goal

Make the normal one-agent launch path in `sase ace` visibly faster, especially the common case where the user submits a
plain prompt or a prompt with only a VCS tag such as `#gh:...` / `#git:...`.

The user-facing target is:

- The prompt bar disappears immediately.
- A "Launching..." notification appears immediately.
- The agent appears in the Agents tab as soon as the subprocess has been spawned and the RUNNING claim is written.
- Plain prompts avoid xprompt/config catalog work during TUI launch preflight.

This should not change multi-prompt, repeat, multi-model, bulk launch, `%wait`, embedded workflow, or VCS-ref semantics.

## Current State

The TUI submit path is already off the Textual event loop:

- `_finish_agent_launch()` unmounts the prompt bar, then schedules `_run_agent_launch_body_async()`.
- `_run_agent_launch_body_async()` sends `_run_agent_launch_body()` through `asyncio.to_thread()`.

That fixes event-loop blocking, but the user can still observe launch lag because `_run_agent_launch_body()` performs a
large amount of preflight before it schedules the actual single-agent spawn notification:

- VCS workflow/ref lookups.
- Prompt history and file-reference writes.
- Multi-prompt parsing.
- Embedded workflow probing.
- Full xprompt expansion through `process_xprompt_references()` to detect `%m(...)` injected by xprompts.
- Repeat/multi-model checks.
- A second `threading.Thread` for `_launch_background_agent()`.

The no-edit timing pass found one concrete hotspot:

- `process_xprompt_references("plain prompt with no xprompt refs")` costs roughly 58 ms in the repo venv.
- `process_xprompt_references("#git:master do thing")` also costs roughly 58 ms, even when no xprompt expands.
- The current implementation loads config/xprompt sources before checking whether the prompt can actually expand.

The multiple-agent launch mixins already give immediate feedback at the launch helper boundary. The single-agent path is
less direct: its immediate feedback happens only after preflight finishes, then the subprocess spawn happens in a second
background thread.

## Design

### 1. Add a Cheap XPrompt Expansion Gate

Introduce a lightweight helper in `sase.xprompt.processor`, for example:

```python
def prompt_may_reference_xprompt(prompt: str, extra_xprompts: dict[str, XPrompt] | None = None) -> bool:
    ...
```

The helper should be conservative:

- Return `False` immediately when there is no `#`.
- Recognize the existing xprompt-reference lexical forms without loading the full xprompt catalog.
- Return `True` for local user frontmatter xprompts that are actually referenced.
- Treat possible non-VCS `#name`, `#name(...)`, `#name:arg`, `#name+`, `#namespace/name`, and `#foo__bar` forms as
  candidates.
- Avoid matching Markdown headings and obvious VCS-only tags when possible.

Then harden `process_xprompt_references()` itself:

- Return immediately before config/xprompt loading when the prompt has no `#`.
- After alias resolution, return immediately when the prompt still has no `#`.
- Keep existing behavior for prompts that may contain xprompts.

This gives a global win for callers that accidentally invoke xprompt processing on plain prompts, and it gives the TUI a
specific gate before doing expensive expansion only to detect multi-model directives.

### 2. Skip Single-Agent TUI Expansion When It Cannot Affect Dispatch

In `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`, replace unconditional single-prompt expansion:

```python
prompt = process_xprompt_references(...)
model_prompts = split_prompt_for_models(prompt)
```

with a fast path:

- Always check `split_prompt_for_models(raw_or_frontmatter_body)` first; this catches explicit `%m`, `%model`, and
  `%alt` without any xprompt work.
- Only call `process_xprompt_references()` if the cheap gate says the prompt may contain an xprompt reference.
- If expansion is skipped, use the unexpanded prompt for multi-model detection.

The agent runner already expands xprompts in the subprocess. The TUI only needs pre-expansion to discover
xprompt-injected multi-model directives, so skipping expansion when there is no candidate is behavior-preserving.

### 3. Make Single-Agent Feedback Immediate

Move the "Launching agent for ..." notification earlier:

- `_finish_agent_launch()` should show the launching notification right after unmounting the prompt bar, using the
  current prompt context display name.
- `_run_agent_launch_body()` should keep the final "Agent started for ..." notification after spawn succeeds.

This does not make the subprocess faster, but it removes the perceived dead period while worker preflight is running.

### 4. Collapse the Extra Single-Agent Thread

The launch body is already running in a worker thread. For the single-agent branch, call `_launch_background_agent()`
directly from that worker instead of creating a nested `threading.Thread`.

Keep all UI mutations marshalled through `self.call_later()`.

Benefits:

- Fewer scheduling hops.
- Simpler exception handling.
- The agents refresh is scheduled immediately after `spawn_agent_subprocess()` returns and the RUNNING claim is written.

Multi-model/repeat/multi-prompt/bulk helpers can keep their current thread-based structure in this task because they are
entered from the main thread via `call_later()` and already provide immediate feedback.

### 5. Refresh Agents as Soon as the Claim Exists

After the direct single-agent spawn returns:

- Call `_schedule_agents_async_refresh()` through `call_later()` immediately.
- Keep the final success notification.

Do not add a pre-spawn optimistic fake agent in this pass. The RUNNING field is already the source of truth, and the
direct worker call should make the delay small without adding synthetic state reconciliation risk.

### 6. Optional Follow-Up if Measurements Still Show Lag

If focused timings still show more than a small delay after the above:

- Add targeted debug timing around `_run_agent_launch_body()` phases and `spawn_agent_subprocess()`.
- Consider caching `get_all_xprompts()` with explicit invalidation keyed by config/xprompt search path mtimes.
- Consider moving prompt history/file-reference recording after subprocess spawn for the single-agent path.

Those are broader changes and should only be taken if the fast path above is not enough.

## Tests

Add or update focused tests:

- `process_xprompt_references("plain text")` returns without calling `get_all_xprompts()`.
- `process_xprompt_references()` still expands known xprompts when `#name` is present.
- The new cheap gate returns `False` for plain prompts and VCS-only tags that should not trigger expansion.
- The cheap gate returns `True` for local frontmatter xprompt references.
- `_run_agent_launch_body()` skips `process_xprompt_references()` for a plain single-agent prompt.
- `_run_agent_launch_body()` still calls expansion when an xprompt reference may inject a multi-model directive.
- `_finish_agent_launch()` schedules the async body, unmounts the prompt bar, and emits immediate launch feedback.
- Single-agent launch calls `_launch_background_agent()` directly from the worker body and schedules one agents refresh
  after success.
- Existing non-blocking launch regression test continues to pass.

Likely test files:

- `tests/test_snippet_references.py` or a new focused `tests/test_xprompt_processor_fast_path.py`.
- `tests/ace/tui/test_agent_launch_non_blocking.py`.

## Verification

Run focused tests first:

```bash
uv run pytest -q tests/test_snippet_references.py tests/ace/tui/test_agent_launch_non_blocking.py
```

Then follow repo requirements after code changes:

```bash
just install
just check
```

Also re-run the no-edit timing check after implementation:

```bash
.venv/bin/python - <<'PY'
import time
from sase.xprompt.processor import process_xprompt_references

for prompt in ["plain prompt with no xprompt refs", "#git:master do thing"]:
    t = time.perf_counter()
    for _ in range(100):
        process_xprompt_references(prompt)
    print(prompt, (time.perf_counter() - t) * 1000 / 100)
PY
```

Expected result: the plain prompt path should be effectively near-zero compared with the current roughly 58 ms/call.

## Risks and Mitigations

- Missing xprompt-injected multi-model directives: keep the gate conservative and test explicit xprompt references.
- Alias behavior: do not skip `resolve_xprompt_aliases()` for prompts with `#`; only skip all work when there is no `#`.
- VCS tags that share names with xprompts: when ambiguous, prefer returning `True` and paying the old cost rather than
  changing behavior.
- Threading regressions: keep `_run_agent_launch_body_async()` as the single offload boundary and marshal UI actions
  with `call_later()`.
- Tests using minimal fake apps: update fakes to record immediate notifications and direct launch calls.
