---
create_time: 2026-05-08 18:19:43
status: done
prompt: sdd/prompts/202605/fix_ci_uv_source.md
---
# Fix CI break from local uv source

## Diagnosis

The GitHub Actions failure begins at commit `7fb11b80 chore: add MkDocs blog scaffold`; the immediately preceding CI run
for `6ffd0aec` passed. Every failing job stops in the shared `Install dependencies` step, before lint, tests, build, or
performance checks run.

The failing command is `just install`. In CI, `just install` successfully builds and installs `sase_core_rs` from the
checked-out Rust repo at:

```text
/home/runner/work/sase/sase/sase-core/crates/sase_core_py
```

It then runs:

```text
uv pip install -e ".[dev]"
```

That resolver fails with:

```text
error: Distribution not found at: file:///home/runner/work/sase/sase-core/crates/sase_core_py
```

The bad path comes from the docs commit adding this project-level uv source:

```toml
[tool.uv.sources]
sase-core-rs = { path = "../sase-core/crates/sase_core_py" }
```

That path matches this local SASE workspace layout, where sibling workspaces live next to the repo. It does not match
CI: the workflow checks out `sase-core` inside the repo directory with `path: sase-core`, while setting `SASE_CORE_DIR`
so the Justfile can find it. The hard-coded uv source bypasses the Justfile's configurable `SASE_CORE_DIR` and makes uv
look one directory above the repo.

The reason local checks passed is that the local workspace had `../sase-core`, so the new source table was valid
locally. The Actions environment exposed the portability bug.

## Goals

1. Restore CI installs for all jobs that run `just install`.
2. Keep the MkDocs docs extra and `just docs-check` workflow working locally.
3. Avoid encoding one developer/runner checkout layout in project metadata.
4. Keep `sase-core-rs` local-development handling centralized in the Justfile, where `SASE_CORE_DIR` already exists.
5. Keep the fix narrow: no unrelated docs/content churn.

## Implementation Plan

1. Remove the hard-coded `[tool.uv.sources]` entry for `sase-core-rs` from `pyproject.toml`.

2. Update `uv.lock` so it keeps the docs dependency set added by the blog scaffold, but no longer records `sase-core-rs`
   as a local directory source. Concretely:
   - keep the `docs` optional dependency metadata and MkDocs-related locked packages;
   - remove the `[[package]] name = "sase-core-rs"` local-directory package entry;
   - change the root package metadata for `sase-core-rs` back to a plain runtime requirement, matching the pre-docs lock
     shape.

3. Adjust Justfile install/docs commands to ignore project uv sources during editable installs:
   - use `uv pip install --no-sources ...` in `_setup` and `install`;
   - make `docs-check` depend on `_setup`;
   - install the docs extra into the project `.venv` with `uv pip install --no-sources -e ".[docs]"`;
   - run MkDocs through `.venv/bin/mkdocs build --strict` instead of `uv run --extra docs ...`, because `uv run`
     performs a project sync and is the wrong place to build around this repo's unpublished local Rust binding.

4. Verify the fix locally in the same order the repo expects:
   - `just install`
   - `just docs-check`
   - `just check`

5. Check final status and diff, confirming the change is limited to dependency/install plumbing needed to repair CI.

## Expected Outcome

CI will continue to use `SASE_CORE_DIR=${{ github.workspace }}/sase-core` for the Rust checkout and will no longer try
to resolve `../sase-core` through uv project metadata. Local SASE workspaces can keep using the default
`SASE_CORE_DIR=../sase-core`, while docs builds still get MkDocs dependencies through the `docs` extra.
