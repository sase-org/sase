---
create_time: 2026-05-10 14:00:23
status: done
prompt: sdd/prompts/202605/telegram_kill_dismisses_agent.md
---
# Telegram "Kill" button: dismiss the killed agent so it doesn't reappear as FAILED

## Problem

When the user presses the **Kill** button in a Telegram launch message, the agent process is sent `SIGTERM` and dies,
then later shows up in the `sase ace` agents tab with status **FAILED**. The user expectation is that a
deliberately-killed agent should not appear in the agents list at all (same behavior as pressing `x` on the agent in the
TUI).

## Root cause

There are two separate kill paths in the codebase, and only one of them updates the `dismissed_agents` index that the
agents tab uses to filter the list:

### Path A — TUI kill (`x` in `sase ace`) — works correctly

`src/sase/ace/tui/actions/agents/_killing.py:135-153, 290-334`

1. `os.killpg(pid, SIGTERM)` is sent to the agent process group.
2. `_apply_killed_agents_in_memory()` adds the agent's `(AgentType, cl_name, raw_suffix)` identity to the in-memory
   `self._dismissed_agents` set and removes the row.
3. `_run_kill_persistence_async()` calls `save_dismissed_agents(dismissed_snapshot)` to persist the index to
   `~/.sase/dismissed_agents.json`.
4. The agent eventually writes `done.json` with `outcome="failed"`, but the agents-tab loader filters it out because its
   identity (or its `raw_suffix`) is in the dismissed-agents set
   (`src/sase/ace/tui/actions/agents/_loading_helpers.py:171-188`).

### Path B — `kill_named_agent` (Telegram, gchat, `sase agents kill`) — broken

`src/sase/agent/running.py:344-475`

This function is the canonical "external kill" entry point used by:

- Telegram Kill button → `_handle_kill_from_callback` → `kill_named_agent(agent_name)`
  (`sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py:617-642`, `:1258-1277`)
- gchat Kill button → `sase-gchat/src/sase_gchat/scripts/sase_gc_inbound.py:594-612`
- CLI `sase agents kill` → `src/sase/agents/cli_kill.py:11-21`
- mobile-agents façade → `src/sase/integrations/_mobile_agent_deps.py:41-45`

It only does two things relevant to "hiding":

1. `os.killpg(pid, SIGTERM)` (line 431).
2. Releases the workspace claim (lines 448-464).

It **does not** add the killed agent's identity to `~/.sase/dismissed_agents.json`. So when the runner subsequently
writes `done.json` with `outcome="failed"`, the loader at `_done_loaders.py:104-115` and `running.py:223-278` classifies
the agent as **FAILED** and the agents-tab filter has no entry to suppress it.

### Secondary issue (live TUI staleness)

`self._dismissed_agents` is loaded **once** at TUI startup (`src/sase/ace/tui/actions/_state_init.py:336`) and never
re-merged from disk. Even if `kill_named_agent` writes to `dismissed_agents.json`, a TUI that was already open when the
Telegram kill happened won't pick up the new entry on its next agent-list refresh — only a freshly-launched TUI will. We
need to merge on-disk additions into the in-memory set on each refresh so external dismissals (Telegram, gchat, CLI)
become visible to a running TUI.

## Goals

1. Telegram (and gchat / CLI / mobile) kills hide the agent from the `sase ace` agents tab the same way TUI kills do.
2. A `sase ace` TUI that is already running picks up dismissals made by external processes on the next refresh.

## Non-goals

- Changing the runner's exit-code → `outcome="failed"` mapping in `done.json`. The agent is still genuinely "failed"
  from the runner's point of view; we hide it via dismissal rather than inventing a new outcome value (which would
  ripple into the loader, status buckets, status overrides, retry chain, integrations, etc.).
- Auto-dismissing agents that crashed on their own. Only user-initiated kills dismiss; spontaneous failures still
  surface as FAILED so they can be triaged.
- Changing the gchat / CLI / mobile call sites themselves — fixing `kill_named_agent` covers them automatically.

## Design

### Fix 1 — `kill_named_agent` updates the dismissed-agents index

`src/sase/agent/running.py` — after a successful kill (i.e. anywhere we return a `_KillResult(True, ...)` for an agent
we actually signalled — including the `already_stopped` branch where the user clearly intended to dismiss), add the
agent's identity to `~/.sase/dismissed_agents.json`.

The identity tuple is `(AgentType.RUNNING, cl_name, raw_suffix)`:

- `AgentType.RUNNING` — `kill_named_agent` already only operates on `ace-run` artifacts (it parses
  `artifacts/ace-run/<timestamp>/`), so RUNNING is the right type here.
- `raw_suffix = artifacts_path.name` — already computed.
- `cl_name`:
  - **Non-home projects**: read from the matching workspace claim (`claim.cl_name`) — already iterated for the PID
    lookup at lines 412-415 / 459-464. Save it once during the PID scan.
  - **Home / orphan agents**: read from `agent_meta.json["cl_name"]`, falling back to `"unknown"` (matches the loader's
    fallback at `_done_loaders.py:104, 253`). Even if the cl_name is wrong, the loader's secondary `raw_suffix` index
    (`_loading_helpers.py:171-188`) still filters the agent out — so this fallback is safe.

Implementation shape (inside `kill_named_agent`, after the `os.killpg`

- workspace-release block, before the final `_KillResult` return):

```python
identity = (AgentType.RUNNING, cl_name or "unknown", timestamp)
dismissed = load_dismissed_agents()
if identity not in dismissed:
    dismissed.add(identity)
    save_dismissed_agents(dismissed)
```

Imports stay lazy / local to keep `sase.agent.running` from pulling in the `sase.ace` TUI package at import time (the
current file already keeps `sase.running_field` imports local for the same reason).

Failure to write the index must not turn a successful kill into a failure — wrap in try/except and log; the kill itself
succeeded.

### Fix 2 — TUI re-merges on-disk dismissed entries on each refresh

`src/sase/ace/tui/actions/agents/_loading.py` — at the top of the agent-refresh path (around line 155 / 185 where
`dismissed_snapshot = set(self._dismissed_agents)` is taken), merge in the current on-disk set so external additions are
picked up:

```python
on_disk = load_dismissed_agents()
new_external = on_disk - self._dismissed_agents
if new_external:
    self._dismissed_agents.update(new_external)
```

We **only union in** new entries — we never drop an in-memory entry that hasn't reached disk yet (the existing
optimistic flow writes to memory first, then to disk asynchronously, and we must not stomp on that pending state).

Same merge needs to happen before `dismissed_snapshot` is taken in `_apply_loaded_agents_prepared` and the auto-dismiss
path so that the already-killed-by-Telegram identities aren't re-classified as "recovered bundles" or "auto-dismissed"
by the loader's self-healing. A single helper method (e.g. `_merge_external_dismissals`) called at the start of the
refresh is the cleanest place.

### Telegram-side: nothing to change

The Telegram inbound handler is correct as-is — it delegates to `kill_named_agent`. Once Fix 1 lands, the existing call
at `sase_tg_inbound.py:632` automatically dismisses the agent.

## Files to change

- `src/sase/agent/running.py` — add dismissal write in `kill_named_agent` (Fix 1).
- `src/sase/ace/tui/actions/agents/_loading.py` (and possibly `_loading_helpers.py` for the helper) — merge on-disk
  dismissals on refresh (Fix 2).

## Tests

- **Unit (Fix 1)**: in the existing `kill_named_agent` test module, add tests that:
  - After a successful kill, `load_dismissed_agents()` contains the expected `(AgentType.RUNNING, cl_name, raw_suffix)`
    identity.
  - The `already_stopped` branch (process already dead) also writes the dismissal entry.
  - A failure of the index write does **not** flip `KillResult.success` to False.
  - `cl_name` is read from the workspace claim for non-home projects and from `agent_meta.json` (with `"unknown"`
    fallback) for home projects.
- **Unit (Fix 2)**: in the TUI loading tests, simulate an external process appending an identity to
  `~/.sase/dismissed_agents.json` while the TUI is running, then trigger a refresh and assert:
  - The identity ends up in `self._dismissed_agents`.
  - An agent with that identity / raw_suffix is filtered out of the rendered agents list (does not appear as FAILED).
  - In-memory-only pending dismissals are preserved across the merge.
- **Integration smoke**: launch a long-running ace-run agent, kill it via `sase agents kill <name>` (exercises the same
  code path as the Telegram button), then assert `sase ace`'s agents-tab listing does not include it.

## Rollout

Single PR. No migration, no schema change, no flag — the `dismissed_agents.json` format already supports the entries
we'd add, and the TUI's merge step is purely additive and safe to ship without a gate.
