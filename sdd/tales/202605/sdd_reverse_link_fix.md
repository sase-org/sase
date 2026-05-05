---
create_time: 2026-05-05 17:18:24
status: wip
prompt: sdd/prompts/202605/sdd_reverse_link_fix.md
---
# SDD Reverse-Link CI Failure Fix Plan

## Diagnosis

GitHub Actions is failing in `just sdd-validate`, which runs `sase sdd validate`.

The validator treats SDD prompt-like files and plan-like files as bidirectionally paired:

- prompt-like files (`sdd/prompts`, legacy `sdd/specs`) use `plan: ...`
- plan-like files (`sdd/tales`, `sdd/epics`, `sdd/legends`) use `prompt: ...`

For every explicit link, `src/sase/sdd/links.py` resolves the target and verifies that the target links back to the
source file. The failing pair is:

- `sdd/tales/202605/unified_artifacts_epic5_phase56_completion.md`
  - has `prompt: sdd/prompts/202605/unified_artifacts_epic5_migration.md`
- `sdd/prompts/202605/unified_artifacts_epic5_migration.md`
  - has `plan: sdd/epics/202605/unified_artifacts_epic5_migration.md`

That prompt is the Epic 5 planning prompt and correctly belongs to
`sdd/epics/202605/unified_artifacts_epic5_migration.md`. The Phase 5.6 completion tale reused the epic prompt instead of
having its own one-to-one prompt, so the validator correctly reports that the prompt links back to the epic rather than
the completion tale.

Nearby SDD convention supports this diagnosis: phase handoff/completion tales that do not have a matching prompt use
metadata like `create_time`, `bead_id`, `tier`, and `status`, but do not claim a `prompt:` link to the parent epic's
prompt. They are allowed to remain unpaired warnings in non-strict validation.

## Fix Strategy

Use the smallest data repair that preserves the existing artifact graph:

1. Remove the incorrect `prompt:` link from `sdd/tales/202605/unified_artifacts_epic5_phase56_completion.md`.
2. Keep the `plan: sdd/epics/202605/unified_artifacts_epic5_migration.md` metadata as a parent/plan reference unless
   validation or conventions show it causes a problem; the validator ignores `plan` on tale files, and it documents the
   completion tale's relationship to Epic 5.
3. Do not change `sdd/prompts/202605/unified_artifacts_epic5_migration.md`, because its `plan:` link to the Epic 5 plan
   is correct.
4. Do not add the new file to the legacy validation allowlist; this is a current, fixable metadata error, and the
   allowlist is explicitly closed for historical invalid SDD only.

## Validation Plan

1. Run `just sdd-validate` to confirm the reverse-link error is gone and only existing warnings remain.
2. Run the focused SDD handler tests if needed: `pytest tests/main/test_sdd_handler.py`.
3. Because this repo's memory requires it after any file change, run `just install` if needed and finish with
   `just check`.

## Risk

The change only edits one SDD markdown frontmatter block. The main risk is accidentally breaking a tool that expects
every completion tale to have a `prompt:` field. Current validator rules and nearby phase handoff examples indicate that
unpaired completion/handoff tales are supported as warnings, so this risk is low.
