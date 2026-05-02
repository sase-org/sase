---
create_time: 2026-03-27 01:43:46
status: done
prompt: sdd/prompts/202603/fix_resume_self_resolution.md
---

# Plan: Fix `#resume:name` resolving to the current agent instead of the previous one

## Problem

When a user sends `%nj #gh:sase #resume:j ...`, the agent fails with a `FileNotFoundError` on `done.json`.

**Execution order causing the bug:**

1. `extract_directives_and_write_meta()` writes `agent_meta.json` with `name: "j"` and calls
   `claim_agent_name("j", artifacts_dir)` — this **strips** the name `"j"` from ALL previous agents (both `name` and
   `workflow_name` fields in `agent_meta.json` and `done.json`).
2. Later, during workflow execution, `#resume:j` calls `find_named_agent("j")`.
3. The only agent with name `"j"` is the **current running one** (the previous one was stripped).
4. `find_named_agent` prefers running agents over done ones, so it returns the current agent.
5. The resolve step tries to read `done.json` from the current agent's artifacts dir → `FileNotFoundError`.

**Root cause:** `claim_agent_name` runs before `#resume` workflow expansion, destroying the name mapping that `#resume`
depends on.

## Fix: Two-part change

### Part 1: `claim_agent_name` should preserve names on completed agents

**File:** `src/sase/agent/names.py`, function `claim_agent_name` (line 182)

Currently, `claim_agent_name` iterates over every artifact directory and strips the name from any agent that matches.
Change it to **skip artifact directories that have a `done.json`** present.

Completed agents should retain their identity — they've already finished their work and their name is part of their
historical record. The name claiming mechanism only needs to clear stale/running agents that would cause ambiguity for
new agent lookups.

**Change:** In `claim_agent_name`, before stripping, check if `done.json` exists in the artifact directory. If it does,
skip that directory entirely.

```python
def claim_agent_name(name: str, claiming_dir: str) -> None:
    ...
    for artifact_dir in ace_run_dir.iterdir():
        if not artifact_dir.is_dir():
            continue
        if artifact_dir.resolve() == claiming:
            continue
        # NEW: Don't strip names from completed agents — they need their
        # identity for #resume and historical lookups.
        if (artifact_dir / "done.json").exists():
            continue
        _strip_name_from_json(artifact_dir / "agent_meta.json", name)
        _strip_name_from_json(artifact_dir / "done.json", name)
```

**Why this is safe:** `find_named_agent` already handles multiple agents with the same name via its priority system:
running agents > done agents (by recency). So even if old done agents retain their names, the most recent one wins. And
`get_next_auto_name` checks both done and running agents to avoid collisions.

### Part 2: Add `only_done` parameter to `find_named_agent`

**File:** `src/sase/agent/names.py`, function `find_named_agent` (line 83)

Add an `only_done: bool = False` keyword parameter. When `True`, the function skips the "return running agent
immediately" shortcut (lines 165-169) and only considers done agents.

This is needed because even with Part 1, the current running agent would still match (it has `name: "j"` in its own
`agent_meta.json`) and would be returned before any done agent.

```python
def find_named_agent(name: str, *, only_done: bool = False) -> _NamedAgent | None:
    ...
    # Running agents take priority — return immediately [...]
    if not is_done:
        if not only_done and is_process_alive(data, artifact_dir):
            if exact or not data.get("parent_timestamp"):
                return agent
        continue
```

### Part 3: Update `resume.yml` to use `only_done=True`

**File:** `src/sase/xprompts/resume.yml`, resolve step (line 12)

Change:

```python
agent = find_named_agent(name)
```

To:

```python
agent = find_named_agent(name, only_done=True)
```

Also add a safety check for `agent.is_done`:

```python
agent = find_named_agent(name, only_done=True)
if agent is None:
    raise RuntimeError(f"No completed agent found with name: {name}")
if not agent.is_done:
    raise RuntimeError(f"Agent '{name}' is still running — cannot resume")
```

### Part 4: Add tests

**File:** `tests/test_agent_names.py`

1. **Test `claim_agent_name` preserves done agents:** Create a done agent with name "foo", then claim "foo" from a new
   directory. Assert that the done agent's `agent_meta.json` still has `name: "foo"`.

2. **Test `claim_agent_name` still strips running/stale agents:** Create a non-done agent with name "foo" (dead PID),
   then claim "foo". Assert that the non-done agent's name was stripped.

3. **Test `find_named_agent` with `only_done=True`:** Create a running agent and a done agent both named "foo". Call
   `find_named_agent("foo", only_done=True)`. Assert it returns the done agent.

4. **Test `find_named_agent` with `only_done=True` and no done agents:** Create only a running agent named "foo". Call
   `find_named_agent("foo", only_done=True)`. Assert it returns `None`.

### Existing test update

The existing test `test_strips_name_from_other_agents` creates a done agent and expects its name to be stripped. This
test needs to be updated to reflect the new behavior (done agents keep names).

## Files to modify

1. `src/sase/agent/names.py` — `claim_agent_name`, `find_named_agent`
2. `src/sase/xprompts/resume.yml` — resolve step
3. `tests/test_agent_names.py` — new tests + update existing test

## Risks and considerations

- **`resolve_agent_changespec` (used by `@j` syntax):** Already calls `find_named_agent` without `only_done`. The
  current behavior (prefer running, error if not done) is correct for `@j` — it tells the user to use `%wait`. No change
  needed.

- **`sase_chop_wait_checks.py` and `running.py`:** Both use `find_named_agent` without `only_done`. Their existing
  behavior (prefer running agents) is correct. No change needed.

- **Name accumulation:** Done agents will no longer have names stripped, so over time more agents retain names. But
  names are already held until dismissal (per `_get_active_agent_names`), and `find_named_agent` picks the most recent.
  This matches the existing lifecycle.
