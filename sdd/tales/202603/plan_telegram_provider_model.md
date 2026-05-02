---
create_time: 2026-03-30 11:11:38
status: done
prompt: sdd/prompts/202603/plan_telegram_provider_model.md
---

# Add LLM Provider and Model to Plan Telegram Messages

## Problem

When an agent submits a plan for approval, the Telegram notification shows:

```
📋 Plan Review  @agent_name
```

But workflow-complete messages already show the provider/model label:

```
✅ CLAUDE(opus) Complete  @agent_name
```

The provider and model info should be shown in plan messages too, so the user knows which LLM generated the plan.

## Design

Thread `agent_model` and `agent_llm_provider` through the existing plan approval notification chain. The data already
exists in `AgentExecContext` — it just isn't forwarded to the notification.

The plan message header will become:

```
📋 CLAUDE(opus) Plan Review  @agent_name
```

When neither provider nor model is available, the label is omitted to keep the message clean (preserving current
behavior).

## Changes

### Phase 1: Thread model/provider through sase core (3 files)

1. **`src/sase/notifications/senders.py`** — Add `agent_model` and `agent_llm_provider` optional params to
   `notify_plan_approval()`. Store them in `action_data` as `"model"` and `"llm_provider"` keys (matching the convention
   used by workflow-complete notifications).

2. **`src/sase/llm_provider/_plan_utils.py`** — Add `agent_model` and `agent_llm_provider` keyword params to
   `handle_plan_approval()`. Forward them to `notify_plan_approval()`.

3. **`src/sase/axe/run_agent_exec_plan.py`** — In `handle_plan_marker()`, pass `ctx.agent_model` and
   `ctx.agent_llm_provider` to `handle_plan_approval()`.

### Phase 2: Display label in Telegram formatting (1 file in sase-telegram plugin)

4. **`../sase-telegram/src/sase_telegram/formatting.py`** — In `_format_plan_approval()`, use
   `format_provider_model_label()` (already imported by `_format_workflow_complete()`) to build the label from
   `action_data`. Include it in the header when available.
