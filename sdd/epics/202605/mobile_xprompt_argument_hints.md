---
create_time: 2026-05-06 21:47:11
status: done
prompt: sdd/prompts/202605/mobile_xprompt_argument_hints.md
bead_id: sase-27
tier: epic
---
# Mobile XPrompt Argument Name/Type Hints

## Goal

Add mobile support for xprompt argument name/type hints when a user selects an xprompt with visible required inputs or
types a cursor-position reference such as `#foo:` / `#!foo:` in the Android launch prompt.

The implementation spans three repositories:

- `sase_100`: Python xprompt catalog projection and mobile helper bridge.
- `../sase-core`: Rust gateway wire structs, route pass-through, and committed mobile API contract.
- `../sase-android`: Kotlin DTOs, fixtures, canonical xprompt insertion, launch prompt hint state, and Compose UI.

The backend remains authoritative for xprompt parsing and launch validation. Android should use a shallow cursor
detector only to decide when to show hints; it should not parse `input_signature` as schema.

## Current State

The recently committed research note `sdd/research/202605/mobile_xprompt_argument_hints.md` identifies the right source
metadata and the current gaps:

- Python already has `InputArg.name`, `InputArg.type`, `InputArg.default`, and `InputArg.is_step_input`.
- Visible mobile inputs are `workflow.inputs` / `xprompt.inputs` filtered by `not inp.is_step_input`.
- Requiredness is `inp.default is UNSET`.
- `input_signature` is display-only text produced by `_format_inputs()` and is too lossy for mobile editor behavior.
- Android currently hard-codes `"#${entry.name}"` in both `LaunchScreen.kt` and `HelpersScreen.kt`.
- TUI already has canonical insertion helpers in `src/sase/xprompt/reference_display.py`, including `#!` for standalone
  workflows and simple xprompts whose body contains multi-agent `---` segment separators.
- Launch helper refresh is tied to `helperRepository` and `helperEventVersion`, but not directly to `project`, so
  project-local xprompts can be stale after the user changes the project field.

## Product Behavior

1. Selecting an xprompt helper inserts `entry.insertion ?: "#${entry.name}"`.
2. If the selected entry has required visible inputs, show a compact hint panel under the prompt field.
3. Do not auto-append `:` by default. Provide concrete edit actions:
   - `Colon args`: rewrite the selected reference to `#foo:` and place the cursor after `:`.
   - `Named args`: rewrite the selected reference to `#foo(arg1=, arg2=)` and place the cursor after the first `=`.
4. Typing an exact trailing reference colon shows the same hint panel for known entries:
   - `#foo:`
   - `#!foo:`
   - `#ns/foo:`
   - `#ns__foo:`
   - `#foo!!:`
   - `#foo??:`
5. Unknown references, non-reference prose, URLs, and `#foo+` do not trigger hints.
6. The launch request should preserve the raw prompt text exactly; hints are editor UI only.

## Wire Shape

Extend xprompt catalog entries with additive metadata:

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

Compatibility guidance:

- Python should always emit `insertion`, `reference_prefix`, `kind`, and `inputs`.
- Rust and Android should accept missing `insertion` and `inputs` during rollout by defaulting to fallback insertion and
  an empty input list.
- Keep gateway `GATEWAY_WIRE_SCHEMA_VERSION = 1`; this is additive.
- Do not serialize `InputArg.output_schema`.
- Until xprompt inputs support a first-class `sensitive` flag, emit `default_display = null` for string defaults.
  Numeric and boolean defaults may be displayed. Explicit YAML `null` remains optional with `default_display = null`.

## Phase 1: Python Catalog Projection

Owner: one SASE repo agent.

Implement structured xprompt input metadata in `sase_100`.

Scope:

- Add a `StructuredCatalogInput` dataclass to `src/sase/xprompt/catalog.py`.
- Extend `StructuredCatalogEntry` with:
  - `insertion: str`
  - `reference_prefix: str`
  - `kind: str`
  - `inputs: list[StructuredCatalogInput]`
- Use `workflow_reference_insertion()`, `workflow_reference_prefix()`, and `workflow_kind_value()` where possible.
- Preserve current `input_signature` formatting for display compatibility.
- Filter out `is_step_input=True`.
- Treat `default is UNSET` as required.
- Omit string defaults from `default_display`; allow safe numeric/bool default display.
- Update `src/sase/integrations/_mobile_helper_catalog.py` to emit the new fields.
- Add/update tests in `tests/test_xprompt_catalog.py` and `tests/test_mobile_helpers.py`.

Decision for this phase:

- Prefer moving the structured mobile catalog to the unified `get_all_prompts()` view so YAML workflows and converted
  Markdown xprompts share the canonical reference helpers. If that creates too much risk, keep `get_all_xprompts()` in
  Phase 1 but still emit canonical insertion for converted simple xprompts, and leave workflow-inclusive cataloging as a
  documented follow-up before Android relies on standalone workflow insertion.

Acceptance:

- Required, optional, explicit-null, and all-step-input cases are covered.
- `input_signature` snapshots remain compatible except where tests intentionally gain new fields.
- Multi-agent simple xprompts and standalone workflows have `#!` insertion if the unified prompt path is adopted.
- `output_schema` does not appear in any bridge JSON.

Verification:

```bash
just install
.venv/bin/pytest tests/test_xprompt_catalog.py tests/test_mobile_helpers.py
just check
```

## Phase 2: Rust Gateway Wire And Contract

Owner: one `../sase-core` agent.

Make the gateway preserve the new helper fields and refresh the committed API contract.

Scope:

- Add `MobileXpromptInputWire` in `../sase-core/crates/sase_gateway/src/wire.rs`.
- Extend `MobileXpromptCatalogEntryWire` with:
  - `insertion: Option<String>`
  - `reference_prefix: Option<String>`
  - `kind: Option<String>`
  - `#[serde(default)] inputs: Vec<MobileXpromptInputWire>`
- Update wire serialization tests and static helper bridge fixtures.
- Update route tests around `/api/v1/xprompts/catalog`.
- Update `src/contract.rs` type map.
- Regenerate `crates/sase_gateway/contracts/api_v1/mobile_api_v1.json`.
- Keep schema version at `1`.

Acceptance:

- Older Python bridge output without the new fields still deserializes.
- New Python bridge output round-trips through Rust and reaches clients.
- Contract snapshot is byte-current.

Verification:

```bash
cd ../sase-core
cargo run -p sase_gateway -- --contract-out crates/sase_gateway/contracts/api_v1/mobile_api_v1.json
cargo test -p sase_gateway committed_contract_snapshot_is_current
cargo test -p sase_gateway xprompt_catalog
cargo test -p sase_gateway
```

## Phase 3: Android DTOs, Fixtures, And Canonical Insertion

Owner: one `../sase-android` agent.

Teach Android to decode the new fields, update fixtures, and use backend-supplied insertion strings before adding hint
UI.

Scope:

- Add `MobileXpromptInputWire` in `HelperWire.kt`.
- Extend `MobileXpromptCatalogEntryWire` with nullable/defaulted:
  - `insertion: String? = null`
  - `referencePrefix: String? = null`
  - `kind: String? = null`
  - `inputs: List<MobileXpromptInputWire> = emptyList()`
- Update `app/src/test/resources/fixtures/gateway/xprompt_catalog.json`.
- Update `app/src/test/resources/contracts/mobile_api_v1.json` from the Rust contract snapshot.
- Replace hard-coded `"#${entry.name}"` insertion/copy in:
  - `LaunchScreen.kt`
  - `HelpersScreen.kt`
- Add a small local helper such as `entry.referenceText()` returning `entry.insertion ?: "#${entry.name}"`.
- Add `LaunchedEffect(project)` or an equivalent debounced project-change refresh in `LaunchScreen.kt`, making sure it
  does not duplicate the initial helper fetch unnecessarily or flash stale helper state.

Acceptance:

- Existing fixture decode tests pass with the new fields.
- Older fixture-like JSON without the new fields still decodes.
- Helper chips and rows use `#!` when the backend provides it.
- Changing the project field refreshes project-scoped helper catalogs.

Verification:

```bash
cd ../sase-android
./gradlew testDebugUnitTest --tests org.sase.mobile.data.api.GatewayDtoFixtureTest
./gradlew testDebugUnitTest --tests org.sase.mobile.data.helpers.HelperRepositoryTest
./gradlew testDebugUnitTest --tests org.sase.mobile.data.api.MobileApiContractTest
./gradlew testDebugUnitTest
```

## Phase 4: Android Hint Model And Selection-Triggered UI

Owner: one `../sase-android` agent.

Add the reusable hint state and compact prompt-adjacent UI, triggered when the user selects an xprompt helper with
required inputs.

Scope:

- Add a small model:
  - `ActiveXpromptArgHint(entry, activeIndex, triggerRangeOrReferenceRange)`
  - helper methods for visible/required inputs and default display text
- Build `catalogByName` with `remember(helperState.xprompts) { ... }`.
- Add compact `XpromptArgHintPanel` directly below the prompt `OutlinedTextField`.
- Render required inputs first and optional inputs dimmed.
- Add `Colon args` and `Named args` edit actions that mutate the current `TextFieldValue` safely.
- When an xprompt helper chip is tapped, insert `entry.referenceText()` and open the hint panel only if it has required
  inputs.
- Keep hints silent while helper state is loading or failed.

Acceptance:

- Selecting a required-input xprompt shows hints.
- Selecting a no-required-input xprompt does not show hints.
- `Colon args` and `Named args` preserve surrounding prompt text and place the cursor correctly.
- Launch still sends exactly the prompt text visible in the field.

Verification:

```bash
cd ../sase-android
./gradlew testDebugUnitTest --tests 'org.sase.mobile.ui.launch.*'
./gradlew testDebugUnitTest
```

## Phase 5: Android Typed-Colon Cursor Detector

Owner: one `../sase-android` agent.

Add the mobile-only cursor detector that shows the hint panel when the cursor is after a typed xprompt colon.

Scope:

- Extract pure Kotlin parsing functions from the composable layer, for example:
  - `activeXpromptArgHint(value: TextFieldValue, catalogByName: Map<String, MobileXpromptCatalogEntryWire>)`
  - `parsePromptReferenceToken(token: String)`
- Mirror the host parser's lightweight semantics:
  - valid leading context is start, whitespace, or `(` / `[` / `{` / `"` / `'`
  - marker is `#` or `#!`
  - names support slash namespaces and `__` alias lookup
  - strip `!!` / `??` before catalog lookup
  - trigger on exact trailing `:`
  - do not trigger on `+`, unknown names, completed prose tokens, or non-collapsed selection
- Keep the first implementation at exact-colon trigger. Comma progress highlighting can be a follow-up unless the agent
  can add it with focused tests and no UI churn.

Acceptance:

- `#foo:` and `#!foo:` show hints for known entries.
- `#bd/work_phase_bead:` and `#bd__work_phase_bead:` resolve to the same catalog entry.
- `#foo!!:` and `#foo??:` show hints.
- `foo#bar:`, URLs, unknown references, and `#foo+` do not show hints.

Verification:

```bash
cd ../sase-android
./gradlew testDebugUnitTest --tests 'org.sase.mobile.ui.launch.*'
./gradlew testDebugUnitTest
```

## Phase 6: Cross-Repo Integration, Docs, And Hardening

Owner: one final integration agent with all three repos available.

Validate the full path from Python bridge JSON through Rust gateway to Android UI, update docs, and close remaining
contract drift.

Scope:

- Run the Python helper bridge and inspect a real `xprompt-catalog` response with structured `inputs`.
- Start or fake the Rust gateway and confirm `/api/v1/xprompts/catalog` preserves new fields.
- Confirm Android fake gateway fixture matches the current contract shape.
- Update docs that describe the mobile xprompt catalog:
  - `docs/mobile_gateway.md`
  - `../sase-core/crates/sase_gateway/README.md`
  - `../sase-android/README.md` only if build/test or contract guidance changes.
- Add any missing smoke test that catches field loss across the bridge boundary.

Acceptance:

- The Android app can show argument hints using fields produced by real SASE catalog data.
- Contract snapshots in `../sase-core` and `../sase-android` agree.
- All touched repos are clean except intended changes.

Verification:

```bash
cd /home/bryan/projects/github/sase-org/sase_100
just install
just check

cd ../sase-core
cargo test -p sase_gateway

cd ../sase-android
./gradlew testDebugUnitTest lintDebug assembleDebug
```

## Risks And Guardrails

- Rust-core boundary: xprompt discovery and input metadata are currently Python-owned host behavior, so the source
  projection belongs in `sase_100`, with Rust only preserving the mobile wire contract.
- Compatibility: use nullable/defaulted fields in Rust and Android so partially landed phases do not break existing
  helper calls.
- Sensitive defaults: do not expose string defaults to mobile until `InputArg` supports explicit sensitivity metadata.
- Parser drift: Android's detector should stay deliberately narrow. Host-side xprompt expansion remains authoritative.
- Project scoping: project-change helper refresh should land before hint UI is judged complete.
- File ownership: each phase should avoid opportunistic refactors; Android phases will touch overlapping files, so they
  should run sequentially.

## Suggested Phase Order

1. Python catalog projection.
2. Rust wire and contract.
3. Android DTOs, fixtures, canonical insertion, and project refresh.
4. Android selection-triggered hint UI.
5. Android typed-colon detector.
6. Cross-repo integration and docs.
