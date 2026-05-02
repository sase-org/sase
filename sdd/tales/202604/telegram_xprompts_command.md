---
create_time: 2026-04-24 09:13:48
status: done
prompt: sdd/prompts/202604/telegram_xprompts_command.md
---
# Telegram `/xprompts` Command — sase-telegram Wiring

## 1. Context

The library side of this feature already shipped in `sase_101` (commit `32e746ab`, plan
`plans/202604/telegram_xprompts_pdf.md`, status: done). That plan explicitly deferred step 7 — the matching change in
the external `sase-telegram` repo — to "a separate PR in sase-telegram" that was never made.

Consequence visible to the user: `/xprompts` does not appear in Telegram's hamburger menu, because:

1. The command is not in `_SLASH_COMMANDS` in `sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py:910`, so it is
   never sent to Telegram via `set_my_commands`.
2. There is no dispatch branch for it in `_handle_command` (same file, lines 569-583), so even typing `/xprompts`
   manually would silently do nothing (the comment "Unknown commands … are silently ignored" confirms).

This plan captures the sase-telegram-side work to close the gap.

## 2. Goal

After this change:

- `/xprompts` appears in the Telegram menu button alongside `/kill`, `/list`, `/listx`, `/resume`.
- Sending `/xprompts` (from the menu or manually) causes the bot to build the xprompts PDF catalog (via the already-
  shipped `sase.xprompt.catalog.build_xprompts_catalog`) and reply with one message: the PDF as an attachment with a
  short stats caption.
- Failure modes (no PDF engine, no xprompts found, anything else) degrade gracefully to a plain-text message, matching
  the behaviour specified in §2.3 / §7.3 of the original plan.

## 3. Repo and Files

All edits land in the external repo at `/home/bryan/projects/github/sase-org/sase-telegram/`. No changes to `sase_101`.

- `src/sase_telegram/scripts/sase_tg_inbound.py` — command registration, dispatch, new handler function.
- `src/sase_telegram/telegram_client.py` — small extension to `send_document` to accept `parse_mode` (needed for the
  HTML caption, see §6).
- `tests/test_inbound.py` — one new test asserting the dispatch path.

## 4. Design

### 4.1 Command registration (`_SLASH_COMMANDS`)

Append one tuple to the existing list at `sase_tg_inbound.py:910`:

```python
_SLASH_COMMANDS = [
    ("kill", "Terminate a running agent"),
    ("list", "Show all running agents"),
    ("listx", "Show done/undismissed agents"),
    ("resume", "Copy resume text for an agent"),
    ("xprompts", "Export the xprompts catalog as a PDF"),
]
```

`_register_commands_if_needed()` (already in place, lines 918-941) will push this to Telegram via `set_my_commands` on
the next eligible tick.

### 4.2 Dispatch (`_handle_command`)

Add one branch in `_handle_command` (sase_tg_inbound.py:569). Match the existing style exactly:

```python
elif command == "xprompts":
    _handle_xprompts_command()
```

No `args` are used — the command takes no arguments in v1.

### 4.3 New handler `_handle_xprompts_command`

Signature (matches the no-arg style of `_handle_list_command` / `_handle_resume_command`; `chat_id` is pulled from
`credentials.get_chat_id()` internally — the same convention those handlers already use):

```python
def _handle_xprompts_command() -> None:
    """Handle /xprompts — build and send the xprompts PDF catalog."""
```

Behaviour (in order):

1. `chat_id = credentials.get_chat_id()`.
2. Send an ack: `telegram_client.send_message(chat_id, "📚 Building your xprompts catalog…")`. This is important — PDF
   generation can take several seconds (wkhtmltopdf), and without the ack the user will think the bot ignored them.
3. Import and call: `from sase.xprompt.catalog import build_xprompts_catalog, PdfEngineUnavailable, NoXpromptsFound`
   then `artifact = build_xprompts_catalog()` (default `output_dir=None` → tempdir, which is fine for Telegram since we
   only need the file long enough to upload it).
4. Build an HTML caption from `artifact.stats` via a small local helper `_format_xprompts_caption(stats) -> str` (see
   §4.4). Ensure the result stays within Telegram's 1024-char caption cap by truncating the "Top tags" line if
   necessary.
5. `telegram_client.send_document(chat_id, str(artifact.pdf_path), caption=caption, parse_mode="HTML")`.

Error branches (each logs via the existing `log` and sends a short user-visible plain-text reply):

| Branch                  | User-visible message                                                                                    |
| ----------------------- | ------------------------------------------------------------------------------------------------------- |
| `PdfEngineUnavailable`  | `"PDF engine (wkhtmltopdf/pandoc) not installed on the bot host — cannot render the catalog PDF."`      |
| `NoXpromptsFound`       | `"No xprompts found — unexpected, file a bug."`                                                         |
| `Exception` (catch-all) | `"Failed to build xprompts catalog: {type(exc).__name__}. See bot logs for details."` + `log.exception` |

The catch-all matches the "full traceback goes to logs like existing handlers" guidance in the original plan (§2.3).

### 4.4 Caption helper

Local helper inside `sase_tg_inbound.py` (or inline — depends on whether reuse emerges; inline is fine for v1):

```python
def _format_xprompts_caption(stats: CatalogStats) -> str:
    ...
```

Output format (HTML; matches §2.2 of the original plan verbatim, adapted to real field names on `CatalogStats`):

```
📚 <b>xprompts Catalog</b>

<b>{total}</b> xprompts across <b>{len(by_project)}</b> projects

• Built-in:     {by_source.get("built-in", 0)}
• Project:      {by_source.get("project", 0)}
• Config:       {by_source.get("config", 0)}
• Plugin:       {by_source.get("plugin", 0)}
• Memory (auto): {by_source.get("memory", 0)}

Top tags: {top_tags_html}

Generated {generated_at.date().isoformat()}
```

Where `top_tags_html` is the top 3 entries of `stats.by_tag` rendered as `<code>#tag</code> · <code>#tag</code> · …`.
Skip the "Top tags" line entirely if `stats.by_tag` is empty.

Guard the total length: if > 1000 chars (leaving a 24-char buffer under Telegram's 1024 cap), drop the "Top tags" line.
An assertion or runtime check is fine — this is a soft bound, not a hard invariant.

### 4.5 `send_document` wrapper extension

`telegram_client.send_document` today accepts `(chat_id, document, caption)` with no `parse_mode` — but `send_message`
accepts `parse_mode`. To render the HTML caption as bold/code, extend the signature:

```python
def send_document(
    chat_id: str,
    document: str | bytes,
    caption: str | None = None,
    parse_mode: str | None = None,
) -> Message:
    bot = _get_bot()
    return _run_async(
        bot.send_document(
            chat_id=chat_id, document=document, caption=caption, parse_mode=parse_mode
        )
    )
```

python-telegram-bot's `Bot.send_document` already accepts `parse_mode`, so this is a pure passthrough — no protocol
risk. Alternative (rejected): strip the HTML in the caption and use plain text. Rejected because the rest of the bot
consistently uses HTML for stats messages (`_handle_list_command` / `_handle_listx_command`), and consistency matters
more than shaving one keyword argument.

## 5. Testing

Add one test to `tests/test_inbound.py` following the existing mock-heavy pattern (the file uses `MagicMock`/`patch`
throughout — e.g. `TestProcessTextMessage` class). A reasonable shape:

```python
class TestXpromptsCommand:
    def test_xprompts_command_builds_and_sends_pdf(self, tmp_path: Path) -> None:
        from sase.xprompt.catalog import CatalogArtifact, CatalogStats
        pdf_path = tmp_path / "catalog.pdf"
        pdf_path.write_bytes(b"%PDF-fake")
        fake_artifact = CatalogArtifact(
            pdf_path=pdf_path,
            stats=CatalogStats(total=5, by_source={"built-in": 5}, by_project={},
                               by_tag={}, with_description=5, with_inputs=0,
                               skills=0, generated_at=...),
        )
        with patch("sase_telegram.scripts.sase_tg_inbound.build_xprompts_catalog",
                   return_value=fake_artifact) as build_mock, \
             patch("sase_telegram.scripts.sase_tg_inbound.telegram_client") as tc_mock, \
             patch("sase_telegram.scripts.sase_tg_inbound.credentials") as cred_mock:
            cred_mock.get_chat_id.return_value = "12345"
            from sase_telegram.scripts.sase_tg_inbound import _handle_xprompts_command
            _handle_xprompts_command()
        build_mock.assert_called_once()
        assert tc_mock.send_message.call_count == 1  # the ack
        tc_mock.send_document.assert_called_once()
        args, kwargs = tc_mock.send_document.call_args
        assert kwargs.get("parse_mode") == "HTML"
        assert "xprompts Catalog" in kwargs.get("caption", "")
```

Optional: a second test for the `PdfEngineUnavailable` branch (assert `send_message` is called twice — ack + error — and
`send_document` is never called). Skip the `NoXpromptsFound` branch for v1; covered by the same code path.

Run in the sase-telegram repo:

```bash
just install
just check    # lint (ruff + mypy) + test
```

Note (per `memory/short/gotchas.md`): `just check` in `sase_101` does **not** cover this work. The sase-telegram repo
has its own venv and its own checks.

## 6. Deployment

After merging the sase-telegram change and redeploying the bot:

1. Delete the command-registration cache so the new `_SLASH_COMMANDS` list is pushed to Telegram on the next tick
   instead of waiting up to an hour:
   ```bash
   rm -f ~/.sase/telegram/commands_registered_ts
   ```
2. Wait for the next inbound chop tick (≤ 5 s). The hamburger menu should refresh in the Telegram client within a few
   seconds (Telegram clients cache the command list briefly; force-closing and reopening the chat guarantees a fresh
   fetch if the client is being stubborn).
3. Smoke test: tap `/xprompts` from the menu. Expect ack message, then PDF with caption within ~5 s.

## 7. Scope and Non-Goals

- No flags (`--include-builtins-only`, project filter, etc.) — matches the original plan's §7.6 minimalism.
- No inline-keyboard variant of `/xprompts` — just fire-and-forget PDF generation.
- No caching of the generated PDF across invocations. Each `/xprompts` regenerates; wkhtmltopdf is fast enough that
  caching isn't worth the complexity for v1.
- No change to `sase_101`. The library side is already in place and shipped.

## 8. Open Questions

1. **HTML caption vs. plain text.** Plan assumes we extend `send_document` to accept `parse_mode`. If there's a reason
   not to touch that wrapper (e.g. upcoming refactor, stylistic preference), a plain-text caption is a trivial swap —
   just drop the `<b>`/`<code>` tags and the `parse_mode` argument.
2. **Telegram's menu cache on the client side.** We've controlled the server-side cache via `commands_registered_ts`.
   Client-side, Telegram apps occasionally cache the menu for a few minutes. If the user sees the command in `/help` but
   not in the hamburger menu right after deploy, that's a client cache issue, not a bug — force-close/reopen the chat.
