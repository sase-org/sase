---
create_time: 2026-06-27 16:41:25
status: done
---
# Plan: Beautiful object/structured value rendering in the Config tab Detail pane

## Problem

On the **Config** tab of the **SASE Admin Center** TUI panel, the Detail pane (right column) renders a selected field's
`default`, `effective`, and per-layer **Provenance** values. For any field whose value is structured — a `type: object`
map (e.g. `ace.lumberjack`), or an array of objects (e.g. `linked_repos` / `sibling_repos`) — the value is dumped as a
single, compact, sorted-key JSON string and then hard-wrapped by the narrow (~40%-width) pane into an unreadable blob.
This is the eyesore captured in the reference screenshot: a nested object collapses into a wall of
`{"...":{"...":[...]}}` that is impossible to scan.

The root cause is one helper, `format_value()` in `src/sase/ace/tui/modals/config_pane_rendering.py`, which renders
every non-string value as `json.dumps(value, sort_keys=True)` (compact, single line). The Detail pane is a vertical
scroll region, so it has plenty of room to render structured values across multiple lines — we just aren't using it.

## Goal

Make structured config values in the Detail pane **intuitive, reliable, and beautiful**:

- Objects/maps and arrays-of-objects render as a multi-line, indented, **syntax-highlighted YAML block** instead of a
  one-line JSON blob.
- Scalars (string / int / number / bool) and short scalar lists keep their existing compact inline form — no regression,
  no surprise.
- The treatment applies uniformly everywhere the Detail pane shows a value: `default`, `effective`, and each
  **Provenance** layer contribution.
- Rendering stays cheap (it runs on the UI thread on every arrow-key field change) and degrades gracefully on
  pathologically large or non-serializable values.

## Design

### Why YAML, not pretty-JSON

The config sources themselves are YAML (`sase.yml`), and the field-edit modal already uses block YAML
(`config_edit_helpers.yaml_dumps`) as its raw-value editor. Block YAML drops the braces, brackets, and quote noise that
make JSON hard to scan, so a list of objects like `linked_repos: [{"name": "core"}]` becomes the far cleaner:

```
- name: core
```

YAML is the right "beautiful" choice and it keeps the Detail pane visually consistent with the editor the user lands in
when they press `e`.

### What counts as "structured" (block) vs "inline"

A small, pure predicate decides the rendering mode so the behavior is obvious and testable:

- **Block** when the value is a non-empty mapping (`dict`), OR a list containing any nested mapping/list, OR any
  list/dict whose compact one-line form is wider than the pane's content width (a fixed threshold constant, ~38 cols —
  long scalar lists become blocks too).
- **Inline** (unchanged `format_value`) for everything else: scalars, empty `{}`/`[]`, and short flat scalar lists like
  `["builtin", "work"]`.

This is adaptive but deterministic — no console measurement, so it is snapshot-stable.

### Rendering mechanism (keeps the Detail pane a single `rich.text.Text`)

The Detail body is a `Static` fed a `rich.text.Text` from `render_detail()`. Rather than switching the widget to a Rich
`Group`/`Syntax` (which would break the many `render_detail(...).plain` unit-test assertions and require
widget/type-hint churn), we highlight **into** the existing `Text`:

- `rich.syntax.Syntax(code, "yaml", theme="ansi_dark", background_color="default").highlight(code)` returns a `Text`
  whose spans carry only **foreground** ANSI colors on a transparent background (verified: token spans are
  `bright_blue`/`bright_black`/… with the base style `on default`).
- ANSI named colors adapt to the active terminal/TUI theme (consistent with the rest of the UI) and map
  deterministically through the visual-test harness's pinned palette.
- We split the highlighted `Text` per line (`Text.split("\n")`, verified to return per-line `Text`), prefix each line
  with an indent, and `append_text` it into the Detail `Text`.

Net effect: `render_detail()` still returns one `Text`, `.plain` still works, the `Static` and its CSS are untouched,
and the YAML reads with highlighted keys.

### New Detail layout

Scalars are unchanged:

```
timezone
type: string
<description>

default:   America/New_York
effective: US/Pacific
...
```

Structured values switch from `label: <blob>` to a header line + indented highlighted block:

```
ace.lumberjack
type: object
<description>

default
  (none)

effective                       ← optional: winning-layer badge appended for context
  effort:
    checks:
      description: Start background checks
      interval: 300s
    recent_audit:
      description: Audit recent saves

Provenance  (low → high priority)
  ▶ user
      effort:
        checks:
          description: Start background checks
          ...
```

Provenance value blocks use a deeper indent so they nest visually under their layer name. The winning-layer badge next
to `effective` is a small clarity win (reuses `winning_layer` + `kind_badge`); include it, but it is non-essential.

### Reliability / performance

- **Deterministic output:** recursively sort mapping keys before dumping (matches today's `sort_keys=True`), and dump
  with block style and an effectively-unbounded line width so ruamel never folds a value mid-line (Textual handles
  visual wrapping). This keeps snapshots stable.
- **Size cap:** reuse the spirit of `ace/tui/util/lazy_syntax.py`. If the YAML block exceeds a modest byte/line cap
  (config values are tiny in practice), skip highlighting (plain `Text`) and, if it is genuinely huge, truncate with a
  dim "… N more lines" notice. Highlighting small YAML on each field change is sub-millisecond, but the cap guarantees
  no pathological stall.
- **Fallback:** if YAML serialization ever fails (non-JSON-able value), fall back to the existing inline `format_value`
  so the pane can never blow up.

### Scope decision (leading the design)

The user named `type: object` specifically, but arrays-of-objects (`linked_repos`, `sibling_repos`) suffer the identical
blob problem and live right next to it in the same pane. Fixing only maps would leave an obvious inconsistency, so the
block treatment covers **all structured values** (maps + nested arrays), driven by the single predicate above. Scalars
and flat short lists are deliberately left inline.

### Rust core boundary

This is presentation-only TUI rendering (Rich/Textual) and stays in this repo. The value _classification_ we depend on
(`kind` = `scalar`/`array`/`map`/`object`, `leaf`, `types`) already comes from the Rust binding `config_field_model` and
is consumed unchanged. Pretty-printing and syntax highlighting are Python presentation concerns, consistent with the
existing `lazy_syntax.py` and the edit modal's `yaml_dumps`. **No `sase-core` changes are needed.**

## Implementation outline

1. **`src/sase/ace/tui/modals/config_pane_rendering.py`** (the core change)
   - Add constants: a block-width threshold, highlight size caps, and the syntax theme (`ansi_dark`).
   - Add pure helpers:
     - `is_structured_value(value) -> bool` — the block/inline predicate.
     - a recursive key-sorter + `format_value_block(value) -> str` — sorted block YAML (huge width,
       `default_flow_style=False`), with an inline `format_value` fallback on error.
     - a highlight helper that builds the transparent-background `Syntax`, returns the highlighted `Text` (or plain
       `Text` past the cap), and an `append_value_block(text, value, *, indent)` that indents + appends it line-by-line.
   - Update `render_leaf_detail` so `default` and `effective` use the header+block form for structured values and keep
     the existing aligned inline form for scalars/unset/none. Optionally append the winning-layer badge to the
     `effective` header.
   - Update `render_provenance` so a structured `raw_value` renders as a nested indented block under the layer marker;
     scalars stay inline as today.
   - Keep `format_value` as-is for scalars and the enum-values line.

2. **`src/sase/ace/tui/modals/config_pane.py`** (compat surface)
   - Re-export the new helpers (`_is_structured_value`, `_format_value_block`, etc.) in `__all__`, following the
     module's existing underscore-alias convention so tests can import them.

3. **Tests**
   - `tests/test_config_pane.py` (pure logic):
     - `is_structured_value` truth table (dict vs empty dict, list-of-dicts vs flat list, long flat list).
     - `format_value_block` produces sorted, multi-line YAML.
     - `render_detail` for an object/map field and an array-of-objects field yields a multi-line block (`.plain`
       contains the expected `key: value` lines and newlines) and carries highlight spans; scalar fields stay
       single-line. Existing `render_detail` assertions (timezone scalar, sibling_repos deprecation text, axe section)
       must keep passing unchanged.
   - Visual PNG snapshot (`tests/ace/tui/visual/`):
     - Extend the shared fixture (`_ace_config_center_png_snapshot_helpers.py`) with an open-map (`type: object` +
       `additionalProperties`) field carrying a realistic nested value so it classifies as a `map` leaf
       (`type: object`), mirroring the screenshot's `lumberjack` case.
     - Add a snapshot test that opens the Config tab, jumps to that field, and captures
       `config_center_config_object_value_120x40`, plus generate/inspect the golden with
       `just test-visual --sase-update-visual-snapshots` and confirm it looks clean and readable. Re-check the existing
       `config_center_config_*` goldens for unintended drift.

4. **CSS** — no change expected; the Detail body is already an auto-height `Static` inside a `VerticalScroll`. Only
   revisit `styles.tcss` if the block needs extra breathing room after visual review.

5. **Docs / conventions** — no keymap, footer, or help-popup changes (no new bindings or options).

## Acceptance criteria

- Selecting an `object`/`map` field (and an array-of-objects field) shows an indented, syntax-highlighted, multi-line
  YAML block for `default`, `effective`, and each Provenance layer — no single-line JSON blobs.
- Scalar fields and short flat lists render exactly as before.
- Rendering is deterministic (stable snapshots), capped for large values, and never raises on unusual values.
- `just check` passes (lint + mypy + tests), including the new unit tests and the new + existing Config Center PNG
  snapshots.
