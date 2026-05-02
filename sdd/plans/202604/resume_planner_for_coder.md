---
create_time: 2026-04-02 13:11:47
status: done
prompt: sdd/prompts/202604/resume_planner_for_coder.md
---

# Prepend `#resume:<planner_name>` to Coder Agent Prompts

## Problem

When a planner agent creates a plan and a coder agent is spawned to implement it, the coder only receives the plan file
reference (`@plan.md`) and "Implement it now." The coder has no context about the user's original request, the planner's
analysis, or the conversation that led to the plan. This means the coder may miss nuances that the planner understood.

## Design

Prepend `#resume:<planner_name> ` to the coder agent's prompt so the `#resume` xprompt injects the planner's
conversation history. For example, if the planner is `@h.1`, the coder prompt becomes:

```
#resume:h.1 %model:opus #gh:sase @plan.md

The above plan has been reviewed and approved. Implement it now.
```

The `#resume` xprompt expands this into a multi-segment prompt (via `---` separator) where:

- Segment 1: The planner's conversation (user prompt + plan content), with xprompt expansion disabled
- Segment 2: The new query (plan reference + "Implement it now"), with xprompt expansion re-enabled

## Key Constraint: Planner Has No `done.json`

The `#resume` xprompt currently requires the target agent to have a `done.json` (uses
`find_named_agent(name, only_done=True)`). But the planner step never gets a `done.json` — the execution loop writes it
only in `_finalize_loop` after the entire workflow completes.

However, the planner's chat IS already saved (line 193 of `run_agent_exec_plan.py`) and its path is stored as
`chat_path` in `agent_meta.json` (line 203). We can modify `#resume` to fall back to `chat_path` from the agent meta
when `done.json` doesn't exist.

**Why not write a `done.json` for the planner step?** Writing `done.json` to the root artifacts dir would be overwritten
by `_finalize_loop` with the coder's `response_path`, making post-completion `#resume:h.1` return the wrong chat.
Keeping `chat_path` in the meta (already done) and teaching `#resume` to use it is cleaner.

## Implementation

### 1. Modify `#resume.yml` resolve step to support `chat_path` fallback

**File:** `src/sase/xprompts/resume.yml`

Replace the resolve step with:

```python
import json, os
from sase.agent.names import find_named_agent
name = {{ name | tojson }}
response_path = None

# Standard path: done agent with response_path in done.json
agent = find_named_agent(name, only_done=True)
if agent is not None:
    done_path = os.path.join(agent.artifacts_dir, "done.json")
    try:
        with open(done_path, encoding="utf-8") as f:
            response_path = json.load(f).get("response_path")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

# Fallback: any agent (including running) with chat_path in meta
if not response_path:
    agent = find_named_agent(name)
    if agent is not None:
        meta_path = os.path.join(agent.artifacts_dir, "agent_meta.json")
        try:
            with open(meta_path, encoding="utf-8") as f:
                response_path = json.load(f).get("chat_path")
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

if not response_path:
    raise RuntimeError(f"No agent with chat history found for: {name}")
print(json.dumps({"path": response_path}))
```

This broadens `#resume` to work with intermediate workflow steps (not just fully completed agents), which is useful
beyond just the planner-to-coder case.

### 2. Prepend `#resume:<planner_name>` in the approval branch

**File:** `src/sase/axe/run_agent_exec_plan.py`, in `handle_plan_marker` approval branch (~line 370)

Before setting `state.current_prompt`, compute the planner name and build the resume prefix:

```python
# The planner's name: after promote_to_workflow, root has name=<base>.1;
# for feedback rounds, the most recent planner is <base>.<step>.
# state.agent_step was just incremented for the coder, so planner = step - 1.
resume_prefix = ""
if ctx.agent_name:
    planner_name = f"{ctx.agent_name}.{state.agent_step - 1}"
    resume_prefix = f"#resume:{planner_name} "

state.current_prompt = (
    f"{model_prefix}{resume_prefix}{vcs_prefix}"
    f"@{plan_data['plan_file']}\n\n"
    "The above plan has been reviewed and approved. "
    f"Implement it now.{coder_extra}\n{embedded_refs}"
)
```

**Note on ordering:** `model_prefix` (`%model:opus\n`) must come before `#resume` because `%model` is a directive parsed
before xprompt expansion. Placing `#resume` after the model prefix and before `vcs_prefix` ensures the planner context
is injected first, then the VCS workflow tag and plan reference follow in the "New Query" segment.

### 3. Edge cases

- **No `ctx.agent_name`:** `resume_prefix` is empty — no `#resume` prepended. Single unnamed agents don't need this.
- **Feedback rounds:** Works correctly. After one feedback round, `state.agent_step` is 3 (feedback=2, coder=3), so
  planner_name is `h.2` — the feedback planner that produced the approved plan.
- **Epic branch:** No change needed. Epic agents run `#bd/new_epic`, not code — they don't need planner context.

### 4. Tests

- Unit test for the modified `#resume.yml` resolve logic: mock an agent with `chat_path` in meta but no `done.json`,
  verify `#resume` resolves correctly.
- Integration test: verify the coder prompt contains `#resume:<planner_name>` after plan approval.
