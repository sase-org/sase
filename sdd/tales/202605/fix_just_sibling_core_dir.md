---
create_time: 2026-05-22 17:25:59
status: done
prompt: sdd/prompts/202605/fix_just_sibling_core_dir.md
---
# Plan: Fix `fix_just` install in numbered SASE workspaces

## Diagnosis

The failed `sase_fix_just` chop reached the first `xprompts/fix_just.yml` workflow step, `_just_install`, which runs
`just install`. The failure was not from the chezmoi chop definition itself. The agent metadata for the failed run
already contained the resolved workspace-matched sibling core checkout:

```text
/home/bryan/.local/state/sase/workspaces/sase-org/sase-core/sase-core_13
```

However, the main repo `Justfile` defaults `sase_core_dir` to `../sase-core`. From a numbered workspace such as:

```text
/home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_13
```

that default points at a non-existent path:

```text
/home/bryan/.local/state/sase/workspaces/sase-org/sase/sase-core
```

Because the local Rust core checkout was missed, `just install` skipped `just rust-install` and then ran
`uv pip install --no-sources -e ".[dev]"`. That forced dependency resolution against package indexes only, where
`sase-core-rs` is not available, so the resolver failed before any actual fixer checks could run.

## Goal

Make `just install` automatically use SASE's resolved workspace-matched `core` sibling repo when a SASE-launched agent
provides it, while preserving the explicit `SASE_CORE_DIR` override and the existing flat-checkout `../sase-core`
fallback.

## Implementation Plan

1. Update the `Justfile` `sase_core_dir` assignment to prefer sources in this order:
   - explicit `SASE_CORE_DIR`;
   - SASE launch env `SASE_SIBLING_REPO_CORE_DIR`;
   - legacy/default `../sase-core`.

2. Add a focused regression test that evaluates the `Justfile` variable and proves:
   - `SASE_CORE_DIR` still wins when set;
   - `SASE_SIBLING_REPO_CORE_DIR` is used when `SASE_CORE_DIR` is absent;
   - the legacy fallback remains `../sase-core`.

3. Run targeted verification:
   - the new focused pytest test;
   - `SASE_SIBLING_REPO_CORE_DIR=/home/bryan/.local/state/sase/workspaces/sase-org/sase-core/sase-core_11 just install`
     to exercise the path used by chop agents in this workspace layout.

4. Run the repo-required full verification after source changes:
   - `just check`.

## Expected Outcome

`sase_fix_just` and other SASE-launched agents can run plain `just install` in numbered workspaces without manually
exporting `SASE_CORE_DIR`. Existing local developer checkouts and CI remain compatible because explicit `SASE_CORE_DIR`
and the `../sase-core` fallback stay intact.
