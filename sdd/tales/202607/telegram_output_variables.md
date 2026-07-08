---
create_time: 2026-07-07 23:00:21
status: done
prompt: sdd/prompts/202607/telegram_output_variables.md
---
# Plan: Show `/sase_var` Output Variables in the Telegram Agent-Completion Message

## Context

The `/sase_var` skill lets a running SASE agent attach small named string results via `sase var set KEY=VALUE`. These
persist in the agent's `agent_meta.json` under `output_variables` (a `dict[str, str]`) and are already surfaced in the
ACE Agents-tab metadata panel under an `OUTPUT VARIABLES` section. They are currently **invisible in the Telegram
agent-completion message**, which is the fastest place a user actually reads "what did this agent produce?" on their
phone.

Goal: when an agent completes, list the output variables it set inside the Telegram completion message, rendered so it
is intuitive, reliable, and beautiful.

### How the completion message is produced today

The completion message flows across two repos:

1. **Producer — main `sase` repo.** When an agent finishes, `send_completion_notification()` in
   `src/sase/axe/run_agent_runner_finalize.py` assembles an `action_data: dict[str, str]` (model, `llm_provider`,
   `agent_name`, `bead_display`, `runtime`, `pr_url`, `prompt`, `commit_message`, `cl_name`, `raw_suffix`) and calls
   `notify_workflow_complete(sender="user-agent", ...)` in `src/sase/notifications/senders.py`, which stores a
   `Notification`. The agent's `current_artifacts_dir` is already in scope here (the function already reads other
   artifact-dir data such as commit metadata and explicit artifacts).

2. **Consumer — `sase-telegram` linked plugin.** An outbound poller loads unsent `Notification` objects directly from
   the store and calls `format_notification(n)`, which dispatches agent completions (sender `user-agent`, for both the
   success `JumpToAgent` and failure `ViewErrorReport` actions) to `_format_workflow_complete(n)` in
   `src/sase_telegram/formatting.py`. That function builds a Telegram **MarkdownV2** message from `n.action_data` and
   `n.notes`. It reads the raw (un-normalized) `Notification`, so structured data placed in `action_data` arrives
   intact.

### Key facts that shape the design

- `Notification.action_data` is typed `dict[str, str]` and is round-tripped through the Rust-backed notification store.
  Adding a **new string key** to it needs no schema change and **no `sase-core` change**. Adding a new typed field to
  `Notification` would cross into `sase-core`; we deliberately avoid that.
- The Telegram side already `import json` and has the escaping/length primitives we need: `escape_markdown_v2` (escapes
  MarkdownV2 specials incl. `_`, which output-variable keys commonly contain), `_escape_code_entity` (for content inside
  code/pre entities), and truncation constants (`MAX_MESSAGE_LENGTH = 4096`, `PROMPT_DISPLAY_MAX = 1000`).
- The existing ACE renderer `_append_output_variables_section`
  (`src/sase/ace/tui/widgets/prompt_panel/_agent_display_header.py`) is the visual reference: sorted keys, `key: value`
  single line, `key:` header plus 2-space-indented lines for multi-line values.
- `STOP` is a reserved output variable used only to halt `%repeat` chains (`STOP_OUTPUT_VARIABLE` in
  `src/sase/axe/run_agent_repeat_stop.py`). ACE currently shows it; a Telegram completion summary should **not** — it is
  orchestration plumbing, not a user-facing result.

## Design (decisions)

### Data path: carry variables in `action_data` as a JSON string

The producer reads the agent's output variables at completion time, filters out reserved keys, and, if any remain,
serializes them into a single `action_data["output_variables"]` JSON object string. The Telegram consumer parses that
string and renders it. Rationale:

- Snapshotting the variables into the notification at completion time makes the message **reliable and immutable** — it
  cannot drift if the ephemeral artifacts directory is later rotated or re-read, and it needs no fragile artifacts-dir
  inference on the plugin side (the artifacts dir is not currently in `action_data`).
- Reusing `action_data` mirrors the existing pattern exactly (`bead_display`, `runtime`, `pr_url` are already
  string-encoded there via the same `**extra` spread idiom), touches no persisted schema, and keeps `sase-core`
  untouched. There is already a JSON-in-notification precedent on the Telegram side (`question_request.json` parsing).

### Policy lives in the producer; rendering lives in the consumer

- The **producer** owns the "which variables are user-facing" policy: drop `STOP`; sort deterministically. This is
  notification-assembly, consistent with the Python code that already assembles `send_completion_notification`'s
  `action_data`. It is not backend/domain logic, so it stays in the Python repo (no `sase-core`).
- The **consumer** owns presentation: parse and render MarkdownV2. It also defensively drops `STOP` and sorts, so a
  malformed or hand-crafted notification still renders sensibly.

### Intentional difference from ACE: hide `STOP`

ACE is a power-user TUI where showing `STOP` aids debugging of `%repeat` fan-outs. The Telegram message is a curated,
user-facing summary where `STOP: 1` would read as confusing noise. Hiding `STOP` in Telegram while keeping it in ACE is
deliberate and will be documented; ACE behavior is unchanged (out of scope).

### Placement and visual format (the "beautiful" part)

Insert the section **after the `🔗 PR` line and before the `📝 Prompt` block**. Rationale: the header/notes say what
finished, the PR link and the named output variables are the agent's _results_ (kept adjacent), and the input prompt
stays last for reference. When there is no PR (e.g. research agents), the section simply follows the notes.

Rendering rules, echoing ACE (sorted keys; single-line vs multi-line handling) but styled in the Telegram idiom (bold
labels, monospace values, emoji section header, bullet list):

- Section header: `📤 *Output Variables:*`
- Keys sorted alphabetically (matching ACE), each escaped via `escape_markdown_v2` (so underscores in keys like
  `report_path` render literally, not as italics).
- Single-line value: `• *{key}:* \`{value}\``— bold key, value in inline code (escaped with`_escape_code_entity`).
- Empty value: render an italic `_(empty)_` placeholder instead of an empty code span.
- Multi-line value: `• *{key}:*` on its own line, followed by the value in a fenced code block (` ``` `), value escaped
  with `_escape_code_entity`. (No expandable blockquote here, to avoid Telegram's blockquote/code-block split issue; a
  plain fenced block is safe and reads well.)

Reliability caps (bound the section so the message stays under Telegram's 4096-char limit):

- Truncate each value to a new `OUTPUT_VARIABLE_VALUE_MAX` (~300 chars) with a `…` suffix, mirroring the existing
  `PROMPT_DISPLAY_MAX` pattern.
- Show at most `OUTPUT_VARIABLES_MAX_DISPLAYED` (~20) variables; if more exist, append a final `• _…and N more_` line so
  truncation is never silent.

#### Rendered mock-up

A producer that ran `sase var set report_path=dist/report.md status=ok` would extend the message like:

```
✅ *Opus 4.8 Complete*  _@build_

Opus 4.8 @build completed: #gh:sase Add retry logic

🔗 *PR:* https://github.com/example/repo/pull/123

📤 *Output Variables:*
• *report_path:* `dist/report.md`
• *status:* `ok`

📝 *Prompt:*
…
```

(A multi-line value renders its key on one line and the value inside a fenced code block beneath it.)

## Implementation Steps

### Phase 1 — Producer (main `sase` repo)

1. In `src/sase/axe/run_agent_runner_finalize.py`:
   - Add a small helper (e.g. `_completion_output_variables(current_artifacts_dir)`) that calls
     `read_agent_output_variables()` (from `sase.core.agent_output_variables`), drops the reserved key
     `STOP_OUTPUT_VARIABLE` (from `sase.axe.run_agent_repeat_stop`), and returns the remaining `dict[str, str]`. Guard
     with try/except so a missing/unreadable `agent_meta.json` yields `{}` and never blocks the notification.
   - In `send_completion_notification()`, compute the variables once and build an
     `output_variables_data = {"output_variables": json.dumps(vars, sort_keys=True, ensure_ascii=False)}` fragment
     (empty dict when there are no non-`STOP` variables). Spread `**output_variables_data` into **both** the success
     (`JumpToAgent`) and failure (`ViewErrorReport`) `action_data` literals, exactly like the existing `**runtime_data`
     idiom, so failed runs that still set variables display them too. Add the `json` import.
2. This is the only producer change. `notify_workflow_complete` and the `Notification` model are untouched (the value is
   just another `action_data` string key). No `sase-core` changes.

### Phase 2 — Consumer (`sase-telegram` linked repo)

Open the linked repo with `sase workspace open -p sase-telegram -r "<reason>" <workspace_num>` and use the printed path.

1. In `src/sase_telegram/formatting.py`:
   - Add constants `OUTPUT_VARIABLE_VALUE_MAX` and `OUTPUT_VARIABLES_MAX_DISPLAYED` near the other length constants.
   - Add `_format_output_variables_section(action_data: dict[str, str]) -> str` that: reads
     `action_data.get("output_variables")`, `json.loads` it inside try/except (returns `""` on missing/invalid), coerces
     to a string→string map, drops `STOP` defensively, sorts keys, applies the caps, and renders the MarkdownV2 block
     described above. Returns `""` when there is nothing to show.
   - Call it inside `_format_workflow_complete`, inserting its output after the `pr_url` block and before the `prompt`
     block.

### Phase 3 — Docs & discoverability

1. Update the `/sase_var` skill source `src/sase/xprompts/skills/sase_var.md`: the line that currently says values are
   "persisted in `agent_meta.json` and shown in ACE" should also mention they appear in the Telegram agent-completion
   message. After editing, regenerate/deploy the skill (`sase init-skills --force`, then `chezmoi apply`) as the
   generated-skills workflow requires, and update any expected-phrase assertions in
   `tests/main/test_init_skills_sources.py`.
2. If a user-facing doc describes the Telegram/notification completion message (grep `docs/` for "completion" /
   "Telegram"), add a short note there; otherwise skip.

## Test Plan

### Main `sase` repo — `tests/test_run_agent_runner_notifications.py`

The existing tests already drive `send_completion_notification` with a `current_artifacts_dir` under `tmp_path` and
assert on the mocked `notify_workflow_complete` `action_data`. Add cases that write an `agent_meta.json` with
`output_variables` into that dir and assert:

- Variables present → `action_data["output_variables"]` is a JSON string whose parsed value equals the expected map
  (keys sorted), with `STOP` excluded.
- Only `STOP` (or no variables) present → `output_variables` key is absent from `action_data`.
- The failure path (`ViewErrorReport`) also includes the `output_variables` key when variables exist.

### `sase-telegram` repo — `tests/test_formatting.py` (`TestFormatWorkflowComplete`)

Following the file's substring/ordering assertion style, add cases asserting:

- Section renders with `📤 *Output Variables:*`, sorted keys, keys with underscores escaped, values in inline code.
- A multi-line value renders inside a fenced code block under its key.
- Section appears after the `🔗 *PR:*` line and before `📝 *Prompt:*` (via `text.index(...)` ordering).
- Absent entirely when `action_data` has no `output_variables` key, and when the JSON is malformed.
- `STOP` is not rendered even if present in the JSON (defensive filter).
- Long values are truncated with `…`; more than the cap yields a `…and N more` line; empty value shows `(empty)`.

## Verification

After Phase 1 (main repo), in this repo:

```bash
just install
.venv/bin/python -m pytest -q \
  tests/test_run_agent_runner_notifications.py \
  tests/main/test_init_skills_sources.py
just check
```

Note: the full suite can be killed by the sandbox (a known environment issue, exit 144); prefer the targeted subset
above plus the `just check` lint/mypy static gates, and re-run the specific failing test at `origin/master` HEAD before
treating any failure as a regression.

After Phase 2 (telegram repo), from the opened `sase-telegram` workspace path:

```bash
python -m pytest -q tests/test_formatting.py
```

End-to-end smoke (reliable + beautiful check): construct a `Notification` with a completion `action_data` containing an
`output_variables` JSON blob (including a multi-line value, an underscore key, and a `STOP` entry) and run
`format_notification(n)`; confirm the printed MarkdownV2 shows the section correctly, hides `STOP`, and stays valid
MarkdownV2.

## Risks and Decisions

- **Carrier choice.** Encoding the map as a JSON string in `action_data` (vs. a new `Notification`/wire field) is
  deliberate: it keeps the change inside the two frontend/notification repos with zero `sase-core` schema work, matching
  the existing `action_data` string-encoding pattern.
- **Hiding `STOP` in Telegram but not ACE** is an intentional, documented divergence (curated summary vs. debugging
  TUI).
- **Length safety.** Per-value truncation plus a max-count guard bound the section; there is no global overflow guard on
  the workflow-complete path other than per-field caps, so these caps are required, not optional.
- **Escaping.** Keys go through `escape_markdown_v2` (underscores are common and are MarkdownV2 specials); values go
  through `_escape_code_entity` because they are rendered inside code entities. This prevents malformed MarkdownV2 from
  arbitrary user-set values.

## Non-Goals

- Do not change the `sase var set` CLI, the `agent_meta.json` storage format, or the cross-agent Jinja `agents` context.
- Do not change ACE's `OUTPUT VARIABLES` rendering (including its display of `STOP`).
- Do not add a field to `Notification` or change `sase-core` / the notification wire.
- Do not modify memory files (`memory/*.md`, `AGENTS.md`, provider shims).
- Do not change non-completion notification types (plan/launch/HITL/question/error-digest).
