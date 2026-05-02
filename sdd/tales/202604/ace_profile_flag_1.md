---
create_time: 2026-04-14 23:37:49
status: done
prompt: sdd/prompts/202604/ace_profile_flag_1.md
---

# Plan: Add `--profile` flag to `sase ace`

## Context

The research document `sdd/research/202604/tui_profiling_strategies.md` recommends pyinstrument as the Layer 2 "Broad Discovery"
profiling tool for the ace TUI. The workflow: run `sase ace --profile`, use the TUI normally, exit, and review the
profiling report. pyinstrument is a statistical sampler with ~2-5% overhead and native asyncio support
(`async_mode="enabled"`), making it safe for interactive Textual sessions.

**Key requirement**: The output file must be optimized for consumption by an LLM agent, not a human in a browser. This
means plain text (not HTML), no ANSI color codes, and the hierarchical call tree that pyinstrument produces natively --
which already includes full module paths that an agent can use to navigate directly to hot functions.

## Changes

### 1. Add `pyinstrument` as a dev dependency

**File**: `pyproject.toml`

Add `pyinstrument` to the `[project.optional-dependencies] dev` list. It's a profiling tool, not needed at runtime.

### 2. Add `-p`/`--profile` flag to the ace parser

**File**: `src/sase/main/parser_ace.py`

Add a `store_true` argument `-p`/`--profile`. Short option `-p` is available on the ace subcommand (existing options use
`-m`, `-M`, `-r`, `-R`, `-x`, `-v`). Insert alphabetically by long option name (after `--no-axe`, before
`--refresh-interval`).

### 3. Wrap `app.run()` with pyinstrument in the handler

**File**: `src/sase/main/ace_handler.py`

When `args.profile` is truthy:

1. Lazily import `pyinstrument` with a clear error message if not installed.
2. Create a `Profiler(async_mode="enabled")` and start it before `app.run()`.
3. After `app.run()` returns, stop the profiler.
4. Write a **plain text** report (not HTML) to `ace_profile_<timestamp>.txt` in the current directory using
   `profiler.output_text(unicode=True, color=False)`. The text format produces a hierarchical call tree with full
   `module.path:lineno` references -- exactly what an agent needs to identify hot spots and navigate to them. No ANSI
   escape codes so it's clean for file consumption.
5. Print the output file path to stderr (stdout is used by the TUI).

When `args.profile` is falsy, behavior is unchanged.
