---
create_time: 2026-03-27 20:08:48
status: done
---

# Plan: Link Planner and Coder Agent Chat Files

## Problem

In multi-step execution loops (planner -> approval -> coder), only the **final** agent step's chat history is saved to
`~/.sase/chats/`. The planner's conversation is lost entirely. There are no cross-references between related chat files,
making it hard to trace the full planner-to-coder pipeline from the chat history.

## Current State

- `_finalize_loop()` in `run_agent_exec.py` saves ONE chat file per execution loop, containing only the last step's
  prompt/response
- The planner agent is killed by SIGTERM when `sase plan` runs; its response text is not captured, but the plan file on
  disk IS the meaningful output
- `agent_meta.json` tracks relationships via `parent_timestamp` and `role_suffix` (`.plan`, `.code`, `.2`, `.3`,
  `.epic`, `.q`), but this metadata isn't reflected in chat files
- `done.json` has a `response_path` field pointing to the saved chat file, but only the final step writes `done.json`
  with this field

## Goal

1. Save a **separate chat file for each agent step** in multi-step execution loops
2. Add **cross-links** between related chat files (planner <-> coder, feedback rounds, etc.)
3. Store `chat_path` in each step's `agent_meta.json` so the TUI can discover it

## Design

### Chat file per step

When the execution loop transitions between steps (plan approval, feedback, questions), save a chat file for the step
that just completed before creating follow-up artifacts.

**For planner steps** (killed by `sase plan`): the full LLM response is unavailable. The chat "response" will be a
formatted reference to the plan file with the first ~10 lines as a preview excerpt. This gives enough context to
understand the planner's output.

**For feedback/question steps**: same approach - save the prompt and reference to the updated plan.

**For the final step** (coder/epic): behavior is unchanged - the full response is saved as today.

### Filename differentiation

Chat filenames already support an `agent` parameter. Intermediate steps will pass `agent_name.role_suffix` (e.g.,
`a.plan`, `a.2`, `a.code`) to `generate_chat_filename`, producing unique filenames like:

```
branch-ace_run-a.plan-260327_152207.md    # planner
branch-ace_run-a.2-260327_152530.md       # feedback round
branch-ace_run-a.code-260327_153045.md    # coder
```

### Cross-linking format

Each chat file includes a `## Linked Chats` section (after timestamp, before extras):

```markdown
## Linked Chats

| Step | Role  | Chat                                                   |
| ---- | ----- | ------------------------------------------------------ |
| 1    | .plan | `~/.sase/chats/branch-ace_run-a.plan-260327_152207.md` |
| 2    | .code | `~/.sase/chats/branch-ace_run-a.code-260327_153045.md` |
```

Since forward links (planner -> coder) aren't available when the planner chat is first saved, the **final step
retroactively updates** earlier chat files with the complete link table.

### State tracking

`LoopState` gets a new field:

```python
saved_chat_paths: list[tuple[str, str]] = field(default_factory=list)
# List of (role_suffix, chat_file_path) pairs, accumulated during the loop
```

## Implementation

### Phase 1: New module `src/sase/history/chat_links.py`

Small helper module with three functions:

1. **`build_linked_chats_section(links: list[tuple[str, str]]) -> str`**
   - Takes a list of `(role_suffix, chat_path)` pairs
   - Returns a formatted `## Linked Chats` markdown table
   - Highlights the "current" entry if a `current_role` parameter is passed

2. **`append_links_to_chat(chat_path: str, links_section: str) -> None`**
   - Opens an existing chat file and inserts the `## Linked Chats` section
   - Inserts after the `**Timestamp:**` line and before any existing sections
   - Idempotent: replaces existing `## Linked Chats` section if present

3. **`format_plan_as_response(plan_file: str) -> str`**
   - Reads the plan file, extracts first ~10 content lines as preview
   - Returns formatted response like:

     ```
     *Plan submitted for review.*

     **Plan file:** `plans/my_feature.md`

     > [preview excerpt]

     *See full plan file for details.*
     ```

### Phase 2: Save intermediate chats in `run_agent_exec_plan.py`

**In `handle_plan_marker`**, after plan approval resolves (approve/epic/feedback):

```python
# Save planner chat before creating follow-up
from sase.history.chat import save_chat_history
from sase.history.chat_links import format_plan_as_response

plan_response = format_plan_as_response(plan_data["plan_file"])
planner_agent = f"{ctx.agent_name}.plan" if ctx.agent_name else None
saved = save_chat_history(
    prompt=state.current_prompt,
    response=plan_response,
    workflow="ace-run",
    agent=planner_agent,
    timestamp=ctx.timestamp,
    extra_sections=format_extra_sections(state.current_artifacts_dir),
)
state.saved_chat_paths.append((".plan", saved))

# Write chat_path to agent_meta.json
update_meta_field(state.current_artifacts_dir, "chat_path", saved)
```

**For feedback rounds** (inside the `if plan_result.action == "feedback":` block):

- Save a chat for the feedback round before creating follow-up artifacts
- Use the feedback content as the response

### Phase 3: Update `_finalize_loop` in `run_agent_exec.py`

After saving the final chat file:

1. Add the final chat to `state.saved_chat_paths`
2. Build the complete links table from all saved paths
3. Write the links section into the final chat file
4. Retroactively update all earlier chat files with the complete links table
5. Write `chat_path` to the final step's `agent_meta.json`

```python
if state.loop_outcome == "completed":
    # ... existing save_chat_history call ...
    state.saved_chat_paths.append((state.current_role_suffix or ".code", saved_path))

    # Cross-link all chat files
    if len(state.saved_chat_paths) > 1:
        from sase.history.chat_links import append_links_to_chat, build_linked_chats_section

        for role, path in state.saved_chat_paths:
            links_section = build_linked_chats_section(
                state.saved_chat_paths, current_role=role
            )
            append_links_to_chat(os.path.expanduser(path), links_section)
```

### Phase 4: Update `LoopState` in `run_agent_exec.py`

Add the tracking field:

```python
@dataclass
class LoopState:
    # ... existing fields ...
    saved_chat_paths: list[tuple[str, str]] = field(default_factory=list)
```

### Phase 5: Tests

- **`tests/history/test_chat_links.py`** (new):
  - `test_build_linked_chats_section` - correct markdown table output
  - `test_build_linked_chats_section_highlights_current` - current role bolded
  - `test_append_links_to_chat_inserts_after_timestamp` - correct insertion point
  - `test_append_links_to_chat_replaces_existing` - idempotent updates
  - `test_format_plan_as_response` - preview extraction and formatting
  - `test_format_plan_as_response_short_plan` - handles plans shorter than 10 lines

## Edge Cases

- **Single-step runs** (no plan/feedback): No intermediate chats saved, no links section added. Behavior unchanged from
  today.
- **Plan rejected**: Planner chat is saved but no coder chat exists. Links section shows only the planner entry.
- **Plan committed** (no coder spawn): Same as rejected - just the planner entry.
- **Multiple feedback rounds**: Each round gets its own chat file. All are linked.
- **Epic agents**: `.epic` step gets a chat file just like `.code`.
- **Question flows**: `.q` steps get chat files with the Q&A as response content.
- **Agent has no name**: Use `None` for the agent parameter (existing behavior). Links still work via role suffix.

## Files Changed

| File                                  | Change                                                                |
| ------------------------------------- | --------------------------------------------------------------------- |
| `src/sase/history/chat_links.py`      | **New** - link building, insertion, plan summary                      |
| `src/sase/axe/run_agent_exec.py`      | Add `saved_chat_paths` to `LoopState`, cross-link in `_finalize_loop` |
| `src/sase/axe/run_agent_exec_plan.py` | Save planner/feedback chats in `handle_plan_marker`                   |
| `tests/history/test_chat_links.py`    | **New** - unit tests for chat_links module                            |
