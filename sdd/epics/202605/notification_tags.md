---
create_time: 2026-05-23 20:09:25
status: done
prompt: sdd/prompts/202605/notification_tags.md
bead_id: sase-43
tier: epic
---
# Plan: Notification Tags + TUI Tag Tabs

## Goal

Add first-class notification tags so senders can attach labels such as `foobar`, and make the ACE notification modal
split unread notifications into polished tag tabs. The first concrete use case is tagging successful user-agent
completion notifications with `done`, while preserving the existing unread-agent acknowledgement behavior that
auto-dismisses those completion notifications when the matching Agents-tab row moves from unread to read.

## Current Shape

- Notifications are persisted as JSONL at `~/.sase/notifications/notifications.jsonl`.
- Python uses `src/sase/notifications/models.py::Notification`; Rust core mirrors it as
  `crates/sase_core/src/notifications/wire.rs::NotificationWire`.
- Storage, counts, and state updates are Rust-backed through `src/sase/core/notification_store_facade.py`.
- The notification modal is section-based, not tab-based:
  - `NotificationModal` owns `self._notifications`.
  - `notification_modal_options.py` groups rows into `PRIORITY`, `ERRORS`, `INBOX`, and `MUTED`.
  - Rows are sorted newest-first within each section.
- Agents-tab unread state is projected from active `user-agent` completion notifications. The relevant matching logic is
  in `src/sase/ace/tui/actions/agents/_notification_utils.py`, and the dismissal path is already bulk/Rust-backed.

## Product Design

Use tags as a filter layer above the existing severity sections.

- The modal always has an `All` tab.
- Every tag present among currently displayed unread notifications gets its own tab.
- `done` is pinned immediately after `All` when present because it is the first product use case.
- Other tags sort alphabetically for stable muscle memory.
- A notification with multiple tags appears in `All` and in each matching tag tab, but never duplicates inside one tab.
- Untagged notifications appear in `All` only. Do not add an `Untagged` tab in this iteration; that would add clutter
  without serving the requested workflow.
- Inside each tag tab, keep the current `PRIORITY -> ERRORS -> INBOX -> MUTED` sections and newest-first ordering.
- The tag strip should be compact and scan-friendly: a single line above the notification list, active tab in bold
  accent, inactive tabs dim, count beside each label, and no nested cards.
- Keyboard support: `[` / `]` switch tag tabs; mouse click on a tab also switches. Switching tabs clears modal-local
  marks so hidden rows are never bulk-dismissed by accident.

## Tag Semantics

- Add `tags: list[str]` / `Vec<String>` as stored metadata.
- Legacy rows missing `tags` load as `[]`.
- Normalize sender-provided tags at creation boundaries:
  - trim whitespace;
  - drop empty strings;
  - lowercase for stable tab identity;
  - dedupe while preserving sender order.
- Do not reject older or hand-written rows with unusual tag strings while reading. Normalize on creation, tolerate on
  load.
- Keep tag classification orthogonal to priority/error/muted/read/silent state. Tags do not affect indicator counts,
  toasts, snooze, mute, or auto-dismiss matching.

## Phase 1: Core Schema and Round Trip

Owner: one agent instance working in both `sase_10` and sibling `sase-core_10`.

Implement the storage contract first, without changing TUI behavior.

Files and areas:

- `../sase-core/crates/sase_core/src/notifications/wire.rs`
  - Add `#[serde(default)] pub tags: Vec<String>` to `NotificationWire`.
- `../sase-core/crates/sase_core/src/notifications/mobile.rs`
  - Include tags in mobile notification cards if the card contract is intended to expose notification metadata.
  - Update mobile contract snapshots only if that public wire shape changes.
- `../sase-core/crates/sase_core/tests/notification_store_parity.rs`
  - Update helper constructors and JSON shape assertions.
  - Add a legacy-row test proving missing `tags` loads as `[]`.
- `src/sase/notifications/models.py`
  - Add `tags: list[str] = field(default_factory=list)`.
  - Add a small `normalize_notification_tags(...)` helper.
- `src/sase/core/notification_store_wire.py`
  - Serialize/rehydrate the new field.
- Notification fixtures/generators under `tests/fixtures/notifications/` as needed.

Acceptance:

- Existing notification rows with no `tags` still load.
- A row with tags survives append, load, rewrite, Rust facade, and PyO3 binding round trips.
- Core JSON shape tests and Python notification model tests are updated.

Suggested verification:

```bash
cd ../sase-core && cargo test -p sase_core notification_store_parity
pytest tests/test_notification_models.py tests/notification_store/test_models.py tests/notification_store/test_storage.py tests/test_core_facade/test_notification_store.py
```

## Phase 2: Sender API, CLI, Catalog, and `done`

Owner: one agent instance in `sase_10`, depending on Phase 1.

Make tags usable by senders and add the first production tag.

Files and areas:

- `src/sase/notifications/senders.py`
  - Add optional `tags: list[str] | None = None` to `notify_workflow_complete(...)`.
  - Pass normalized tags into the `Notification`.
  - Consider adding the same optional parameter only to sender helpers that have immediate callers needing custom tags;
    the model and CLI are already the general-purpose escape hatch.
- `src/sase/axe/run_agent_runner_finalize.py`
  - In `send_completion_notification(...)`, pass `tags=["done"]` only for successful user-agent completion notifications
    that use the `JumpToAgent` action.
  - Do not tag failures with `done`; those should remain error reports.
  - Keep `silent=agent_hidden` unchanged. Hidden successful completions may carry `done` in storage while remaining
    hidden from the TUI.
- `src/sase/main/parser_commands.py` and `src/sase/main/notify_handler.py`
  - Support JSON `tags` on `sase notify` / `sase notify create`.
  - Add repeatable `--tag/-t` for CLI-created notifications; CLI tags override or extend JSON tags consistently.
- `src/sase/notifications/catalog.py`, `cli_list.py`, and `cli_show.py`
  - Add `tags` to `NotificationInfo` and JSON output.
  - Let `-q/--query` match tags.
  - Add optional `sase notify list --tag <tag>` if it stays small; otherwise leave filtering to `-q` and document JSON
    consumers.
- `docs/notifications.md` and `docs/configuration.md`
  - Document the `tags` field, create examples, list/show output, and the `done` convention.

Acceptance:

- External senders can create a tagged notification through JSON or CLI flags.
- `sase notify list -j` and `sase notify show -f json` expose tags.
- Successful completion notification tests assert `tags == ["done"]`.
- Failure notification tests assert `done` is absent.
- Auto-dismiss tests continue passing without changing their matching rules.

Suggested verification:

```bash
pytest tests/notification_store/test_senders.py tests/test_run_agent_runner_notifications.py tests/test_notification_catalog.py
```

## Phase 3: TUI Notification Tag Tabs

Owner: one agent instance in `sase_10`, depending on Phases 1 and 2.

Add the tag-tab UI while preserving existing modal actions.

Files and areas:

- `src/sase/ace/tui/modals/notification_modal.py`
  - Track active tag state, likely `None` for `All` and `str` for a tag.
  - Compose a tag strip above `#notification-list` when there is at least one tag tab.
  - Add bindings for previous/next tag tab.
- New or local helper in `src/sase/ace/tui/modals/`
  - Build tag tab data: `All`, pinned `done`, then remaining sorted tags.
  - Return counts from the current unread modal dataset.
  - Provide stable click hit ranges if implemented as a `Static`, following the existing top-level `TabBar` pattern.
- `src/sase/ace/tui/modals/notification_modal_options.py`
  - Filter rows by active tag before section grouping.
  - Keep original notification indexes as option ids so selection, detail pane, dismiss, mute, snooze, and jump mode
    keep using the existing action plumbing.
  - Show compact tag badges in row labels, especially in `All`, without allowing long tag strings to crowd out notes.
- `src/sase/ace/tui/modals/notification_modal_actions.py`
  - Clear marks on tag switch.
  - Ensure dismiss/mute/snooze rebuilds preserve the active tag when possible, and fall back to the nearest remaining
    tab when a tab becomes empty.
  - Decide explicitly whether `R` remains global. Recommendation: keep global in this phase to preserve existing
    semantics and avoid a hidden behavior change.
- `src/sase/ace/tui/styles.tcss`
  - Add stable one-line styling for the tag strip.
  - Keep the modal dense and work-focused: no nested cards, no decorative gradients, no oversized typography.

Acceptance:

- Untagged notifications still render exactly in `All`.
- Tagged notifications render in `All` and their tag tab.
- `done` tab appears when successful completion notifications are present.
- Section headers/counts reflect only the active tag tab.
- Jump hints and visual order operate on visible rows only.
- Switching tabs does not touch disk or provider state.

Suggested verification:

```bash
pytest tests/test_notification_modal_sections.py tests/test_notification_modal_actions.py tests/test_notification_modal_jump.py tests/ace/tui/modals/test_notification_image_files.py
```

## Phase 4: End-to-End Polish and Regression Pass

Owner: one final integration agent after Phases 1-3 land.

Tie the feature together, update docs, and harden behavior under real workflows.

Checklist:

- Add or update end-to-end tests that create two successful completion notifications tagged `done`, open the modal data,
  and verify the `done` tab dataset matches the notifications that project unread Agents-tab rows.
- Confirm selecting or acknowledging a done agent still dismisses the matching completion notification and removes it
  from both `All` and `done` modal views after refresh.
- Confirm failed-agent `ViewErrorReport` notifications are not in `done` and still live under `ERRORS`.
- Add a small visual snapshot or screenshot-oriented test if the existing visual harness can mount `NotificationModal`
  cheaply. If not, keep focused option-rendering tests and manually inspect with a local notification corpus.
- Update docs to describe the tab strip UX and `[` / `]` keybindings.
- Run the repo-required checks.

Suggested verification:

```bash
just install
just check
cd ../sase-core && cargo fmt --all -- --check && cargo test --workspace
```

## Risks and Guardrails

- **Rust/Python schema drift**: Phase 1 must land first and should include round-trip tests on both sides.
- **Hidden bulk action surprise**: clearing marks on tag switch prevents dismissing rows that are no longer visible.
- **Performance**: tab switching should only regroup the in-memory modal list. Do not read the JSONL store on tab
  switch.
- **Completion semantics**: `done` is a display/navigation tag, not the source of truth for auto-dismiss. Keep existing
  agent-key matching so old untagged completion notifications still dismiss correctly.
- **Pagination**: the modal currently reads a bounded unread page. Tag tabs in this plan reflect the loaded modal
  dataset. If a future daemon-backed provider pages notification rows, add tag facets/counts to the provider contract
  before making tabs global across unloaded rows.
