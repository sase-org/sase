# TUI XPrompt Argument Completion And Hints

Date: 2026-05-07

## Question

What should the `sase ace` TUI equivalent of the mobile xprompt argument support look like, now that mobile has
structured xprompt insertion, type/name completion, and argument hints?

## Executive Summary

The TUI already has most of the primitives needed, but they are split across two UX paths:

- `Ctrl+T` in the prompt input bar completes xprompt names and inserts the canonical reference text, including `#!`
  where appropriate.
- The xprompt selection/browser modals show input argument names, but that information is not available in the inline
  prompt completion panel and does not react to cursor position inside `#foo:` or `#foo(...)`.

The best next step is to add a small pure xprompt argument assist layer under
`src/sase/ace/tui/widgets/`, then wire it into the existing prompt completion panel. That would give TUI parity with
mobile without inventing a second parser or another modal.

Recommended shape:

1. Keep `Ctrl+T` as the explicit completion trigger.
2. Enrich xprompt completion candidates with structured metadata: `name`, `insertion`, `kind`, `inputs`, and optionally
   `content_preview`.
3. When completing an xprompt name, display a compact detail pane or second line showing visible inputs and types.
4. When a selected xprompt with required inputs is accepted, keep the prompt text as the canonical insertion by default,
   but leave a hint panel active with edit actions such as `:` positional args and `()` named args.
5. Add an automatic cursor detector for exact trailing argument positions, starting with `#foo:` / `#!foo:` and later
   `#foo(arg=`.
6. Keep backend xprompt validation authoritative. The TUI should show hints and generate syntax, not validate full
   argument semantics beyond local, cheap feedback.

This should be local to the Python TUI and xprompt helper modules. There is no need to change the mobile gateway
contract for TUI support.

## Existing TUI Support

### Prompt Bar Completion

`PromptTextArea` owns the prompt editor and mixes in `FileCompletionMixin`
(`src/sase/ace/tui/widgets/prompt_text_area.py`, `src/sase/ace/tui/widgets/_file_completion.py`).

Current behavior:

- `Ctrl+T` triggers `_try_file_completion_tab()`.
- Token extraction comes from `extract_token_around_cursor()`.
- If the token starts with `#`, the completion kind becomes `xprompt`.
- `build_xprompt_completion_candidates()` loads `get_all_prompts()` and returns `CompletionCandidate` rows.
- The prompt input bar renders those rows in a shared `Static#prompt-completion` panel.

Important source points:

- `src/sase/ace/tui/widgets/xprompt_completion.py:23` builds xprompt candidates.
- `src/sase/ace/tui/widgets/xprompt_completion.py:36` supports `#!`-only filtering when the typed token starts with
  `#!`.
- `src/sase/ace/tui/widgets/xprompt_completion.py:47` uses `workflow_reference_insertion()`, so canonical insertion is
  already correct.
- `src/sase/ace/tui/widgets/_file_completion.py:239` chooses path vs xprompt completion.
- `src/sase/ace/tui/widgets/prompt_input_bar.py:175` renders the completion panel.

Gap: `CompletionCandidate` only carries `display`, `insertion`, `is_dir`, and `name`. The panel cannot show inputs,
types, requiredness, defaults, tags, kind, or preview without another lookup.

### XPrompt Selection And Browser Modals

The TUI also has modal xprompt browsing:

- `XPromptSelectModal` is triggered by the `#@` snippet flow.
- `XPromptBrowserModal` is the broader browse/manage surface.
- Both reuse `append_input_args()` from `xprompt_browser_helpers.py`.

`append_input_args()` filters out step inputs and renders user-facing inputs:

- Required inputs are bright.
- Optional inputs are dimmed.
- Optional defaults are shown when available.

Important source points:

- `src/sase/ace/tui/modals/xprompt_browser_helpers.py:22` renders input argument labels.
- `src/sase/ace/tui/modals/xprompt_select_modal.py:160` adds those labels to the select modal rows.
- `src/sase/ace/tui/modals/xprompt_select_modal.py:241` returns the suffix to insert after an existing `#`.

Gap: this support is modal-only. It helps when the user explicitly opens the selector, but not when they type or complete
inside the normal prompt bar.

## Mobile Work Now Available To Reuse

The mobile catalog projection now has exactly the structured metadata that the TUI needs:

- `StructuredCatalogInput`: `name`, `type`, `required`, `default_display`, `position`.
- `StructuredCatalogEntry`: `name`, `display_label`, `insertion`, `reference_prefix`, `kind`, `input_signature`,
  `inputs`, `content_preview`, and source metadata.

Important source points:

- `src/sase/xprompt/_catalog_models.py:43` defines `StructuredCatalogInput`.
- `src/sase/xprompt/_catalog_models.py:54` defines `StructuredCatalogEntry`.
- `src/sase/xprompt/_catalog_structured.py:144` builds canonical structured entries.
- `src/sase/xprompt/_catalog_structured.py:149` uses `workflow_reference_insertion()`.
- `src/sase/xprompt/_catalog_structured.py:164` filters visible inputs and derives requiredness from `UNSET`.
- `src/sase/xprompt/_catalog_structured.py:181` suppresses string defaults, matching the mobile sensitive-default
  guardrail.

The TUI can either call `build_structured_xprompts_catalog()` directly, or it can reuse the same projection functions
behind a TUI-specific helper. Calling the structured catalog directly has the advantage of matching mobile exactly.
Using a small adapter has the advantage of keeping prompt completion lightweight and avoiding PDF/catalog terminology
inside widget code.

## Parser Semantics To Mirror

The TUI should not invent a looser xprompt reference parser. The shared lexical parser already defines the important
rules:

- Valid leading context: start of text, whitespace, or one of `(`, `[`, `{`, `"`, `'`.
- Marker: `#` or `#!`.
- Names: slash namespaces are supported, and `__` aliases are normalized to `/`.
- HITL suffixes `!!` and `??` sit after the name and before arguments.
- Argument kinds include parentheses, colon, colon shorthand, double-colon shorthand, and plus syntax.

Important source points:

- `src/sase/xprompt/_parsing_references.py:11` defines the leading-context fragment.
- `src/sase/xprompt/_parsing_references.py:14` defines `#` vs `#!`.
- `src/sase/xprompt/_parsing_references.py:17` defines xprompt name syntax.
- `src/sase/xprompt/_parsing_references.py:22` defines HITL suffixes.
- `src/sase/xprompt/_parsing_references.py:25` defines argument fragments.
- `src/sase/xprompt/_parsing_references.py:160` normalizes `__` to `/`.

For a first TUI version, the cursor detector can stay intentionally narrow:

- Trigger on an exact cursor-after-colon token: `#foo:|`, `#!foo:|`, `#ns/foo:|`, `#ns__foo:|`, `#foo!!:|`,
  `#foo??:|`.
- Do not trigger on `#foo+`, unknown names, URLs, prose like `foo#bar:`, or `#foo: text` shorthand.
- Do not parse command substitution, quoted args, or text blocks for the first slice.

## UX Options

### Option A: Enriched `Ctrl+T` Completion Only

When the user types `#bd/` and presses `Ctrl+T`, show the existing completion list, but each xprompt row includes:

```text
> #bd/work_phase_bead
    bead_id: word
  #bd/land_epic
    epic_id: word  plan_file?: path
```

Pros:

- Smallest change.
- Reuses the existing completion lifecycle.
- Easy to test with current prompt completion tests.

Cons:

- The user only sees hints while the completion menu is active.
- Typing `#foo:` manually still gives no help.
- Accepting a candidate leaves the user to remember syntax.

This is the minimal parity slice.

### Option B: Argument Hint Panel After Completion

After accepting a candidate with visible inputs, keep `Static#prompt-completion` open in a new `xprompt_args` mode:

```text
#bd/work_phase_bead inputs
  bead_id: word
  [^L] colon args  [^Y] named args  [Esc] dismiss
```

Suggested actions:

- `Colon args`: rewrite `#foo` or `#!foo` to `#foo:` / `#!foo:` and put the cursor after `:`.
- `Named args`: rewrite `#foo` to `#foo(arg1=, arg2=)` and place the cursor after the first `=`.
- `Enter` should still submit only when no completion or argument action is active. Avoid surprising launch behavior.

Pros:

- Directly helps after a completion accept.
- Does not force colon syntax.
- Fits the current prompt bar layout.

Cons:

- Needs a distinct hint state, separate from completion list state.
- Must be carefully cleared on edits, mode switches, cancel, submit, and normal-mode entry.

This is the recommended first product target.

### Option C: Automatic Cursor Hints

On every prompt edit/cursor move, detect when the cursor is inside a known xprompt argument position:

```text
#bd/work_phase_bead:
^ shows bead_id: word
```

Useful sub-features:

- Exact trailing colon shows the first required input.
- Comma progress in colon args highlights the next positional input.
- Parenthesized named args show available names and types when the user types `#foo(` or `#foo(arg=`.
- `path` inputs can chain into existing file completion.
- `bool` inputs can offer `true` and `false`.

Pros:

- Better than mobile because it can combine xprompt-aware parsing with the TUI's existing path/file-history completion.
- Helps users who type directly instead of using the picker.

Cons:

- More parser state.
- More interaction conflicts with file completion, snippet tabstops, VCS MRU cycling, and submit behavior.
- Needs stronger tests.

This should be phase two unless the first implementation stays very narrow.

### Option D: Modal Argument Form

After selecting an xprompt, open a small form with one input per argument and then insert the final `#foo(...)`.

Pros:

- Most guided.
- Can validate types before insertion.

Cons:

- Slower for power users.
- Duplicates the prompt editor.
- Awkward for freeform text arguments.
- Less coherent with the existing `Ctrl+T` completion pattern.

Not recommended as the default. It could be useful later for complex workflows with many required inputs.

## Recommended Architecture

### 1. Split Completion Data From Rendering

Create an xprompt assist module, for example:

```text
src/sase/ace/tui/widgets/xprompt_arg_assist.py
```

Suggested pure models:

```python
@dataclass(frozen=True)
class XPromptInputHint:
    name: str
    type: str
    required: bool
    default_display: str | None
    position: int

@dataclass(frozen=True)
class XPromptAssistEntry:
    name: str
    insertion: str
    reference_prefix: str
    kind: str
    input_signature: str | None
    inputs: tuple[XPromptInputHint, ...]
    content_preview: str | None
```

Suggested pure functions:

```python
def build_xprompt_assist_entries(project: str | None = None) -> list[XPromptAssistEntry]:
    ...

def visible_required_inputs(entry: XPromptAssistEntry) -> tuple[XPromptInputHint, ...]:
    ...

def active_xprompt_arg_hint(line: str, col: int, entries_by_name: Mapping[str, XPromptAssistEntry]) -> ActiveHint | None:
    ...

def named_args_skeleton(entry: XPromptAssistEntry) -> str:
    ...
```

The first implementation can call `build_structured_xprompts_catalog()` internally, convert dataclasses, and cache per
project or per prompt-bar mount.

### 2. Extend Candidate Shape

`CompletionCandidate` is currently file-shaped. For xprompt support, either:

- add optional metadata fields to `CompletionCandidate`, or
- introduce a separate `PromptCompletionCandidate` with `kind` and `metadata`.

The second option is cleaner long term because xprompt candidates, file candidates, file-history candidates, and future
argument-value candidates have different display needs.

A conservative first slice can keep `CompletionCandidate` unchanged and have `_completion_kind == "xprompt"` perform a
lookup by selected candidate name before rendering details.

### 3. Add A Prompt Bar Hint Rendering Mode

The prompt input bar already renders completion rows in `show_file_completions()`. Add a sibling method rather than
overloading row tuples too far:

```python
def show_xprompt_arg_hint(self, entry: XPromptAssistEntry, active_index: int = 0) -> None:
    ...
```

Keep it in `Static#prompt-completion` so layout behavior stays consistent with current completion height management.

### 4. Keep State In `PromptTextArea`

`PromptTextArea` already owns:

- active completion state;
- insertion and cursor movement;
- key interception;
- clearing completion state on submit, cancel, escape, normal mode, and edits.

Argument hint state should live there too:

```python
self._xprompt_arg_hint_active = False
self._xprompt_arg_hint_entry = None
self._xprompt_arg_hint_range = None
```

Clear it anywhere `_clear_file_completion()` is currently called, unless the current edit is the exact one that should
refresh the hint.

### 5. Use Shared Parser Semantics In Pure Tests

Do not copy the whole xprompt expansion parser into the widget. A small detector can use either:

- `iter_xprompt_references()` and filter references ending at the cursor, or
- a TUI-specific regex assembled from the exported parser fragments.

Using `iter_xprompt_references()` is safer for drift. It also already normalizes `__` to `/` and handles HITL suffixes.
The detector can feed it a bounded prefix of the current line or whole prompt and then require:

- `ref.end == cursor`;
- `ref.arg_kind == XPromptReferenceArgKind.COLON`;
- `ref.argument_source == ":"` for the exact first slice.

One caveat: the current shared parser's colon argument fragment requires a value after `:` for the regex-level
`COLON` case. A bare trailing `#foo:` may be observed as a no-argument match plus trailing colon. The detector should
have tests for that exact case and may need a helper that recognizes `ref.raw + ":"` at the cursor.

## "Equivalent Or Better" Feature Set

Parity with mobile:

- Structured input names and types visible for required-input xprompts.
- Exact trailing-colon hint trigger.
- `#` and `#!` both supported.
- Slash namespaces and `__` aliases supported.
- HITL suffixes handled.
- No host-side launch semantics changed.

Better than mobile:

- `Ctrl+T` can complete xprompt names and immediately preview arguments in the same flow.
- `path` typed arguments can delegate into existing file completion after `#foo:`.
- `bool` typed arguments can offer `true` / `false` completion.
- Parenthesized named-argument skeletons can be inserted with the cursor placed at the first missing value.
- Completion rows can show xprompt kind, e.g. inline xprompt vs embeddable workflow vs standalone workflow.
- `sase ace --agent`/Textual tests can exercise the whole interaction in-process without Android fixture or gateway
  setup.

## Suggested Phases

### Phase 1: Metadata And Rendering In `Ctrl+T` XPrompt Completion

Scope:

- Add a pure assist adapter over `build_structured_xprompts_catalog()`.
- Extend xprompt completion rendering to show input signature or per-input lines.
- Keep accept behavior unchanged.

Acceptance:

- `Ctrl+T` on `#foo` still filters and inserts canonical references.
- Required/optional inputs are visible in completion rows or a detail pane.
- Entries with only step inputs show no user-facing hints.
- `#!` entries still insert with `#!`.

Tests:

- Extend `tests/ace/tui/widgets/test_xprompt_completion.py`.
- Add pure tests for assist adapter projection.

### Phase 2: Post-Accept Argument Hint Panel

Scope:

- After accepting an xprompt with visible required inputs, render the input hint panel.
- Add `Colon args` and `Named args` actions.
- Add clear/refresh behavior for submit, escape, normal mode, and edits.

Acceptance:

- Accepting `#foo` with required inputs shows hints.
- Accepting `#bar` with no required inputs does not show hints.
- Colon action rewrites only the selected reference.
- Named action inserts `#foo(arg1=, arg2=)` and places the cursor after the first `=`.

Tests:

- Use the existing prompt completion test harness under `tests/ace/tui/widgets/`.
- Add cursor placement assertions.

### Phase 3: Typed Colon Cursor Detector

Scope:

- Show hints when the cursor is immediately after a known trailing colon reference.
- Support `#foo:`, `#!foo:`, `#ns/foo:`, `#ns__foo:`, `#foo!!:`, and `#foo??:`.
- Do not trigger on unknown names, URLs, `foo#bar:`, `#foo+`, or `#foo: text`.

Acceptance:

- Direct typing can reach the same hint panel as completion accept.
- Existing file completion and file-history completion behavior does not regress.

Tests:

- Pure detector tests for parser edge cases.
- Widget tests for typed prompt behavior.

### Phase 4: Value Completion By Type

Scope:

- For `path` inputs, route to existing file completion with the current argument value as the path token.
- For `bool`, offer `true` and `false`.
- For `int`/`float`, show type hints only.
- For parenthesized syntax, complete missing named argument names.

Acceptance:

- `#foo:` where first input is `path` can immediately use file completion.
- `#foo(enabled=)` offers boolean values.
- Named argument completion does not interfere with snippet tabstops.

Tests:

- Pure tests for argument-position inference.
- Widget tests for path and bool completion.

## Risks And Guardrails

- Do not parse `input_signature`. Use structured `inputs`.
- Do not show string defaults unless the source projection explicitly marks them safe. The mobile projection already
  suppresses strings.
- Do not run full xprompt expansion from the prompt bar on every keystroke.
- Keep the first automatic detector exact and narrow.
- Keep `Enter` semantics predictable: accept active completion first; otherwise submit. Argument hint actions should use
  explicit keybindings or buttons, not hijack submit.
- Watch for conflicts with existing prompt editor behavior: VCS MRU cycling on `Ctrl+N`/`Ctrl+P`, snippet expansion on
  `Tab`, `Ctrl+T` file completion, `Ctrl+Y` workflow editor, and normal/insert mode transitions.

## Open Questions

1. Should `#@` selection also open the post-accept hint panel, or should this be limited to `Ctrl+T` completion first?
2. Should xprompt completion rows show every input, or only required inputs with optional inputs in the detail pane?
3. Should `Named args` include optional inputs by default, or only required inputs with a way to add optional ones?
4. Should automatic hints appear as the user types `#foo(`, or wait until `#foo(arg=` / `#foo:` to reduce noise?
5. Should the TUI completion cache refresh live when xprompt files change, or is per-prompt-bar mount good enough?

## Implementation Recommendation

Start with Phase 1 and Phase 2 together if the implementation stays small:

- Use the mobile structured catalog projection as the data source.
- Render input hints in the existing prompt completion panel.
- After accepting a required-input xprompt, leave a compact argument hint panel with explicit syntax actions.

Then add the exact trailing-colon detector as a follow-up. That gives the TUI equivalent support quickly and establishes
the architecture for a better-than-mobile path where typed argument values can reuse file completion and other TUI-only
affordances.
