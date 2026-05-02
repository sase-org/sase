# Making `status of all running sase agents` Easy for an Agent

## Motivation

When a user asks an agent "Can you give me a status report on all running sase agents?", today the agent has no obvious,
low-token, low-tool-call way to answer. It would have to:

1. Discover that sase stores agent state under `~/.sase/projects/*/artifacts/ace-run/*/`.
2. Walk those dirs, read `agent_meta.json`, skip entries with `done.json`.
3. Verify each PID is alive (subprocess / syscalls).
4. Parse the `RUNNING` field of `{project}.gp` to resolve workspace numbers.
5. Handle the `home` project special case (`running.json`).
6. Dedupe parent/child agents, workflow agents, axe-spawned hook agents.

All of this logic already exists in `src/sase/agent/running.py::list_running_agents()` (lines 41–175), but it is **not
exposed to the CLI** and the agent cannot know about it without code-diving. The TUI renders the same info via
`src/sase/ace/tui/models/agent_loader.py`, but a TUI is not machine-readable.

The rest of this doc catalogs concrete ways to close that gap, roughly ordered by effort vs. payoff.

---

## Idea A — `sase agents` CLI subcommand (HIGH ROI, LOW EFFORT) ⭐

Add a first-class subcommand that wraps `list_running_agents()`:

```
sase agents status         # default: pretty table on stdout
sase agents status -j      # NDJSON / JSON array for machine consumption
sase agents status -p PRJ  # filter to a single project
sase agents status --all   # include DONE/FAILED in addition to RUNNING
```

**Why this matters for the agent**: one shell call, deterministic output, trivially parseable. The agent never has to
learn the on-disk layout.

**Implementation sketch**:

- New `src/sase/main/agents_handler.py`, registered in `parser_commands.py`.
- Reuses `list_running_agents()` verbatim for the RUNNING case; for `--all`, extend with a `list_all_agents()` that
  merges the done-markers loader from `src/sase/ace/tui/models/_loaders/_artifact_loaders.py:393`.
- JSON mode must include: `name`, `project`, `pid`, `model`, `provider`, `workspace_num`, `duration_seconds` (integer,
  not pretty string), `status`, `started_at`, `prompt_snippet` (≤200 chars, already computed).
- Keep pretty output compact (≤1 row per agent, ≤120 cols) so even the pretty form fits in an agent context cheaply.

**Follow-on**: alias `sase ps` for muscle memory — the question is literally "what's running?", and `ps` is the
universal answer.

---

## Idea B — A skill / slash command the agent can invoke (HIGH ROI)

Ship a `sase-generated` skill named something like `agents-status` that:

- Is triggered by the keyword set
  `{"status report", "running agents", "sase agents", "agent status", "what's running"}`.
- Body is short: "Run `sase agents status -j` and summarize the output as a table grouped by project. If there are >10
  agents, show only the 10 most recent and say 'N more'."

This is the cheapest way to make the knowledge discoverable — the agent finds the skill by keyword instead of guessing
paths. Works across all runtimes (Claude / Gemini / Codex) because skills are already uniform per
`memory/short/gotchas.md`.

Prereq: Idea A.

---

## Idea C — Dynamic memory entry (keyword-triggered) (MEDIUM ROI)

Sase already has tier-2 dynamic memory (see `sdd/research/202604/dynamic_memory_implementation.md`). Add a memory file (e.g.
`memory/long-agent-status-report.md`) keyed on `running agents`, `agent status`, `sase ps`. Its content is one
paragraph: "To report on running agents, run `sase agents status -j` — each row is an agent with fields …".

This is lighter than a skill and requires no glob engine change. The downside: dynamic memory only fires when keywords
match the _user_ prompt; if the user phrases the question oddly, the memory won't be loaded. A skill/xprompt is more
robust because the agent itself can decide to invoke it.

Prereq: Idea A.

---

## Idea D — Single-file "running index" (MEDIUM ROI)

Today every status check fan-outs over `~/.sase/projects/*/artifacts/ace-run/*`. For users with many projects or many
archived timestamp dirs this is expensive and can return stale reads (no atomic view).

Maintain `~/.sase/running_index.json` — a single JSON array updated by `launcher.spawn_agent_subprocess()` (append) and
the runner's done-writing path (remove). Each entry mirrors the `_RunningAgentInfo` dataclass plus `artifacts_dir`.

Benefits:

- Reading is one `open()` call, no directory walks, no PID probes unless explicitly verifying.
- Crash-safe refresh: `sase agents status --rebuild` regenerates by walking the file tree (current logic).
- Scales to N projects without fan-out.

Cost: two new write paths + rebuild command. The existing tree still has to stay as the source of truth, since processes
can die without cooperation.

---

## Idea E — Expose via Prometheus / telemetry (LOW-MEDIUM ROI for this task)

The telemetry pipeline (`src/sase/telemetry/metrics.py`) already tracks `AGENT_ACTIVE` and `AGENT_SPAWNS`. The metrics
are **aggregated** — no agent-name label — so they answer "how many are running" but not "what are they?". Adding a
per-agent label to a Prometheus gauge is a cardinality smell and not recommended.

**Verdict**: not a good fit for a _per-agent_ status report. Keep telemetry for health/rate questions
(`sase telemetry health`) and answer the name-level question with Idea A.

---

## Idea F — MCP-style tool endpoint (LOW ROI unless MCP-first)

If sase were to ship an MCP server exposing agent operations to LLMs (`list_running_agents`, `kill_named_agent`,
`tail_agent_output`), the status question becomes a single tool call with typed results. This is cleaner than shelling
out — but it requires shipping and versioning an MCP server, which is a bigger lift than Idea A. Worth considering once
`sase agents status` has shaken out.

---

## Idea G — Pre-inject status into agent context (SessionStart hook) (NICHE)

A `SessionStart` hook could run `sase agents status -j` and prepend a `### RUNNING AGENTS` block to the system prompt
(cf. the dynamic-memory section in `AGENTS.md`). That way the agent can answer the question **before the user even
asks**, with zero tool calls.

Downsides:

- Token cost on every session, even when the user never asks.
- Status is stale the moment the session starts — fine for an opening summary, misleading if the user asks 10 minutes
  in.

Best as opt-in (settings.json flag), not default.

---

## Idea H — Output shape designed for agent consumption (DETAIL)

Whatever surface we ship (Idea A's CLI, or B/C/G), the _shape_ of the output dictates whether an agent can summarize
without burning tokens. Concretely:

- **One agent per line** in pretty mode — avoid multi-line blocks.
- **Fixed column order** — so the agent doesn't have to re-parse headers.
- **Short name column first** — agents tend to summarize by name.
- **ISO timestamps, not "5m3s ago"** — easier to diff, easier to sort.
- **Truncate the prompt to one line** — the user's question is "status", not "transcript"; an agent that wants the
  prompt can read `artifacts_dir/raw_xprompt.md`.
- **Include `artifacts_dir`** — one field lets the agent drill down without re-deriving the path.

Rough target: `-j` output should be ≤500 tokens for a typical 5-agent session, so the agent can slurp it wholesale.

---

## Recommendation

Ship Idea **A** (CLI subcommand with `-j`) first. On top of it, Idea **B** (skill with keyword triggers) makes it
trivially discoverable by any agent runtime. Everything else (D, E, F, G) is an optimization or a different surface —
none of them pay off until the underlying CLI exists.

The whole arc is 1–2 PRs: (1) new `sase agents status` handler that reuses the existing `list_running_agents()` with a
JSON flag; (2) a generated skill + dynamic-memory entry that points at the new command.

## Key References

- `src/sase/agent/running.py:41` — `list_running_agents()` (reusable today).
- `src/sase/agent/running.py:178` — `kill_named_agent()` (companion op).
- `src/sase/ace/tui/models/agent_loader.py` — richer multi-source loader (RUNNING + done.json + workflow + ChangeSpec
  agents). Relevant if `sase agents status --all` needs to cover non-running states.
- `src/sase/ace/tui/models/_loaders/_artifact_loaders.py:210,393,471` — per-source scanners to crib from.
- `src/sase/main/telemetry_handler.py` — pattern for a new handler (subcommand parser + dispatch).
- `src/sase/main/parser_commands.py` — where to register `agents`.
- `memory/short/gotchas.md` — reminder: define `-m`, `-f`, etc. short flags on every new subcommand argument.
