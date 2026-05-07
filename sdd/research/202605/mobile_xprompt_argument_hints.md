# Mobile XPrompt Argument Hints

Date: 2026-05-07

## Question

How should SASE's Android app support xprompt argument name/type hints when:

- the user selects an xprompt that has required arguments; or
- the user types `:` after an xprompt reference, for example `#foo:`?

## Executive Summary

The right implementation is a small mobile contract extension plus a local Compose prompt-editor state machine.
Android should not parse the existing `input_signature` string as the source of truth. That field is display text, not a
stable schema. The gateway should send structured xprompt input metadata, and the app should use that metadata to render
argument hints at the cursor.

Recommended shape:

1. Extend `MobileXpromptCatalogEntryWire` with structured `inputs` records and an `insertion` or `reference_prefix`
   field.
2. Build those records from `InputArg`/`Workflow.inputs`, where `default is UNSET` means required and
   `is_step_input=True` inputs are hidden from the user.
3. In Android, keep a `Map<String, MobileXpromptCatalogEntryWire>` from the launch helper catalog.
4. When a catalog entry with required inputs is selected, insert the reference and show an argument hint surface.
5. On every prompt text/selection change, if the cursor is immediately after a known reference colon such as `#foo:` or
   `#!foo:`, show the same hint surface.
6. Prefer rendering hints without mutating the user's text beyond the selected reference. Let the user decide whether to
   type positional colon args, comma-separated args, or later switch to parenthesized named args.

This should be treated as shared gateway contract work plus Android UI work. It is not a Rust-core-only change because
xprompt loading and input metadata are still Python-owned host behavior.

## Current State

### XPrompt Input Model

The Python xprompt model already has the needed source metadata:

- `src/sase/xprompt/models.py`
  - `InputType`: `word`, `line`, `text`, `path`, `int`, `bool`, `float`.
  - `InputArg.name`
  - `InputArg.type`
  - `InputArg.default`
  - `InputArg.is_step_input`
  - `UNSET`, where `default is UNSET` means the input is required.
- `src/sase/xprompt/loader_parsing.py`
  - Markdown/config xprompt input parsing preserves `UNSET` for missing defaults.
- `src/sase/xprompt/workflow_loader_parse.py`
  - Workflow input parsing uses the same `InputArg` type.

For user-facing hints, the effective input list is:

```python
visible_inputs = [inp for inp in workflow.inputs if not inp.is_step_input]
required_inputs = [inp for inp in visible_inputs if inp.default is UNSET]
```

### Mobile Catalog Contract

The mobile helper catalog currently projects xprompts through:

- `src/sase/xprompt/catalog.py`
- `src/sase/integrations/_mobile_helper_catalog.py`
- `../sase-core/crates/sase_gateway/src/wire.rs`
- `../sase-android/app/src/main/java/org/sase/mobile/data/api/dto/HelperWire.kt`

The relevant current fields are:

- `name`
- `display_label`
- `description`
- `source_bucket`
- `project`
- `tags`
- `input_signature`
- `is_skill`
- `content_preview`
- `source_path_display`

`input_signature` is produced by `_format_inputs()` (`src/sase/xprompt/catalog.py:603-616`) as display text like
`(plan_file: path, notes?: line)`. It filters out step inputs and encodes requiredness by omission of `?`. That is
useful for display, but it is too lossy for a prompt-editor feature:

- It has no stable per-input array.
- Defaults are not surfaced at all (the formatter omits them entirely).
- Subtle gotcha: when **every** input is `is_step_input=True`, `_format_inputs` returns `""` and `_structured_entry`
  converts that to `None`, even though `workflow.inputs` is non-empty. Android cannot infer "no required inputs" from
  `input_signature is None` once structured `inputs` exist; rely on the new array directly.
- Tests and fixtures already show drift: Android fixtures use values like `"bead_id"`, while Python actually formats
  `"(bead_id: word)"`.
- Client parsing would couple Android to punctuation rather than the backend input model.

The Rust contract (`../sase-core/crates/sase_gateway/src/wire.rs`) is at `GatewayWireSchemaVersion = 1`. Adding new
fields is backward-compatible if Android defaults missing fields to empty/`null`, but the snapshot test
`committed_contract_snapshot_is_current` (`crates/sase_gateway/src/contract.rs`) byte-compares against
`contracts/api_v1/mobile_api_v1.json`, so the JSON snapshot must be regenerated in the same change.

### Android Launch UI

The launch screen is currently a raw prompt editor plus helper chips:

- `../sase-android/app/src/main/java/org/sase/mobile/ui/launch/LaunchScreen.kt`
  - Prompt is stored as `var prompt by rememberSaveable(stateSaver = TextFieldValue.Saver)`, so cursor and selection
    are preserved across recomposition and process death — no extra plumbing needed for hint-state restoration.
  - `insertPromptSnippet(...)` (~`LaunchScreen.kt:651-661`) is a raw splice that replaces the current selection with
    a snippet and places the cursor right after it. Useful as the primitive for selection-trigger insertion, but it
    does not parse the existing buffer.
  - Concrete colon-arg precedent already exists: phase-bead insertion writes
    `"#bd/work_phase_bead:$id"` (~`LaunchScreen.kt:666-670`, mirrored in `HelpersScreen.kt:637-641`). The proposed
    "Colon args" edit action should follow this same shape.
  - `refreshHelpers()` (~`LaunchScreen.kt:140-147`) re-fetches the catalog with the current `project` filter. There is
    a `LaunchedEffect(helperRepository, helperEventVersion)` that fires on gateway `event_helpers_changed` pings
    (`app/src/test/resources/fixtures/gateway/event_helpers_changed.json`) but **no `LaunchedEffect(project)`** —
    typing a new project name does not re-fetch the catalog, so project-local xprompts will be missing from the
    catalog map and hints will silently no-op. Fix this *before* shipping hints, otherwise the feature looks broken
    for any project-scoped xprompt.
  - Theme tokens already in use for similar surfaces: `MaterialTheme.colorScheme.surfaceVariant` (~`alpha = 0.55f` for
    `HelperResultBanner`), `MaterialTheme.shapes.small`, `typography.titleSmall`/`bodyMedium`. Reuse these so the hint
    panel matches the existing helper banner styling.
  - `LaunchHelperInsertPanel` inserts ChangeSpec tags, xprompts, and beads into the prompt.
  - Xprompt chips currently insert `"#${entry.name}"` unconditionally (~`LaunchScreen.kt:517`).
- `../sase-android/app/src/main/java/org/sase/mobile/ui/helpers/HelpersScreen.kt`
  - Xprompt rows copy/insert `"#${entry.name}"` unconditionally (~line 376).

The unconditional `#` insertion is fine for simple inline xprompts, but it is incomplete for standalone workflows or
multi-agent xprompts that should use `#!`. The TUI has the correct helper in
`src/sase/xprompt/reference_display.py`: `workflow_reference_insertion(name, workflow)`.

Performance note: Compose recomposes on every keystroke. The `Map<String, MobileXpromptCatalogEntryWire>` used by the
detector should be built with `remember(state.xprompts) { state.xprompts.associateBy { it.name } }` so lookup stays
O(1) and the map is not rebuilt per character. The detector itself should also early-return on
`state.loading || state.failureMessage != null || catalogByName.isEmpty()` so the user does not see a flash of
empty hint panel before the catalog arrives.

## Existing Parser Semantics To Preserve

The shared xprompt reference parser lives in:

- `src/sase/xprompt/_parsing_references.py`
- `src/sase/xprompt/_parsing_args.py`

The full reference regex is composed in `_parsing_references.py:11-39`. Salient pieces the mobile detector should
mirror exactly:

- **Leading-context anchor** (`_parsing_references.py:11`): `(?:^|(?<=\s)|(?<=[(\[{"\']))`. References only start at
  line start, after whitespace, or after `(`, `[`, `{`, `"`, `'`. This is what makes `foo#bar:` not a reference and is
  also why `# Heading` is not a reference (the regex requires a name char to follow `#`/`#!` immediately, no space).
  Android does not need a separate Markdown-heading guard.
- **Marker** (`_parsing_references.py:14`): `#!|#`.
- **Name** (`_parsing_references.py:17-19`): `[a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*`. Each slash segment
  must start with a letter or underscore. The double-underscore alias `#a__b` is a literal name, not a regex feature;
  it is rewritten to `a/b` after parsing in `_parsing_args.py` (`name.replace("__", "/")`).
- **HITL suffix** (`_parsing_references.py:22`): `!!|??`. References like `#foo!!:`, `#bar??(...)` are valid; the
  suffix sits between the name and the argument fragment. The Android cursor detector must strip a trailing `!!`/`??`
  before looking the reference up in the catalog (`_parsing_args.py:162-187` is the host equivalent).
- **Argument fragment** (`_parsing_references.py:25-29`): a single colon-arg whitelist of
  `` `…` ``, `$(…)`, `{{…}}`, `{…}`, or `[a-zA-Z0-9_.~,/-]*[a-zA-Z0-9_~/-]`. Comma is included, so a colon-arg can be a
  comma-separated list. The mobile detector can ignore the substitution forms in v1 — exact trailing `:` is enough.
- **Plus syntax** (`_parsing_args.py:209-210`): `#foo+` is sugar for `:true`. Hints should not trigger on `+`.

Reference syntax surface:

- `#name`, `#name(args)`, `#name:arg`, `#name:a,b,c`, `#name+`
- `#name: text` (single-colon shorthand) and `#name:: text` (double-colon shorthand) — both consume to end of paragraph
  via `find_double_colon_text_end`/`find_shorthand_text_end`. The mobile hint detector should not trigger on the space
  variant because it would compete with normal prose.
- `#!name` for standalone-workflow or multi-agent (`---`-separated) xprompt references.
- `#ns/name` and the `#a__b` slash alias.

For mobile hints, the app does not need to fully reimplement expansion parsing. It only needs a lightweight cursor
detector that recognizes a reference immediately before the cursor and looks it up in the already-loaded catalog. The
backend remains authoritative at launch time.

Cursor detector scope:

- Show hints when the cursor is after an exact trailing colon for a known reference: `#foo:|`, `#!foo:|`, `#ns/foo:|`,
  `#ns__foo:|`, `#foo!!:|`, `#foo??:|`.
- Optionally keep hints visible while the user fills comma-separated colon args: `#foo:first,|` can highlight the
  second input.
- Strip any trailing `!!`/`??` before catalog lookup. Replace `__` with `/` for namespaced names.
- Do not trigger on unknown names.
- Do not trigger when the colon belongs to surrounding prose, URLs, or a prior completed token (the leading-context
  anchor makes this naturally false in most cases).

## TUI Prior Art

The TUI already renders xprompt argument hints. Mobile should match these conventions where reasonable so the two
clients feel coherent.

- **Inline argument signature on each xprompt row in the selection modal.** `append_input_args(text, inputs)` at
  `src/sase/ace/tui/modals/xprompt_browser_helpers.py:22-42` (used by `xprompt_select_modal.py:21`) writes one indented
  line per visible input below the xprompt name, using:
  - required: bright `#D7AF87` (warm tan).
  - optional: dim `#D7AF87` for the name, plus `=<default>` (or `?` when no default) in dim `#888888`.
  - same `is_step_input` filter and same `default is UNSET` requiredness rule the catalog projection should use.
  Android should map these roles to Material tokens — for example required → `colorScheme.tertiary`, optional name →
  `colorScheme.onSurfaceVariant` at reduced alpha, default-display → `colorScheme.onSurfaceVariant` at lower alpha.
- **Compact inline completion line, not a modal.** The prompt input bar reserves a single `Static#prompt-completion`
  line above the editor (`src/sase/ace/tui/widgets/prompt_input_bar.py`) and the `<ctrl+t>` xprompt completion uses it
  via `src/sase/ace/tui/widgets/xprompt_completion.py`. The mobile hint surface should follow the same pattern — a
  compact panel directly under the prompt field rather than a popup that fights the IME.
- **Insertion already uses the canonical helper in TUI.** `xprompt_completion.py` resolves `workflow_reference_insertion`
  and `workflow_reference_prefix`, so it correctly inserts `#!` for standalone or `---`-segmented xprompts. Android
  currently does not (`LaunchScreen.kt:517` and `HelpersScreen.kt:376` both hard-code `"#${entry.name}"`). Bringing
  Android up to parity is a prerequisite for hints that target `#!` references.
- **No on-`:` hint trigger exists yet anywhere.** That part is genuinely mobile-novel; there is no Python prior art to
  reuse. The detector contract below is the authoritative spec.

## Contract Recommendation

Add structured input records to the gateway contract.

Suggested wire shape:

```json
{
  "name": "bd/work_phase_bead",
  "display_label": "bd/work_phase_bead",
  "insertion": "#bd/work_phase_bead",
  "reference_prefix": "#",
  "kind": "xprompt",
  "input_signature": "(bead_id: word)",
  "inputs": [
    {
      "name": "bead_id",
      "type": "word",
      "required": true,
      "default_display": null,
      "position": 0
    }
  ]
}
```

Fields:

- `inputs`: stable array for UI logic.
- `required`: derived from `default is UNSET`.
- `default_display`: stringified default for display only; `null` when required or when the default is explicit YAML
  `null`. **Sensitive-default risk:** `InputArg` does not currently carry a `sensitive`/`secret` flag (`models.py:46-83`),
  so any default value authored in a workflow YAML — including tokens, paths, or names a user considers private — would
  flow to mobile clients as plain text. Recommended mitigations, in order of preference: (a) add `sensitive: bool = False`
  to `InputArg` and gate `default_display` on it; (b) until that lands, ship `default_display = null` for all string
  defaults and only surface defaults for `INT`/`BOOL`/`FLOAT` types; (c) never emit `default_display` for inputs whose
  name matches a denylist (`token`, `secret`, `password`, `key`).
- `position`: stable positional order.
- `insertion`: exact reference to insert, including `#` vs `#!`. Required field — Android cannot derive the marker from
  `kind` alone, because `workflow_reference_prefix` returns `"#!"` for `SIMPLE_XPROMPT` whose body contains `---`
  segment separators (`src/sase/xprompt/reference_display.py:9-37`), which `kind` does not capture.
- `reference_prefix`: `"#"` or `"#!"`, sourced from `workflow_reference_prefix`. Useful for chip-label rendering even
  when `insertion` is what gets pasted into the editor.
- `kind`: source from `workflow_kind_value(workflow)` (returns the strings `"xprompt"`, `"embeddable_workflow"`,
  `"standalone_workflow"`). Note `workflow_kind_value` returns `"xprompt"` (not `"simple_xprompt"`) for the
  `SIMPLE_XPROMPT` enum value — match that string on the wire.

Do **not** project `InputArg.output_schema` to the wire. It is internal step-output validation and may carry arbitrary
JSON Schema with PII or repo-specific structure; the catalog should never serialize it.

Keep `input_signature` for compact list display and backwards compatibility.

### Python Projection

In `src/sase/xprompt/catalog.py`, add a dataclass similar to:

```python
@dataclass(frozen=True)
class StructuredCatalogInput:
    name: str
    type: str
    required: bool
    default_display: str | None
    position: int
```

Then project visible inputs from `InputArg`.

If the mobile catalog remains xprompt-only, this is a small additive change to `StructuredCatalogEntry`. If mobile
should support YAML workflows in the same picker, change the catalog source from `get_all_xprompts()` to the unified
`get_all_prompts()` path and use `workflow_reference_insertion()`/`workflow_kind_value()` for insertion metadata.

That workflow-inclusive version is preferable long term because the launch screen already treats helper entries as
launchable prompt references, not just Markdown prompt parts.

### Rust Gateway Contract

Update `../sase-core/crates/sase_gateway/src/wire.rs` and the contract snapshot:

- Add `MobileXpromptInputWire`.
- Add `inputs: Vec<MobileXpromptInputWire>` to `MobileXpromptCatalogEntryWire`.
- Add `insertion: Option<String>` or non-optional `insertion: String`.
- Refresh `../sase-core/crates/sase_gateway/contracts/api_v1/mobile_api_v1.json`.

This is additive if Android treats missing `inputs` as empty during migration.

### Android DTO

Update `../sase-android/app/src/main/java/org/sase/mobile/data/api/dto/HelperWire.kt`:

```kotlin
@Serializable
data class MobileXpromptInputWire(
    val name: String,
    val type: String,
    val required: Boolean,
    @SerialName("default_display") val defaultDisplay: String? = null,
    val position: Int,
)
```

Then add:

```kotlin
val insertion: String? = null,
val inputs: List<MobileXpromptInputWire> = emptyList(),
```

Using nullable/defaulted fields lets existing fixtures continue decoding during rollout.

## Android UX Recommendation

### Selection Trigger

When the user taps an xprompt chip or row:

1. Insert `entry.insertion ?: "#${entry.name}"`.
2. If `entry.inputs.any { it.required }`, show an argument hint panel.
3. Do not automatically append a colon unless the product decision is to move the cursor directly into positional entry.

Why avoid auto-colon by default:

- Some users may prefer `#foo(arg=value)` named syntax.
- Multi-argument xprompts are easier to fill correctly with named or parenthesized syntax.
- The user explicitly asked for hints, not forced syntax rewriting.

A useful enhancement is an action in the hint panel:

- `Use colon args`: rewrites `#foo` to `#foo:` and places the cursor after `:`.
- `Use named args`: rewrites `#foo` to `#foo(arg1=, arg2=)` and places the cursor after the first `=`.

### Colon Trigger

On `TextFieldValue` change, derive:

```kotlin
data class ActiveXpromptArgHint(
    val entry: MobileXpromptCatalogEntryWire,
    val activeIndex: Int,
)
```

Pseudo-logic:

```kotlin
fun activeXpromptArgHint(
    value: TextFieldValue,
    catalogByName: Map<String, MobileXpromptCatalogEntryWire>,
): ActiveXpromptArgHint? {
    val cursor = value.selection.end
    if (!value.selection.collapsed || cursor == 0) return null

    val before = value.text.substring(0, cursor)
    val token = before.substringAfterLastWhitespaceOrOpenDelimiter()
    if (!token.endsWith(":") && !token.matchesColonArgsInProgress()) return null

    val ref = parsePromptReferenceToken(token) ?: return null
    val entry = catalogByName[ref.name] ?: catalogByName[ref.name.replace("__", "/")] ?: return null
    if (entry.inputs.none { it.required }) return null

    return ActiveXpromptArgHint(entry, activeIndex = ref.completedColonArgCount)
}
```

The first implementation can stay simpler:

- only trigger when token exactly ends in `:`;
- active index is always `0`;
- render all visible inputs.

Then add comma-progress highlighting later.

### Hint Presentation

Use a compact panel directly under the prompt field. Avoid a modal for the normal typing case.

Recommended contents:

- title: `#foo inputs`
- required chips first: `path: path`, `count: int`, `enabled: bool`
- optional chips dimmed with default display: `limit?: int = 500`
- short helper buttons only if they perform concrete edits:
  - `Named args`
  - `Colon args`

For the selected-entry trigger, the same panel can open even before the colon exists. For the typed-colon trigger, the
panel should remain visible while the cursor stays in that reference token.

## Edge Cases

### Single Required Argument

For one required input, `#foo:` plus a hint `file_path: path` is enough.

### Multiple Required Arguments

For several inputs, colon syntax is positional and comma-separated. Hints should show the declared order:

```text
#foo:
inputs: path: path, mode: word, notes: text
```

If the user chooses `Named args`, insert:

```text
#foo(path=, mode=, notes=)
```

### Optional Arguments

Optional inputs should be visible but lower priority. Requiredness comes from `default is UNSET`, not from type.

### Step Inputs

`InputArg.is_step_input` values are internal workflow inputs generated from step outputs. Do not show them in mobile
hints.

### `#!` Standalone References

The detector should accept both `#foo:` and `#!foo:`. The catalog should tell Android the correct insertion string.

### Namespaced XPrompts

Support names like `#bd/work_phase_bead:` and the double-underscore alias `#bd__work_phase_bead:`.

### HITL Override Suffix

References can carry a HITL override suffix `!!` or `??` between the name and the argument fragment, e.g. `#foo!!:`,
`#bar??(arg=1)`. The cursor detector must strip a trailing `!!`/`??` before catalog lookup so a user who types
`#foo!!:` still sees hints. (Mirror `_parsing_args.py:162-187`.)

### All-Step-Inputs XPrompts

When `workflow.inputs` is non-empty but every entry has `is_step_input=True`, the catalog produces
`input_signature is None` even though structured `inputs` would be empty. Android logic should drive the hint surface
off the new `inputs` array, not off `input_signature`.

### Sensitive Defaults

Until `InputArg.sensitive` exists, the gateway projection should treat string defaults as untrusted and emit
`default_display = null` for them. Numeric and bool defaults are safe.

### Loading And Error States

`LaunchHelperState.loading=true` is the initial state and `state.failureMessage` is set when the catalog fetch fails.
The hint surface must short-circuit in both cases — silent no-op rather than a partial hint based on a stale map.

### Project-Filtered Catalogs

Launch currently refreshes helpers with a `project` filter. The launch screen does not have a `LaunchedEffect(project)`
today, so changing the project does not re-fetch the catalog and the hint map can miss project-local xprompts. Add an
explicit (debounced) refresh on project change as part of this feature, not after.

## Testing Plan

### Python Tests

Add focused tests around `build_structured_xprompts_catalog()`:

- required and optional inputs become structured input records;
- `default: null` is optional with `default_display == null`;
- `is_step_input=True` inputs are omitted;
- an xprompt whose inputs are entirely step inputs round-trips with `inputs == []` and `input_signature is None`;
- `input_signature` remains unchanged for existing fixtures;
- insertion metadata uses `#` for inline xprompts;
- standalone workflows AND simple xprompts whose body has `---` segment separators both use `#!`;
- `output_schema` is never serialized to the wire;
- string defaults are not echoed in `default_display` until `sensitive` exists.

Update mobile helper bridge tests:

- `tests/test_mobile_helpers.py` — note its `data["entries"] == [...]` assertion (~line 87-100) is exact-dict-equality
  and will fail until updated for the new fields.
- `tests/test_mobile_helper_bridge_smoke.py` — same dict-equality pattern.

### Rust Gateway Tests

Update:

- `../sase-core/crates/sase_gateway/src/wire.rs` sample JSON tests;
- route tests around `/api/v1/xprompts/catalog`;
- `../sase-core/crates/sase_gateway/contracts/api_v1/mobile_api_v1.json`. The
  `committed_contract_snapshot_is_current` test (`crates/sase_gateway/src/contract.rs`) does a byte-exact comparison,
  so regenerating the snapshot must be part of the same change. Schema version stays at `1` (additive change).

### Android Tests

Update fixtures:

- `../sase-android/app/src/test/resources/fixtures/gateway/xprompt_catalog.json` — already drifts from the producer
  (uses `"bead_id"` where Python emits `"(bead_id: word)"`); regenerate from a real fixture build.
- `../sase-android/app/src/test/resources/contracts/mobile_api_v1.json`.

`MobileApiContractTest` only asserts schema version, contract name, base path, route list, and error shape, and the
DTO decoder uses `ignoreUnknownKeys = true`. Adding `inputs` and `insertion` to the wire will not break existing
contract tests on the Android side; new fields need their own decode tests.

Add Compose/UI tests:

- selecting an xprompt with required inputs shows input hints;
- selecting an xprompt without required inputs does not show hints;
- typing `#foo:` shows hints;
- typing `#foo:` for an unknown xprompt shows no hints;
- typing `#bd/work_phase_bead:` supports slash names;
- tapping `Named args` inserts a named-argument skeleton;
- launching preserves the raw prompt text exactly.

Add pure Kotlin tests for cursor detection if the parser is extracted from the composable.

## Open Design Choices

1. Whether the mobile catalog should include YAML workflows via `get_all_prompts()`.
   - Recommended: yes, because launch helper insertion is about prompt references, not only Markdown xprompt parts.
2. Whether selecting a required-arg xprompt should auto-insert `:` or only show hints.
   - Recommended: only show hints first; provide an explicit `Colon args` edit action.
3. Whether to validate argument values in Android.
   - Recommended: not in the first pass. Show types as hints and let host-side xprompt validation remain authoritative.
4. Whether hints should parse comma progress immediately.
   - Recommended: start with exact `#foo:` trigger, then add progress highlighting once the core UX is proven.
5. How to handle defaults that may be sensitive.
   - Recommended: add `InputArg.sensitive: bool = False` and gate `default_display`. Until then, omit string defaults
     entirely; only echo `INT`/`BOOL`/`FLOAT` defaults.
6. Whether the TUI should also gain an on-`:` hint trigger.
   - Out of scope here, but worth noting: the TUI uses inline-row hints (`append_input_args`) rather than a dynamic
     trigger. If parity becomes a goal, the same detector logic could land in `prompt_input_bar.py`.

## Implementation Sequence

1. Fix the Android project-change refresh gap (`LaunchedEffect(project)`) so a stale catalog cannot make hints
   silently no-op for project-local xprompts.
2. Add structured xprompt input metadata to the Python catalog projection (including `insertion`, `reference_prefix`,
   `kind`).
3. Add Rust wire records, refresh `mobile_api_v1.json`, and re-run the contract snapshot test.
4. Update Android DTOs and fixtures.
5. Replace `"#${entry.name}"` insertion with `entry.insertion ?: "#${entry.name}"` in `LaunchScreen.kt` and
   `HelpersScreen.kt`.
6. Memoize the catalog map (`remember(state.xprompts) { state.xprompts.associateBy { it.name } }`).
7. Add launch-screen prompt hint state and UI panel.
8. Add selection-trigger behavior.
9. Add typed-colon cursor-trigger behavior (handle HITL suffix and `__` aliasing in the lookup path).
10. Add focused tests in all three repos.

## Related Work

- Closed `sase-26.4.3` (Phase 3: Xprompt Catalog Endpoint And Optional PDF Attachment) is the bead that landed the
  current `MobileXpromptCatalogEntryWire`; this work extends that contract.
- Closed `sase-26.3.3` (Phase 3: Text Launch Endpoint And Mobile Launch Normalization) defines the launch payload
  shape that the inserted reference text ultimately rides on.
- No open beads currently track structured xprompt input metadata or mobile xprompt UX hints. This research is
  greenfield input for a new epic + phase beads.

This keeps the backend authoritative, keeps Android's parser intentionally shallow, and gives users the expected mobile
hint UX without changing xprompt launch semantics.
