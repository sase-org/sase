---
create_time: 2026-06-18 20:03:33
status: done
prompt: sdd/prompts/202606/default_list_notice.md
---
# Default List Delegation Notice Plan

## Goal

Make SASE's implicit `list` subcommand convention visible at runtime and document the convention as a formal CLI rule.

When a command group has an exact `list` child and the user invokes that command group without choosing a child
subcommand, SASE should print a short notice before running the list handler. Explicit `list` invocations should not
print the notice.

## Current Shape

The parser already has a centralized `_default_list_subcommands()` helper in `src/sase/main/parser.py`. It recursively
finds subparser groups with an exact `list` child, makes the subparser optional, sets the public subcommand destination
to `"list"`, and copies the list parser's defaults onto the parent parser.

Current implemented groups include:

- `sase agent`
- `sase agent tag`
- `sase amd`
- `sase axe chop`
- `sase axe lumberjack`
- `sase bead`
- `sase chat`
- `sase file`
- `sase file-history`
- `sase memory`
- `sase notify`
- `sase plan`
- `sase plugin`
- `sase project`
- `sase project alias`
- `sase prompt`
- `sase sdd`
- `sase skill`
- `sase telemetry`
- `sase workspace`
- `sase xprompt`

The current parser only records the final public value, such as `agent_subcommand="list"`, so handlers cannot
distinguish an omitted child from an explicit `list`.

## Proposed Implementation

1. Extend the centralized parser defaulting helper rather than changing individual command handlers.
   - When `_default_list_subcommands()` defaults a command group to `list`, add private metadata to the parsed namespace
     identifying the command path that was defaulted.
   - Set matching private metadata on explicit child parsers so explicit `list` and explicit non-`list` commands do not
     look defaulted.
   - Keep all existing public parsed attributes unchanged.

2. Add a small public-internal helper near the parser or entry layer to consume that metadata and format notices.
   - Notice wording should be direct and stable, for example:
     `No subcommand provided for 'sase agent'; delegating to 'sase agent list'.`
   - Print notices in `src/sase/main/entry.py` immediately after parsing and before command dispatch, so the message
     starts the command output.
   - Support nested defaults such as `sase agent tag` and `sase project alias` while printing only the actually omitted
     command group.

3. Add focused parser/entry tests.
   - Parser-level tests should assert the default metadata appears for omitted command groups and is absent for explicit
     `list` or explicit non-`list` subcommands.
   - CLI entry tests should assert a bare defaulted command prints the delegation notice before handler output.
   - Existing tests for copied list defaults should remain valid.

4. Update `memory/cli_rules.md`.
   - Formalize that command groups with an exact `list` child default to that child when invoked bare.
   - Require a runtime notice for bare invocations that delegate to `list`.
   - Clarify that flags owned by `list` still belong after the explicit `list` token, matching the current docs.
   - Preserve existing rules about sorted help, short aliases, and high-quality help output.

## Verification

Run the focused parser tests after implementation:

```bash
.venv/bin/pytest tests/main/test_parser_help.py
```

Run a few smoke commands through the CLI to verify notice placement:

```bash
.venv/bin/sase plan
.venv/bin/sase plan list
.venv/bin/sase agent tag
```

If the focused tests are clean, run the broader project check command from the local build instructions.
