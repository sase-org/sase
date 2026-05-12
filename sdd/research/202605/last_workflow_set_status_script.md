# Last Workflow Set Status Script

Date: 2026-05-11

## Question

How should we implement a script that finds the last set of GitHub Actions workflows to fully run on `master`/`main`,
reports whether they all passed, and (when any failed) names the failing workflows and tails their error output?

## Summary

Build a small script around the `gh` CLI (already installed at `/usr/bin/gh`, v2.92.0). The core algorithm is:

1. Enumerate the repo's "interesting" workflows once.
2. Walk recent runs on the target branch (newest → oldest) and group them by `headSha`.
3. Pick the newest `headSha` where every interesting workflow has a `status == "completed"` run — that commit is the
   "last set".
4. For that group, report `conclusion` per run; if any are not `success`/`skipped`, fetch failed-step logs with
   `gh run view --log-failed` and tail them.

`gh` is the right primitive here because it handles auth, pagination, and JSON projection, and exposes both
`gh run list` (cheap metadata) and `gh run view --log-failed` (just the failed steps' logs, which is exactly the tail we
want and avoids downloading the full multi-MB log zip).

The non-obvious decisions are: (a) what counts as "the last set" when workflows can be added/removed or skipped by path
filters, and (b) how to keep the log tail useful without downloading entire job logs. Both are addressed below.

## Current Repo State

Repository: `sase-org/sase` (origin from `git remote -v`).

Active workflows (`gh workflow list`):

- `CI` (id 245920129) — `.github/workflows/ci.yml`
- `Deploy Docs` (id 273843005) — `.github/workflows/docs-deploy.yml`
- `Publish to PyPI` (id 245920130) — `.github/workflows/publish.yml`

Sample of `gh run list --branch master --limit 5 --json …` confirms each push to `master` triggers `CI` and
`Deploy Docs` together, while `Publish to PyPI` only fires on tag pushes (i.e., not present in every per-commit set).
This is the central reason "the last set" is not the same as "the last N runs".

## Defining "the last set to fully run"

The user-facing phrase has three plausible meanings; pick one explicitly in the script:

1. **Per-commit grouping (recommended default).** A "set" is all workflow runs sharing the same `headSha` on the target
   branch. The "last set to fully run" is the newest such SHA where every relevant workflow has a non-`in_progress`,
   non-`queued` run. This matches what a human means when they ask "did CI pass for the last commit on master?".
2. **Last run per workflow.** For each workflow, take its latest completed run on the branch (potentially from
   different commits). Easier to implement (`gh run list --workflow <id> --branch <branch> --status completed
   --limit 1`) but mixes commits and can hide a regression that has not yet had every workflow re-run.
3. **Last completed batch by trigger event.** Group by `(headSha, event)`. Useful if the same SHA is pushed and also
   manually re-run, but rarely what people want.

We recommend (1) and treat (2) as a `--per-workflow` flag.

### Which workflows are "relevant" for a given SHA?

Workflows can be:

- **Always-on for the branch** (e.g., `CI`, `Deploy Docs` on push to master).
- **Conditional** via `on.push.paths`, `on.push.branches`, or `if:` guards — won't appear at all for some SHAs.
- **Tag- or release-only** (e.g., `Publish to PyPI` here, which fires on `v*` tags, not branch pushes).

Three viable strategies for choosing the relevant set:

- **A. Discovered set.** Trust whatever runs were *actually* triggered for the SHA. A SHA "fully ran" once none of
  those runs are still `in_progress`/`queued`. This naturally handles path filters and tag-only workflows but cannot
  detect a workflow that *should* have run and was silently dropped (e.g., a YAML parse error).
- **B. Configured set.** Compare against `gh workflow list` (active workflows) and require each to have a run for the
  SHA. Will permanently never satisfy on a branch push if any workflow is tag-only (`Publish to PyPI`), so this needs
  per-workflow opt-out config, which is annoying for users.
- **C. Discovered set + reachability filter.** Discovered set, but additionally fetch each active workflow's YAML
  (`gh api /repos/:owner/:repo/contents/.github/workflows/<file>`) and statically check whether it could fire on
  `push` to the branch. Most accurate, but requires parsing YAML triggers — overkill for v1.

Recommendation: ship strategy **A** as the default with a `--require <name,name,…>` flag for users who want to assert
that specific workflows must be present (covers strategy B's safety net without its rigidity).

## Tooling Options

### `gh` CLI (recommended)

Pros:

- Already installed and authenticated.
- `gh run list --branch <b> --json …` returns structured JSON, paginated with `--limit`.
- `gh run view <id> --log-failed` returns *only* the failed steps' logs. This is the closest thing to a "tail of error
  output" without downloading and grepping the full log archive.
- `gh run view <id> --json jobs` exposes per-job conclusions and step names — useful when `--log-failed` is empty
  (e.g., a job was cancelled before any step failed).

Cons / gotchas:

- `gh run list` returns runs across *all* workflows by default, so we must paginate enough to be sure we captured every
  run for the target SHA. Empirically, fetching `--limit 50` is more than enough for this repo (≤3 workflows per push)
  but should be configurable.
- `gh` man page warns that log-fetching has platform limitations: when the in-zip job→log mapping is missing, `gh`
  falls back to per-job API calls and aborts if more than 25 job logs are missing. Not a concern at this repo's scale.
- `--log-failed` returns the entire failed-step output, not a tail. The script should pipe through `tail -n N` (with
  `N` configurable, default ~50) per failed run.

### Raw REST API (`gh api` or `curl`)

Useful endpoints:

- `GET /repos/{owner}/{repo}/actions/runs?branch=master&per_page=100` — same as `gh run list` but returns
  `head_commit`, `run_attempt`, etc.
- `GET /repos/{owner}/{repo}/actions/runs/{run_id}/jobs` — per-job status, with `steps[]` including each step's
  `conclusion` and `number`. Use this to identify the *first failing step*, then…
- `GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs` — returns plain-text logs for one job (subject to the
  same retention window, ~90 days by default).

This is necessary if we ever want to tail logs in environments without `gh`, or to fetch only one specific step's
output. For v1 on this repo, `gh` is simpler.

### GraphQL (`gh api graphql`)

Could fetch workflow runs and their `checkSuite` in one round trip, but offers no advantage over REST for this use
case and complicates pagination.

## Recommended Algorithm (Pseudocode)

```text
branch        := flag --branch (default: detect main vs master via `gh repo view --json defaultBranchRef`)
fetch_window  := flag --limit  (default: 50 runs)
tail_lines    := flag --tail   (default: 50)
require_set   := flag --require (default: empty; comma-sep workflow names that MUST appear)

runs := gh run list --branch $branch --limit $fetch_window \
          --json databaseId,workflowName,workflowDatabaseId,headSha,status,conclusion,createdAt,event,displayTitle,url

# Group newest-first by headSha, preserving order of first appearance.
groups := stable_group_by(runs, key=headSha)

for (sha, sha_runs) in groups:
    if any(r.status in {"in_progress", "queued", "waiting", "requested", "pending"} for r in sha_runs):
        continue  # this SHA is still running; skip
    if require_set and not require_set.issubset({r.workflowName for r in sha_runs}):
        continue  # missing a workflow the user demanded
    chosen_sha, chosen_runs := sha, sha_runs
    break
else:
    error: no fully-completed run set found in last $fetch_window runs; rerun with --limit larger

# Report
print header: commit chosen_sha, displayTitle, createdAt
ok_conclusions := {"success", "skipped", "neutral"}
failed := [r for r in chosen_runs if r.conclusion not in ok_conclusions]

if not failed:
    print "All N workflows passed."
    exit 0

print "FAIL: M of N workflows did not pass:"
for r in failed:
    print "  - {r.workflowName} ({r.conclusion}) — {r.url}"

for r in failed:
    print divider, "=== {r.workflowName} (run {r.databaseId}) ==="
    log := gh run view $r.databaseId --log-failed   # may be empty for cancelled runs
    if log empty:
        # Fall back: list failing steps from jobs JSON
        jobs := gh run view $r.databaseId --json jobs
        for job in jobs where job.conclusion not in ok_conclusions:
            print "  job: {job.name} → {job.conclusion}"
            for step in job.steps where step.conclusion not in ok_conclusions:
                print "    step: {step.name} → {step.conclusion}"
    else:
        print last $tail_lines lines of log
exit 1
```

## Edge Cases & Gotchas

- **`status` values that mean "not done":** `queued`, `in_progress`, `waiting`, `requested`, `pending`. Treat any of
  these as "set not complete". Treat `completed` as the only terminal status.
- **`conclusion` values:** `success`, `failure`, `cancelled`, `skipped`, `timed_out`, `action_required`, `neutral`,
  `stale`, `startup_failure`. The script should treat `success` and `skipped` (and arguably `neutral`) as
  "passed"; everything else, including `cancelled`, as "did not pass" — because a cancelled CI run is not evidence
  master is healthy.
- **Manual reruns / multiple attempts.** Re-running a single failed workflow creates a new run (or a new attempt) for
  the same `headSha`. If we naively pick the newest run per workflow within a SHA group, we get the latest attempt —
  usually what the user wants. Document this.
- **Tag pushes vs branch pushes.** `Publish to PyPI` here only runs on tags, so it should *not* be in `--require` for
  branch-status checks. Default behavior (strategy A) handles this correctly because tag-only workflows simply will
  not appear in branch-push run sets.
- **Path-filtered workflows.** Same as above — strategy A naturally tolerates them.
- **Log retention.** GitHub keeps Actions logs for 90 days by default. Older runs may return empty logs from
  `gh run view --log-failed`. Treat empty logs as "logs unavailable" and print the structured job/step summary
  instead.
- **Authentication.** `gh` must be authenticated for private repos. The script should fail with a clear message
  pointing at `gh auth status` rather than a cryptic API error.
- **Repo selection.** Default to the repo of the current working directory (`gh` does this implicitly), but accept
  `--repo OWNER/NAME` for use outside a clone. Pass it through to every `gh` invocation.
- **Default branch detection.** Don't hard-code `master`. Resolve via
  `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name` (sase uses `master`, but most modern repos are
  `main`).
- **Pagination.** `gh run list --limit N` accepts up to 1000. For active repos with many workflows, the default
  fetch window of 50 may not contain a fully-completed set. The script should detect "no candidate found" and
  suggest raising `--limit`.

## Implementation Choice: Bash vs Python

Both are reasonable.

- **Bash + `jq`:** ~80 lines, no dependencies beyond `gh`/`jq`/`tail`. Best for a tool that ships as a one-file
  utility and lives in `bin/` or `scripts/`. Slightly painful for the "stable group by headSha" step but doable with
  `jq`'s `group_by`.
- **Python (stdlib only, shelling out to `gh`):** ~150 lines, easier to test, easier to extend (e.g., emit JSON for
  another tool to consume, integrate with sase's existing test harness).

Recommendation: **Python**. The script lives in a Python project, will likely grow (per-workflow flag, structured
output for sase ace, color/no-color toggles), and stdlib `subprocess` + `json` is enough — no extra deps.

## Concrete Commands the Script Will Run

```bash
# Default branch
gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name'

# Run metadata (newest first; gh's natural order)
gh run list \
  --branch "$BRANCH" \
  --limit "$LIMIT" \
  --json databaseId,workflowName,workflowDatabaseId,headSha,status,conclusion,createdAt,event,displayTitle,url

# For each failed run in the chosen set:
gh run view "$RUN_ID" --log-failed         # primary: tail this output
gh run view "$RUN_ID" --json jobs           # fallback when --log-failed is empty
```

## Out of Scope (Possible Follow-ups)

- Posting a summary to Slack/Telegram (would slot into sase's existing notification surfaces).
- Watching a SHA until it completes (`gh run watch`) — different feature; this script is a status snapshot.
- Diffing the failing step's log against the previous successful run on the same workflow to surface the new failure
  signature.
- Caching the last reported SHA so the script can be used as a cron-style notifier ("notify me when a new master SHA
  finishes its workflow set").

## References

- `gh run list --help`, `gh run view --help` (local).
- GitHub REST: `actions/runs`, `actions/runs/{id}/jobs`, `actions/jobs/{id}/logs`
  (https://docs.github.com/rest/actions/workflow-runs, /actions/workflow-jobs).
- GitHub Actions status & conclusion enums (https://docs.github.com/rest/checks/runs#create-a-check-run — same enums
  apply to workflow runs).
