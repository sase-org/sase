---
create_time: 2026-05-13 10:30:47
status: done
prompt: sdd/prompts/202605/bead_fast_path_config_gate.md
---
# Plan: Align bead fast-path store resolution with SDD VC mode

## Context

The earlier `bead_fast_path_vc_mode.md` plan was written for the same user-visible failure: fast-pathed `sase bead` read
commands could print `No issues found.` because the resolver selected a stale non-VC store before the current checkout's
`sdd/beads` store.

That exact failure has already been fixed by changing `src/sase/main/bead_fast_path.py` to prefer the current checkout's
`sdd/beads` before `primary/.sase/sdd/beads`. The focused regression in `tests/main/test_bead_fast_path.py` now covers
the mixed current-checkout plus primary non-VC store case.

One recommendation from the older plan remains relevant: the fast-path resolver still chooses by directory existence
alone. It does not consult `sase.sdd.beads.get_sdd_config()`, while the slow path in
`sase.bead.cli_common.find_beads_location()` does. That means the fast path can still disagree with normal bead CLI
resolution when `sdd.version_controlled` and stale or incidental on-disk directories conflict.

## Goal

Make fast-pathed bead commands use the same VC/non-VC store selection policy as the slow path, without expanding the
fast path to initialize missing stores or change write-command safety behavior.

## Implementation

1. Update `src/sase/main/bead_fast_path.py::_resolve_lightweight_beads_context`.
   - When `_resolve_primary_workspace_by_project_scan(cwd)` finds a primary workspace, lazily import
     `sase.sdd.beads.get_sdd_config`.
   - If `get_sdd_config()` is true, resolve only VC stores:
     - prefer the nearest ancestor of `cwd` containing `sdd/beads`;
     - otherwise use `primary/sdd/beads` if it exists;
     - otherwise return `None` so the slow path can handle the command.
   - If `get_sdd_config()` is false, resolve only the non-VC primary store:
     - use `primary/.sase/sdd/beads` if it exists;
     - otherwise return `None`.
   - Keep the existing legacy walk-up fallback for the no-primary case.

2. Keep write-command behavior unchanged.
   - `_resolve_fast_path_context()` should continue to return `None` for write commands when the resolved directory kind
     is the non-VC beads directory.
   - The change should only affect which store kind can be resolved in primary-workspace contexts.

3. Simplify helper usage only where it makes the policy clearer.
   - `_select_current_checkout_beads_dir()` can remain as the VC ancestor lookup helper.
   - `_select_primary_beads_dir()` may be removed or kept depending on whether the implementation still needs it.

## Tests

1. Extend `tests/main/test_bead_fast_path.py` so config mode is explicit.
   - Patch `sase.sdd.beads.get_sdd_config` to `True` in VC-mode tests.
   - Patch it to `False` in non-VC tests.

2. Add or update fast-path resolver regressions:
   - VC mode with both `primary/.sase/sdd/beads` and current checkout `sdd/beads` present must return the current
     checkout VC store.
   - VC mode with a primary VC store and a stale primary non-VC store must ignore the non-VC store.
   - Non-VC mode with both a primary non-VC store and a current checkout VC store present must return the primary non-VC
     store.
   - Non-VC write commands must remain disabled through the fast path.

3. Keep the existing single-store CLI read tests as integration coverage.

## Verification

Run:

```bash
just install
.venv/bin/python -m pytest tests/main/test_bead_fast_path.py -q
.venv/bin/python -m pytest tests/test_bead/test_cli_read_single_store.py -q
.venv/bin/sase bead stats
.venv/bin/sase bead list -s closed
just check
```

If `just check` fails in an unrelated existing gate, capture the failing command and error after confirming the focused
fast-path and single-store tests pass.
