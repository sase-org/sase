---
create_time: 2026-05-05 08:45:05
status: done
prompt: sdd/prompts/202605/cli_help_subcommand_sorting.md
---
# Plan: Alphabetize CLI Subcommands In All Help Output

## Goal

Ensure every `sase ... --help` view that lists subcommands shows those subcommands in alphabetically sorted order,
including nested command groups such as `sase agents`, `sase bead`, `sase sdd`, and `sase xprompt`.

## Current Findings

The CLI is built with `argparse` in `src/sase/main/parser.py` and split across `src/sase/main/parser_*.py`. `argparse`
displays subcommands in registration order through each `_SubParsersAction`, so preserving sorted help output currently
depends on every registration block staying manually sorted.

The top-level registrations in `create_parser()` are already sorted, but several nested groups are not:

- `sase agents`: currently registers `status`, `kill`, `show`, `tag`, `archive`, `index`.
- `sase agents tag`: currently registers `set`, `unset`, `list`.
- `sase agents archive` and `sase agents index` are already sorted, but should still be covered.
- `sase bead`: mostly sorted, but `work` appears before `update`.
- `sase file-history`: currently registers `list`, `delete`.
- `sase sdd`: currently registers `init`, `validate`, `links`, `list`, `repair-links`.
- `sase xprompt`: currently registers `expand`, `explain`, `graph`, `list`, `catalog`.

Other command groups I checked are already sorted or have only one subcommand, but should be covered by the same guard
so future additions do not regress.

## Approach

1. Add a small parser-ordering utility that walks the constructed `argparse.ArgumentParser` tree and sorts every
   `_SubParsersAction` alphabetically by subcommand name.
   - Sort both `choices` insertion order and `_choices_actions`, because `argparse` uses these private structures to
     render usage/help.
   - Recurse into each child parser so all nesting levels are covered.
   - Keep the utility local to CLI parser construction, likely in `src/sase/main/parser.py` or a small sibling module,
     because this is presentation behavior for the Python CLI.

2. Call the utility once at the end of `create_parser()`, after all parser registration functions have run.
   - This avoids broad manual churn across every `parser_*.py` file.
   - It also makes the behavior future-proof when a new subcommand is appended in an unsorted location.
   - It does not change parsing semantics, only help display order.

3. Add focused tests for the complete parser tree.
   - Build the parser with `create_parser()`.
   - Traverse every `_SubParsersAction` recursively.
   - Assert each action's visible help entries are alphabetically sorted.
   - Assert each action's `choices` keys are alphabetically sorted, since these drive usage metavars like
     `{archive,index,kill,...}`.
   - Include enough failure context to identify the command path, e.g. `sase agents tag`.

4. Add a small representative formatted-help assertion.
   - Check at least one known formerly unsorted command path, such as `sase agents`, `sase bead`, or `sase xprompt`, to
     prove the user-facing `format_help()` output now reflects the sorted internal tree.
   - Keep this test structural rather than a brittle full golden snapshot.

5. Verify.
   - Run the new focused parser/help tests first.
   - Run `just install` if needed for this workspace, per repo guidance.
   - Run `just check` after making code changes, per repo guidance.

## Risks And Tradeoffs

- This relies on `argparse` private structures (`_SubParsersAction`, `_choices_actions`), but the repo already uses
  these private types in annotations and this is the narrowest practical way to control subcommand help ordering
  globally.
- Sorting only after construction keeps registration code readable and minimizes unrelated diffs, but developers looking
  at registration order may not see the final help order directly. Tests should make the contract explicit.
- The requested scope is subcommand ordering, not option ordering or positional `choices` ordering. I will not change
  option order unless a failing test reveals argparse mixes subcommands with other entries.
