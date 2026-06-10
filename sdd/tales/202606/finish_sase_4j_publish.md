---
title: Finish sase-4j Public Publish Verification
bead_id: sase-4j
create_time: 2026-06-09 20:47:25
status: wip
prompt: sdd/prompts/202606/finish_sase_4j_publish.md
---

# Finish `sase-4j` Public Publish Verification

## Current State

All child beads under `sase-4j` are closed and the source, docs, and release hardening work is present on `master`. The
remaining unmet epic acceptance criterion is the public package publish:

- `pyproject.toml` is at `0.1.4`.
- GitHub release `v0.1.4` exists.
- Release run `27244950800` completed `build` and `install-smoke` successfully.
- The `publish` job failed because PyPI trusted publishing has no matching publisher for `repo:sase-org/sase`, workflow
  `.github/workflows/release.yml`, environment `pypi`, ref `refs/heads/master`.
- PyPI still serves `sase==0.1.0`, so the public `uv tool install sase --python 3.12` path is still stale.

## Plan

1. Add or confirm the PyPI trusted publisher for the `sase` project with these claims: `repo=sase-org/sase`,
   `workflow=release.yml`, `environment=pypi`, `ref=refs/heads/master`.
2. Rerun the failed `publish` job from release workflow run `27244950800`.
3. Verify PyPI now reports a current `sase` release newer than `0.1.0`.
4. Verify a clean public install path: `uv tool install sase --python 3.12 --force`, `sase version`, `sase doctor`, and
   `sase run --help`.
5. Re-run the local launch-readiness checks needed for final confidence: `just check`, `just docs-check`, and
   `just docs-pdf-check`.
6. Update the epic plan frontmatter at `sdd/epics/202606/p0_onboarding.md` so `status: done`.
7. Close the epic bead with `sase bead close sase-4j`.
