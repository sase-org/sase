# XPrompt Workflow Step: Special Output Variables

Research into underscore-prefixed and system-managed output variables that xprompt YAML workflow steps can produce.
These are distinct from user-defined output schema fields.

## How Step Output Works

Every workflow step produces an output dict stored in `context[step_name]`. Subsequent steps access it via Jinja2
templates (e.g. `{{ my_step._raw }}`). Output is populated differently depending on step type:

- **bash/python steps**: stdout is parsed by `parse_bash_output()` in `workflow_executor_utils.py`. Supports JSON,
  `key=value` lines, or plain text fallback.
- **agent/prompt steps**: response text is optionally parsed for structured content via `extract_structured_content()`
  in `workflow_executor_steps_prompt.py`.

---

## Special Output Variables

### `_output` (bash/python only)

**Set in**: `workflow_executor_utils.py:103`

When a bash or python step emits plain text that contains no `key=value` lines and is not valid JSON, the entire stdout
is stored under the `_output` key.

```python
# parse_bash_output fallback
return {"_output": output} if output else {}
```

Used by loop `join: text` mode to concatenate results (`workflow_executor_loops.py:140`).

---

### `_raw` (agent/prompt only)

**Set in**: `workflow_executor_steps_prompt.py:317, 319`

Contains the raw response text from an agent step. Set in two cases:

1. The step has no output schema (`step.output` is None) -- always set.
2. The step has an output schema but structured extraction failed -- fallback.

```python
if step.output:
    try:
        data, _ = extract_structured_content(response_text)
        ...
    except Exception:
        output = {"_raw": response_text}
else:
    output = {"_raw": response_text}
```

Also used by `workflow_runner.py:491` to extract the final response text, and by `workflow_output.py:384` as a display
fallback.

---

### `_data` (agent/prompt only)

**Set in**: `workflow_executor_steps_prompt.py:315`

Contains parsed structured data when an agent step has an output schema and `extract_structured_content()` returns a
non-dict value (e.g. a list or scalar).

```python
data, _ = extract_structured_content(response_text)
if isinstance(data, dict):
    output = data          # fields go directly into output
else:
    output = {"_data": data}  # wrapped in _data
```

When structured extraction returns a dict, its keys are merged directly into the output (no `_data` wrapper).
`workflow_output.py:384` unwraps `_data` for display: `output.get("_data", output.get("_raw", output))`.

---

### `_chdir` (bash/python only)

**Set in**: `workflow_executor_steps_script.py:218-223, 393-398`

A control variable that changes the executor's working directory. When a script step emits `_chdir=/some/path` as a
key=value line, the executor calls `os.chdir()` to that path. The key is **popped** from output before being stored in
context, so downstream steps never see it.

```python
if "_chdir" in output:
    chdir_path = str(output.pop("_chdir"))
    if not os.path.isabs(chdir_path):
        chdir_path = os.path.abspath(chdir_path)
    os.chdir(chdir_path)
```

Relative paths are resolved to absolute via `os.path.abspath()`.

---

### `_artifact` (bash/python only)

**Set in**: `workflow_executor_steps_script.py:226-227, 401-402`

Set when a step declares `artifact: stdout`. The step's stdout is captured to a file in the workflow's `artifacts_dir`,
and `_artifact` is set to the file path.

```python
if artifact_path is not None:
    output["_artifact"] = artifact_path
```

Useful for saving large outputs (e.g. diffs) to disk rather than keeping them in-memory in the context dict.

---

### `_prompt` (embedded workflow post-steps only)

**Set in**: `workflow_executor_steps_prompt.py:411`

Injected into the embedded workflow context before post-steps execute. Contains the fully expanded agent prompt that was
sent to the LLM.

```python
info.context["_prompt"] = expanded_prompt
```

Only available within embedded workflow post-step scope, not in the parent step's output.

---

### `_response` (embedded workflow post-steps only)

**Set in**: `workflow_executor_steps_prompt.py:412`

Injected alongside `_prompt` into the embedded workflow context before post-steps execute. Contains the raw response
text from the agent.

```python
info.context["_response"] = response_text
```

Only available within embedded workflow post-step scope, not in the parent step's output.

---

### `approved` (bash/python with HITL)

**Set in**: `workflow_executor_steps_script.py:194, 369`

Set to `True` when a step with `hitl: true` is accepted by the user during human-in-the-loop review. Only added on
acceptance, not on rejection or edit.

```python
elif result_hitl.action == "accept":
    output["approved"] = True
```

Downstream steps can check `{{ my_step.approved }}` to branch on HITL outcome.

Note: agent/prompt steps with HITL do **not** set `approved` -- only bash/python steps do.

---

### `meta_*` (convention, any step type)

**Collected in**: `workflow_executor_steps_prompt.py:49-62`

Any output field whose key starts with `meta_` is treated as metadata. These are collected from embedded workflow
pre-steps and post-steps and merged into the parent agent step's output (with parent keys taking priority).

```python
for k, v in step_output.items():
    if k.startswith("meta_") and v:
        meta_fields[k] = str(v)
```

Common examples: `meta_workspace`, `meta_project`, `meta_cl_name`, `meta_cl_url`, `meta_pr_header`. Used by the TUI to
display context and to enrich agent prompt markers for done entries.

---

### `diff_path` (agent/prompt, system-managed)

**Set in**: `workflow_executor_steps_prompt.py:494, 501`

Not underscore-prefixed, but system-managed. Set on the step output in two ways:

1. **Auto-captured VCS diff**: after an agent step completes, the executor calls `capture_vcs_diff()` and writes any
   diff to `{step_name}_diff.txt` in artifacts_dir (lines 382-392).
2. **Embedded post-step path output**: if the last post-step of an embedded workflow declares a `path`-type output
   field, its value becomes `diff_path` (lines 64-76, 488-502).

The TUI uses `diff_path` to populate the file panel for done agent entries.

---

## Summary Table

| Variable    | Step Types       | Scope                | Persists in Context? | Purpose                                |
| ----------- | ---------------- | -------------------- | -------------------- | -------------------------------------- |
| `_output`   | bash, python     | step output          | Yes                  | Plain text fallback when no key=value  |
| `_raw`      | agent/prompt     | step output          | Yes                  | Raw agent response text                |
| `_data`     | agent/prompt     | step output          | Yes                  | Structured data (non-dict)             |
| `_chdir`    | bash, python     | consumed immediately | **No** (popped)      | Change executor working directory      |
| `_artifact` | bash, python     | step output          | Yes                  | Path to artifact file from `artifact:` |
| `_prompt`   | agent (embedded) | embedded context     | No (scoped)          | Expanded prompt for post-steps         |
| `_response` | agent (embedded) | embedded context     | No (scoped)          | Agent response for post-steps          |
| `approved`  | bash, python     | step output          | Yes                  | HITL acceptance flag                   |
| `meta_*`    | any              | step output          | Yes (merged up)      | Metadata fields for TUI/markers        |
| `diff_path` | agent/prompt     | step output          | Yes                  | Path to diff file for TUI file panel   |

## Loop Join Modes and Special Variables

The `_collect_results` method in `workflow_executor_loops.py:112-151` handles how iteration outputs are combined. In
`join: text` mode, it specifically looks for `_raw` and `_output` to extract text:

```python
if "_raw" in r:
    texts.append(str(r["_raw"]))
elif "_output" in r:
    texts.append(str(r["_output"]))
else:
    texts.append(json.dumps(r))
```

## Output Display Priority

In `workflow_output.py:384`, the display logic unwraps special keys:

```python
display_data = output.get("_data", output.get("_raw", output))
```

Priority: `_data` > `_raw` > full output dict.
