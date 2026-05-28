---
create_time: 2026-05-28 07:19:26
status: done
prompt: sdd/prompts/202605/agent_group_name_prompt.md
---
# Prompt for Optional Saved Agent Group Names

## Goal

When the Agents-tab `save_marked_agents` keymap is triggered, prompt for an optional saved agent group name before
saving and dismissing the marked agents. If the user enters a name, the saved-group revival panel opened by `R` should
show that name. If the user leaves the prompt blank, the current generated group summary should continue to be used.

This should apply to the same app action regardless of entry point: lowercase `s` on the Agents tab and the command
palette command should both use the prompt.

## Current Shape

- `src/sase/default_config.yml` already binds `save_marked_agents` to lowercase `s`; no keymap change is needed.
- `MarkingMixin.action_save_marked_agents()` delegates to `AgentMarkingMixin._save_marked_agent_group()`.
- `_save_marked_agent_group()` currently mutates state immediately, dismisses the candidates in memory, and schedules
  `_run_marked_agent_group_save_persistence_async()`.
- Persistence writes dismissed bundles, a saved group archive record, and the dismissed-agent index. The saved group is
  currently built by `_build_saved_agent_group(agents)`, with a generated `title` such as `3 agents from @backend`.
- The revival panel (`SavedAgentGroupRevivalModal`, opened by `R`) renders `SavedAgentGroupSummaryWire.title` in the row
  and `SavedAgentGroupWire.title` in the preview.
- Saved-group persistence is Rust-core-backed with a Python fallback, so any new persisted metadata belongs in both the
  Rust wire/backend and the Python mirror.

## Product Design

Add a dedicated “Save Agent Group” modal with one input:

- `Enter`: save the marked agents.
- Blank input: save without a custom name and keep the existing generated `title`.
- Nonblank input: save the custom group name.
- `Esc`: cancel without dismissing agents or clearing marks.

Do not reuse `AgentNameModal`; it returns `None` for both blank submission and cancel, but this flow must distinguish
“save unnamed” from “cancel”.

In the revival panel:

- Unnamed groups render exactly as they do today.
- Named groups render the user-provided name as the primary row/preview title.
- The generated `title` remains available as secondary context, so a named group can still show useful summary text such
  as `3 agents from @backend`.

## Data Model

Add an optional `name` field to saved group metadata and summaries:

- `SavedAgentGroupWire.name: str | None`
- `SavedAgentGroupSummaryWire.name: str | None`

Keep the existing `title` field as the generated summary/fallback display string. This avoids throwing away the current
context and keeps old saved groups readable without migration.

Implementation details:

- In `sase-core`, add `#[serde(default)] name: Option<String>` to the full and summary wire structs, propagate it
  through `summary_from_group()`, and normalize empty/whitespace-only names to `None` when saving.
- In the Python wire mirror (`src/sase/core/agent_group_archive_wire.py`), add the same optional field to dataclasses,
  dict rehydration, summary creation, and JSON projection.
- Do not bump the archive schema for this additive optional field. Existing JSON files missing `name` load as `None`.

## TUI Flow

1. In `action_save_marked_agents()`, keep the current tab guard.
2. Replace the direct `_save_marked_agent_group()` call with `_prompt_and_save_marked_agent_group()`.
3. `_prompt_and_save_marked_agent_group()` should:
   - Show the current “No agents marked” / “No marked agents remain” warnings before opening the modal when possible.
   - Push the new modal with context like the marked candidate count.
   - On cancel, do nothing and leave marks intact.
   - On submit, call `_save_marked_agent_group(group_name=result.name)`.
4. Update `_save_marked_agent_group()`, `_run_marked_agent_group_save_persistence_async()`, and
   `_persist_marked_agent_group_save()` to thread the optional name through to `_build_saved_agent_group()`.
5. Keep the optimistic dismiss timing exactly where it is today: after the modal returns, but before async persistence.

This preserves the current fast in-memory dismissal and keeps the new prompt from touching persistence state until the
user confirms.

## Rendering

Update `saved_agent_group_revival_rendering.py` with one display helper:

- `display_title = summary.name or summary.title`

Then:

- Row rendering uses `display_title` as the bold primary label.
- When `summary.name` is present and differs from `summary.title`, append the generated `summary.title` dimmed as
  secondary context.
- Preview rendering uses the name as the heading when present, and shows the generated summary below it.

The empty-state text currently says `Use S on marked Agents-tab rows`; update it to lowercase `s` to match the current
keymap.

## Command Metadata and Help

No default keymap changes are needed. The existing action remains `save_marked_agents`.

Small copy updates are optional but useful:

- Command palette aliases can include `name group` / `saved group name`.
- Help/footer labels can stay as `Save/dismiss marked agents`; the prompt itself makes the naming affordance visible.

## Tests

Add focused coverage in the current repo:

- Modal tests:
  - Enter on blank returns a confirmed result with `name is None`.
  - Enter on a trimmed nonblank value returns the normalized name.
  - Escape returns `None`.
- Action flow tests:
  - Agents-tab lowercase `s` with marks opens the group-name modal before dismissing.
  - Blank submit preserves existing generated `title` behavior.
  - Named submit persists `name` and dismisses the agents.
  - Cancel leaves agents visible and marks intact.
  - Command palette execution of `app.save_marked_agents` opens the same prompt.
- Persistence tests:
  - Python facade round-trips `name` into full group records and list summaries.
  - Missing `name` in existing JSON still loads as `None`.
- Revival rendering tests:
  - Named summaries show the name in rows and previews.
  - Unnamed summaries keep the current row/preview text.

Add Rust-core coverage:

- Saved group save/list/load preserves `name`.
- Missing `name` remains accepted.
- Whitespace-only `name` normalizes to `None`.

## Verification

Before finishing the implementation:

- In `sase-core`: run targeted agent-group archive tests, then the relevant Rust check/test command used by that repo.
- In this repo: run `just install`, focused pytest for saved-group persistence, modal, routing, command palette, keymap,
  and e2e save/revive flows, then the required `just check`.

## Risks and Edge Cases

- The prompt must not collapse blank and cancel into the same result.
- Marks can become stale while the modal is open; the save method should keep its existing stale-mark checks.
- Older saved group files must remain readable.
- The Rust binding and Python fallback must agree on field names and summary behavior.
- Long custom names should be single-line and trimmed; rendering should not rely on unbounded row width.
