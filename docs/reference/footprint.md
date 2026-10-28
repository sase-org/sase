---
title: "Footprint"
description: "Local usage census recording, its privacy limits, and the mode switch."
---

# Footprint

Footprint records a local census of allowlisted SASE features so you can see which
surfaces you use.

## What Footprint records

The CLI recorder appends one line per process to
`$SASE_HOME/footprint/spool/YYYY-MM-DD.jsonl` (default root: `~/.sase`). A record
contains:

- A catalogued command ID, or `cli:~other` for an unknown command.
- Up to 16 option destination names for the selected command. It records names such as
  `json`, never values passed to options.
- An actor (`human`, `agent`, `automation`, or `unknown`) and a source such as `cli`,
  `editor`, `chat`, or `auto`.
- An outcome (`ok`, `error`, `usage_error`, `help`, or `cancelled`), a count, elapsed
  milliseconds, the local calendar date, and the SASE version.

The spool uses private local files and is folded into a local daily ledger by the hourly
`footprint_fold` housekeeping job. A full daily file stops accepting CLI records after
32 MiB; a small drop record reports skipped lines when space remains.

## What it never records

Footprint does not store command arguments, option values, prompts, free text, paths,
project names, usernames, hostnames, process IDs, or session IDs. Custom plugin names
collapse to one `plugin:~third_party` ID. Actor and source are closed enums, not
identity strings.

Pytest runs are excluded by default. Set `SASE_FOOTPRINT=test` only for isolated
recorder tests; those writes pass the SASE pytest state-write guard.

## Turning it off

Run `sase footprint mode off` to stop recording new CLI hits. Run
`sase footprint mode local` to resume. With no mode file, the effective mode is `local`.

`SASE_FOOTPRINT=off` disables recording for one process and takes precedence over the
mode file. `sase footprint mode` prints the effective mode and a short disclosure. The
mode switch does not delete records already in the spool.

## Status and clear

Run `sase footprint status` to see the effective mode, privacy summary, first recorded
day, ledger size, spool backlog, catalog revision, seven-day coverage, and any dropped,
torn, or unknown-ID records. Status folds pending spool data when the last fold is more
than ten minutes old. Use `-f json` for the ledger status wire data.

Run `sase footprint clear` to remove the ledger and spool. The command asks for
confirmation; pass `-y` to skip the prompt. Clearing advances a generation number so TUI
counts buffered before the clear are discarded. The recording mode stays as set.

The hourly `footprint_fold` job ingests a changed catalog, folds pending spool lines,
applies spool retention, and prunes old daily aggregates. It skips a pass when the
ledger is busy. `sase doctor` warns when local recording has unfolded spool bytes older
than three days. The first fold that stores records adds one disclosure notification to
the inbox.

Related: [`sase footprint`](cli/footprint.md) ·
[Environment variables](environment-variables.md).
