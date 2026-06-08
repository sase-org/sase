---
create_time: 2026-06-08 11:11:35
status: done
prompt: sdd/prompts/202606/pyvendor_strip_executable_prefix.md
---
# Plan: Strip Chezmoi `executable_` Prefix During Pyvendor

## Context

`pyvendor` lives in the chezmoi repo at `/home/bryan/.local/share/chezmoi/home/bin/executable_pyvendor`. It currently
derives the vendored script name from `basename "$SCRIPT_PATH"`, so vendoring `home/bin/executable_pyvision` produces
`tools/executable_pyvision-YYmmdd` in SASE.

That `executable_` prefix is a chezmoi source-file convention, not the actual runtime script name. For scripts sourced
from the chezmoi repo, `pyvendor` should strip `executable_` before copying into another repository. The SASE repo
currently still references the prefixed dated `pyvision` filename, so the fix must also re-vendor `pyvision` into this
workspace and let references move to the unprefixed dated filename.

## Implementation Plan

1. Update the chezmoi `pyvendor` source to distinguish the source basename from the vendored basename.
   - Keep `script_basename="$(basename "$SCRIPT_PATH")"` for source-path handling.
   - Add a normalized vendored basename, stripping a leading `executable_` only when the source path is from the
     chezmoi-managed tree.
   - Use the normalized basename for the new destination file, old-copy removal, and reference replacement targets.

2. Preserve cleanup of already-vendored prefixed copies.
   - When vendoring `home/bin/executable_pyvision`, remove old dated copies matching both `executable_pyvision-YYmmdd`
     and `pyvision-YYmmdd`.
   - Record reference updates from the removed old basename to the new normalized basename so SASE files that still
     mention the old prefixed dated filename are updated automatically.

3. Add focused bashunit coverage in the chezmoi repo.
   - Create a `tests/bash/pyvendor_test.sh` file using temporary project directories.
   - Cover copying a chezmoi-style `home/bin/executable_foo` source as `tools/foo-YYmmdd`.
   - Cover replacing an existing `tools/executable_foo-OLD` copy and updating project references to `foo-YYmmdd`.
   - Cover that non-chezmoi or non-prefixed script basenames are not unexpectedly renamed.

4. Run focused chezmoi validation.
   - Run the new bashunit test file directly.
   - Run shell syntax checks for `home/bin/executable_pyvendor`.
   - If practical, run the existing bashunit suite; note any environment-only gaps.

5. Re-vendor pyvision into this SASE workspace using the fixed `pyvendor`.
   - Run
     `pyvendor /home/bryan/.local/share/chezmoi/home/bin/executable_pyvision /home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_10`.
   - Confirm the generated file is `tools/pyvision-260608`, not `tools/executable_pyvision-260608`.
   - Confirm the old prefixed dated copy is removed and references in `Justfile`, `tools/AGENTS.md`, and
     tracked SDD docs move to `pyvision-260608`.

6. Validate the vendored SASE result.
   - Compare the vendored script with the chezmoi `executable_pyvision` source, allowing for the inserted provenance
     line.
   - Run `just install` before SASE repo checks because this is an ephemeral workspace.
   - Run `just pyvision`.
   - Run `just check` because non-markdown/tool files in this repo will change.

## Risks and Mitigations

- Broad reference updates are expected because `pyvendor` searches the whole project. I will review the diff and keep
  only changes that correspond to the new vendored filename.
- The source file will still be named `executable_pyvendor` in chezmoi; the runtime command remains `pyvendor` after
  chezmoi applies it. The change is limited to how target filenames are computed during vendoring.
- Chezmoi's full `just check` may still depend on local tools such as `busted`; focused pyvendor tests should provide
  direct coverage even if broader local checks are blocked.
