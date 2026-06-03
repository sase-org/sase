---
create_time: 2026-06-03 17:05:45
status: wip
prompt: sdd/prompts/202606/ref_type_frontmatter.md
---
# Add Ref Type Frontmatter To Migrated AI Reference Notes

## Context

The `sase-4b.1` Bob vault migration created 282 Markdown reference notes under `~/bob/ref/ai/**` in commit
`a478dd9384d232485d4aafadbc32903f0d7d171a`. Those notes already have YAML frontmatter with `parent`, `tags`, `status`,
`title`, and source metadata, but they do not currently have a `type` property.

The Bob vault has unrelated local modifications outside `ref/ai`, so this work must stay tightly scoped to the migrated
note files. Existing `ref/*` notes use `type: "[[ref]]"` in YAML. I will use that quoted YAML form so Obsidian sees the
value as the wikilink `[[ref]]` while the frontmatter remains valid YAML.

## Plan

1. Reconstruct the target set from the migration commit with `git -C ~/bob ls-tree -r --name-only a478dd938 -- ref/ai`,
   and verify it still contains 282 Markdown files that exist in the working tree.

2. Confirm the target area is clean before editing with `git -C ~/bob status --short -- ref/ai`, so unrelated dirty
   vault files remain untouched.

3. Apply a bounded mechanical frontmatter update to only those 282 files:
   - Open each target Markdown file.
   - Require a YAML frontmatter block starting at the first line.
   - If a top-level `type:` field is already present in that block, leave the file unchanged.
   - Otherwise insert `type: "[[ref]]"` directly after the existing `parent:` line.
   - Fail fast if a target file lacks frontmatter or lacks `parent`, because that would indicate the migration shape is
     not what we verified.

4. Verify the edit structurally:
   - Count changed files under `~/bob/ref/ai` and confirm it is 282.
   - Confirm every target file now has exactly one top-level `type: "[[ref]]"` line.
   - Confirm no non-target files under `~/bob` were modified by this work.
   - Run `git -C ~/bob diff --check -- ref/ai`.

5. Verify through Obsidian/Dataview if available:
   - Run a `bob dataview` query for `#ai/reference` notes under `ref/ai` and confirm 282 notes report `type = [[ref]]`.
   - If the exact Dataview engine is unavailable, report that explicitly and rely on the file-level verification above.

6. Leave the changes uncommitted unless Bryan asks for a commit, and report the exact verification results.
