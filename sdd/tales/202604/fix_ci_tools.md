---
create_time: 2026-04-04 11:33:35
status: done
prompt: sdd/prompts/202604/fix_ci_tools.md
---

# Plan: Fix chezmoi CI workflow missing tool installations

## Problem

The GitHub Actions CI workflow fails because several tools required by the Justfile are not installed in the CI
environment. The immediate error is `llscheck: not found`, but there are other missing tools as well.

## Current State

The CI workflow (`.github/workflows/ci.yml`) has two jobs:

- **lint** - runs `just lint` (which runs `lint-py`, `lint-lua`, `lint-md`)
- **test** - runs `just test` (which runs `test-nvim`, `test-bash`, `test-python`)

Currently installed in CI:

| Tool        | lint job | test job |
| ----------- | -------- | -------- |
| Python 3.12 | Yes      | Yes      |
| Node.js 20  | Yes      | No       |
| prettier    | Yes      | No       |
| just        | Yes      | Yes      |
| uv          | Yes      | Yes      |

## Missing Tools

### Lint job needs

| Tool     | Install method   | Required by |
| -------- | ---------------- | ----------- |
| luarocks | apt-get          | lint-lua    |
| llscheck | luarocks install | lint-lua    |
| luacheck | luarocks install | lint-lua    |

### Test job needs

| Tool     | Install method   | Required by      |
| -------- | ---------------- | ---------------- |
| luarocks | apt-get          | test-nvim        |
| neovim   | apt-get / PPA    | test-nvim (nlua) |
| nlua     | luarocks install | test-nvim        |
| busted   | luarocks install | test-nvim        |
| bashunit | curl from GitHub | test-bash        |

Note: `nlua` is a Neovim-based Lua interpreter used by the `.busted` config (`lua = "nlua"`), so Neovim must be
available at runtime.

## Implementation

### Phase 1: Add missing tool installations to lint job

Add steps to `.github/workflows/ci.yml` lint job:

1. Install luarocks via `apt-get install luarocks`
2. Install llscheck and luacheck via `luarocks install --local`
3. Add `~/.luarocks/bin` to `$PATH`

### Phase 2: Add missing tool installations to test job

Add steps to `.github/workflows/ci.yml` test job:

1. Install luarocks via `apt-get install luarocks`
2. Install Neovim (needed for nlua) - use a stable PPA or `rhysd/action-setup-vim` action
3. Install nlua and busted via `luarocks install --local`
4. Add `~/.luarocks/bin` to `$PATH`
5. Install bashunit via curl from GitHub releases (v0.34.1)
6. Add bashunit to `$PATH`
