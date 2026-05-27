---
create_time: 2026-05-26 21:51:15
status: done
prompt: sdd/prompts/202605/episodes_build_progress.md
---
# Plan: Rich progress output for `sase memory episodes build`

## Problem

`sase memory episodes build` runs silently until it completes. The slowest phase is the bulk scan of `~/.sase/projects/`
(see commit `2412c2e32 fix: bound episode project scan expansion`), which can take many seconds with no feedback. Users
have no signal that the command is alive, working, or stuck.

## Goal

Give the user continuous, informative feedback throughout the build so they know:

1. **What phase** is currently running.
2. **Roughly how much** has been done (counts where cheap to compute).
3. **How long** each phase took (so they learn where time goes).
4. **What was produced** at the end (current summary stays).

…while keeping `--json` output a clean, machine-readable single JSON document on stdout.

## Build phases (current)

`_handle_build` in `src/sase/memory/cli_episodes.py:71` calls four functions in sequence. All are bulk, no internal
iteration we can subdivide without changes:

| #   | Phase                  | Function                                                   | Notes                                                                             |
| --- | ---------------------- | ---------------------------------------------------------- | --------------------------------------------------------------------------------- |
| 1   | Scan agent artifacts   | `collect_episode_draft` → `_scan_projects`                 | Walks `~/.sase/projects/*`. By far the slowest step; bounded but still expensive. |
| 2   | Collect episode draft  | `collect_episode_draft` → `EpisodeCollectorEngine.collect` | Indexing + graph build over scanned records. Usually fast but can scale with N.   |
| 3   | Build episode          | `build_episode`                                            | Pure transform of draft → canonical episode (fast).                               |
| 4   | Render lesson markdown | `render_lesson_markdown`                                   | Pure markdown render (fast).                                                      |
| 5   | Write project episode  | `write_project_episode`                                    | Atomic write of `episode.json`, `lesson.md`, `sources.jsonl` + index row. Fast.   |

(1) and (2) are inside the same `collect_episode_draft` call today. To show them as separate phases the engine would
need a small refactor; for v1 we treat them as one phase ("Collecting") and surface counts after.

## User-facing design

### Default (interactive TTY, non-JSON)

```
▶ Building episode for project: sase
  ⏱  Scanning agent artifacts…                              0.0s
  ✔ Scanned 3 projects, 142 agent records                   2.4s
  ⏱  Collecting episode draft (selector: agent=foo)…        0.0s
  ✔ Drafted episode with 8 sources, 4 lessons               0.3s
  ⏱  Rendering lesson markdown…                             0.0s
  ✔ Rendered lesson (3 KB)                                  0.0s
  ⏱  Writing episode files…                                 0.0s
  ✔ Wrote ep-20260526-…/{episode.json,lesson.md,sources.jsonl}  0.1s

Built episode ep-20260526-… "Retry feedback memory" (8 sources, 4 lessons)
project: sase
episode_dir: /home/.../episodes/ep-20260526-…
```

Each in-progress line is a `rich.status.Status` spinner that updates in place; on completion the spinner is replaced by
a check mark + elapsed time. The final "Built episode …" block (unchanged from today) is printed last so existing
muscle-memory and any text-scrapers still work.

### Dry run

Identical, but the "Writing episode files…" phase prints `✔ Skipped (dry run)` without touching disk. Final line uses
today's `"Would build"` wording.

### `--json` / `-j` mode

**Zero progress output.** Stdout must remain a single JSON document. Tests in `tests/test_memory_episodes_cli.py` parse
the entire stdout with `json.loads(capsys.readouterr().out)`, so even stderr progress is fine but we default to silent
in JSON mode to avoid surprising downstream automation.

### Non-TTY (CI, pipes)

Rich auto-degrades spinners on non-TTY consoles. We will additionally suppress the in-place spinner frames and just
print one "▶ phase" line and one "✔ phase done in Xs" line per phase. Same content, no ANSI churn.

### Quiet escape hatch

Add `-q / --quiet` to `memory episodes build` that suppresses everything except errors and the final summary. Useful for
shell scripts that want the human-text summary but no preamble. (Long+short option per `gotchas.md`.)

## Where progress goes

All progress lines go to **stderr** via a dedicated `rich.console.Console(stderr=True)`. This:

- Keeps `--json` stdout clean even if a user forgets `-q`.
- Lets the final summary (`print(...)` to stdout) stay as the canonical machine-grep-able output.

The existing `print(...)` summary calls at the end of `_handle_build` are untouched.

## Counts we can cheaply surface

- After scan: `len(scan.records)` and number of distinct `project_name` values.
- After collect: `len(draft.sources)`, `len(draft.lessons)` (already on `EpisodeDraft`).
- After render: byte length of the markdown string.
- After write: the three filenames (already constants in `storage.py`).

No new computation, no extra I/O. Each is read straight from existing return values.

## Implementation outline

1. **New module `src/sase/memory/episodes/_build_progress.py`** with a small `BuildProgress` context-manager class
   wrapping `rich.console.Console(stderr=True)` and a stack of `Status` spinners. Methods:

   ```python
   with BuildProgress(enabled=...) as bp:
       with bp.phase("Scanning agent artifacts"):
           ...
       bp.summary("Scanned 3 projects, 142 agent records")
   ```

   `enabled=False` (JSON or quiet or non-TTY+`--quiet`) makes every method a no-op so call sites don't need branches.

2. **Refactor `_handle_build`** in `cli_episodes.py` to:
   - Construct `BuildProgress(enabled=not args.json and not args.quiet)`.
   - Wrap each of the 4–5 phases in `bp.phase(...)`.
   - After each phase, call `bp.summary(...)` with the counts described above.
   - Catch exceptions inside `bp` so the spinner stops cleanly on error.

3. **Add `-q/--quiet` flag** to the build subparser (find it via grep — likely in a `parser.py` near `cli_episodes.py`).
   Default: false.

4. **No changes** to `collect_episode_draft`, `build_episode`, `render_lesson_markdown`, or `write_project_episode`.
   Progress is purely observational at the CLI layer.

### Optional follow-up (NOT in this CL)

Thread an optional progress callback into `scan_agent_artifacts` so the scan phase ticks per project. This requires
touching the Rust-core boundary (`AgentArtifactScanOptionsWire` / `scan_agent_artifacts`) and is therefore a separate
change per `rust_core_backend_boundary.md`. v1 uses a single spinner for the scan and surfaces counts only after it
returns.

## Tests

Add a new test file or extend `tests/test_memory_episodes_cli.py`:

- `test_build_progress_prints_to_stderr_in_human_mode` — invoke the human path, assert stderr contains the phase labels
  ("Scanning", "Collecting", "Rendering", "Writing") and the final stdout block is unchanged.
- `test_build_progress_silent_in_json_mode` — invoke with `-j`, assert `capsys.readouterr().err == ""` (or only
  error-level content) and stdout parses as JSON exactly as today.
- `test_build_progress_silent_with_quiet_flag` — assert `-q` suppresses progress but keeps the final human summary.
- Existing JSON test (`test_memory_episodes_build_writes_episode_from_agent_selector`) must keep passing untouched.

Manual smoke: run `just install && sase memory episodes build -n <agent>` and confirm spinners render and the trailing
summary is unchanged.

## Risks / open questions

- **Rich spinner clobbering on `LANG=C` / dumb terminals.** Rich detects this and falls back to plain text. Verified by
  `output.py`'s existing usage.
- **Stderr noise in test fixtures.** Existing tests use `capsys.readouterr().out` only, so stderr emission is invisible
  to them. Confirm none rely on `capsys.readouterr().err`.
- **`-q` flag short option collision.** Check the existing `memory episodes build` parser for an existing `-q` — if
  taken, fall back to `--quiet` only and document the exception locally (and re-check `gotchas.md`'s short-option rule
  before doing so).

## Out of scope

- Per-project tick during scan (requires Rust-core change).
- Logging framework integration / structured logs.
- Progress for `list`, `show`, `verify`, `recall` subcommands.
- Reworking the final summary block.
