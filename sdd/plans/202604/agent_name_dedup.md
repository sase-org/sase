---
create_time: 2026-04-28 15:16:08
status: wip
prompt: sdd/prompts/202604/agent_name_dedup.md
---
# Agent Name De-duplication Plan

## Context

The Agents tab displays agent names from `agent_meta.json` / `done.json`. Dismissed agents are renamed with a `YYmmdd.`
prefix, and revive currently strips that prefix via `allocate_revived_name()`. If the stripped name is already active,
the current code falls back to a fresh auto-name such as `a`, which preserves uniqueness but loses the original base
name.

Agent launch writes `agent_meta.json` in `extract_directives_and_write_meta()` and then calls `claim_agent_name()`.
Today `claim_agent_name()` strips names from stale non-done agents but intentionally leaves completed agents alone, so
an explicit `%name:<name>` can coexist with a completed visible agent that already has the same name.

## Goal

Keep every visible Agents-tab name distinct while preserving user-chosen base names as much as possible:

- Reviving `YYmmdd.foo` should restore `foo` when free, otherwise choose a deterministic numeric variant such as
  `foo.2`.
- Starting an agent with an explicit `%name:foo` should let the new agent keep `foo` and rename the existing visible
  conflicting agent to the next numeric variant using the same policy.
- Batch operations must reserve names in one pass so two revived agents do not choose the same suffix.

## Proposed Design

Add shared name-allocation helpers in `sase.agent.names`, close to the current active-name scan logic:

- `dedupe_agent_name(base, reserved=None) -> str`: return `base` if unused, otherwise `base.2`, `base.3`, and so on,
  skipping names already in `reserved`.
- Keep `reserved` mutable for batch revive, matching the existing `allocate_revived_name(..., reserved=...)` pattern.
- Update `allocate_revived_name()` to strip the dismissal prefix and call the numeric de-duper instead of falling back
  to a fresh auto-name.

Extend `claim_agent_name()` for explicit claims:

- Add an optional mode/flag that tells the function this is an explicit user claim and existing visible conflicts should
  be renamed instead of preserved.
- Scan `~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json` for visible conflicts excluding the claiming directory.
- Treat completed agents and live non-completed agents as visible; keep the current stale non-done cleanup behavior for
  dead artifacts.
- Rename conflicting existing artifacts to numeric variants and write the new name to both `agent_meta.json` and
  `done.json` when those files contain the old name. If the conflict is through `workflow_name`, rename `workflow_name`
  too so references and reservation stay coherent.
- Use a reserved set seeded from active names plus the claiming name, removing the old conflicting name before choosing
  that conflict's replacement.

Wire explicit-name detection in the runner:

- `extract_prompt_directives()` currently returns only the resolved name, so bare `%name` and explicit `%name:<name>`
  are indistinguishable after extraction.
- Add a small boolean to `PromptDirectives` indicating whether the name directive had an explicit non-empty argument.
- In `extract_directives_and_write_meta()`, pass the explicit-claim flag to `claim_agent_name()` only when the prompt
  contained `%name:<name>` (or equivalent parenthesized/backtick explicit form), not for auto-names or
  `SASE_REPEAT_NAME`.

## Tests

Add or update focused tests:

- Revive: `260428.foo` with active `foo` becomes `foo.2` instead of `a`.
- Revive batch: multiple conflicts reserve sequential numeric names.
- Names/claim: explicit claim of `foo` renames an existing completed visible `foo` to `foo.2`, while the claiming
  artifact remains `foo`.
- Names/claim: explicit claim renames an existing live non-done `foo` to `foo.2` but still strips stale dead non-done
  conflicts as before.
- Directives/runner: explicit `%name:foo` triggers explicit claim mode; bare `%name` and auto-generated names do not.

## Verification

Run targeted tests first:

```bash
just install
pytest tests/test_agent_revive.py tests/test_agent_names.py tests/test_agent_names_extract.py
```

Then run the repo-required check:

```bash
just check
```
