---
create_time: 2026-03-24 22:01:42
status: done
prompt: sdd/prompts/202603/telegram_resume_command.md
---

# Plan: Add `/resume` Telegram Slash Command

## Goal

Add a `/resume` slash command to the Telegram bot that lists all running and done/undismissed agents, each with a copy
button that produces the same resume text as the existing Resume buttons on agent launch/completion notifications.

## Context

The bot already has Resume copy buttons in two places:

- **Agent launch** (`sase_tg_inbound.py:373-402`): `{vcs_prefix}#resume:{name} %w:{name} ` — includes `%w:` wait
  directive since agent is still running
- **Workflow completion** (`formatting.py:534-553`): `{vcs_prefix}#resume:{name} ` — no wait directive since agent is
  done

The `/resume` command reuses this exact logic so users can resume any active agent without scrolling back through chat
history to find the original notification.

## Data Sources

- **Running agents**: `sase.agent.names.list_running_agents()` → `_RunningAgentInfo` with `name`, `prompt` (first ~200
  chars of raw_xprompt.md — sufficient for VCS tag extraction since tags are at the start)
- **Done/undismissed agents**: `sase.ace.tui.models.agent_loader.load_all_agents()` filtered by status and dismissed
  set, same as existing `/listx` — `Agent` model with `agent_name`, `get_raw_xprompt_content()`, `status`,
  `is_workflow_child`, `identity`
- **VCS tag extraction**: `sase.xprompt.extract_vcs_workflow_tag(prompt)` extracts leading VCS tags like `#gh:sase `

## Implementation

### File: `sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py`

#### 1. Add `_handle_resume_command()` function (after `_handle_listx_command`)

```python
def _handle_resume_command() -> None:
    """Handle /resume — show copy buttons to resume running or done agents."""
    from sase.ace.dismissed_agents import load_dismissed_agents
    from sase.ace.tui.models.agent_loader import load_all_agents
    from sase.agent.names import list_running_agents
    from sase.xprompt import extract_vcs_workflow_tag

    _DISMISSABLE_STATUSES = {"DONE", "FAILED", "PLAN DONE"}
    chat_id = credentials.get_chat_id()

    # --- Running agents ---
    running = list_running_agents()
    running_buttons: list[list[InlineKeyboardButton]] = []
    running_names: set[str] = set()
    for a in running:
        if not a.name:
            continue
        running_names.add(a.name)
        vcs_prefix = ""
        if a.prompt:
            vcs_tag = extract_vcs_workflow_tag(a.prompt)
            if vcs_tag:
                vcs_prefix = vcs_tag
        resume_text = f"{vcs_prefix}#resume:{a.name} %w:{a.name} "
        running_buttons.append([
            InlineKeyboardButton(
                f"🏃 {a.name}",
                copy_text=CopyTextButton(text=resume_text),
            )
        ])

    # --- Done/undismissed agents ---
    all_agents = load_all_agents()
    dismissed = load_dismissed_agents()
    done_buttons: list[list[InlineKeyboardButton]] = []
    for a in all_agents:
        name = a.agent_name or a.cl_name
        if a.status not in _DISMISSABLE_STATUSES:
            continue
        if a.is_workflow_child:
            continue
        if a.identity in dismissed:
            continue
        if name in running_names:
            continue
        vcs_prefix = ""
        raw = a.get_raw_xprompt_content()
        if raw:
            vcs_tag = extract_vcs_workflow_tag(raw)
            if vcs_tag:
                vcs_prefix = vcs_tag
        resume_text = f"{vcs_prefix}#resume:{name} "
        done_buttons.append([
            InlineKeyboardButton(
                f"✅ {name}",
                copy_text=CopyTextButton(text=resume_text),
            )
        ])

    buttons = running_buttons + done_buttons
    if not buttons:
        telegram_client.send_message(chat_id, "No agents to resume.")
        return

    telegram_client.send_message(
        chat_id,
        "Select an agent to resume:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
```

Key design decisions:

- Running agents get 🏃 prefix, done agents get ✅ prefix — visually distinguishable
- Running agents include `%w:{name}` wait directive (same as launch Resume), done agents don't (same as completion
  Resume)
- `running_names` set prevents duplicates if an agent appears in both lists
- Filters match `/listx` exactly: status in DISMISSABLE_STATUSES, not workflow child, not dismissed

#### 2. Register the command in `_handle_command()` dispatch

Add to the if/elif chain at line 504-509:

```python
elif command == "resume":
    _handle_resume_command()
```

#### 3. Add to `_SLASH_COMMANDS` list

Add to the list at line 675-679:

```python
("resume", "Copy resume text for an agent"),
```

**Note**: Adding to `_SLASH_COMMANDS` will auto-register the command with Telegram's menu on the next hourly refresh
cycle.

## Summary

Single file change (`sase_tg_inbound.py`):

1. New `_handle_resume_command()` function
2. One line in `_handle_command()` dispatch
3. One line in `_SLASH_COMMANDS`
