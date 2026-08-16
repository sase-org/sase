# Artifacts pane visual grammar

Every configured Artifacts pane — Stitches, Patch, Beads, Files, every document
provider, and a degraded provider that failed to load — renders through one shared,
contract-driven shell. This document is the reference for that grammar: the code lives
in `src/sase/ace/tui/widgets/artifacts/shell.py`.

## Layout order

The vertical order is invariant for every pane:

1. **Filter slot** — the pane's inline filter editor, collapsed when that pane's current
   query UX does not expose one.
2. **Identity/scope header** — built from the active `ArtifactsPaneContract`: the
   contract's icon/label on the contract's accent, project scope, and any active filter
   chips. Built with `shell.build_shell_scope`.
3. **State/count lane** — a compact line combining the pane's own counts
   (task/epic/phase totals, file-kind chips, commit position, and so on) with the shared
   state badge from `shell.build_state_badge` when the pane is loading or stale.
4. **Content region** — the pane's list/detail split, using the shared split-mode
   classes owned by `ArtifactsView` and a stable `*-detail-scroll` id when the contract
   declares one (`contract.detail_scroll_id`).
5. **Footer-hint lane** — the pane's configured key/label hints, built with
   `shell.build_footer_hints` so every pane uses the same separator (`  ·  `) and accent
   treatment for enabled keys, with disabled keys dimmed.

Bespoke information (Patch fold levels, Stitch repository presence, Bead triage counts,
File origin counts) belongs in the state/count lane or the pane's own rows — never in a
second identity header.

### Relation panel slot

Panes whose contract enables `PaneCapability.RELATIONS` own one host-rendered relation
panel at the bottom of the content region's list column. The panel is fed the
snapshot-built `RelationIndex`; widgets never build relation edges on highlight or
keypress paths.

The host assigns relation key roles from declaration order and relation kind. The first
declared hierarchy relation is the ancestor mode (`<`), its declared hierarchy inverse
is the descendant mode (`>`), every family relation participates in sibling/family mode
(`~`), and link relations render as rows without taking a relation key mode. A pane or
provider names relation properties; it does not assign keys.

Each visible section uses the declared relation label as its uppercase header, appends
`(N hidden)` when pane-supplied facts hide targets, and renders dangling same-pane
targets dimmed with a `(missing)` marker. Cross-pane link rows show their destination
pane id so the target switch is explicit.

## State precedence

Visible state is a closed `ArtifactsPaneState` enum, resolved by
`shell.resolve_pane_state` from an immutable, purely presentational
`ArtifactsShellState` record. Precedence, most to least specific:

| State      | Condition                                                                                             |
| ---------- | ----------------------------------------------------------------------------------------------------- |
| `degraded` | A contract/discovery failure, or an initial load failure with no usable content.                      |
| `loading`  | First load for the current scope, with no cached content yet.                                         |
| `stale`    | Usable content from the current scope remains while a refresh is running or a runtime error occurred. |
| `empty`    | The current scope loaded successfully but has no rows.                                                |
| `results`  | Usable rows are present and no refresh is in flight.                                                  |

`ArtifactsShellState` fields (`is_degraded`, `is_loading`, `has_error`, `has_content`,
`row_count`, `has_active_filter`) must already be computed by the pane; the resolver
never touches the filesystem, invokes provider code, or resolves providers.

### Required information per state

- **Loading**: a compact progress affordance (`Loading…`) in the state lane. Panes never
  substitute a blank list — the list keeps whatever rows it already has (there are none
  on a genuine first load).
- **Stale**: the current selection, list, and detail stay visible; the shell overlays a
  `Refreshing` badge (or, when the refresh ended in an error but cached content remains,
  an `⚠ <message>` badge) rather than rebuilding from disk or clearing content on the
  event loop.
- **Empty**: an empty-inventory card uses `contract.empty_state` (title + body). A
  no-match card — rows exist but the active filter excludes all of them — names the
  active filter and the key that edits or clears it. `shell.build_empty_card` picks
  between the two from `has_active_filter`.
- **Degraded**: the tab stays named and navigable. The card shows provider kind,
  configuration source, the stable diagnostic code when available, the validation
  problem, and (when known) a direct recovery hint (`error_source`).
  `shell.build_degraded_card` renders `(hero, card)` from exactly those fields — never
  provider code.
- **Results**: usable rows are present; no badge is shown (the pane's own count text is
  the signal).

## Accent rules

- Every renderer consumes `contract.accent` (or an explicit `accent` parameter that
  defaults to the pane's pinned built-in color) — never `ARTIFACTS_ACCENTS[<pane id>]`
  inside `shell.py`. This is what stops a document-provider pane like `ref:research`
  from rendering Plans-purple: before this phase, `plans_rendering.py` hard-coded
  `ARTIFACTS_ACCENTS["plans"]` in every builder, so a Research pane using the generic
  document adapter still painted Plans' pinned purple. The built-in Plan adapter keeps
  its pinned purple through the same accent-parameter path rather than a special case.
- The provider accent palette (`_PROVIDER_ACCENTS` in `_artifact_tab_descriptors.py`) is
  nine hex colors chosen in OKLCH (a perceptually uniform color space) at a shared
  lightness/chroma band, then pinned as plain hex so runtime assignment
  (`_provider_accent_for_kind`, unchanged SHA-256-of-`ref_kind` hashing) stays
  dependency-free and deterministic. Every entry clears a WCAG contrast ratio of at
  least 3.3 against the app's dark (`#121212`/`#1E1E1E`) and light (`#E0E0E0`/`#D8D8D8`)
  shell surfaces and against the identity chip's `#1A1A1A` text, and is at least `0.085`
  OKLab units from every other palette entry and from every reserved `ARTIFACTS_ACCENTS`
  / `EXTERNAL_ACCENT` color. `tests/ace/tui/test_artifacts_provider_palette.py` pins all
  of these properties, plus that installing or removing an unrelated `ref_kind` cannot
  repaint an existing tab (the hash is a pure function of the kind string alone) and
  that provider discovery never mutates `ARTIFACTS_ACCENTS`.
- Filter bars carry their own `ACCENT` (used for match-count highlighting); `FilterBar`
  accepts an optional `accent` constructor kwarg so a document-provider pane's filter
  bar uses its contract accent instead of a pinned default.

## Accessibility constraints

- Text-on-accent chips (the identity header's `" Label "` chip) always pair `#1A1A1A`
  text with the accent as background; the provider palette's chip-contrast check exists
  specifically to keep that combination legible.
- Accent-as-foreground text (scope labels, count numbers, footer keys) is checked
  against both shell surfaces so a color that reads fine in the dark theme cannot go
  illegible in the light theme, and vice versa.
- The provider palette deliberately avoids hues too close to `EXTERNAL_ACCENT`
  (`#FF5F5F`, the shared error/warning red) so a provider's identity color is never
  mistaken for an error state.

## Provider-data boundary

No renderer in `shell.py` may look up a pane id in `ARTIFACTS_ACCENTS`, invoke provider
code, resolve providers, touch the filesystem, or perform data-scaled work. Every shell
function takes an already-resolved `ArtifactsPaneContract` and small, pre-computed
presentation values (booleans, counts, strings) — never a provider spec, a callback, or
a widget. Composition stays host-owned: `ArtifactsView` passes the resolved contract and
descriptor diagnostics into every pane; no sidecar-provided markup, widget, command
string, or color ever reaches the shell.

## Extension checklist

Adding a new built-in pane or generalizing an existing one to use more of the shell:

1. Make sure the pane has a compiled `ArtifactsPaneContract` (built-in adapter table in
   `_artifact_tab_contract.py`, or the schema-v1 provider path for document providers).
2. Build the identity header with
   `shell.build_shell_scope(label=contract.label, accent=contract.accent, ...)` instead
   of a pane-local accent chip.
3. Derive `ArtifactsShellState` from the pane's own lifecycle fields (loading flag, load
   error, whether cached content matches the current scope, row count, active-filter
   flag) and resolve it with `shell.resolve_pane_state`. `ArtifactsSnapshotPane`
   subclasses get this for free by overriding
   `_snapshot_matches_scope`/`_snapshot_row_count` and calling `self.pane_state(...)`.
4. Feed the resolved state into `shell.build_state_badge` for the state/count lane, and
   into `shell.build_empty_card` for the empty/no-match surface.
5. Build the footer with
   `shell.build_footer_hints(keymap_pairs, accent=contract.accent)`.
6. Add the pane's descriptor to the conformance harness coverage in
   `tests/ace/tui/artifacts_contract/harness.py` (already automatic for every resolved
   sub-tab) and, for a genuinely new fixture shape, exercise `PANE_CONFORMANCE_CHECKS`
   directly the way `test_degraded_descriptor_satisfies_every_conformance_check` does.
7. Add or update the PNG snapshot for the new surface, inspecting
   `.pytest_cache/sase-visual/` actual/expected/diff artifacts before accepting a
   golden.

## Patch's contract-in/spec-out asymmetry

Patch is contract-in like every other pane: `ArtifactsPatchesPane` receives a compiled
`ArtifactsPaneContract` and its accent, label, and capabilities come from that contract
exactly like Stitches, Beads, or Files. But Patch is not spec-out — its query, grouping,
detail rendering, and action surface remain the pre-existing, heavily specialized Patch
implementation (`PatchInfoPanel`, `PatchList`, `PatchDetail`, the modal query editor),
and this phase does not migrate any of that to the generic document/snapshot pipeline.
Patch's existing empty state already routes through `TabQuickStart`
(`_actions/patch/_onboarding.py` shows/hides `#patch-quickstart-panel`); this phase
treats that established mechanism as Patch's canonical empty surface rather than
introducing a second one. A literal shared identity-header _row_ was deliberately not
added to Patch's layout in this phase: Patch is covered by a very large number of PNG
snapshots across otherwise-unrelated test suites (agents, axe, config center, and more
all screenshot the default view), and inserting a new row would shift every one of them
for no behavioral benefit — `PatchInfoPanel` already carries Patch's identity and
state/count information. That migration is left as explicit follow-up work, tracked
separately from this phase's bead.
