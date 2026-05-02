---
create_time: 2026-04-28 21:34:03
status: done
prompt: sdd/prompts/202604/telegram_bead_default_buttons_1.md
---
# Plan: Default `/bead` (no args) → Inline-Keyboard Picker of Open Beads

## Goal

When a user sends `/bead` with no argument (currently shows a one-line usage hint), instead reply with a Telegram
message containing an **inline keyboard of buttons — one per open bead**. Tapping a button renders that bead's details
exactly as if the user had typed `/bead <bead_id>`.

## Context

- `/bead <id>` was implemented in the previous plan (`telegram_bead_command.md`) and lives at:
  - Handler: `_handle_bead_command()` in `sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py:998`
  - Formatter: `sase-telegram/src/sase_telegram/bead_format.py:bead_show_to_markdown()`
  - Tests: `tests/test_bead_format.py`, `tests/test_inbound.py::TestBeadCommand`
- The handler currently dispatches the no-arg case to a static usage message at lines 1003–1008. That branch is the one
  we're replacing.
- The plugin already has full inline-keyboard infrastructure — no new client work is needed:
  - `telegram_client.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(...), parse_mode=...)`
    (`src/sase_telegram/telegram_client.py:147`).
  - `telegram_client.answer_callback_query(callback_query_id, text=None)` (line 214).
  - `telegram_client.edit_message_reply_markup(...)` for clearing buttons after a tap (line 223).
  - The polling loop (`sase_tg_inbound.py:1149`) already routes `update.callback_query` events to `_handle_callback()`
    (line 114).
  - `_handle_callback()` already has an "early action-type dispatch" pattern (lines 119–128) for stateless callbacks
    like `kill` and `retry` that don't go through `pending_actions`. Our `bead` callback follows the same pattern.
  - Reference for "list-of-buttons-from-CLI-output": `_show_kill_selection()` at line 637 — same shape (one button per
    row, callback_data per button).
- `sase bead list` (in `sase_102/src/sase/bead/cli.py:234`):
  - Default filter (no `--status`) returns `[OPEN, IN_PROGRESS]` — exactly the "open beads" semantic the user wants.
  - Output format, one line per bead:
    ```
    ○ sase-13 · DELTAS ChangeSpec Field
    ◐ sase-13.5 · Phase 5: Lifecycle Wiring ← sase-13
    ✓ sase-13.1 · Phase 1: Data Model
    ```
    Status icons: `○` open · `◐` in_progress · `✓` closed · `⊘` (other). Optional ` ← <parent_id>` suffix on phases.
  - Empty case prints `No issues found.` to stdout (returncode 0).

## Design

### 1. CLI invocation

Run `sase bead list` (no flags) via `subprocess.run`. The default already excludes closed beads, which is what we want.
Don't pass `--type` — include both plans and phases (user asked for "all open beads"). Same subprocess-vs-library
rationale as the existing handler: layering, decoupling, automatic tracking of CLI changes.

### 2. Output parsing

Add a small pure helper to `bead_format.py`:

```python
@dataclass(frozen=True)
class BeadListEntry:
    icon: str        # "○" | "◐" | "✓" | "⊘"
    bead_id: str     # e.g. "sase-13.1"
    title: str       # e.g. "Phase 1: Data Model"
    parent_id: str | None  # set iff "← <parent_id>" suffix was present

def parse_bead_list_output(raw: str) -> list[BeadListEntry]: ...
```

Parser rules:

- Skip blank lines and the literal `No issues found.` line (return `[]`).
- Split each line as `^(\S+)\s+(\S+)\s+·\s+(.+?)(?:\s+←\s+(\S+))?$`.
- Tolerate unexpected lines by skipping them (don't crash on future format additions).

Unit tests in `test_bead_format.py` cover: typical list, empty output, lines with parent suffix, malformed lines
ignored, unicode icons preserved.

### 3. Callback data scheme

Reuse the existing `callback_data.encode()` (format `action:prefix:choice`, 64-byte limit).

- **Action type:** `"bead"`
- **Prefix slot:** the bead ID itself (e.g. `sase-13.1`). The "prefix" terminology is just historical — for stateless
  callbacks like `kill` it already holds the agent name, so this matches the pattern.
- **Choice slot:** `"show"` (single fixed verb; leaves room for future verbs like `"close"` or `"work"` without a schema
  change).

Encoded: `bead:sase-13.1:show` — well under the 64-byte budget for any realistic bead ID.

Edge case: a bead ID containing `:` would break decoding. The bead system never produces such IDs (they're
`<project>-<n>(.<n>)*`), but defend with an assertion or by skipping any entry whose ID contains `:` (safer — silently
omit rather than crash).

### 4. New "show selection" helper

```python
def _show_bead_selection(chat_id: str) -> None:
    """Render the open-beads picker as an inline keyboard."""
```

Behavior:

1. Run `sase bead list` via subprocess.
2. On non-zero exit → forward stderr in a fenced code block (same pattern as the existing `_handle_bead_command` error
   path).
3. Parse stdout via `parse_bead_list_output`.
4. Empty result → `telegram_client.send_message(chat_id, "No open beads.")`.
5. Build buttons (one bead per row, mirroring `_show_kill_selection`):

   ```python
   InlineKeyboardButton(
       f"{entry.icon} {entry.bead_id}: {entry.title}",
       callback_data=encode("bead", entry.bead_id, "show"),
   )
   ```

   - Truncate the label to ~60 chars (Telegram allows ~64 bytes; long titles get `…`-trimmed).
   - One button per row → readable on mobile, consistent with `_show_kill_selection`.

6. **Pagination cap:** Telegram practically tolerates ~100 buttons per message. Cap at **80 entries** per message; if
   `len(entries) > 80`, send the first 80 and append a final non-button line
   `_(showing first 80 of N — refine with /bead <id>)_`. We don't expect a project to ever have hundreds of open beads
   in practice; if it does, a follow-up plan can add a real Prev/Next paging UI. Keeping this simple now matches the "no
   premature abstraction" guidance.
7. Send via `telegram_client.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")`
   — HTML parse mode chosen to match `_show_kill_selection` and avoid double-escaping bead IDs/titles inside the message
   body. (The button labels themselves are not parsed — Telegram displays them literally.)

### 5. Wiring into the existing handler

`_handle_bead_command()` becomes:

```python
def _handle_bead_command(args: str) -> None:
    chat_id = credentials.get_chat_id()
    parts = args.strip().split()
    if not parts:
        _show_bead_selection(chat_id)
        return
    bead_id = parts[0]
    # ...existing show flow unchanged...
```

The current usage-hint message goes away. (Users who want a hint can read `/help` from `_SLASH_COMMANDS`.)

### 6. Callback dispatch

Extend the early action-type dispatch in `_handle_callback()` (`sase_tg_inbound.py:119`):

```python
if cb.action_type == "bead":
    _handle_bead_callback(callback_query, cb.notif_id_prefix)  # bead_id lives in prefix slot
    return
```

Where:

```python
def _handle_bead_callback(callback_query: Any, bead_id: str) -> None:
    telegram_client.answer_callback_query(callback_query.id, f"Loading {bead_id}…")
    _handle_bead_command(bead_id)
```

Design notes:

- We **don't** edit/remove the picker keyboard after a tap (unlike kill/retry, which are one-shot destructive actions).
  The picker stays intact so the user can tap multiple beads in succession — this is a navigation UI, not a decision UI.
- We **don't** route through `pending_actions` — the bead ID is fully self-contained in the callback data, so there's no
  per-message state to track. This matches the kill/retry pattern.
- Reusing `_handle_bead_command(bead_id)` guarantees the button-tap path renders identically to the slash-command path.
  Single source of truth for bead rendering.

### 7. No registry changes

`_SLASH_COMMANDS` already advertises `/bead` (added in the previous plan). No change needed — we're only changing the
no-arg behavior, not adding a new command.

## Files Touched

- **EDIT** `sase-telegram/src/sase_telegram/bead_format.py` — add `BeadListEntry` dataclass and
  `parse_bead_list_output()`.
- **EDIT** `sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py`:
  - Add `_show_bead_selection()`.
  - Add `_handle_bead_callback()`.
  - Modify `_handle_bead_command()` to call `_show_bead_selection()` on empty args.
  - Add `bead` branch to `_handle_callback()` early dispatch (alongside `kill`/`retry`).
- **EDIT** `sase-telegram/tests/test_bead_format.py` — `parse_bead_list_output` unit tests.
- **EDIT** `sase-telegram/tests/test_inbound.py` — extend `TestBeadCommand` (or new `TestBeadSelection` /
  `TestBeadCallback` classes) with:
  - No-arg path: subprocess returns 3 beads → `send_message` called with `reply_markup` containing 3 buttons whose
    `callback_data` round-trips through `decode()` to `("bead", "<id>", "show")`.
  - No-arg empty path: subprocess returns `No issues found.` → `send_message(chat_id, "No open beads.")`.
  - No-arg error path: subprocess returns non-zero → stderr in code block.
  - Callback path: `_handle_callback` invoked with `data="bead:sase-13:show"` → `answer_callback_query` called and
    `subprocess.run` invoked with `["sase", "bead", "show", "sase-13"]`.

No changes needed in `sase_102` — `sase bead list` already does what we need.

## Verification

1. `cd ~/projects/github/sase-org/sase-telegram && just check` — lint + type-check + tests pass.
2. Manual smoke test from Telegram:
   - Send `/bead` → expect a message titled e.g. "Open beads (N):" followed by a column of one button per bead.
   - Tap any button → expect the same bead-detail card that `/bead <id>` would produce, and the picker remains intact
     for further taps.
   - Run `sase bead update <id> --status closed` for a bead, then `/bead` again → that bead no longer appears.
   - Test the empty-list case in a project with no open beads → expect `"No open beads."`.
3. (Optional) Stress: create 90 open beads in a scratch project → expect the first 80 to render with the truncation
   footer.

## Open Questions / Deferred

- **Paging UI** (Prev/Next buttons): deferred until someone actually has >80 open beads. Current 80-cap fallback is a
  graceful degradation, not a silent truncation.
- **Filtering picker by type** (e.g. only plans): out of scope; the user said "all open beads". Could add `/bead plans`
  / `/bead phases` later.
- **Sort order**: parser preserves CLI order (created_at ASC, per `db.list_issues`). Good enough; no need to re-sort.
