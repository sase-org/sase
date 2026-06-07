---
create_time: 2026-06-07 06:06:16
status: done
prompt: sdd/prompts/202606/rename_cls_tab_to_prs.md
---
# Rename ACE "CLs" Tab to "PRs"

## Goal

Rename the user-facing ACE tab label from "CLs" to "PRs" and update related user-facing references so the TUI, help,
command palette, documentation, and tests consistently present the tab as the PRs tab.

## Scope Boundary

This should be a presentation-layer rename, not a data model migration. Keep stable internal identifiers and storage/API
terminology where they are part of existing contracts, including:

- `current_tab == "changespecs"` and the `TabName` literal values.
- Python names such as `cl_name`, `rename_cl`, and existing ChangeSpec model fields.
- Serialized ChangeSpec fields such as `CL:` / `PR:` and docs that explicitly describe provider-specific CL/PR metadata.
- Historical SDD prompt/tale text unless a test or generated user-facing artifact consumes it.

Update text that a user sees or that documents the ACE tab itself:

- The visible tab label: `CLs` -> `PRs`.
- Tab badges in jump-all and command-palette modals.
- Help modal section labels and action descriptions that describe the tab or its visible entries.
- Footer labels such as `go to CL`, `run cmd (CL)`, `run agent (CL)`, and `CL#` where the UI now presents PR language.
- Grouping toast/help/docs from `CL grouping` / `CL by date` to PR language.
- Group banner count chips from `N CLs` to `N PRs`.
- Saved-agent-group summaries/previews that show `CLs` as a user-facing group field.
- Docs and blog references to the "CLs tab" and tab trio.
- Tests and PNG visual snapshots that assert visible text.

## Implementation Plan

1. Introduce or update display-label constants where labels are already centralized.
   - Change `src/sase/ace/tui/widgets/tab_bar.py` `_TAB_LABELS` entry for `changespecs` from `CLs` to `PRs`.
   - Update `_TAB_STYLES` / `_TAB_BADGE` / `TAB_DISPLAY_NAMES` mappings in jump-all, command-palette, and help-modal
     code.
   - Prefer keeping internal tab id `changespecs` unchanged to avoid breaking command scopes, state restoration, CLI
     `--tab`, and tests that intentionally assert stable internal state.

2. Update adjacent user-facing ACE UI copy.
   - Command catalog display categories and labels: `CL Actions` -> `PR Actions`; action labels like `Change CL status`,
     `Mail CL`, `View CL files`, `Run agent from CL`, `Jump to agent's CL`, and copy labels to PR wording.
   - Help modal labels in `changespecs_bindings.py` from CL-focused language to PR-focused language while preserving
     ChangeSpec-specific terms where the action edits a ChangeSpec section.
   - Footer and dynamic binding chips in `keybinding_footer.py` and `_keybinding_bindings.py`.
   - Grouping toast in `actions/agents/_grouping.py` from `CL grouping: ...` to `PR grouping: ...`.
   - Banner count chips in `_changespec_list_banner.py` from `N CLs` to `N PRs`.
   - Saved-agent-group preview/summary labels from `CLs` to `PRs`.
   - Project selection modal visible copy from project/CL language to project/PR language, while keeping variable names
     and semantics intact.

3. Update documentation and public reference text.
   - `docs/ace.md` tab system, keybinding section title, grouping/folding section, global tab-switching copy, command
     palette, jump-all modal, mentor comment stats, and tab-bar display.
   - Related docs/blog posts that explicitly refer to the ACE "CLs tab" or the tab trio.
   - Keep general ChangeSpec docs using CL/PR terminology where they describe the underlying review record format rather
     than the ACE tab label.

4. Update test expectations.
   - Adjust unit tests asserting help/footer/catalog strings.
   - Adjust grouped-list tests expecting `2 CLs` banner chips.
   - Adjust saved-agent-group visual fixture titles or expected text where relevant.
   - Add or update a focused TabBar assertion if existing tests do not directly guard that the visible label is now
     `PRs`.

5. Refresh visual snapshots.
   - Run the targeted PNG visual snapshot suite that covers ACE tab-bar and modal labels.
   - Update affected goldens intentionally with the repo's snapshot update flag if failures are only label changes.
   - Inspect changed PNGs enough to confirm the tab text and modal labels render cleanly and do not overflow.

6. Verification.
   - Run focused tests first: tab bar/widget tests, help display tests, footer visibility tests, command palette tests,
     grouped ChangeSpec list tests, saved-agent-group tests, and PNG snapshots.
   - Because implementation changes will modify repo files, run `just install` if needed and finish with `just check` as
     required by repo instructions.
   - Run
     `rg -n -S "\bCLs\b|CLs tab|go to CL|CL Actions|CL grouping|CL by date|run cmd \(CL\)|run agent \(CL\)" src tests docs README.md`
     and triage any remaining hits. Remaining hits should be either intentionally internal/historical, provider-specific
     CL/PR format docs, or unrelated domain terms.

## Risks and Mitigations

- Risk: changing internal identifiers such as `changespecs` would break persisted state, command scopes, and CLI
  options. Mitigation: keep this as a display-copy change only.
- Risk: broad replacement of `CL` could corrupt provider-specific behavior and ChangeSpec file format docs. Mitigation:
  make targeted UI/docs/test edits and review remaining `CL` hits manually.
- Risk: PNG snapshot churn. Mitigation: update only snapshots whose rendered text changes and inspect them before
  finalizing.
