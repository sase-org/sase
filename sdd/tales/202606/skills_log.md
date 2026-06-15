---
create_time: 2026-06-15 16:39:55
status: done
prompt: sdd/prompts/202606/skills_log.md
---
# Plan: Add the `sase skills log` Inspection Command

## Goal

Introduce a read-only `sase skills log` command that summarizes and inspects the skill-use audit events recorded by
`sase skills use`. This is the inspection counterpart promised when `sase skills log` was freed by renaming the
write-only command to `sase skills use`. It is the skills-domain mirror of `sase memory log`.

The command must be **intuitive** (panel layout and filters parallel to `sase memory log`, which users already know),
**reliable** (deterministic JSON mode, tolerant reads, exact/prefix id lookup), and **beautiful** (Rich panels and
tables with consistent color, plus a first-class _runtime_ dimension that `memory log` cannot offer).

## Background (what already exists)

- **Foundation** — `src/sase/skills/use_log.py` already provides everything needed to read and aggregate events:
  `SkillUseEvent` (fields:
  `schema_version, id, timestamp, project, cwd, skill_name, agent_name, agent_source, artifacts_dir, reason, runtime`),
  `read_skill_use_events`, `filter_skill_use_events(skill_name, agent_name)`, `summarize_skill_uses_by_skill`, and
  `summarize_skill_uses_by_agent`. Storage is `~/.sase/projects/<project>/skill_uses.jsonl`.
- **Model to imitate** — `sase memory log` (`src/sase/main/parser_memory.py`, `src/sase/main/memory_handler.py`,
  `src/sase/memory/cli_log.py`). It renders a Rich `Group` of cyan-bordered `Panel`s: a summary panel, a grouped "Memory
  Paths" panel, a conditional "Agents" panel (shown with `--agent`), a conditional individual-events panel (shown on any
  drill-down filter), and a single-event detail view (`--id`). It supports `--json` for deterministic machine output and
  exact-or-prefix id lookup.
- **Write command** — `sase skills use` (`src/sase/skills/cli_use.py`) appends events. It stays unchanged.

## Design

### The lead design decision: runtime as a first-class dimension

`SkillUseEvent` carries a `runtime` field (e.g. `claude`, `codex`, `gemini`) that memory-read events do not. This is the
distinguishing, beautiful axis for this command. It surfaces in four ways: a "Runtimes" count in the summary, a
`-R/--runtime` filter, a dedicated runtimes breakdown panel (parallel to the agents panel), and a Runtime column in the
individual-events drill-down. Everything else parallels `sase memory log` so the command feels instantly familiar.

### Command surface

`sase skills log [filters] [--id USE_ID] [--json]`

Options (alphabetized per CLI rules; every public option gets a short alias, which `memory log` predates):

| Long        | Short | Meaning                                                  |
| ----------- | ----- | -------------------------------------------------------- |
| `--agent`   | `-a`  | Only include uses by the given agent.                    |
| `--id`      | `-i`  | Show one skill-use event by id or unambiguous id prefix. |
| `--json`    | `-j`  | Emit deterministic machine-readable JSON.                |
| `--runtime` | `-R`  | Only include uses recorded under the given runtime.      |
| `--skill`   | `-s`  | Only include uses of the given skill.                    |

`-R` (capital) is used for runtime to avoid clashing with the `-r/--reason` mnemonic that `sase skills use` already
establishes, preventing cross-subcommand confusion.

### Panel layout (Rich, cyan borders to match `memory log`)

Default summary view, built as a `Group`:

1. **Summary panel** — "SASE Skill Use Log": Project, Filters, Skill uses (total), Skills (distinct), Agents (distinct),
   Runtimes (distinct).
2. **Skills panel** — "Skills (N)" (always shown, parallel to "Memory Paths"): Skill | Uses | Agents | Last used | Last
   agent | Last reason.
3. **Agents panel** — "Agents (N)" (shown only with `--agent`, parallel to memory's agents panel): Agent | Uses | Skills
   | Last used | Last skill | Last reason.
4. **Runtimes panel** — "Runtimes (N)" (shown only with `--runtime`; the new dimension): Runtime | Uses | Skills |
   Agents | Last used | Last reason.
5. **Skill Use Events panel** — "Skill Use Events (N)" (shown on any of `--skill`/`--agent`/`--runtime`, parallel to
   memory's events drill-down): ID | Timestamp | Agent | Runtime | Skill | Reason.

Single-event view (`--id`): summary panel + a key/value detail panel showing every field (ID, Timestamp, Project, Skill,
Agent, Agent source, Runtime, Reason, CWD, Artifacts dir). Honors `--json` to dump the raw event.

Empty/edge states mirror `memory log`: "No skill-use events found." vs. "No skill-use events match the current
filters.". `None` runtimes render as `unknown` and group under an `unknown` bucket; reasons are previewed/truncated with
the same one-line, ~72-char helper.

### JSON contract (deterministic, sorted keys)

Summary mode emits
`{ filters: {agent, runtime, skill}, project, summary: [by-skill summaries...], total_agents, total_runtimes, total_skill_uses, total_skills }`.
`--id` mode emits `asdict(event)`. Errors go to stderr with a `sase skills log:` prefix and exit code 1, matching the
`memory log` error convention.

## Implementation

1. **Extend the foundation** (`src/sase/skills/use_log.py`):
   - Add an optional `runtime` parameter to `filter_skill_use_events` (backward-compatible keyword).
   - Add a `SkillUseRuntimeSummary` dataclass
     (`runtime, use_count, distinct_skill_count, distinct_agent_count, last_used_at, last_reason`) and a
     `summarize_skill_uses_by_runtime` function that buckets `None` runtime under `unknown` and sorts deterministically.
   - Export the new symbols from `use_log.py.__all__` and re-export from `src/sase/skills/__init__.py`.

2. **Add the parser subcommand** (`src/sase/main/parser_skills.py`):
   - Register a `log` subparser (keeping subcommands alphabetized: `init`, `list`, `log`, `use`) with the five options
     above, helpful `description`/`epilog` examples, and `RawDescriptionHelpFormatter`.
   - Add a `sase skills log` example to the `skills` group epilog.

3. **Add command dispatch** (`src/sase/main/skills_handler.py`):
   - Add `_handle_skills_log_command` that imports and calls `sase.skills.cli_log.handle_skills_log_command`.
   - Dispatch `skills_subcommand == "log"`; update the fallback usage string to `sase skills {init,list,log,use}`.

4. **Create the renderer** (`src/sase/skills/cli_log.py`, new): mirror `src/sase/memory/cli_log.py` structure (handler +
   summary dashboard builder + per-panel helpers + single-event view + JSON payload builders + exact/prefix id
   selection + filter-label/normalize/reason-preview helpers), adapted to skill-use fields and the runtime panel. Drop
   the proposals machinery (no skills analog).

5. **Docs** — add `sase skills log` to the command tables in `docs/cli.md` and `docs/configuration.md` (alphabetical:
   `log` before `use`), and add a sentence to `docs/init.md` and `docs/xprompt.md` noting that recorded skill uses can
   be summarized/inspected with `sase skills log` (the read-side counterpart to `sase skills use`).

6. **Tests**:
   - New `tests/main/test_skills_log.py` mirroring `tests/main/test_memory_log.py`: grouped summary render, empty-state
     for an unknown filter, skill drill-down events, `--agent` agents panel, `--runtime` runtimes panel (new), composed
     filters, JSON summary payload, JSON `--id` raw event, `--id` detail render (asserting the runtime row), and an
     unknown-id error carrying the `sase skills log:` prefix.
   - Extend `tests/test_skill_use_log.py` to cover `summarize_skill_uses_by_runtime` (including the `unknown` bucket)
     and the new `runtime=` filter argument.
   - Extend `tests/main/test_skills_handler.py` with parser-registration coverage for `skills log` (all filters parse;
     bare/default behavior unchanged) and a dispatch test routing `log` to the renderer.

## Non-Goals / Notes

- **Rust core boundary**: This deliberately follows the established precedent of its direct sibling `sase memory log`
  and the existing `use_log.py` foundation — both of which already live as pure Python in this repo (not `sase-core`).
  The skill-use read/summarize/render layer is local audit tooling and presentation consistent with that precedent, so
  no `sase-core` change is proposed. (Flag for reviewer if the audit-summary foundation should instead move to Rust; the
  parallel memory feature is entirely Python today.)
- No change to the skill-use JSONL schema, storage path, the `sase skills use` write command, or the TUI skill-use
  loaders (`src/sase/ace/tui/skill_uses.py`). The command is CLI-only and does not touch the TUI hot path, so
  `tui_perf.md` is out of scope.
- No new `sase ace` option, so the ACE help-popup/footer rules do not apply.

## Verification

1. `just install` first (workspace may be stale).
2. Focused tests:
   `.venv/bin/pytest tests/main/test_skills_log.py tests/test_skill_use_log.py tests/main/test_skills_handler.py tests/main/test_parser_help.py`
3. Manual spot-checks: `sase skills log --help`, `sase skills log`, `sase skills log --json`,
   `sase skills log --runtime claude`, `sase skills log --skill sase_plan`.
4. `just check` (required for source/docs changes).
