---
create_time: 2026-05-01 17:48:58
status: done
bead_id: sase-1v
prompt: sdd/prompts/202605/sase_notify_skill_1.md
---
# Plan: `/sase_notify` Skill for Agent Notification Access

## Problem

SASE has a notification store at `~/.sase/notifications/notifications.jsonl` and user-facing notification UI in ACE, but
agents do not have a first-class recipe for answering prompts like:

```text
Can you help me fix the axe errors I just got a sase notification about?
```

The existing `/sase_agents_status`, `/sase_changespecs`, and `/sase_chats` skills all follow the same successful
pattern: they point agents at a stable SASE CLI surface, prefer JSON for discovery, and give compact summarization
rules. `/sase_notify` should follow that model. It should not teach agents to hand-parse the notification JSONL file or
know TUI-only details.

## Current Context

- Generated skill source files live under `src/sase/xprompts/skills/`.
- Live provider skill files are generated from those sources by `sase init-skills --force`; do not hand-edit generated
  provider `SKILL.md` files.
- Existing skill sources:
  - `src/sase/xprompts/skills/sase_agents_status.md`
  - `src/sase/xprompts/skills/sase_changespecs.md`
  - `src/sase/xprompts/skills/sase_chats.md`
- The notification model is `src/sase/notifications/models.py`.
- The store API is `src/sase/notifications/store.py`, backed by the Rust facade in `src/sase/core/notification_store_*`.
- The current `sase notify` CLI only creates notifications. It accepts JSON on stdin plus `--sender` and writes one
  notification. This behavior must remain backward-compatible.
- Notification docs live at `docs/notifications.md`.

## Design Direction

Add a read-oriented CLI surface to `sase notify`, then make `/sase_notify` a generated skill that tells agents exactly
how to use it.

The proposed command surface is:

```text
sase notify list -j
sase notify list -j -l 20
sase notify list -j -q '<text>'
sase notify list -j --sender axe
sase notify list -j --unread
sase notify list -j --all
sase notify show --id <notification_id>
sase notify show --id <notification_id> -f json
sase notify show --id <notification_id> -f markdown
```

Keep `sase notify` without a subcommand as the legacy create path. Adding `sase notify create` as an explicit alias is
fine, but not required unless it simplifies parser implementation.

The skill should use `sase notify list -j -l 20` as its primary discovery command and `sase notify show --id ...` for
exact inspection. For axe digest notifications, the notification's `files` or `action_data.error_report_path` will point
at the digest file; the skill should tell agents to read that attached file after identifying the notification.

## Non-Goals

- Do not move notification storage logic out of the existing Rust-backed store for this work.
- Do not add notification mutation behavior such as mark-read, dismiss, mute, or snooze for the skill. The skill is for
  inspection.
- Do not expose TUI-only rendering internals through the CLI.
- Do not introduce provider-specific behavior for Claude, Gemini, Codex, or external provider.

## Phase 1 - Notification Catalog Foundation

Build the reusable read/query layer without parser wiring or skill changes.

### Scope

- Add a small helper module, likely `src/sase/notifications/catalog.py`.
- Define a dataclass such as `NotificationInfo` or serialize directly from `Notification`, but keep a single stable JSON
  projection helper.
- Read notifications through `sase.notifications.store.load_notifications()` or `read_notification_snapshot()` rather
  than opening the JSONL file directly.
- Apply due-snooze expiry only if the existing store API already exposes it cheaply and safely for this use case. If in
  doubt, default to a non-mutating read and leave snooze expiry to existing TUI/store paths.
- Provide `list_notification_infos(...)` with filters:
  - `limit`
  - `query` over id, sender, notes, files, action, and action_data string values
  - `sender`
  - `unread`
  - `include_dismissed`
  - optional `include_silent`, if current user-facing store behavior needs explicit control
- Provide `resolve_notification_ref(id: str)` for exact lookup.
- Provide `notification_info_to_json(...)` with stable key order:

```json
{
  "id": "uuid",
  "timestamp": "2026-05-01T10:00:00-04:00",
  "age": "2m ago",
  "sender": "axe",
  "priority": true,
  "notes": ["1 error(s) in the last hour"],
  "files": ["~/.sase/axe/error_digests/digest_20260501_100000.txt"],
  "action": "ViewErrorReport",
  "action_data": { "error_report_path": "~/.sase/axe/error_digests/digest_20260501_100000.txt" },
  "read": false,
  "dismissed": false,
  "silent": false,
  "muted": false,
  "snooze_until": null
}
```

Normalize home paths to `~` in output for readability, while preserving enough exact path information for agents to open
attached files. If only one path is emitted, prefer the usable path and document whether it is expanded or `~`-prefixed.

### Tests

- Unit tests with a test-local notification store, following existing patterns in `tests/test_notification_store.py`.
- Cover newest-first ordering, limit, exact id lookup, missing id, sender filter, query filter, unread filter, dismissed
  inclusion/exclusion, priority classification, silent rows, muted/snoozed fields, and axe-style attached digest paths.
- Assert JSON key presence and stable key order.

### Acceptance

- Foundation tests pass without reading the user's real `~/.sase` data.
- No user-facing CLI behavior changes yet.

## Phase 2 - `sase notify list/show` CLI

Expose the catalog through a stable command surface suitable for agent skills, while preserving legacy creation.

### Scope

- Extend `register_notify_parser()` in `src/sase/main/parser_commands.py`.
- Refactor `src/sase/main/notify_handler.py` so:
  - bare `sase notify` remains the existing create behavior
  - `sase notify list` lists notifications
  - `sase notify show --id <id>` shows one notification
  - optional `sase notify create` aliases the legacy create path if useful
- Prefer small CLI implementation helpers under `src/sase/notifications/cli_*.py` if the handler would otherwise become
  crowded.
- `list` options:
  - `-j, --json`
  - `-l, --limit`, default 20
  - `-q, --query`
  - `-s, --sender`
  - `-u, --unread`
  - `-a, --all` to include dismissed notifications
- `show` options:
  - `-i, --id`, required
  - `-f, --format`, choices `markdown` and `json`, default `markdown`
- Pretty list output can be simple and terminal-friendly, but JSON is the stable contract.
- Markdown show output should include id, timestamp/age, sender, priority, notes, files, action, action_data, and state
  flags. It should not inline arbitrary attached file content; the skill can read attached files explicitly.
- Error behavior:
  - unknown id: stderr plus exit code 2
  - malformed arguments: argparse error
  - store read failure: stderr plus exit code 1

### Tests

- Parser/handler tests under `tests/main/` or adjacent notification CLI tests.
- Verify the legacy create path still works exactly enough for existing users and tests.
- Verify `list -j` shape, default limit, filters, pretty empty state, show markdown/json, unknown id, and argparse short
  options.

### Acceptance

- `sase notify list -j -l 5` works from a real workspace.
- `sase notify show --id <id> -f markdown` gives agents enough data to locate attached axe digest files.
- Targeted tests pass.

## Phase 3 - Generated `/sase_notify` Skill

Add the agent-facing skill source and generation coverage.

### Scope

- Add `src/sase/xprompts/skills/sase_notify.md`.
- Front matter:
  - `name: sase_notify`
  - `skill: true`
  - Description should trigger on SASE notifications, notification inbox, axe notification/errors, plan/question
    notifications, and prompts such as "the notification I just got".
- Body should include:
  - Primary command: `sase notify list -j -l 20`
  - Filtering examples for axe, unread, sender, and text search
  - Exact inspection: `sase notify show --id <id>`
  - Guidance for axe digests: read the attached `files` entry or `action_data.error_report_path`
  - Summarization rules: cite notification id/sender/timestamp, distinguish notification notes from attached file
    contents, report no matches plainly, and avoid fabricating notification context
  - Read-only posture: do not dismiss/mute/mark notifications unless the user explicitly asks and a CLI exists for it
- Add an init-skills discovery/rendering test modeled after the existing `sase_chats` test in
  `tests/main/test_init_skills_handler.py`.
- Regenerate live provider skills with:

```bash
sase init-skills --force
```

If chezmoi deployment is enabled, follow the repo's generated-skill workflow and run `chezmoi apply` as needed.

### Tests

- Skill source front matter test asserts `name == "sase_notify"` and `skill is True`.
- Rendered provider skill output contains `sase notify list -j` and `sase notify show --id`.
- Existing init-skills tests still pass.

### Acceptance

- `/sase_notify` is available to all registered providers after regeneration.
- The skill gives enough instructions for an agent to handle an axe digest notification without prior repo knowledge.

## Phase 4 - Documentation, End-to-End Validation, and Handoff

Tie the feature together and verify it behaves like the existing operational skills.

### Scope

- Update `docs/notifications.md` CLI section with the new read commands while preserving the create examples.
- Add a small end-to-end test or integration-style fixture that creates:
  - a regular notification
  - an unread axe digest notification with an attached digest file
  - a dismissed notification Then verifies list/show output and the skill-recommended discovery flow.
- Manually exercise the intended user scenario:

```bash
sase notify list -j -l 20 --sender axe
sase notify show --id <axe_notification_id>
```

- Read the attached digest path and confirm it contains the actionable axe error details.

### Validation

Each implementation phase that changes code should run targeted tests first. The final phase should run:

```bash
just install
just check
```

If `just check` cannot be run, the final handoff must say why and include the targeted tests that did run.

## Final Acceptance Criteria

- Agents can discover recent notifications with `sase notify list -j`.
- Agents can inspect one notification with `sase notify show --id ...`.
- The legacy notification creation path remains backward-compatible.
- `/sase_notify` is generated for supported providers from `src/sase/xprompts/skills/sase_notify.md`.
- The skill points agents to attached files for axe digest details.
- Tests cover the notification read catalog, CLI behavior, generated skill source, and legacy create compatibility.
- `just check` passes after `just install`.
