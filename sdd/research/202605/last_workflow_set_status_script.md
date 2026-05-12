# Last Workflow Set Status Script

Date: 2026-05-11

## Question

How should we implement a script that finds the last set of GitHub Actions workflows to fully run on `master`/`main`,
reports whether they all passed, and (when any failed) names the failing workflows and tails their error output?

## Update Log

- **2026-05-11 (initial):** Algorithm, `gh` primitives, edge cases.
- **2026-05-11 (revision):** Added annotations-API failure summaries (cleaner than raw log tails), branch-protection
  required-checks as an authoritative "relevant set", `event=push` filtering, attempt-aware rerun handling,
  concurrency-cancellation false-failure detection, merge-queue/`merge_group` notes, performance/parallelism guidance,
  prior-art survey, and a testing strategy.

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

### Strategy D (added): branch protection's required status checks

GitHub's branch-protection rules let maintainers declare *which* check-run contexts must pass before merge. That list
is the authoritative answer to "what counts as a complete set" for a protected branch. Fetch it once:

```bash
gh api "/repos/{owner}/{repo}/branches/{branch}/protection" \
  --jq '.required_status_checks.contexts'      # classic protection
# or, for rulesets (newer):
gh api "/repos/{owner}/{repo}/rules/branches/{branch}" \
  --jq '[.[] | select(.type=="required_status_checks") | .parameters.required_status_checks[].context]'
```

When this list is non-empty, prefer it over the heuristic discovered set: a SHA is "fully run" once every required
context has a `completed` check-run on it. Two caveats:

- `gh api branches/{branch}/protection` returns 404 if the branch is unprotected (`sase-org/sase`'s `master` is
  unprotected as of 2026-05-11; the rule-list call returns `[]`). Fall back to strategy A.
- The contexts in `required_status_checks` are **check-run names** (per-job/check), not workflow names. Mapping back
  to workflow runs requires walking `gh api /repos/{owner}/{repo}/commits/{sha}/check-runs` and joining on the
  `check_suite.id` → workflow run. Worth the complexity only if/when sase ace surfaces required-check state.

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
- `gh run list` ordering is *empirically* newest-first by `createdAt`, but this isn't contractually documented. The
  script should sort the JSON itself by `createdAt` desc rather than trust `gh`'s order.
- The `--branch` filter matches the run's `head_branch`. For `push` events this is the pushed branch; for
  `pull_request` events it's the PR's *source* branch (not the target). Filtering to `--event push` (or, on repos that
  use a merge queue, also `merge_group`) prevents incidentally-matching PR runs from a feature branch that happens to
  be named `master`/`main`. Schedule-triggered runs also have `head_branch = <default branch>` but `event = schedule`
  — usually noise for this question.

Useful additional flags worth knowing about:

- `gh run view <id> --exit-status` — exits non-zero if the run is unsuccessful. Convenient as a one-shot "did this
  run pass?" check inside the script's report loop, though we already have `conclusion` in JSON.
- `gh run view <id> --json jobs --jq '.jobs[].steps[] | select(.conclusion=="failure") | {job:.name, step:.name, number}'`
  — extracts the *first failing step* per job without any log download, which makes for a tight one-line summary
  ("CI failed at job=lint step=ruff (step 4)").
- `gh run list --status <value>` accepts both status (`in_progress`, `completed`, …) and conclusion (`failure`,
  `success`, …) tokens — handy for "show me the last 3 failed master runs" follow-ups but not needed for the primary
  algorithm (we want both passes and fails in the same fetch).
- `gh run list --created '>2026-05-01'` is an alternative to `--limit` for repos with very low or very high churn —
  bounds the window by time instead of count.

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

### Better failure summaries: the Annotations API

For many failure classes (lint, type-check, test reporters that emit `::error file=…,line=…`), GitHub already has a
clean, structured "what went wrong" string in the check-run annotations — far more useful than tailing 50 lines of
raw log. Each workflow run produces one check-suite containing one check-run per job. To fetch annotations:

```bash
# Find check-runs for the failing run's head SHA, then list annotations per check-run.
gh api "/repos/{owner}/{repo}/commits/{sha}/check-runs" \
  --jq '.check_runs[] | select(.conclusion=="failure") | .id' \
| while read -r id; do
    gh api "/repos/{owner}/{repo}/check-runs/$id/annotations" \
      --jq '.[] | {level:.annotation_level, path, line:.start_line, msg:.message}'
  done
```

Each annotation has `annotation_level` (`notice`/`warning`/`failure`), `path`, `start_line`/`end_line`, `title`, and
`message`. The list is capped at 50 per check-run (per the Checks API), which is roughly always enough for a summary.

Caveats:

- Many failures (e.g., a shell command exiting non-zero without emitting workflow commands) produce no annotations.
  The script should fall back to `--log-failed` when annotations are empty.
- Annotations for *previous* attempts of a re-run check are not always accessible via the REST API — there's an open
  community discussion about this limitation. For the "last set" question we always want the latest attempt anyway, so
  this rarely bites.
- GitHub Apps need `checks:read`; the user's `gh` auth (OAuth/PAT) needs `repo` scope for private repos. The default
  `gh auth login` flow grants this.

Recommended output strategy: when a workflow fails, print (a) the first failing step from `--json jobs`, (b) any
annotations from the Checks API (one line each: `LEVEL path:line — message`), and (c) the `--log-failed` tail only if
both prior sources came up empty. This gives a crisp summary for common failures and a real log tail for the rest.

## Recommended Algorithm (Pseudocode)

```text
branch        := flag --branch (default: detect main vs master via `gh repo view --json defaultBranchRef`)
fetch_window  := flag --limit  (default: 50 runs)
tail_lines    := flag --tail   (default: 50)
require_set   := flag --require (default: empty; comma-sep workflow names that MUST appear)

runs := gh run list --branch $branch --event push --limit $fetch_window \
          --json databaseId,workflowName,workflowDatabaseId,headSha,headBranch,status,conclusion,createdAt,updatedAt,event,attempt,displayTitle,url
# Note: --event push excludes pull_request and schedule runs that happen to share the branch name.
# Also fetch --event merge_group on repos that use the merge queue (sase-org/sase does not, as of 2026-05-11).
runs := sort(runs, key=createdAt, desc=True)  # don't trust gh's order

# Collapse multiple attempts of the same (workflowDatabaseId, headSha) to the newest attempt only.
runs := dedup_by(runs, key=(workflowDatabaseId, headSha), keep=max(attempt))

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

## Performance & Parallelism

For a passing set the script makes one API call (`gh run list`). For a failing set with K failed workflows, naive
serial fetching incurs roughly 2K extra calls (`--log-failed` + `--json jobs`) and downloads K log zips. On a slow
network this dominates wall time.

Mitigations:

- Use `concurrent.futures.ThreadPoolExecutor(max_workers=min(8, K))` to fan out per-failed-run fetches. `gh` is a
  subprocess so a thread pool is sufficient; the bottleneck is HTTP I/O, not CPU.
- Prefer the Checks API annotations path (one cheap JSON call per failed check-run) over `--log-failed` (zip
  download) for the *summary* output. Reserve the log tail for failures that produced no annotations.
- For the "did the set pass?" question alone (no log output requested), the script never needs to call `gh run view` —
  conclusion data is already in `gh run list --json`.
- Cache the default-branch lookup and the workflow list per script invocation (these never change mid-run).

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
- **Concurrency-cancelled runs are not real failures.** Workflows often declare
  `concurrency: { group: ..., cancel-in-progress: true }`. When a new push to master arrives before the previous
  push's workflows finish, the older runs end with `conclusion: cancelled` for reasons unrelated to code health.
  Heuristic: if a `cancelled` run's `updatedAt` is close to (within ~30s of) a newer run's `createdAt` on the same
  workflow, classify it as "superseded" rather than "failed". Cleaner alternative: only judge the *latest* SHA; older
  SHAs are not the question being asked.
- **Reruns and `attempt`.** Re-running a single failed job creates a new *attempt* on the same run id; re-running the
  whole workflow creates a new run id. `gh run list --json … attempt` captures the attempt number. Dedup
  `(workflowDatabaseId, headSha)` to the row with the highest `attempt` so the report reflects the *current* state.
  Use `gh run view <id> --attempt N` if a user wants to inspect a specific attempt.
- **Merge queue (`merge_group` event).** Repos that enable GitHub's merge queue run checks on synthetic
  `gh-readonly-queue/<target>/pr-<n>-<sha>` branches, not on `master` itself, with `event: merge_group`. Those runs
  will NOT appear in `gh run list --branch master --event push`. If/when sase adopts merge queue, add `merge_group`
  to the event filter and treat the synthetic branch's runs as the authoritative pre-merge signal.
- **PR runs leaking via `--branch`.** Per GitHub's API semantics, `branch` filters on `head_branch`. A PR whose source
  branch is named `master` would appear; filtering with `--event push` excludes it.
- **Disabled workflows.** `gh workflow list` hides disabled workflows by default; `gh workflow list --all` includes
  them. The discovered-set strategy is unaffected (disabled workflows produce no runs), but `--require <name>` should
  warn if a required name maps to a disabled workflow.
- **Empty repos / never-run workflows.** A brand-new repo or branch returns an empty `gh run list`. Exit with a
  distinct "no runs found" message and exit code, not a misleading "all passed".
- **Running inside CI.** `gh` honors `GH_TOKEN` and (with lower precedence) `GITHUB_TOKEN`. If invoked from a GitHub
  Actions job, set `env: GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}`; the default `GITHUB_TOKEN` has `actions:read` already.
- **Rate limits.** Authenticated REST is 5,000 req/hr per user — never the bottleneck for this script. `gh api` adds
  a `--cache <dur>` flag for response caching during development; useful while iterating on the script.

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

# Run metadata (sort in-script by createdAt; don't rely on gh's order)
gh run list \
  --branch "$BRANCH" \
  --event push \
  --limit "$LIMIT" \
  --json databaseId,workflowName,workflowDatabaseId,headSha,headBranch,status,conclusion,createdAt,updatedAt,event,attempt,displayTitle,url

# Optional: authoritative required-checks set (404 if branch is unprotected)
gh api "/repos/{owner}/{repo}/branches/$BRANCH/protection" \
  --jq '.required_status_checks.contexts' 2>/dev/null || echo '[]'

# Per failed run — pick the cheapest source that yields content:
gh run view "$RUN_ID" --json jobs              # per-job/per-step conclusions; identifies first failing step
gh api "/repos/{owner}/{repo}/commits/$SHA/check-runs"  # check-run ids for this commit
gh api "/repos/{owner}/{repo}/check-runs/$CHECK_RUN_ID/annotations"   # structured failure messages
gh run view "$RUN_ID" --log-failed             # fall back to log tail if annotations are empty
```

## Suggested Output Schema

Human-readable by default; emit JSON when `--json` (or `--format json`) is set so sase ace and other consumers can
parse without scraping. Proposed shape:

```json
{
  "branch": "master",
  "head_sha": "0c6a420d...",
  "display_title": "chore(research): add research...",
  "created_at": "2026-05-11T14:22:31Z",
  "ok": false,
  "runs": [
    {"workflow": "CI", "conclusion": "failure", "attempt": 1, "url": "https://github.com/.../runs/123",
     "first_failing": {"job": "lint", "step": "ruff", "step_number": 4},
     "annotations": [{"level": "failure", "path": "src/foo.py", "line": 42, "message": "F401 unused import"}],
     "log_tail": null},
    {"workflow": "Deploy Docs", "conclusion": "success", "attempt": 1, "url": "..."}
  ],
  "missing_required": []
}
```

Exit codes:

- `0` — set found and all passed.
- `1` — set found but at least one workflow did not pass.
- `2` — no fully-completed set in the fetch window (suggest raising `--limit`).
- `3` — `gh` auth or transport error (point user at `gh auth status`).

## Prior Art

A few existing tools cover adjacent problems; none of them quite answers "what was the last fully-completed set on
master?", which is why we're writing our own:

- **`gh run watch <id>`** — built into `gh`. Streams an *in-flight* run until completion. Different problem
  (you already know the run id; you want to wait), but useful for a follow-up "watch the current set" mode.
- **`gh pr checks`** — surfaces check state for one PR, including failure URLs. Not branch-oriented.
- **`act`** (nektos/act) — runs workflows locally. Unrelated.
- **GitHub status-badge endpoints** (`/actions/workflows/<id>/badge.svg`) — only encode the latest run per workflow,
  with no cross-workflow grouping by SHA and no failure details.
- **`hub ci-status`** (the legacy `hub` CLI) — checks one SHA's combined status. Discontinued in favor of `gh`.

The closest first-party primitive is `gh run list` + manual parsing, which is exactly what this script wraps.

## Testing Strategy

A few patterns work well for shell-out-heavy scripts like this; pick one and stick to it:

- **Fixture-based subprocess mocking.** Capture real `gh` JSON output once (passing set, failing set, partially-
  complete set, empty repo) into `tests/fixtures/gh/*.json`. In tests, monkeypatch the `_run_gh()` helper to return
  fixture content keyed on the argv. Fast, deterministic, no network.
- **Golden-file output assertions.** For human-readable output, snapshot the report into a `.txt` golden file and
  diff. Use sase's existing visual/snapshot infra if a textual snapshot harness exists, else `pytest`'s
  `syrupy`/`approvaltests` style.
- **Live smoke test (opt-in).** A `@pytest.mark.live` test that actually invokes `gh` against
  `sase-org/sase`. Skipped in CI unless `SASE_GH_LIVE=1` is set. Useful as a once-a-release sanity check that the
  `gh` JSON schema hasn't drifted.

Cases worth covering: passing set, single-failure set, multi-failure set, cancelled-by-concurrency set, rerun (higher
`attempt`) set, partial/in-progress set (must skip and find an older SHA), empty branch, log-retention-expired
(annotations empty AND log empty), and `--require` flag with missing/extra workflows.

## Out of Scope (Possible Follow-ups)

- Posting a summary to Slack/Telegram (would slot into sase's existing notification surfaces).
- Watching a SHA until it completes (`gh run watch`) — different feature; this script is a status snapshot.
- Diffing the failing step's log against the previous successful run on the same workflow to surface the new failure
  signature.
- Caching the last reported SHA so the script can be used as a cron-style notifier ("notify me when a new master SHA
  finishes its workflow set").

## References

- `gh run list --help`, `gh run view --help` (local; `gh` 2.92.0).
- GitHub REST: `actions/runs`, `actions/runs/{id}/jobs`, `actions/jobs/{id}/logs`
  (https://docs.github.com/rest/actions/workflow-runs, /actions/workflow-jobs).
- GitHub Actions status & conclusion enums (https://docs.github.com/rest/checks/runs#create-a-check-run — same enums
  apply to workflow runs).
- Checks API annotations (https://docs.github.com/rest/checks/runs#list-check-run-annotations).
- Branch protection `required_status_checks`
  (https://docs.github.com/rest/branches/branch-protection#get-branch-protection) and rulesets
  (https://docs.github.com/rest/repos/rules).
- Merge queue / `merge_group` event
  (https://docs.github.com/actions/using-workflows/events-that-trigger-workflows#merge_group).
- Concurrency cancellation
  (https://docs.github.com/actions/using-jobs/using-concurrency).
- Community discussion on annotations for previous run attempts
  (https://github.com/orgs/community/discussions/103026).
