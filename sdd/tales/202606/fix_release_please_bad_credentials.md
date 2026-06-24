---
create_time: 2026-06-24 07:24:48
status: done
prompt: sdd/prompts/202606/fix_release_please_bad_credentials.md
---
# Plan: Stop the `Publish` workflow's intermittent `release-please: Bad credentials` failures

## Problem

The `Publish` GitHub Actions workflow (`.github/workflows/publish.yml`) intermittently fails in its `release` job with:

```
Error: release-please failed: Bad credentials - https://docs.github.com/rest
```

Yesterday's attempted fix (commit `dcf015e02`, "ci: add publish workflow concurrency") added a `concurrency:` block.
That only serializes runs on the same ref; it does nothing about per-run API load, trigger frequency, or transient-error
recovery — so the failures continue.

This plan diagnoses the true root cause and makes the workflow resilient so these red failures stop recurring.

## Diagnosis (evidence-based)

Findings from the CI run history and repo state:

1. **The failure is intermittent, ~12.5% of runs** (≈5 failures out of the last 40 `Publish` runs). The same job
   succeeds on most pushes.

2. **Every failure happens mid-"Backfilling file list for commit ..." — at a random point.** In one failed run
   release-please dies after backfilling only ~2 commits; in another after ~350 commits. The job never reaches the write
   phase (tree/commit/PR creation). Successful runs perform the identical backfill and then create/update the release PR
   (#180) with no problem.

3. **The token is valid.** Because the failure point is random and the _same_ credential succeeds in hundreds of API
   calls on other runs, the token is not expired or misconfigured. The job is being rejected with a transient
   `401 Bad credentials` _under load_, not because the credential is bad.

4. **release-please does a huge API burst on every push.** The last GitHub release is **v0.4.0 (2026-06-18)**. The
   **v0.5.0 release PR (#180) has been open and unmerged for ~6 days**, so on every push release-please re-walks **every
   commit since v0.4.0 (~350+ and growing)** and backfills each commit's file list via individual REST calls — hundreds
   of requests in ~90 seconds, per run.

5. **master is pushed very frequently.** ~40 `Publish` runs in ~2 hours, many triggered by trivial
   `chore: Add SDD prompt and plan ...` commits that only touch `sdd/`. Each such push fires a full, heavy `release`
   run.

6. **The `|| secrets.GITHUB_TOKEN` fallback is dead code.** `SASE_RELEASE_TOKEN` is configured (a non-empty repo
   secret), so `${{ secrets.SASE_RELEASE_TOKEN || secrets.GITHUB_TOKEN }}` always resolves to the PAT. The fallback
   never triggers and gives a false sense of resilience; worse, if the PAT ever _were_ removed, it would silently fall
   back to `GITHUB_TOKEN`, which cannot trigger downstream workflows.

### Root cause

On every push to `master`, the `release` job fires release-please, which makes a burst of hundreds of GitHub API calls
(re-walking the large, ever-growing commit window back to v0.4.0). Under that burst — amplified by very frequent pushes
— GitHub intermittently returns a transient `401 Bad credentials` for an otherwise-valid token. release-please/Octokit
does **not** retry `401`, so a single spurious rejection aborts the entire job. The result is the ~1-in-8 red failures
the user keeps seeing. The credential itself is fine; the problem is **unbounded API burst + over-frequent triggering +
no transient-error recovery**.

## Goals

- Eliminate the recurring `release: Bad credentials` failures (no more red `Publish` runs from this).
- Do not regress the actual release flow (release PR maintenance, tagging, build, PyPI publish).
- Prefer a fix that needs **no new infrastructure/secrets**, with an optional gold-standard hardening path documented
  for later.

## Approach — defense in depth

The fix attacks all three contributing layers: recover from the transient error, shrink the burst, and reduce how often
the heavy job runs.

### 1. Make a transient `401` non-fatal: retry the release-please step with backoff (primary fix)

A `uses:` action step cannot be retried natively, so chain up to **three** release-please attempts in the `release` job,
each `continue-on-error: true` except the last, gated on the previous attempt's `outcome == 'failure'`, with a short
**`sleep` backoff step between attempts** (≈60s) so any secondary-rate-limit / transient-load window clears before
retrying.

- release-please is **idempotent**: re-running simply recomputes the release PR, so repeated attempts are safe.
- The job output `release_created` becomes the OR of the attempts' outputs
  (`steps.release3.outputs.release_created || steps.release2... || steps.release1... || 'false'`), so downstream
  `build`/`install-smoke`/`publish` gating is preserved exactly.
- With independent-ish ~12.5% failure odds and a backoff between tries, three attempts drive the user-visible failure
  probability to a fraction of a percent.

### 2. Cut the number of heavy runs: add `paths-ignore` to the `push` trigger

Add `paths-ignore` to `publish.yml`'s `push` trigger for high-churn, non-release-relevant paths (at minimum `sdd/**`;
also consider research/docs-only markdown and memory docs). A large share of the failing runs are triggered by
`sdd/`-only chore commits.

- **Safe for correctness:** release-please walks full git history, not just the triggering push's diff. Commits skipped
  by an ignored push are still picked up the next time the workflow runs on a code change, so no changelog entries are
  lost.
- Net effect: far fewer heavy `release` runs → less cumulative API pressure and far fewer chances to hit the flaky path.

### 3. Remove the misleading dead fallback

Replace `${{ secrets.SASE_RELEASE_TOKEN || secrets.GITHUB_TOKEN }}` with an explicit `${{ secrets.SASE_RELEASE_TOKEN }}`
so the credential in use is unambiguous and a missing PAT fails loudly instead of silently degrading to a token that
can't trigger downstream workflows. (If we adopt the optional App-token hardening in §5, this line is replaced by the
generated app token instead.)

### 4. Operational: shrink the backfill window

The single biggest reason each run is heavy is that release PR **#180 (v0.5.0) has sat unmerged for ~6 days**, so the
backfill window keeps growing. **Merging #180 to cut the v0.5.0 release** resets the walk from ~350 commits to ~0, so
each subsequent run makes only a handful of API calls — well under any burst threshold. Going forward, cutting releases
promptly keeps the window (and the burst) small.

This is an operational action, not a code change, but it's the deepest structural relief and should be called out so the
user does it as part of landing this fix.

### 5. Optional gold-standard hardening: GitHub App installation token

For maximum durability regardless of release cadence, replace the static PAT with a **fresh GitHub App installation
token** minted per run via `actions/create-github-app-token`:

- Fresh, short-lived token each run (no stale-credential risk).
- Installation tokens get a **15,000 req/hour** budget (vs a PAT's 5,000) and a more generous secondary-rate-limit
  allowance, so the backfill burst no longer trips the transient-401 regime.
- Can trigger downstream workflows (unlike `GITHUB_TOKEN`). This is the release-please-recommended auth method.

This requires one-time setup the user must perform: create a GitHub App in the `sase-org` org with `contents: write`,
`pull-requests: write`, `issues: write` permissions, install it on the repo, and store `SASE_RELEASE_APP_ID` +
`SASE_RELEASE_APP_PRIVATE_KEY` as secrets. Documented here as an opt-in upgrade so the primary fix (§1–§3) can land
immediately with no new infrastructure.

## Files to change

- `.github/workflows/publish.yml`
  - `on.push`: add `paths-ignore` (§2).
  - `release` job: replace the single release-please step with the retry chain + backoff steps, update the job's
    `release_created` output to OR across attempts, and make the token explicit (§1, §3).
  - (Optional §5) add an `actions/create-github-app-token` step and feed its token to release-please.

No changes needed to `release-please-config.json` or `.release-please-manifest.json`; the deep walk is correct behavior
— we're making it resilient and less frequent, not changing release semantics.

## Verification

- **Static:** validate the edited workflow YAML (e.g. `actionlint` if available, or a YAML parse) so the retry chain,
  `if:` gating, and output expression are well-formed.
- **Functional:** after merging, watch several `Publish` runs on master. Expect: (a) `sdd/`-only pushes no longer
  trigger `Publish`; (b) any single transient `401` is absorbed by a retry and the job still goes green; (c) the release
  PR continues to be created/updated and, on a real release, `build` → `install-smoke` → `publish` still run.
- Confirm the `release_created` output still correctly gates downstream jobs (a normal push keeps it `false`; merging
  the release PR flips it `true` and publishes).
- After merging release PR #180, confirm subsequent `release` runs do a small backfill instead of ~350 commits.

## Risks & mitigations

- **Retry re-runs the heavy backfill.** Mitigated by the `sleep` backoff (lets the transient/secondary window clear) and
  by §2/§4 shrinking the burst so retries are rarely needed.
- **`paths-ignore` could skip a release-worthy commit's trigger.** Mitigated: release-please walks full history, so the
  commit is still included on the next non-ignored run; only the _trigger_ is skipped, never the changelog content. Keep
  the ignore list conservative (start with `sdd/**`).
- **Retry-chain YAML is more verbose** than a single step. Acceptable; it preserves the action's outputs without
  reimplementing release-please via the CLI.
- **(If §5 adopted)** App setup is a one-time manual step; the primary fix does not depend on it.
