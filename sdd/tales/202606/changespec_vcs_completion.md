---
create_time: 2026-06-19 17:40:38
status: done
prompt: sdd/prompts/202606/changespec_vcs_completion.md
---
# Plan: Add active ChangeSpecs to `#+` VCS completion (TUI prompt + xprompt LSP)

## Goal

Make the `#+` (and bare leading `+`) completion menu list **active ChangeSpecs in addition to projects**, so it shows
the same set the `@` keymap's "Select Project or PR" modal shows. Both the `sase ace` TUI prompt input and the Neovim
xprompt LSP must clearly distinguish **projects** from **ChangeSpecs**, and the result must be intuitive, reliable, and
beautiful.

## Why this is small at the core (the key insight)

Selecting a ChangeSpec in the `@` menu inserts the **same tag shape** as selecting a project: `#<vcs_prefix>:<name> `.
The only differences are:

- the ref slot holds the **CL name** instead of the project name, and
- the `vcs_prefix` is detected from the **owning project's** spec file.

(`_start_custom_agent_from_selection` in `src/sase/ace/tui/actions/agent_workflow/_entry_custom.py:148-180` calls the
same `_vcs_prompt_prefix(project_file, name)` for both, just passing `cl_name` vs `project_name`.)

Therefore the **parity-critical expansion algorithm is unchanged**: `apply_vcs_project_selection` / the Rust
`apply_vcs_project_selection` in `sase-core/crates/sase_core/src/editor/completion.rs` already take a `display_tag` and
are agnostic to whether it came from a project or a CL. The existing golden vectors keep passing.

This is fundamentally a **catalog-building + rendering** change, plus one **cache-correctness** fix. We extend one entry
type with a `kind` discriminator and flow it through both frontends.

## Current architecture (confirmed)

- **Catalog (source of truth, Python):** `src/sase/xprompt/vcs_project_completion.py`
  - `VcsProjectEntry` dataclass: `name, vcs_prefix, display_tag, provider_display, description, aliases`.
  - `_build_entries()` reads `list_project_records(projects_dir, "active")`, drops system-managed / non-launchable /
    `home` / undetectable-workflow projects, builds `#<prefix>:<name>` tags.
  - Module-level cache keyed by `_catalog_signature()` = **a single `stat()` of the projects dir**.
  - `vcs_project_catalog_payload()` serializes the catalog to JSON (`schema_version = 1`) for the LSP.
- **TUI bridge:** `src/sase/ace/tui/widgets/vcs_project_completion.py` →
  `CompletionCandidate(display=name, insertion=display_tag, name=name, metadata=entry)`.
- **TUI rendering:** `_append_vcs_project_completion_row()` in
  `src/sase/ace/tui/widgets/_prompt_input_bar_completion.py` (panel border title `"projects"`). Per-keystroke refilter
  rebuilds candidates via `vcs_project_completion_candidates()` in `_file_completion_refresh.py:61-90` (so the cache
  signature is recomputed on every keystroke).
- **LSP:** Python materializes the JSON catalog at LSP startup (`_materialize_vcs_project_catalog`,
  `src/sase/integrations/xprompt_lsp.py`). The Rust LSP (`sase-core/crates/sase_xprompt_lsp`) reads it, filters, and
  converts to `CompletionItem` (`lsp_convert.rs::vcs_project_completion_item`, currently `kind = MODULE`, no
  `label_details`).
- **`@` reference UX:** `src/sase/ace/tui/modals/project_select_modal.py` lists `[P] <project>` and
  `[PR] <cl> [<status>]` rows; ChangeSpecs come from `find_all_changespecs()` filtered to base status in
  `{WIP, Draft, Ready, Mailed}` via `remove_workspace_suffix`. Badge palette: `[P]` = bold `#87D7FF` (cyan), `[PR]` =
  bold `#00D7AF` (green).

## Design

### 1. Unified catalog entry with a `kind` discriminator

Extend `VcsProjectEntry` (Python and the Rust wire struct) with three additive fields — one pipeline, one expansion
algorithm, two render styles:

- `kind`: `"project"` (default) or `"changespec"`.
- `project`: owning project basename (for projects, equals `name`); used as display context for CLs.
- `status`: base ChangeSpec status (e.g. `"Ready"`); empty for projects.

Keep the type name `VcsProjectEntry` and the menu kind constant `VCS_PROJECT_COMPLETION_KIND` to limit churn and
preserve JSON field stability; update docstrings to state it now represents both. New JSON fields are
`#[serde(default)]` on the Rust side, so the change is backward/forward compatible; bump `schema_version` to `2` and
have Rust tolerate both 1 and 2.

### 2. Catalog builder (`_build_entries`)

1. First pass (unchanged): build project entries; record `prefix_by_project[name] = (vcs_prefix, provider_display)`.
2. Second pass: for each `cs` from `find_all_changespecs()` whose `remove_workspace_suffix(cs.status)` is in
   `{WIP, Draft, Ready, Mailed}` **and** whose `cs.project_basename` is in `prefix_by_project`, emit a
   `kind="changespec"` entry: `name=cs.name`, `display_tag=f"#{prefix}:{cs.name}"`, `project=cs.project_basename`,
   `status=base_status`. Tying CL visibility to the project map guarantees the CL's tag is always expandable and the
   owning project is itself listed.
3. Ordering (mirrors `@`): **projects first** (sorted by name, as today), then ChangeSpecs (sorted by `(project, name)`
   for deterministic grouping).
4. De-dup: projects stay de-duped by name among themselves; ChangeSpecs are a list (a CL may share a name with a project
   or with a CL in another project — all are shown, distinguished by kind/tag, matching `@`).

Filtering (`filter_vcs_project_entries`) is unchanged: case-insensitive prefix match on `name`/aliases, stable order. CL
filter key is the CL name, consistent with the existing `#+` behavior. (Intentional, documented difference vs `@`, which
substring-matches; `#+` keeps prefix matching.)

### 3. Reliability: cache invalidation for ChangeSpec edits (the important fix)

`_catalog_signature()` today stats only the top-level projects dir, which catches project add/remove but **not**
ChangeSpec status edits (those rewrite nested `.gp`/`.sase` files). Without a fix, `#+` would show stale CLs (e.g. a
Submitted CL lingering, or a new CL missing).

Fix: compute the signature from the **mtimes of the active project spec files** (the same files the catalog parses,
enumerated via the existing `iter_changespec_project_files`/`list_project_records` machinery). This subsumes project
membership changes and CL content changes in one signature.

Per the TUI perf rules ("cache disk reads keyed by mtime; measure, don't guess"), the signature is recomputed on each
keystroke while the menu is open. With the realistic project count this is one dir walk + N stats (sub-millisecond), but
**we validate it** with `SASE_TUI_PERF=1` and the j/k benches (target p95 < 16 ms). Fallback if it regresses on large
project sets: build the catalog once on menu-open and filter the in-memory entries on keystrokes (compute the signature
only on open).

### 4. TUI rendering — make it look like the `@` menu

Update `_append_vcs_project_completion_row()` to lead each row with the **same colored badge as the `@` modal**, so the
two menus feel like one family:

- Project: `[P] ` (bold `#87D7FF`) · name (bold cyan when selected, else cyan) · `#gh:<name>` (dim green, expansion
  hint) · provider (dim).
- ChangeSpec: `[PR] ` (bold `#00D7AF`) · name (bold when selected) · `#gh:<cl>` (dim green) · `<status>` (dim) ·
  `· <project>` (dim, owning project).

Refinements for beauty: pad the badge+name to the max visible width so the tag/metadata columns align vertically; panel
`border_title` becomes `"projects & PRs"`; the empty-state row reads `"no active projects or PRs"` when the whole
catalog is empty (the existing non-selectable placeholder path is reused).

### 5. LSP rendering — distinguish via `kind` + `labelDetails`

In `lsp_convert.rs::vcs_project_completion_item`, set fields by `entry.kind` (the most reliable cross-client "which is
which" signal is the text in `labelDetails`, with the icon from `kind` as a bonus):

- Project: `kind = MODULE` (unchanged), `label_details.description = "project"`, `detail = display_tag`.
- ChangeSpec: `kind = EVENT` (distinct icon),
  `label_details = { detail: " · <project>", description: "PR · <status>" }`, `detail = display_tag`.

`filter_text` keeps the existing `#+<name>` / `+<name>` form. Build-side candidate construction in `completion.rs`
carries the new fields through to the candidate so `lsp_convert` can branch on `kind`.

### 6. LSP freshness (explicit scope note)

The LSP catalog JSON is materialized **once at LSP startup** today (true for projects already). CL entries inherit the
same freshness model: fresh as of LSP start, refreshed on LSP/editor restart (the Rust loader's TTL re-reads the file if
it ever changes). Fully-live mid-session CL freshness in the LSP (which would require Rust-side catalog building or a
file watcher) is **out of scope** and called out as a known limitation.

## Files to change

**sase repo** (`.../sase/sase_10`):

- `src/sase/xprompt/vcs_project_completion.py` — entry fields, `_build_entries` CL pass, signature fix, payload schema
  v2.
- `src/sase/ace/tui/widgets/vcs_project_completion.py` — candidate metadata carries `kind`.
- `src/sase/ace/tui/widgets/_prompt_input_bar_completion.py` — badge/column rendering, border title, empty state.
- Tests: `tests/test_xprompt_vcs_project_completion.py`, `tests/ace/tui/widgets/test_vcs_project_completion.py`,
  `tests/main/test_lsp_handler.py`.

**sase-core repo** (`.../sase-core/sase-core_10`, already opened via `sase workspace open -p sase-core 10`):

- `crates/sase_core/src/editor/wire.rs` — `VcsProjectEntry` gains `kind/project/status` (serde default).
- `crates/sase_core/src/editor/completion.rs` — carry new fields into candidate build; extend the filter/sort golden
  test with a CL entry.
- `crates/sase_xprompt_lsp/src/catalog_cache.rs` — tolerate schema v2 + new fields.
- `crates/sase_xprompt_lsp/src/lsp_convert.rs` — branch CompletionItem on `kind`.
- Rust tests alongside the above (+ any shared catalog/golden fixture, kept byte-parallel with Python).

## Testing

- **Python:** CL entries built with correct `kind/tag/status/project`; ordering projects-then-CLs; status filtering; CL
  skipped when owning project is non-launchable/undetectable; CL sharing a name with a project yields both; **cache
  invalidates when a spec file mtime changes** (new/updated CL appears, Submitted CL drops); payload emits new fields +
  `schema_version = 2`; TUI menu lists both and renders distinct badges; selecting a CL expands to `#<prefix>:<cl> `;
  border title `"projects & PRs"`.
- **Rust:** entry deserializes new fields (and a v1 catalog defaults `kind="project"`); loader handles v2; filtering
  surfaces CLs by name prefix; CompletionItem: project → MODULE + `"project"`, changespec → EVENT + `"PR · <status>"` +
  project label detail; both `detail = display_tag`.
- **Parity:** extend the shared catalog/filter-sort fixture so Python and Rust agree on ordering and candidate display
  strings with a CL present. Apply-vector goldens are unchanged (tag-driven).
- **Visual:** run `just test-visual`; capture/update the `#+` menu PNG golden to lock the new look.
- **Gates:** `just install` then `just check` in the sase repo; rebuild + `cargo test` the `sase_xprompt_lsp` /
  `sase_core` crates in sase-core.

## Docs / memory (require your approval before editing)

- Glossary entry **"VCS Project Completion (`#+`)"** (`memory/glossary.md`, a protected memory file): update to note the
  menu now also lists active ChangeSpecs and distinguishes them. I will **not** touch memory files without your
  go-ahead.
- If `#+` is documented in the ace `?` help modal, update it to mention CLs (per the ace AGENTS rule to keep the help
  popup in sync).

## Out of scope / non-goals

- No change to the expansion algorithm or its golden vectors.
- No new CLI subcommands/options.
- No live mid-session LSP CL freshness (startup-materialized, matching today's project behavior).
- No move of catalog building into Rust core (Python remains the catalog source of truth that materializes JSON for the
  LSP, consistent with the existing `#+` architecture).
