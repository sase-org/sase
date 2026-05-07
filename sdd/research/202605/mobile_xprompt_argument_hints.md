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

`input_signature` is produced by `_format_inputs()` as display text like `(p: path, n?: line)`. It filters out step
inputs and encodes requiredness by omission of `?`. That is useful for display, but it is too lossy for a prompt-editor
feature:

- It has no stable per-input array.
- Defaults are not available except as a display convention.
- Tests and fixtures already show drift: Android fixtures use values like `"bead_id"`, while Python currently formats
  `"(path: path)"`.
- Client parsing would couple Android to punctuation rather than the backend input model.

### Android Launch UI

The launch screen is currently a raw prompt editor plus helper chips:

- `../sase-android/app/src/main/java/org/sase/mobile/ui/launch/LaunchScreen.kt`
  - Prompt is stored as `TextFieldValue`, so cursor/selection are available.
  - `LaunchHelperInsertPanel` inserts ChangeSpec tags, xprompts, and beads into the prompt.
  - Xprompt chips currently insert `#${entry.name}` unconditionally.
- `../sase-android/app/src/main/java/org/sase/mobile/ui/helpers/HelpersScreen.kt`
  - Xprompt rows copy/insert `#${entry.name}` unconditionally.

The unconditional `#` insertion is fine for simple inline xprompts, but it is incomplete for standalone workflows or
multi-agent xprompts that should use `#!`. The TUI has the correct helper in
`src/sase/xprompt/reference_display.py`: `workflow_reference_insertion(name, workflow)`.

## Existing Parser Semantics To Preserve

The shared xprompt reference parser lives in:

- `src/sase/xprompt/_parsing_references.py`
- `src/sase/xprompt/_parsing_args.py`

Important syntax rules:

- `#name`
- `#name(args)`
- `#name:arg`
- `#name:a,b,c`
- `#name: text` shorthand
- `#name:: text` shorthand
- `#!name` for standalone workflow or multi-agent xprompt references
- `#ns/name` namespaced references
- `#a__b` as a slash alias for `#a/b`

For mobile hints, the app does not need to fully reimplement expansion parsing. It only needs a lightweight cursor
detector that recognizes a reference immediately before the cursor and looks it up in the already-loaded catalog. The
backend remains authoritative at launch time.

Cursor detector scope:

- Show hints when the cursor is after an exact trailing colon for a known reference: `#foo:|`, `#!foo:|`,
  `#ns/foo:|`, `#ns__foo:|`.
- Optionally keep hints visible while the user fills comma-separated colon args: `#foo:first,|` can highlight the second
  input.
- Do not trigger on Markdown headings like `# Heading`.
- Do not trigger on unknown names.
- Do not trigger when the colon belongs to surrounding prose, URLs, or a prior completed token.

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
- `default_display`: stringified non-secret default for display only; `null` when required or default is explicit null.
- `position`: stable positional order.
- `insertion`: exact reference to insert, including `#` vs `#!`.
- `reference_prefix`/`kind`: useful for filtering and future UI display; `insertion` is the most directly useful field.

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

### Project-Filtered Catalogs

Launch currently refreshes helpers with a `project` filter. If the prompt field's project changes, the hint map should
refresh or at least mark stale helper results. A stale map can miss project-local xprompts.

## Testing Plan

### Python Tests

Add focused tests around `build_structured_xprompts_catalog()`:

- required and optional inputs become structured input records;
- `default: null` is optional with `default_display == null`;
- `is_step_input=True` inputs are omitted;
- `input_signature` remains unchanged;
- insertion metadata uses `#` for inline xprompts;
- if workflows are included, standalone workflows use `#!`.

Update mobile helper bridge tests:

- `tests/test_mobile_helpers.py`
- `tests/test_mobile_helper_bridge_smoke.py`

### Rust Gateway Tests

Update:

- `../sase-core/crates/sase_gateway/src/wire.rs` sample JSON tests;
- route tests around `/api/v1/xprompts/catalog`;
- `../sase-core/crates/sase_gateway/contracts/api_v1/mobile_api_v1.json`.

### Android Tests

Update fixtures:

- `../sase-android/app/src/test/resources/fixtures/gateway/xprompt_catalog.json`
- `../sase-android/app/src/test/resources/contracts/mobile_api_v1.json`

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

## Implementation Sequence

1. Add structured xprompt input metadata to the Python catalog projection.
2. Add Rust wire records and refresh the mobile API contract.
3. Update Android DTOs and fixtures.
4. Replace `#${entry.name}` insertion with `entry.insertion ?: "#${entry.name}"`.
5. Add launch-screen prompt hint state and UI panel.
6. Add selection-trigger behavior.
7. Add typed-colon cursor-trigger behavior.
8. Add focused tests in all three repos.

This keeps the backend authoritative, keeps Android's parser intentionally shallow, and gives users the expected mobile
hint UX without changing xprompt launch semantics.
