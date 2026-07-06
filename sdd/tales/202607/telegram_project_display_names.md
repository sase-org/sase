---
create_time: 2026-07-06 15:52:16
status: wip
prompt: sdd/prompts/202607/telegram_project_display_names.md
---
# Plan: Telegram Project Display Names

## Context

Recent SASE changes replaced raw project directory keys in user-visible output with configured project display names
while preserving canonical identifiers for lookup, storage, JSON, and command/callback payloads. The main repo now
exposes `sase.project_display_names` helpers such as `project_display_name_for`, `humanize_cl_name`, and
`humanize_cl_names_in_text`.

The `sase-telegram` repo still has several Telegram-visible surfaces that can render raw project keys or
project-prefixed ChangeSpec/agent names. Raw identifiers are also used as routing data, so the fix must be display-only.

## Confirmed Overlooked Surfaces

In `src/sase_telegram/scripts/sase_tg_inbound.py`:

- `/changes [project]` renders the typed project filter in empty-state and header text, and `_changes_button_label()`
  renders `entry.project/entry.name`.
- `/list` renders `agent.project` directly in the agent details line.
- Launch confirmations, kill confirmations, `/kill` selection, and `/fork` selection render raw agent names in visible
  message text and button labels.
- Bead picker labels disambiguate duplicate bead IDs with `entry.project/entry.bead_id`, and bead list errors include
  `project.project`.

In `src/sase_telegram/formatting.py`:

- Plan approval and workflow-complete headers render raw `agent_name`.
- Workflow-complete notes, bead display text, and prompt snippets can contain project-prefixed ChangeSpec/agent tokens.

## Design

Add small local display helpers in the Telegram code that import `sase.project_display_names` lazily and fall back to
identity behavior when running against an older installed `sase`. This preserves compatibility with the plugin's broad
`sase>=0.1.0` dependency while using the new behavior when available.

Use these helpers only for Telegram-visible text:

- Project labels: `project_display_name_for(project)`.
- ChangeSpec/agent labels: `humanize_cl_name(name)`.
- Free-form message text that may contain standalone project-prefixed names: `humanize_cl_names_in_text(text)`.

Do not rewrite:

- Callback data.
- `CopyTextButton` payloads.
- `/changes` filter arguments passed to `list_changespec_xprompt_tags`.
- `entry.tag`.
- persisted project context JSON.
- workspace resolution keys.
- bead callback tokens and subprocess arguments.

## Implementation Steps

1. Add display helper functions, likely in `src/sase_telegram/formatting.py` or a new tiny module if reuse between
   formatting and inbound is cleaner.
2. Update outbound notification formatting to humanize visible agent names, notes, bead display text, and prompt
   snippets, while leaving fork copy text untouched.
3. Update inbound Telegram command rendering:
   - `/changes` header and empty state use a display label for the filter project; button labels humanize both project
     and ChangeSpec name.
   - `/list` project detail uses the display project name.
   - launch, kill, fork, and retry-visible labels humanize agent names; callbacks and copy payloads continue using raw
     names.
   - bead duplicate labels and aggregated project error prefixes use display project names, with callback tokens
     remaining canonical.
4. Add focused regression tests in `tests/test_formatting.py` and `tests/test_inbound.py` that monkeypatch the helper
   layer to simulate configured display names without requiring real project config files.
5. Run `just install`, then focused tests for touched areas, then `just check` in `sase-telegram`.

## Validation

- Confirm tests prove raw identifiers remain in copy/callback payloads while display labels are humanized.
- Run `rg` after the change for direct visible uses of `entry.project`, `agent.project`, `agent_name`, and
  project-prefixed labels in touched code.
- Run the repo-required verification: `just install` and `just check`.
