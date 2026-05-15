---
create_time: 2026-05-14 22:20:52
status: done
prompt: sdd/prompts/202605/async_workflow_detail_loads.md
---
# Async Workflow Detail Loads Plan

## Problem

The TUI audit calls out synchronous "workflow prompt/detail JSON loads" in the Agents tab detail path. Top-level
workflow rows reach `AgentPromptPanel._update_workflow_display()` through the debounced `AgentDetail.update_display()`
path. The debounce prevents per-keystroke work, but once it fires the Textual event loop still does all of the following
inline:

- Opens and parses `workflow_state.json` multiple times per render for inputs, meta fields, steps, error fallback, and
  prompt fallback.
- Globs and stats `*_prompt.md`, then reads the first prompt file.
- Globs and parses `prompt_step_*.json` marker files.
- Opens/parses `embedded_workflows_{step_name}.json` files.

The goal is to keep workflow-row selection responsive by moving disk I/O and JSON parsing off the event loop, while
preserving existing rendered output and the immediate header behavior used during `j`/`k` navigation.

## Proposed Design

1. Introduce a small workflow-detail snapshot layer in `src/sase/ace/tui/widgets/prompt_panel/_workflow_display.py`.

   The snapshot should be a plain dataclass containing the parsed `workflow_state.json`, optional prompt content,
   embedded markers, and embedded workflow metadata. A helper such as `load_workflow_detail_snapshot(agent)` will
   perform all filesystem work in one pass:
   - Resolve `agent.get_artifacts_dir()`.
   - Load `workflow_state.json` once using the existing `load_json_cached()` mtime cache.
   - Extract inputs, special meta fields, aggregate meta fields, steps, error, traceback, and fallback `step_prompts`
     from that in-memory dict.
   - Find/read the earliest `*_prompt.md` by mtime if present, otherwise use the `step_prompts` fallback.
   - Load `prompt_step_*.json` markers with `load_json_cached()`.
   - Load `embedded_workflows_{step_name}.json` with `load_json_cached()`.

   Formatting helpers should stay synchronous and pure: given an already-built snapshot, they construct the same Rich
   `Text`/`Syntax`/`Group` renderables that the current code constructs.

2. Add an async workflow-detail path at the `AgentDetail` boundary.

   `AgentDetail._update_display_impl()` already owns a generation counter used to discard stale debounced work. For
   top-level workflow agents (`AgentType.WORKFLOW`, not child, not `appears_as_agent`), it should ask the prompt panel
   to start a background workflow render and then skip the normal synchronous prompt render. The background task can use
   Textual `run_worker(thread=True)` from the prompt panel or `asyncio.to_thread()` via the owning widget. The result
   must only be applied if:
   - The worker result belongs to the currently selected agent identity.
   - The captured `AgentDetail` generation is still current.
   - The prompt panel still exists and the selected attempt view has not changed in a way that invalidates the result.

   On a cache hit, this still runs in the worker, but the cached JSON avoids repeated parse cost. On a cold read, the UI
   can keep the immediate header or show a compact loading render until the worker completes.

3. Preserve immediate navigation behavior.

   `AgentDetail.update_display_immediate()` currently calls `prompt_panel.update_header_only(agent)`, which
   intentionally avoids disk reads. Leave that path synchronous and unchanged. The async workflow render should be
   launched only from the debounced full update.

4. Preserve footer/file/tools behavior.

   Top-level workflow rows are non-agent entries. After starting async prompt rendering, `AgentDetail` should continue
   the same secondary-panel decisions it makes today for workflow agents: no tools probe, file panel only when existing
   workflow diff/extra files require it, otherwise expand prompt only. The async change should not alter artifact footer
   discovery or ChangeSpec jump behavior.

5. Tests.

   Add focused tests around the prompt-panel workflow snapshot helper and the AgentDetail orchestration:
   - Snapshot helper reads `workflow_state.json` once per render path and uses parsed data for inputs, meta fields,
     steps, and fallback prompts.
   - Prompt files, embedded markers, and embedded metadata still render in the expected order.
   - Selecting a workflow row starts a background render instead of directly invoking the synchronous workflow display
     path from the debounced update.
   - A stale worker result is ignored when the detail generation advances before completion.

   Existing prompt display tests should continue to cover terminal agents and workflow child agents.

6. Verification.

   Run the narrow tests first:
   - `just install` if the workspace environment is not current.
   - `pytest tests/ace/tui/widgets/test_agent_display_workflow.py` or the new focused test file.
   - Relevant existing prompt-panel tests such as
     `pytest tests/ace/tui/widgets/test_agent_display_xprompt.py tests/test_ace_tui_widgets.py`.

   Because this repo requires it after code changes, finish with `just check`.

## Risks and Mitigations

- Textual worker callback ordering can race with selection changes. Use the existing generation counter and agent
  identity checks before applying results.
- Rendering Rich objects in a worker may touch Textual widget state if the code is not cleanly separated. Keep worker
  work limited to filesystem reads and pure renderable construction that does not call `self.update()`.
- `workflow_state.json` changes frequently for running workflows. The mtime-keyed cache is acceptable because it
  invalidates on `(mtime_ns, size)`; worker results are short-lived and stale UI results are guarded by generation.
- Current helper functions are method-shaped and read from disk. Keep backwards compatibility where easy, but route the
  main render path through the new snapshot helper so the audit offender is fixed even if old helpers remain for direct
  unit tests.
