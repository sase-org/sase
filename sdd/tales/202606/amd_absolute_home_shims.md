---
create_time: 2026-06-06 11:29:40
status: done
prompt: sdd/prompts/202606/amd_absolute_home_shims.md
---
# Plan: Make `sase amd init` generate absolute home-provider shims

## Summary

Update the AMD provider-shim generator so SASE no longer emits `@~/AGENTS.md` for home-level instruction entrypoints.
The generator should preserve project-local behavior (`@AGENTS.md`), generate absolute imports for direct live-home
files, and generate chezmoi template sources for chezmoi-managed home files:

- Project roots: `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, `OPENCODE.md` contain `@AGENTS.md`.
- Live home root without chezmoi: provider shims contain an absolute import such as `@/home/bryan/AGENTS.md`.
- Chezmoi home source root: provider shims are managed as `*.md.tmpl` files containing
  `@{{ .chezmoi.homeDir }}/AGENTS.md`, so deployed files render to an absolute path on each machine.

This is a follow-up to the dotfiles fix that converted the live chezmoi sources to templates. Without this SASE-side
change, running `sase amd init` or `sase memory init` in chezmoi mode can recreate plain `*.md` files beside the new
`*.md.tmpl` sources and can reintroduce the broken `@~/AGENTS.md` form.

## Relevant Current State

- `src/sase/amd/constants.py` defines `HOME_PROVIDER_SHIM_CONTENT = "@~/AGENTS.md\n"`.
- `src/sase/amd/_shared.py` chooses provider shim content by root equivalence, but it returns only content, not the
  correct source path. That is insufficient for chezmoi because the desired source path is now `CLAUDE.md.tmpl`, not
  `CLAUDE.md`.
- `src/sase/amd/_planner.py` and `src/sase/amd/_runner.py` can plan and apply writes, but not deletions. Chezmoi source
  migration needs to remove stale plain `*.md` shim sources when replacing them with `*.md.tmpl`.
- `src/sase/main/init_memory/roots.py` reuses the AMD shim helper, so it must move to the same path/content abstraction
  or `sase memory init` can undo the AMD fix.
- `src/sase/amd/inventory.py` currently checks plain provider shim filenames beside `AGENTS.md`; it will report chezmoi
  template shims as missing unless inventory also understands the preferred `.tmpl` source path.
- Docs in `docs/init.md` and `docs/configuration.md` still describe live-home and chezmoi-home shims as `@~/AGENTS.md`.

## Implementation Plan

1. Introduce a shared provider-shim spec abstraction in `src/sase/amd/_shared.py`.
   - Add a small immutable model, for example `ProviderShimSpec`, with at least:
     - `filename`: the provider filename, such as `CLAUDE.md`.
     - `path`: the source path SASE should manage for the selected root.
     - `content`: the exact desired source content.
     - `legacy_paths`: old source paths that should be cleaned up when safe.
   - Keep ordinary project roots simple: `path=root / filename`, `content="@AGENTS.md\n"`.
   - For direct live-home roots, use `path=root / filename` and `content=f"@{root.resolve(strict=False)}/AGENTS.md\n"`.
   - For `config_core.CHEZMOI_HOME`, use `path=root / f"{filename}.tmpl"` and
     `content="@{{ .chezmoi.homeDir }}/AGENTS.md\n"`, with `root / filename` as the legacy plain source path.
   - Keep backward compatibility helpers where useful, but move new planning, writing, and status logic to the spec
     interface instead of a root-to-content function.

2. Teach provider-shim status detection about current and legacy forms.
   - Treat the preferred spec path with exact desired content as `exact_shim`.
   - Treat old recognized forms as `shim`, including project `@AGENTS.md`, legacy home `@~/AGENTS.md`, direct absolute
     home shims, and the chezmoi template source content.
   - For chezmoi roots, prefer the `.md.tmpl` source when present. If both the preferred template and a plain legacy
     source exist, report the template status and separately plan cleanup of the plain file when it is a recognized
     shim.
   - If both preferred and legacy paths exist with custom/conflicting content, block rather than guessing which file
     should win.

3. Extend AMD planning and application to migrate chezmoi shim paths.
   - Add a planned deletion or cleanup action type. The cleanest approach is to extend `InitOperation` with `delete` and
     add a corresponding AMD operation model, while keeping the shared init rendering generic.
   - Update `provider_shim_writes` into a more general provider-shim plan function that can return writes plus cleanup
     actions.
   - In check mode, report creation of `*.md.tmpl` files and deletion of stale plain `*.md` shim sources without
     writing.
   - In apply mode, write preferred shim paths first, then remove stale legacy plain paths only when they contain
     recognized shim content. Never delete custom provider instruction content.
   - Preserve existing migration behavior for exactly one custom provider instruction file when `AGENTS.md` is missing,
     but make it path-aware so a custom `CLAUDE.md.tmpl` or legacy `CLAUDE.md` in the chezmoi source is handled
     deliberately.

4. Update `sase memory init` to use the same provider-shim specs.
   - Replace the current `provider_shim_content_for_root(...)` usage in `src/sase/main/init_memory/roots.py` with the
     new spec planner.
   - Let memory planning surface the same `create`, `overwrite`, and `delete` actions for provider shims.
   - Let memory apply write preferred shim paths and safely delete stale recognized legacy plain paths.
   - Ensure deferred chezmoi deployment receives both written template paths and deleted legacy paths, so the chezmoi
     commit/apply path can stage removals as well as additions. If the existing deploy helper only handles existing
     paths, update it to stage deleted paths safely.

5. Update `sase amd list` inventory.
   - Use provider-shim specs to check preferred paths.
   - For chezmoi source entries, display provider filenames as user-facing `CLAUDE.md` etc., but base status on the
     preferred `.md.tmpl` source.
   - Optionally render stale legacy plain shims as warnings or `shim` status until `sase amd init` cleans them up.

6. Update tests.
   - `tests/main/test_amd_init.py`:
     - Change live-home expectations from `@~/AGENTS.md` to absolute `@<home>/AGENTS.md`.
     - Add/adjust chezmoi tests to assert `CLAUDE.md.tmpl`, `GEMINI.md.tmpl`, `QWEN.md.tmpl`, and `OPENCODE.md.tmpl` are
       written with `@{{ .chezmoi.homeDir }}/AGENTS.md`.
     - Add a regression test where stale plain `CLAUDE.md` exists in the chezmoi source and `sase amd init --check`
       reports both creating/updating the template and deleting the plain legacy shim without modifying files.
     - Add an apply test for the same migration.
   - `tests/main/test_init_memory_chezmoi.py` and `tests/main/test_init_memory_plan.py`:
     - Update provider shim path/content expectations for direct home and chezmoi home roots.
     - Verify `sase memory init` does not recreate plain chezmoi shim sources.
   - `tests/main/test_amd_list.py`:
     - Add or update inventory expectations so `.md.tmpl` chezmoi shims are reported as exact shims.
   - Keep existing project-root shim tests unchanged except for any helper API updates.

7. Update documentation.
   - Replace docs that say live-home and chezmoi-home shims contain `@~/AGENTS.md`.
   - Document the new behavior:
     - direct live-home shims contain absolute `@/path/to/home/AGENTS.md`;
     - chezmoi source shims are `*.md.tmpl` files containing `@{{ .chezmoi.homeDir }}/AGENTS.md`;
     - deployed chezmoi shims render to absolute imports.
   - Touch the AMD sections in `docs/init.md` and `docs/configuration.md`; update README snippets only if they describe
     shim contents directly.

## Verification

After implementation:

1. Run focused tests:
   - `uv run pytest tests/main/test_amd_init.py tests/main/test_amd_list.py tests/main/test_init_memory_plan.py tests/main/test_init_memory_chezmoi.py`
2. Run `just install` if this workspace has not been initialized recently, then run `just check` as required after repo
   file changes.
3. Optionally perform a manual dry-run against the real chezmoi source:
   - `sase amd init --check`
   - Confirm it does not want to recreate plain `~/.local/share/chezmoi/home/{CLAUDE,GEMINI,QWEN,OPENCODE}.md` when the
     corresponding `.md.tmpl` files already exist.

## Out of Scope

- Do not modify the canonical memory files.
- Do not modify the live chezmoi dotfiles as part of this SASE repo change; the prior dotfiles fix already converted
  those sources.
- Do not add commit/push/apply deployment behavior to explicit `sase amd init` unless a separate requirement asks for
  it. This plan keeps AMD focused on writing the selected source roots and keeps deployment behavior where it already
  exists.
