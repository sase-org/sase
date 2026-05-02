---
create_time: 2026-04-28 20:57:19
status: done
prompt: sdd/prompts/202604/telegram_bead_command.md
---
# Plan: `/bead` Telegram Slash Command

## Goal

Add a new `/bead <bead_id>` slash command to the `sase-telegram` plugin that:

1. Accepts a bead ID argument from the user.
2. Runs `sase bead show <bead_id>` as a subprocess.
3. Transforms the plain-text CLI output into well-formatted Markdown.
4. Sends the result back as a Telegram message (using the existing MarkdownV2 pipeline).

## Context

- The plugin lives at `/home/bryan/projects/github/sase-org/sase-telegram`.
- All slash command logic is centralized in `src/sase_telegram/scripts/sase_tg_inbound.py`:
  - Registry tuple `_SLASH_COMMANDS` (~line 1038).
  - Dispatcher `_handle_command()` (~line 592).
  - Existing handlers: `_handle_kill_command`, `_handle_list_command`, `_handle_listx_command`,
    `_handle_resume_command`, `_handle_xprompts_command`.
- Outbound messaging goes through `telegram_client.send_message(chat_id, text, parse_mode=...)`, which auto-splits long
  messages, retries with backoff, and falls back to plain text if MarkdownV2 fails.
- A markdown→MarkdownV2 converter already exists: `formatting.markdown_to_telegram_v2()` (handles headers, bold/italic,
  code blocks, lists, links, escaping).

### Sample `sase bead show` output (current format)

For an epic / plan bead:

```
○ sase-13 · DELTAS ChangeSpec Field   [OPEN]
Type: plan · Owner: bryanbugyi34@gmail.com

CHILDREN
  ✓ sase-13.1: Phase 1: Data Model, Parsing, Serialization
  ◐ sase-13.3: Phase 3: VCS Computation

PLAN
  ../sase/plans/202604/deltas_field.md
```

For a leaf phase bead:

```
✓ sase-13.1 · Phase 1: Data Model, Parsing, Serialization   [CLOSED]
Type: phase · Owner: bryanbugyi34@gmail.com
Assignee: sase-13.1

PARENT
  ↑ sase-13 · DELTAS ChangeSpec Field   [OPEN]

BLOCKS
  ← ✓ sase-13.2: Phase 2: Atomic Update Helper   [CLOSED]

DESCRIPTION
  Round-trip a ChangeSpec with a DELTAS section ...

NOTES
  COMMIT: 616a50ea
```

Sections that may appear (from `src/sase/bead/cli.py` `handle_bead_show`): header line, `Type:`/`Owner:`/`Assignee:`
metadata, `PARENT`, `CHILDREN`, `DEPENDS ON`, `BLOCKS`, `DESCRIPTION`, `NOTES`, `PLAN`. Non-trivial whitespace and the
leading status icons (`○ ◐ ✓ ⊘`) are part of the output.

## Design

### 1. Subprocess vs library call

Run `sase bead show <id>` via `subprocess.run([...], capture_output=True, text=True)`. Reasons:

- Matches the user's explicit request ("runs `sase bead show <bead_id>`").
- Avoids coupling the telegram plugin to internal `sase.bead` APIs, which would be a layering violation (plugins consume
  sase via its public CLI/plugin interfaces).
- Behavior automatically tracks any future changes to the CLI output.

Tradeoff: we have to _parse_ text output rather than reading structured data. Mitigated by the fact that the format is
small, stable, and section-based.

### 2. Argument parsing

`/bead <bead_id>` — single required positional argument. If missing or extra whitespace only:

> Usage: `/bead <bead_id>` — example: `/bead sase-13.1`

If the subprocess returns non-zero (`Error: issue not found: ...`), forward the stderr text wrapped in a code block.

### 3. Text → Markdown transformation

Add a new pure function in the plugin (likely a new helper module `src/sase_telegram/bead_format.py`, kept small and
unit-testable):

```python
def bead_show_to_markdown(raw: str) -> str: ...
```

Transformation rules (line-by-line, stateful — track current section):

| Input pattern                                   | Markdown output                                              |
| ----------------------------------------------- | ------------------------------------------------------------ |
| Header line: `<icon> <id> · <title>   [STATUS]` | `# <icon> <id> — <title>` then a line `**Status:** <STATUS>` |
| `Type: <t> · Owner: <o>`                        | `**Type:** <t>  •  **Owner:** <o>`                           |
| `Assignee: <a>`                                 | `**Assignee:** <a>`                                          |
| Blank line                                      | preserved                                                    |
| ALL-CAPS section header (e.g. `CHILDREN`)       | `## Children` (title-cased; `DEPENDS ON` → `Depends On`)     |
| Indented child/dep/blocks line                  | `- <icon> \`<id>\` — <title> _(STATUS)_`                     |
| `PARENT` body line                              | `- ↑ \`<id>\` — <title> _(STATUS)_`                          |
| `DESCRIPTION` body                              | paragraph (re-flow indentation, escape MD specials)          |
| `NOTES` body                                    | code-block fenced (preserves `COMMIT: <sha>`, etc.)          |
| `PLAN` body (a path)                            | inline code: `` `<path>` ``                                  |

Then pass the result through `formatting.markdown_to_telegram_v2()` for final escaping.

Edge cases to handle in the transformer:

- Bead with none of the optional sections (header + Type/Owner only).
- Very long DESCRIPTION (rely on `markdown_to_telegram_v2`'s expandable blockquote logic — already handled downstream).
- Unicode status icons must pass through unchanged.
- Preserve `Type: plan` vs `Type: phase` etc. without re-interpreting.

### 4. New handler

In `sase_tg_inbound.py`:

````python
def _handle_bead_command(args: str) -> None:
    """Handle /bead <id> — render bead details as a Telegram message."""
    chat_id = credentials.get_chat_id()
    bead_id = args.strip().split()[0] if args.strip() else ""
    if not bead_id:
        telegram_client.send_message(
            chat_id,
            "Usage: /bead <bead_id> — example: /bead sase-13.1",
        )
        return

    result = subprocess.run(
        ["sase", "bead", "show", bead_id],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        telegram_client.send_message(
            chat_id,
            f"```\n{result.stderr.strip() or 'sase bead show failed'}\n```",
            parse_mode="MarkdownV2",
        )
        return

    md = bead_show_to_markdown(result.stdout)
    telegram_client.send_message(
        chat_id,
        markdown_to_telegram_v2(md),
        parse_mode="MarkdownV2",
    )
````

### 5. Registration

Two small edits in `sase_tg_inbound.py`:

1. Append to `_SLASH_COMMANDS`:
   ```python
   ("bead", "Show a bead's details as Markdown"),
   ```
2. Add to `_handle_command()`:
   ```python
   elif command == "bead":
       _handle_bead_command(args)
   ```

The hourly `_register_commands_if_needed()` call will publish the command to Telegram automatically.

### 6. Tests

Add to `sase-telegram/tests/`:

- `test_bead_format.py` — pure unit tests on `bead_show_to_markdown` covering:
  - Plan bead with CHILDREN + PLAN.
  - Phase bead with PARENT + BLOCKS + DESCRIPTION + NOTES.
  - Empty / minimal bead.
  - Unknown sections gracefully passed through.
- Extend `tests/test_inbound.py` with a `TestBeadCommand` class that:
  - Patches `subprocess.run` to return a fixed stdout.
  - Patches `telegram_client.send_message` and asserts it's called with `parse_mode="MarkdownV2"` and the expected
    markdown body.
  - Covers the missing-arg path (usage message).
  - Covers the subprocess-error path (forwards stderr).

## Files Touched

- **NEW** `sase-telegram/src/sase_telegram/bead_format.py` — `bead_show_to_markdown()` transformer.
- **EDIT** `sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py` — add command to registry, dispatcher case, and
  handler function.
- **NEW** `sase-telegram/tests/test_bead_format.py` — transformer unit tests.
- **EDIT** `sase-telegram/tests/test_inbound.py` — handler integration tests.

No changes are needed in the main `sase_103` repo: `sase bead show` already does what we need, and we're only invoking
it as a subprocess.

## Verification

1. `cd ~/projects/github/sase-org/sase-telegram && just check` — lint + type-check + tests pass.
2. Manual smoke test:
   - Send `/bead sase-13` from Telegram → expect a nicely formatted card with header, children list, plan link.
   - Send `/bead sase-13.1` → expect parent, blocks, description, notes sections.
   - Send `/bead bogus-id` → expect error code-block.
   - Send `/bead` (no args) → expect usage message.
3. Confirm the new command appears in Telegram's `/` autocomplete after the next `_register_commands_if_needed()` cycle
   (or force by deleting the cached registration timestamp file).

## Open Questions

- None blocking. If the bead show output format changes substantially in the future, only `bead_show_to_markdown` needs
  updating; the section-based transformer is intentionally tolerant of unknown headers.
