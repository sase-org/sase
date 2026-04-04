---
create_time: 2026-04-04 12:16:08
status: done
---

# Plan: Fix CI — missing LuaCov dependency

## Problem

The CI `test` job fails with:

```
busted: error: LuaCov not found on the system, try running without --coverage option, or install LuaCov first
```

## Root Cause

The `.busted` config sets `coverage = true` in the `_all` section, which tells busted to load `luacov` for code coverage
instrumentation. LuaCov is not installed in the CI environment — the "Install Lua test tools" step installs `nlua` and
`busted` but not `luacov`.

This likely worked before because `coverage = true` was added to `.busted` after the CI workflow was last updated (or
`.busted` was newly created with coverage enabled).

## Fix

**File: `.github/workflows/ci.yml`** (chezmoi repo) — Add `luacov` to the "Install Lua test tools" step:

```yaml
- name: Install Lua test tools
  run: |
    luarocks install --local nlua
    luarocks install --local busted
    luarocks install --local luacov
    echo "$HOME/.luarocks/bin" >> $GITHUB_PATH
    echo "LUA_PATH=$(luarocks path --local --lr-path);;" >> $GITHUB_ENV
    echo "LUA_CPATH=$(luarocks path --local --lr-cpath);;" >> $GITHUB_ENV
```

No changes needed to `.busted`, the Justfile, or any other files.
