---
create_time: 2026-06-13 09:01:57
bead_id: sase-4m
status: done
tier: epic
prompt: sdd/prompts/202606/prompt_history_tui.md
---
# Prompt History TUI Improvements

## Context

The current prompt history feature has two separate behaviors that should be untangled:

- Shared prompt history storage and picker APIs prioritize entries by branch/workspace/project context. This is
  implemented in `src/sase/history/prompt.py` through `branch_or_workspace`, `workspace`, current-branch/workspace
  detection, `*`/`~` markers, and a two-stage sort. The TUI modal, CLI fzf picker, docs, and tests all surface that
  behavior.
- The prompt input widget opens history by submitting special text such as `.`, `.x`, or `#gh:sase .`. That logic lives
  in `PromptInputBar._handle_text_submission()` and `PromptBarRequestsMixin.on_prompt_input_bar_history_requested()`.
- Launch history persistence is partly protected by the cancel-unmount safety net, but successful submit intentionally
  bypasses that path for responsiveness and to avoid stale cancelled writes. Failed launch attempts therefore need
  worker-side history writes, not UI-thread unmount writes.

The TUI performance constraint is important: do not add synchronous disk I/O or launch resolution work to Textual key
handlers. Opening the modal from `<ctrl+.>` should only gather the current in-memory text and push a modal; history file
loading should stay in existing modal/opening paths, and launch failure saves should stay in worker/background launch
paths.

## Goals

1. Prompt history ordering is recency-only, not project/branch/VCS-workflow aware.
2. User-facing references to branch/workspace/project-prioritized history are removed.
3. The prompt input widget no longer treats typed `.`/`.x`/VCS-dot text as history commands.
4. `<ctrl+.>` opens the prompt history modal from the prompt input widget only when the current prompt has exactly one
   logical line.
5. The modal filter input is pre-populated with that single line when opened through `<ctrl+.>`.
6. Failed agent launches record the submitted prompt as cancelled history, including short prompts such as `#gh:foobar`.
7. Normal successful submit still does not route through the prompt-bar cancel save path.

## Non-Goals

- Do not remove the existing leader-mode prompt history commands unless a phase finds they are purely tied to
  project-prioritized sorting. The request targets the prompt input widget's typed `.` syntax; leader `,.`, `, Ctrl+G`,
  and `,>` are separate keymap commands.
- Do not migrate existing `~/.sase/prompt_history.json` with a standalone migration command. Backward-compatible reads
  are enough.
- Do not make prompt history loading happen on every prompt keystroke.

## Phase 1: Make Prompt History Recency-Only

Owner: first implementation agent.

Scope:

- Refactor `src/sase/history/prompt.py` so picker results are sorted only by `last_used` descending.
- Remove prompt-history logic whose only purpose is project/branch/workspace prioritization:
  - current branch/workspace detection for prompt history,
  - `_branch_or_workspace_for_segment()`,
  - `current_branch` / `current_workspace` / `sort_by` picker arguments,
  - `*` and `~` ranking markers.
- Keep the JSON reader backward compatible with old entries containing `branch_or_workspace` and `workspace`, but do not
  require those fields for an entry to load.
- Prefer new writes that only persist fields still needed by prompt history: `text`, `timestamp`, `last_used`, and
  `cancelled`.
- Keep existing short-prompt filtering semantics for normal successful/cancelled history writes; the failed-launch phase
  will add an explicit exception for launch failures.
- Update all direct call sites of `add_or_update_prompt()` that only pass `project_name` or `branch_or_workspace` for
  prompt-history sorting. Preserve unrelated launch context variables such as `history_sort_key` where they are still
  needed by agent spawning, workspace metadata, or artifact naming.
- Update `get_prompts_for_fzf()` tests to assert recency ordering instead of current-branch/current-workspace grouping.
- Update multi-prompt tests so segments are still saved and deduplicated, but no longer derive segment-specific history
  keys.

Key files:

- `src/sase/history/prompt.py`
- `src/sase/agent/launch_cwd.py`
- `src/sase/ace/tui/actions/agent_workflow/_launch_body.py`
- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_mount.py`
- `src/sase/main/query_handler/_query.py`
- `tests/history/test_prompt.py`
- `tests/history/test_prompt_multi.py`
- `tests/history/test_prompt_filtering.py`
- `tests/history/test_prompt_cancelled.py`

Acceptance:

- `get_prompts_for_fzf()` or its replacement returns non-cancelled prompts by descending `last_used`, unless cancelled
  prompts are explicitly included.
- Old JSON entries with legacy context fields still load.
- Old JSON entries missing legacy context fields also load.
- No prompt-history test expects branch/workspace/project prioritization.

Suggested verification:

```bash
pytest tests/history
```

## Phase 2: Remove Sorting References From Pickers, Docs, And Leader Labels

Owner: second implementation agent.

Scope:

- Update `PromptHistoryModal` to stop displaying project/branch/workspace ranking:
  - remove `sort_by` and `workspace` constructor arguments,
  - remove the sort-context header,
  - remove `display_context`,
  - remove branch/workspace metadata from preview if it only exists for prompt-history ranking,
  - filter by prompt text only, unless a retained field has an independent product purpose.
- Replace modal rows with compact recency rows: cancelled marker, last-used timestamp, prompt preview.
- Update CLI fzf prompt history picker in `src/sase/main/query_handler/_editor.py` to call the recency-only API and
  remove headers such as `* = current branch/workspace`.
- Keep the CLI VCS-dot reuse command only if it still has value as a wrapper that replaces embedded VCS tags. Its picker
  must no longer sort or describe sorting by that VCS ref.
- Update command/help/footer labels that mention "last CL" or project-ranked history. Leader commands can remain, but
  their labels should describe what they do without claiming the history list is scoped or sorted to a CL.
- Update docs and blog text that mention `.` history, `.x`, ranking by CL/project, or visual markers `*`/`~`, but do not
  document the new `<ctrl+.>` until Phase 3 implements it.

Key files:

- `src/sase/ace/tui/modals/prompt_history_modal.py`
- `src/sase/main/query_handler/_editor.py`
- `src/sase/main/query_handler/special_cases.py`
- `src/sase/ace/tui/widgets/keybinding_footer.py`
- `src/sase/ace/tui/modals/help_modal/agents_bindings.py`
- `src/sase/ace/tui/modals/help_modal/changespecs_bindings.py`
- `src/sase/ace/tui/modals/help_modal/axe_bindings.py`
- `src/sase/ace/tui/commands/catalog.py`
- `docs/ace.md`
- `docs/blog/posts/prompt-widget-and-nvim.md`
- `tests/ace/tui/modals/test_prompt_history_modal.py`
- `tests/test_special_cases.py`
- `tests/test_command_catalog.py`

Acceptance:

- Prompt history UI no longer contains `*`/`~` marker explanations.
- Prompt history filtering does not match branch/workspace context.
- CLI picker headers no longer describe branch/workspace/project ranking.
- The VCS-dot CLI special case, if retained, still replaces embedded VCS tags in the selected prompt.

Suggested verification:

```bash
pytest tests/ace/tui/modals/test_prompt_history_modal.py tests/test_special_cases.py tests/test_command_catalog.py
```

## Phase 3: Add `<ctrl+.>` Prompt-Input History Trigger

Owner: third implementation agent.

Scope:

- Remove the typed history trigger logic from `PromptInputBar._handle_text_submission()`:
  - `.` no longer opens history,
  - `.x` no longer opens history,
  - `#vcs:ref .` and `#vcs:ref .x` no longer open history from the prompt input widget.
- Remove prompt-bar cancel-save skip logic that only exists for those typed trigger patterns.
- Add a prompt text-area action for `<ctrl+.>` in `PromptTextArea`:
  - handle Textual's actual key spelling for Ctrl-period, likely `ctrl+full_stop`; include a narrowly-scoped
    compatibility check for any observed spelling such as `ctrl+period` only if tests or Textual behavior require it,
  - only handle the action when the parent prompt bar is in normal prompt mode,
  - only handle it when `document.line_count == 1`,
  - clear active completion/hint state before opening history, matching other modal-triggering shortcuts.
- Extend `PromptInputBar.HistoryRequested` to carry the current single-line text as `initial_filter`.
- Extend `PromptHistoryModal` with an `initial_filter` constructor argument:
  - initialize the filter input value with that text,
  - pre-filter the list before first render,
  - focus the filter input and keep the cursor at the end.
- Update prompt-history request handling so cancelling a modal opened from `<ctrl+.>` returns focus to the existing
  prompt bar without unmounting or saving the typed line as cancelled.
- Preserve existing behavior for selecting a history entry:
  - Enter submits the selected historical prompt,
  - Ctrl+I loads the selected historical prompt into the input bar,
  - Ctrl+G opens it in the editor first.
- Decide explicitly whether multiline `<ctrl+.>` is silent no-op or a warning toast. Prefer silent no-op unless the
  existing TUI shortcut style strongly favors a warning.
- Update placeholder/subtitle/docs to replace `.` history guidance with `<ctrl+.>` guidance, following current prompt
  widget conventions.

Key files:

- `src/sase/ace/tui/widgets/prompt_text_area.py`
- `src/sase/ace/tui/widgets/prompt_input_bar.py`
- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_requests.py`
- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_mount.py`
- `src/sase/ace/tui/modals/prompt_history_modal.py`
- `docs/ace.md`
- `docs/blog/posts/prompt-widget-and-nvim.md`
- new or existing focused tests under `tests/ace/tui/`

Acceptance:

- With a one-line prompt `fix failing auth test`, `<ctrl+.>` opens prompt history and the modal filter input contains
  `fix failing auth test`.
- With a multiline prompt, `<ctrl+.>` does not open the modal.
- Cancelling the modal opened by `<ctrl+.>` leaves the prompt bar mounted with its original text.
- Submitting `.` from the prompt input widget does not open prompt history.
- `.x` is no longer a prompt-input history shortcut; cancelled prompts remain available from the modal toggle and leader
  cancelled-history command.

Suggested verification:

```bash
pytest tests/ace/tui tests/test_keymaps_validation.py
```

## Phase 4: Save Failed TUI Launches As Cancelled History

Owner: fourth implementation agent.

Scope:

- Add a dedicated failed-launch history helper instead of reusing the prompt-bar cancel-unmount path. The helper should:
  - run only from worker/background launch code or pre-worker submit failure code, not from a hot key handler,
  - write `cancelled=True`,
  - use `allow_short=True` so short failed launch prompts such as `#gh:foobar` are recorded,
  - force the cancelled state for failed launch attempts without changing normal prompt cancellation semantics.
- Preserve the existing normal cancellation rule that a user cancelling an input bar does not downgrade a previously
  successful prompt unless the new helper is explicitly used for a launch failure.
- Apply the helper to TUI launch failure branches that currently miss history or save as non-cancelled:
  - unresolved explicit VCS tag in home-mode launches, including single-token tags like `#gh:foobar`,
  - launch-name validation failures,
  - bulk launch rejecting multi-prompt input,
  - final `execute_launch_plan()` / `_launch_background_agent()` exceptions,
  - prompt fan-out, repeat, and multi-prompt worker exceptions when no complete successful launch was produced,
  - forced name-reuse wipe failure in `_finish_agent_launch()` if it is treated as a submitted launch attempt.
- Avoid duplicate history writes where an earlier branch already saved the same failed prompt as cancelled.
- Keep `tests/ace/tui/test_prompt_bar_submit_no_cancel_save.py` passing: successful submit must still use
  `_unmount_prompt_bar_after_submit()` and must not synchronously save cancelled history.

Key files:

- `src/sase/history/prompt.py`
- `src/sase/ace/tui/actions/agent_workflow/_launch_start.py`
- `src/sase/ace/tui/actions/agent_workflow/_launch_body.py`
- `src/sase/ace/tui/actions/agent_workflow/_launch_multi_model.py`
- `src/sase/ace/tui/actions/agent_workflow/_launch_multi_prompt.py`
- `src/sase/ace/tui/actions/agent_workflow/_launch_repeat.py`
- `tests/ace/tui/test_agent_launch_vcs.py`
- `tests/ace/tui/test_agent_launch_dispatch.py`
- `tests/ace/tui/test_launch_fan_out_unified.py`
- `tests/ace/tui/test_prompt_bar_submit_no_cancel_save.py`
- `tests/history/test_prompt_cancelled.py`

Acceptance:

- `#gh:foobar` submitted from a home-mode TUI prompt fails to launch and creates a cancelled prompt history entry even
  though it is a single token.
- A launch-name validation failure records the submitted prompt as cancelled.
- A spawn/claim failure after the prompt has been submitted records the submitted prompt as cancelled, using the
  failed-launch helper rather than the prompt-bar cancel path.
- A successful launch still records the prompt as non-cancelled.
- A later successful launch of the same text can upgrade the entry back to non-cancelled.

Suggested verification:

```bash
pytest tests/history/test_prompt_cancelled.py tests/ace/tui/test_agent_launch_vcs.py tests/ace/tui/test_prompt_bar_submit_no_cancel_save.py
```

## Phase 5: Audit Non-TUI Launch Surfaces And Finalize

Owner: fifth implementation agent.

Scope:

- Apply the same failed-launch history rule to non-TUI launch entry points where prompts can fail after submit:
  - `src/sase/agent/launch_cwd.py` single-agent, multi-prompt, repeat, and alt/fan-out paths,
  - mobile/chat launch paths that call `launch_agents_from_cwd()` or equivalent helpers,
  - foreground `sase run` paths if they launch agents and can fail after a history write.
- Use the same failed-launch helper from Phase 4 so behavior is consistent across surfaces.
- Search for remaining references to removed prompt-history sorting and typed-dot TUI behavior:
  - `current_branch`, `current_workspace`, `sort_by`, `display_context`, `* = current branch`, `same workspace`, `.`
    history shortcut, `.x` shortcut, and "ranked by relevance to current CL".
- Remove now-unused imports, helper functions, tests, and docs.
- Run the repo-required verification after code changes.

Key files:

- `src/sase/agent/launch_cwd.py`
- `src/sase/integrations/_mobile_agent_launch.py`
- `src/sase/main/query_handler/_query.py`
- `src/sase/main/query_handler/special_cases.py`
- `docs/ace.md`
- `docs/blog/posts/prompt-widget-and-nvim.md`
- relevant `tests/test_cd_launch_from_cwd*.py`
- relevant mobile/helper tests

Acceptance:

- Failed launches from TUI and non-TUI surfaces record cancelled prompt history consistently.
- No code, test, or doc reference claims prompt history is sorted or prioritized by branch/workspace/project/VCS
  workflow.
- No TUI prompt input path uses typed `.` or `.x` as a prompt-history command.
- The final workspace passes the standard check.

Suggested verification:

```bash
just install
just check
```

## Cross-Phase Notes

- If a phase changes prompt-history file writes, preserve the existing sidecar lock and atomic `os.replace()` behavior.
- If a phase touches TUI launch paths, keep blocking file I/O and spawn preparation off the Textual event loop.
- Be careful with `PromptEntry` backward compatibility. The live history file may contain legacy context fields; old
  entries should not disappear simply because those fields are no longer part of the product behavior.
- Prefer a small dedicated failed-launch history API over scattered direct
  `add_or_update_prompt(..., cancelled=True, allow_short=True, force=...)` calls. This keeps the new exception to
  short-prompt filtering auditable.
- Update tests before or with each behavior change. Several existing tests intentionally encode the old behavior and
  should be rewritten, not preserved with compatibility shims that keep the old product behavior alive.
