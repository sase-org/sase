---
create_time: 2026-06-09 18:15:06
status: done
prompt: sdd/prompts/202606/cli_help_output.md
---
# Improve `sase` Command Line Help Output

## Goal

Make root `sase --help` useful for people trying to understand or use SASE, while preserving the current exhaustive
top-level command inventory behind a new root `-H|--full-help` option.

The current root help output is maintainer-oriented: it exposes every top-level command in one large argparse-generated
list. That is useful for exhaustive discovery, but it buries the first useful commands. The new behavior should split
those two jobs:

- `sase -h` and `sase --help`: concise user-facing help with only the most useful top-level commands and better text.
- `sase -H` and `sase --full-help`: the exhaustive command inventory currently shown by `sase --help`.

All existing commands must remain parseable and unchanged. This is a presentation change, not a command removal.

## Current Shape

Root CLI construction is centralized in `src/sase/main/parser.py`.

Important existing behavior:

- The root parser is an `argparse.ArgumentParser` with the default `-h|--help`.
- Every top-level command is registered on one `argparse._SubParsersAction`.
- `_sort_subcommand_help()` sorts all subparser choices and visible help rows.
- `_default_list_subcommands()` makes command groups with an exact `list` child default to that child.
- Parser help tests live in `tests/main/test_parser_help.py`.
- The project convention requires new command-line options to have both short and long forms, so the exhaustive help
  option should be `-H|--full-help`.

The current full root help lists these top-level commands:

`ace`, `agents`, `amd`, `artifact`, `axe`, `bead`, `changespec`, `chats`, `comments`, `commit`, `config`, `core`,
`doctor`, `editor`, `file`, `file-history`, `git`, `init`, `logs`, `lsp`, `memory`, `mobile`, `notify`, `path`, `plan`,
`plugin`, `project`, `questions`, `repro`, `restore`, `revert`, `revive-log`, `run`, `sdd`, `skills`, `telemetry`,
`validate`, `var`, `version`, `workspace`, and `xprompt`.

## Proposed Compact Root Help

The compact help should be manually curated rather than produced by hiding parser choices. This keeps the parser's real
command set intact and avoids spreading "primary command" policy across every `register_*_parser()` function.

Proposed root `--help` command set:

- `doctor`: run read-only install, config, provider, project, and state diagnostics.
- `init`: check or initialize SASE-managed files such as `AGENTS.md`, memory, SDD guides, and skills.
- `version`: show the exact SASE host, Rust core, and plugin packages loaded by this process.
- `ace`: open the interactive control surface for agents, projects, notifications, automation, and ChangeSpecs.
- `run`: launch or resume a coding-agent run from a prompt, xprompt, workflow, or history.
- `agents`: list, inspect, tag, or stop active and recent agent runs.
- `memory`: inspect loaded memory, review proposals, and audit long-term memory activity.
- `bead`: manage git-portable issues, dependencies, planning beads, and executable epics.
- `project`: list active projects and hide or reactivate dormant work.
- `workspace`: inspect, prepare, and repair numbered checkouts used by parallel agents.

This intentionally omits lower-level and integration surfaces from compact root help, including `artifact`, `axe`,
`changespec`, `chats`, `comments`, `commit`, `config`, `core`, `editor`, `file`, `file-history`, `git`, `logs`, `lsp`,
`mobile`, `notify`, `path`, `plan`, `plugin`, `questions`, `repro`, `restore`, `revert`, `revive-log`, `sdd`, `skills`,
`telemetry`, `validate`, `var`, and `xprompt`. Those commands remain visible in `sase --full-help`.

The compact help should also include short examples, because examples are more useful than command descriptions for
first-contact CLI discovery:

```text
Examples:
  sase doctor
  sase init -c
  sase run "#cd:$(pwd) summarize this repository; do not change files"
  sase ace
  sase agents status
  sase --full-help
```

## Implementation Plan

1. Add root-help policy near root parser construction.

   Add a small local data structure in `src/sase/main/parser.py`, for example a frozen dataclass or tuple of
   `(command, summary, examples)` records. Keep it close to `create_parser()` so future root command additions can
   update the curated help in the same file.

2. Replace the root parser's default help action with explicit help actions.

   Build the root parser with `add_help=False`, then add:
   - `-h`, `--help`: custom action that prints compact root help and exits 0.
   - `-H`, `--full-help`: custom action that prints exhaustive root help and exits 0.

   Scope this behavior to the root parser. Subcommand help such as `sase memory --help` and `sase agents --help` should
   keep their current argparse behavior unless a later task asks to curate those surfaces too.

3. Preserve exhaustive help without altering command parsing.

   Keep registering every top-level subcommand exactly as today. `sase --full-help` should render the same exhaustive
   command inventory that `sase --help` currently renders, with the expected addition that the options section now
   documents both compact help and full help.

   Avoid marking non-primary subcommands as hidden or deleting them from `action.choices`; doing so would risk breaking
   parsing, completion helpers, tests, and command-discovery code.

4. Render compact root help from a dedicated formatter/helper.

   Generate compact help text from the curated command list and the parser's actual subparser choices. The helper should
   fail loudly in tests if a curated command no longer exists. Keep the root usage line simple, for example:

   ```text
   usage: sase [-h] [-H] <command> [args...]
   ```

   The body should emphasize purpose and next action:

   ```text
   SASE - Structured Agentic Software Engineering

   Common commands:
     doctor     Run read-only install, config, provider, project, and state diagnostics.
     init       Check or initialize AGENTS.md, memory, SDD guides, and skills.
     ...

   Use `sase <command> --help` for command-specific flags.
   Use `sase --full-help` to show every command.
   ```

5. Add regression tests.

   Extend `tests/main/test_parser_help.py` with coverage for:
   - `create_parser().parse_args(["--help"])` exits 0 and prints compact help.
   - `create_parser().parse_args(["-h"])` behaves the same as `--help`.
   - Compact help includes the curated commands and improved descriptions.
   - Compact help excludes representative non-curated commands such as `artifact`, `mobile`, `telemetry`, `questions`,
     and `var`.
   - `create_parser().parse_args(["--full-help"])` and `["-H"]` exit 0 and include every top-level command.
   - Non-curated commands still parse normally, proving this is not a command removal.
   - Existing sorted-subcommand and default-list tests continue to pass.

6. Validate.

   After source changes, run the focused parser-help tests first:

   ```bash
   just install
   pytest tests/main/test_parser_help.py
   ```

   Then run the required repository check before finishing:

   ```bash
   just check
   ```

## Non-Goals

- Do not remove, rename, or deprecate any existing command.
- Do not curate every nested subcommand's help output in this change.
- Do not change README or docs unless implementation reveals a direct inconsistency that should be fixed with the same
  behavior change.
- Do not change root command dispatch in `src/sase/main/entry.py` except if needed to support the parser-level help
  behavior.

## Risks And Mitigations

- Argparse root help options can interact awkwardly with subparser options. Keep `-H|--full-help` root-scoped and
  require it before any subcommand, matching normal root option behavior. Existing subcommand `-H` flags, such as axe
  runner concurrency options, should continue to work after their subcommand.
- Custom help can drift from the real command set. Keep the curated commands as data, assert they exist in tests, and
  test exhaustive help for the full command inventory.
- Full help may no longer be bit-for-bit identical because the options section must mention both help modes. Preserve
  the substantive current behavior: exhaustive usage, all commands, and current command summaries.
