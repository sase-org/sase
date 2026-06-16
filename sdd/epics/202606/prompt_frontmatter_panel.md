---
create_time: 2026-06-16 13:42:15
bead_id: sase-4r
tier: epic
status: done
prompt: sdd/prompts/202606/prompt_frontmatter_panel.md
---
# Plan: Frontmatter Panel for the Prompt Input Widget

## Summary

Bring the `sase ace` prompt input widget to parity with xprompt markdown files by adding a **structured Frontmatter
Panel** that renders above the prompt stack. The panel lets a user add/edit/delete the same frontmatter properties an
xprompt `.md` file supports (`name`, `description`, `tags`, `input`, `xprompts`, `skill`, `snippet`), with first-class,
beautiful editors for the two high-value structured fields (`input` and `xprompts`).

Two capabilities get special care:

1. **Local xprompts** declared in the panel's `xprompts:` field must light up `<ctrl+t>` and `<ctrl+l>` completion in
   every prompt pane exactly like global xprompts.
2. **`input` collection**: when the submitted multi-agent prompt declares inputs without defaults, the user is prompted
   (after `<ctrl-enter>`/whole-stack submit) through a typed, validated **Input Collection Modal**, and the values are
   substituted into each segment before fan-out launch.

The feature is split into **5 dependency-ordered phases**, each sized for a single agent instance.

---

## Goals

- A persistent, navigable, **beautiful** structured frontmatter editor above the top prompt pane, triggered by typing
  `---` on a new line at the very start of the prompt.
- Full add/edit/delete for every xprompt frontmatter field, with inline validation and guidance sourced from the same
  engine that powers the xprompt LSP (so the TUI panel and the editor LSP never drift).
- Local `xprompts:` definitions are immediately usable: `#_helper` completes, soft-completes, and shows argument hints
  in every pane.
- `input` declarations drive a typed, validated post-submit collection flow whose values are rendered into each agent
  segment.
- Lossless round-trip: structured panel ⇄ canonical YAML ⇄ existing `parse_multi_prompt` launch path. Nothing about the
  current multi-agent submit contract regresses.

## Non-Goals

- No new frontmatter _fields_ beyond what xprompt `.md` files already support. Parity, not expansion. (Workflow-only
  fields such as `environment`/`steps` are out of scope — those are `.yml` workflow concepts, not ad-hoc prompt
  concepts.)
- No change to how global xprompts are discovered or to the xprompt file format itself.
- Interactive input _prompting_ is a TUI concern; non-interactive CLI launch keeps today's behavior (improved error
  message only).

---

## Background: What Exists Today

Grounded in the current code (file references for the implementing agents):

- **Prompt stack model** — `src/sase/ace/tui/widgets/prompt_stack.py`. `PromptStackState` already stores
  `frontmatter: str` (raw YAML incl. delimiters), lifts a leading frontmatter block off the first pane during live `---`
  splitting (`split_selected_live`), and re-attaches it on `join()` / `attach_frontmatter()`. This is the seam the panel
  binds to.
- **Bar + panes** — `prompt_input_bar.py` composes a hidden completion `Static` (`#prompt-completion`) above a
  `#prompt-stack` `Vertical`. The completion panel is the existing precedent for "a panel above the prompt."
  `prompt_text_area.py` is the per-pane editor (vim/readline, Jinja highlight/diagnostics, `<ctrl+t>` file/xprompt
  completion, `<ctrl+l>` accept).
- **Multi-prompt parse/launch** — `src/sase/agent/multi_prompt.py::parse_multi_prompt` extracts frontmatter, pops
  `xprompts` → `parse_local_xprompt_entries` → `dict[str, XPrompt]`, and splits segments. `MultiPromptLaunchMixin`
  (`.../actions/agent_workflow/_launch_multi_prompt.py`) fans out segments and **already passes `local_xprompts` to the
  launcher**. The `input` key is parsed into `frontmatter` but **currently ignored** at launch.
- **Frontmatter schema/validation** — exists twice:
  - Python runtime: `src/sase/xprompt/loader_parsing.py`, `models.py` (`InputArg`, `InputType`, `validate_and_convert`),
    `_jinja.py` (`substitute_placeholders`).
  - **Rust LSP**: `../sase-core/crates/sase_core/src/editor/frontmatter.rs` + `crates/sase_xprompt_lsp` — field-level
    diagnostics, hover, allowed-field checks, input type parsing. This is the canonical "what's valid + guidance" engine
    and already backs an editor integration (sase-nvim).
- **Completion injection point** — `src/sase/ace/tui/widgets/xprompt_completion.py::build_xprompt_completion_candidates`
  accepts an optional `entries=` override, and `xprompt_arg_assist.py::xprompt_assist_entry_from_workflow` shows how to
  turn an `XPrompt`/`Workflow` into an `XPromptAssistEntry`. Clean seam for injecting local xprompts.

**Implication:** much of the backend plumbing exists. The net-new work is (a) a panel-oriented schema/validation surface
from core, (b) a structured frontmatter model + stack wiring, (c) the panel widget + editors, (d) local-xprompt
completion injection, and (e) the input collection modal + launch-time substitution.

---

## Rust Core Boundary Decision

Per `memory/short/rust_core_backend_boundary.md` and its litmus ("if an editor integration would need the behavior to
match the TUI, treat it as core"):

- **Core (sase-core, Rust → `sase_core_rs` binding):** the _frontmatter field schema_ (which fields exist, their kinds,
  one-line descriptions, allowed values), _field/value validation + guidance messages_, and the _input-type catalog +
  per-type rule text_. An editor LSP already owns this; the panel must consume the same source so guidance never drifts.
  Reuse/refactor `editor/frontmatter.rs`; do **not** clone its rules in Python.
- **This repo (Python/Textual):** the panel widget, keybindings, layout, the structured `PromptFrontmatter` model +
  canonical YAML serialization (presentation glue over existing Python parsers), the input collection modal, completion
  injection, and launch wiring.
- **Reused as-is (existing Python runtime):** `InputArg.validate_and_convert` for input-value coercion (it is exactly
  what launch will accept), `parse_local_xprompt_entries`, `substitute_placeholders`. The modal validates against the
  real runtime validator.

---

## UX Design

### The Frontmatter Panel

A persistent bordered region rendered **directly above the top prompt pane** (above the `#prompt-stack`). Structured,
navigable, with a status chip mirroring the existing Jinja diagnostics chip convention.

Populated example:

```
╭─ frontmatter ─────────────────────────────────────  ⟨✓⟩ ─╮
│  description   Refactor the auth module across services    │
│  tags          refactor, backend                           │
│  input        ▾                                            │
│    • service   word    (required)   target service         │
│    • dry_run   bool  = false        skip writes            │
│  xprompts     ▾                                            │
│    • _rules    "Follow the team review checklist…"         │
│  skill         false                                       │
╰─ a add · e edit · d delete · R raw · h/l fold · esc done ──╯
```

Empty (just triggered):

```
╭─ frontmatter ─────────────────────────────────────  ⟨ ⟩ ─╮
│  No properties yet.                                        │
│  Press a to add:  name · description · tags · input ·      │
│  xprompts · skill · snippet                                │
╰─ a add · R raw · esc done ─────────────────────────────────╯
```

- **Rows**: `key` (accent) + a type-styled value summary. `input` and `xprompts` render as collapsible sub-trees (one
  row per item), using the `h`/`l` reveal/hide convention already used on the Agents tab.
- **Status chip** in the border title: `⟨✓⟩` valid, `⟨! N⟩` with N issues. Invalid rows show an inline message below
  them in red, using the **guidance text from core** (Phase 1).
- **Beauty**: consistent borders/colors with the existing completion + Jinja panels; type badges; dim placeholders;
  aligned columns.

### Trigger & Focus

- **Open**: when the prompt is empty and the user types `---` followed by a newline at the very start, promote into
  frontmatter mode — remove the typed `---\n` from the body, mount the (empty) panel, and focus it. This is distinct
  from a `---` typed _after_ content, which remains a multi-agent segment separator (consistent with
  `parse_multi_prompt`: the first leading `---` pair is frontmatter; later `---` lines split segments).
- **Auto-show**: if the bar opens on a prompt that already carries frontmatter (history recall, stash restore,
  `attach_frontmatter`), the panel mounts pre-populated.
- **Move between panel and body**: a leader keymap (`,f`) focuses the panel from any pane; `<esc>`/`q` returns focus to
  the body. Leaving an empty panel removes the frontmatter entirely (no stray `---\n---`).

### Editing Model (intuitive + reliable)

Hybrid: a structured view for the common case, a raw escape hatch for the long tail.

- `a` — add property: opens a picker of fields **not yet set**, each with its core-provided one-line description;
  selecting one creates the row and drops into its editor.
- `<enter>` / `e` — edit the focused row's value with a type-appropriate editor (inline for scalars/lists; a small
  sub-form modal for `input`/`xprompts` items).
- `d` — delete the focused property/item (deleting `input`/`xprompts` removes the whole field).
- `j`/`k` move rows; `h`/`l` fold/unfold sub-trees; inside a sub-tree `a`/`d`/`<enter>` add/delete/edit items.
- `R` — **edit raw YAML**: focus a single text area holding the canonical serialized frontmatter, validated live by
  core. This is the reliability backstop and ultimate source of truth; on exit it re-parses into the structured view.

Reliability stance: the panel **owns/normalizes** the YAML (canonical serialization). We do not attempt to preserve
arbitrary hand-authored formatting/comments; the panel is the authoring surface. Unparseable raw input surfaces a core
diagnostic rather than silently dropping data.

### Local xprompts → `<ctrl+t>` / `<ctrl+l>` parity

When the panel's `xprompts:` declares helpers (e.g. `_rules`), every pane's completion must treat `#_rules` like a
global xprompt:

- `<ctrl+t>` lists it (with description + input signature),
- `<ctrl+l>` soft-completes / accepts it,
- argument hints appear when typing `#_rules(...)`.

Mechanism: parse the live frontmatter `xprompts` (existing `parse_local_xprompt_entries`), convert each to an
`XPromptAssistEntry` (mirroring `xprompt_assist_entry_from_workflow`), and merge into the `entries=` passed to
`build_xprompt_completion_candidates` and the arg-assist resolver. Because the panel keeps frontmatter live, completion
always reflects current definitions — define a helper in the panel and it is instantly usable below.

### Input Collection Modal

On whole-stack submit (`<shift+enter>`/`<ctrl-enter>`) when the frontmatter declares `input` with one or more entries
lacking defaults:

```
╭─ Inputs for this prompt ───────────────────────────────────╮
│  service    (word · required)                              │
│    target service to refactor                              │
│    > billing                                               │
│                                                            │
│  retries    (int · required)                               │
│    how many times to retry                                 │
│    > three                                                 │
│    ✗ must be a whole number                                │
│                                                            │
│  ▸ 1 optional input (dry_run = false)        [tab] reveal   │
│                                                            │
│            [⏎ launch 3 agents]       [esc cancel]          │
╰────────────────────────────────────────────────────────────╯
```

- One field per **required** input; optional inputs collapsed behind a "reveal" toggle with their defaults shown.
- Type-appropriate editors: `bool` → toggle; `int`/`float` → numeric; `word`/`line`/`path` → single line (`path` reuses
  `<ctrl+t>` file completion); `text` → multiline.
- Each field shows its `type` badge, its `description`, and the per-type rule (great guidance).
- **Live validation** via `InputArg.validate_and_convert`; confirm disabled until all required inputs are valid.
- On confirm, values are substituted into each segment via existing Jinja machinery, then the normal fan-out launch
  proceeds. Cancel returns to the prompt without launching.

---

## Phase Breakdown

> Each phase is one agent. Every phase that changes files in this repo must end green on `just check` (run
> `just install` first — workspaces are ephemeral). Phase 1 changes the `sase-core` sibling (open via
> `sase workspace open -p sase-core <N>`) and must pass its cargo tests + keep the binding importable. Phases touching
> ace options/keymaps must update the `?` help popup, the conditional footer (`keybinding_footer.py`), and
> `default_config.yml` per `src/sase/ace/AGENTS.md` and `memory/short/gotchas.md`.

### Phase 1 — Core frontmatter schema & validation API (sase-core + binding)

**Goal:** one source of truth for "what fields/inputs exist, what's valid, and the guidance text," shared by the panel
and the existing xprompt LSP.

**Scope**

- In `sase-core`, expose a panel-oriented introspection surface, refactoring/reusing `editor/frontmatter.rs` so the LSP
  and this API share rules:
  - `frontmatter_field_schema()` → ordered field descriptors: `name`, `kind` (scalar/list/bool-or-list/structured),
    `required`, one-line `description`, allowed-value hints, example.
  - `validate_frontmatter(text)` and `validate_frontmatter_field(field, value)` → structured diagnostics (message +
    guidance + severity + span) matching LSP output.
  - `input_type_schema()` → input type catalog (`word`/`line`/`text`/`path`/`int`/`float`/`bool`
    - aliases) with per-type human rule text for modal guidance.
- Expose via `sase_core_rs` (`crates/sase_core_py`).
- Provide a thin Python adapter `src/sase/xprompt/frontmatter_schema.py` (this repo) that wraps the binding into typed
  Python objects the TUI consumes, so later phases never touch binding details.

**Acceptance**: cargo tests for the new surface; binding importable; a Python smoke test exercising the adapter (schema
list non-empty, a known-good and known-bad value validate as expected). No Python rule duplication.

**Depends on**: none.

### Phase 2 — Structured frontmatter model + stack round-trip (Python, pure logic)

**Goal:** a deterministic, fully unit-tested structured model the panel binds to — mirroring how `prompt_stack.py` was
built as a non-visual model first.

**Scope**

- New `PromptFrontmatter` model in this repo: `parse(raw_yaml) → model`, `serialize(model) → canonical YAML` (incl.
  delimiters), and accessors/mutators for scalars (`name`, `description`, `tags`, `skill`, `snippet`), the `input` list
  (`InputArg`), and the `xprompts` map (`XPrompt`). Reuse `parse_yaml_front_matter`, `parse_inputs_from_front_matter`,
  `parse_local_xprompt_entries`.
- Wire into `PromptStackState`: keep the existing `frontmatter: str` contract (`join()`/`attach_frontmatter()`
  byte-stable) by serializing the model on demand; the model becomes the structured editing view over that string.
  `parse_multi_prompt` stays the launch source of truth.
- Decide `input` vs `inputs` key handling (see Design Decisions): canonical `input`, accept `inputs` as a normalized
  alias on parse.

**Acceptance**: unit tests for parse→model→serialize→parse round-trip (lossless for canonical forms), alias
normalization, and stack `join`/`attach_frontmatter` unchanged. No Textual.

**Depends on**: Phase 1 (for validation hooks; model can carry/return core diagnostics).

### Phase 3 — Frontmatter Panel widget: trigger, layout, scalar/list editing

**Goal:** the visible, navigable panel with the common-case editors and the raw escape hatch. Shippable on its own (set
`description`/`tags`/`skill`/`snippet`/`name`).

**Scope**

- Panel widget mounted above `#prompt-stack`; renders rows + status chip; inline diagnostics from Phase 1; folding for
  (not-yet-editable) `input`/`xprompts` sub-trees shown read-only.
- Trigger: leading `---`+newline at the very start opens the panel (distinct from segment separators); auto-show when
  opening on existing frontmatter; `,f` focus / `<esc>` return; empty-panel-on-exit removes frontmatter.
- Add-property picker (core schema), inline editors for scalars/lists, `d` delete, `R` raw-YAML mode (live core
  validation).
- Keymap + `?` help + footer + `default_config.yml` sync.

**Acceptance**: widget unit tests (trigger detection, add/edit/delete scalar flows, raw-mode round-trip) + PNG visual
snapshots for populated/empty/error states (see `memory/short/build_and_run.md`). `just check` green.

**Depends on**: Phases 1, 2.

### Phase 4 — Structured `input`/`xprompts` editors + local-xprompt completion parity

**Goal:** the high-value structured editing, plus the `<ctrl+t>`/`<ctrl+l>` parity for local xprompts.

**Scope**

- Sub-editors: add/edit/delete `input` items (name, type picker, default, description) and `xprompts` items (`_`-name,
  content, inputs, description), validated/guided by Phase 1.
- Completion injection: build `XPromptAssistEntry` objects from the live frontmatter `xprompts` and merge into
  `build_xprompt_completion_candidates(entries=…)` and the arg-assist resolver so `#_helper`
  completes/soft-completes/arg-hints in every pane.
- Underscore-name validation surfaced inline (reuse existing `LocalXPromptNameError` rules).

**Acceptance**: unit tests for the sub-editors and for completion injection (local entry shows up for
`<ctrl+t>`/`<ctrl+l>`/arg-hints; precedence vs global entries defined); snapshot of the structured editors. `just check`
green.

**Depends on**: Phase 3.

### Phase 5 — Input Collection Modal + launch-time substitution

**Goal:** complete the `input` story end-to-end.

**Scope**

- Modal triggered on whole-stack submit when required (default-less) inputs exist: per-input typed editor, description +
  per-type guidance (Phase 1 `input_type_schema`), live validation via `InputArg.validate_and_convert`, collapsed
  optional-inputs section, confirm/cancel.
- Launch wiring: extend the multi-prompt launch path so collected input values render into each segment via
  `substitute_placeholders` before fan-out (alongside the already-passed `local_xprompts`). Keep CLI/non-interactive
  behavior, but improve the missing-required-input error message.
- `path`-typed inputs reuse `<ctrl+t>` file completion in the modal.

**Acceptance**: unit tests for modal validation (each type, required vs optional, error guidance) and for segment
substitution at launch; snapshot of the modal (valid + error states). `just check` green.

**Depends on**: Phases 1, 2 (and benefits from 4's parsing, but is independent of the panel internals).

---

## Cross-Cutting Requirements

- **Keymap/help/footer/config sync** (per `src/sase/ace/AGENTS.md`, `memory/short/gotchas.md`): any new ace keymap or
  option updates the `?` help popup, the conditional footer, and `src/sase/default_config.yml`.
- **Uniform runtimes** (per gotchas): no runtime-specific branching — local xprompts and inputs behave identically
  across Claude/Gemini/Codex/etc.
- **Tests**: prefer pure-logic unit tests for models/parsing; PNG visual snapshots for panel and modal appearance; keep
  coverage above the CI gate.
- **Docs**: update `docs/xprompt.md` (and any prompt-input docs) to note that ad-hoc prompt frontmatter now has a
  structured panel and the same field set.

---

## Design Decisions & Assumptions (open to plan-review pushback)

1. **`input` is canonical; `inputs` is accepted as an alias.** xprompt files use `input` (singular); the panel authors
   `input` so frontmatter stays copy-paste compatible with an xprompt `.md`. We normalize a user-typed `inputs` to
   `input` on parse for ergonomics.
2. **Field set = xprompt `.md` parity only** (`name`, `description`, `tags`, `input`, `xprompts`, `skill`, `snippet`).
   Workflow-only keys are out of scope.
3. **Panel owns canonical YAML** (normalizes formatting/comments); the raw-YAML mode is the power-user/reliability
   backstop and the ultimate source of truth.
4. **Interactive input prompting is TUI-only**; CLI keeps current behavior with a clearer error.
5. **Trigger** = leading `---`+newline at the very start; a `---` after content stays a segment separator, consistent
   with `parse_multi_prompt`.
6. **Field schema + validation + guidance come from sase-core** to stay in lockstep with the xprompt LSP; input-value
   coercion reuses the existing Python `InputArg.validate_and_convert`.

## Risks & Mitigations

- **Cross-repo Rust binding (Phase 1)** is the riskiest. Mitigation: scope it to a thin introspection slice that reuses
  existing `frontmatter.rs` rules; the Python adapter isolates later phases from binding churn.
- **Lossless round-trip** of structured ⇄ YAML. Mitigation: canonical normalization (we own the YAML) + raw-mode
  backstop + Phase 2 round-trip tests.
- **Trigger ambiguity** with the existing multi-agent live-split. Mitigation: explicit "very start, empty body" rule +
  tests; reuse `parse_multi_prompt` semantics.
- **Completion precedence** between local and global xprompts. Mitigation: define and test that local `_`-prefixed
  entries are additive and namespaced by the underscore rule.

```

```
