---
create_time: 2026-05-09 13:29:42
status: wip
prompt: sdd/prompts/202605/gh_actions_failure_chop.md
---
# GitHub Actions Failure Fix Chop Plan

## Goal

Add a SASE lumberjack chop, stored in the chezmoi repo, that periodically checks the latest GitHub Actions run for one
or more configured GitHub repositories. If the latest completed run failed, the chop should collect the failed action
output and launch a SASE agent with that failure context embedded in the prompt.

## Existing System Context

- Chezmoi maps executable files under `home/bin/executable_*` onto the real home `PATH` without the `executable_`
  prefix.
- SASE external chop scripts are discovered as `sase_chop_<name>` on `PATH`, so a file named
  `home/bin/executable_sase_chop_gh_actions_fix` can be referenced from config as the chop named `gh_actions_fix`.
- `sase axe` passes script chops a `--context <json>` file. That context includes a durable per-lumberjack `state_dir`,
  which is the right place to store dedupe state.
- Current personal SASE lumberjack config lives in `home/dot_config/sase/sase_athena.yml`. Work-specific Google config
  is in `sase_work.yml`; this GitHub Actions automation belongs in the personal/athena config unless we later decide to
  make it part of the base config.
- Agent chops in YAML are static. This task needs dynamic `gh` output in the agent prompt, so a script chop is the right
  extension point.

## Design

1. Add a new executable script:

   `home/bin/executable_sase_chop_gh_actions_fix`

   Implement it as a small Python CLI with only standard-library dependencies. It should:
   - Accept `--context <path>` for SASE chop compatibility.
   - Read the context JSON to find `state_dir`.
   - Read target repositories from an env var such as `SASE_GHA_FIX_REPOS`, supporting comma or whitespace separators.
   - For each repo, run `gh run list -R <repo> -L 1 --json databaseId,attempt,status,conclusion,...`.
   - No-op when there is no run, the latest run is not completed, or the conclusion is not an actionable failure.
   - Treat at least `failure`, `timed_out`, `startup_failure`, and `action_required` as actionable. Ignore `success`,
     `cancelled`, `skipped`, and `neutral` by default.
   - Collect failure output with `gh run view -R <repo> <run-id> --attempt <attempt> --log-failed`.
   - Fall back to `gh run view -R <repo> <run-id> --attempt <attempt> --verbose` if failed-step logs cannot be fetched.
   - Launch a detached agent with `sase run -d <prompt>` using `subprocess.run([...])`, not shell interpolation.
   - Print concise lumberjack log lines for no-op, skipped duplicate, failed `gh`, and launched-agent cases.

2. Add durable dedupe in the script.

   Store a JSON file in the chop context state dir, for example:

   `state_dir / "gh_actions_fix_seen.json"`

   Key records by repo and by run identity: `databaseId` plus `attempt`. If the latest failed run has already launched
   an agent, skip it on later ticks. A new run id or new attempt should launch again, because it represents new CI
   evidence.

3. Build an explicit, high-signal agent prompt.

   The launched prompt should include:
   - A VCS launch ref: `#gh:<owner>/<repo>`.
   - Tags/name for discoverability, likely `%t:chop %t:gact` and a stable `%n:gha-fix-<repo-slug>-<run-id>-a<attempt>`.
   - Run metadata: workflow name, title, branch, SHA, event, conclusion, run URL, attempt.
   - The exact failed-step output discovered by the chop in a fenced block.
   - Instructions to diagnose the root cause, fix the repo, run relevant checks, and avoid committing unless explicitly
     requested.

   The prompt should preserve the failed log text as discovered. To avoid oversized CLI args, cap logs to a generous
   limit such as the last 40-60 KiB and say in the prompt when truncation happened.

4. Wire the chop into SASE config.

   In `home/dot_config/sase/sase_athena.yml`, add a new lumberjack or a new entry under an appropriate existing
   lumberjack. Prefer a dedicated lumberjack so GitHub Actions polling is easy to inspect independently:

   ```yaml
   axe:
     lumberjacks:
       github_actions:
         interval: 300
         chop_timeout: "120s"
         chops:
           - name: gh_actions_fix
             description: "Launch a fixer agent when the latest GitHub Actions run fails"
             run_every: "15m"
             timeout: "120s"
             env:
               SASE_GHA_FIX_REPOS: "bbugyi200/dotfiles"
   ```

   If we want this to watch SASE repos too, make `SASE_GHA_FIX_REPOS` a whitespace-separated list, for example
   `bbugyi200/dotfiles sase-org/sase sase-org/sase-core`.

5. Add focused tests where practical.

   The chezmoi repo already has `tests/bash` and runs them with `bashunit`. Add a bashunit test file that invokes the
   Python script with fake `gh` and fake `sase` executables earlier on `PATH`.

   Cover:
   - Success/no-op: latest run conclusion is `success`, so no agent is launched.
   - Failure launch: latest run conclusion is `failure`, failed logs are included in the `sase run -d` prompt.
   - Dedupe: running the script twice with the same repo/run/attempt launches only once.
   - New attempt: same run id with a higher attempt launches again.
   - `gh run view --log-failed` failure fallback includes verbose run output.

6. Validate.

   Run targeted script tests first:

   ```bash
   just test-bash
   ```

   Then run the required chezmoi repo check:

   ```bash
   just check
   ```

   Because this modifies chezmoi-managed files, after the implementation is complete and before considering it installed
   locally, run:

   ```bash
   chezmoi apply --force
   ```

## Open Decisions

- Default repo list: start with `bbugyi200/dotfiles` because the chop itself lives in the dotfiles/chezmoi repo, unless
  you want the first version to monitor SASE repos instead.
- Prompt naming: use one deterministic `%n:` per failed run/attempt so repeated failures are easy to find in the Agents
  tab.
- Failure scope: ignore `cancelled` initially. It is often user-triggered noise, while `failure`, `timed_out`,
  `startup_failure`, and `action_required` are more likely to need an agent.
