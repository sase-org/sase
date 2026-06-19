---
create_time: 2026-06-19 11:26:10
status: done
prompt: sdd/prompts/202606/log_skill_use_lsp.md
---
# Plan: Add LSP Support for `log_skill_use`

## Goal

Make `log_skill_use` a supported xprompt frontmatter field in the editor/LSP path so Neovim no longer reports it as an
unsupported property when used in skill xprompt sources, for example:

```yaml
---
skill: true
description: Plan creation helper
log_skill_use: false
---
```

Runtime support already exists in the Python xprompt loader, skill generation, docs, and `config/sase.schema.json`. The
missing path is the shared Rust frontmatter validation engine used by both `sase-xprompt-lsp` and the Python
`sase.xprompt.frontmatter_schema` adapter.

## Current Findings

- `src/sase/xprompt/frontmatter_schema.py` is intentionally a thin wrapper over `sase_core_rs`; it does not own the
  supported field set.
- The active core checkout is
  `SASE_SIBLING_REPO_SASE_CORE_DIR=/home/bryan/.local/state/sase/workspaces/sase-org/sase-core/sase-core_13`.
- In `crates/sase_core/src/editor/frontmatter.rs`, `validate_top_level_fields()` treats any top-level field missing from
  `TOP_LEVEL_FIELD_DOCS` as `unknown_xprompt_frontmatter_field`.
- Current behavior reproduced through the Python binding: `log_skill_use: false` emits
  `unknown_xprompt_frontmatter_field` with severity `information`.
- `PANEL_FIELD_SCHEMA` is the prompt Frontmatter Panel add-property schema. Adding `log_skill_use` there would also
  require Python model and TUI editing support for a plain boolean field. That is more scope than needed to fix the LSP
  warning.

## Implementation Plan

1. Update the core frontmatter field contract in `sase-core`:
   - Add `log_skill_use` to `TOP_LEVEL_FIELD_DOCS` with hover text explaining that it controls whether generated skill
     files include the `sase skill use ...` audit directive.
   - Keep it out of `PANEL_FIELD_SCHEMA` for this change unless a deeper product decision says the prompt Frontmatter
     Panel should expose skill-generation-only fields.

2. Add core validation for the field:
   - Add `validate_log_skill_use(builder, mapping)` in `crates/sase_core/src/editor/frontmatter.rs`.
   - Call it from `validate_frontmatter_value()`.
   - Accept only YAML booleans.
   - Emit a focused diagnostic, likely `invalid_xprompt_frontmatter_log_skill_use`, when the value is not boolean.
   - Use a warning or error consistently with nearby field validators. I would choose warning unless the existing loader
     rejects non-booleans; if the Python runtime accepts any truthy/non-bool value today, warning avoids making editor
     validation stricter than runtime failure behavior.

3. Add Rust regression coverage:
   - `validate()` accepts a frontmatter block containing `log_skill_use: false` without
     `unknown_xprompt_frontmatter_field`.
   - `hover()` on the `log_skill_use` key returns the new field documentation.
   - Invalid values such as `log_skill_use: "false"` or `log_skill_use: no thanks` produce
     `invalid_xprompt_frontmatter_log_skill_use`.
   - Keep the existing `field_schema_is_ordered_documented_and_parity_scoped` expectations unchanged if the field
     remains out of the panel schema.

4. Verify the Python adapter sees the updated core behavior:
   - Rebuild/install the local `sase_core_rs` from the managed sibling core checkout, using
     `SASE_CORE_DIR="$SASE_SIBLING_REPO_SASE_CORE_DIR" just rust-install`.
   - Add or update Python-side tests in `tests/test_xprompt_frontmatter_schema.py` to assert `validate_frontmatter()`
     accepts `log_skill_use: false` and flags non-boolean values with the new code.
   - Do not duplicate validation logic in Python.

5. Run targeted checks:
   - In `sase-core`: `cargo test -p sase_core editor::frontmatter`.
   - In `sase-core`: `cargo test -p sase_xprompt_lsp` if the hover/diagnostic behavior is covered through LSP server
     tests.
   - In `sase`:
     `PYTHONPATH=src .venv/bin/python -m pytest tests/test_xprompt_frontmatter_schema.py tests/test_prompt_frontmatter.py`.
   - Because file changes in the `sase` repo require it, run `just check` after any implementation edits here. If
     `uv.lock` still blocks `uv` commands, report that blocker explicitly and provide the targeted test results that did
     run.

## Non-Goals

- Do not change runtime xprompt parsing unless inspection finds the loader mishandles `log_skill_use`.
- Do not add a `FrontmatterFieldKind::Bool` or prompt-panel editing support in this pass; that would be a larger TUI
  feature, not required to fix the Neovim LSP warning.
- Do not edit release versions or dependency pins in `sase-core` Cargo manifests.

## Risk and Mitigation

- Risk: the LSP and Python binding can drift if only one side is changed. Mitigation: change the shared Rust validator
  and rebuild the binding before Python tests.
- Risk: keeping `log_skill_use` out of `PANEL_FIELD_SCHEMA` may surprise users who expect the panel to expose every
  supported xprompt frontmatter key. Mitigation: document that this pass is LSP support only; revisit panel support
  later with a dedicated boolean field kind and model support.
- Risk: existing installed `sase_core_rs` may be stale. Mitigation: explicitly rebuild from the managed sibling core
  checkout before validating Python behavior.
