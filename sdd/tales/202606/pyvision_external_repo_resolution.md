---
create_time: 2026-06-08 10:56:54
status: done
prompt: sdd/prompts/202606/pyvision_external_repo_resolution.md
---
# Plan: Fix pyvision External Repo Resolution

## Context

`just pyvision` succeeds in this agent workspace:

- `/home/bryan/.local/state/sase/workspaces/sase-org/sase/sase_10`

But it fails in the pinned primary SASE checkout:

- `/home/bryan/projects/github/sase-org/sase`

The primary failure is:

```text
Error: pyvision pragma in src/sase/project_aliases.py:160: external repository 'https://github.com/sase-org/sase-github.git' does not reference symbol 'allocate_project_alias'
Error: pyvision pragma in src/sase/project_aliases.py:325: external repository 'https://github.com/sase-org/sase-github.git' does not reference symbol 'ensure_project_alias_locked'
```

Those symbols are referenced by the up-to-date `sase-github` checkout at:

- `/home/bryan/projects/github/sase-org/sase-github/src/sase_github/workspace_plugin.py`

Directly asking pyvision to check that checkout returns `True` for both symbols, so the SASE code and the `sase-github`
consumer are not the problem.

## Diagnosis

The bug is in pyvision's URI pragma checkout selection.

For a URI pragma like `https://github.com/sase-org/sase-github.git`, pyvision scans local sibling directories and
returns the first checkout whose git origin normalizes to that URI. In `/home/bryan/projects/github/sase-org`, there are
several stale numbered `sase-github_*` workspaces with the same origin:

- `sase-github_10`
- `sase-github_11`
- `sase-github_13`
- `sase-github_14`
- `sase-github_15`
- `sase-github_100`

Those stale workspaces do not contain the newer project-alias imports. The good primary checkout
`/home/bryan/projects/github/sase-org/sase-github` does contain them, but pyvision currently accepts the first matching
origin instead of preferring the best available checkout.

This also explains why the numbered agent workspace passes: its parent directory does not contain stale `sase-github_*`
siblings, so pyvision falls back to the healthy deterministic cache clone.

## Implementation Plan

1. Update pyvision in the chezmoi repo, not SASE's vendored copy.
   - Source file: `/home/bryan/.local/share/chezmoi/home/bin/executable_pyvision`
   - Keep SASE's `tools/pyvision-260608` untouched until the source fix is tested.

2. Make external repo resolution deterministic and freshness-aware.
   - Gather all local checkout candidates whose origin matches the pragma URI.
   - Prefer explicit `--external-repo-path` / `PYVISION_EXTERNAL_REPO_PATHS` candidates first.
   - Prefer non-numbered canonical sibling checkouts such as `sase-github` over numbered SASE workspaces such as
     `sase-github_10`.
   - Among remaining candidates, avoid returning the first arbitrary `Path.iterdir()` result; sort candidates so
     behavior is stable.
   - Validate the selected candidate against the requested symbol before reporting that the external repo lacks the
     symbol. If one matching checkout references the symbol, the pragma should pass.

3. Add focused regression coverage in chezmoi's pyvision bash tests.
   - Create two local external repositories with equivalent origins:
     - a stale numbered-style checkout that does not import the symbol
     - a canonical checkout that does import the symbol
   - Verify the URI pragma passes when the canonical checkout exists.
   - Add a second case, if useful, showing explicit `PYVISION_EXTERNAL_REPO_PATHS` wins over sibling discovery.

4. Verify the chezmoi fix.
   - Run `bashunit ./tests/bash/pyvision_test.sh` from `/home/bryan/.local/share/chezmoi`.
   - Run the fixed pyvision source directly against `/home/bryan/projects/github/sase-org/sase`.

5. Re-vendor pyvision into SASE after the source fix is green.
   - Follow `tools/AGENTS.md`: do not hand-edit `tools/pyvision-260608`.
   - Use the repo's vendoring flow (`pyvendor`) so the SASE copy is regenerated from chezmoi.
   - Preserve the existing vendored header convention.

6. Verify SASE.
   - Run `just pyvision` in `/home/bryan/projects/github/sase-org/sase` to confirm the originally failing checkout is
     fixed.
   - Run `just pyvision` in this agent workspace.
   - If SASE files changed beyond markdown/plan files, run `just install` if needed and then `just check` per project
     instructions.

## Notes

The fix should be in pyvision rather than in SASE pragmas. The pragmas are accurate: the symbols are consumed by
`sase-github`. The failure comes from pyvision selecting a stale local checkout just because it has a matching remote
origin.
