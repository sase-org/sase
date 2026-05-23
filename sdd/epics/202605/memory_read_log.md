---
create_time: 2026-05-23 15:13:10
status: done
prompt: sdd/prompts/202605/memory_read_log.md
bead_id: sase-41
tier: epic
---
# Plan: `sase memory read` and `sase memory log`

## Background

The existing memory CLI is implemented in Python:

- `src/sase/main/parser_memory.py` registers `sase memory {init,list}`.
- `src/sase/main/memory_handler.py` dispatches the subcommands.
- `src/sase/memory/cli_list.py` and `src/sase/memory/inventory.py` render and discover memory context.
- `src/sase/xprompt/loader_memory.py` already treats `memory/long/*.md` files with frontmatter keywords as dynamic
  long-term memory sources.

This work should stay close to that surface for the first implementation. It should not modify `memory/short/*`, and the
new command must explicitly reject attempts to read short-term memory through this path.

## Command Contract

Add:

```bash
sase memory read <memory-relative-path> --reason <reason>
sase memory log [--path <memory-relative-path>] [--agent <agent-name>] [--id <read-id>] [--json]
```

Initial `read` path behavior:

- The argument is canonicalized relative to the project `memory/` directory, so the normal form is
  `long/generated_skills.md`.
- Only `long/*.md` is readable in the first version.
- Reject `short/...`, absolute paths, `..` traversal, non-`.md` paths, directories, missing files, and symlinks that
  resolve outside the approved memory subdirectory.
- Keep the readable subdirectories behind one small allowlist, initially `{"long"}`, so a later phase can add another
  `memory/` subdirectory without rewriting validation.

`read` output behavior:

- Print the file body to stdout with a leading YAML frontmatter block removed.
- Preserve the body content as closely as possible, including normal trailing newlines.
- Print validation and filesystem errors to stderr and return nonzero.
- Require `--reason` to be non-empty because the reason is part of the audit record.

Agent attribution:

- Prefer `SASE_AGENT_NAME`.
- Fall back to `SASE_AGENT` and then to `SASE_ARTIFACTS_DIR/agent_meta.json` fields if present.
- If no agent identity can be found, fail by default with a message explaining that reads are intended to be
  attributable. A later manual/debug mode can be added intentionally if desired.

Log storage:

- Store append-only JSONL under project SASE state, not in the repo, for example:

```text
~/.sase/projects/<project>/memory_reads.jsonl
~/.sase/projects/<project>/memory_reads.lock
```

- Use `project_memory_name(Path.cwd())` for the project key.
- Do not log memory file contents.
- Each JSONL row should include `schema_version`, a stable `id`, ISO timestamp, project name, cwd, canonical memory
  path, resolved path, agent identity, artifacts dir if known, reason, byte count, and whether frontmatter was stripped.
- Use a file lock around appends and reads so concurrent agents do not interleave JSONL writes.

## Phase 1: Memory Read and Log Foundation

Owner: foundation agent.

Scope:

- Add a new module under `src/sase/memory/`, for example `read_log.py` or split into `reading.py` and `read_log.py`.
- Implement path canonicalization and validation for memory-relative paths.
- Implement a small frontmatter stripper for leading `---` blocks.
- Implement agent identity discovery from env and `agent_meta.json`.
- Implement append/read helpers for the project-scoped JSONL log with locking.
- Implement aggregation helpers used by the later `log` UI.

Acceptance:

- Unit tests cover allowed `long/foo.md`, rejected `short/foo.md`, traversal, absolute paths, missing files, and
  outside-root symlink resolution.
- Unit tests cover frontmatter removal and no-frontmatter preservation.
- Unit tests cover log append/read, malformed JSONL tolerance, and basic aggregation.
- No argparse or user-facing command behavior is required in this phase.

Suggested tests:

- New `tests/test_memory_read_log.py`.
- Use `tmp_path` for project roots and monkeypatch `Path.home()` or helper functions so tests never touch the real
  `~/.sase`.

## Phase 2: `sase memory read`

Owner: read-command agent.

Depends on Phase 1.

Scope:

- Extend `src/sase/main/parser_memory.py` with a `read` subcommand.
- Extend `src/sase/main/memory_handler.py` dispatch.
- Add a thin command handler, likely `src/sase/memory/cli_read.py`, that:
  - validates the requested path,
  - reads and prints the frontmatter-stripped body,
  - appends the read event with the required reason,
  - exits with clear nonzero errors for invalid path, missing reason, or missing agent attribution.
- Keep `sase memory` with no subcommand defaulting to `list`.

Acceptance:

- `sase memory read long/foo.md --reason "Need context for X"` prints the body and appends one log row.
- `sase memory read short/foo.md --reason "..."` fails and does not append a log row.
- Missing or blank `--reason` fails at parser or handler level.
- Existing `init` and `list` parser tests continue to pass.

Suggested tests:

- Extend `tests/main/test_memory_handler.py` for parser and dispatch.
- Add CLI-level tests for stdout/stderr behavior with `capsys`.

## Phase 3: `sase memory log` Summary

Owner: log-summary agent.

Depends on Phase 1.

Scope:

- Extend parser and handler with a `log` subcommand.
- Add `src/sase/memory/cli_log.py` with the default summary view.
- Render with Rich, following the style of `sase memory list`.
- Default view should group by canonical memory path and show at least:
  - read count,
  - distinct agent count,
  - last read time,
  - last agent,
  - a short last reason preview.
- Support `--path` and `--agent` filters in summary mode.
- Support `--json` for machine-readable summary output.

Acceptance:

- Empty logs render an understandable empty state.
- Summary counts match multiple reads by multiple agents.
- `--path` and `--agent` filters narrow the summary without crashing on unknown values.
- `--json` emits deterministic JSON suitable for tests.

Suggested tests:

- Rich render tests similar to existing memory list dashboard tests.
- JSON output tests should assert parsed objects, not exact whitespace.

## Phase 4: Drilldown View

Owner: drilldown agent.

Depends on Phase 3.

Scope:

- Add drilldown behavior to `sase memory log`.
- Recommended shape:
  - `sase memory log --path long/foo.md` shows path-level summary plus individual read events for that path.
  - `sase memory log --agent <name>` shows agent-level summary plus individual read events for that agent.
  - `sase memory log --id <read-id>` shows one full event with timestamp, agent identity, reason, cwd, canonical path,
    resolved path, and artifacts dir.
- Keep event IDs short enough to copy from tables but stable enough to look up unambiguously.
- Include a helpful error when `--id` is unknown.

Acceptance:

- A user can go from default summary to an individual read event and see the full reason and agent context.
- Multiple filters compose predictably, or invalid combinations are rejected with a clear parser error.
- `--json --id <read-id>` emits the full raw event object.

Suggested tests:

- Tests for detail rendering, unknown IDs, composed filters, and JSON detail output.

## Phase 5: Integration Hardening

Owner: integration agent.

Depends on Phases 2-4.

Scope:

- Update parser help tests to include `read` and `log`.
- Run focused test suites first, then full repo checks.
- Review error wording and examples so agents know to pass `--reason`.
- Add or update lightweight docs only if the repo has an existing CLI docs surface for memory commands. Do not edit
  memory files unless the user explicitly approves.
- Check whether any generated command catalogs or completion metadata need updates.

Acceptance:

- `just install` has been run in the workspace before checks if needed.
- `just check` passes.
- Focused tests pass:

```bash
pytest tests/main/test_memory_handler.py tests/test_memory_inventory.py tests/test_memory_read_log.py
```

- The command help shows the expected contract:

```bash
sase memory read long/generated_skills.md --reason "Need generated skill context"
sase memory log
sase memory log --path long/generated_skills.md
sase memory log --id <read-id>
```

## Risks and Decisions

- Do not store logs in the repo. Read logging is operational state and should not dirty workspaces.
- Do not log file contents. The stat goal only needs path, agent, time, and reason.
- Start with project-scoped logs. Cross-project reporting can be added later without changing individual event rows.
- Keep the first implementation in Python because the existing memory CLI and inventory are Python-only. If ACE or
  another frontend later needs the same stats, promote the storage/query layer behind a Rust core API then.
- Treat `memory/short` as explicitly disallowed, not merely absent from the allowlist, so the error explains the policy.
