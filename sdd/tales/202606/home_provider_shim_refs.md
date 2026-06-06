---
create_time: 2026-06-06 10:02:01
status: done
prompt: sdd/prompts/202606/home_provider_shim_refs.md
---
# Plan: Make Home Provider Shims Load Home AGENTS.md

## Problem

`sase amd init` currently renders every provider instruction shim with the same content:

```text
@AGENTS.md
```

That is correct for project-local shims such as `<repo>/CLAUDE.md`, because the provider should load `<repo>/AGENTS.md`.
It is ambiguous for home-level shims such as `~/CLAUDE.md`, especially when agents are launched from ephemeral project
workspaces. In that context, a relative `@AGENTS.md` can resolve against the workspace instead of the home instruction
file, which means home-only long-memory references such as `~/memory/long/obsidian.md` may not be surfaced reliably.

The user-requested target is `@~/AGENTS.md`, not `@/home/bryan/AGENTS.md`, so the generated file remains portable across
machines.

## Observations

- The shared constant lives in `src/sase/amd/constants.py` as `PROVIDER_SHIM_CONTENT = "@AGENTS.md\n"`.
- `sase amd init` uses that constant through `provider_shim_writes()`, `provider_statuses()`, and AMD inventory.
- `sase memory init` also imports the same provider-shim content through `src/sase/main/init_memory/constants.py`, so
  the same root-aware behavior should cover both commands.
- Chezmoi home-source roots are home-equivalent for this purpose: a shim written to
  `~/.local/share/chezmoi/home/CLAUDE.md` deploys to live `~/CLAUDE.md`, so its content should also be `@~/AGENTS.md`.
- Project-local provider shims must not switch to `@~/AGENTS.md`, because that would stop project agents from loading
  project-local instructions.
- The referenced agent `33.r1` has stable live artifacts at
  `/home/bryan/.sase/projects/bob-cli/artifacts/ace-run/20260606094012`. Those artifacts show the workspace `CLAUDE.md`
  contained `@AGENTS.md`; they also show the agent eventually did run `sase memory read long/obsidian.md`, so the
  example is not a clean proof that the memory was never read. The root cause is still plausible and worth fixing
  because the home shim currently has the same ambiguous relative import.

## Implementation Approach

1. Introduce root-aware provider shim content.
   - Keep project/default content as `@AGENTS.md\n`.
   - Add home content as `@~/AGENTS.md\n`.
   - Add a small helper, likely in `sase.amd._shared` or a nearby AMD module, that returns the expected shim content for
     a root.
   - Treat roots resolving to `Path.home()` and roots resolving to `config_core.CHEZMOI_HOME` as home-equivalent.

2. Update all shim writers and drift checks to use root-aware content.
   - Change `provider_shim_writes(root)` to write `@~/AGENTS.md\n` only for home-equivalent roots.
   - Change `provider_statuses(root)` and AMD inventory shim classification to compare against the root-specific
     expected content.
   - Preserve recognition of the old `@AGENTS.md` text as a shim, not custom content, so existing home shims are
     reported as stale and overwritten rather than accidentally treated as legacy provider prose.
   - Consider recognizing both `@AGENTS.md` and `@~/AGENTS.md` as shim-shaped content across roots, while only the
     root-specific expected content counts as `exact_shim`.

3. Update `sase memory init` expected-file rendering.
   - Replace direct use of the constant in `src/sase/main/init_memory/roots.py` with the same root-aware helper.
   - Verify project memory init still writes project shims as `@AGENTS.md`.
   - Verify home memory init writes live-home and chezmoi-home shims as `@~/AGENTS.md`.

4. Update tests.
   - AMD init tests:
     - project-managed instructions keep provider shims as `@AGENTS.md`;
     - live home from user config writes `@~/AGENTS.md`;
     - chezmoi home source writes `@~/AGENTS.md`;
     - mixed project plus chezmoi source writes each root's correct shim content.
   - Memory init tests:
     - project root shims remain `@AGENTS.md`;
     - home root shims become `@~/AGENTS.md`;
     - stale home `@AGENTS.md` is planned/reported as an overwrite.
   - AMD inventory tests:
     - `@~/AGENTS.md` is `exact_shim` for home-equivalent roots;
     - old `@AGENTS.md` beside a home `AGENTS.md` is shim-shaped but not exact.

5. Update documentation.
   - Adjust `docs/init.md` to say project provider shims contain `@AGENTS.md`, while home/chezmoi-home provider shims
     contain `@~/AGENTS.md`.
   - Leave checked-in project-root `CLAUDE.md`, `GEMINI.md`, `QWEN.md`, and `OPENCODE.md` as `@AGENTS.md`.

6. Refresh generated/user-facing files only after code and tests are in place.
   - Run targeted tests first.
   - Run `sase amd init --check` to confirm the remaining drift is the intended home shim drift.
   - Run `sase amd init` to update the active home/chezmoi home provider shims if the check output matches the intended
     change.

## Validation

- Run `just install` before repo checks, per project instructions for ephemeral workspaces.
- Run targeted tests around AMD and memory init:

```bash
uv run pytest tests/main/test_amd_init.py tests/main/test_amd_list.py tests/main/test_init_memory_handler.py tests/main/test_init_memory_plan.py
```

- Run `sase amd init --check` before applying the generated shim refresh.
- Run `sase amd init` once the targeted behavior is verified.
- Run `just check` before finishing, because this repo requires it after file changes.
