---
create_time: 2026-04-23 19:57:14
status: done
prompt: sdd/prompts/202604/wait_chats_jinja_variable.md
---

# Plan: Expose `wait_chats` Jinja variable for `%w` / `%wait` directives

## Problem

The `%wait:<name>` directive (alias `%w`) makes an agent block until one or more named peer agents have finished writing
`done.json`. Once the wait resolves, the waiting agent has no first-class way to reference the **chat transcripts** of
the agents it waited for. Users currently have to reconstruct the transcript paths out-of-band or resort to
`#resume:<name>` (which inlines the full transcript). There is no way to, for example, read the transcripts as files via
`@`-references or feed them into an xprompt as arguments.

## Goal

When a prompt contains one or more `%wait`/`%w` directives, expose a Jinja variable `wait_chats` whose value is a list
of `~/.sase/chats/...` file paths — one per waited-for agent, in the order the `%wait` directives appeared. Users can
then write templates like:

```
%wait:a
%wait:b

Review the transcripts of the agents I waited for:
{% for path in wait_chats %}
@{{ path }}
{% endfor %}
```

When no `%wait` directive is present, `wait_chats` is **not** injected (keeping parity with how `N` is handled for
`%repeat` — `{{ wait_chats }}` without `%wait` raises `UndefinedError` under `StrictUndefined`).

## Design

### Existing pipeline

The relevant flow in `run_agent_runner.py` already looks like this:

```
extract_directives_and_write_meta(prompt, ...)   # returns info.wait_names
    ↓
wait_for_dependencies(info.wait_names, ...)      # blocks until done.json appears for each
    ↓
resolve_agent_refs_in_prompt(prompt)             # post-wait — safe to read done.json
    ↓
run_execution_loop(ctx, prompt)                  # eventually calls preprocess_prompt_early
    ↓
_execute_prompt_step → preprocess_prompt_early(step.agent, context=self.context)
```

`preprocess_prompt_early` already accepts a `context` dict for Jinja2 rendering. The `context` is sourced from
`WorkflowExecutor.context`, which is built from the `named_args` passed to `execute_workflow`. This is the same
injection seam used by the existing `cl_name`, `workspace_num`, and `N` variables (see
`plans/202604/repeat_iteration_variable.md`).

The natural implementation: resolve the wait-name list → chat-path list once, right after `wait_for_dependencies`
returns, then thread that list into `run_execution_loop`'s `named_args`.

### Phase 1: Resolve wait names to chat paths

Add a helper in `src/sase/axe/run_agent_phases.py`:

```python
def resolve_wait_chat_paths(wait_names: list[str]) -> list[str]:
    """Resolve each waited-for agent name to its ~/.sase/chats/ file path.

    Called after wait_for_dependencies() returns, so every name should have
    a done.json with response_path.  Missing/unresolvable names are skipped
    (best-effort — a failed agent still counts as "waited for", but may not
    have written a response).
    """
```

Implementation notes:

- Use `find_named_agent(name, only_done=True)` (already exists in `src/sase/agent/names.py`) to locate each agent's
  artifacts directory.
- Read `done.json["response_path"]` — this field is already written by `build_done_marker` for completed outcomes and
  stores the `~`-prefixed path (see `save_chat_history` return).
- Skip entries where the agent can't be resolved or has no `response_path` (e.g., failed agents). Log a warning via
  `print_status(..., "warning")` so the user sees why a `wait_chats[i]` they expected is missing; do not raise.
- Preserve the order of `wait_names` (list comprehension, not a set).

### Phase 2: Thread `wait_chats` into the execution loop

**`src/sase/axe/run_agent_runner.py`** — After `wait_for_dependencies(...)` at line ~293, call
`resolve_wait_chat_paths(info.wait_names)` and store the result on `ctx` (add a field
`wait_chats: list[str] = field(default_factory=list)` to `AgentExecContext` in `run_agent_exec.py`).

**`src/sase/axe/run_agent_exec.py`** — In `run_execution_loop`, when building the `named_args` dict (around line 304),
inject `"wait_chats": ctx.wait_chats` only when the list is non-empty. This matches the pattern of the `N`/`n` variables
which are only injected when repeat env vars are set.

Why gate on "non-empty" rather than always injecting? A consistent rule with `N`: the variable is only defined when the
triggering directive fired. This keeps `StrictUndefined` as a good typo-catcher — a user writing `{{ wait_chats }}`
without any `%wait` will get a clear Jinja error instead of silently iterating over an empty list.

### Phase 3: Tests

**`tests/test_axe_run_agent_phases.py`** (new or existing) — Unit-test `resolve_wait_chat_paths`:

- Resolves a single name correctly by seeding a fake `~/.sase/projects/.../done.json` with `response_path`.
- Preserves order across multiple names.
- Skips a name with no matching agent (best-effort, logs warning, returns shorter list).
- Skips an agent whose `done.json` has no `response_path`.

**`tests/test_preprocessing_jinja_context.py`** — Add a case verifying `{{ wait_chats | join(",") }}` renders from a
`context={"wait_chats": [...]}` dict fed into `preprocess_prompt_early`.

**`tests/test_axe_run_agent_runner.py`** (or the closest existing integration test) — End-to-end: launch a fake agent
prompt with `%wait:<name>`, stub `wait_for_dependencies` and `resolve_wait_chat_paths`, confirm that `named_args` passed
to `execute_workflow` contains `wait_chats` with the expected list.

### Edge cases

- **No `%wait` directive**: `info.wait_names` is empty; `wait_chats` is not injected; `{{ wait_chats }}` raises
  `UndefinedError` (desired — matches `N` behavior).
- **`%wait` with only `%wait:<duration>` / `%wait:<time>` (no agent names)**: These use `info.wait_duration` /
  `info.wait_until` but leave `info.wait_names` empty. `wait_chats` is not injected — correct, since there are no peer
  agents being waited for.
- **Waited-for agent failed**: `done.json` exists but `outcome != "completed"`. The `response_path` field is still
  written (see `build_done_marker` line ~487 — `completed` outcome always includes result fields, and non-completed
  omits them). So the list entry is skipped. Users can still reference the failed agent via `#resume:<name>` if needed;
  `wait_chats` is specifically for successful-run transcripts.
- **`response_path` is a `~`-prefixed string**: Leave as-is. Jinja renders the literal string; downstream `@`-reference
  expansion in `preprocess_prompt_late` already handles `~` expansion. This also matches how `SASE_AGENT_CHAT_PATH`
  stores paths elsewhere.
- **Duplicate names in `%wait:a` `%wait:a`**: The directive extractor already collects duplicates in order
  (`_MULTI_VALUE_DIRECTIVES`). We preserve that — `wait_chats` will contain the same path twice. Cheap and predictable;
  deduping would surprise users who wrote it deliberately.

### Not in scope

- Exposing the waited-for agents' outcomes, names, or diffs as Jinja vars (would warrant a richer `wait_agents` dict if
  requested later).
- Auto-inlining transcripts (that's `#resume:<name>`'s job).
- Resolving `wait_chats` for deferred/absolute-time waits (`%wait:5m`, `%wait:2026-04-23T12:00`) — these wait for wall
  clock, not agents.
- Documentation updates to `xprompt.md` (can follow in a separate doc-only change once the feature lands).
