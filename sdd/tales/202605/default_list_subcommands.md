---
create_time: 2026-05-28 21:49:34
status: done
prompt: sdd/prompts/202605/default_list_subcommands.md
---
# Default list Subcommands

## Goal

Make every `sase` command group that owns an exact `list` subcommand dispatch to that `list` command when the group is
invoked without a child subcommand.

## Scope

Apply this to both top-level and nested command groups discovered from the argparse tree, including:

- `sase amd`
- `sase axe chop`
- `sase axe lumberjack`
- `sase bead`
- `sase chats`
- `sase file`
- `sase file-history`
- `sase memory`
- `sase memory episodes`
- `sase notify`
- `sase plugin`
- `sase sdd`
- `sase skills`
- `sase telemetry`
- `sase workspace`
- `sase xprompt`
- `sase agents tag`

Do not treat similarly named commands such as `list-agents` or `beads-list` as a `list` subcommand. Do not change
command groups without an exact `list` child; for example `sase agents` should continue to default to `status`, and
`sase init` should continue to run the onboarding coordinator.

## Design

Add a small argparse utility in `src/sase/main/parser.py` that walks the completed parser tree after all command
registrations and help sorting. For every `_SubParsersAction` whose choices include `list`, set the subparser action to
not-required and set the parent parser defaults so the destination field resolves to `"list"` when omitted.

The helper should also copy the `list` parser's argument defaults onto the parent parser. This prevents default-list
dispatch from producing namespaces that are missing list-handler fields such as `json`, `limit`, `query`, `project`, or
`path`.

Keep the implementation centralized instead of editing every parser registration by hand. That makes the behavior
automatic for future command groups that add an exact `list` subcommand.

## Compatibility Notes

This intentionally changes existing legacy behavior for `sase notify` with no subcommand: it should now list
notifications rather than create one implicitly. Creation remains available as `sase notify create`.

Existing handler-level defaults for `amd`, `memory`, and `skills` can remain harmless fallback logic, but tests should
assert the parser now resolves their omitted subcommand to `"list"`.

## Tests

Add parser coverage that walks all subparser actions and asserts every group with an exact `list` choice has an omitted
subcommand default of `"list"` with the expected list-parser defaults.

Update targeted parser/handler tests that currently expect bare `amd`, `memory`, or `skills` to parse as `None`.

Add or update focused tests for commands that previously errored on missing subcommands, especially `chats`, `file`,
`file-history`, `plugin`, `workspace`, `xprompt`, `bead`, and nested groups like `memory episodes`, `agents tag`,
`axe chop`, and `axe lumberjack`.

## Verification

Run focused pytest coverage for parser and affected command handlers first. Because this repo requires it after file
changes, run `just install` if needed and finish with `just check`.
