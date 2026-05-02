---
create_time: 2026-03-26 11:09:01
status: done
prompt: sdd/prompts/202603/agent_ref_in_vcs_tags.md
---

# Plan: `#<vcs>:@<name>` Agent Reference in VCS Tags

## Summary

Add support for referencing another agent's PR/CL branch name inside VCS tags using `@<name>` syntax (e.g.,
`%wait:a #gh:@a Fix tests`). When resolved, `@a` is replaced with the `meta_changespec` from agent `a`'s done marker.

## Design Decisions (from user)

1. `@name` resolves to `meta_changespec` (branch name) from the referenced agent's `done.json`
2. Resolution happens after `wait_for_dependencies()`, before VCS workflow execution (Option A)
3. Pragmatic PR verification: check `meta_changespec` is present and non-empty
4. All failure modes produce errors (agent not found, still running, failed, no changespec)
5. Separate pre-processing step (not extending VCS tag regex)
6. All syntax variants: `#gh:@a`, `#gh_@a`, `#gh!!:@a`, `#gh??:@a`, `#gh(@a)`
7. Can only appear once per prompt

## Implementation

### Step 1: Add `resolve_agent_changespec()` to `src/sase/agent/names.py`

Add a function that looks up a named agent and returns its `meta_changespec`:

```python
def resolve_agent_changespec(name: str) -> str:
    """Resolve a named agent to its changespec (branch/CL name).

    Raises AgentRefError for all failure modes.
    """
    agent = find_named_agent(name)
    if agent is None:
        raise AgentRefError(f"No agent found with name '{name}'")
    if not agent.is_done:
        raise AgentRefError(
            f"Agent '{name}' is still running. "
            f"Use %wait:{name} to wait for it to complete before referencing it with @{name}"
        )
    if agent.outcome != "completed":
        raise AgentRefError(
            f"Agent '{name}' failed (outcome: {agent.outcome}). "
            f"Cannot reference a failed agent's PR with @{name}"
        )

    # Read done.json to get meta_changespec
    done_path = os.path.join(agent.artifacts_dir, "done.json")
    try:
        with open(done_path, encoding="utf-8") as f:
            done_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        raise AgentRefError(f"Cannot read done marker for agent '{name}': {exc}")

    step_output = done_data.get("step_output")
    if not step_output or not isinstance(step_output, dict):
        raise AgentRefError(
            f"Agent '{name}' has no step output. "
            f"The agent must have run a #pr workflow to create a PR."
        )

    changespec = step_output.get("meta_changespec")
    if not changespec:
        # Legacy fallback
        meta_new_cl = step_output.get("meta_new_cl")
        if meta_new_cl:
            value = str(meta_new_cl).strip()
            paren_idx = value.rfind(" (")
            changespec = value[:paren_idx].strip() if paren_idx > 0 else value
    if not changespec:
        raise AgentRefError(
            f"Agent '{name}' completed but did not create a PR/CL. "
            f"The agent must have run a #pr workflow to use @{name} syntax."
        )

    return str(changespec).strip()
```

Also add the exception class:

```python
class AgentRefError(Exception):
    """Raised when an @name agent reference cannot be resolved."""
```

### Step 2: Add `resolve_agent_refs_in_prompt()` to `src/sase/axe/run_agent_phases.py`

This phase function handles the pre-processing. It uses `_parsing.py` functions to find the VCS tag and `names.py` to
resolve the agent ref. Placing it in `run_agent_phases.py` keeps the dependency direction clean (`run_agent_phases` ->
`_parsing` + `agent.names`).

```python
def resolve_agent_refs_in_prompt(prompt: str) -> tuple[str, str | None]:
    """Resolve @name agent references in VCS tags.

    Normalizes underscore VCS refs, extracts the VCS tag, checks for
    @name in the ref portion, and replaces it with the agent's changespec.

    Returns (resolved_prompt, resolved_vcs_tag).
    """
    from sase.xprompt._parsing import (
        extract_project_from_vcs_tag,
        extract_vcs_workflow_tag,
        normalize_vcs_underscore_refs,
    )

    # Normalize #gh_@a -> #gh:@a so downstream only sees colon form
    prompt = normalize_vcs_underscore_refs(prompt)

    # Extract the VCS tag (handles leading %directives)
    vcs_tag = extract_vcs_workflow_tag(prompt)
    if not vcs_tag:
        return prompt, None

    # Check if the ref portion is an @name reference
    ref = extract_project_from_vcs_tag(vcs_tag)
    if not ref or not ref.startswith("@"):
        return prompt, vcs_tag

    agent_name = ref[1:]  # strip leading @
    if not agent_name:
        return prompt, vcs_tag

    # Resolve the agent reference
    from sase.agent.names import resolve_agent_changespec

    changespec = resolve_agent_changespec(agent_name)

    # Replace @name with the changespec in the VCS tag portion
    new_tag = vcs_tag.replace(f"@{agent_name}", changespec)
    resolved_prompt = prompt.replace(vcs_tag, new_tag, 1)

    # Re-extract vcs_tag from the resolved prompt
    resolved_vcs_tag = extract_vcs_workflow_tag(resolved_prompt)
    return resolved_prompt, resolved_vcs_tag
```

Key observations:

- `normalize_vcs_underscore_refs` converts `#gh_@a` -> `#gh:@a`, so all variants normalize to colon form before
  resolution
- `extract_vcs_workflow_tag` already handles leading `%directive` tokens
- `extract_project_from_vcs_tag` handles colon (`#gh:@a` -> `@a`), paren (`#gh(@a)` -> `@a`), and HITL variants
  (`#gh!!:@a` -> `@a`)
- The `replace(vcs_tag, new_tag, 1)` ensures we only modify the VCS tag portion, not body text that might contain `@`
  mentions

### Step 3: Integrate into `src/sase/axe/run_agent_runner.py`

After `wait_for_dependencies()` (line ~205) and before `AgentExecContext` creation (line ~220), add the resolution call.
The resolution should run unconditionally (not just when `%wait` is present) since the user said completed agents don't
need `%wait`.

Insert after line 215 (after the deferred workspace block, before `if info.approve`):

```python
            # Resolve @name agent references in VCS tags (e.g., #gh:@a -> #gh:branch_name).
            # This runs after wait_for_dependencies() so referenced agents are done.
            prompt, vcs_tag = resolve_agent_refs_in_prompt(prompt, vcs_tag)
```

Wait — looking at this more carefully, the resolution should happen even when there are no `%wait` directives (the user
said "this syntax can also be used for complete agents, in which case the `%wait` directive is not necessary"). So the
call should be placed right before `AgentExecContext` creation, outside the `if info.wait_names:` block:

```python
        # After wait block ends (line ~216), before AgentExecContext:

        # Resolve @name agent references in VCS tags
        prompt, vcs_tag = resolve_agent_refs_in_prompt(prompt)
```

This updates both `prompt` and `vcs_tag` (which was captured at line 130 with `@name` unresolved).

### Step 4: Tests

**File**: `tests/test_agent_ref_resolution.py`

Unit tests for `resolve_agent_changespec()`:

- Agent not found -> AgentRefError
- Agent still running -> AgentRefError with hint about %wait
- Agent failed -> AgentRefError
- Agent completed but no step_output -> AgentRefError
- Agent completed but no meta_changespec -> AgentRefError
- Agent completed with meta_changespec -> returns changespec
- Agent with legacy meta_new_cl format -> returns parsed name

Unit tests for `resolve_agent_refs_in_prompt()`:

- No VCS tag in prompt -> prompt unchanged
- VCS tag without @name -> prompt unchanged
- `#gh:@a` -> resolves to `#gh:branch_name`
- `#gh_@a` -> normalizes then resolves to `#gh:branch_name`
- `#gh!!:@a` -> resolves to `#gh!!:branch_name`
- `#gh??:@a` -> resolves to `#gh??:branch_name`
- `#gh(@a)` -> resolves to `#gh(branch_name)`
- `%wait:a #gh:@a Fix tests` -> resolves VCS tag, preserves body
- Prompt with `@mention` in body (not in VCS tag) -> body text unchanged

## Files Modified

1. `src/sase/agent/names.py` — Add `AgentRefError`, `resolve_agent_changespec()`
2. `src/sase/axe/run_agent_phases.py` — Add `resolve_agent_refs_in_prompt()`
3. `src/sase/axe/run_agent_runner.py` — Call `resolve_agent_refs_in_prompt()` before context creation
4. `tests/test_agent_ref_resolution.py` — New test file

## Edge Cases / Risks

- **Double normalization**: `normalize_vcs_underscore_refs` is called again later during embedded workflow expansion.
  Since `#gh:@a` has already been resolved to `#gh:branch_name` by then, the second normalization is a no-op (no `_` to
  normalize). Safe.
- **`@name` in body text**: Only the VCS tag portion is modified via targeted `replace(vcs_tag, new_tag, 1)`. Body text
  like "cc @someone" is untouched.
- **VCS tag re-extraction**: After resolution, `vcs_tag` is re-extracted from the resolved prompt. This ensures
  `AgentExecContext.vcs_tag` carries the resolved branch name.
