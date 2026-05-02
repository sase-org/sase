---
status: done
create_time: 2026-05-01 23:21:01
prompt: sdd/prompts/202605/migrate_root_sdd_artifacts.md
---

# Plan: Migrate Remaining Root Specs And Plans Into SDD

## Goal

Move the last repository-root `specs/` and `plans/` artifacts into the canonical `sdd/` tree, then remove the legacy
root directories once they are empty. The migration should preserve unique historical content, avoid overwriting newer
canonical SDD files, and leave prompt/plan frontmatter links valid through SASE-owned repair tooling rather than
hand-authored metadata.

## Current State

- `specs/` contains four May 2026 prompt snapshots:
  - `specs/202605/markdown_pdf_attachment_limit.md`
  - `specs/202605/move_sase_beads_to_sdd_beads.md`
  - `specs/202605/retry_agent_name_suffix.md`
  - `specs/202605/sdd_prompt_management.md`
- `plans/` contains nineteen markdown plans:
  - Four May 2026 plans matching the remaining root specs above.
  - Thirteen dated `sase_plan_*` files under `plans/202603/` and `plans/202604/`.
  - Two flat root `sase_plan_*` files that already have canonical `sdd/tales/202604/*` counterparts.
- Canonical SDD layout already exists:
  - prompts: `sdd/prompts/{YYYYMM}/*.md`
  - plans: `sdd/tales/{YYYYMM}/*.md`
  - epics: `sdd/epics/{YYYYMM}/*.md`
  - legends: `sdd/legends/{YYYYMM}/*.md`
- `src/sase/sdd/links.py` can repair unambiguous prompt-plan links by matching `{kind}/{YYYYMM}/{name}.md`.
- The working tree has parser and handler support for `sase sdd`, but the installed `sase` on PATH in this workspace is
  stale and currently does not expose the `sdd` command. Verification must start with `just install`.

## Migration Policy

Use a manifest-driven migration rather than a blind `mv`.

1. Root prompt snapshots move from `specs/{YYYYMM}/{name}.md` to `sdd/prompts/{YYYYMM}/{name}.md`.
2. Root May plans move from `plans/{YYYYMM}/{name}.md` to `sdd/tales/{YYYYMM}/{name}.md`.
3. Root `sase_plan_*` plans should be compared against canonical SDD names with the `sase_plan_` prefix stripped,
   matching `save_plan_to_sase()` behavior.
4. If a canonical SDD counterpart already exists and its body is equivalent aside from frontmatter and leading
   blank-line formatting, keep the SDD file and remove the root duplicate.
5. If a canonical SDD counterpart exists but has substantively different body content, do not overwrite it. Preserve the
   root file under a non-colliding SDD filename, preferably the original basename, and record it as an unpaired
   historical plan unless a prompt counterpart can be inferred.
6. If no SDD counterpart exists, move the root file into `sdd/tales/{YYYYMM}/` with the `sase_plan_` prefix stripped
   when that target name is free. For root files without a dated directory, infer the month only when there is an
   existing SDD counterpart; otherwise stop and inspect rather than guessing.

Expected duplicate handling from the read-only survey:

- Already represented in `sdd/tales` and removable after body-equivalence check:
  - `plans/202603/sase_plan_axe_error_notification_action.md`
  - `plans/202603/sase_plan_commits_multiline_notes.md`
  - `plans/202603/sase_plan_fix_crs_changespec_entry.md`
  - `plans/202603/sase_plan_fix_empty_commit_chat.md`
  - `plans/202604/sase_plan_approve_options_constraints.md`
  - `plans/202604/sase_plan_cls_tab_l0_spacing.md`
  - `plans/202604/sase_plan_enter_accepts_file_completion.md`
  - `plans/202604/sase_plan_file_completion_improvements.md`
  - `plans/202604/sase_plan_prometheus_telemetry.md`
  - `plans/202604/sase_plan_status_background_task.md`
  - `plans/sase_plan_agent_name_in_completion_toast.md`
  - `plans/sase_plan_changespec_suffix_match.md`
- Root-only plan content expected to be moved into `sdd/tales/202604/`:
  - `plans/202604/sase_plan_dynamic_memory.md` -> `sdd/tales/202604/dynamic_memory.md`
  - `plans/202604/sase_plan_fix_mentor_checks_timeout_v2.md` -> `sdd/tales/202604/fix_mentor_checks_timeout_v2.md`
  - `plans/202604/sase_plan_lower_claude_effort_level.md` -> `sdd/tales/202604/lower_claude_effort_level.md`
- Root-only May prompt/plan pairs expected to move as linked SDD pairs:
  - `markdown_pdf_attachment_limit`
  - `move_sase_beads_to_sdd_beads`
  - `retry_agent_name_suffix`
  - `sdd_prompt_management`

## Implementation Steps

1. Reconfirm the manifest immediately before editing:
   - `git status --short`
   - `find specs plans -type f | sort`
   - destination existence checks under `sdd/prompts` and `sdd/tales`
   - body-equivalence checks for files with existing canonical counterparts
2. Create any missing destination directories under `sdd/prompts/202605`, `sdd/tales/202604`, and `sdd/tales/202605`.
3. Move the four May prompt snapshots and four May plans into `sdd/prompts/202605` and `sdd/tales/202605`.
4. Move the three root-only April plans into `sdd/tales/202604` using the normalized names above.
5. Remove only the root duplicate plan files whose canonical SDD counterpart has already been confirmed equivalent.
6. Remove empty legacy directories under `specs/` and `plans/`.
7. Run `just install` so the workspace CLI includes the current `sase sdd` command.
8. Run `sase sdd repair-links -p sdd --write` so code backfills bidirectional `prompt` and `plan` fields for the four
   new May prompt/plan pairs and any other unambiguous pairs touched by this migration.
9. Review the repair report and the resulting diff:
   - Expected frontmatter link changes should be deterministic.
   - Unpaired historical plans such as April root-only moved plans may remain warnings unless they have matching
     prompts.
   - No absolute paths should be introduced into tracked SDD files.
10. Update active references that still point to root `specs/` or root `plans/` only when they describe current tracked
    artifact locations. Avoid rewriting old prompt snapshots or historical research prose solely for archival mentions.

## Verification

- `sase sdd validate -p sdd`
- `just sdd-validate`
- Focused tests if validation exposes code-path regressions:
  - `pytest tests/main/test_sdd_handler.py tests/test_sdd.py tests/test_commit_workflow_artifacts.py`
- Full required repo check after file changes:
  - `just check`

## Risks And Guardrails

- Do not overwrite existing `sdd/tales` files with root `plans` files unless the destination is missing.
- Do not delete root files until their SDD destination is either created or confirmed equivalent.
- `sase sdd repair-links --write` repairs only unambiguous name/month pairs. That is the desired behavior; historical
  unpaired plans should remain unlinked instead of inventing prompt references.
- The stale installed CLI is an environment risk, not a migration design issue. `just install` is required before using
  `sase sdd` commands.
