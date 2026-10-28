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

## Reading the report

Run `sase footprint list` to report the ledger through one of nine lenses, and
`sase footprint show <id>` for the evidence card behind one feature or area. Both fold
pending spool data first when the last fold is more than ten minutes old, so the report
never goes stale by more than one fold interval. Bare `sase footprint` delegates to
`list`. Pick the lens with `-l/--lens`, the actor scope with `-a/--actor` (`you` shows
your use, `agents` and `automation` show theirs, `everyone` shows all use), and the
window with `-r/--range` (`Nd`, `Nw`, or `all`; the default is `60d`). Use
`-f/--format json` for the report wire or `-f/--format markdown` for a compact,
agent-ready table with the evidence sentence and IDs in backticks.

The lenses are:

- `map`: one row per area with a proportional hot-to-cold heat strip, used/total, and
  the share used. A `◂` marker flags areas below 25%.
- `cold`: deletion candidates: zero use by anyone, gate met, unprotected, and undecided
  (or snooze expired), hottest carrying cost first.
- `fading`: used before the last `fading_days`, nothing since.
- `agent-only`: used by agents, never by you.
- `dead-paths`: bound TUI keys never reached via `key`, and zero-use options whose
  command was used.
- `friction`: `(usage_error + help) / total ≥ 0.25` with at least 3 hits.
- `hot`: top 50 by days used, with CLI time spent.
- `coverage`: measured and active days per surface family, plus torn, dropped, and
  unknown-ID counts.
- `decisions`: every local review decision with its current evidence.

Each feature is in exactly one evidence state:

- `used`: at least one record in the window for the lens's actor scope.
- `no_recorded_use`: zero use, gate met, unprotected: a candidate.
- `rare_by_design`: zero use but overlay-protected (recovery, safety, bootstrap, or
  infra): shown with a lock-like glyph, never a candidate.
- `too_new`: the gate is not met (under 60 days in the catalog or under 30 observed
  active days, excluding a 3-day calibration window).
- `not_measured`: the feature's surface family has no measured day in the window.
- `retired`: no longer in the latest catalog revision.

The candidate gate needs at least 60 days in the catalog and 30 observed active days on
the relevant surface. The header chip reads `PREVIEW 12/30 active days` (amber) until
the gate is met, then `READY`. An amber qualifier marks incomplete evidence (dropped or
torn days in the window). A zero is neutral grey, never red; red is reserved for
collector faults. Every evidence sentence states its denominator, for example "No
recorded use by you across 41 observed active days."

Record review decisions with
`sase footprint decide <id> {keep,later,cut,clear} [-r/--reason]` (reasons:
`rare_by_design`, `safety`, `agent_facing`, `api_contract`, `other`). A decision is
metadata on top of the evidence state; `later` snoozes 30 days and then re-enters Cold.

Related: [`sase footprint`](cli/footprint.md) ·
[Environment variables](environment-variables.md).
