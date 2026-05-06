---
create_time: 2026-05-05 08:39:07
status: done
prompt: sdd/prompts/202605/bead_create_relative_plan_paths.md
---
# Bead Create Relative Plan Paths

## Context

`sase bead create` currently parses plan beads with `--type plan(<plan_file>[,<parent_id>])`, validates that the plan
file exists, resolves the file path, normalizes sibling workspace prefixes back to the primary workspace, and stores the
result in the bead `design` field. Because the stored value is still absolute after `Path.resolve()`, new plan beads can
persist paths like `/home/bryan/projects/github/sase-org/sase_100/sdd/epics/202605/legend_bead_integration.md`.

The attached Telegram screenshot shows this symptom in the bead plan display: the plan field carries a machine-local
absolute path even though the plan file lives under the repository. That makes bead JSONL less portable across
workspaces and machines.

There is already a related helper, `normalize_workspace_path()`, in `src/sase/bead/cli_common.py`; it rewrites ephemeral
sibling workspace roots back to the primary workspace. It does not make paths relative. The fast-path Rust bead CLI has
display-time support for relativizing `design` paths, but `create` is not handled by that fast path, and display-only
relativization would not fix newly stored bead data.

## Goal

Make newly created plan beads store workspace-relative plan paths when the referenced plan file is inside the project
workspace, while preserving existing behavior for valid external paths.

Examples:

- From primary workspace: `/home/bryan/projects/github/sase-org/sase_100/sdd/epics/202605/legend_bead_integration.md`
  becomes `sdd/epics/202605/legend_bead_integration.md`.
- From an ephemeral sibling workspace:
  `/home/bryan/projects/github/sase-org/sase_101/sdd/epics/202605/legend_bead_integration.md` first maps to the primary
  workspace, then stores as `sdd/epics/202605/legend_bead_integration.md`.
- A plan file outside the resolved workspace stays absolute after sibling-workspace normalization, since there is no
  trustworthy project-relative representation.

## Proposed Design

1. Add a focused path-normalization helper in `src/sase/bead/cli_common.py`.

   The helper should accept a resolved plan-file `Path` and return a string suitable for bead storage. It should reuse
   the existing `normalize_workspace_path()` behavior, then attempt to strip the primary workspace prefix. If primary
   workspace resolution is unavailable, it should attempt to strip the bead project root or current working directory
   only where that is already the command’s effective project context. If no project-relative form is valid, it should
   return the normalized absolute path.

2. Update `handle_bead_create()` in `src/sase/bead/cli_crud.py`.

   Replace the current `design = str(normalize_workspace_path(plan_file.resolve()))` assignment with the new storage
   helper. Keep the existing file existence check before normalization. Do not change `parse_type_arg()` behavior in
   this pass.

3. Keep scope limited to `create`.

   Do not silently rewrite existing bead records or alter `sase bead update --design` in the first implementation unless
   tests reveal that the same helper is already clearly required there. The user asked for `sase bead create`, and a
   migration could surprise users who intentionally stored external or historical absolute paths.

4. Preserve external paths.

   If a plan path is outside the resolved primary workspace/project root, store the normalized absolute path. This
   avoids inventing `../../...` paths that are ambiguous, fragile, or leak implementation details in a different way.

5. Add focused tests.

   Add CLI-level tests around `handle_bead_create()` that assert the stored `issue.design` is relative for:
   - a plan file under the current project root;
   - a plan file under a sibling `sase_<N>` workspace when `resolve_primary_workspace()` points to the primary
     workspace.

   Also add a test that an external absolute plan file remains absolute. Existing tests that create plan beads with
   absolute temp paths should be updated only where their assertions conflict with the new intended behavior.

6. Verify command output and downstream work compatibility.

   `sase bead show`, `sase bead list`, and `sase bead work` should continue to work because they already treat `design`
   as a displayable string or plan-file string. The change only improves stored values for workspace-local plan files.

## Risks and Tradeoffs

- If the project is in non-version-controlled SDD mode, the beads store root may be `.sase/sdd/`, while plan files may
  still be in `.sase/sdd/...`. The helper should not assume every valid relative path starts with `sdd/`; it should
  relativize to the effective workspace/project root when possible.
- If `resolve_primary_workspace()` is unavailable in a test or non-agent shell, falling back too aggressively to
  `Path.cwd()` could make unrelated absolute paths relative. The fallback should only be used when the resolved plan
  path is under the current command root.
- Existing beads will still show absolute paths until separately migrated or updated. That is intentional for this first
  change.

## Validation

Run targeted tests first:

```bash
just install
pytest tests/test_bead/test_cli_changespec.py tests/main/test_bead_fast_path.py
```

Then run the repository check required for SASE repo changes:

```bash
just check
```
