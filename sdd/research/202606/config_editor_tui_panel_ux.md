# Config Editor TUI Panel — UX Research

## Question

What does the UX of an *ideal* solution look like for a new `sase ace` TUI panel that lets a user view and
set SASE configuration fields across **any and all** supported SASE configuration files?

This document maps the current configuration system, names the hard UX problems unique to SASE's
multi-file/multi-layer config, surveys prior art, and proposes a concrete, opinionated UX with mockups,
interaction flows, and keybindings — plus alternatives and an implementation surface.

## TL;DR — Recommended UX

A new **`Config` tab** (4th tab alongside PRs / Agents / AXE) built as a **master–detail, schema-driven
editor**:

- **Left pane** — a searchable, collapsible **tree** of config sections → fields, generated from
  `config/sase.schema.json`. Badges flag fields that are *modified* (≠ default) and *which layer* sets them.
- **Right pane** — a **detail editor** for the selected field that shows the schema description, type, default,
  the **effective value**, and a **provenance strip** (the per-layer stack showing exactly which file wins and
  why). The editor widget is chosen by schema type: toggle for `boolean`, select for `enum`, stepper for
  `integer`, input for `string`, sub-editors for `object`/`array`.
- **A scope selector** (think VS Code's *User / Workspace* tabs or git's `--global/--local`) controls the single
  most important decision: **which file an edit is written to**. Default destination is the user global
  `~/.config/sase/sase.yml`.
- **A "Save" flow that previews a YAML diff** of the target file before writing, validates against the schema
  live, and **preserves comments/formatting** via round-trip YAML.
- **A raw-YAML escape hatch** (`e` to open the selected section's slice in the editor) for the handful of
  complex/free-form sections (`keymaps`, `axe.lumberjacks`, `xprompts`) that don't fit a generated form.

The two killer features that distinguish this from "an editor on a YAML file" are **provenance** (*why does this
field have this value, and which file would I edit to change it?*) and **scope-aware writes** (*my edit lands
where I intend it to*). These directly answer the #1 SASE config support question: "I changed it and it didn't
take effect."

---

## Current State (grounded findings)

### Configuration is layered across up to 5 files, merged at load

Precedence, lowest → highest (`src/sase/config/core.py:289-363`, `_deep_merge` at `:92-139`):

| # | Layer | Path | Writable? | List merge |
|---|-------|------|-----------|------------|
| 1 | Bundled defaults | `src/sase/default_config.yml` (in-package) | No (read-only) | base |
| 2 | Plugin defaults | each plugin's `default_config.yml` (entrypoint group `sase_config`) | No | **concatenate** |
| 3 | User global | `~/.config/sase/sase.yml` | **Yes** | **replace** |
| 4 | User overlays | `~/.config/sase/sase_*.yml` (sorted) | **Yes** | **concatenate** |
| 5 | Local project | `./sase.yml` (CWD) | **Yes** | **concatenate** |

Notes that matter for UX:
- **Lists behave differently per layer.** The user global layer **replaces** list values; overlays and local
  config **concatenate**. This is invisible in plain YAML and is a classic footgun.
- The **`sase ace` TUI disables the local layer** (`set_include_local_config(False)`) so the editor doesn't
  inherit the repo it happens to be sitting in. A config panel must decide deliberately whether local config is
  in scope.
- Load is memoized on the stat tokens (mtime+size) of all candidate files (`load_merged_config`), so a panel
  can cheaply detect external edits and refresh.

### A rich JSON Schema already exists — this is the enabler

`config/sase.schema.json` (Draft-07, 976 lines) covers **22 top-level sections** with **164 field
descriptions, enums, defaults, and constraints** (`minLength`, types). It is the validation source of truth
(`tests/test_config_schema.py`) and is already exposed via `sase path config-schema`
(`src/sase/main/entry.py:250-261`). `additionalProperties: false` makes it strict.

Representative leaf fields show the schema is **form-ready today**:

```
ace.inactive_seconds        integer   default=600    "Seconds of inactivity before auto-sleep"
ace.prompt_completion.auto  enum?     default="soft" "Automatic prompt completion mode…"
mobile_gateway.push_provider enum=[disabled,test,fcm] default="disabled" "Push notification provider…"
mobile_gateway.bind_address string    default="127.0.0.1" "Host address to bind the mobile gateway."
axe.max_agent_runners       integer   default=3      "Maximum concurrent agent runners…"
```

Implication: **the panel's form should be *generated* from the schema**, not hand-built. New config fields then
appear in the UI automatically when the schema is updated — no parallel maintenance.

### There is almost no write-back today — but the surgical-edit pattern exists

Config is effectively read-only from the app's perspective. The only existing write paths:
- `insert_xprompt_into_config()` (`src/sase/ace/tui/modals/xprompt_config_yaml.py:48-147`) — line-based
  insertion of a new xprompt into a chosen `sase.yml`, kept alphabetically sorted.
- `write_sdd_init_config()` (`src/sase/main/sdd_init_config.py:76-96`) — surgical update of
  `sdd.version_controlled` that **preserves formatting and comments**.

Both are precedents for "edit a YAML field without nuking the user's comments/formatting." Neither is general.

### The CLI surface is read-only

`sase config layers` (per-layer breakdown w/ merge strategy, keys, deprecated/unsupported keys),
`sase config show [-k KEY]` (dump merged YAML), `sase config mentor-match` — all read
(`src/sase/main/parser_commands.py:133-165`, `src/sase/main/config_handler.py`). **There is no
`sase config set`.** Today a user changes config by hand-editing YAML. `sase config layers` already computes
exactly the provenance data a UI provenance strip needs.

### The Rust core already knows the layer paths

`sase-core/crates/sase_core/src/xprompt_catalog.rs` enumerates the same layer paths (`config`, overlays,
`local_config`, workspace) and has `load_yaml_mapping`. Per `memory/rust_core_backend_boundary.md`, config
resolution + provenance + write-back is squarely **core backend logic** (a future web app, CLI `config set`,
and the editor LSP would all want identical behavior). The schema is the shared contract.

### The TUI is a mature host for a new panel

`src/sase/ace/tui/app.py:70` — `TabName = Literal["changespecs", "agents", "axe"]`; tabs are sibling
containers toggled via a `hidden` CSS class and `watch_current_tab` (`:320`). Adding a 4th tab is a
well-trodden path. Reusable building blocks already exist: `FilterInput`/readline inputs, `OptionList` +
`OptionListNavigationMixin` (vim `j/k`), `ConfirmActionModal`, live-validation forms (`input_item_modal.py`),
grouped pickers (`model_picker_modal.py`), and a conditional `keybinding_footer`. Keymaps are config-driven
(`ace.keymaps`, `keymaps/loader.py`) — the panel inherits the same leader/mode infrastructure.

### Scale of the field space

~340 leaf fields total; **~70% are simple scalars** (bool/int/float/str/enum) that a generated form handles
trivially. The complex minority:
- **`ace.keymaps`** — 2-tier, ~48 app bindings + mode submaps (action→key strings).
- **`axe.lumberjacks`** — named map of lumberjacks, each with a `chops` list of objects and duration strings
  (`"90s"`).
- **`llm_provider.retry`** — per-provider repeating shape (lists of patterns/wait-times).
- **`xprompts`** — Jinja2 template bodies; effectively authored content, not "settings."
- **Free-form maps** — `ace.snippets`, `vcs_provider.pr_tags`, `xprompt_aliases` (open key→value).

---

## The Core UX Challenges

1. **"Where does my edit go?" (scope/destination).** With 3 writable layers, the panel must make the write
   target explicit and obvious, with a sane default, or users will edit the "wrong" file.
2. **"Why is it this value?" (provenance).** The effective value can come from any of 5 layers. Users need to
   *see the stack* to understand and debug overrides. This is the feature plain YAML editors can never give.
3. **List replace-vs-concatenate.** A surprising, layer-dependent semantic. The UI must surface it where it
   bites (editing a list at the user-global layer replaces; at overlay/local it appends).
4. **Discoverability across ~340 fields.** Needs search, categorization, descriptions inline, and a
   "modified-only" filter so users can audit what they've actually changed.
5. **Type-appropriate editing.** A bool should be a toggle, an enum a select, a path an input with completion —
   not free-text YAML. The schema makes this automatic.
6. **Graceful handling of complex/free-form sections.** Keymaps, lumberjacks, xprompts, and open maps don't fit
   a flat form; the panel needs specialized sub-editors and/or a raw-slice escape hatch — without pretending
   they're simple scalars.
7. **Safety: validation, preview, no clobbering.** Edits must validate against the schema *before* write,
   preview the diff, and preserve the user's comments and key ordering.
8. **Consistency with `sase ace`.** Vim-style navigation, leader/mode keys, modal patterns, and footer hints
   must match the rest of the TUI so the panel feels native.

---

## Prior Art (what to borrow)

| Tool | Pattern worth stealing | Caveat |
|------|------------------------|--------|
| **VS Code Settings UI** | Schema-driven widgets; **User vs Workspace scope tabs**; search-first; per-field "reset to default"; "modified" filter; "Edit in settings.json" escape hatch; gutter dot for non-default values. | Its 2-pane (table-of-contents + list) is the closest analog to what we want. |
| **git config** | The mental model of **scopes** (`--system/--global/--local`) and `git config --show-origin` (= provenance). Users already think this way. | CLI-only; no discovery. |
| **k9s** | Native TUI feel: `:`-command to jump, `/` to filter, vim nav, breadcrumb of context, fast refresh. | Read-mostly; little inline editing. |
| **lazygit** | Panel-of-panels layout, contextual keybinding footer, confirmation + diff-preview before mutating. | — |
| **which-key / Neovim** | Discoverable leader-mode menus for keymap-like nested config. | — |
| **npm/cargo config** | "effective config" vs "where set" reporting; per-key origin. | CLI-only. |
| **Datadog/Grafana settings** | Inline validation with red/green field states and helptext from schema. | Web, not TUI. |

The synthesis: **VS Code's schema-driven form + scope tabs**, rendered with **k9s/lazygit TUI ergonomics**,
plus **git's provenance model** made visual.

---

## Proposed Ideal UX

### Layout — a master/detail `Config` tab

```
┌─ PRs ─ Agents ─ AXE ─[ Config ]──────────────────────────────────────────────┐
│ Scope:  ● User (~/.config/sase/sase.yml)   ○ Overlay ▾   ○ Local (./sase.yml) │
│ Filter: /push_                                            [m] modified only ▢  │
├───────────────────────────────┬───────────────────────────────────────────────┤
│ ▾ mobile_gateway            ● │  mobile_gateway.push_provider                   │
│     bind_address              │  ───────────────────────────────────────────   │
│     port                      │  Push notification provider for mobile clients. │
│   ▸ push_provider          ●  │                                                 │
│     fcm_project_id            │  Type: enum     ◂ disabled │ test │ fcm ▸       │
│ ▸ ace                      ●  │  Value:  ▌fcm▐                                  │
│ ▸ axe                         │  Default: disabled                              │
│ ▸ llm_provider             ●  │                                                 │
│ ▸ vcs_provider                │  Provenance ──────────────────────────────────  │
│ ▸ telemetry                   │   ● user     ~/.config/sase/sase.yml   fcm  ★   │
│ ▸ workspace                   │   ○ overlay  (unset)                            │
│   timezone                    │   ○ default  (built-in)                disabled │
│   use_chezmoi                 │                                                 │
│   precommit_command           │  [enter] edit  [d] reset-to-default  [g] go-to  │
├───────────────────────────────┴───────────────────────────────────────────────┤
│ ● modified   ★ effective       [/]filter [tab]scope [s]save [e]raw-yaml [?]help │
└────────────────────────────────────────────────────────────────────────────────┘
```

### 1. Navigation (left pane)

- A **collapsible tree** mirroring the schema's structure (sections → nested objects → leaf fields). `h`/`l`
  collapse/expand (consistent with the Agents tab tree), `j`/`k` move, `g`/`G` top/bottom.
- **`/` opens a fuzzy filter** over field paths *and* descriptions; matching fields stay visible with their
  ancestors. This is the primary discovery mechanism for 340 fields.
- **Badges:** a `●` marks any field whose effective value ≠ default; the badge color/letter encodes the
  *winning layer* (U/O/L/P/D). **`m` toggles "modified only"** to audit exactly what the user has changed across
  all files at a glance.
- A **`:` command** (k9s-style) jumps straight to a dotted path (`:mobile_gateway.port`).

### 2. The detail/editor pane (right)

Generated from the schema for the selected leaf:
- **Header:** dotted path + one-line `description`.
- **Editor widget by `type`:** `boolean` → toggle/switch; single `enum` → inline left/right select (reuse the
  `OptionList`/picker pattern); `integer`/`number` → stepper + input with min/max from schema; `string` → input
  (with path completion when the field name/description implies a path); `object`/`array` → "open sub-editor"
  affordance (see §6).
- **Default** shown explicitly; **`d` resets** the field in the current scope (deletes the key from that file so
  the lower layer wins again — *not* writing the literal default value).
- **Live validation** against the schema as you type; invalid input shows inline red helptext and blocks save.

### 3. The provenance strip (the differentiator)

For the selected field, render the **layer stack** exactly like `git config --show-origin`, top = highest
precedence:

```
Provenance
 ● user     ~/.config/sase/sase.yml      fcm        ★ effective
 ○ overlay  ~/.config/sase/sase_x.yml    (unset)
 ○ local    ./sase.yml                   (n/a — local layer off in ACE)
 ○ default  (built-in)                   disabled
```

This answers "why is it this value?" and "which file do I edit?" at a glance. `sase config layers` already
computes this data; the panel renders it per-field. Selecting a row in the strip can set that layer as the edit
scope (fast path).

### 4. Scope/destination selector (the second differentiator)

A header control (toggled with `tab`, or leader-mode) chooses the **write target** for edits:
`User` (default) · `Overlay ▾` (choose which `sase_*.yml`, or create one) · `Local` (`./sase.yml`).
The currently-selected scope is always visible. Edits *only ever touch the selected scope's file*; the
provenance strip then shows the new effective winner. This mirrors VS Code's User/Workspace tabs and git's
scope flags — a model users already hold.

### 5. List replace-vs-concatenate, made visible

When editing an `array` field, the editor banner states the **effective merge behavior for the chosen scope**:
- User scope → *"This list replaces lower layers."*
- Overlay/Local scope → *"This list appends to lower layers (concatenate). Effective = default + yours."* with a
  preview of the merged result.

This turns SASE's most surprising semantic into an explicit, teachable moment instead of a silent footgun.

### 6. Complex & free-form sections — graceful degradation

Do **not** force these into a flat form. Tier the treatment:
- **Free-form maps** (`ace.snippets`, `vcs_provider.pr_tags`, `xprompt_aliases`) → a **key→value table
  sub-editor** (add/edit/delete rows), reusing the `tag_input_modal` pattern.
- **`ace.keymaps`** → a dedicated **keymap sub-editor**: action→key rows grouped by mode, with conflict
  detection (two actions bound to one key) and "press the key to bind it" capture. High-value because keymaps
  are the most-edited complex section.
- **`axe.lumberjacks` / `llm_provider.retry`** (lists of objects, per-provider) → a **row-per-entry table** with
  a drill-in form per row; duration fields (`"90s"`) get a parsed duration widget.
- **`xprompts`** → treated as *authored content*, not settings: link out to the existing xprompt
  browser/config modal rather than re-implement.
- **Universal escape hatch:** **`e` opens the selected section's YAML slice** in `$EDITOR` (or an in-TUI
  `TextArea`), re-validated and re-merged on save. Guarantees nothing is uneditable even before every sub-editor
  is built — and lets the panel ship incrementally (scalars first, sub-editors later).

### 7. Save flow — preview, validate, preserve

1. Edits accumulate as **pending changes** (badge "● 3 unsaved"), so a user can batch.
2. **`s` (save)** opens a **confirm modal with a YAML diff** of *each affected file* (reuse the diff-preview +
   `ConfirmActionModal` patterns).
3. On confirm, write via a **round-trip YAML writer that preserves comments, key order, and formatting** (the
   `write_sdd_init_config` precedent generalized; ideally in the Rust core writer).
4. Re-load (cheap, stat-token memoized) and refresh provenance. Surface schema/deprecation warnings inline
   (the data `sase config layers` already produces).

### 8. Empty/onboarding state

First open with an all-defaults config: lead with **"modified only"** empty and a prompt — *"Nothing
customized yet. Filter (/) to find a setting, or press m to see what you've changed."* Pairs naturally with the
new-user onboarding work (`new_user_onboarding_recommendations_consolidated.md`).

---

## Interaction Walkthroughs

**A. Turn on mobile push (simple scalar/enum).**
`tab` until scope = User → `/push` → select `mobile_gateway.push_provider` → `enter` → arrow to `fcm` → `enter`
→ provenance strip now shows `user … fcm ★` → `s` → confirm the one-line diff to `~/.config/sase/sase.yml`.

**B. Debug "my timezone change isn't taking" (provenance).**
`:timezone` → detail pane provenance strip reveals `overlay sase_x.yml = "UTC" ★` is overriding the user file.
User selects the overlay row to switch scope, or fixes the overlay directly. Problem diagnosed in seconds —
impossible with a single-file editor.

**C. Add a PR tag (free-form concatenating map at overlay scope).**
Scope = Overlay → `vcs_provider.pr_tags` → key→value sub-editor → add `wip: "WIP "` → banner: *"appends to
lower layers"* with merged preview → `s` → diff against the overlay file.

---

## Keybindings (proposed, ACE-consistent)

| Key | Action |
|-----|--------|
| `j`/`k`, `g`/`G` | move / top / bottom |
| `h`/`l` | collapse / expand section |
| `/` | fuzzy filter (path + description) |
| `:` | jump to dotted path |
| `m` | toggle "modified only" |
| `tab` | cycle write scope (User → Overlay → Local) |
| `enter` | edit selected field |
| `d` | reset field to default (in current scope) |
| `e` | open section's raw YAML slice |
| `s` | save (preview diff → confirm) |
| `u` | discard pending change |
| `?` | help / keymap overlay |

All overridable via `ace.keymaps` like the rest of the TUI; defaults must also be added to
`src/sase/default_config.yml` per `memory/gotchas.md`.

---

## Alternatives Considered

**A. VS Code-style flat searchable list (no tree).** Pure search + scrollable list of fields with inline
widgets. Pro: dead simple, search-first. Con: weak for SASE's deep nesting (keymaps/lumberjacks) and loses the
section mental model. *Verdict: fold its search + per-field widgets into the detail pane, but keep a tree for
structure.*

**B. Master–detail tree + schema-driven detail (recommended).** Best balance of discovery, structure, and
type-appropriate editing; provenance and scope have a natural home. *Verdict: chosen.*

**C. Multi-file raw YAML editor with a provenance overlay.** Show the actual files as text, annotate each line
with its effective/overridden status. Pro: maximum power, zero schema dependency, no "uneditable" fields. Con:
no discovery, no type safety, no guidance — it's "edit YAML, but prettier." *Verdict: ship this as the `e`
escape hatch inside B, not as the primary UX.*

**Recommendation: B, with A's widgets in the detail pane and C as the escape hatch.** This is incrementally
shippable: phase 1 = tree + scalar/enum/bool form + provenance + scope + raw-slice escape hatch (covers ~70% of
fields immediately); phase 2 = sub-editors for keymaps, lumberjacks, free-form maps; phase 3 = CLI parity
(`sase config set/edit`) and web reuse.

---

## Implementation Surface

- **Schema-driven form generator.** Read `config/sase.schema.json` (already shipped + validated + exposed via
  `sase path config-schema`). Map JSON-Schema type/enum/default/description/constraints → TUI widgets. New
  fields appear in the UI for free as the schema grows — no parallel hand-maintained form.
- **Rust core boundary (`memory/rust_core_backend_boundary.md`).** Put **layer resolution, provenance
  computation, schema-typed get/set, and comment-preserving write-back** in `../sase-core`
  (`sase_core_rs` binding). `xprompt_catalog.rs` already enumerates the same layer paths; `sase config layers`
  already computes provenance. The Textual panel stays presentation-only. This gives a future web app, the
  editor LSP, and a CLI `config set` identical behavior from one implementation.
- **Write-back.** Generalize the surgical, comment-preserving pattern from `write_sdd_init_config`
  /`insert_xprompt_into_config` into a round-trip setter (`set(path, key, value)` / `unset(path, key)`),
  ideally in the Rust core writer. Never rewrite the whole file from a parsed dict (loses comments/order).
- **CLI parity.** A `sase config set -k <dotted.key> -v <value> [--scope user|overlay|local] [--dry-run]` (and
  `unset`) should share the same core writer. Honors the CLI conventions in `memory/cli_rules.md` (every long
  option gets a short alias; alphabetical, colored help). The panel and CLI become two front-ends over one
  backend.
- **TUI integration.** New tab in `app.py` `TabName` + `compose()` + `tab_bar` labels + `next/prev_tab`
  cycling; reuse `OptionList`/picker, readline `FilterInput`, `ConfirmActionModal`, diff preview, and the
  conditional `keybinding_footer`. Add default keymaps to `src/sase/default_config.yml`.
- **Refresh.** Use the existing stat-token memoization to detect external edits and refresh provenance without
  polling cost.

---

## Risks & Open Questions

1. **Should the local (`./sase.yml`) layer be editable inside ACE?** ACE deliberately disables local config at
   load. Editing it from the TUI may surprise users who expect ACE to ignore repo config. *Proposal: include
   it as a selectable scope but clearly label it "off in ACE's own merge" in the provenance strip.*
2. **Overlay file management.** Creating/naming new `sase_*.yml` overlays from the UI — how much management
   (rename/delete/reorder) is in scope vs. left to the filesystem?
3. **Concatenate semantics for nested lists** (e.g., `axe.lumberjacks` chops) — preview accuracy matters; the
   merged preview must use the real `_deep_merge` (another reason to compute it in core, not re-implement in the
   panel).
4. **`additionalProperties: false`** means unknown/deprecated keys (`sibling_repos` → `linked_repos`) exist in
   real files. The panel must *show* them (with a deprecation nudge, data already available) rather than hide or
   silently drop them.
5. **Secrets** (`fcm_service_account_json`, credential envs) — mask/redact in the UI; never echo full values.
6. **Schema completeness/drift.** The form is only as good as the schema. Any field missing a description/enum
   degrades to a plain input — acceptable, but worth a lint that flags schema fields lacking descriptions.
7. **Reset semantics.** Confirm that "reset to default" = *delete the key in this scope* (let lower layers
   surface) rather than *write the literal default* — the latter would shadow future default changes.

---

## Sources Checked

- `src/sase/config/core.py` (layering, `_deep_merge`, `load_merged_config`, `load_config_layers`,
  deprecated/unsupported keys)
- `src/sase/default_config.yml` (546 lines; section inventory)
- `config/sase.schema.json` (976 lines; 22 sections, 164 descriptions, enums, defaults) + `sase path
  config-schema` (`src/sase/main/entry.py:250-261`)
- `src/sase/main/parser_commands.py` + `config_handler.py` (`sase config layers/show/mentor-match`)
- `src/sase/main/sdd_init_config.py` (`write_sdd_init_config` — comment-preserving write precedent)
- `src/sase/ace/tui/modals/xprompt_config_modal.py` + `xprompt_config_yaml.py` (modal + YAML insertion
  precedent)
- `src/sase/ace/tui/app.py`, `bindings.py`, `widgets/tab_bar.py`, `widgets/keybinding_footer.py`,
  `modals/{confirm_action,input_item,model_picker,tag_input}_modal.py`, `keymaps/loader.py` (TUI architecture &
  reusable widgets)
- `sase-core/crates/sase_core/src/xprompt_catalog.rs` (layer-path knowledge already in Rust core)
- Domain sub-configs: `llm_provider/{config,retry_config,commit_finalizer_config}.py`, `vcs_provider/config.py`,
  `axe/config.py`, `telemetry/_config.py`, `amd/_config.py`, `bead/config.py`
- Memory: `rust_core_backend_boundary.md`, `cli_rules.md`, `gotchas.md`, `glossary.md`
- External prior art (general knowledge): VS Code Settings UI, `git config --show-origin`/scopes, k9s, lazygit,
  which-key/Neovim, npm/cargo config.
```

