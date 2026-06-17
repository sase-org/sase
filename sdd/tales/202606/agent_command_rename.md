---
create_time: 2026-06-17 07:49:29
status: done
prompt: sdd/prompts/202606/agent_command_rename.md
---
# Plan: Rename `sase agents` to `sase agent`

## Goal

Rename the public top-level command group from plural `sase agents` to singular `sase agent`.

The subcommands and behavior stay the same:

```bash
sase agent list
sase agent show
sase agent kill
sase agent tag
sase agent archive
sase agent artifacts layout
sase agent index
sase agent names migrate-auto
```

Bare `sase agent` should continue to default to `sase agent list` through the existing exact-`list` default parser
convention.

I will treat this as a breaking CLI rename, matching the recent `sase chats` -> `sase chat` and `sase agents status` ->
`sase agents list` changes. I will not keep a visible or hidden `sase agents` compatibility alias unless review asks for
one.

## Context Found

- The top-level parser is registered from `src/sase/main/parser.py` through `register_agents_parser()` in
  `src/sase/main/parser_agents.py`.
- Runtime dispatch happens in `src/sase/main/entry.py` with `args.command == "agents"`, then
  `src/sase/main/agents_handler.py` dispatches nested subcommands.
- `sase agents` currently has an exact `list` child, so the root parser's `_default_list_subcommands()` already makes
  bare `sase agents` parse as the list view. The same mechanism should work after the top-level command becomes `agent`.
- The concrete CLI implementation package is `src/sase/agents/`, but there is already a separate `src/sase/agent/`
  package for launch/runtime/name helpers. Renaming the implementation package wholesale would collide with that
  existing domain boundary. I will leave the lower-level `sase.agents.*` package and handler function names such as
  `handle_agents_index()` in place unless a name is directly part of the top-level parser/handler surface.
- The generated skill source `src/sase/xprompts/skills/sase_agents_status.md` documents the command. Its skill identity
  should remain `/sase_agents_status`; only command examples and explanatory text need to move to `sase agent ...`.
- `src/sase/xprompts/skills/sase_chats.md` uses the agents listing command as a fallback and also needs updating.
- `docs/configuration.md` currently has a stale table row that still calls the listing subcommand `status`; this should
  be corrected while renaming the surrounding command group.
- Live references to `sase agents ...` appear in README, docs, blog posts, smoke docs, publish workflow greps, CLI help
  examples, doctor next-step strings, TUI repair notices, JSON payload fields, nested usage text, tests, and the Phase 7
  perf benchmark prose/commands.
- Historical SDD prompts/tales/research and committed plan records may mention old commands as past artifacts. Those
  should be audited and classified after live surfaces are updated, not rewritten blindly.
- Per project memory, CLI changes must keep help excellent and sorted, public long options retain short aliases, and
  generated provider `SKILL.md` files must be regenerated from source rather than hand-edited.

## Proposed Changes

1. Rename the public parser and entry dispatch.
   - Rename `src/sase/main/parser_agents.py` to `src/sase/main/parser_agent.py`.
   - Rename `register_agents_parser()` to `register_agent_parser()`.
   - Register the top-level subparser as `agent`.
   - Update parser help text from "agents" command wording to singular command-group wording while preserving the domain
     meaning that the command operates on multiple agent runs.
   - In `src/sase/main/parser.py`, import and call `register_agent_parser()` in the alphabetically sorted command list.
   - Update compact root help from `agents` to `agent`, including the example `sase agent list`.
   - In `src/sase/main/entry.py`, dispatch `args.command == "agent"`.

2. Rename the top-level command handler surface.
   - Rename `src/sase/main/agents_handler.py` to `src/sase/main/agent_handler.py`.
   - Rename `handle_agents_command()` to `handle_agent_command()`.
   - Rename the argparse nested-subcommand destination from `agents_subcommand` to `agent_subcommand` so parsed
     namespaces match the public command spelling.
   - Keep imports from `sase.agents.cli_*` and lower-level handler names such as `handle_agents_list()` unchanged,
     because those modules manage collections of agent records and avoid colliding with the existing `sase.agent`
     package.
   - Update all top-level and nested usage strings to `sase agent ...`, including archive, artifacts layout, index,
     names, and tag usage messages.

3. Update emitted live command strings.
   - Update `src/sase/agents/cli_index.py` repair/verify command strings and JSON payload fields from
     `sase agents index ...` to `sase agent index ...`.
   - Update doctor checks and tests that render or assert those next steps.
   - Update ACE/TUI repair notices and any other live messages that tell users to run `sase agents ...`.
   - Update source docstrings/comments only when they describe the CLI command, not generic English references to
     multiple agents.

4. Update tests.
   - Rename/update the top-level dispatch test module or test descriptions from `sase agents` to `sase agent`.
   - Update parser assertions:
     - `parse_args(["agent"])` yields `command == "agent"` and `agent_subcommand == "list"`.
     - `parse_args(["agent", "list", "-a", "-j", "-p", "proj"])` preserves existing list flags.
     - `parse_args(["agents", ...])` is rejected, unless review explicitly requests an alias.
   - Update list-default coverage from `sase agents` / `sase agents tag` to `sase agent` / `sase agent tag`.
   - Update help tests to assert the singular command and sorted subcommand set.
   - Update nested handler tests for usage strings and parser namespace names.
   - Update shipped skill-source tests to expect `sase agent list -j`.

5. Update generated skill sources.
   - In `src/sase/xprompts/skills/sase_agents_status.md`, change command examples to `sase agent ...`.
   - Keep `name: sase_agents_status`; the skill reports on running agents and should not be renamed as part of this CLI
     spelling change.
   - In `src/sase/xprompts/skills/sase_chats.md`, update fallback listing references to `sase agent list -a -j`.
   - After source edits, regenerate provider skill files with the supported flow (`sase skill init --force`, using
     `--no-push` if preserving the current local-only chezmoi behavior is still desired). Do not edit generated provider
     `SKILL.md` files directly.

6. Update docs, workflows, and benchmark command text.
   - README quickstart/common commands.
   - `docs/cli.md`, including the daily-operation table and exact-list default paragraph.
   - `docs/configuration.md`, including the heading `### sase agent`, the bare-command description, and the stale
     `status` row, which should become `list`.
   - `docs/ace.md`, `docs/rust_backend.md`, current blog posts, `docs/xprompt.md`, `smoke/pypi/README.md`, and the
     publish workflow grep.
   - `tests/perf/bench_phase7_e2e.py` command invocation/prose from `sase agents list -j` to `sase agent list -j`.
     Preserve locked benchmark surface IDs such as `sase_agents_status_listing` when they are artifact names rather than
     executable commands.

7. Sweep and classify leftovers.
   - Run exact-string searches over live code, tests, docs, workflows, and root markdown for:
     - `sase agents`
     - `Usage: sase agents`
     - `args.command == "agents"`
     - `register_agents_parser`
     - `agents_subcommand`
     - `parser_agents`
     - `agents_handler`
   - Normalize non-command prose like "sase agents" to "SASE agents" where it is product prose and not a CLI command.
   - Separately sweep `sdd/` and any historical artifacts. Leave genuinely historical references intact, but report them
     so stale live references are distinguishable from archival records.

8. Validate.
   - Run focused tests first:
     - `tests/main/test_agents_dispatch_handler.py` or its renamed equivalent.
     - `tests/main/test_parser_help.py`.
     - `tests/main/test_init_skills_sources.py`.
     - `tests/test_agents_index_cli.py`, `tests/test_agents_archive_cli.py`, `tests/main/test_agents_tag_handler.py`,
       and doctor/TUI tests touched by user-facing command strings.
   - Run CLI smoke checks with the workspace environment:
     - `sase agent --help`
     - `sase agent list -j`
     - bare `sase agent`
     - confirm `sase agents list` is rejected if no alias is requested.
   - Run `just install` if needed for this workspace, then `just check`.
   - Finish with a final `rg` sweep for live `sase agents` references and summarize any historical-only leftovers.

## Risks And Checks

- This is a breaking change. Existing scripts using `sase agents ...` will fail unless an alias is explicitly added.
- Renaming the lower-level `src/sase/agents/` package would be risky because `src/sase/agent/` already exists and owns a
  different domain. The safer boundary is public parser/handler spelling plus user-facing strings.
- The `/sase_agents_status` skill name should stay stable; changing it would break installed skill lookup and is outside
  the requested CLI rename.
- Generated provider skills must be regenerated from source. If regeneration wants to commit/push/apply dotfiles, I will
  preserve the same conservative behavior as the prior change unless review requests otherwise.
- Historical SDD records may retain `sase agents` for audit accuracy. The final report should distinguish those from
  current executable documentation.
