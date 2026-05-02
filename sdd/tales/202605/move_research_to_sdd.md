---
create_time: 2026-05-02 18:19:03
status: done
prompt: sdd/prompts/202605/move_research_to_sdd.md
---
# Move root-level research under sdd/

## Goal

Move the repository-local research corpus from the old root-level research directory to `sdd/research/` and update
references so current docs, default prompts, tests, and historical SDD artifacts no longer point at the old root-level
location.

## Current State

- The old root-level research directory currently contains date-sharded material under `202602/`, `202603/`, `202604/`,
  and `202605/`, including one PNG asset in its `202604/` shard.
- `sdd/` already exists and contains `prompts/`, `tales/`, `epics/`, `legends/`, `assets/`, and `beads/`; there is no
  `sdd/research/` directory yet.
- The live product text still says research remains top-level:
  - `README.md`
  - `docs/sdd.md`
  - `docs/xprompt.md`
  - `src/sase/default_config.yml`
- Tests contain at least one fixture creating an old root-level workspace research file and asserting attachment PDF names
  for that path.
- Many checked-in SDD prompt/tale/epic artifacts and research notes contain path references like
  `sdd/research/202604/rust_backend_migration.md`.

## Implementation Plan

1. **Move the directory as a single tree.**
   - Create `sdd/research/` by moving the existing root-level research directory there.
   - Preserve the existing `YYYYMM/` layout and filenames exactly.
   - Ensure no root-level research directory remains.

2. **Rewrite path references in tracked text files.**
   - Replace file and directory path references from the old root-level location to `sdd/research/`.
   - Cover Markdown, YAML, JSON/JSONL, Python, config, and ignore files because references appear in all of those.
   - Include historical SDD artifacts because the user explicitly requested all references.
   - Avoid replacing unrelated prose uses of the word `research` or third-party names/URLs such as `agiresearch/...`.
   - Update old research file-reference tags to `@sdd/research/...`.
   - Update absolute or embedded design paths only when they include the repo-relative `sdd/research/...` segment.

3. **Update current behavior-facing documentation and prompts.**
   - Change the built-in `#research` xprompt body to ask agents to write under `sdd/research/`.
   - Update `docs/xprompt.md` so `#research` documents the new destination.
   - Update `README.md` and `docs/sdd.md` to describe research as part of `sdd/`, not as a top-level exception.
   - Update `.prettierignore` to ignore `sdd/research/`.

4. **Adjust tests and expected generated paths.**
   - Update fixtures that create sample research files under the old workspace root-level location so they use
     `workspace/sdd/research/`.
   - Update expected markdown PDF artifact names if the path-derived filename changes from `research__example.md.pdf` to
     `sdd__research__example.md.pdf`.
   - Keep tests focused on behavior, not on preserving the old root-level location.

5. **Verify no stale root path references remain.**
   - Run a targeted search for old root-level research path references and inspect remaining hits.
   - Remaining valid hits should be only:
     - new `sdd/research/...` paths,
     - xprompt names like `research/prompt` or `research/more`,
     - non-path words or external identifiers such as `agiresearch`.
   - Run a second search for old research file-reference tags.
   - Confirm `find research` fails and `find sdd/research` lists the moved files.

6. **Run checks.**
   - Per workspace memory, run `just install` before validation.
   - Run focused tests touched by the move first, especially attachment discovery and xprompt config tests.
   - Run `just check` before reporting completion.

## Risks and Handling

- **Historical artifacts are large and noisy.** Use a targeted path-prefix rewrite and then inspect residual matches
  rather than hand-editing every old prompt/tale.
- **Some docs intentionally said not to move research.** Since the current request supersedes that prior direction,
  update those statements instead of preserving the old recommendation.
- **Path-derived artifact names may change.** Accept the new `sdd__research__...` naming in tests because it reflects
  the real source path after migration.
- **Binary files should not be rewritten.** Move the PNG normally but limit textual replacements to tracked text-like
  files.

## Acceptance Criteria

- All files previously under the old root-level research directory exist under `sdd/research/`.
- The root-level research directory no longer exists.
- No tracked references to old root-level research file or directory paths remain.
- Current docs and built-in prompts direct new research output to `sdd/research/`.
- Updated tests pass, and `just check` completes successfully.
