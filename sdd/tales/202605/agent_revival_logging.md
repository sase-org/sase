---
create_time: 2026-05-11 14:41:31
status: done
prompt: sdd/prompts/202605/agent_revival_logging.md
---
# Agent Revival Logging and Query Tooling

## Context

The `R` keymap on the Agents tab is bound to `action_start_rewind` in `src/sase/ace/tui/bindings.py:26`, which
dispatches to `_revive_agent()` for the agents tab in `src/sase/ace/tui/actions/agents/_revive.py:147-152`. The actual
work happens in `_do_revive_agent()` (line 300) and `_do_revive_agents()` (line 354), which:

- mutate `~/.sase/dismissed_agents.json` via `save_dismissed_agents()`
- restore artifact files via `_restore_agent_artifacts()`
- delete bundles under `~/.sase/dismissed_bundles/YYYYMM/` via `remove_bundle_by_identity()`
- reload agents and refresh the panel

The only observability today is an in-app `self.notify()` toast on success ("Revived agent for <cl_name>", line 347;
"Revived N agents", line 413) or on "no dismissed agents to revive" (line 159). Failures inside the revival flow
(missing bundle file, IO errors restoring artifacts, exceptions in `_load_agents()`) are not surfaced to the user and
are not persisted anywhere on disk.

This was discovered when an agent was asked "what was the last agent I tried to revive?" and could not answer —
`~/.sase/dismissed_agents.json` mtime tells you _that_ something changed at 14:33, but not _which_ agent, and the
deleted bundle files leave no forwarding address.

The existing `sase.logs.run_log` module already writes append-only JSONL to `~/.sase/logs/events.jsonl` for events like
`commit_created`, `changespec_reverted`, `changespec_restored`, and `hook_completed` (`src/sase/logs/run_log.py:71`).
Revival fits the same pattern.

## Goals

After this work, an agent or the user should be able to answer:

- What was the most recent revival attempt? When? Did it succeed?
- Which agents have been revived in the last day/week, and from what dismissed bundle paths?
- Why did a particular revival fail — missing bundle, artifact restore error, exception during reload?
- For batch revivals, how many agents were in the batch and which ones?

## Non-Goals

- No change to revival semantics (what gets restored, when bundles are deleted, dismissed-set bookkeeping). This is
  observability only.
- No new UI surface beyond the existing toast and an optional debug entry point. The audit log is for the agent/CLI
  consumer, not the TUI.
- No retention/rotation policy for `events.jsonl` in this work — the file is already long-lived and shared with other
  events.

## Rust Core Boundary Call

This work stays **Python-side** in the TUI action layer. Rationale:

- Revival manipulates `~/.sase/dismissed_agents.json` and the dismissed bundle directory through
  `src/sase/ace/dismissed_agents.py`, which is Python-only today. There is no Rust counterpart in `sase-core` for the
  dismissed-agents store; this is a TUI/local-state concern, not core domain.
- The event log target (`~/.sase/logs/events.jsonl`) is already written from Python via `log_event()` and is not
  mirrored in `sase-core`.
- Other frontends (a hypothetical web/CLI revive command) would not need revival behavior to _match_ the TUI — there is
  no such frontend, and even if there were, the audit hook belongs at the TUI action boundary because that is where user
  intent is captured.

If a future change moves dismissed-agent storage into `sase-core`, the audit event should move with it; until then,
Python is correct.

## Phase 1 — Event Schema and Emission Points

Owner scope: `src/sase/ace/tui/actions/agents/_revive.py` and a small helper module.

Add two new event kinds, written via the existing `log_event()` helper:

- `agent_revive_started` — emitted once at the top of `_do_revive_agent` and once for the batch entry in
  `_do_revive_agents`. Captures the user intent before any mutation, so a crash mid-revival still leaves a record.
- `agent_revived` — emitted at the success notify point (lines 347, 413).
- `agent_revive_failed` — emitted from a new `try/except` wrapper around the body of `_do_revive_agent` and
  `_do_revive_agents`, plus the "No dismissed agents to revive" early-out (line 159) recorded as `agent_revive_failed`
  with `reason="no_dismissed_agents"`.

Fields for a single-agent revival (`agent_revived` / `agent_revive_failed`):

- `timestamp` — populated by `log_event`.
- `agent_identity` — three-tuple from `Agent.identity` serialized as a list `[agent_type, cl_name, raw_suffix]`.
- `cl_name`
- `raw_suffix`
- `agent_type` — the `AgentType` enum value.
- `project_file` — `Agent.project_file` (path to the `.gp`).
- `bundle_path` — the path under `~/.sase/dismissed_bundles/` that was removed, if known. Populated from the bundle file
  used to load the agent (the loader sets `_loaded_from_dismissed_bundle`); add a sibling attribute
  `_dismissed_bundle_path: str | None` populated alongside it in `_load_dismissed_archive` and on the in-memory
  dismissed objects so the revive emission has the value to log.
- `child_suffixes` — list of revived child/follow-up raw suffixes (the `child_suffixes` set that already gets passed to
  `remove_bundle_by_identity`).
- `batch_size` — `1` for single, `len(valid_agents)` for batch.
- `selection_scope` — the `SelectionItem.item_type` from the project selector ("all", "home", "project", "cl") plus
  `project_name`/`cl_name` when applicable. Plumb this through `_show_dismissed_agents_for_scope` → modal callback →
  `_do_revive_agent(s)`.
- `outcome` — `"success"` or `"failure"`. (Implicit in the event name, but redundant fields make ad-hoc queries easier.)
- For failures: `error_type` (exception class name), `error_message` (the `str(exc)` truncated to 500 chars), and
  `stage` — one of `"dismissed_set_update"`, `"artifact_restore"`, `"bundle_removal"`, `"reload"`, `"refresh_display"`,
  `"no_dismissed_agents"`. The stage is set by wrapping each of the four phases in `_do_revive_agent` /
  `_do_revive_agents` with a local stage variable.

For batch revivals, emit one `agent_revive_started` and one terminal event per agent (success or failure) so the log
reflects partial-success cases — a batch of five where two fail should produce two failure records, not a single "batch
failed" record. The phase-3 loop in `_do_revive_agents` is the natural emission point.

Helper module: introduce `src/sase/ace/tui/actions/agents/_revive_log.py` exposing `log_revive_started(...)`,
`log_revive_success(...)`, and `log_revive_failure(...)` so the call sites stay readable and the field construction
lives in one place. The helpers wrap `log_event()` and swallow any logging exception (wrapped in a broad `except` that
calls `self.app.log` only) — a broken log writer must never break a revival.

## Phase 2 — Query Helpers

Owner scope: `src/sase/logs/` and a small CLI surface.

Add a query helper so agents/users do not need to grep JSONL by hand:

- New function `iter_revive_events(since=None, until=None, outcome=None) -> Iterator[dict]` in
  `src/sase/logs/run_log.py` (or a sibling `query.py` if `run_log.py` should stay write-only). Reads `events.jsonl` in
  reverse, filters on the new event kinds, and yields parsed records.
- New CLI subcommand `sase revive-log` exposed through the existing `sase logs` entry or as a sibling command. Two
  output modes:
  - default: a Rich table of timestamp, cl_name, raw_suffix, outcome, reason. Last 20 by default, `--all` for the full
    file, `--since` accepting the same daterange grammar as `sase logs`.
  - `--json` / `--jsonl`: raw records for agent consumption.
- Document the schema and CLI in `memory/short/gotchas.md` is **not** the right home — instead add a short doc page
  under `docs/troubleshooting/agent-revival.md` that lists the events, schema, and `sase revive-log` invocations.
  Reference it from the help modal's troubleshooting hint if one exists; otherwise leave the file discoverable via
  `mkdocs` only.

## Phase 3 — Tests

Owner scope: `tests/` mirroring the existing revive test layout.

- Unit tests for `_revive_log.py`: round-trip a record through `log_event()` and read it back via `iter_revive_events`.
  Use a tmp `SASE_HOME`/`~/.sase` override (existing tests do this already; reuse the fixture).
- Integration tests in the existing revive test module (`tests/ace_tui_actions/test_revive*.py` or equivalent — locate
  by grepping for `_do_revive_agent`): assert that a successful single revival emits exactly one `agent_revive_started`
  and one `agent_revived` event with the expected `cl_name`, `raw_suffix`, and `bundle_path`.
- Failure path test: monkeypatch `_restore_agent_artifacts` to raise, assert `agent_revive_failed` is emitted with
  `stage="artifact_restore"` and the right `error_type`/`error_message`, and that the failure does not prevent the
  toast/notify call from running (failure should still notify the user with `severity="error"`).
- Batch test: revive three agents where the middle one fails, assert one started + two success + one failure events.
- CLI test: feed a synthetic `events.jsonl` and assert the table and JSON outputs of `sase revive-log`.

## Phase 4 — Backfill Consideration

Skip. There is no recoverable history before this change ships, and the deleted bundle files cannot be reconstructed.
The first revival after this lands becomes the earliest entry. Call this out in the docs page so users do not expect
retroactive answers.

## Files Touched

- `src/sase/ace/tui/actions/agents/_revive.py` — instrument the four emission points and add the failure wrappers.
- `src/sase/ace/tui/actions/agents/_revive_log.py` — new helper module.
- `src/sase/ace/tui/actions/agents/_revive.py` (and `_load_dismissed_archive` / loader for `_dismissed_bundle_path`) —
  small attribute plumbing so the bundle path is available at emission time.
- `src/sase/logs/run_log.py` (or new `src/sase/logs/query.py`) — add `iter_revive_events`.
- `src/sase/main/<dispatcher>.py` — wire up `sase revive-log` subcommand (locate the same way the existing `sase logs`
  command is wired).
- `docs/troubleshooting/agent-revival.md` — schema + CLI usage.
- Tests under `tests/` matching the existing revive test module.

## Risks

- Disk I/O on the revival hot path: `log_event` does an `fcntl`-locked append. The dismissed-agents flow already does
  several disk writes, so one more append is fine, but the helper must swallow logging errors so a full disk or
  permission issue does not break revival.
- `events.jsonl` growth: revival is rare, so growth is negligible compared to existing event volume. No rotation needed
  in this work.
- Schema drift: the `agent_identity` tuple shape is the right primary key; reusing it (rather than inventing a new ID)
  keeps the log joinable with dismissed-bundle filenames and the in-memory model.
