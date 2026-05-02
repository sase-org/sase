---
create_time: 2026-03-29 10:03:33
status: wip
prompt: sdd/prompts/202603/makefile_to_justfile_1.md
---

# Plan: Migrate chezmoi repo from Makefile to Justfile

## Context

The chezmoi repo currently uses a two-file Make setup (`Makefile` + `targets.mk`) with Docker wrapper support, redundant
Python linters (ruff + black + flake8), and pip-based venv management. The user wants to modernize this to a single
Justfile following the conventions established in the sase repo, and update CI accordingly.

### Design decisions (from user)

1. **Drop Docker** — remove all Docker-related targets and the `.lcldev/use-docker` toggle
2. **Single file** — one Justfile, no imports/mods
3. **Drop black and flake8** — ruff-only for linting and formatting
4. **Migrate to uv** — replace `python3.12 -m venv` + `pip install` with `uv venv` + `uv pip install`
5. **No shell strictness** — use Just's default shell (no `set shell` directive)
6. **`fmt` is the real target, `fix` is an alias** — `fmt` does formatting, `fix` aliases to `fmt`
7. **Delete old files** — remove Makefile, targets.mk, Dockerfile, docker-compose.yml after migration
8. **Update CI** — update `.github/workflows/ci.yml` to use `just` instead of `make`, install uv

## Recipe mapping (Make → Just)

| Just recipe    | Source Make target                | Notes                                                                     |
| -------------- | --------------------------------- | ------------------------------------------------------------------------- |
| `default`      | `help`                            | `@just --list`                                                            |
| `_setup`       | `$(VENV_DIR)`                     | `uv venv` + `uv pip install -r requirements-dev.txt` with staleness check |
| `_header NAME` | `*-header` targets                | Reuse sase's box-drawing helper                                           |
| `fmt`          | `fix`                             | Primary target: `fmt-py fmt-lua fmt-md`                                   |
| `fix`          | —                                 | Alias for `fmt`                                                           |
| `fmt-py`       | `fix-python`                      | `ruff check --fix` + `ruff format` (drop black)                           |
| `fmt-lua`      | `fix-lua`                         | `stylua` (unchanged)                                                      |
| `fmt-md`       | `fix-md`                          | `prettier --write` (unchanged)                                            |
| `fmt-check`    | —                                 | `fmt-py-check fmt-md-check` (CI-friendly)                                 |
| `fmt-py-check` | —                                 | `ruff format --check`                                                     |
| `fmt-md-check` | —                                 | `prettier --check`                                                        |
| `lint`         | `lint`                            | `lint-py lint-lua lint-md`                                                |
| `lint-py`      | `lint-python-lite`                | `ruff check` + `ruff format --check` + `mypy` (drop flake8, black)        |
| `lint-lua`     | `lint-llscheck` + `lint-luacheck` | Combine both Lua linters into one recipe                                  |
| `lint-md`      | `lint-md`                         | `prettier --check` (unchanged)                                            |
| `test`         | `test`                            | `test-nvim test-bash test-python`                                         |
| `test-nvim`    | `test-nvim`                       | `busted` (unchanged)                                                      |
| `test-bash`    | `test-bash`                       | `bashunit` (unchanged)                                                    |
| `test-python`  | `test-python`                     | `cd home/lib/xfile && pytest test` via venv                               |
| `check`        | —                                 | New CI recipe: `fmt-check lint test`                                      |
| `clean`        | `clean`                           | Remove `.venv`, caches (drop docker-clean)                                |

## CI changes

Current CI has two jobs (`lint` and `test`) that run `make lint` and `make test`. The new CI will:

- Remove `USE_DOCKER: true` env var
- Update `actions/checkout` from v2 → v4
- Add `extractions/setup-just@v2` to install just
- Add `astral-sh/setup-uv@v4` to install uv
- Keep Node.js setup for prettier (lint job only)
- Replace `make lint` → `just lint` and `make test` → `just test`

## Phases

### Phase 1: Create Justfile

Write a single `Justfile` in the chezmoi repo root with all recipes from the mapping table above. Follow sase
conventions: `venv_dir`/`venv_bin` variables at top, `_setup` recipe using `uv venv` + `uv pip install`, `_header`
private helper for box banners, comments on each recipe for `just --list`.

The `_setup` recipe should check venv staleness by comparing `requirements-dev.txt` mtime against a sentinel file,
similar to how the current Makefile uses the `$(VENV_DIR)` prerequisite with `requirements-dev.txt`.

### Phase 2: Update requirements-dev.txt

Remove `black` and `flake8` from `requirements-dev.txt` since they're replaced by ruff.

### Phase 3: Update pyproject.toml

Remove `[tool.black]` section. Update the `E501` ignore comment from "let black handle this" to "let ruff handle this".

### Phase 4: Update CI

Rewrite `.github/workflows/ci.yml`:

- Remove `USE_DOCKER: true` env
- Update checkout action to v4
- Add just and uv setup actions
- Keep Python 3.12 and Node 20 setup
- Replace make commands with just commands

### Phase 5: Delete old files

Remove:

- `Makefile`
- `targets.mk`
- `Dockerfile`
- `docker-compose.yml`

### Phase 6: Verify

Run `just fmt`, `just lint`, and `just test` in the chezmoi repo to validate the migration.
