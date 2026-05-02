---
create_time: 2026-03-24 17:36:58
status: done
prompt: sdd/prompts/202603/commit_message_in_pdf.md
---

# Plan: Include Commit Message in Telegram PDF

## Context

When an agent completes and makes changes, the telegram outbound chop sends a PDF containing the agent's response and a
"Changes" section with the diff. We want to add the full commit message above the diff section.

The commit message is already captured: xprompt workflows (`commit.yml`, `propose.yml`) output `meta_commit_message` via
their hidden `report` step, which reads `commit_result.json` from the artifacts directory. This value ends up in
`workflow_state.json` as step output. However, it's not currently threaded through to the telegram outbound.

## Approach

Thread `meta_commit_message` from the workflow step output through the notification's `action_data` dict, then use it in
the telegram outbound when building the markdown before PDF conversion.

## Changes

### 1. `src/sase/axe/run_agent_exec.py` — Return step_output in result

Add `step_output` field to `_AgentExecResult` so the runner can access workflow meta fields:

```python
@dataclass
class _AgentExecResult:
    success: bool
    saved_path: str | None = None
    diff_path: str | None = None
    current_artifacts_dir: str = ""
    step_output: dict[str, Any] | None = None  # <-- add this
```

Set it where `step_output` is already extracted (around line 578):

```python
return _AgentExecResult(
    success=True,
    saved_path=saved_path,
    diff_path=diff_path,
    current_artifacts_dir=current_artifacts_dir,
    step_output=step_output,  # <-- add this
)
```

### 2. `src/sase/axe/run_agent_runner.py` — Pass commit_message in action_data

After getting `exec_result`, extract `meta_commit_message` from `step_output` and include it in `action_data`:

```python
# After line 304 (current_artifacts_dir = exec_result.current_artifacts_dir)
step_output = exec_result.step_output

# In the action_data dict construction (~line 468/478), add:
commit_message = (step_output or {}).get("meta_commit_message")
# Then add to action_data:
**({"commit_message": commit_message} if commit_message else {}),
```

### 3. `../sase-telegram/src/sase_telegram/scripts/sase_tg_outbound.py` — Add commit message section to markdown

Add a new helper function that prepends the commit message before the diff:

````python
def _prepend_commit_message_to_markdown(response_file: Path, commit_message: str) -> None:
    """Append a commit message section to a response markdown file.

    Called before _append_diff_to_markdown() so the commit message
    appears above the diff in the resulting PDF.
    """
    with open(response_file, "a", encoding="utf-8") as f:
        f.write("\n\n---\n\n")
        f.write("## Commit Message\n\n")
        f.write("```\n")
        f.write(commit_message)
        if not commit_message.endswith("\n"):
            f.write("\n")
        f.write("```\n")
````

Then call it in the main loop, just before the diff embedding (~line 437):

```python
# Embed commit message into the response markdown
commit_message = n.action_data.get("commit_message")
if commit_message:
    _prepend_commit_message_to_markdown(response_file, commit_message)

# Embed diff content into the response markdown
if diff_paths:
    _append_diff_to_markdown(response_file, diff_paths)
    diff_embedded = True
```

## File Summary

| File                                                             | Repo          | Change                                               |
| ---------------------------------------------------------------- | ------------- | ---------------------------------------------------- |
| `src/sase/axe/run_agent_exec.py`                                 | sase_101      | Add `step_output` to `_AgentExecResult`, populate it |
| `src/sase/axe/run_agent_runner.py`                               | sase_101      | Extract `meta_commit_message`, add to `action_data`  |
| `../sase-telegram/src/sase_telegram/scripts/sase_tg_outbound.py` | sase-telegram | New helper + call to insert commit message section   |
