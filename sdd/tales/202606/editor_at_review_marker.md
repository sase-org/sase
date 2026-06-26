---
create_time: 2026-06-25 21:29:52
status: done
prompt: sdd/prompts/202606/editor_at_review_marker.md
---
# Plan: Replace `%edit` with editor ` @` review marker

## Goal

Remove the `%edit` / `%e` directive as a user-facing prompt directive. Preserve the existing editor-return behavior with
a new editor-only marker:

- When text returned from the user's external editor has any line ending in the exact suffix ` @`, strip that suffix
  from every matching line.
- If at least one marker was stripped, load the edited prompt back into the ACE prompt input widget for review instead
  of launching immediately.
- When the edited text is xprompt markdown with prompt-level frontmatter and top-level `---` multi-agent separators,
  reload through the existing xprompt-markdown stack path so frontmatter, local xprompts, and multiple prompt panes are
  preserved.

This is intentionally an editor-return syntax, not a runtime directive. Typing ` @` directly in the prompt input bar and
submitting should not get special behavior.

## Current State

The old `%edit` behavior is split across three concerns:

1. TUI editor-return control flow:
   - `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_mount.py::has_edit_directive`
   - `_select_and_open_editor_for_home`
   - `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_requests.py`
   - `src/sase/ace/tui/actions/agent_workflow/_entry_prompt_history.py`
2. Runtime directive parsing and ACE completion:
   - `src/sase/xprompt/_directive_types.py`
   - `src/sase/xprompt/directives.py`
   - `src/sase/ace/tui/widgets/directive_completion.py`
3. Editor/LSP directive metadata in the sibling Rust workspace:
   - `/home/bryan/.local/state/sase/workspaces/sase-org/sase-core/sase-core_12/crates/sase_core/src/editor/directive.rs`

The good news is that xprompt/frontmatter reload semantics already exist:

- `PromptInputBar(initial_xprompt_markdown=...)`
- `PromptInputBar.load_stack_from_xprompt_markdown(...)`
- `PromptStackState.from_text(...)`

Those paths already lift leading frontmatter into stack state and split real top-level `---` body separators into prompt
panes.

## Design

### 1. Add a pure editor-marker helper

Replace `has_edit_directive(prompt) -> tuple[bool, str]` with a helper named along the lines of
`strip_editor_review_markers(prompt) -> tuple[bool, str]`.

Semantics:

- Scan all returned editor lines.
- A line matches only when the content before its newline ends with the exact two-character suffix ` @`.
- Strip exactly those two characters from every matching line.
- Preserve other characters, all non-matching lines, line order, and newline style.
- Return `(True, cleaned_text)` if at least one line matched, else `(False, original_text)`.

Important edge cases:

- `Fix auth @` becomes `Fix auth`.
- `Fix auth @\n---\nFix API @` becomes `Fix auth\n---\nFix API`.
- `Fix auth @ ` does not match because the line does not end in ` @`.
- `Fix auth  @` matches and leaves one trailing space before the marker's space.
- Markers inside frontmatter or code blocks still count because the requested rule says any editor-returned line. This
  is different from `%` directive parsing and is intentionally simpler.

Do the strip before xprompt-markdown loading so a marked separator such as `--- @` becomes a real `---` separator before
stack parsing.

### 2. Rewire editor-return call sites

Use the new helper only on text returned from the external editor:

- `_select_and_open_editor_for_home`
  - marker present: `_show_prompt_input_bar_for_home(..., initial_text=cleaned, as_xprompt_markdown=True)`
  - marker absent: `_finish_agent_launch(prompt)`
- `on_prompt_input_bar_editor_requested`
  - stacked defensive branch: update only the active pane with cleaned text when marked, matching today's `%edit`
    stripping behavior for that defensive path.
  - single-pane branch: marker present reloads the mounted bar via `_load_editor_markdown_into_bar(cleaned)`; marker
    absent launches.
- `on_prompt_input_bar_all_editor_requested`
  - whole-stack editor already reloads without launching. Strip markers if present, then call
    `load_stack_from_xprompt_markdown(...)`.
- prompt-history edit paths in `_prompt_bar_requests.py` and `_entry_prompt_history.py`
  - marker present reloads the prompt bar for review with xprompt-markdown semantics.
  - marker absent launches edited text as today.

Do not add marker handling to normal prompt submit, history LOAD, paste, stash restore, or runtime preprocessing.

### 3. Remove `%edit` as a directive surface

Python parser and completion:

- Remove `edit` from `_KNOWN_DIRECTIVES`.
- Remove `PromptDirectives.edit`.
- Stop constructing `edit=...` in `extract_prompt_directives`.
- Remove `%edit` metadata from ACE directive completion.
- Update `%e` completion behavior so `%e` narrows to `%effort` only.

Migration handling:

- Prefer a targeted directive migration error for old `%edit` and `%e` when they reach `extract_prompt_directives`, with
  a message like: "The `%edit` directive has been removed; from an editor, put ` @` at the end of any line to reload the
  prompt for review."
- This avoids silently launching old editor buffers that still start with `%edit`.
- Keep this as parser-only migration handling, not as behavior support in TUI editor-return code.

Rust editor/LSP parity:

- Remove `edit` from the Rust `DIRECTIVES` table.
- Remove `e -> edit` alias resolution.
- Update comments and tests so `%effort` is the only `%e...` completion surface.
- Confirm Rust launch canonicalization still treats removed `%edit` as non-special or emits the intended diagnostics
  based on existing Rust behavior.

### 4. Documentation updates

Update docs that advertise `%edit`:

- `docs/xprompt.md`: remove `%edit` from the directive table and directive examples; replace the `%edit` section with
  the editor-only ` @` marker rule or move that explanation to ACE docs.
- `docs/ace.md`: document the external-editor review marker and the fact that marker-triggered reloads preserve prompt
  frontmatter and multi-agent panes.
- `docs/blog/posts/prompt-widget-and-nvim.md` and `docs/blog/posts/why-coding-agents-need-orchestration.md`: remove or
  update references that present `%edit` as current syntax.

Avoid changing historical SDD/research files unless the project convention requires it; those are records of prior plans
and research.

## Tests

Python unit tests:

- Add focused tests for the new marker helper:
  - no marker returns `(False, original)`;
  - one marker strips and returns `True`;
  - multiple marked lines strip all markers;
  - trailing spaces after `@` do not match;
  - newline style and final newline are preserved;
  - `--- @` becomes `---` before xprompt markdown parsing.

TUI editor-return tests:

- Update `tests/ace/tui/test_prompt_bar_editor_stack.py`:
  - stacked single-pane editor return strips ` @` into the active pane;
  - single-pane marked editor return reloads the whole bar instead of launching;
  - marked multi-agent markdown with leading frontmatter reloads through xprompt markdown and does not launch;
  - whole-stack editor strips markers before reload.
- Update `tests/ace/tui/test_entry_points_vcs_prefix_editor_reload.py` and
  `tests/ace/tui/test_entry_points_vcs_prefix_prompt_history.py` to use the ` @` marker in editor-return fixtures and
  keep the existing frontmatter/xprompt assertions.
- Keep `tests/ace/tui/widgets/test_prompt_input_bar_stack_xprompt_markdown.py` focused on the existing markdown loader,
  with wording updated away from `%edit`.

Directive and completion tests:

- Update `tests/test_directives_flags.py` and `tests/test_directives_effort.py` so `%edit` / `%e` no longer set
  `directives.edit`.
- Add or update tests for the migration error if that path is implemented.
- Update `tests/ace/tui/widgets/test_directive_completion_candidates.py` and
  `tests/ace/tui/widgets/test_directive_completion_interactions.py` so `%edit` is absent and `%e` resolves toward
  `%effort`.

Rust tests:

- Update `crates/sase_core/src/editor/directive.rs` tests in the sibling `sase-core_12` workspace:
  - `edit` is not in directive metadata;
  - `canonical_directive_name("e")` is `None`;
  - `%e` completion returns `%effort` behavior only.

## Validation

Run targeted Python tests first:

```bash
pytest \
  tests/test_directives_flags.py \
  tests/test_directives_effort.py \
  tests/ace/tui/test_prompt_bar_editor_stack.py \
  tests/ace/tui/test_entry_points_vcs_prefix_editor_reload.py \
  tests/ace/tui/test_entry_points_vcs_prefix_prompt_history.py \
  tests/ace/tui/widgets/test_prompt_input_bar_stack_xprompt_markdown.py \
  tests/ace/tui/widgets/test_directive_completion_candidates.py \
  tests/ace/tui/widgets/test_directive_completion_interactions.py
```

Run Rust/editor tests in the sibling core workspace:

```bash
cargo test -p sase_core editor::directive
```

Then run the repo-level check if the targeted tests pass:

```bash
just check
```

## Risks and Decisions

- The ` @` marker is intentionally broad within editor-return text. If a user has a literal code or prose line ending in
  ` @`, it will be stripped and trigger review. That matches the "any line" requirement and keeps the feature simple and
  predictable.
- The marker is not parsed in runtime prompts, which prevents a new hidden launch directive from leaking into CLI,
  mobile, or workflow execution.
- Whole-stack editor sessions should keep reloading even without a marker. The marker only strips text there; it does
  not change that all-stack editor sessions are review sessions by definition.
- Removing `%e` frees the `%e...` prefix for `%effort` completion, but does not create a `%e` alias for `%effort`.
- The sibling `sase-core` change is necessary for nvim/LSP completion parity. Without it, Python ACE would stop
  advertising `%edit` while editor integrations still suggested it.
