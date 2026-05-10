---
create_time: 2026-03-21 17:53:35
status: done
bead_id: sase-7
prompt: sdd/prompts/202603/mentor_redesign.md
---

# Mentor Redesign - Implementation Plan

## Overview

Major redesign of the sase mentor system: replace free-form proposal-based mentors with structured JSON output, add a
Mentor Review popup to the TUI, introduce rubric-driven config, and support partial approval with a single apply agent.

---

## Phase 1: Config Schema & XPrompt Tag Foundation

**Goal**: Establish the new `mentor_profiles` config format, add new xprompt tags with priority-based enforcement, and
define the JSON output schema for mentor comments.

### 1a. Add new xprompt tags: `mentor`, `commit`, `make_mentor_changes`

- **`src/sase/xprompt/tags.py`**: Add `mentor`, `commit`, and `make_mentor_changes` to `XPromptTag` enum.
- **`src/sase/xprompt/tags.py`**: Update `get_by_tag()` to enforce the "one and only one" constraint: if multiple
  xprompts share the same tag AND the same priority, raise an error. If priorities differ, return the highest-priority
  one (first-wins, which the existing loader order already provides). Add a new helper `get_by_tag_strict(tag, project)`
  that performs this validation.
- **`src/sase/xprompt/loader.py`**: Verify that the existing priority ordering (local > user > plugin > builtin)
  naturally handles the "higher priority wins" rule. No changes expected here.

### 1b. Redesign `mentor_profiles` config schema

Replace the current `MentorConfig` (which has `mentor_name` + `prompt`) with a rubric-based schema.

- **`src/sase/config/mentor.py`**: Redesign dataclasses:

  ```python
  @dataclass
  class MentorFocusArea:
      focus_name: str        # e.g., "comments", "shared_code", "visibility"
      description: str       # Review focus description passed to #mentor prompt

  @dataclass
  class MentorConfig:
      mentor_name: str
      role: str              # e.g., "code quality expert", "test coverage specialist"
      focus_areas: list[MentorFocusArea]

  @dataclass
  class MentorProfileConfig:
      profile_name: str
      mentors: list[MentorConfig]
      file_globs: list[str] | None = None
      diff_regexes: list[str] | None = None
      amend_note_regexes: list[str] | None = None
      first_commit: bool = False
  ```

- **`src/sase/config/mentor.py`**: Update `_load_mentor_profiles()` to parse the new schema. The new YAML format:

  ```yaml
  mentor_profiles:
    - profile_name: code
      mentors:
        - mentor_name: code_quality
          role: "senior code quality reviewer"
          focus_areas:
            - focus_name: comments
              description: "Ensure all public APIs have clear doc comments..."
            - focus_name: shared_code
              description: "Identify duplicated code across files..."
            - focus_name: visibility
              description: "Check visibility modifiers are appropriate..."
      file_globs:
        - "**/*.java"
        - "**/*.dart"
  ```

### 1c. Define mentor comment JSON output schema

- **`src/sase/ace/mentor_output.py`** (new file): Define the JSON schema and dataclasses for mentor output:

  ```python
  @dataclass
  class MentorComment:
      focus_name: str         # Which focus area this comment addresses
      file_path: str          # File the comment is about
      line_number: int        # Line reference in the file
      description: str        # High-level description of the proposed change
      severity: str           # "error" | "warning" | "suggestion"

  @dataclass
  class MentorOutput:
      mentor_name: str
      profile_name: str
      role: str
      comments: list[MentorComment]

  MENTOR_OUTPUT_JSON_SCHEMA: dict  # JSON Schema dict for use with #json workflow
  ```

- This schema will be embedded in the `#mentor` xprompt via the `#json` workflow to enforce structured output.

### 1d. Mentor comment storage and retrieval

- **`src/sase/ace/mentor_output.py`**: Add functions for persisting/loading mentor JSON output:
  - `save_mentor_output(cl_name, profile_name, mentor_name, timestamp, output: MentorOutput) -> Path`
    - Saves to `~/.sase/mentors/<cl_name>-<profile>-<mentor>-<timestamp>.json`
  - `load_mentor_output(path: Path) -> MentorOutput`
  - `load_all_mentor_outputs(cl_name) -> list[tuple[Path, MentorOutput]]`
  - `load_mentor_outputs_for_commit(cl_name, entry_id) -> list[tuple[Path, MentorOutput]]`
    - Uses the timestamp from MentorStatusLine to match outputs to commits.

### 1e. Acceptance state persistence

- **`src/sase/ace/mentor_output.py`**: Add acceptance state tracking:
  - `MentorAcceptanceState` dataclass mapping `(profile_name, mentor_name, comment_index)` → `bool`
  - `save_acceptance_state(cl_name, entry_id, state: MentorAcceptanceState) -> Path`
    - Saves to `~/.sase/mentors/<cl_name>-<entry_id>-acceptance.json`
  - `load_acceptance_state(cl_name, entry_id) -> MentorAcceptanceState`
  - Acceptance state references mentor outputs by `(profile_name, mentor_name, comment_index)` so it survives across
    popup sessions.

### Tests

- Unit tests for new tag validation and `get_by_tag_strict` enforcement.
- Unit tests for config parsing (new schema, validation errors for missing fields).
- Unit tests for JSON schema validation, save/load round-trips, acceptance state persistence.

---

## Phase 2: Mentor Execution Overhaul

**Goal**: Rewrite the mentor execution pipeline to use the new config, produce structured JSON output via `#json`, and
remove workspace claiming for mentor agents.

### 2a. Create `#mentor` xprompt workflow (YAML)

- **`src/sase/xprompts/mentor.yml`** (new file): Replace the plugin-provided `mentor.md` with a built-in YAML workflow
  tagged `mentor`:

  ```yaml
  tags: mentor
  input:
    role: text
    focus_areas_json: text # JSON array of {focus_name, description} pairs
    cl_name: { type: word, default: "null" }
    vcs_type: { type: word, default: "hg" }
  steps:
    - name: render_focus_areas
      hidden: true
      python: |
        import json
        areas = json.loads("{{ focus_areas_json }}")
        formatted = "\n".join(
            f"### {a['focus_name']}\n{a['description']}" for a in areas
        )
        output = {"rendered_focus_areas": formatted}
      output: { rendered_focus_areas: text }
    - name: review
      prompt_part: |
        %model:#pro
        {% if cl_name != "null" %}#{{ vcs_type }}:{{ cl_name }}

        {% endif %}### Role

        You are a {{ role }}.

        You will review a CL and provide structured feedback on specific focus areas.
        You must NOT make any file changes. Instead, produce structured JSON output
        describing any issues you find.

        IMPORTANT:
        - DO NOT make any changes outside the scope of the focus areas below.
        - Do NOT comment on code that was not modified / added by this CL.
        - Every comment MUST be actionable: include the file path, line number, and
          a clear description of what should be changed.
        - If you find no issues for a focus area, omit it from your output.

        ### Focus Areas

        {{ rendered_focus_areas }}

        #json:`{{ schema }}`
  ```

  The `schema` variable will be set by the `MentorWorkflow` to the `MENTOR_OUTPUT_JSON_SCHEMA` defined in Phase 1.

  **Note**: The `#json` workflow (tagged `rollover`) handles JSON schema enforcement and validation. It injects output
  format instructions and validates the agent's response against the schema in post-steps.

### 2b. Update `MentorWorkflow` to use new config and `#mentor` tag

- **`src/sase/workflows/mentor.py`**: Major refactor:
  - Instead of using `mentor.prompt` directly, resolve the `#mentor` xprompt via `get_by_tag_strict(XPromptTag.mentor)`.
  - Serialize the mentor's `role` and `focus_areas` into the xprompt's inputs.
  - Serialize `MENTOR_OUTPUT_JSON_SCHEMA` and pass it as the `schema` input.
  - Remove the `_build_mentor_prompt()` function (replaced by xprompt workflow invocation).
  - Remove `#propose` expansion logic — mentors no longer create proposals.
  - Remove workspace claiming for mentor agents (they only read code, no writes).
  - Parse the JSON response and save via `save_mentor_output()`.

### 2c. Update mentor status model

- **`src/sase/ace/changespec/models.py`**: Add `"COMMENTED"` as a valid mentor status (alongside RUNNING, PASSED,
  FAILED, KILLED).
- **`src/sase/ace/mentors.py`**: Update `set_mentor_status()` to use `COMMENTED` when a mentor produces one or more
  comments, `PASSED` when it produces zero comments.
- **FAILED status**: When a mentor fails or produces invalid JSON, mark as `FAILED` and include the log file path in the
  suffix field. Update suffix formatting to show the log path.
- **`src/sase/axe/mentor_runner.py`**: Update the background runner to:
  - Parse JSON output and determine COMMENTED vs PASSED.
  - On failure/invalid JSON, set FAILED with log file path.
  - Save structured output to disk via `save_mentor_output()`.

### 2d. Update mentor display

- **`src/sase/ace/tui/widgets/mentors_builder.py`**: Update display to show COMMENTED status with appropriate styling.
- **`src/sase/ace/display.py`**: Update CLI Rich styling for COMMENTED status.
- **`home/dot_config/nvim/syntax/saseproject.vim`** (chezmoi): Add COMMENTED syntax highlighting.

### Tests

- Unit tests for `MentorWorkflow` with new config format.
- Unit tests for COMMENTED/PASSED/FAILED status transitions.
- Integration test: run mentor workflow with mock agent, verify JSON output is saved.

---

## Phase 3: Mentor Review Popup

**Goal**: Build the `,m` Mentor Review popup in the `sase ace` TUI with side panel (mentor list), main panel (comment
display), navigation, acceptance toggling, and running mentor killing.

### 3a. Add `,m` keymap

- **`src/sase/default_config.yml`**: Add `m` to the leader mode keys with description "review mentors".
- **`src/sase/ace/tui/keymaps/`**: Wire the `,m` binding to an `action_review_mentors` action.

### 3b. Create the Mentor Review modal

- **`src/sase/ace/tui/modals/mentor_review_modal.py`** (new file): Implement `MentorReviewModal(ModalScreen)`:

  **Layout** (takes up most of the screen):

  ```
  ┌─ Mentor Review ─────────────────────────────────────────────┐
  │ ┌─ Mentors ──────┐ ┌─ Comment 2/5 ───────────────────────┐ │
  │ │ ▸ code_quality  │ │                                     │ │
  │ │   sound_tests   │ │  Focus: comments                    │ │
  │ │   aaa           │ │  Severity: warning                  │ │
  │ │ ● complete (R)  │ │                                     │ │
  │ │                 │ │  File: src/foo/bar.py:42             │ │
  │ │                 │ │                                     │ │
  │ │                 │ │  Add a docstring to the `process()`  │ │
  │ │                 │ │  method explaining the retry logic   │ │
  │ │                 │ │  and timeout behavior.               │ │
  │ │                 │ │                                     │ │
  │ │                 │ │                                     │ │
  │ │                 │ │  [✓ ACCEPTED]                        │ │
  │ └────────────────┘ └─────────────────────────────────────┘ │
  │ Accepted: 3/12  │  n/p: comments  j/k: mentors  ␣: toggle │
  │                 │  K: kill  <enter>: apply  q: close       │
  └─────────────────────────────────────────────────────────────┘
  ```

  **Side panel** (left):
  - Lists all mentors from the latest commit's MENTORS entry only.
  - Shows mentor name, status indicator (▸ selected, ● running, ✗ failed, ✓ all accepted).
  - Running/queued mentors shown with status suffix.
  - Navigate with `j`/`k`.

  **Main panel** (right):
  - Shows one comment at a time from the selected mentor.
  - Header: "Comment N/M" with focus area and severity.
  - Body: file path + line number, description of proposed change.
  - Footer: acceptance state indicator `[✓ ACCEPTED]` or `[ ]`.
  - Navigate comments with `n` (next) / `p` (previous).
  - At boundary (last comment of mentor), `n` jumps to first comment of next mentor.

  **Bottom bar**:
  - Shows total accepted count: "Accepted: 3/12".
  - Shows available keybindings.

### 3c. Implement navigation and acceptance

- **Navigation**:
  - `j`/`k`: Move between mentors in the side panel. When switching mentors, show comment 1 of the new mentor.
  - `n`/`p`: Move between comments within a mentor. At boundary, wrap to next/previous mentor's comments.
  - `q`/`Escape`: Close the popup.

- **Acceptance toggling**:
  - `<space>`: Toggle acceptance of the current comment. Update the `[✓ ACCEPTED]`/`[ ]` indicator.
  - Persist acceptance state to disk immediately on toggle (via `save_acceptance_state()`).
  - Load acceptance state from disk when opening popup (via `load_acceptance_state()`).

- **Kill running mentors**:
  - `K` (shift-k): Kill the currently selected mentor if it's running. Reuse existing mentor killing logic from
    `_mentors.py` hint actions. Mark as KILLED in MENTORS field.

### 3d. Wire up the action

- **`src/sase/ace/tui/actions/`**: Add a new `MentorReviewMixin` or extend `ChangeSpecMixin` with
  `action_review_mentors()`:
  - Find the latest commit's MENTORS entry from the selected ChangeSpec.
  - Load all mentor outputs for that entry.
  - Load acceptance state.
  - Push `MentorReviewModal` with the data.

### 3e. Update keybinding footer and help modal

- **`src/sase/ace/tui/widgets/keybinding_footer.py`**: Add `,m` as conditional keymap (shown when MENTORS entry exists
  for latest commit with COMMENTED or FAILED status).
- **`src/sase/ace/tui/modals/help_modal.py`**: Add `,m` to the leader mode section.

### Tests

- Unit tests for modal navigation logic (j/k/n/p boundary wrapping).
- Unit tests for acceptance toggling and persistence.
- End-to-end test with `sase ace --agent`: verify `,m` opens popup, navigation works.

---

## Phase 4: Apply Agent & Integration

**Goal**: Implement the `#make_mentor_changes` xprompt, the `<enter>` apply flow from the popup, and `commit` tag
support.

### 4a. Create `#make_mentor_changes` xprompt

- **`src/sase/xprompts/make_mentor_changes.yml`** (new file): YAML workflow tagged `make_mentor_changes`:

  ```yaml
  tags: make_mentor_changes
  input:
    accepted_comments_json: text # JSON array of accepted MentorComment objects
    cl_name: word
    vcs_type: { type: word, default: "hg" }
  steps:
    - name: render_changes
      hidden: true
      python: |
        import json
        comments = json.loads("{{ accepted_comments_json }}")
        formatted = "\n\n".join(
            f"### Change {i+1}: {c['focus_name']} ({c['severity']})\n"
            f"**File**: `{c['file_path']}:{c['line_number']}`\n"
            f"{c['description']}"
            for i, c in enumerate(comments)
        )
        output = {"rendered_changes": formatted}
      output: { rendered_changes: text }
    - name: apply
      prompt_part: |
        #{{ vcs_type }}:{{ cl_name }}

        ### Task

        Apply the following code review changes to the codebase. Make each change as described,
        run any relevant tests, and commit your changes.

        {{ rendered_changes }}
  ```

  **`commit` tag support**: After rendering the apply prompt, check if an xprompt with the `commit` tag exists. If so,
  append ` #<xprompt_name>` to the prompt. This lets the user control what happens after changes are applied (e.g.,
  amend the CL, create a proposal, etc.).

### 4b. Implement `<enter>` apply flow in popup

- **`src/sase/ace/tui/modals/mentor_review_modal.py`**: Handle `<enter>` keypress:
  - Collect all accepted comments across all mentors.
  - If none accepted, show a brief notification and do nothing.
  - Serialize accepted comments to JSON.
  - Resolve the `#make_mentor_changes` xprompt via `get_by_tag_strict(XPromptTag.make_mentor_changes)`.
  - Dismiss the modal with a result containing the accepted comments and xprompt info.

- **`src/sase/ace/tui/actions/`**: Handle the modal result:
  - Launch the apply agent as a normal agent workflow (claims a workspace, visible on Agents tab).
  - Pass `accepted_comments_json`, `cl_name`, and `vcs_type` as inputs.
  - If a `commit`-tagged xprompt exists, append it to the prompt.

### 4c. Multi-round acceptance support

- After the apply agent completes, the user can open `,m` again for the same commit.
- Stale mentor outputs (from previous runs) are preserved on disk.
- The acceptance state can be modified again and another apply agent launched.
- Each apply agent run is independent (new workflow entry on Agents tab).

### Tests

- Unit tests for `#make_mentor_changes` prompt rendering.
- Unit tests for `commit` tag resolution and prompt appending.
- Integration test: mock accepted comments → verify apply agent prompt is correct.
- End-to-end: verify apply agent appears on Agents tab.

---

## Phase 5: Plugin Migration & Cleanup

**Goal**: Migrate the retired Mercurial plugin plugin to the new config format, remove old mentor xprompts, and clean up deprecated
code paths.

### 5a. Update retired Mercurial plugin `default_config.yml`

- **`../retired Mercurial plugin/src/retired_mercurial_plugin/default_config.yml`**: Rewrite `mentor_profiles` to use the new schema. Convert each
  `#mentor/<name>` xprompt's review instructions into `role` + `focus_areas` entries. Example conversion:

  Current:

  ```yaml
  - profile_name: code
    mentors:
      - prompt: "#mentor/code_quality"
      - prompt: "#mentor/sound_tests"
    file_globs: ["**/*.java", "**/*.dart"]
  ```

  New:

  ```yaml
  - profile_name: code
    mentors:
      - mentor_name: code_quality
        role: "senior code quality reviewer"
        focus_areas:
          - focus_name: comments
            description: "Ensure all public APIs have clear doc comments..."
          - focus_name: shared_code
            description: "Identify duplicated code across files..."
          - focus_name: symbol_names
            description: "Ensure all symbols have clear and descriptive names..."
          - focus_name: visibility
            description: "Check visibility modifiers are appropriate..."
      - mentor_name: sound_tests
        role: "test coverage specialist"
        focus_areas:
          - focus_name: test_coverage
            description: "Verify new logic has proper test coverage..."
          - focus_name: regression_tests
            description: "For bug fixes, ensure regression tests exist..."
    file_globs: ["**/*.java", "**/*.dart"]
  ```

### 5b. Remove old mentor xprompts from retired Mercurial plugin

- **Delete** `../retired Mercurial plugin/src/retired_mercurial_plugin/xprompts/mentor.md` — replaced by built-in `#mentor` workflow.
- **Remove** all `mentor/*` xprompt definitions from `../retired Mercurial plugin/src/retired_mercurial_plugin/default_config.yml` (the
  `mentor/aaa`, `mentor/code_quality`, `mentor/sound_tests`, etc. entries in the `xprompts` section).

### 5c. Remove `#propose` from mentor flow

- **`src/sase/workflows/mentor.py`**: Remove all `#propose` expansion and post-step execution logic (proposal_id
  extraction, etc.). Mentors no longer create proposals.
- **`src/sase/ace/changespec/models.py`**: The `suffix` field on `MentorStatusLine` no longer needs to hold
  `proposal_id` — verify the `entry_ref` suffix_type is no longer used for mentors (may still be used elsewhere).

### 5d. Clean up old `MentorConfig`

- **`src/sase/config/mentor.py`**: Remove the old `prompt` field from `MentorConfig`. The `_load_mentor_profiles()`
  parser should no longer accept the old format (or optionally, log a deprecation warning).
- **`src/sase/ace/tui/actions/hints/_mentors.py`**: Update mentor killing to work with new status model. The existing
  `,M` kill command should still work (or be replaced by `K` in the Mentor Review popup).

### 5e. Update `src/sase/default_config.yml`

- Update any mentor-related keymap documentation.
- Add `,m` to the leader mode keys documentation.

### Tests

- Verify `just check` passes across both sase and retired Mercurial plugin repos.
- End-to-end: run full mentor cycle (trigger → structured output → review popup → apply).
- Verify old config format is rejected with a clear error message.

---

## Key Design Decisions Summary

| Decision             | Choice                                                                       |
| -------------------- | ---------------------------------------------------------------------------- |
| Mentor output format | Structured JSON via `#json` workflow — no file changes by mentor agents      |
| Mentor status        | COMMENTED (has comments), PASSED (no issues), FAILED (error + log path)      |
| Side panel scope     | Latest commit only                                                           |
| Comment navigation   | `n`/`p` with cross-mentor boundary jumping                                   |
| Acceptance           | `<space>` toggles, persisted to disk, survives popup close                   |
| Apply mechanism      | Single `#make_mentor_changes` agent for all accepted comments across mentors |
| Workspace claiming   | Mentors: no workspace needed. Apply agent: claims workspace                  |
| Tag override         | Higher priority wins silently; same priority = error                         |
| Multi-round          | Supported — re-open popup, modify acceptances, launch new apply agent        |
| `commit` tag         | Appended to apply agent prompt when an xprompt with this tag exists          |
