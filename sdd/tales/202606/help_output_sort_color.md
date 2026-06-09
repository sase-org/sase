---
create_time: 2026-06-09 19:25:17
status: done
prompt: sdd/prompts/202606/help_output_sort_color.md
---
# Plan: Colored, Sorted Root Help

## Context

The root CLI parser is built in `src/sase/main/parser.py` with custom `-h|--help` and `-H|--full-help` actions. `--help`
currently renders a curated compact root help string, while `--full-help` delegates to argparse's exhaustive help.

Existing parser tests already assert that argparse subparser choices and visible subparser help rows are sorted
recursively. The observed gap is the curated `Common commands:` section used by `sase -h` / `sase --help`: its command
rows are not alphabetized. The current output is plain text even when stdout is a terminal, although the project already
depends on Rich and has terminal-aware console patterns elsewhere.

## Goals

- Make the compact root help command rows sort alphabetically by command name.
- Add color to `sase -h` / `sase --help` when stdout supports it.
- Preserve plain, deterministic output for pipes, redirected output, tests, and non-terminal captures.
- Keep `-h` and `--help` byte-for-byte identical in the same output mode.
- Avoid changing parser behavior, command registration, or command handlers.

## Non-goals

- Do not redesign the command inventory or expand compact help to include every subcommand.
- Do not color machine-readable command output.
- Do not depend on Python 3.14 argparse color support; the project supports Python 3.12+.
- Do not change memory files.

## Proposed Design

1. Sort compact help data at render time.
   - Keep `_COMPACT_ROOT_COMMANDS` as the curated allowlist.
   - Build rows from `sorted(_COMPACT_ROOT_COMMANDS, key=lambda command: command.name)` so future edits cannot
     accidentally reintroduce unsorted compact help.
   - Keep the existing missing-command assertion before rendering.

2. Add a small terminal-aware help renderer.
   - Keep the existing plain string formatter as the source of truth for captured and redirected output.
   - Add a companion renderer for terminal output using Rich `Console` and `Text`, following the existing local pattern
     of enabling color only when `sys.stdout.isatty()` is true.
   - Use restrained semantic styling: usage dim/bold, title bold, section headings cyan, command names green/bold,
     examples yellow or dim, and footer guidance dim with command snippets highlighted.
   - Keep line content and ordering the same as the plain renderer so the help remains familiar and easy to diff after
     stripping ANSI escapes.

3. Route the compact help action through the renderer.
   - `_CompactRootHelpAction.__call__` should write colored output only when the target stream is a color-capable
     terminal.
   - For non-TTY stdout, it should continue using `parser._print_message(...)` with the plain help string.
   - Leave `_FullRootHelpAction` as-is unless implementation reveals a trivial shared path that preserves argparse
     behavior. The user asked specifically about `sase -h|--help`, and exhaustive argparse help is already sorted.

4. Extend tests in `tests/main/test_parser_help.py`.
   - Assert compact root help command rows are sorted alphabetically.
   - Update any expectations that currently rely on the old compact command order.
   - Add a plain-output regression test that captured `--help` contains no ANSI escapes.
   - Add a focused color test by invoking the compact renderer with a Rich console or fake TTY stream, asserting ANSI
     escapes are present and that stripping them leaves the same core help text.
   - Keep existing recursive sorted-subparser tests intact.

5. Verify behavior manually and with tests.
   - Run `just install` before checks if dependency metadata is stale.
   - Run the targeted parser help test file first: `just test tests/main/test_parser_help.py`.
   - Run `just check` before final response because source/test files will have changed.
   - Manually inspect `.venv/bin/python -m sase -h` and a PTY-backed invocation such as
     `script -qefc '.venv/bin/python -m sase -h' /dev/null` to confirm plain vs colored behavior.

## Risks and Mitigations

- Rich may wrap or normalize output differently from the plain formatter. Mitigation: construct line-oriented `Text`
  output and test stripped colored output against the plain formatter.
- Tests run under captured stdout, so accidental ANSI output would be noisy. Mitigation: default to plain output unless
  stdout is a TTY, and test that captured help has no escape sequences.
- Future compact command additions could break sorting. Mitigation: render from sorted data and add an explicit
  compact-order test.
