# Migrating Telegram Dot Commands to Slash Commands

## Current State

We have three dot commands in `sase-telegram` (defined in `sase_tg_inbound.py`):

| Command        | Purpose                                |
| -------------- | -------------------------------------- |
| `.kill <name>` | Terminate a running agent by name      |
| `.list`        | Show all currently running agents      |
| `.listx`       | Show done but not yet dismissed agents |

These are parsed manually in `_handle_dot_command()` — text starting with `.` is split on whitespace and dispatched via
`if`/`elif`. There is no command registry, no help system, and unknown commands are silently ignored.

## What Telegram Slash Commands Provide

Telegram's native bot command system (`/command`) provides:

- **Auto-completion menu**: When users type `/` in a bot chat, a popup lists all registered commands with descriptions.
  A menu button (hamburger icon) next to the input field also opens this list.
- **Per-scope command sets**: Different menus for private chats vs groups vs admins via `BotCommandScope`.
- **Up to 100 commands** per scope, each with a description (1-256 chars).

### Registration

Commands are registered via the `setMyCommands` Bot API method (or BotFather for static setup). In python-telegram-bot:

```python
async def post_init(application: Application) -> None:
    await application.bot.set_my_commands([
        BotCommand("kill", "Terminate a running agent"),
        BotCommand("list", "Show running agents"),
        BotCommand("listx", "Show done/undismissed agents"),
    ])
```

Registration is separate from handler setup — the library does not auto-register commands from `CommandHandler`
instances.

### Handling

```python
app.add_handler(CommandHandler("kill", handle_kill))
app.add_handler(CommandHandler("list", handle_list))
```

Arguments are available via `context.args` (whitespace-split list of everything after the command name).

## Key Constraints and Gotchas

### Command names

- Only lowercase letters, digits, and underscores (`[a-z0-9_]`). No hyphens.
- 1-32 characters.
- Our current commands (`kill`, `list`, `listx`) are all valid as-is.

### Arguments and the menu

- **Selecting a command from the auto-complete menu sends it immediately with no arguments.** Users cannot append
  arguments from the menu.
- To type arguments, users must type the command manually: `/kill agent_name`.
- Desktop clients: pressing Tab after selecting from menu lets you append text before sending.
- Mobile: long-tap a command to append text instead of sending immediately.
- This is relevant for `/kill` which requires an argument. The menu will send `/kill` with no args, which will need to
  prompt for the agent name.

### No sub-commands

- Telegram has no native sub-command support. No `/parent subcommand` syntax.
- Workaround: use flat names like `/kill`, `/list_running`, `/list_done`.
- Alternative: use inline keyboards for drill-down flows.

### Our inbound architecture

- We don't use python-telegram-bot's `Application`/`Updater` framework. We poll manually with `get_updates()` and
  dispatch in our own `_handle_text_message()`.
- This means we won't use `CommandHandler` — we'll parse `/command` text the same way we parse `.command` today.
- We **will** still need to call `setMyCommands` to register commands for the auto-complete menu, but this is a one-time
  API call (can be done on startup or as a setup step).

## Migration Plan

### Phase 1: Add slash command support alongside dot commands

Minimal changes to `sase_tg_inbound.py`:

1. **Stop ignoring `/` messages.** Currently lines 526-528 silently ignore all `/` prefixed messages. Change this to
   dispatch to a command handler, falling through to "ignore" only for unknown commands like `/start`.

2. **Unify parsing.** Extract command dispatch into a shared function that handles both `.kill` and `/kill`:

   ```python
   def _handle_command(text: str) -> bool:
       """Handle a dot or slash command. Returns True if handled."""
       # Strip the prefix (. or /)
       stripped = text.lstrip(".").lstrip("/")
       parts = stripped.split(None, 1)
       command = parts[0].lower()
       args = parts[1] if len(parts) > 1 else ""

       if command == "kill":
           _handle_kill_command(args)
       elif command == "list":
           _handle_list_command()
       elif command == "listx":
           _handle_listx_command()
       else:
           return False
       return True
   ```

3. **Register commands for auto-completion.** Add a one-time `setMyCommands` call. This can be:
   - A CLI subcommand (`sase tg register-commands`) run once during setup.
   - Called on every inbound script startup (idempotent, but adds a small API call).
   - A standalone script.

   Since we use the raw Bot API via our `telegram_client`, the call would look like:

   ```python
   import requests

   def register_commands(token: str) -> None:
       commands = [
           {"command": "kill", "description": "Terminate a running agent by name"},
           {"command": "list", "description": "Show all running agents"},
           {"command": "listx", "description": "Show done/undismissed agents"},
       ]
       requests.post(
           f"https://api.telegram.org/bot{token}/setMyCommands",
           json={"commands": commands},
       )
   ```

### Phase 2: Handle no-argument `/kill` gracefully

Since selecting `/kill` from the menu sends it without arguments, we need a better UX than just "Usage: .kill
<agent_name>":

**Option A — Prompt with inline keyboard:** When `/kill` arrives with no args, send a message listing running agents as
inline keyboard buttons. User taps the agent they want to kill. This is the best UX but requires more work (new callback
data type, handler logic).

**Option B — Prompt with text:** Reply with "Which agent? Reply with the agent name." and use the existing two-step
feedback flow (awaiting state) to capture the next message as the agent name.

**Option C — Just show usage.** Reply "Usage: /kill <agent_name>" and let the user type it manually. Minimal effort,
acceptable UX.

Recommendation: **Option A** is the best experience and consistent with how we already use inline keyboards for other
interactions. The running agents list is already available via `list_running_agents()`.

### Phase 3: Deprecate dot commands

1. When a `.` command is received, handle it but also reply with a hint: "Tip: use /list instead of .list for
   auto-complete support."
2. After a transition period, remove dot command support entirely.

## Effort Estimate

| Task                                                         | Scope                                                             |
| ------------------------------------------------------------ | ----------------------------------------------------------------- |
| Unified command dispatch (Phase 1)                           | Small — ~30 lines changed in `sase_tg_inbound.py`                 |
| `setMyCommands` registration                                 | Small — new function + call site, ~20 lines                       |
| Interactive `/kill` with inline keyboard (Phase 2, Option A) | Medium — new callback type, keyboard builder, handler (~80 lines) |
| Deprecation hints (Phase 3)                                  | Trivial                                                           |
| Tests                                                        | Small-medium depending on existing test coverage for inbound      |

Total: roughly a few hours of work if going with Option A for `/kill`, less if going with Option C.

## Open Questions

1. **Should we register commands on every inbound poll startup or once via a setup command?** Registering on startup is
   simpler but adds an API call per invocation. A setup command is cleaner but requires remembering to re-run it when
   commands change.

2. **Do we want to add more commands while we're at it?** e.g., `/help`, `/status`, `/dismiss`. The menu supports up to
   100 commands, so there's room.

3. **Should `/start` do something?** Telegram sends `/start` when a user first opens a chat with the bot. Currently
   ignored. Could show a welcome/help message.

4. **BotCommandScope usage?** Since this is a single-user bot (one chat ID), scoping isn't necessary now, but if the bot
   is ever shared, per-chat scopes become relevant.
