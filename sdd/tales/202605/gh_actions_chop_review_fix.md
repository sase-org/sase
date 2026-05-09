---
create_time: 2026-05-09 13:49:50
status: done
prompt: sdd/prompts/202605/gh_actions_chop_review_fix.md
---
# Review Fix: GitHub Actions Failure Chop Duplicate `%tag` Bug

## Goal

Fix a critical bug introduced by the recently-implemented GitHub Actions failure chop in the chezmoi repo (commit
`8609b318` in `/home/bryan/.local/share/chezmoi`, planned in `sdd/tales/202605/gh_actions_failure_chop.md`). Both the
planner and coder produced a prompt template that the real `sase run -d` parser rejects, so every cron-triggered launch
would fail before an agent ever starts.

## Background — what's broken

The chop builds the agent prompt with two `%tag` directives:

```python
# home/bin/executable_sase_chop_gh_actions_fix:234
f"#gh:{repo} %t:chop %t:gact %n:{agent_name}",
```

The `%tag` directive is **single-value** in this codebase (`_MULTI_VALUE_DIRECTIVES` in
`src/sase/xprompt/_directive_types.py` only contains `wait`). `extract_prompt_directives` raises
`DirectiveError: Duplicate directive '%tag' in prompt` for any second `%tag`/`%t` occurrence.

I confirmed this empirically against the live `sase` directive parser:

```text
$ .venv/bin/python -c "from sase.xprompt.directives import extract_prompt_directives; \
    extract_prompt_directives('#gh:owner/repo %t:chop %t:gact %n:gha-fix-x\n\nbody')"
ERR DirectiveError Duplicate directive '%tag' in prompt
```

A comma-separated single tag (`%t:chop,gact`) is also rejected — `validate_tag_name` requires `^[A-Za-z0-9_.-]+$`, so
the script must pick exactly one tag value.

The bashunit test in `tests/bash/gh_actions_fix_chop_test.sh:122` asserts the launched prompt contains
`%t:chop %t:gact`, so the tests pass even though the real launcher would reject the prompt. The fake `sase` shim never
invokes the directive parser, hiding the defect.

**Net effect**: the chop appears healthy in unit tests and dry runs, but every production launch from the
`github_actions` lumberjack would fail and no fixer agent would ever start.

## Design

### Decision: use `%t:gact` (single tag)

Pick `%t:gact` over `%t:chop`. Reasoning:

- `gact` is specific to GitHub Actions failures — exactly the discoverability axis a future me will use to filter the
  Agents tab.
- The user's `home/dot_config/sase/sase.yml` already defines `gact: "GitHub Actions"` as a snippet, so the tag matches
  existing project vocabulary.
- `%t:chop` is generic across many chop-launched agents in `sase_athena.yml` and would not help locate these specific
  failures.

### Files to change

1. `/home/bryan/.local/share/chezmoi/home/bin/executable_sase_chop_gh_actions_fix` — `build_prompt`, line 234. Replace
   the directive line:

   ```python
   # before
   f"#gh:{repo} %t:chop %t:gact %n:{agent_name}",
   # after
   f"#gh:{repo} %t:gact %n:{agent_name}",
   ```

2. `/home/bryan/.local/share/chezmoi/tests/bash/gh_actions_fix_chop_test.sh` — line 122 assertion. Update the substring
   asserted in `test_failure_launches_agent_with_failed_logs`:

   ```bash
   # before
   assert_contains "#gh:owner/repo %t:chop %t:gact %n:gha-fix-owner-repo-12345-a1" "$(cat "${PROMPTS_FILE}")"
   # after
   assert_contains "#gh:owner/repo %t:gact %n:gha-fix-owner-repo-12345-a1" "$(cat "${PROMPTS_FILE}")"
   ```

No other test cases reference the `%t:chop` substring; the `test_new_attempt_launches_again` assertion only checks `%n:`
and the failure log content.

### Files explicitly NOT touched

- `home/dot_config/sase/sase_athena.yml` — env wiring (`SASE_GHA_FIX_REPOS: "bbugyi200/dotfiles"`), `interval: 300`,
  `chop_timeout: "120s"`, and `run_every: 15m` are all fine and unrelated to the bug.
- `sdd/tales/202605/gh_actions_failure_chop.md` (in `sase_100`) — already marked `done`. This is a follow-up review fix,
  not a re-plan. Leaving the historical tale intact preserves an honest record of what the original plan said.

## Out of scope (deliberately deferred)

These are observations from the same review pass that I'm intentionally not folding into this fix:

- Dedupe state file grows unbounded (one entry per failed run/attempt forever). LRU pruning is worth doing if the file
  ever gets large in practice; not now.
- `gh`/`sase` not on PATH would surface as `FileNotFoundError` rather than a clean log line. The chop only runs in
  chezmoi-managed environments where both are guaranteed installed.
- `gh run list -L 1` masks an older failure if a newer in-progress run has started. The original plan explicitly chose
  this behavior ("no-op when the latest run is not completed").
- Stored `databaseId`/`attempt` fields in the seen-state value duplicate the seen-key. Cosmetic.

If any of these turn into real problems later, they're each small follow-up tasks.

## Validation

In the chezmoi worktree (`/home/bryan/.local/share/chezmoi`):

1. **Targeted bash tests** — re-runs the chop test under the fake `gh`/`sase` shims:

   ```bash
   just test-bash
   ```

2. **Repo gate** — required after any chezmoi-managed file change:

   ```bash
   just check
   ```

3. **Live directive-parse spot-check** — prove the bug is actually gone, not just that the test was updated. From the
   `sase_100` checkout:

   ```bash
   .venv/bin/python -c "from sase.xprompt.directives import extract_prompt_directives; \
     cleaned, d = extract_prompt_directives('#gh:owner/repo %t:gact %n:gha-fix-owner-repo-12345-a1\n\nbody'); \
     print(d.tag, d.name)"
   ```

   Expected output: `gact gha-fix-owner-repo-12345-a1`.

## Apply & commit

After validation passes:

1. `chezmoi apply --force` on the chop binary so the live `~/bin/sase_chop_gh_actions_fix` matches the fixed source. The
   YAML is unchanged so it doesn't need re-applying.
2. Commit the two changed files via `sase commit` only if the user explicitly asks. The Neovim `_snip_utils.lua`
   worktree change pre-existed and remains untouched.
