---
create_time: 2026-04-30 22:56:46
status: done
prompt: sdd/prompts/202604/agent_list_status_grouping.md
---
# Agent List Status Grouping Plan

## Context

This work spans three sibling repos:

- `sase_100` at `/home/bryan/projects/github/sase-org/sase_100`
- `sase-telegram` at `/home/bryan/projects/github/sase-org/sase-telegram`
- `retired chat plugin` at `/home/bryan/projects/github/sase-org/retired chat plugin`

The user-visible goal is to make the Telegram `/list` slash command and Google Chat `.list` dot command group their
agent reply messages by status, matching the mental model of the Agents tab's `by status` grouping.

Current shape:

- Telegram `/list` is implemented in `sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py::_handle_list_command`.
  It calls `sase.agent.running.list_running_agents()` and renders one flat HTML message.
- Google Chat `.list` is implemented in `retired chat plugin/src/retired_chat_plugin/scripts/sase_gc_inbound.py::_format_running_agents`.
  It also calls `list_running_agents()` and renders one flat CommonMark message.
- The Agents tab status grouping semantics live in
  `sase_100/src/sase/ace/tui/models/agent_groups/_buckets.py::status_bucket_for`, with ordered buckets:
  `Needs Attention`, `Running`, `Waiting`, `Failed`, `Done`.
- `list_running_agents()` currently emits `RunningAgentInfo` records whose `status` is normally `RUNNING`, while
  `list_all_agents()` can emit `RUNNING`, `DONE`, and `FAILED`. The design should not accidentally turn `/list` into
  `/resume` or resurrect the removed `.listx` behavior.

## Product Design

Keep `/list` and `.list` scoped to the agents they already list: currently running/live agents. The change is
presentation-first: group that result set by the same status bucket rules used by the Agents tab, so the command is
ready for richer live statuses without changing command meaning.

The output should feel like a compact status dashboard, not a raw dump:

- Top line: total count, e.g. `4 Running Agents`.
- Section headers: status bucket glyph + label + count, in Agents-tab order.
  - `▲ Needs Attention (1)`
  - `▶ Running (2)`
  - `⏳ Waiting (1)`
  - `✗ Failed (0)` and `✓ Done (0)` should be omitted when empty.
- Agent blocks: keep each agent readable at a glance:
  - primary line: agent name, model, duration
  - metadata line: project, workspace number, pid, autonomous flag when present
  - prompt snippet: short, italicized, one line
- Sorting inside each bucket should preserve the current `list_running_agents()` order, which is newest-first today.
- Empty result stays terse: `No running agents.`

Transport-specific polish:

- Telegram should use HTML formatting and existing escaping conventions. Use bold status headers and italic prompt
  snippets. Avoid inline buttons for `/list`; this command is informational.
- Google Chat should use CommonMark, matching the existing `.list`, `.kill`, and `.resume` style. Use bold headers and
  compact blocks separated by blank lines.
- Keep wording consistent across both transports while respecting platform syntax.

## Technical Design

### Phase 1: Core Shared Status Grouping Helper

Repo: `sase_100`

Add a small presentation-neutral helper under `src/sase/integrations/`, for example
`src/sase/integrations/agent_status_groups.py`.

Suggested API:

```python
@dataclass(frozen=True)
class AgentStatusGroup:
    bucket: str
    agents: list[RunningAgentInfo]

def group_agent_statuses(agents: Iterable[RunningAgentInfo]) -> list[AgentStatusGroup]:
    ...

def agent_status_bucket(info: RunningAgentInfo) -> str:
    ...
```

Implementation guidance:

- Reuse the Agents-tab semantics rather than duplicating ad hoc status checks.
- Because `status_bucket_for()` currently expects the TUI `Agent` model, either:
  - create a tiny adapter object with only `status` and `retried_as_timestamp`, or
  - extract the pure status mapping into a shared function and make both the TUI and integration helper call it.
- Prefer the extraction if it stays small; it prevents future drift between the TUI and chat surfaces.
- Preserve the fixed bucket order from the Agents tab.
- Omit empty groups.
- Preserve input order within each group.
- Keep this module free of Telegram, Google Chat, HTML, and Markdown concerns.

Tests:

- `RUNNING` maps to `Running`.
- `WAITING` maps to `Waiting`.
- `QUESTION` maps to `Needs Attention`.
- `FAILED` without `retried_as_timestamp` maps to `Needs Attention`.
- `FAILED` with `retried_as_timestamp` maps to `Failed`.
- `DONE` maps to `Done`.
- Empty buckets are omitted, and input order is preserved within each emitted group.

Acceptance criteria:

- The helper is importable by external plugin repos.
- Existing Agents-tab grouping tests still pass.
- Focused helper tests pass in `sase_100`.
- If `sase_100` is modified, run `just install` if needed and then `just check`.

### Phase 2: Telegram `/list` Grouped Reply

Repo: `../sase-telegram`

Primary file:

- `src/sase_telegram/scripts/sase_tg_inbound.py`

Update `_handle_list_command()` to:

- Fetch agents exactly as it does today with `list_running_agents()`.
- Pass the result through `sase.integrations.agent_status_groups.group_agent_statuses()`.
- Render one HTML message with:
  - `<b>{N} Running Agent(s)</b>`
  - blank line
  - one section per non-empty status group, using the shared bucket order
  - existing agent detail fields: project, `ws#`, `PID`, `autonomous`
  - prompt snippets escaped and italicized
- Keep `_format_agent_description()` available for `/kill` and `/resume`; either reuse it for each list item or add a
  narrowly named list-specific helper if the metadata line needs to differ.
- Avoid changing `/kill`, `/resume`, `/changes`, or launch behavior.

Suggested Telegram shape:

```text
<b>4 Running Agent(s)</b>

<b>▲ Needs Attention (1)</b>
<b>alpha</b>  opus-4-7, 12m
sase · ws#100 · PID 12345
<i>waiting on plan feedback...</i>

<b>▶ Running (3)</b>
...
```

Tests:

- Empty result remains `No running agents.`
- Single `RUNNING` group renders a `▶ Running (N)` section.
- Multiple statuses render in Agents-tab bucket order, independent of input order.
- HTML escaping still covers agent name, project, model, and prompt.
- Existing detail fields still render.

Acceptance criteria:

- `/list` output is grouped and readable.
- Existing Telegram command behavior outside `/list` is unchanged.
- `just check` passes in `../sase-telegram`.

### Phase 3: Google Chat `.list` Grouped Reply

Repo: `../retired chat plugin`

Primary file:

- `src/retired_chat_plugin/scripts/sase_gc_inbound.py`

Update `_format_running_agents()` to:

- Fetch agents exactly as it does today with `list_running_agents()`.
- Group via `sase.integrations.agent_status_groups.group_agent_statuses()`.
- Render one CommonMark message with:
  - `*{N} Running Agent(s)*`
  - one `*{glyph} {bucket} ({count})*` section per non-empty group
  - agent descriptions using the existing `_format_agent_description()` style
- Keep `.kill` no-arg output and `.resume` output as they are unless a tiny shared helper naturally reduces duplication.

Suggested Google Chat shape:

```text
*4 Running Agent(s)*

*▲ Needs Attention (1)*

*alpha* — opus-4-7, 12m
  _waiting on plan feedback..._

*▶ Running (3)*
...
```

Tests:

- Empty result remains `No running agents.`
- Single `RUNNING` group renders `*▶ Running (N)*`.
- Multiple statuses render in Agents-tab bucket order.
- Existing `_format_agent_description()` expectations still pass.
- `.help`, `.kill`, `.resume`, `.changes`, and `.retry` tests are unaffected.

Acceptance criteria:

- `.list` output is grouped and readable.
- Existing Google Chat dot-command behavior outside `.list` is unchanged.
- `just check` passes in `../retired chat plugin`.

### Phase 4: Cross-Repo Consistency Pass

Repos: all modified repos

Work:

- Compare Telegram and Google Chat output with the same mocked agent set.
- Confirm bucket labels and counts match across platforms.
- Confirm the bucket order matches the Agents tab order.
- Confirm the commands still describe themselves as listing running agents unless the underlying API scope changes in a
  future feature.
- If status mapping was extracted from the TUI module, run the relevant Agents-tab grouping tests in `sase_100` before
  the full check.

Validation commands:

```bash
cd /home/bryan/projects/github/sase-org/sase_100 && just install && just check
cd /home/bryan/projects/github/sase-org/sase-telegram && just check
cd /home/bryan/projects/github/sase-org/retired chat plugin && just check
```

## Risks And Non-Goals

- Do not broaden `/list` or `.list` to include done/undismissed agents in this change. That would blur the distinction
  between list/resume/history commands.
- Do not duplicate the TUI status mapping in each plugin repo; that would drift quickly.
- If the current live listing only emits `RUNNING`, the first visible result may be a single `Running` group. That is
  acceptable for this phase because the structure and shared mapping are in place for richer statuses.
- Do not add buttons to `/list`; Telegram already has `/kill` and `/resume` for action-oriented flows.
