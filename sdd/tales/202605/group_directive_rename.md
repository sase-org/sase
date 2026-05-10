---
create_time: 2026-05-09 22:45:52
status: wip
prompt: sdd/prompts/202605/group_directive_rename.md
---
# Rename `%tag` / `%t` Directive To `%group` / `%g`

## Context

SASE currently uses a `%tag` prompt directive, with `%t` as its short alias, to assign an agent's user-managed grouping
tag at launch. The stored agent metadata and ACE UI still use the domain term `tag`, so this change should rename the
prompt directive spelling without changing the persisted `tag` field, `agent_tags.json` format, or Agents-tab grouping
behavior.

The affected active repositories are:

- `sase_101`: Python directive parser, prompt rendering, tests, generated xprompts, and docs.
- `../sase-core`: Rust editor/LSP directive metadata and launch helper alias normalization.
- `~/.local/share/chezmoi`: personal SASE config and GitHub Actions chop helper/tests.

The maintained plugin repos listed in memory (`../sase-github`, `../sase-telegram`, `../sase-nvim`) and additional
sibling plugin-like repos (`../sase-google`, `../sase-gchat`, `../sase-android`) had no literal `%tag` or SASE `%t`
directive references in the initial scan. `../sase-core` is the only sibling repo with directive-table references to
update.

## Goals

1. `%group:<value>` and `%g:<value>` are the supported spellings for assigning an agent grouping tag at launch.
2. Generated prompts from bead/legend/epic workflows emit `%group:<bead_id>`.
3. User configs and helper scripts in chezmoi launch agents with `%g:<value>` instead of `%t:<value>`.
4. Directive completion, hover, diagnostics, and any Rust-side canonicalization expose `%group` / `%g`.
5. Tests and user-facing docs describe and assert the new directive spelling.
6. A final repository-wide scan leaves no SASE `%tag` / `%t` directive references except intentionally unrelated
   non-SASE format strings such as mutt `%t`.

## Non-Goals

- Do not rename the persisted agent metadata concept from `tag` to `group`.
- Do not migrate `~/.sase/agent_tags.json`; directive parsing should continue to populate `PromptDirectives.tag`.
- Do not alter the Agents-tab UI grouping model or `sase agents tag ...` CLI in this change unless tests reveal an
  unavoidable naming conflict.

## Implementation Plan

1. Update Python directive parsing in `src/sase/xprompt/_directive_types.py` and `src/sase/xprompt/directives.py`:
   - Replace the known directive name `tag` with `group`.
   - Replace alias `t -> tag` with `g -> group`.
   - Map parsed `group` values into the existing `PromptDirectives.tag` field.
   - Update duplicate, validation, and missing-argument error text to mention `%group` / `%g`.

2. Update prompt generation in `src/sase/bead/work.py` and active xprompts:
   - Make bead/legend/epic rendering use `%group:<id>`.
   - Update `xprompts/pylimit_split.yml` to use `%group` or `%g`.

3. Update Rust core directive metadata:
   - In `../sase-core/crates/sase_core/src/editor/directive.rs`, expose directive metadata as `group` with alias `g`.
   - Update directive metadata tests from `t/tag` to `g/group`.
   - In `../sase-core/crates/sase_core/src/agent_launch/mod.rs`, update canonical alias normalization from `%t` to `%g`
     for parity with editor-facing directive behavior.

4. Update tests in `sase_101`:
   - Rename directive extraction tests to `%group` / `%g`.
   - Update bead-work rendering and CLI tests to expect `%group`.
   - Update multi-prompt and axe runner tests/comments that compare prompt text or describe the launch directive.

5. Update docs and project references:
   - Update active docs in `docs/`.
   - Update SDD/plans/prompts/tales references that mention the directive spelling so repository searches do not leave
     stale SASE directive examples.
   - Preserve unrelated uses of the word `tag` where they describe persisted metadata or UI grouping rather than the
     prompt directive spelling.

6. Update chezmoi references:
   - Change SASE config prompts in `~/.local/share/chezmoi/home/dot_config/sase/` from `%t:` to `%g:`.
   - Change `~/.local/share/chezmoi/home/bin/executable_sase_chop_gh_actions_fix` and its bash tests from `%t:gact` to
     `%g:gact`.
   - Do not touch unrelated non-SASE `%t` placeholders such as mutt status-format syntax.

7. Verify:
   - In `sase_101`: run `just install` if needed, then targeted pytest for directive extraction and bead-work rendering,
     then `just check`.
   - In `../sase-core`: run the repo's normal Rust checks/tests, at minimum `cargo test`.
   - In `~/.local/share/chezmoi`: run `just check`.
   - Re-run cross-repo `rg` scans for `%tag`, `%t:`, `%group`, and `%g:` over active repos plus chezmoi, reviewing any
     remaining old spellings for intentional exclusion.

## Risks

- Some historical SDD files may intentionally describe old behavior. Because the request asks for all references, stale
  directive spellings should be updated unless the line is clearly an immutable transcript where changing it would
  misrepresent source history.
- `%g` may already mean something in a future or external directive surface; the active directive tables show no current
  conflict.
- Keeping `PromptDirectives.tag` while exposing `%group` creates mixed internal/public naming. That is intentional for
  scope control, but comments and errors must be clear enough to prevent future confusion.
