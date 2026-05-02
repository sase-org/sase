---
create_time: 2026-04-24 21:40:25
status: done
prompt: sdd/prompts/202604/retry_as_new_agent.md
---
# Retry as a Brand-New Agent

## Problem

When an sase agent hits a retryable error (rate limit, transient provider failure, context overflow, etc.), the current
retry loop in `src/sase/axe/run_agent_exec_retry.py:55` reuses the **same Python process** and:

- Calls `prepare_workspace()` — which, unless `preserve_workspace=True`, **wipes the workspace clone** and re-pulls from
  the update target (loses uncommitted file edits the agent made).
- Snapshots the previous attempt's `live_reply.md` into `attempts/<N>/` but **does not seed the next attempt with any
  structured continuation context** — only an optional one-liner `continuation_prompt` nudge.
- Keeps the same agent identity and chat file, so the TUI cannot show a clean "this is attempt #3" view; the user sees
  the agent flicker between `RUNNING → retrying → running_retry → …` without a stable record of what each attempt did.
- Loses any `SASE_MODEL_OVERRIDE` / fallback model state once the process eventually exits.

The user wants each retry to instead be a **brand-new detached agent** (as if `sase run -d` had been invoked), with a
clear UI indicator that it is a retry and an unambiguous link back to the failed parent.

## Goals

1. **Replace the in-process retry loop with a cross-process spawn** for every retryable error path. The original agent's
   process snapshots its state, marks itself FAILED-but-retried, spawns a fresh detached agent, and exits.
2. **Preserve all useful context across the boundary**: chat history, on-disk workspace state, plan file, agent name,
   model/provider, last error snippet, and a continuation nudge.
3. **Make the retry lineage first-class** in the data model: every retry agent stores a pointer to its immediate parent
   failed agent and to the chain root, and every failed-then-retried agent stores a pointer forward to the retry that
   succeeded (or failed and retried again).
4. **Make the TUI presentation beautiful**: retries nest under their parent in the Agents tab, show a clean `↻ Retry #N`
   badge, and the detail panel renders the full retry chain as a breadcrumb. A failed-and-retried agent's status
   visually distinguishes "terminal failure with downstream retry" from "terminal failure, dead end."
5. **No silent context loss**: on-disk file edits the failed agent made are carried into the retry by reusing the same
   workspace number (skip the `prepare_workspace()` rebuild on the retry side).

Non-goals (deferred):

- User-initiated "try again" TUI keymap on a finished FAILED agent. The machinery this plan introduces makes it trivial
  to add later, but the first cut is automatic-only.
- Cross-process retries for non-LLM errors (workspace/git/hook failures). Same machinery applies; defer until the
  LLM-error path is proven.
- Migrating already-failed agents in users' artifact directories. Backward-compatible reads only; no migration.

## Design

### Lifecycle of a retry

```
   ┌─────────────────────────┐     LLM error, retryable
   │  Agent A (attempt 1)    │ ─────────────────────────┐
   │  status: RUNNING        │                          │
   └─────────────────────────┘                          ▼
                            ┌───────────────────────────────────────────────┐
                            │ 1. snapshot_attempt() — same as today         │
                            │ 2. write retry_handoff.json into A's          │
                            │    artifacts dir                              │
                            │ 3. spawn fresh detached agent B via the same  │
                            │    `spawn_agent_subprocess()` used by         │
                            │    `sase run -d`, passing A's workspace_num   │
                            │    and workflow type so the workspace         │
                            │    claim transfers without rebuild            │
                            │ 4. mark A status = FAILED with                │
                            │    retried_as_timestamp = B.timestamp         │
                            │ 5. exit A's process cleanly                   │
                            └───────────────────────────┬───────────────────┘
                                                        ▼
   ┌─────────────────────────┐                ┌─────────────────────────┐
   │  Agent A                │  ←── parent ── │  Agent B (retry #1)     │
   │  status:                │                │  status: RUNNING        │
   │   FAILED (RETRIED)      │  ── retry ──→  │  retry_of: A.timestamp  │
   │  retried_as: B          │                │  retry_attempt: 1       │
   └─────────────────────────┘                │  retry_chain_root: A    │
                                              └─────────────────────────┘
```

If B also fails retryably, the same flow runs again and produces Agent C with `retry_attempt = 2`,
`retry_of_timestamp = B.timestamp`, `retry_chain_root_timestamp = A.timestamp`. The chain is a singly-linked list
forward (`retried_as_timestamp`) and singly-linked backward (`retry_of_timestamp`), with `retry_chain_root_timestamp`
short-circuiting walks for display.

### Hand-off file: `retry_handoff.json`

Written by the failing process into A's artifacts dir before spawn. Loaded by B's runner at startup. Schema:

```json
{
  "parent_timestamp": "<A's artifacts timestamp>",
  "retry_attempt": 1,
  "chain_root_timestamp": "<A's artifacts timestamp>",
  "error_snippet": "...",
  "error_category": "context_overflow" | "rate_limit" | "transient" | "other",
  "continuation_prompt": "...optional nudge text...",
  "original_prompt": "<the prompt A was last running with>",
  "chat_path": "<absolute path to A's saved chat .md>",
  "plan_path": "<plan_path.json contents, if any>",
  "role_suffix": ".plan" | ".code" | null,    // inherited from A
  "workspace_num": 7,
  "workspace_dir": "/path/to/sase_7",
  "vcs_ref": ["github", "feature/x"] | null,
  "agent_name": "...",                         // inherited from A
  "agent_model": "...",                        // inherited from A
  "agent_llm_provider": "claude",              // inherited from A
  "agent_vcs_provider": "GitHub",              // inherited from A
  "fallback_model": "claude-haiku-4-5" | null,
  "use_fallback": true | false,
  "qa_sections": [...],                        // any in-flight Q&A history
  "feedback_bullets": [...]                    // any in-flight feedback history
}
```

The runner already reconstructs all of these fields from environment + arguments today; the hand-off file just collects
them so the spawning side does not have to re-derive them and so that diagnostic tooling can read them.

### Spawning the retry

Reuse `spawn_agent_subprocess()` from `src/sase/agent/launcher.py:24` directly. It already handles: writing the prompt
to a temp file, setting `SASE_AGENT_*` env vars, claiming workspace, registering the running-field record, and detaching
via `start_new_session=True`.

Two extensions:

1. **Workspace claim transfer.** Before the parent exits it must release its existing workspace claim (so the child's
   `claim_workspace()` does not race against it) without freeing the workspace for other agents. Cleanest
   implementation: add a `claim_kind="retry"` mode to `claim_workspace` that atomically swaps the PID on the existing
   claim record instead of creating a new one. The parent calls `release_for_retry()` which marks the record as
   in-transition; the child's claim sees the in-transition marker and adopts it.

2. **New env vars** consumed by the runner to steer it into "retry mode":
   - `SASE_AGENT_RETRY_HANDOFF`: path to `retry_handoff.json`
   - `SASE_AGENT_RETRY_OF_TIMESTAMP`, `SASE_AGENT_RETRY_ATTEMPT`, `SASE_AGENT_RETRY_CHAIN_ROOT_TIMESTAMP`: also recorded
     into the new agent's `agent_meta.json` for trivial loader access without re-reading the hand-off.

The new prompt the child agent runs with is constructed as:

```
#resume:<parent_agent_name>            ← only if parent had a stable name; otherwise resume by chat path
<continuation_prompt>                  ← e.g. context-overflow nudge
<original_prompt>                      ← the prompt the parent was working on
```

If the parent has no `agent_name`, fall back to a synthetic resume directive that points at the saved chat path
(machinery already exists via `xprompts/resume_by_chat.yml`).

### Parent's terminal state

The parent process, before exiting, performs:

1. `RetryState.delete_from(artifacts_dir)` — clear in-process retry state.
2. Update `agent_meta.json`: add `retried_as_timestamp = B.timestamp`, `retry_terminal = true`,
   `retry_handoff_path = ".../retry_handoff.json"`.
3. Write a `done.json` with `outcome = "failed"` and `retried_as_timestamp` echoed at the top level so the loader in
   `src/sase/ace/tui/models/_loaders/` can construct linkage without opening `agent_meta.json`.
4. Save the chat history (`save_chat_history()` is already called from the existing failure path) so the child can
   resume from it.
5. Exit with the same nonzero code the in-process retry would have raised after exhausting attempts. (Distinct from
   "exit 0 because retry succeeded eventually" — the parent process never knows the outcome of B.)

### Data-model additions

`src/sase/ace/tui/models/agent.py` `Agent` dataclass — new fields (all `None` / 0 by default for back-compat):

| Field                        | Type          | Source                                                        |
| ---------------------------- | ------------- | ------------------------------------------------------------- |
| `retry_of_timestamp`         | `str \| None` | `agent_meta.retry_of_timestamp`                               |
| `retry_attempt`              | `int`         | `agent_meta.retry_attempt` (default 0, meaning "not a retry") |
| `retry_chain_root_timestamp` | `str \| None` | `agent_meta.retry_chain_root_timestamp`                       |
| `retried_as_timestamp`       | `str \| None` | `agent_meta.retried_as_timestamp` (set on the failed parent)  |
| `retry_terminal`             | `bool`        | `agent_meta.retry_terminal`                                   |
| `retry_error_category`       | `str \| None` | from `retry_handoff.json` echoed into meta                    |
| `retry_chain_siblings`       | `list[Agent]` | populated at load time, like `followup_agents`                |

Two new derived properties:

- `is_retry_attempt`: `retry_attempt > 0`
- `is_retried_parent`: `retried_as_timestamp is not None`

### Loader changes

`src/sase/ace/tui/models/_loaders/_artifact_loaders.py` — when reading `agent_meta.json` and `done.json`, populate the
new fields. After all agents in a project are loaded, walk the list once and:

- For every retry agent, find its parent by `retry_of_timestamp` and append it to the parent's `retry_chain_siblings`
  (the parent already exists in the list — `agent_meta.json` writes happen before `done.json`).
- For every retried parent, set its display `status` to `"FAILED (RETRIED)"` (a new status string) instead of
  `"FAILED"`. Old failed agents with no `retried_as_timestamp` keep `"FAILED"`.

The `_is_child_of` helper in `src/sase/ace/tui/actions/agents/_revive.py:15` is extended to recognize retry children
analogously to follow-up children, so the existing dismiss/revive bulk operations on a parent also sweep its retry
chain.

### TUI presentation (the "beautiful" part)

**Agents tab list — retry chain nests under the original.** The very first agent in a chain (`retry_attempt == 0`)
renders normally. Subsequent retries render indented one level under it, prefixed with a glyph from the existing
tree-decoration palette:

```
  feature/login                                         RUNNING     2026-04-24 14:12:03
    ↳ ↻ retry #1 — context overflow                    RUNNING     2026-04-24 14:18:21
  feature/payments                                     FAILED (RETRIED)  2026-04-24 13:42:01
    ↳ ↻ retry #1 — rate limit                          FAILED (RETRIED)  2026-04-24 13:55:10
      ↳ ↻ retry #2 — rate limit                        DONE              2026-04-24 14:09:44
```

Indentation reuses the same renderer that handles `parent_timestamp`-based follow-ups today
(`src/sase/ace/tui/widgets/agent_list.py`). Each retry row displays the error category ("context overflow", "rate
limit", "transient", "other") so the user can pattern-match without opening the detail panel.

**Status colors and styles** — three buckets:

| Status                                | Color                                        | Notes                                  |
| ------------------------------------- | -------------------------------------------- | -------------------------------------- |
| `FAILED` (terminal, no retry)         | bright red                                   | unchanged                              |
| `FAILED (RETRIED)`                    | dim red + yellow `↻` glyph                   | "this failed but a retry took over"    |
| `RUNNING` / `DONE` on a retry attempt | normal color, with a small `↻N` badge prefix | so the user knows it's a retry attempt |

All four files listed in `src/sase/ace/AGENTS.md` ("ChangeSpec Suffix Syntax Highlighting") that govern style for new
suffix types must be updated:

1. `home/dot_config/nvim/syntax/saseproject.vim` (vim)
2. `src/sase/ace/display.py` (CLI Rich styling)
3. `src/sase/ace/query/highlighting.py` (`QUERY_TOKEN_STYLES`)
4. `src/sase/ace/tui/widgets/changespec_detail.py` (TUI Rich styling)

A new style key `retried_agent` (dim red + yellow glyph) is added in all four.

**Detail panel header — breadcrumb of the retry chain.** When the selected agent has `retry_attempt > 0` or
`retried_as_timestamp is not None`, render a breadcrumb at the top of the prompt panel:

```
↻ Retry chain (3 attempts):
  attempt 1 (FAILED · context_overflow)  [j: jump]
  attempt 2 (FAILED · rate_limit)        [k: jump]
  attempt 3 (RUNNING — current)
```

`j` / `k` navigate up and down the chain. The header lives in
`src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py` next to the existing follow-up display.

**Help modal** — `src/sase/ace/tui/modals/help_modal/` documents the retry chain and the navigation keymap. The
57-character box-width rule from `src/sase/ace/AGENTS.md` is honored.

**Footer** — the `j` / `k` chain-navigation keymap is added to `keybinding_footer.py`. It is conditional (only appears
when the selected agent is part of a retry chain), so by the project's footer convention it qualifies for the footer
rather than being help-modal-only.

### Configuration

Extend `ProviderRetryConfig` in `src/sase/llm_provider/retry_config.py:17` with one new field:

```python
spawn_new_agent: bool = False   # if True, retry by spawning a fresh detached agent; if False, retry in-process (legacy)
```

For the first release the field defaults to `False` (no behavior change unless opted in). Once shaken out, flip the
default in a follow-up change.

Plugin authors set this in their `llm_default_retry_config()` hook. The user can override per-provider in their merged
config file.

### Failure modes

- **Spawn raises `RuntimeError("Failed to claim workspace …")`.** Fall back to a single in-process retry attempt (the
  legacy code path) so the user is never worse off than today. Log a `retry_spawn_failed` metric.
- **No `agent_name` and no chat file.** The hand-off can still carry the original prompt and continuation; the child
  runs without `#resume`. We log a `retry_no_chat_history` metric.
- **Workspace already gone (deleted by user).** Same fallback as above; spawn would fail at workspace lookup.
- **Concurrent retries for the same parent.** Impossible by construction — the parent process exits after a successful
  spawn, and only the parent process can spawn retries of itself.
- **Retry budget exhaustion.** `ProviderRetryConfig.max_retries` continues to govern. The chain root's
  `retry_attempt = 0`; the budget is `max_retries` total spawns. Once exhausted, the failing process exits with `FAILED`
  (terminal, no `retried_as_timestamp`).

### Telemetry

- `LLM_RETRIES` (existing counter) keeps incrementing on every spawn, with a new label
  `mode={"in_process","spawn_new"}`.
- New counter `RETRY_SPAWNS_TOTAL{outcome="ok"|"fallback"|"failed"}` for spawn-side observability.

### Tests

- Unit tests for the new hand-off file round-trip (write parent side, read child side).
- Unit test for `Agent` loader: given fixture `agent_meta.json` files for a 3-deep chain, the loader produces the
  expected `retry_chain_siblings` linkage and status badges.
- Integration test using the existing fake LLM provider machinery: trigger a retryable error, assert the parent process
  exits with the failed-and-retried marker, the child process runs, and the chain is visible in `load_all_agents()`.
- TUI snapshot test for the Agents tab rendering of a retry chain (using the existing `pytest-textual-snapshot` setup).
- TUI snapshot test for the detail panel breadcrumb.
- Test that workspace files written by the parent agent (`echo foo > new_file.py`) are still present when the child
  agent starts (workspace transfer correctness).
- Test the spawn-failure fallback path: simulate `claim_workspace` returning `False`, assert a single in-process retry
  attempt is performed.

### Documentation / memory

- `memory/short/glossary.md` gets a new entry: **Retry chain** — definition, lineage fields, and where the spawn
  happens.
- `memory/short/gotchas.md` gets a note: spawn-on-retry is opt-in via `ProviderRetryConfig.spawn_new_agent`; in
  in-process mode workspace state may be wiped between attempts (existing behavior), in spawn mode it is preserved by
  design.

## Files most likely to change

- `src/sase/axe/run_agent_exec_retry.py` — replace the loop body with a spawn-and-exit branch when `spawn_new_agent` is
  true.
- `src/sase/axe/run_agent_retry_spawn.py` — **new module** containing `spawn_retry_agent(parent_ctx, error, tracker)`
  and the `retry_handoff.json` writer.
- `src/sase/axe/run_agent_runner.py` — at startup, detect `SASE_AGENT_RETRY_HANDOFF`, load it, and seed the initial
  `LoopState` from its contents.
- `src/sase/agent/launcher.py` — add a `claim_kind="retry"` parameter wired through `spawn_agent_subprocess` and on into
  `claim_workspace`.
- `src/sase/running_field.py` — implement `release_for_retry()` and the in-transition claim record.
- `src/sase/llm_provider/retry_config.py` — add `spawn_new_agent: bool` field.
- `src/sase/ace/tui/models/agent.py` — new dataclass fields and properties.
- `src/sase/ace/tui/models/_loaders/_artifact_loaders.py` — populate new fields, build chain linkage.
- `src/sase/ace/tui/widgets/agent_list.py` — render retry-chain indentation and badges.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py` — render the breadcrumb header.
- `src/sase/ace/tui/widgets/keybinding_footer.py` — `j` / `k` chain-navigation footer entries.
- `src/sase/ace/tui/modals/help_modal/bindings.py` and the help-modal box content — document the new keymap and the
  `FAILED (RETRIED)` status.
- All four `retried_agent` style files listed under "ChangeSpec Suffix Syntax Highlighting" above.
- `src/sase/ace/tui/actions/agents/_revive.py` — extend `_is_child_of` to include retry children.
- `memory/short/glossary.md`, `memory/short/gotchas.md`.

## Open questions to confirm before implementation

1. **Default for `spawn_new_agent`** — keep `False` initially (opt-in) and flip later, or flip to `True` immediately for
   built-in providers? Recommend opt-in for the first release.
2. **Workspace-transfer scope** — should this apply only to "live coding" workspaces (vcs-tracked branches), or also to
   home-mode agents? Recommend: both, since the home workspace is just `~` and there is nothing to prepare.
3. **Chain-root navigation key** — `j`/`k` collide with vim-style scrolling in some panels. If that is a concern, fall
   back to `[`/`]` (prev/next in chain) or shift-J/shift-K. To be confirmed during implementation.
4. **Per-attempt artifact dirs vs. per-agent artifact dirs** — under this design each retry gets its own timestamped
   artifacts dir (clean), and the legacy `attempts/<N>/` snapshot dirs become unnecessary in spawn mode. Recommend:
   still write the final attempt snapshot to the parent's `attempts/01/` for symmetry with in-process-mode reads, but
   stop writing further attempts since each retry is now its own dir.
