---
create_time: 2026-04-30 03:54:11
status: wip
prompt: sdd/prompts/202604/fix_agent_image_file_panel.md
---
# Fix Agent Image File Panel Cycling

## Problem

The affected revived agent added `docs/images/sase_tui_tabs_infographic.png`, but the Agents tab file panel only exposes
the saved binary diff (`/tmp/sase-gh-vDVSDP.diff`). Since `<ctrl+n>` cycles `Agent.extra_files`, the image is not
reachable unless it is present in the agent's loaded file list.

Inspection of the concrete artifact at `~/.sase/projects/sase/artifacts/ace-run/20260430032430/done.json` shows
`image_paths` is missing/empty even though the saved diff contains:

```text
diff --git a/docs/images/sase_tui_tabs_infographic.png b/docs/images/sase_tui_tabs_infographic.png
```

The current image collector can recover that image from the diff when given the correct workspace, but the loaded agent
has no image attachment because the artifact metadata was already written without it.

## Root Cause

There are two related gaps:

1. Completion-time image discovery is too easy to miss for committed image-producing workflows. The
   `include_head_commit` fallback is only enabled for `meta_new_commit`/`meta_pr_url`, but embedded GitHub commit
   workflows in this path only surfaced `meta_commit_message` plus `diff_path`.
2. Loader/revive paths trust `done.json.image_paths` as the only image attachment source. If that field is empty, ACE
   does not infer displayable images from the saved diff, and revived artifact reconstruction also does not preserve
   image paths distinctly from plan files.

## Plan

1. Add a small image-attachment helper that extracts supported existing image files from a saved diff relative to a
   known workspace, without running full git status commands. Keep the existing `collect_agent_image_paths()` behavior
   intact and reuse the same path normalization/dedup rules.
2. In completed-agent loading, when `done.json.image_paths` is empty or incomplete, resolve the agent workspace from
   `project_file` + `workspace_num` and infer images from `diff_path`. Append inferred images after plan files,
   preserving order and avoiding duplicates.
3. Apply the same fallback to workflow-state agent loading so `appears_as_agent` entries are robust even when the dedup
   winner is the workflow record rather than the done record.
4. Improve dedup merging so `extra_files` are appended uniquely, not copied only when the target list is empty. This
   prevents workflow entries with a plan file from dropping images carried by the done entry.
5. Update revive artifact restoration so image `extra_files` are written back as `image_paths`, while non-image
   plan-like attachments remain `plan_path`. This prevents future revive cycles from losing image attachments.
6. Add focused tests:
   - done loader infers an image from a binary diff when `image_paths` is empty;
   - workflow loader includes an inferred image from `diff_path`;
   - dedup merges plan + image extras rather than dropping the image;
   - revive done marker writes image attachments as `image_paths`.
7. Run `just install` first, then focused pytest for the touched paths, and finally `just check` per repo instructions.

## Expected Outcome

The existing `@ju` artifact should load with the PNG in `extra_files`, so the file panel can cycle from the diff to the
image via `<ctrl+n>`. Future agents that add or commit images should record `image_paths` more reliably, and revive
should preserve those attachments.
