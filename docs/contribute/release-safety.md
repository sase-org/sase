---
title: "Release Safety and Recovery"
description:
  "How to recover a broken family release: yank then fix forward, core backfill, and the
  safety nets that catch the next one."
---

# Release Safety and Recovery

This runbook is the recovery side of the installable-family promise: a broken `sase`
release is yanked and fixed forward, an empty core window is backfilled, and the canary,
the floor check, and the retention protected set catch the next failure before a user
does.

## Yank, then fix forward

PyPI's web UI is the only way to yank a release. There is no yank API, and upload tokens
are upload-only, so this step is always human. Three facts shape everything else:

- An exact pin still installs yanked files. `sase==0.17.1` keeps working after a yank;
  only unpinned resolution skips the yanked release. A yank protects fresh installs
  without breaking pinned ones.
- Never move a tag or reuse a version number. The fix always ships as a new version; a
  yanked version number stays burned.
- A recovery release is never blocked by the safety nets below. An install outage holds
  unrelated packaging churn, never a separately qualified recovery release.

### Why `sase` 0.1.0 is yanked

`sase` 0.1.0 has no `sase-core-rs` dependency, so whenever every newer release's core
window is empty the resolver silently falls back to it — a February 2025 build
installing as if it were current. Yanking 0.1.0 turns that silent fallback into a loud
resolver error, which is what the documented `uv tool install "sase>=0.18"` floor
already assumes: while no newer window resolves, the floored command fails visibly
instead of installing something ancient. Undoing it is the same page in reverse
(un-yank), which restores the fallback if a recovery ever needs a last-resort
installable release.

To yank (or un-yank) it:

1. Log in to [PyPI](https://pypi.org) as a `sase` maintainer and open
   `https://pypi.org/manage/project/sase/releases/`.
2. Open the `0.1.0` release, fill in the yank reason (for example "E1 runbook: prevent
   silent fallback to 0.1.0; see the release-safety runbook"), and confirm.
3. Verify from any machine: `curl -s https://pypi.org/pypi/sase/0.1.0/json` must show
   `"yanked": true` under `info`. Un-yanking flips the same control back.

## Core backfill

When a supported `sase` release's core window holds no complete version at all, no
retention setting can help: the version the window needs was already deleted. The remedy
is a backfill — a new core patch cut from an old tag, for example `sase-core-rs` 0.32.17
from `v0.32.16` — published through the guarded manual route in `release-plz.yml`. The
exact steps, the quota cost (a full release, about 75–105 MB), and the side effect that
a `dry_run=false` dispatch also merges an open release PR live in the
[`sase-core` retention doc](https://github.com/sase-org/sase-core/blob/master/docs/pypi-retention.md#core-backfill).
Backfill is human-gated; no agent or workflow performs it.

## Recovery is never blocked

The canary and the headroom alert are detectors, not gates: a red run opens or updates
an issue and never holds a release. The dependency-floor check is the only new merge
blocker, and it applies only to family plugin release PRs. A separately qualified
recovery release always ships through the normal train while the incident is open.

### Resume an interrupted train

When a train stalls after the candidate is sealed — a partial upload, a lost
confirmation — re-enter it with `release.yml -f mode=resume` at the same tag. Resume
runs only `publish` and `confirm` from the stashed bytes: it never rebuilds, and it
refuses without passing evidence. Recovering an old version is never a rebuild, and the
old `publish.yml` re-publish route is gone.

## The safety nets

- **Family install canary** (`install-smoke.yml`, helper `tools/check_family_install`).
  A red run means a clean `uv tool install` of `sase`, alone or with the family plugins,
  no longer produces the newest working release on Linux or macOS. Each matrix leg
  uploads an `install-canary-<os>.json` artifact (`schema_version`, os, run id, attempt,
  sha, verdict `green`/`red`, per-package expected/installed versions and rules, failing
  step and reason). The alert is green only when the smoke job succeeded and both OS
  artifacts (`install-canary-ubuntu-latest.json` and `install-canary-macos-latest.json`)
  are present, readable, and green; a missing artifact counts as red. A red scheduled
  (or opted-in dispatch) run opens or comments on one `install-canary` issue, and a
  later green run closes it. A `workflow_dispatch` probe input forces the red path
  without touching the issue unless asked.
- **Release dependency floor** (`tools/check_release_dependency_floor`, reusable
  workflow `release-dependency-floor.yml`, called by each plugin at `@master`). It
  blocks a plugin release PR whose family sibling floor has no published, non-yanked,
  non-pre-release match, or whose full runtime set does not jointly resolve. It clears
  on its own: the schedule re-runs the failed check for the current head SHA once the
  sibling publishes, with no new push — hourly for the first day, then every four hours,
  stopping at GitHub's 50-attempt rerun cap. A probe input such as `sase>=99` forces the
  red path.
- **Retention protected set** (`.github/scripts/pypi_retention.py`, `pypi_delete.py`).
  Deletion plans derive from live consumer metadata — the newest ten non-yanked releases
  of `sase` and the family plugins, the confirmed-working baseline, the newest 30 core
  releases, and explicit pins — and any list touching the set is refused before
  credentials are read. The
  [`sase-core` retention doc](https://github.com/sase-org/sase-core/blob/master/docs/pypi-retention.md)
  owns the tools, the procedure, and the runway line.

## Practice drill

The yank-and-fix-forward path has an optional TestPyPI rehearsal (`testpypi-drill.yml`
and `tools/check_testpypi_drill`). It was not run when E1 landed. Running it needs the
human-only TestPyPI project and pending-publisher setup first.

## Related

- Bead `sase-1m4` tracks the published blog posts that still show a bare
  `uv tool install sase` command, which resolves to the 0.1.0 fallback this runbook
  yanks. That fix lives with the blog posts, not here.
- The install commands the canary checks are single-sourced in
  `tools/render_applicability`. The family command is `INSTALL.md`'s
  `--with sase-github --with sase-telegram` form plus `--with sase-research-artifacts`.
