---
create_time: 2026-04-30 18:45:06
status: done
---
# Plan: Resume-Based Agent Names

## Goal

When a newly launched agent's top-level prompt resumes another agent with `#resume:<name>` and the user did not provide
an explicit name, assign the new agent the first available name of the form `<name>.r<N>`, starting at `N = 1`. This
should make resumed agents sort/group with the agent they resumed in the Agents tab's project grouping, while preserving
all existing explicit naming behavior.

## Current Behavior and Constraints

- Agent names are assigned in `src/sase/axe/run_agent_phases.py` by `extract_directives_and_write_meta()`.
- `#resume:<name>` is expanded earlier in `run_agent_runner.py` via `preprocess_prompt_xprompts()`, so the resume token
  is gone before directive extraction currently decides the agent name.
- Existing `%name:<value>` / `%n:<value>` already has a clear "explicit name wins" contract through
  `PromptDirectives.name_explicit`.
- Bare `%name` is not explicit today; it asks for an auto-generated name.
- Existing grouping in `src/sase/ace/tui/models/agent_groups/_keys.py` only treats names with a dot as having a root.
  That means `foo.r1` can group with `foo.bar`, but not reliably with a dotless parent named `foo`.
- Repeat and multi-model fan-out inject `%name` directives before the runner sees each spawned prompt, so they need
  dedicated handling if they should preserve the new resume-based grouping.

## Design

### 1. Preserve the Raw Resume Signal

Keep a copy of the prompt after alias resolution but before xprompt expansion in the runner. Pass that raw/resolved
prompt into `extract_directives_and_write_meta()` as an optional keyword argument, so existing unit tests and non-runner
call sites keep working.

The naming decision should be based on that pre-expansion prompt. This avoids accidentally naming from `#resume` text
embedded inside the injected "Previous Conversation" section.

### 2. Add Resume-Name Parsing and Allocation Helpers

Add a small helper near the agent naming code, likely under `src/sase/agent/names/`, that:

- Finds top-level `#resume` references using the same syntaxes already accepted by chat history parsing:
  - `#resume:foo`
  - `#resume(foo)`
  - `#resume:`foo bar``
- Ignores `#resume_by_chat`, because that argument is a chat path, not an agent name.
- Protects fenced code blocks and disabled xprompt regions, matching existing directive/xprompt behavior.
- Returns the first `#resume` target in textual order when multiple are present.

Add an allocation helper that scans the same active visible names used by auto-naming and returns the first candidate
`<resume_name>.r<N>` not already reserved. Use positive integers starting at `1`; if `foo.r1` exists and `foo.r3`
exists, choose `foo.r2`.

### 3. Naming Precedence

In `extract_directives_and_write_meta()`, use this order:

1. Explicit `%name:<value>` / `%n:<value>` / `%name(value)` / backtick variants: keep existing behavior exactly.
2. Top-level `#resume:<name>` with no explicit `%name`: use `<name>.r<N>`.
3. Repeat-provided `SASE_REPEAT_NAME`: keep existing repeat behavior unless repeat launcher has already chosen
   resume-derived names.
4. Bare `%name`: keep existing auto-generated name when there is no resume-derived name.
5. Existing normal auto-name fallback.
6. Preserve `SASE_AGENT_AUTO_DISMISS`: hidden auto-dismiss agents still get no auto name.

This means bare `%name` plus `#resume:foo` will produce `foo.r<N>`, because bare `%name` is not an explicit
user-selected name under the existing directive model.

### 4. Fan-Out Cases

Handle fan-out at the point where fan-out names are currently chosen:

- `%repeat:N #resume:foo` with no explicit `%name` should spawn agents named `foo.r<N>`, `foo.r<N+1>`, etc., and use
  those exact names in the injected `%wait:<previous>` chain.
- Multi-model fan-out with `#resume:foo` and no explicit `%name` should use a resume-derived base, then append model
  suffixes, e.g. `foo.r1.claude`, `foo.r1.codex`. These still group under `foo`.
- If the user supplies an explicit base/name in either fan-out path, preserve existing explicit behavior.

### 5. Grouping Adjustment

Update the Agents-tab name-root calculation so a dotless agent can share a root with dotted descendants:

- Treat a named dotless agent's root as its own full name for grouping purposes.
- Keep singleton suppression intact, so a lone dotless agent still renders exactly as it does today.
- Add regression coverage for `foo` and `foo.r1` producing a shared name-root group under project sorting.

This is needed for the stated outcome. Without it, `foo.r1` is not guaranteed to group with a parent named `foo`.

### 6. Distinctness and Races

Use a narrow agent-name allocation lock for resume-derived allocations so two concurrent `#resume:foo` launches do not
both select `foo.r1`. The lock should cover scanning active names and writing/claiming the selected name for the current
artifact directory. Keep this scoped to the naming subsystem and avoid changing unrelated workspace or ChangeSpec
locking.

Existing auto-name behavior can remain as-is unless tests expose a shared helper opportunity. The goal here is to make
the new resume-derived path distinct by construction.

## Test Plan

Add focused tests in these areas:

- Resume parser:
  - colon, paren, and backtick syntax
  - ignores `#resume_by_chat`
  - ignores fenced-code and disabled-region references
  - first `#resume` wins when multiple are present
- Resume allocator:
  - chooses `foo.r1` when free
  - skips existing `foo.r1`
  - fills gaps
  - treats visible done/running names as reserved, consistent with current auto-name behavior
- Runner metadata:
  - `#resume:foo do work` writes `agent_meta.json` with `name = "foo.r1"`
  - `%name:bar #resume:foo` writes `bar`
  - bare `%name #resume:foo` writes `foo.r1`
  - auto-dismiss still suppresses naming
- Fan-out:
  - repeat with `#resume:foo` and no explicit name emits `foo.r1`, `foo.r2`, ...
  - repeat with explicit `%name:bar` keeps `bar.1`, `bar.2`, ...
  - multi-model with `#resume:foo` uses `foo.r1.<runtime>` names
- Agents-tab grouping:
  - dotless `foo` and resumed `foo.r1` share a name-root group
  - lone dotless and lone dotted agents still suppress the extra banner

Run targeted tests first:

```bash
pytest tests/test_agent_names.py tests/test_agent_names_extract.py tests/test_repeat_launcher.py tests/test_directives_split_models.py tests/ace/tui/models/test_agent_groups_layout.py tests/ace/tui/models/test_agent_groups_ordering.py
```

Then run repo checks after source changes:

```bash
just install
just check
```

## Implementation Order

1. Add resume parsing/allocation helpers and unit tests.
2. Thread the pre-expansion prompt through the runner into directive extraction.
3. Apply resume-derived naming in `extract_directives_and_write_meta()`.
4. Update repeat and multi-model naming paths.
5. Update Agents-tab name-root grouping and tests.
6. Run targeted tests, then `just install` and `just check`.
