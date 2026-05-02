---
create_time: 2026-03-24 17:45:55
status: done
prompt: sdd/prompts/202603/plan_telegram_agent_name_and_pdf.md
---

# Plan: Agent Name in Plan Telegram Messages + Always Attach Plan PDF

## Problem

Two issues with plan approval Telegram messages:

1. **No agent name shown** — The Telegram formatter already looks for `agent_name` in `action_data`
   (`formatting.py:336`) and would display it as a subtitle, but the plan notification pipeline never populates this
   field.

2. **No PDF attached for short plans** — `_format_plan_approval()` only adds the plan file to `attachments` when the
   message exceeds `MAX_MESSAGE_LENGTH` (4096 chars). Short plans get no PDF attachment at all.

## Root Cause Analysis

### Agent name missing

The call chain is:

- `run_agent_exec.py:343` calls `handle_plan_approval(plan_file, session_id)` — `ctx.agent_name` is available but not
  passed
- `_plan_utils.py:146` calls `notify_plan_approval(...)` — no `agent_name` parameter
- `senders.py:195` builds `action_data` — no `agent_name` key

The workflow completion flow (`run_agent_runner.py:468,476`) already threads `agent_name` into `action_data` correctly.
The plan approval flow just never got the same treatment.

### PDF not attached

In `formatting.py:362-382`, the plan file is only added to `attachments` inside the `if len(text) > MAX_MESSAGE_LENGTH`
branch. The outbound script (`sase_tg_outbound.py:444-478`) then converts attachments to PDF via `md_to_pdf()`. Short
plans never enter this branch, so no PDF is generated.

## Changes

### 1. `src/sase/notifications/senders.py` — Add `agent_name` param to `notify_plan_approval()`

Add `agent_name: str | None = None` parameter and include it in `action_data` when present.

### 2. `src/sase/llm_provider/_plan_utils.py` — Thread `agent_name` through `handle_plan_approval()`

Add `agent_name: str | None = None` parameter. Read `SASE_AGENT_NAME` env var as a fallback (consistent with how
`SASE_AGENT_CL_NAME` etc. are read). Pass it to `notify_plan_approval()`.

### 3. `src/sase/axe/run_agent_exec.py` — Pass `ctx.agent_name` to `handle_plan_approval()`

At line 343, add `agent_name=ctx.agent_name` to the call.

### 4. `src/sase/agent/launcher.py` — Set `SASE_AGENT_NAME` env var

Add `SASE_AGENT_NAME` to the subprocess environment (after line 81) so `_plan_utils.py` can read it as a fallback. Only
set when agent_name is available (need to check if it's passed to the launcher or derivable there). Actually,
`agent_name` is extracted later in `run_agent_runner.py` from `extract_directives_and_write_meta()`, not available at
launcher time. So the env var approach won't work for the launcher. Instead, rely on the direct parameter passing from
`run_agent_exec.py`.

**Revised**: Skip the env var approach. The direct parameter passing (`ctx.agent_name`) is sufficient since
`handle_plan_approval()` is always called from `run_agent_exec.py` where the context is available.

### 5. `sase-telegram/src/sase_telegram/formatting.py` — Always attach plan PDF

In `_format_plan_approval()`, always add the plan file to `attachments` when `n.files` is non-empty, not just when the
message is too long. Move the `attachments.append(n.files[0])` outside the `len(text) > MAX_MESSAGE_LENGTH` branch.

## File Summary

| File                                   | Repo          | Change                                                   |
| -------------------------------------- | ------------- | -------------------------------------------------------- |
| `src/sase/notifications/senders.py`    | sase          | Add `agent_name` param, populate in `action_data`        |
| `src/sase/llm_provider/_plan_utils.py` | sase          | Add `agent_name` param, pass to `notify_plan_approval()` |
| `src/sase/axe/run_agent_exec.py`       | sase          | Pass `ctx.agent_name` to `handle_plan_approval()`        |
| `src/sase_telegram/formatting.py`      | sase-telegram | Always append plan file to attachments                   |
