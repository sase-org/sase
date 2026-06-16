---
create_time: 2026-06-15 17:35:51
status: done
prompt: sdd/prompts/202606/multi_agent_prompt_stack.md
bead_id: sase-4p
tier: epic
---
# Multi-Agent Prompt Stack Plan

## Problem

ACE already supports multi-agent prompts at launch time: user-authored `---` separator lines and markdown multi-agent
xprompts are parsed into multiple launch segments, with the canonical separator rules implemented behind
`plan_agent_launch_fanout`. The prompt input widget still presents that workflow as one text box, which makes live
composition hard: users cannot see, reorder, submit, or cancel one agent prompt at a time.

This feature should make multi-agent composition feel native in the TUI:

- `---` separator lines become visible stacked prompt widgets.
- The currently editable prompt remains at the bottom by default.
- `,j` / `,k` navigate prompt widgets.
- `,J` / `,K` reorder prompt widgets.
- `<enter>` submits only the selected prompt widget and removes it from the stack.
- `<shift+enter>` submits the whole stack as one multi-agent prompt using the same rules as markdown multi-agent
  xprompts and user multi-prompts.
- Normal-mode `-` or typing `---` in insert mode adds a new bottom prompt widget and pushes the previous widget up.
- `<ctrl+c>` cancels only the selected widget, records it as cancelled history, and removes it.

## Current Shape

- `src/sase/ace/tui/widgets/prompt_input_bar.py` is a single bottom-docked `Static` containing one `PromptTextArea`.
- `PromptTextArea` owns insert/normal/visual key handling and posts `PromptInputBar.Submitted` or
  `PromptInputBar.Cancelled`.
- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_submit.py` treats a submitted prompt as a whole-bar event.
- `src/sase/ace/tui/actions/agent_workflow/_launch_start.py` immediately unmounts the prompt bar after successful
  submit, then dispatches launch work through tracked tasks.
- `src/sase/ace/tui/actions/agent_workflow/_launch_body.py` already parses user prompts, expands multi-agent xprompts,
  writes prompt history, and routes multi-prompt launches through `_launch_multi_prompt_agents`.
- `src/sase/history/prompt_store.py` already records cancelled prompts and records manual multi-prompts as combined
  prompt plus reusable segments. Recent multi-agent xprompt history work preserves the original user-submitted xprompt
  invocation rather than generated child prompts.
- The canonical `---` split is Rust-backed via `sase.core.agent_launch_facade.plan_agent_launch_fanout`, which handles
  frontmatter and fenced code blocks.

## Design Principles

1. Keep launch semantics centralized.
   - The stack UI should produce text that the existing launch path can parse, not launch agents itself.
   - Whole-stack submit should join non-empty stack entries with `\n---\n` and pass that text through
     `_finish_agent_launch`.
   - Single-widget submit should pass only that widget's prompt through `_finish_agent_launch`.

2. Model the prompt stack explicitly.
   - Add a small state model for prompt items: stable id, text, cursor, mode, selection/focus state, and optional
     last-known height.
   - Do not infer stack state by scraping the DOM except at controlled synchronization points.
   - Preserve order as top-to-bottom launch order, with the active/newest editable item at the bottom unless the user
     intentionally navigates elsewhere.

3. Use the canonical separator parser for conversion.
   - Initial text from history/editor/xprompt insertion that contains real separators should be split using the same
     `plan_agent_launch_fanout(..., launch_kind="multi_prompt")` behavior used by dispatch.
   - A typed `---` line in insert mode should be recognized only when it is a separator line outside fenced code blocks.
     The simplest reliable implementation is to re-parse the current widget text with the canonical parser after a text
     change that introduces a possible separator, then replace the current item with parsed segments.

4. Keep the TUI responsive.
   - Stack navigation, split, reorder, and remove are in-memory Textual mutations only.
   - No synchronous disk I/O in key handlers. Cancel-history writes for a single widget should either reuse the existing
     fast cancellation path in a way that remains off the hot path, or be pushed through `asyncio.to_thread` / existing
     tracked task conventions if measurement shows it can block.
   - UI mutations should happen before launch/cancel persistence, matching existing prompt unmount and launch patterns.

5. Make it beautiful without adding visual noise.
   - Use a single bottom-docked `PromptInputBar` containing a vertical stack of compact prompt panes.
   - Active pane: accent border/title, full subtitle with available commands.
   - Inactive panes: dimmer border/title, compact height, still showing enough wrapped content to understand the prompt.
   - Separator rows should be quiet, centered, and structural: for example a dim line with an `agent N` / `agent N+1`
     cue rather than a literal noisy `---` block.
   - Avoid nested-card styling; panes are the repeated framed items, while the bar itself remains the docked tool.

## Phase 1: Stack Data Model And Canonical Split/Join

Goal: add the non-visual state layer and helpers that make all later UI behavior deterministic.

Work:

- Add prompt-stack model/helpers near the prompt widgets, likely a new module such as
  `src/sase/ace/tui/widgets/prompt_stack.py`.
- Define `PromptStackItem` and `PromptStackState` operations:
  - create from plain text
  - split text into items using canonical multi-prompt parsing
  - join items into a multi-prompt string with `\n---\n`
  - insert below/at bottom
  - remove selected
  - move selected up/down
  - clamp selection after mutations
- Preserve empty bottom input behavior:
  - A one-item stack may be empty while the user is drafting.
  - Whole-stack submit should ignore empty items except when that would make the prompt empty.
  - Single-widget submit of an empty selected item should remove it when other items remain; otherwise behave like the
    current "Empty prompt - cancelled" path.
- Add focused unit tests for:
  - split/join parity with fenced `---`
  - frontmatter handling
  - empty segment dropping
  - add/remove/reorder selection clamping
  - bottom item remains the default active item after splitting initial text.

Deliverable:

- Pure model/helpers and tests. No visible TUI behavior change yet.

## Phase 2: Render A Beautiful Stack In `PromptInputBar`

Goal: convert `PromptInputBar` from one `PromptTextArea` to a stack-capable container while preserving existing single
prompt behavior.

Work:

- Update `PromptInputBar.compose()` to render a vertical stack of prompt panes.
- Keep one `PromptTextArea` per stack item so each item can retain cursor, undo state, completions, and vim mode.
- Use stable child ids/classes instead of repeated `#prompt-input`; add helper methods like:
  - `active_text_area()`
  - `active_text()`
  - `all_prompt_texts()`
  - `load_stack_from_text(text)`
  - `focus_item(index)`
- Keep completion panels scoped to the active pane. Only the focused pane should show file/xprompt completions and soft
  completion subtitles.
- Rework height calculation so total stack height is capped by terminal height, with active pane growing most and
  inactive panes compacting first.
- Update `_load_prompt_into_bar`, history-load, editor-return, snippet insertion, and workflow-editor paths to target
  the active pane or replace the whole stack deliberately.
- Add TCSS for:
  - stack container
  - active/inactive prompt pane
  - separator row
  - compact inactive pane title/subtitle.
- Add widget-level tests for initial multi-prompt rendering and height behavior.

Deliverable:

- Existing single prompt tests still pass.
- Initial text containing separator lines renders as stacked panes.
- No submission behavior change yet except helper APIs are stack-aware.

## Phase 3: Stack Keymaps And Live Splitting

Goal: make the stack ergonomic while staying compatible with the existing vim prompt editor.

Work:

- Add prompt-stack normal-mode key handling:
  - `,j`: focus next/lower prompt pane.
  - `,k`: focus previous/upper prompt pane.
  - `,J`: move active pane down.
  - `,K`: move active pane up.
  - `-`: add a new bottom pane and focus it, pushing the current prompt up visually when it was the bottom item.
- Treat these as prompt-local key sequences, not app leader mode. The app-level comma leader should remain inactive
  while `PromptTextArea` has focus.
- Decide whether to keep these hard-coded with the current prompt vim key layer or introduce a prompt-keymap config
  section. If a configurable prompt keymap section is added, update `src/sase/default_config.yml`, keymap types, help,
  and keymap tests in the same phase.
- Implement insert-mode typed separator handling:
  - Detect a text change that can create a separator line.
  - Re-parse that pane's text with the Phase 1 helper.
  - Replace the current pane with the resulting panes, preserving prefix/suffix text as parsed segments.
  - Focus the bottom/new pane after split.
  - Do not split `---` inside fenced code blocks or YAML frontmatter delimiters.
- Clear active completion/soft-completion state before stack navigation or structural mutation.
- Add tests for all keymaps, including collision behavior with vim comma repeat/search behavior and normal `J` line
  join.

Deliverable:

- Users can navigate, reorder, add, and split prompt panes without launching agents.

## Phase 4: Submit And Cancel Semantics

Goal: wire stack-aware actions into existing launch/history behavior.

Work:

- Extend `PromptInputBar.Submitted` to distinguish:
  - single selected item submit
  - whole-stack multi-prompt submit
  - mode (`prompt`, `feedback`, `approve_prompt`) remains respected.
- Keep feedback and approve-prompt modes single-pane unless there is a strong reason to support stacks there. They are
  not multi-agent prompt composition surfaces.
- `<enter>` in prompt mode:
  - submit only the selected pane text through `_finish_agent_launch`.
  - remove that pane from the stack immediately.
  - if other panes remain, do not unmount the prompt bar; regenerate prompt context for the remaining launches as needed
    before each later submit.
  - if no panes remain, unmount after submit as today.
- `<shift+enter>` in prompt mode:
  - join non-empty stack items with `\n---\n`.
  - submit through `_finish_agent_launch` as one prompt so existing multi-prompt and multi-agent xprompt rules apply.
  - unmount the full prompt bar after submit, as today.
  - Verify what Textual receives for shift-enter in supported terminals. If it is not portable, add an explicit fallback
    binding and document the practical key in the prompt subtitle.
- `<ctrl+c>`:
  - cancel only the active pane.
  - record that pane text as cancelled prompt history, including file-reference history if applicable.
  - remove the pane and focus the nearest remaining pane.
  - unmount only when the last pane is cancelled.
- Be careful with `_prompt_context`:
  - Current launch code clears `_prompt_context` after one submit. Single-pane submit from a remaining stack needs a
    fresh snapshot or a retained base context so subsequent pane submissions still have valid launch context.
  - Prefer storing an immutable base prompt context for the mounted stack and cloning/regenerating timestamp/workflow
    name per submit.
- Add tests around the existing submit-unmount regression:
  - single selected submit does not save that selected prompt as cancelled
  - remaining stack panes are not saved as cancelled on successful single submit
  - final pane submit unmounts through the submit path
  - ctrl-c saves only the selected pane as cancelled
  - shift-enter saves/launches the joined prompt.

Deliverable:

- Stack submit/cancel behavior matches the requested product semantics and preserves history contracts.

## Phase 5: Launch Integration, History, And Edge Cases

Goal: harden interaction with existing multi-prompt, multi-agent xprompt, history, and VCS behavior.

Work:

- Ensure whole-stack submit preserves existing launch behavior:
  - manual multi-prompt stack should save combined prompt plus reusable segments, as documented.
  - stack containing `#!multi_agent_xprompt` should preserve the submitted invocation in history and not save generated
    child prompts.
  - per-segment VCS refs, `%wait`, `%name`, `%model`, `%alt`, `%repeat`, and local prompt frontmatter should continue to
    flow through existing launch code.
- Decide how frontmatter displays in the stack:
  - Recommended: keep prompt-level YAML frontmatter attached above the first pane and not reorder it as an agent pane.
  - If this is too large for this feature, split only body segments and preserve frontmatter in the joined whole-stack
    submit; single-pane submit with prompt-level frontmatter should be clearly handled or disallowed with a warning.
- Update prompt history load behavior:
  - Loading a manual multi-prompt history entry should split into stack panes.
  - Loading a single cancelled prompt should stay single-pane.
  - Loading a multi-agent xprompt invocation should stay as the authored invocation unless it literally contains
    separator lines.
- Update editor behavior:
  - Opening editor from a stack should either edit the active pane or edit the whole stack; choose one and make the
    title/subtitle explicit.
  - Recommended: `^G` edits the active pane, while whole-stack editing can remain future work unless an existing command
    naturally maps to it.
- Add integration tests using existing launch harnesses to verify:
  - enter launches one selected pane and keeps the stack mounted
  - shift-enter routes to `_launch_multi_prompt_agents`
  - single submissions can be repeated until the stack is empty
  - failures record only the submitted text as failed/cancelled.

Deliverable:

- The stack works with real launch paths and history, not just widget state.

## Phase 6: Visual Polish, Help, And Performance Validation

Goal: make the feature feel finished and protect responsiveness.

Work:

- Add or update help/subtitle text for prompt mode:
  - active pane command hints should mention `,j`, `,k`, `,J`, `,K`, `-`, `<enter>`, and whole-stack submit.
  - Keep the subtitle short; prefer rotating/compact labels over a long crowded footer.
- Add PNG visual snapshots for:
  - two-prompt stack at 120x40
  - active upper vs active lower pane
  - narrow terminal with compact inactive panes
  - completion panel inside active pane.
- Run focused prompt widget tests, history tests, multi-prompt launch tests, and visual tests.
- Run `SASE_TUI_PERF=1 sase ace` or the relevant bench if structural updates touch hot paths; stack operations should
  not affect normal j/k navigation when the prompt bar is absent.
- Run `just install` if needed, then `just check` before completion, per project instructions.

Deliverable:

- Feature-complete UI with regression and visual coverage.

## Risks And Decisions For Implementers

- `<shift+enter>` portability is the main unknown. Test Textual's actual key event before hard-coding assumptions.
- Single-pane submit while keeping the stack mounted requires careful prompt-context lifecycle work; do this before
  polishing visuals.
- Reusing one `PromptTextArea` class for every pane is safest for completion/vim behavior, but multiple instances make
  ids and event routing important.
- Avoid synchronous history writes in key handlers if profiling shows they block; the TUI performance rule is no
  blocking disk I/O on the event loop.
- Do not treat feedback or approve-prompt modes as multi-agent stacks unless a later product decision asks for that.

## Suggested Phase Ownership

Each phase is intended to be implementable by a distinct agent instance:

1. Model and split/join helpers.
2. Stack rendering and height/styling.
3. Navigation/reorder/add/live-split keymaps.
4. Submit/cancel semantics and prompt context lifecycle.
5. Launch/history integration edge cases.
6. Visual polish, docs/help, and performance validation.
