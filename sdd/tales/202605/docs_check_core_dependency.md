---
create_time: 2026-05-09 11:49:00
status: done
prompt: sdd/prompts/202605/docs_check_core_dependency.md
---
# Fix GitHub Actions `docs-check` dependency resolution

## Context

GitHub Actions fails in the `docs-build` job while running `just docs-check`:

```text
Because sase-core-rs was not found in the package registry and
sase==0.1.0 depends on sase-core-rs>=0.1.1,<0.2.0
```

The repository now declares `sase-core-rs` as a hard runtime dependency of the Python package. Local and CI Python jobs
that run the application handle this by checking out the sibling `sase-core` repo, installing Rust, and letting the
Justfile build/install the PyO3 extension before editable dependency resolution.

The `docs-build` workflow does not check out `sase-core` or install Rust. That is reasonable for documentation, because
the current MkDocs site uses Material, blog, RSS, search, and Markdown extensions only; it does not use `mkdocstrings`
or import the `sase` package during the site build.

The immediate root cause is that `docs-check` depends on `_setup`, and `_setup` performs an editable `sase[dev]`
install. With no local Rust extension available, `uv pip install --no-sources -e ".[dev]"` must resolve the normal
runtime dependency `sase-core-rs>=0.1.1,<0.2.0` from the package registry. The package is not available there for this
CI path, so resolution is unsatisfiable before MkDocs runs.

## Plan

1. Make `just docs-check` a documentation-tooling check instead of a full application editable install:
   - depend only on `_venv`;
   - install the MkDocs dependencies directly into `.venv`;
   - run `.venv/bin/mkdocs build --strict`.

2. Keep the docs dependency constraints aligned with `pyproject.toml`:
   - use the same `mkdocs-material>=9.7,<10` and `mkdocs-rss-plugin>=1.18,<2` constraints in the Justfile command;
   - avoid `-e ".[docs]"`, because installing a project extra still installs the base project and therefore still
     requires `sase-core-rs`.

3. Update user-facing docs that describe `just docs-check`, since it will no longer install the project `docs` extra.

4. Verify the failure mode and the fix:
   - run `SASE_CORE_DIR=/tmp/nonexistent-sase-core just docs-check` to simulate the current docs CI job without a Rust
     core checkout;
   - run focused formatting/check commands for touched files as needed;
   - because this repo requires `just check` after edits, run `just install` first if needed and then `just check`
     unless a local environment blocker prevents it.

## Expected Result

The docs CI job will no longer try to resolve or build `sase-core-rs`, because MkDocs does not need the application
package installed. Other CI jobs that run the application keep using the existing Rust-core checkout/build path,
preserving the hard runtime dependency contract for `sase` itself.
