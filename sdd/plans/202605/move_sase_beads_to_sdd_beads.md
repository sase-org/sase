---
title: Move version-controlled bead storage to sdd/beads
create_time: 2026-05-01 22:10:51
status: done
prompt: sdd/prompts/202605/move_sase_beads_to_sdd_beads.md
---

# Goal

Move the repository's version-controlled bead database from the legacy root-level bead directory to `sdd/beads/`, and
update references so the runtime, commit workflow, docs, and tests consistently treat `sdd/beads/` as the VC bead
storage location.

# Current Shape

- Runtime VC bead storage is centralized mostly through `sase.bead.project.BEADS_DIRNAME`.
- Several paths are still hardcoded outside that constant:
  - fast path bead resolution in `src/sase/main/bead_fast_path.py`
  - git commit staging/amend behavior in `src/sase/vcs_provider/plugins/_git_commit_dispatch.py`
  - precommit bead detection in `src/sase/workflows/commit/precommit_hooks.py`
  - Rust binding health probe setup in `src/sase/core/health.py`
  - CLI help/onboarding strings and docs/tests.
- Non-version-controlled bead storage remains `.sase/sdd/beads/`; this is a different mode and should not be collapsed
  into the new `sdd/beads/` VC path.
- Rust core production APIs receive explicit bead directory paths from Python; the sibling Rust repo has bead path
  references in docs/tests, not in production directory resolution.
- The current tracked bead state consists of:
  - `sdd/beads/config.json`
  - `sdd/beads/issues.jsonl`
  - `sdd/beads/metadata.json`
  - `sdd/beads/beads.db` is present locally but ignored.

# Plan

1. Move tracked project state.
   - Create `sdd/beads/` and move the tracked JSON state files from the legacy root-level bead directory.
   - Keep `beads.db` untracked and ignored under the new location.
   - Remove the old root-level bead directory if it becomes empty after the move.

2. Update runtime path constants and discovery.
   - Change the VC bead directory constant to `sdd/beads`.
   - Update fast-path lightweight resolution to use the new VC path while preserving `.sase/sdd/beads/` as the non-VC
     path.
   - Review workspace enumeration and CLI location resolution so sibling workspaces look for `sdd/beads/`.
   - Keep existing APIs that accept a `beads_dirname` string working by allowing the string to contain a slash.

3. Update commit and precommit integration.
   - Stage `sdd/beads/` when bead state changes.
   - Amend commits with `sdd/beads/` changes after adding the COMMIT note.
   - Detect either the new `sdd/beads/` store or legacy `.beads/` fallback where the precommit workflow currently checks
     for bead presence.

4. Update human-facing references.
   - Update README/docs/help/xprompt text that describes VC bead storage.
   - Update `.gitignore` to ignore `sdd/beads/beads.db*`.
   - Treat historical SDD plans/specs/research as references too where they describe current paths or contain literal
     examples of the bead directory, because the request is to update all references to this directory.

5. Update tests and fixtures.
   - Replace test setup paths and assertions with `sdd/beads/`.
   - Update golden output and git command assertions that mention the old path.
   - Update sibling Rust test/doc references if needed so cross-boundary parity remains aligned with the Python caller.

6. Verify.
   - Run targeted bead and commit workflow tests first.
   - Run `just install` if needed for the workspace, then `just check` as required by repo instructions after edits.
   - Run a final search for legacy bead directory references. Any remaining matches must be intentionally legacy-only
     and called out.

# Risks And Constraints

- `sdd/` already contains plans, specs, and docs, so staging logic must stage only `sdd/beads/`, not all of `sdd/`.
- Non-VC storage is still `.sase/sdd/beads/`; changing that would alter a separate storage mode and is out of scope.
- Some historical documents may describe past behavior. The default approach is to update literal directory references
  because the user requested all references, but preserve the surrounding historical meaning where possible.
- If the Rust sibling repo is not part of this workspace's final commit surface, at minimum update Python tests and
  production code here, and report any remaining sibling-repo references explicitly.
