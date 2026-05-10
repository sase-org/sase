---
create_time: 2026-05-09 20:11:52
status: wip
prompt: sdd/prompts/202605/fix_retired_chat_plugin_sdd_links.md
---
# Plan: Fix retired_chat_plugin SDD Link Validation

## Problem

GitHub Actions fails at `sase sdd validate` because the two SDD artifacts for `retired_chat_plugin` have stale
reciprocal frontmatter links:

- `sdd/epics/202604/retired_chat_plugin.md` points `prompt` at
  `sdd/prompts/202604/retired_chat_plugin_integration.md`
- `sdd/prompts/202604/retired_chat_plugin.md` points `plan` at
  `sdd/epics/202604/retired_chat_plugin_integration.md`

Those `_integration.md` targets do not exist. The actual prompt and epic files both exist without the duplicate suffix.

## Investigation Summary

- `sdd/README.md` documents the intended bidirectional relationship: prompt files use `plan: ...`; plan-like artifacts
  use `prompt: ...`.
- Nearby April 2026 SDD pairs, such as `gchat_telegram_integration_improvements.md` and `markdown_pdf_attachments.md`,
  use matching same-name prompt/epic links.
- `.venv/bin/sase sdd validate` reproduces the CI failure with exactly two errors.
- `.venv/bin/sase sdd repair-links` dry-run proposes exactly two actions and no warnings or errors:
  - update the prompt file's `plan` target to `sdd/epics/202604/retired_chat_plugin.md`
  - update the epic file's `prompt` target to `sdd/prompts/202604/retired_chat_plugin.md`

## Implementation Plan

1. Edit only the frontmatter of:
   - `sdd/prompts/202604/retired_chat_plugin.md`
   - `sdd/epics/202604/retired_chat_plugin.md`
2. Replace the stale `_integration.md` links with the existing same-name counterpart paths.
3. Do not rename or create SDD artifacts; the existing filenames are canonical and match the repair command's
   unambiguous inference.
4. Re-run `sase sdd validate` to verify the errors are gone.
5. Because this repo's instructions require it after changes, run `just install` if needed and then `just check`. If
   `just check` is too slow or blocked by environment issues, report the blocker and retain the targeted SDD validation
   result.

## Risks

This is a low-risk metadata-only fix. The main risk would be using the automated repair command with `--write` if it had
broader inferred actions, but the dry run showed only the two expected changes. Manual frontmatter edits keep the change
tightly scoped.
