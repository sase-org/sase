---
create_time: 2026-04-29 18:35:39
status: done
prompt: sdd/prompts/202604/install_sase_github_core_rs.md
---
# Fix `install_sase_github` Resolution Of Local `sase-core-rs`

## Problem

Running `install_sase_github -i` fails in the initial `uv tool install` step:

```text
Because sase-core-rs was not found in the package registry and sase==0.1.0 depends on sase-core-rs>=0.1.0,<0.2.0
```

The current chezmoi installer syncs local checkouts for `sase`, `sase-core`, `sase-github`, and `sase-telegram`, then
runs:

```bash
uv tool install --force --editable \
    "sase @ $SASE_DIR" \
    --with-editable "sase-github @ $SASE_GITHUB_DIR" \
    --with-executables-from sase-github \
    --with-editable "sase-telegram @ $SASE_TELEGRAM_DIR" \
    --with-executables-from sase-telegram
```

But `sase/pyproject.toml` now declares `sase-core-rs>=0.1.0,<0.2.0` as a hard runtime dependency. Since that Rust
binding package is built from the sibling `sase-core/crates/sase_core_py` project and is not currently available from
the package registry used by `uv`, dependency resolution fails before the later `just rust-install-uv-tool` step can
build the local extension into the uv-tool environment.

## Root Cause

The installer was updated to build `sase_core_rs` after the uv-tool environment exists, but the environment cannot be
created unless `uv tool install` can resolve `sase-core-rs` up front.

The source-install story in the main repo already handles the editable venv case via `just install`: it builds the
sibling Rust package before `uv pip install -e ".[dev]"`. The chezmoi uv-tool installer needs the equivalent resolver
input for tool installs.

## Implementation Plan

1. Update the chezmoi-managed `install_sase_github` script to pass the local Rust binding project into the initial
   `uv tool install`, for example:

   ```bash
   --with-editable "sase-core-rs @ $SASE_CORE_DIR/crates/sase_core_py"
   ```

   This gives the resolver a local package named `sase-core-rs` at version `0.1.0`, satisfying `sase`'s declared runtime
   dependency without requiring the package to exist on PyPI.

2. Apply the same fix to `install_retired_mercurial_plugin`, because it has the same install shape and will hit the same resolver
   failure whenever it installs the local editable `sase` package.

3. Keep the existing `just -f "$SASE_DIR/Justfile" rust-install-uv-tool` call after `uv tool install`. The local
   `--with-editable` input solves dependency resolution and creates the tool venv; the Just target remains the explicit
   release-mode refresh path for the compiled extension in that uv-tool venv.

4. Add a small guard before the install step to fail clearly if `$SASE_CORE_DIR/crates/sase_core_py/pyproject.toml` is
   missing. The existing sync loop already assumes the repo exists, but this catches partial or stale checkouts with a
   targeted message instead of a long resolver/build error.

5. Validate with a non-destructive resolver/install simulation where possible, then run the required chezmoi validation:

   ```bash
   just check
   ```

   from `~/.local/share/chezmoi`.

6. If validation passes, run the actual installer command:

   ```bash
   /home/bryan/.local/share/chezmoi/home/bin/executable_install_sase_github -i
   ```

   Then verify the uv-tool `sase` environment can import the Rust extension and report backend health:

   ```bash
   "$(uv tool dir)/sase/bin/python" -c "import sase_core_rs"
   sase core health --json
   ```

## Files Expected To Change

- `~/.local/share/chezmoi/home/bin/executable_install_sase_github`
- `~/.local/share/chezmoi/home/bin/executable_install_retired_mercurial_plugin`

No changes are expected in the main `sase`, `sase-core`, `sase-github`, or `sase-telegram` repos unless validation
reveals a separate packaging issue.
