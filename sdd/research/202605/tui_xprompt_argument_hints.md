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

## Verified Gotchas Found During Research

These are correctness traps that any implementer must internalize before sketching the state machine. They are listed
up front because they constrain the design more than the UX choices below.

- **`:` is already a token-boundary character.** `_TOKEN_DELIMITERS` in `src/sase/ace/tui/widgets/file_completion.py:22`
  contains `:`, so `extract_token_around_cursor()` (`file_completion.py:43`) truncates the token at the colon. After
  the user types `#foo:`, the existing extractor sees only `#foo`. The new argument-hint detector cannot reuse this
  helper to determine "is the cursor in an argument position"; it must use `iter_xprompt_references()` (or its own
  regex-derived helper) and inspect the substring between `ref.end` and the cursor.
- **The shared parser does not match a bare trailing `#foo:`.** The COLON arm in
  `src/sase/xprompt/_parsing_references.py:25-29` requires a non-empty `colon_arg` group, and the surrounding alternative
  is the literal `(`. With no value after the colon, the match collapses to `#foo` with
  `arg_kind == XPromptReferenceArgKind.NONE`, and the trailing `:` is ordinary surrounding text. The detector needs
  to: (a) iterate references, (b) for each reference whose `end` is at or just before the cursor, look at
  `prompt[ref.end : cursor]` and decide whether it is `":"`, `":,"` (positional progress), `"("` or `"(...="`
  (named-arg progress).
- **`Ctrl+Y` is already taken.** `prompt_text_area.py` BINDINGS map `Ctrl+Y` to `action_open_workflow_editor()`, and
  `Ctrl+L` to `_accept_file_completion()`. The earlier draft of this note suggested `[^L] colon args  [^Y] named args`
  in the hint panel — that would clobber the YAML editor binding. Use unbound combos (e.g. `Ctrl+,` / `Ctrl+.` or a
  small explicit footer hint) and route them through the keymap config in `src/sase/default_config.yml` as
  `gotchas.md` requires.
- **`Tab` is owned by snippet expansion / tabstop advance.** `prompt_text_area.py:281-288` calls
  `_try_expand_snippet()` first and `_try_advance_tabstop()` second. The argument hint feature should not bind `Tab`
  itself; instead it should *cooperate* with this machinery (see "Snippet Tabstop Reuse" below).
- **`Ctrl+G` opens the external editor**, `Ctrl+J` inserts a newline, and the `#@` snippet trigger hijacks `@` typed
  after `#`. All three are competing edit affordances; argument hint state must be cleared by the same hooks that
  clear file completion (`_clear_file_completion()` in `_file_completion.py:109`).
- **`COLON_SHORTHAND` (`#foo: text…`) consumes to end-of-paragraph.** Triggering hints when there is a space after `:`
  would compete with prose. The detector must require `prompt[ref.end:cursor]` to start with `:` *and* not contain
  whitespace.
- **`#@` snippet flow already filters by VCS tag.** When the prompt contains a VCS tag like `#gh:sase`,
  `actions/agent_workflow/_prompt_bar_requests.py` derives a project name and passes it to `XPromptSelectModal` so
  project-local xprompts appear. Argument completion should reuse this exact precedent (see "Project-Scoped Catalog").
- **No catalog invalidation hook exists in the Python repo today.** Mobile uses an `event_helpers_changed` ping,
  but the TUI loads xprompts on every `Ctrl+T` via `get_all_prompts()`. Per-build is fine for v1; a small mount-time
  cache is acceptable as long as it is rebuilt on prompt-bar focus or workflow editor exit.

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

- `src/sase/ace/tui/widgets/xprompt_completion.py:23` builds xprompt candidates from `get_all_prompts()` (so YAML
  workflows are already merged in).
- `src/sase/ace/tui/widgets/xprompt_completion.py:36` supports `#!`-only filtering when the typed token starts with
  `#!`.
- `src/sase/ace/tui/widgets/xprompt_completion.py:47` uses `workflow_reference_insertion()`, so canonical insertion is
  already correct.
- `src/sase/ace/tui/widgets/file_completion.py:43` defines `extract_token_around_cursor()` (note: pure-logic file is
  `file_completion.py`; the widget mixin lives at `_file_completion.py`).
- `src/sase/ace/tui/widgets/_file_completion.py:239` chooses path vs xprompt completion in the mixin.
- `src/sase/ace/tui/widgets/prompt_input_bar.py:175` renders the completion panel.

Gap: `CompletionCandidate` only carries `display`, `insertion`, `is_dir`, and `name`
(`file_completion.py:12-19`). The panel cannot show inputs, types, requiredness, defaults, tags, kind, or preview
without another lookup.

Snippet/tabstop machinery: `SnippetExpansionMixin` in `src/sase/ace/tui/widgets/_snippets.py` already handles
`$1`,`$2`,…,`$0` markers and stores remaining tabstops in `_snippet_tabstops` as char-from-end offsets. This is
load-bearing for the recommended named-arg insertion; see "Snippet Tabstop Reuse" below.

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

- `src/sase/ace/tui/modals/xprompt_browser_helpers.py:22` renders input argument labels using the exact
  required-bright/optional-dim style that Phase 1 wants in the inline completion panel:
  required → `#D7AF87`, optional name → `dim #D7AF87`, default or `?` → `dim #888888`.
- `src/sase/ace/tui/modals/xprompt_select_modal.py:160` adds those labels to the select modal rows.
- `src/sase/ace/tui/modals/xprompt_select_modal.py:241` returns the suffix to insert after an existing `#`.
- `src/sase/ace/tui/widgets/prompt_text_area.py:290-302` is the `#@` trigger: typing `@` immediately after `#` posts
  `PromptInputBar.SnippetRequested`, suppresses the literal `@`, and opens `XPromptSelectModal`. The handler in
  `actions/agent_workflow/_prompt_bar_requests.py:120-183` derives a project from any leading VCS tag in the prompt
  and passes it to the modal — direct precedent for project-scoped catalog reuse.
- `src/sase/ace/tui/widgets/prompt_input_bar.py:286` defines `insert_snippet()`, which the modal selection path uses to
  splice the chosen suffix into the prompt.

Gap: this support is modal-only. It helps when the user explicitly opens the selector, but not when they type or complete
inside the normal prompt bar. **Refactor lever**: `append_input_args()` is the exact rendering function the inline
completion panel needs. Phase 1 should extract it (or its inputs-only inner loop) into a shared helper rather than
introducing a second renderer.

## Mobile Work Now Available To Reuse

The mobile catalog projection now has exactly the structured metadata that the TUI needs:

- `StructuredCatalogInput`: `name`, `type`, `required`, `default_display`, `position`.
- `StructuredCatalogEntry`: `name`, `display_label`, `insertion`, `reference_prefix`, `kind`, `input_signature`,
  `inputs`, `content_preview`, and source metadata.

Important source points:

- `src/sase/xprompt/_catalog_models.py:43` defines `StructuredCatalogInput`.
- `src/sase/xprompt/_catalog_models.py:54` defines `StructuredCatalogEntry`.
- `src/sase/xprompt/_catalog_structured.py:32` defines `build_structured_xprompts_catalog(project=None, source=None,
  tag=None, query=None)` — already accepts a project filter.
- `src/sase/xprompt/_catalog_structured.py:144` builds canonical structured entries.
- `src/sase/xprompt/_catalog_structured.py:149` uses `workflow_reference_insertion()`.
- `src/sase/xprompt/_catalog_structured.py:164` filters visible inputs and derives requiredness from `UNSET`.
- `src/sase/xprompt/_catalog_structured.py:181` suppresses string defaults, matching the mobile sensitive-default
  guardrail. Numeric and bool defaults still flow as `default_display`.
- `src/sase/xprompt/_catalog_sources.py:53-88` (`gather_structured_entries`) merges
  `get_all_workflows()` + `get_all_xprompts()` with workflows winning name collisions. This is near-equivalent to the
  current TUI's `get_all_prompts()` call, so switching the completion path to the structured catalog does not change
  *which* prompts appear, only what metadata travels with them.
- `src/sase/xprompt/reference_display.py:9-37` defines the `#` vs `#!` rule: standalone workflows always get `#!`,
  and `SIMPLE_XPROMPT` workflows whose body contains `---` segment separators also get `#!`. `kind` alone is not
  enough to derive the prefix — always use `insertion` / `reference_prefix` from the projection.
- `src/sase/xprompt/reference_display.py:20-25` defines `workflow_kind_value()` returning `"xprompt"`,
  `"embeddable_workflow"`, or `"standalone_workflow"`.

The TUI can either call `build_structured_xprompts_catalog()` directly, or it can reuse the same projection functions
behind a TUI-specific helper. Calling the structured catalog directly has the advantage of matching mobile exactly.
Using a small adapter has the advantage of keeping prompt completion lightweight and avoiding PDF/catalog terminology
inside widget code. **Today there are zero TUI callers of `build_structured_xprompts_catalog()`** — the only consumer
is the mobile helper bridge (`src/sase/integrations/_mobile_helper_catalog.py`,
`src/sase/integrations/mobile_helpers.py`). Adding a TUI caller is greenfield.

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

### Detector Algorithm (Concrete)

Because the shared regex does not match a bare trailing `#foo:` (see Verified Gotchas), the detector must compose
existing pieces rather than rely on a single `iter_xprompt_references()` lookup. Recommended algorithm in pseudo-code:

```python
def active_xprompt_arg_position(prompt: str, cursor: int, entries_by_name: Mapping[str, ...]) -> ActiveHint | None:
    # 1. Cheap early-out: cursor must be at end of a "#..."-rooted token region.
    refs = iter_xprompt_references(prompt[: cursor + 1])
    candidates = [r for r in refs if r.start < cursor and r.arg_kind in {COLON, PAREN, NONE}]
    if not candidates:
        return None
    ref = candidates[-1]

    # 2. Look at the slice between the matched reference and the cursor.
    suffix = prompt[ref.end:cursor]
    name = ref.name  # already normalized (`__` -> `/`) by xprompt_reference_from_match.
    entry = entries_by_name.get(name)
    if entry is None or not any(i.required for i in entry.inputs):
        return None

    # 3. Decide active argument index.
    if suffix == "":  # cursor sits at end of `#foo` immediately after accept.
        return ActiveHint(entry, mode="bare", index=0)
    if suffix.startswith(":") and " " not in suffix:  # `#foo:`, `#foo:a,b,`
        completed_commas = suffix.count(",")
        return ActiveHint(entry, mode="colon", index=completed_commas)
    if suffix.startswith("(") and "\n" not in suffix:
        return ActiveHint(entry, mode="paren", index=_paren_arg_index(suffix))
    return None  # `#foo: text` shorthand or unrelated trailing text — no hint.
```

Notes:

- `iter_xprompt_references()` returns the reference even for `#foo` with no args (`arg_kind == NONE`), which is the
  shape the bare and colon cases see. This is verified by the parser tests in `tests/test_xprompt_references.py`.
- Replacing `__` with `/` is already done inside `xprompt_reference_from_match()` (`_parsing_args.py`), so the
  detector only needs to look up by `ref.name`.
- HITL suffixes `!!`/`??` are stripped by the parser into `ref.hitl_override`, so `ref.name` is the catalog key.
- Skip detection when `prompt_text_area._snippet_tabstops` is non-empty so an in-progress snippet does not double-fire
  hints on each tabstop advance.

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
  [^,] colon args  [^.] named args  [Esc] dismiss
```

Suggested actions (pick keybinds that are not already taken — `Ctrl+L`, `Ctrl+Y`, `Ctrl+G`, `Ctrl+D`, `Ctrl+T` are
all bound elsewhere on the prompt bar; `Ctrl+,` and `Ctrl+.` are free, and any final choice must land in
`src/sase/default_config.yml` per `gotchas.md`):

- `Colon args`: rewrite `#foo` or `#!foo` to `#foo:` / `#!foo:` and put the cursor after `:`.
- `Named args`: rewrite `#foo` to `#foo(arg1=$1, arg2=$2)$0` (using the existing snippet template syntax) and let
  `SnippetExpansionMixin` place the cursor at `$1` and remember the remaining tabstops — see "Snippet Tabstop Reuse"
  below. This eliminates the awkward "place cursor after first `=`" custom code path the earlier draft proposed.
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

## Snippet Tabstop Reuse

The single highest-leverage architectural decision in this feature is to render named-argument insertion as a snippet
template and let the existing tabstop machinery do the cursor work for free.

`src/sase/ace/tui/widgets/_snippets.py` already implements:

- Template substitution with `$1`, `$2`, …, `$0` markers (`_try_expand_snippet()` at `_snippets.py:40`).
- Cursor placement at the first tabstop (`_position_cursor_at_expansion_offset()` at `_snippets.py:141`).
- `Tab`-driven tabstop advancement via `_try_advance_tabstop()` at `_snippets.py:156`, with offsets stored in
  `_snippet_tabstops` as char-from-end deltas so subsequent edits don't drift.
- Implicit `$0` at end if the template omits it.

For named-arg insertion, the hint panel's `Named args` action just constructs:

```python
template = f"#{name}(" + ", ".join(f"{i.name}=$" + str(idx + 1) for idx, i in enumerate(visible_inputs)) + ")$0"
```

Then it calls the same `_replace_via_keyboard()` + `_position_cursor_at_expansion_offset()` + `_snippet_tabstops`
sequence the snippet path uses. The user gets `Tab` navigation between fields and `$0` exit out of the parens with no
new code. This also means the feature interacts with snippet expansion in a way users can already reason about.

Caveat: the regex in `_try_expand_snippet()` uses `\$(\d+)` and there is no escape syntax. If an xprompt input name
ever happens to look like `$3` it would collide; visible input names are `[a-zA-Z_][a-zA-Z0-9_]*` so this is not a
real risk in practice, but the named-arg builder should still place the marker `$N` *outside* the input name (after
the `=`), as in the template above.

For colon-arg mode, the same idea applies but is less ergonomic because colon args are positional and comma-separated
without per-arg labels. A simpler `#foo:$0` template (cursor lands after `:`) is sufficient for the first slice.

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

### 5. Project-Scoped Catalog

`build_structured_xprompts_catalog(project=...)` already accepts a project filter, and the existing `#@` snippet flow
shows how to derive that project from the prompt itself. In
`src/sase/ace/tui/actions/agent_workflow/_prompt_bar_requests.py:120-183`, the snippet handler:

1. Reads the current prompt text.
2. Calls `extract_vcs_workflow_tag()` (`src/sase/xprompt/_parsing`) to find a leading `#vcs:project` tag.
3. Passes the resolved project to the modal so project-local xprompts appear.

The argument hint feature should reuse this exact precedent so a user typing `#gh:my-repo #bd/...` sees argument hints
for `bd/...` xprompts that are scoped to `my-repo`. Practically:

- The pure assist module exposes `build_xprompt_assist_entries(project: str | None = None)`.
- The widget computes `project` once on prompt-bar focus and on prompt-text changes that touch the leading VCS-tag
  region (a cheap leading-token re-parse, not full prompt re-parse).
- The widget caches `entries_by_name` keyed on the resolved project so the detector lookup is O(1).

Without this, a user's project-local xprompts would silently fail to produce hints — the same trap the mobile work
called out as a prerequisite for shipping hints there.

### 6. Use Shared Parser Semantics In Pure Tests

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
- For an xprompt with a single required `bool` input, the hint panel can offer a `+` action that rewrites
  `#foo` to `#foo+` (the existing parser sugar for `:true`, `_parsing_args.py:209-210`). Mobile cannot easily expose
  this because `+` is awkward on touch keyboards.
- Reuse of `SnippetExpansionMixin` makes named-arg navigation feel native — `Tab` jumps fields, `$0` exits the parens.
  Mobile has no equivalent IME-friendly multi-tabstop affordance.
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

- The current TUI test files for the prompt bar are `tests/ace/tui/widgets/test_prompt_file_completion.py`,
  `test_prompt_at_prefix_completion.py`, `test_prompt_snippet_expansion.py`, and
  `test_prompt_file_history_completion.py`; modal tests live at
  `tests/ace/tui/modals/test_xprompt_select_modal.py` and `test_xprompt_browser_helpers.py`. There is no
  `test_xprompt_completion.py` today — add one alongside the existing widget tests, and reuse the rendering helpers
  exercised by `test_xprompt_browser_helpers.py` so visual style stays consistent across surfaces.
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

### Conflict Matrix

The prompt bar already overloads several keys conditionally on internal state. Any new argument-hint state must coexist.
Confirmed via direct read of `prompt_text_area.py` BINDINGS and the `_on_key`/action handlers:

| Key      | Idle                       | Completion active            | Snippet tabstops active        | VCS-MRU eligible (empty/VCS-only prompt) |
| -------- | -------------------------- | ---------------------------- | ------------------------------ | ---------------------------------------- |
| `Tab`    | Snippet expand → tabstop   | Snippet expand → tabstop     | Advance tabstop                | Snippet expand                           |
| `Ctrl+T` | Open file/xprompt comp.    | Cycle / refresh comp.        | Open comp.                     | Open comp.                               |
| `Ctrl+L` | (unbound on idle)          | Accept active candidate      | (unbound)                      | (unbound)                                |
| `Ctrl+D` | (unbound)                  | Delete history entry         | (unbound)                      | (unbound)                                |
| `Ctrl+N` | Cursor down                | Next candidate               | Cursor down                    | Cycle to next prior prompt               |
| `Ctrl+P` | Cursor up                  | Previous candidate           | Cursor up                      | Cycle to previous prior prompt           |
| `Ctrl+Y` | Open workflow YAML editor  | Open workflow YAML editor    | Open workflow YAML editor      | Open workflow YAML editor                |
| `Ctrl+G` | Open external editor       | Open external editor         | Open external editor           | Open external editor                     |
| `Ctrl+J` | Insert newline             | Insert newline               | Insert newline                 | Insert newline                           |
| `Ctrl+C` | Clear / cancel             | Clear completion             | Clear (also clears tabstops)   | Clear                                    |
| `Esc`    | Insert → Normal mode       | Clear completion             | Clear tabstops                 | Reset MRU index                          |
| `Enter`  | Submit                     | Accept candidate (then idle) | Submit (tabstops are advisory) | Submit                                   |
| `@`      | Literal `@`                | Literal `@`                  | Literal `@`                    | Literal `@`                              |
| `#@`     | Open `XPromptSelectModal`  | Open modal (clears comp.)    | Open modal                     | Open modal                               |

Argument-hint state is best modeled as an *advisory overlay*: it does not own any key today, it co-exists with
completion-active and snippet-tabstops-active modes (because Phase 2 named-args inserts a snippet template), and it is
torn down by the same set of events that already tear down completion (submit, escape, mode switch, prompt edit
outside the active reference span).

## Open Questions

1. Should `#@` selection also open the post-accept hint panel, or should this be limited to `Ctrl+T` completion first?
   **Tentative answer:** yes, the `#@` modal already shows input rows via `append_input_args`, so wiring its
   `dismiss(name)` path through the same hint-on-accept code path is a small additional cost and gives a coherent
   experience across both completion entry points.
2. Should xprompt completion rows show every input, or only required inputs with optional inputs in the detail pane?
   **Tentative answer:** match the existing modal behavior in `xprompt_browser_helpers.append_input_args` — show all
   user-facing inputs with the same required-bright / optional-dim styling. Two surfaces using one renderer is the
   point of the refactor.
3. Should `Named args` include optional inputs by default, or only required inputs with a way to add optional ones?
   **Tentative answer:** required-only by default; add a follow-up modifier (e.g. shift+action) to include all visible
   inputs. Snippet tabstops make extending the template later trivial.
4. Should automatic hints appear as the user types `#foo(`, or wait until `#foo(arg=` / `#foo:` to reduce noise?
   **Tentative answer:** trigger as soon as `(` or `:` appears immediately after a known reference; require no
   whitespace in the suffix to avoid `#foo: text` shorthand collisions.
5. Should the TUI completion cache refresh live when xprompt files change, or is per-prompt-bar mount good enough?
   **Tentative answer:** per-mount (or per-prompt-bar focus) is good enough today — there is no
   `event_helpers_changed` analogue in the Python repo. If/when one lands, hook it from the existing prompt bar
   refresh path rather than inventing a new lifecycle.
6. Should the assist module call `build_structured_xprompts_catalog()` directly, or extract a thin helper that
   returns just `(name, insertion, inputs)` triples? Calling directly keeps mobile and TUI on identical metadata;
   a helper avoids dragging tags / source_bucket / source_path_display through widget code. Suggest direct call,
   since the structured entry is already small and immutable.
7. How should the hint panel interact with `XPromptTag`-resolved references like the `bd/work_phase_bead` /
   `bd/land_epic` defaults used by `sase bead work`? Those are *role* tags (`src/sase/xprompt/tags.py`), not part of
   the user-typed reference syntax, so they are out of scope for the cursor detector — but the completion list could
   surface a small "(default for `bd/work_phase_bead` role)" annotation when a user has overridden the default.

## Implementation Recommendation

Start with Phase 1 and Phase 2 together if the implementation stays small:

- Use the mobile structured catalog projection as the data source, with `project=` derived from any leading VCS tag
  via the existing `extract_vcs_workflow_tag()` helper.
- Render input hints in the existing prompt completion panel by extracting `append_input_args` (or its inputs-only
  inner loop) into a shared helper used by both the modal and the inline panel.
- After accepting a required-input xprompt, leave a compact argument hint panel with explicit syntax actions, where
  the `Named args` action emits a snippet template (`$1`,…,`$0`) and reuses `SnippetExpansionMixin` for tabstop
  navigation.
- Bind any new prompt-bar shortcuts in `src/sase/default_config.yml` per `gotchas.md`, and avoid `Ctrl+T`,
  `Ctrl+L`, `Ctrl+Y`, `Ctrl+G`, `Ctrl+D`, `Ctrl+J`, and `Ctrl+N`/`Ctrl+P` — all are already overloaded.

Then add the exact trailing-colon detector as a follow-up using the algorithm in "Detector Algorithm (Concrete)"
above. That gives the TUI equivalent support quickly and establishes the architecture for a better-than-mobile path
where typed argument values can reuse file completion and other TUI-only affordances (path completion after
`#foo:`, boolean `+` sugar, snippet-tabstop navigation through named args).
