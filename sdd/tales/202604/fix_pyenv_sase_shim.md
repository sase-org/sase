---
create_time: 2026-04-11 22:50:15
status: wip
prompt: sdd/prompts/202604/fix_pyenv_sase_shim.md
---

# Fix pyenv shim for `sase` being repeatedly recreated

## Problem

The file `/home/bryan/.pyenv/shims/sase` keeps getting recreated, shadowing the intended `sase` binary at
`~/.local/bin/sase`.

### Root Cause

`sase` is installed as an editable package in pyenv's Python 3.12.11:

```
Location: /home/bryan/.pyenv/versions/3.12.11/lib/python3.12/site-packages
Editable project location: /home/bryan/projects/github/sase-org/sase_100
```

This is a stale leftover — the project's `.venv` uses uv with Python 3.14, not pyenv's Python. The installation likely
happened from running `pip install -e .` outside the project venv at some point.

### Why it keeps coming back

`pyenv rehash` scans all pyenv Python versions for executables and creates shims. It runs:

- On every shell init via `eval "$(pyenv init -)"` in `.zshrc`
- After pip installs in any pyenv-managed Python

Since sase is installed in 3.12.11, every rehash recreates the shim. And since `~/.pyenv/shims` comes before
`~/.local/bin` in PATH, the shim shadows the uv-installed sase.

## Fix

1. **Uninstall sase from pyenv's Python 3.12.11**:

   ```bash
   /home/bryan/.pyenv/versions/3.12.11/bin/pip uninstall sase
   ```

2. **Run `pyenv rehash`** to clean up the now-orphaned shim.

3. **Verify** `which sase` resolves to `~/.local/bin/sase`.

No repo file changes needed. This is a one-time cleanup of stale system state.
