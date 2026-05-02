---
create_time: 2026-04-08 17:22:32
status: wip
prompt: sdd/prompts/202604/pyenv_shim_cleanup.md
---

# Plan: Remove Stale pyenv sase Shim

## Problem

The pyenv shim at `/home/bryan/.pyenv/shims/sase` keeps reappearing after deletion because:

1. `sase` is pip-installed (editable) in pyenv's Python 3.12.11 from an old workspace (`sase_100`):
   `/home/bryan/.pyenv/versions/3.12.11/bin/sase`
2. `pyenv init -` runs in `.zshrc` and triggers `pyenv rehash`, which regenerates shims for all executables in managed
   Python versions
3. Every new shell session recreates the shim

The user's actual `sase` lives at `/home/bryan/.local/bin/sase` (installed via uv tools).

## Proposed Fix

**Phase 1: Uninstall stale sase from pyenv's Python 3.12.11**

1. Run `/home/bryan/.pyenv/versions/3.12.11/bin/pip uninstall sase sase-github` to remove the stale editable install and
   its dependent package
2. Run `pyenv rehash` to regenerate shims (the sase shim will no longer be created since no pyenv-managed Python has a
   `sase` binary)
3. Verify `/home/bryan/.pyenv/shims/sase` no longer exists
4. Verify `which sase` resolves to `/home/bryan/.local/bin/sase` (the uv-managed one)

No file changes to the sase codebase are needed — this is purely a cleanup of a stale pip installation.
