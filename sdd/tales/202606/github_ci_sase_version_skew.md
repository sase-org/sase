---
create_time: 2026-06-09 15:53:32
status: done
prompt: sdd/prompts/202606/github_ci_sase_version_skew.md
---
# Plan: Fix sase-github CI SASE Version Skew

## Problem Summary

`sase-github` CI fails during `just lint` because the workflow installs `sase-github` with `uv pip install -e ".[dev]"`,
and `pyproject.toml` only declares `sase>=0.1.0`. A clean install resolves `sase==0.1.0` from PyPI.

The current `sase-github` source depends on SASE APIs that exist in the SASE source repo/tag `v0.1.3`, but not in the
published `sase==0.1.0` package:

- `GitCommon.vcs_create_pull_request`
- `sase.ace.mail_ops.get_cl_description`
- `sase.ace.changespec.project_spec_path`
- the commit-dispatch VCS provider hooks/manager methods

The local workspace `.venv` masked this because it imports editable SASE source from the sibling `sase_11` checkout. A
fresh CI-style venv reproduces the reported mypy errors and also exposes later test collection/runtime failures against
`sase==0.1.0`.

## Root Cause

This is not a local typing bug in the two flagged call sites. It is dependency skew: `sase-github` has advanced to the
SASE `v0.1.3` plugin API, but CI/dev dependency installation still allows and receives the older published `sase==0.1.0`
package.

## Implementation Plan

1. Tighten `sase-github`'s SASE dependency metadata from `sase>=0.1.0` to the API level the code actually requires,
   `sase>=0.1.3`.

2. Make CI install a compatible SASE source checkout until `sase==0.1.3` is available from PyPI:
   - Check out `sase-org/sase` at `v0.1.3` into a CI-local directory.
   - Install that checkout into the same `.venv` before or together with `sase-github`.
   - Keep the install path deterministic rather than relying on whatever PyPI currently exposes.

3. Update the `Justfile` install/setup flow to support a `SASE_CORE_PATH` override:
   - If `SASE_CORE_PATH` is set, install editable SASE from that path before installing `sase-github[dev]`.
   - If it is unset, keep the normal published-package install behavior.
   - Use this in GitHub Actions so both lint and test jobs share the same dependency setup.

4. Verify the fix in two ways:
   - Run `just lint` in the `sase-github` workspace with `SASE_CORE_PATH` pointed at the sibling SASE checkout.
   - Run `just test` or at least the failing plugin/workspace tests under the same dependency setup.

5. Report the residual release issue explicitly:
   - CI will be fixed by source checkout pinning.
   - Public installs of the next `sase-github` release should wait until `sase==0.1.3` is published to PyPI, or the
     release workflow should publish SASE first.
