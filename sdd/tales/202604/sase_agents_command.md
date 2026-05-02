---
create_time: 2026-04-23 17:18:19
status: done
prompt: sdd/prompts/202604/sase_agents_command.md
---
# `sase agents` — First-Class CLI for Running-Agent Visibility

## Motivation

When a user (or another agent) asks "what's running right now?", there is no first-class answer. The machinery already
exists — `src/sase/agent/running.py::list_running_agents()` walks `~/.sase/projects/*/artifacts/ace-run/*/`, filters by
liveness, dedupes parent/child and hidden workflow agents, and returns a clean dataclass — but it is **not wired to the
CLI**. The only surface is the TUI (`sase ace`), which is not machine-readable and not scriptable.

`sdd/research/202604/agent_status_report.md` lays this out explicitly (Idea A, "HIGH ROI, LOW EFFORT"). This plan ships that idea
plus two small companion ops that fall out naturally from the same module.

## Design Principles

1. **Intuitive.** `sase agents` alone does the obvious thing (status). Short flags match the rest of the CLI (`-j`,
   `-p`, `-a`, `-n`). Exit codes match existing telemetry conventions (0 success, non-zero failure).
2. **Reliable.** Reuse `list_running_agents()` verbatim — its edge cases (dead PIDs, home project, workflow hidden
   steps, parent/child dedup) are already handled and tested in production via `sase ace`. Don't rewrite, don't fork.
3. **Beautiful.** Rich table with color-coded status (from `ace/display_helpers.py::get_status_color`), provider badges
   (claude=orange, gemini=blue, codex=green), right-aligned duration, friendly empty state, single-line rows.
4. **Agent-consumable.** JSON mode hits the target from the research doc: ≤500 tokens for a 5-agent session, fixed
   schema, ISO timestamps, `artifacts_dir` included so the calling agent can drill down without re-deriving paths.

## Command Surface

```text
sase agents                        # alias for `status` (bare form)
sase agents status                 # pretty rich table of RUNNING agents
sase agents status -j, --json      # JSON array (one object per agent)
sase agents status -p, --project   # filter by project name
sase agents status -a, --all       # include DONE/FAILED, not just RUNNING
sase agents kill   -n, --name NAME # SIGTERM the named agent (wraps kill_named_agent)
sase agents show   -n, --name NAME # full detail panel for one agent
```

Bare `sase agents` (no subcommand) defaults to `status` for muscle memory. `sase ps` as a top-level alias is listed as
an open question below — cheap to add but may clutter the top-level namespace.

## Output Shape

### Pretty (`sase agents status`)

```
╭─ Running Agents (3) ────────────────────────────────────────────────────────────────╮
│ NAME           PROJECT  WS  MODEL            PROVIDER  DURATION  STATUS   PROMPT    │
│ brisk-otter    sase     3   claude-opus-4.7  claude    1h12m     RUNNING  Fix the…  │
│ calm-fox       dotfiles 1   gemini-2.5-pro   gemini    4m31s     RUNNING  Audit …   │
│ eager-hawk     home     –   codex-mini       codex     12s       RUNNING  Tail th…  │
╰─────────────────────────────────────────────────────────────────────────────────────╯
```

Column rules (from `sdd/research/202604/agent_status_report.md` Idea H):

- Single line per agent, fixed column order.
- `NAME` first (agents tend to summarize by name).
- `WS` is `–` for home-project agents where workspace_num is `None`.
- `STATUS` color-coded via `get_status_color` scheme (green RUNNING, yellow WAITING, red FAILED, gray DONE).
- `PROVIDER` rendered as a colored badge — anthropic/orange, gemini/blue, openai/green, unknown/white.
- `DURATION` right-aligned; reuse the pretty string already produced by `list_running_agents()`.
- `PROMPT` truncated to 80 chars (single line, ellipsis suffix). No multi-line blocks.

Empty state:

```
╭─ Running Agents (0) ─────────────────────────────────────────────╮
│ No running agents.                                               │
│ Start one with `sase run <xprompt>` or `sase ace`.               │
╰──────────────────────────────────────────────────────────────────╯
```

### JSON (`sase agents status -j`)

```json
[
  {
    "name": "brisk-otter",
    "project": "sase",
    "pid": 12345,
    "model": "claude-opus-4.7",
    "provider": "claude",
    "workspace_num": 3,
    "status": "RUNNING",
    "duration_seconds": 4321,
    "started_at": "2026-04-23T12:34:56+00:00",
    "prompt_snippet": "Fix the bug where…",
    "artifacts_dir": "/home/bryan/.sase/projects/sase/artifacts/ace-run/20260423123456"
  }
]
```

Stable schema; never reorder keys; `prompt_snippet` capped at 200 chars. `duration_seconds` is an integer (easier to
diff/sort than the pretty string). `started_at` is ISO 8601 with timezone.

### `--all` mode

Extends the listing with DONE and FAILED agents by scanning `done.json` in each artifact dir (pattern: crib from
`src/sase/ace/tui/models/_loaders/_artifact_loaders.py:393`). New helper `list_all_agents()` in `agent/running.py`
returns the same dataclass extended with a `status` field. `status` becomes first-class in the output (it's implicit
"RUNNING" in the default mode). **Cap**: most-recent-50 per project to keep the walk bounded; documented in `--help`.
(Open question — see below.)

### `show`

Full rich `Panel` per agent. Reads `agent_meta.json`, `raw_xprompt.md` (full, not truncated),
`attempts/*/attempt_meta.json` if present, plus a live tail hint (`tail -f <artifacts_dir>/live_reply.md`). One screen,
no pagination.

### `kill`

One-liner result echoed to stdout: `Killed agent 'brisk-otter' (PID 12345).` Errors (no such agent, permission denied,
already done) write to stderr and exit non-zero. **No confirmation prompt** — `kill` is explicit and named; we don't
want an interactive prompt breaking scripts. (Open question — see below.)

## Exit Codes

| Code | When                                                                   |
| ---- | ---------------------------------------------------------------------- |
| 0    | Listing/show succeeded (even with 0 agents); kill succeeded.           |
| 1    | Unexpected error (I/O failure, bad JSON, argparse subcommand missing). |
| 2    | `kill`/`show` failed because the named agent doesn't exist or is done. |

Matches `telemetry/cli_health.py` conventions (0/1/2 tiered).

## Implementation Phases

Each phase is independently shippable. Target one PR per phase, or bundle 1+2 if small.

### Phase 1 — Parser + `status` pretty + JSON (MUST-HAVE)

**New files:**

- `src/sase/main/agents_handler.py` — dispatcher (mirror of `telemetry_handler.py`, ~40 lines).
- `src/sase/agents/cli_status.py` — renders pretty table and JSON using `rich.table.Table` + `rich.panel.Panel`. Reuses
  `list_running_agents()` verbatim. ~120 lines.

**Modified files:**

- `src/sase/main/parser_commands.py` — new `register_agents_parser()` (mirror of `register_telemetry_parser`, ~50 lines
  for phase 1 scope).
- `src/sase/main/parser.py` — import + call in alphabetical order (between `register_ace_parser` and
  `register_axe_parser` — verify alphabetical placement).
- `src/sase/main/entry.py` — dispatch arm in alphabetical order (between `ace` and `axe`).

**New tests:**

- `tests/main/test_agents_handler.py` — mirror `tests/main/test_init_skills_handler.py`. Cover: pretty empty, pretty
  populated, JSON shape, JSON field presence, project filter, bare `sase agents` → status. Use `unittest.mock.patch` on
  `list_running_agents` to inject fixture rows.

**Acceptance:**

- `sase agents` prints a table.
- `sase agents status -j | jq '.[0].name'` returns the first agent's name.
- `just check` passes.

### Phase 2 — `--all`, `kill`, `show`

**Modified files:**

- `src/sase/agent/running.py` — new `list_all_agents()` that extends `list_running_agents()` by also scanning
  `done.json` markers. Adds `status` field to `_RunningAgentInfo` (or introduces a new `_AgentInfo` superset — prefer
  adding the field to the existing dataclass with default `"RUNNING"` to avoid a parallel type).
- `src/sase/agents/cli_status.py` — plumb `--all` to call the new function.
- `src/sase/agents/cli_kill.py` — new, thin wrapper over `kill_named_agent()` with exit-code mapping.
- `src/sase/agents/cli_show.py` — new, reads artifact dir and renders a Panel.
- `src/sase/main/parser_commands.py` — extend `register_agents_parser` with `kill` and `show` subparsers.
- `src/sase/main/agents_handler.py` — extend dispatch.

**New tests:**

- `tests/main/test_agents_handler.py` — extend with: `--all` includes DONE, `kill` success, `kill` failure (no such
  agent), `show` missing agent exits 2.

**Acceptance:**

- `sase agents status --all` lists finished agents from today.
- `sase agents kill <name>` terminates the process and returns 0.
- `sase agents show <name>` renders a detailed panel.

### Phase 3 — Generated skill + dynamic memory

**New files:**

- `src/sase/xprompts/skills/sase_agents_status.md` — generated skill, frontmatter keywords: `running agents`,
  `agent status`, `sase agents`, `what's running`, `status report`. Body: "Run `sase agents status -j` and summarize as
  a table grouped by project. If >10 agents, show 10 most recent and say 'N more'."
- `.sase/memory/long-agent-status-report.md` — dynamic memory entry keyed on the same keywords, one-paragraph body
  pointing at the CLI command.

**Regeneration:** Run `sase init-skills --force` per `memory/long/generated_skills.md` to deploy.

**Acceptance:**

- Keyword-triggered skill appears in `~/.claude/skills/` after regeneration.
- Typing "what's running?" to an agent loads the dynamic-memory entry.

### Phase 4 — `sase ps` alias (optional)

Top-level `sase ps` registered as a hidden parser that forwards to `handle_agents_command` with
`agents_subcommand="status"`. Implementation: ~10 lines in `parser_commands.py` + a dispatch arm in `entry.py`.

Gated on user approval in the plan review (see open questions).

## File List

| File                                             | Change                                                    |
| ------------------------------------------------ | --------------------------------------------------------- |
| `src/sase/main/agents_handler.py`                | NEW — dispatch handler                                    |
| `src/sase/agents/__init__.py`                    | NEW — empty package marker                                |
| `src/sase/agents/cli_status.py`                  | NEW — pretty + JSON rendering                             |
| `src/sase/agents/cli_kill.py`                    | NEW — kill wrapper (Phase 2)                              |
| `src/sase/agents/cli_show.py`                    | NEW — detail panel (Phase 2)                              |
| `src/sase/agent/running.py`                      | Extend: add `status` field, `list_all_agents()` (Phase 2) |
| `src/sase/main/parser_commands.py`               | Add `register_agents_parser`                              |
| `src/sase/main/parser.py`                        | Import + register, alphabetical                           |
| `src/sase/main/entry.py`                         | Dispatch arm, alphabetical                                |
| `src/sase/xprompts/skills/sase_agents_status.md` | NEW — generated skill source (Phase 3)                    |
| `.sase/memory/long-agent-status-report.md`       | NEW — dynamic memory entry (Phase 3)                      |
| `tests/main/test_agents_handler.py`              | NEW — handler + rendering tests                           |

Note on package location: the implementation lives under a new `src/sase/agents/` package (not `src/sase/agent/`, which
is internal machinery). Handler under `src/sase/main/agents_handler.py` matches the existing handler layout.

## Reused Building Blocks

- `src/sase/agent/running.py::list_running_agents()` — lines 41–175, reused verbatim.
- `src/sase/agent/running.py::kill_named_agent()` — lines 178–263, reused verbatim.
- `src/sase/ace/display_helpers.py::get_status_color` — status color scheme (extend with `RUNNING`, `DONE`, `FAILED`,
  `WAITING` keys if not already present).
- `src/sase/telemetry/cli_list.py` — closest template for table + panel rendering.
- `src/sase/main/telemetry_handler.py` — dispatch pattern.

## Risks

1. **`--all` walk cost.** Scanning every archived `ace-run/*` directory across all projects could be slow for long-lived
   installs. Mitigation: cap at most-recent-50 per project, document the cap. Open to tuning.
2. **`list_all_agents()` API shape.** Adding a `status` field to `_RunningAgentInfo` changes the shape consumed by
   `list_running_agents()` callers. The dataclass is underscore-prefixed (module-private), so the blast radius is
   contained to `sase.agent.running` and `sase.ace`. Any external tools parsing this would break, but there are none.
3. **`kill` with no confirmation.** Explicit by name; scripts may rely on non-interactive behavior. A future `--force` /
   `-y` gate can be added if user asks, but default to non-interactive (see open question).
4. **Home-project coverage.** Already handled by `list_running_agents()` (iterates every project dir including `home`,
   derives PID from `running.json` when workspace-claim file is absent). `workspace_num=None` renders as `–`. No extra
   work needed; call out in tests.

## Open Design Questions

1. **`sase ps` alias?** Pro: muscle memory, the universal "what's running" shorthand. Con: pollutes the top-level
   namespace with a two-letter command that could collide with future subcommands. **Recommendation:** ship it in Phase
   4 behind user approval; easy to remove if it proves noisy.
2. **`--all` scan depth?** Option A: scan every archived timestamp dir (complete, slow). Option B: cap at most-recent-N
   per project (fast, may miss older entries). **Recommendation:** B with N=50 default, add `--limit` flag if users ask.
3. **`kill` confirmation?** Option A: non-interactive (current proposal). Option B: confirm unless `--yes`/`-y`.
   **Recommendation:** A — the command is explicit, named, and rarely used; a prompt breaks scripts and isn't worth the
   guardrail. Reconsider if we add `sase agents kill --all` (not proposed here).
4. **Provider badge colors.** Proposing claude=orange (#D97757), gemini=blue (#4285F4), codex=green (#10A37F). Verify
   these pair well with the existing `styles.tcss` palette before committing — swap if they collide with an existing
   color role.
5. **Include `approve` in pretty output?** `_RunningAgentInfo` carries an `approve: bool` field (auto-approve mode).
   Useful for ops, adds a column. **Recommendation:** include in JSON, omit from pretty to keep rows single-line; add
   only if asked.

## Non-Goals

- A TUI tab for agents — `sase ace` already has one.
- A Prometheus metric per agent — cardinality smell (see Idea E in the research doc).
- An MCP tool endpoint — bigger lift, deferred (Idea F).
- A `SessionStart` hook that pre-injects status into the prompt — opt-in feature, deferred (Idea G).
- Integration with `sase axe` — out of scope; axe state is rendered in `sase ace` already.
