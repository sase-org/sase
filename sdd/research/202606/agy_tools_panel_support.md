---
create_time: 2026-06-20
updated_time: 2026-06-20
status: research
---

# Adding ACE Tools-Panel Support to the Antigravity (`agy`) Provider

## Research Request

The Antigravity (`agy`) LLM provider was added as an MVP (epic `sase-50`,
`sdd/epics/202606/agy_provider_mvp.md`). It streams plain stdout and writes no
tool-call artifacts, so the ACE Agents-tab **Tools panel shows nothing** for an
`agy` run, while Claude/Codex/Qwen/OpenCode runs show a full tool-call timeline.

This note researches the best way to close that gap. It ends with a recommended
solution.

## Bottom Line

The prior MVP research concluded that `agy 1.0.10` "exposes no stable
machine-readable contract" and gated the Tools panel on a future upstream
`--output-format stream-json`. **That conclusion was too pessimistic about the
data, and correct about the stability risk.**

Direct on-disk investigation (this note) shows `agy` **does** persist a complete,
structured tool-call trajectory for every run — just not on stdout. Each
conversation is written to a SQLite database under
`~/.gemini/antigravity-cli/conversations/<uuid>.db`, whose `steps` table holds
the full agent trajectory: tool name, tool-call id, JSON-encoded tool input,
tool output, permission decisions, timestamps, and token counts. The blob
payloads are protobuf, but they decode cleanly with a generic protobuf-wire
walker (no `.proto` file needed — verified locally with `protoc --decode_raw`),
and the tool arguments inside them are plain JSON strings.

So the choice is **not** "data exists vs. doesn't." It is:

- **(A) Keep waiting** for an upstream stdout/JSON contract that Google has shown
  no sign of shipping for `agy`. Tools panel stays empty indefinitely.
- **(B) Parse the conversation SQLite trajectory** into the existing
  `tool_calls.jsonl` schema. Real tool data, available today, fully encapsulated
  in a new `_subprocess_agy.py` / `_tool_call_agy.py` so the ACE reader and panel
  stay provider-neutral and unchanged. The cost is brittleness: the SQLite
  schema, protobuf field numbers, and `step_type` enum are undocumented and can
  change between `agy` releases.
- **(C) Scrape the human TUI / `live_reply.md`** text. Explicitly forbidden by
  the epic; fabricates data; worst stability. Reject.

**Recommendation: Option B**, implemented as a post-run trajectory reader behind
an explicit `agy` version guard, golden fixtures, and graceful "show nothing"
degradation when the format drifts. This is the only path that lights up the
Tools panel without inventing data, and it reuses 100% of SASE's existing
provider-neutral tool-call pipeline. Details and integration points are in
[Recommended Solution](#recommended-solution).

## Background: How the Tools Panel Gets Its Data

The Tools panel is **provider-neutral by construction**. It never knows which
runtime produced a run.

- Producers (each LLM provider) normalize their runtime's events into one
  schema and append rows to `tool_calls.jsonl` in the run's
  `SASE_ARTIFACTS_DIR`. The schema and writers live in
  `src/sase/llm_provider/_tool_calls.py`, `_tool_call_common.py`, and
  `_tool_call_io.py`. Each runtime has a thin normalizer, e.g.
  `_tool_call_claude.py`, `_tool_call_codex.py`, `_tool_call_qwen.py`.
- The consumer (`src/sase/ace/tui/tools/reader.py` →
  `read_tool_calls_for_agent`) reads `tool_calls.jsonl` from the run's artifact
  dirs, parses each line into a `ToolCallEntry`
  (`src/sase/ace/tui/tools/_entry.py`), collapses `ToolUse`+`ToolResult` pairs,
  and the widget (`src/sase/ace/tui/widgets/tools_panel.py`) renders the
  timeline.

The normalized row schema (from `_tool_call_common.base_stream_tool_call_record`
and the `ToolCallEntry` fields) is:

`schema_version`, `recorded_at`, `runtime`, `source`, `event`
(`ToolUse`/`ToolResult`), `status` (`pending`/`success`/`failure`/`interrupted`),
`tool_name`, `tool_use_id`, `tool_input_summary`, `tool_response_summary`,
`duration_ms`, plus optional `session_id`, `cwd`, `error`, `is_interrupt`.

**Key consequence:** if `agy` ever writes a conformant `tool_calls.jsonl`, the
panel works with **zero** TUI changes. This is pinned by
`tests/ace/tui/tools/test_reader_agy.py::test_tools_panel_contract_is_unchanged_for_agy_runtime`,
which asserts that `runtime: "agy"` rows flow through the existing reader
untouched.

## Why `agy` Shows Nothing Today

`AgyProvider.invoke` (`src/sase/llm_provider/agy.py:223`) runs:

```
agy --print-timeout <dur> --model <model> --dangerously-skip-permissions --print <prompt>
```

and streams **plain stdout** through `stream_process_output`
(`src/sase/llm_provider/_subprocess_plain.py:56`). That helper only writes
`live_reply.md` + `live_reply_timestamps.jsonl`. There is no `agy` stream
parser and no `_tool_call_agy.py`, so no `tool_calls.jsonl` is ever produced.
The module docstring (`agy.py:1-11`) states tool-call/usage/thinking artifacts
are "intentionally unsupported until a stable `agy` machine-readable contract
exists."

The companion gate
`tests/ace/tui/tools/test_reader_agy.py::test_agy_run_without_tool_calls_artifact_shows_nothing`
exists specifically to prevent a tempting wrong fix: scraping the
tool-shaped prose in `live_reply.md` into fake rows.

## Investigation: `agy`'s Machine-Readable Surfaces

`agy 1.0.10` (`/home/bryan/.local/bin/agy`) writes everything under
`~/.gemini/antigravity-cli/`. The relevant surfaces and what each actually
contains:

| Surface | Contents | Tool-call data? | Format |
| --- | --- | --- | --- |
| `--print` stdout | Final assistant text only | No | plain text |
| `history.jsonl` | One record per prompt: `{display, timestamp, workspace}` | No | JSON lines |
| `log/cli-*.log`, `cli.log` | Go `klog` language-server lifecycle logs (`I0619 16:01:03 … server.go:1346] …`); only `toolPermission=request-review` settings appear | No | glog text |
| `conversations/<uuid>.db` | **Full agent trajectory: tool calls, inputs, outputs, permissions, timestamps, tokens** | **Yes** | SQLite + protobuf |
| `brain/<uuid>/`, `implicit/*.pb` | Auxiliary memory/state protobufs | partial | protobuf |
| `cache/last_conversations.json` | `{ workspace_abs_path: conversation_uuid }` map | No (but see association) | JSON |

So the conversation SQLite DB is the **only** surface with the real tool-call
timeline. stdout, `history.jsonl`, and the `cli-*.log` files are all dead ends
for this purpose.

### The Conversation Database (`conversations/<uuid>.db`)

It is a normal SQLite 3 database. Schema (verified):

```sql
CREATE TABLE steps (
  idx integer, step_type integer, status integer,
  has_subtrajectory numeric, metadata blob, error_details blob,
  permissions blob, task_details blob, render_info blob,
  step_payload blob, step_format integer, PRIMARY KEY (idx)
);
CREATE TABLE trajectory_meta (trajectory_id text, cascade_id text, ...);
CREATE TABLE gen_metadata (...);      -- token/usage accounting blob
CREATE TABLE executor_metadata (...);
-- plus parent_references, trajectory_metadata_blob, battle_mode_infos
```

The `steps` table is an append-only trajectory. In a real 34-step run
(`bb78d3f6-…`), the `step_type` histogram was
`{14:1, 98:1, 15:16, 132:1, 23:1, 21:14}` — i.e. one user step (14), many
model steps (15), and many tool-result steps (21), exactly the shape the Tools
panel timeline expects.

Each `step_payload` is protobuf, but `protoc --decode_raw` (installed at
`/usr/bin/protoc`) decodes the wire structure with **no `.proto` schema**. A
tool-call step decodes to a clean, mappable structure:

```
1: 132                      # step_type
5 {                         # step body
  4 {                       # tool-call descriptor
    1: "dna8kdvr"           #   tool-call id
    2: "list_permissions"   #   tool name
    3: "{\"toolAction\":\"Listing permissions\",\"toolSummary\":\"…\"}"   # JSON args
    9: "list_permissions"   #   tool name (canonical)
  }
  20 { 4: "bb78d3f6-…" }    # trajectory/conversation id
  6/7/8 { 1: <sec> 2: <ns> } # timestamps
}
```

`run_command` steps carry their arguments as embedded JSON too, e.g.
`{"CommandLine":"pwd && ls -F","Cwd":"/home/bryan/…","WaitMs":…}`, and tool
output bytes appear in adjacent fields. Model steps (type 15) even carry token
counts (`9 { 1:1132 2:18196 3:363 … }`), so the **same** parser could later
populate `usage.json`.

**Takeaways for feasibility:**

- The data is complete and structured, not display text. Extraction is **not**
  "scraping the TUI."
- It is extractable today with a generic protobuf-wire reader (a ~100-line pure
  Python varint/length-delimited walker, or `protoc --decode_raw` piped through
  a small mapper). No dependency on Google publishing a `.proto`.
- Tool input args are JSON strings inside the protobuf, so the
  `tool_input_summary` mapping is direct once the right field is located.
- The fragile parts are exactly the undocumented identifiers: the SQLite column
  names, the protobuf **field numbers** (`5.4.2` = tool name, etc.), and the
  **`step_type` enum** (14/15/21/132/…). Any of these can change in a new `agy`
  release with no notice. This is the real risk, and it is what the
  recommendation must contain.

### The Run → Conversation Association Problem

SASE runs many agents in parallel, and `agy --print` mints a fresh conversation
UUID per run without echoing it on stdout. To consume the right DB, SASE must
map *this run* to *its* `<uuid>.db`. Two viable signals, best used together:

1. **Workspace map.** `cache/last_conversations.json` is keyed by the absolute
   workspace cwd, e.g.
   `"…/sase-org/sase/sase_13": "faa7488a-…"`. `agy` runs with cwd = the agent
   workspace, so after a run SASE can look up
   `last_conversations.json[cwd]`. Because SASE agents run in distinct ephemeral
   `sase_<N>` clones, the cwd is usually unique per agent.
2. **New-DB diff.** Snapshot the set (or max mtime) of `conversations/*.db`
   *before* `Popen`, then pick the DB created/updated during the run. This
   disambiguates the race where two invocations share one cwd (e.g.
   interrupt-resume cycles or the commit finalizer re-invoking in the same
   workspace), where `last_conversations.json` only keeps the latest.

A cleaner future option is to **pin** the id: pass a SASE-generated UUID via
`--conversation <id>`. The flag is documented as "resume by ID"; whether it
*creates* an unknown id needs a one-call spike before relying on it. The
map+diff approach needs no such guarantee and should be the v1 mechanism.

## Options Analysis

| | A. Wait for upstream | B. Parse conversation DB | C. Scrape TUI/stdout |
| --- | --- | --- | --- |
| Tools panel works now | No | **Yes** | Yes (fake) |
| Data fidelity | n/a | Real events | Fabricated |
| Stability | Perfect | Brittle to `agy` releases | Worst |
| Honest (no invented data) | Yes | Yes | **No** |
| Touches ACE reader/panel | No | No | Likely |
| Effort | Zero | Moderate (1 parser + glue) | Low but forbidden |
| Epic alignment | Matches current gate | Matches Phase 5 "if a stable structured contract exists" | Violates non-goals |

Option C is ruled out by `sdd/epics/202606/agy_provider_mvp.md` non-goals and the
existing parity-gate test. Option A is the status quo and indefinite. Option B is
the Phase-5 "structured contract" path — the only nuance is that the contract is
an on-disk SQLite/protobuf trajectory rather than a stdout JSON stream, which
the original plan did not realize was available.

## Recommended Solution

Implement **Option B**: a post-run trajectory reader that normalizes the
conversation DB into the existing `tool_calls.jsonl` schema, guarded for safety.

### Shape

1. **`src/sase/llm_provider/_subprocess_agy.py`** — orchestration:
   - Before invoking `agy`, capture the baseline set of `conversations/*.db`
     (path + mtime).
   - After `agy` exits, resolve the run's conversation id via
     `last_conversations.json[cwd]`, cross-checked against the new-DB diff.
   - Open the resolved `<uuid>.db` read-only (`?mode=ro`, never the live writer
     handle), iterate `steps` ordered by `idx`, and hand each
     `(step_type, status, step_payload)` to the normalizer.
   - Write rows via the existing `append_jsonl` into
     `SASE_ARTIFACTS_DIR/tool_calls.jsonl`.
2. **`src/sase/llm_provider/_tool_call_agy.py`** — pure normalizer:
   - A small protobuf-wire decoder (varint + length-delimited; ignore unknown
     fields) — no `.proto`, no new runtime dependency.
   - Map `step_type` → event/role; emit `ToolUse` rows (tool name, tool-call id,
     JSON args → `tool_input_summary`) and `ToolResult` rows (output/exit →
     `tool_response_summary`, `status`, `duration_ms` from step timestamps).
   - Reuse `base_stream_tool_call_record("agy", …)`, `summarize_tool_input`,
     `summarize_tool_response`, and `ToolCallDurationTracker` from
     `_tool_call_common.py`, exactly as `_tool_call_qwen.py` does.
   - Map `agy` tool names to SASE display names (`run_command` → `Bash`,
     `read_file` → `Read`, `write_file` → `Write`, `edit` → `Edit`, etc.),
     mirroring `_qwen_display_tool_name`.
   - `source: "trajectory"` (a new, accurate label distinct from `"stream"`).
3. **Wire it into `AgyProvider._run_subprocess`** (`agy.py:326`): after
   `stream_process_output` returns, call the new reader. Keep it **best-effort**:
   any failure logs a diagnostic and leaves `tool_calls.jsonl` absent, so a run
   never fails because of artifact extraction.

No change to `src/sase/ace/tui/tools/*` or `tools_panel.py`. The provider-neutral
reader already handles `runtime: "agy"` rows (pinned by the existing parity
test). This keeps the change inside the provider, consistent with
`memory/rust_core_backend_boundary.md` (presentation stays neutral) and the
epic's "no `if provider == 'agy'`" rule.

### Stability Guards (the important part)

Because field numbers and `step_type` values are undocumented:

- **Version pin.** Record the supported `agy` version range (probe
  `agy --version`). On a mismatch, skip extraction and emit a diagnostic rather
  than emitting wrong rows.
- **Golden fixtures.** Commit a small captured `<uuid>.db` (or extracted step
  blobs) under `tests/` and assert the normalizer produces the expected
  `tool_calls.jsonl`. This makes an upstream format change fail loudly in CI
  instead of silently corrupting the panel.
- **Graceful degradation.** Unknown `step_type` → skip the step; malformed
  payload → skip the row + writer diagnostic (the `append_writer_diagnostic`
  pattern already in `_tool_call_qwen.py`). Worst case the panel shows a partial
  or empty timeline — never fabricated rows.
- **Read-only, post-hoc.** Open the DB read-only after the process exits to avoid
  racing `agy`'s writer / SQLite locks.

### Tests

- Extend `tests/test_llm_provider_agy.py`: a fake `conversations/<uuid>.db` +
  `last_conversations.json` drives the reader and asserts normalized rows.
- Add a normalizer unit test with golden step blobs (success, failure,
  `run_command`, `read_file`).
- Keep both existing
  `tests/ace/tui/tools/test_reader_agy.py` gates green: the
  "shows nothing without artifact" test still holds when extraction is disabled
  or unavailable; the "contract unchanged" test now exercises a real `agy` row.
- Add an association test for the parallel-run / shared-cwd race
  (new-DB-diff disambiguation).

### Phasing

1. Spike: confirm field/enum mapping against 2–3 captured DBs and pin the `agy`
   version; optionally probe whether `--conversation <new-uuid>` can pin the id.
2. Land `_tool_call_agy.py` (pure, fixture-tested) — no behavior change yet.
3. Land `_subprocess_agy.py` + association + the `_run_subprocess` hook behind a
   version guard.
4. Bonus follow-up: populate `usage.json` from the token fields in step_type 15
   / `gen_metadata`, closing a second `agy` parity gap with the same DB read.

## Risks and Mitigations

- **Upstream format drift** → version pin + golden fixtures + skip-on-mismatch.
- **Wrong conversation picked under load** → workspace map cross-checked with
  pre/post new-DB diff; association unit test.
- **SQLite lock / partial write** → read-only handle, post-exit read, tolerate
  `OperationalError` by skipping.
- **Scope creep into the ACE reader** → none required; the contract test pins
  neutrality.
- **Perceived equivalence to TUI scraping** → it is not; this is the structured
  event store, not rendered display text. Worth stating explicitly in the
  provider docstring and `docs/llms.md#structured-artifacts-parity-gap`.

## Evidence / Reproduction

All findings are from local `agy 1.0.10` on 2026-06-20:

```bash
agy --help                       # --print, --conversation, --continue, --log-file …
find ~/.gemini/antigravity-cli   # conversations/*.db, history.jsonl, log/cli-*.log, cache/…
python3 -c "import sqlite3; …"    # steps schema; step_type histogram {14,15,21,132,98,23}
protoc --decode_raw < step_blob   # tool name / id / JSON args / timestamps / tokens
cat ~/.gemini/antigravity-cli/cache/last_conversations.json   # {workspace_cwd: uuid}
```

## References

- Epic plan: `sdd/epics/202606/agy_provider_mvp.md` (Phase 5 parity gate)
- Phase 7 hardening: `sdd/research/202606/agy_e2e_hardening.md`
- Migration research: `sdd/research/202606/agy_migration_consolidated.md`
- Provider: `src/sase/llm_provider/agy.py`,
  `src/sase/llm_provider/_subprocess_plain.py`
- Tool-call pipeline: `src/sase/llm_provider/_tool_calls.py`,
  `_tool_call_common.py`, `_tool_call_qwen.py`, `_tool_call_io.py`
- Tools panel: `src/sase/ace/tui/tools/reader.py`,
  `src/sase/ace/tui/tools/_entry.py`,
  `src/sase/ace/tui/widgets/tools_panel.py`
- Parity gate: `tests/ace/tui/tools/test_reader_agy.py`
</content>
</invoke>
