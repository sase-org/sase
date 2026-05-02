---
create_time: 2026-04-14 23:32:46
status: wip
prompt: sdd/prompts/202604/ace_profile_flag.md
---

# Plan: Add `--profile` flag to `sase ace`

## Context

The research document `sdd/research/202604/tui_profiling_strategies.md` recommends a layered profiling strategy for the ace TUI.
Layer 2 ("Broad Discovery with pyinstrument") specifically calls for:

> Add a `--profile` flag to `sase ace` that starts/stops pyinstrument around the app run

pyinstrument is a statistical sampling profiler that captures wall-clock time with ~2-5% overhead, making it safe to use
during interactive TUI sessions. Its `async_mode="enabled"` setting handles asyncio natively, which is exactly what we
need for a Textual app. The workflow is: run `sase ace --profile`, use the TUI normally for 30-60 seconds, exit, and
review the generated HTML flamegraph report.

## Changes

### 1. Add `pyinstrument` as a dev dependency

**File**: `pyproject.toml`

Add `pyinstrument` to the `[project.optional-dependencies] dev` list. This is a development/profiling tool, not needed
at runtime, so it belongs in dev deps rather than core deps.

### 2. Add `-p`/`--profile` flag to the ace parser

**File**: `src/sase/main/parser_ace.py`

Add a new `store_true` argument `-p`/`--profile` to `register_ace_parser()`. Short option `-p` is available (existing
ace options use `-m`, `-M`, `-r`, `-R`, `-x`, `-v`). Insert alphabetically by long option name (after `--no-axe`, before
`--refresh-interval`).

### 3. Wrap `app.run()` with pyinstrument in the handler

**File**: `src/sase/main/ace_handler.py`

When `args.profile` is truthy:

1. Lazily import `pyinstrument` with a clear error message if not installed (since it's a dev dep, it may not be present
   in non-dev installs).
2. Create a `Profiler(async_mode="enabled")` and start it before `app.run()`.
3. After `app.run()` returns, stop the profiler.
4. Write an HTML report to `sase_ace_profile.html` in the current directory and print the path to stdout.

When `args.profile` is falsy, behavior is unchanged — just `app.run()` as before.
