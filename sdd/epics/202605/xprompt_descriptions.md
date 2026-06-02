---
bead_id: sase-3w
tier: epic
status: done
---
# Plan: Optional descriptions for xprompts and xprompt inputs

## Goal

Add optional `description` fields to xprompts and xprompt inputs, then surface those descriptions wherever users
discover, select, inspect, or complete xprompts.

The feature should support:

- Xprompt-level descriptions on markdown xprompts, configured xprompts, workflow YAML xprompts, and workflow-local
  xprompts.
- Input-level descriptions on both longform and shortform input declarations.
- Python/TUI/catalog/mobile surfaces in the main `sase` repo.
- Native Rust catalog, editor, LSP, and gateway surfaces in `sase-core`.
- Neovim fallback picker and Telescope preview surfaces in `sase-nvim`.
- Real metadata on the xprompt files that will exercise this feature immediately.

## Contract

The intended YAML/frontmatter shape is:

```yaml
---
description: Split a large Python module into smaller import-safe files.
input:
  file_path:
    type: path
    description: Python source file to split.
---
```

Longform input definitions should also support descriptions:

```yaml
input:
  - name: prompt
    type: prompt
    description: User request that drives the workflow.
```

Existing shorthand remains valid:

```yaml
input:
  file_path: path
```

Workflow YAML should accept top-level `description`:

```yaml
description: Refresh generated documentation and report any drift.
input:
  docs_dir:
    type: path
    description: Documentation root to refresh.
steps: ...
```

Descriptions are optional. Missing descriptions must deserialize and render exactly as before, except that newly richer
surfaces can prefer xprompt descriptions over content previews when both are available.

## Display policy

- Use xprompt descriptions as the human-readable summary/subtitle for xprompt choices.
- Keep compact input signatures compact; add input descriptions only in rich contexts: argument hint panels,
  browser/select previews, explain output, catalog detail, mobile catalog wire data, editor/LSP completion
  documentation, and hover text.
- For completion rows and dense TUI lists, show a one-line description only when it fits the existing row model; avoid
  multi-line row expansion unless that is already how the widget behaves.
- Search/filter should match xprompt descriptions and input descriptions where the backing surface already supports
  query filtering.
- Treat this as an additive wire change. Old clients must continue to read old payloads without description fields.

## Phase 1 - Main repo model, parsing, schemas, and docs

Owner: one agent in `/home/bryan/.local/state/sase/workspaces/github.com_sase-org_sase/sase_13`.

Purpose: make descriptions first-class in the Python representation without changing presentation surfaces yet.

Write scope:

- `src/sase/xprompt/models.py`
- `src/sase/xprompt/workflow_models.py`
- `src/sase/xprompt/loader_parsing.py`
- `src/sase/xprompt/workflow_loader_parse.py`
- `src/sase/xprompt/workflow_loader.py`
- `src/sase/xprompt/loader_sources.py`
- `src/sase/xprompt/_catalog_sources.py`
- `src/sase/xprompts/workflow.schema.json`
- `config/sase.schema.json`, if useful for stricter config-xprompt input schema support
- `docs/xprompt.md`
- Focused parser/schema tests under `tests/`

Implementation outline:

1. Add `description: str | None = None` to `InputArg`.
2. Add `description: str | None = None` to `Workflow`.
3. Parse input descriptions from:
   - longform markdown/config inputs: `[{name, type, default, description}]`
   - shortform nested inputs: `{arg: {type, default, description}}`
   - workflow input declarations with the same forms
   - workflow-local xprompt declarations under workflow `xprompts`
4. Preserve descriptions through:
   - `namespace_xprompt`
   - `_namespace_workflow`
   - `xprompt_to_workflow`
   - `classify_workflow` and structured catalog source creation
5. Update JSON schemas so `description` is accepted for:
   - workflow top-level descriptions
   - longform workflow inputs
   - shortform nested workflow inputs
   - workflow-local xprompts and their inputs
   - config-defined xprompt input shapes, if the existing schema can be made precise without rejecting supported
     shorthand
6. Update `docs/xprompt.md` to document input descriptions and workflow descriptions.

Tests:

- Add parser tests covering longform input descriptions, nested shortform input descriptions, and workflow top-level
  descriptions.
- Add a regression test that existing shorthand still parses with `description is None`.
- Add schema validation coverage if the repo already has schema tests.

Exit criteria:

- Python objects carry the new fields end to end.
- No presentation behavior is required from this phase beyond data preservation.
- Run focused tests for the changed parser/model code.

## Phase 2 - Main repo user-facing surfaces

Owner: one agent in the main `sase` repo after Phase 1 lands.

Purpose: surface the new description data in CLI, TUI, catalog, explain, and mobile helper output.

Write scope:

- `src/sase/xprompt/_catalog_models.py`
- `src/sase/xprompt/_catalog_structured.py`
- `src/sase/xprompt/_catalog_format.py`
- `src/sase/xprompt/_catalog_render.py`
- `src/sase/xprompt/catalog_template.html.j2`
- `src/sase/xprompt/catalog_style.css`
- `src/sase/integrations/_mobile_helper_catalog.py`
- `src/sase/main/xprompt_handler.py`
- `src/sase/xprompt/explain.py`
- `src/sase/ace/tui/widgets/xprompt_arg_assist.py`
- `src/sase/ace/tui/widgets/prompt_input_bar.py`
- `src/sase/ace/tui/modals/xprompt_browser_modal.py`
- `src/sase/ace/tui/modals/xprompt_select_modal.py`
- Focused tests under `tests/ace/tui/`, xprompt catalog tests, CLI/list tests, and mobile helper tests

Implementation outline:

1. Extend structured catalog input records with optional `description`.
2. Include xprompt/workflow descriptions and input descriptions in `sase xprompt list` JSON output so non-LSP clients
   can consume them.
3. Include input descriptions in mobile helper catalog wire output.
4. Update query matching to include input descriptions, while preserving existing name, tag, content, and
   xprompt-description matching.
5. Update `sase xprompt explain`:
   - show workflow/xprompt descriptions near the header
   - add an input description column only when at least one input has a description
6. Update generated xprompt catalog output:
   - keep existing compact signatures
   - add a small per-input detail section when any input has a description
7. Update TUI xprompt completion and browse/select surfaces:
   - completion rows use xprompt description as a subtitle/trailing summary when available
   - argument hint panels show input descriptions
   - xprompt browser metadata/preview shows xprompt description and input descriptions
   - xprompt select modal workflow previews show workflow and input descriptions
   - filters match descriptions where those modals already support filtering

Tests:

- Update `test_xprompt_arg_assist.py` and completion tests to assert input descriptions appear in hint/help text.
- Update browser/select modal helper tests to assert descriptions appear in previews and search filtering.
- Add or update CLI JSON tests to assert optional `description` fields are present when configured and absent or null
  when missing, matching existing style.
- Add mobile helper serialization tests for input descriptions.

Exit criteria:

- Main Python user surfaces expose descriptions without crowding compact signatures.
- Legacy xprompts without descriptions still render cleanly.
- Run focused tests for changed surfaces.

## Phase 3 - Rust core, native editor, LSP, and gateway

Owner: one agent in `/home/bryan/.local/state/sase/workspaces/github.com_sase-org_sase-core/sase-core_13`.

Purpose: make native catalog and editor/LSP behavior match the Python contract.

Write scope:

- `crates/sase_core/src/xprompt_catalog.rs`
- `crates/sase_core/src/host_bridge.rs`
- `crates/sase_core/src/editor/wire.rs`
- `crates/sase_core/src/editor/completion.rs`
- `crates/sase_core/src/editor/hover.rs`
- `crates/sase_core/src/editor/frontmatter.rs`
- `crates/sase_xprompt_lsp/src/server.rs`, only if server-side plumbing is needed
- `crates/sase_gateway/src/wire.rs`
- `crates/sase_gateway/src/contract.rs`
- Contract fixtures/snapshots, if this repo maintains them
- Focused Rust tests in the touched crates

Implementation outline:

1. Add optional input descriptions to `CatalogInput`.
2. Add optional workflow descriptions to `CatalogWorkflow`.
3. Parse descriptions from markdown frontmatter, workflow YAML, workflow-local xprompts, and longform/nested input
   declarations.
4. Preserve descriptions through namespace and xprompt-to-workflow conversion helpers.
5. Add optional `description` to mobile/editor input wire structs with serde defaults so old JSON still deserializes.
6. Update native editor completion:
   - xprompt completion already has entry docs; ensure workflow descriptions populate it
   - argument-name completion documentation should prefer the input description and also include default information
     when available
7. Update hover text for active xprompt inputs to include input descriptions.
8. Update frontmatter validation:
   - `description` is a known input key for longform and nested inputs
   - `description` is valid at workflow top level
   - diagnostics catch invalid input-description shapes consistently with current top-level description validation
9. Update gateway wire/contract tests for the additive optional field. Prefer no schema version bump unless this repo's
   contract policy requires one for optional fields.

Tests:

- Rust catalog parsing tests for input descriptions and workflow descriptions.
- Editor completion tests asserting input descriptions appear in completion docs.
- Hover tests asserting active-input descriptions render.
- Frontmatter diagnostics tests asserting no unknown-key warning for valid input descriptions and a clear diagnostic for
  invalid shapes.
- Host bridge/gateway compatibility tests that old payloads without input descriptions still deserialize.

Exit criteria:

- Native LSP results in Neovim can display xprompt and input descriptions through completion documentation and hover.
- Additive wire compatibility is covered by tests.
- Run focused cargo tests and then this repo's `just check`.

## Phase 4 - Neovim fallback picker and Telescope surfaces

Owner: one agent in `/home/bryan/.local/state/sase/workspaces/github.com_sase-org_sase-nvim/sase-nvim_13`.

Purpose: consume descriptions in Neovim code paths that are not already handled by the native LSP work in Phase 3.

Write scope:

- `lua/sase/xprompt.lua`
- `lua/telescope/_extensions/sase.lua`
- `tests/completion_helpers.lua`
- `tests/lsp_snippet_smoke.lua`, if LSP smoke fixtures need richer expectations
- `README.md`, if picker behavior is documented there

Implementation outline:

1. Extend Lua xprompt/input annotations with optional `description`.
2. In the non-LSP `sase xprompt list` fallback path, read xprompt and input descriptions from the JSON returned by
   Phase 2.
3. Update display formatting:
   - keep reference and input signature visible
   - show xprompt description as secondary text where the UI has room
4. Update Telescope preview to include:
   - xprompt/workflow description
   - input descriptions
   - existing content preview
5. Add filtering by description only where the current picker already owns filtering locally; do not duplicate LSP
   server filtering.

Tests:

- Update Lua tests for formatting with and without descriptions.
- Add a fallback JSON fixture with input descriptions.
- Run this repo's `just check`.

Exit criteria:

- Neovim users see descriptions in fallback completions/pickers and Telescope previews.
- LSP-provided descriptions from Phase 3 continue to pass through unchanged.

## Phase 5 - Xprompt metadata pass

Owner: one agent after Phases 1 and 3 have made the new fields valid.

Purpose: add real descriptions to the prompt library so the feature has immediate use cases.

Main repo write scope:

- `xprompts/*.md`
- `xprompts/*.yml`
- Consider `src/sase/xprompts/*.md` and `src/sase/default_xprompts/*.md` in the same pass if they appear in the same
  catalog/TUI/LSP surfaces
- Tests only if fixtures assert exact frontmatter or catalog output

Required main repo files found during planning:

- `xprompts/pick_plan.md`
- `src/sase/xprompts/split_file.md`
- `xprompts/sync.md`

Also audit these workflow YAML files in the same directory, because workflow descriptions are part of the feature
contract:

- `xprompts/audit_recent_bugs.yml`
- `xprompts/audit_recent_improvements.yml`
- `xprompts/fix_just.yml`
- `xprompts/pylimit_split.yml`
- `xprompts/refresh_docs.yml`

Sibling repo write scope:

- In `/home/bryan/.local/state/sase/workspaces/github.com_sase-org_sase-github/sase-github_13`, audit and update plugin
  xprompt YAML files under `src/sase_github/xprompts/`.
- `sase-telegram_13` had no xprompt files during planning, but re-check before declaring it out of scope.

Content guidelines:

- Keep descriptions short, factual, and action-oriented.
- Prefer user-facing wording that explains when to use the xprompt, not implementation mechanics.
- For inputs, describe what value the user should provide, including expected scope or format when helpful.
- Convert shorthand inputs to nested object form only when a description is needed:

```yaml
input:
  file_path:
    type: path
    description: Python source file to split.
```

Tests:

- Run loader/catalog smoke commands that parse the updated xprompt files.
- In the main repo, run focused xprompt tests or `sase xprompt list` against the updated files.
- In any sibling repo modified, run that repo's `just check`.

Exit criteria:

- Every markdown xprompt in root `xprompts/` has an xprompt description.
- Every declared input in those files has an input description.
- Workflow YAML in root `xprompts/` has top-level descriptions and input descriptions where inputs exist.
- Plugin xprompt files in sibling repos are either updated or explicitly documented as out of scope because they do not
  participate in the same catalog path.

## Phase 6 - Cross-repo integration verification

Owner: final integration agent after prior phases land.

Purpose: catch contract drift and ensure all user-visible surfaces agree.

Write scope:

- Small fixes only, in whichever repo owns the failing behavior.
- Do not do unrelated refactors.

Verification checklist:

1. Main `sase` repo:
   - run `just install`
   - run focused parser/catalog/TUI tests changed by the prior phases
   - run `just check`
2. `sase-core` repo:
   - run focused Rust tests for catalog/editor/frontmatter/gateway changes
   - run `just check`
3. `sase-nvim` repo:
   - run `just check`
4. `sase-github` repo, if xprompt files were edited:
   - run `just check`
5. Manual smoke checks from the main repo:
   - `sase xprompt list` includes xprompt descriptions and input descriptions in JSON
   - `sase xprompt explain <workflow-or-xprompt>` shows descriptions
   - generated xprompt catalog renders input descriptions
   - an LSP completion/hover smoke test shows input descriptions in documentation
   - a TUI xprompt browser/select helper test or snapshot shows descriptions in the expected panels

Exit criteria:

- The additive description fields are parsed, serialized, and displayed consistently across Python, Rust, and Neovim
  paths.
- All modified repos pass their required checks.
- Any intentionally unsurfaced area is listed with a reason.

## Known risks and mitigations

- There are two catalog implementations, Python and Rust. Keep the contract identical: optional xprompt/workflow
  `description`, optional input `description`, legacy shorthand unchanged.
- Dense TUI rows can become noisy. Put full input descriptions in panels/previews and keep rows concise.
- Contract tests may treat optional wire fields as schema-affecting. If so, update fixtures deliberately and document
  why no behavior breaks for old clients.
- Some xprompt files are in sibling repos. Use only workspace-matched sibling paths:
  - core: `/home/bryan/.local/state/sase/workspaces/github.com_sase-org_sase-core/sase-core_13`
  - github: `/home/bryan/.local/state/sase/workspaces/github.com_sase-org_sase-github/sase-github_13`
  - telegram: `/home/bryan/.local/state/sase/workspaces/github.com_sase-org_sase-telegram/sase-telegram_13`
  - nvim: `/home/bryan/.local/state/sase/workspaces/github.com_sase-org_sase-nvim/sase-nvim_13`
