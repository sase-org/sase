---
create_time: 2026-04-11 22:39:17
status: done
prompt: sdd/prompts/202604/sort_subcommands.md
---

# Plan: Sort Subcommands in --help Output

## Problem

Four sase subcommands display their nested subcommands in non-alphabetical order in `--help` output. The top-level
commands and `bead` are already sorted, but `axe`, `config`, `telemetry`, and `xprompt` are not.

## Current vs. Desired Order

| Command          | Current                                                  | Sorted                                                   |
| ---------------- | -------------------------------------------------------- | -------------------------------------------------------- |
| `sase axe`       | start, stop, chop, lumberjack                            | chop, lumberjack, start, stop                            |
| `sase config`    | show, layers, mentor-match                               | layers, mentor-match, show                               |
| `sase telemetry` | status, list, snapshot, dashboard, health, export-config | dashboard, export-config, health, list, snapshot, status |
| `sase xprompt`   | expand, graph, list, explain                             | expand, explain, graph, list                             |

## Approach

argparse displays subcommands in the order `add_parser()` is called. To sort the help output, reorder the `add_parser()`
blocks in each parser registration function, then update the corresponding handler dispatch and usage strings to match.

## Changes per command

### Phase 1: `sase axe` (parser_ace.py + axe_handler.py)

1. **parser_ace.py** (lines 105-208): Reorder the axe subparser blocks so `chop` and `lumberjack` come before `start`
   and `stop`
2. **axe_handler.py** (line 28): Update usage string from `{start,stop,chop,lumberjack}` to
   `{chop,lumberjack,start,stop}`
3. **axe_handler.py** (lines 19-26): Reorder if/elif to match: chop, lumberjack, start, stop

### Phase 2: `sase config` (parser_commands.py + config_handler.py)

1. **parser_commands.py** (lines 107-129): Reorder config subparser blocks so `layers` comes before `mentor-match` which
   comes before `show`
2. **config_handler.py** (line 79): Update usage string from `{show,layers,mentor-match}` to
   `{layers,mentor-match,show}`
3. **config_handler.py** (lines 11-76): Reorder if/elif to match: layers, mentor-match, show

### Phase 3: `sase telemetry` (parser_commands.py + telemetry_handler.py)

1. **parser_commands.py** (lines 326-440): Reorder telemetry subparser blocks alphabetically: dashboard, export-config,
   health, list, snapshot, status
2. **telemetry_handler.py** (line 49): Update usage string to `{dashboard,export-config,health,list,snapshot,status}`
3. **telemetry_handler.py** (lines 13-48): Reorder if blocks to match alphabetical order

### Phase 4: `sase xprompt` (parser_commands.py + xprompt_handler.py)

1. **parser_commands.py** (lines 473-535): Reorder xprompt subparser blocks so `explain` comes before `graph` (expand is
   already first, list is already last)
2. **xprompt_handler.py** (line 20): Update usage string from `{expand,list,graph,explain}` to
   `{expand,explain,graph,list}`
3. **xprompt_handler.py** (lines 11-18): Reorder elif to match: expand, explain, graph, list

## Verification

Run `sase --help`, `sase axe --help`, `sase config --help`, `sase telemetry --help`, `sase xprompt --help` and confirm
all subcommands appear in alphabetical order. Run `just check` to verify no regressions.
