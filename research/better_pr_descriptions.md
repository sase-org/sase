# Research: Better PR / CL Descriptions via the `#pr` Xprompt Workflow

## Problem Statement

When using the `#pr` xprompt workflow, the PR description is derived entirely from the commit message the agent
composes. This produces low-quality descriptions because:

1. **The commit message IS the PR body** — GitHub's `gh pr create --title <first-line> --body <full-message>` uses the
   raw commit message verbatim. Commit messages are written for git log, not for PR reviewers.
2. **No structured context is gathered** — the workflow never examines the diff, commit history, changespec description,
   plan file, or bead context before creating the PR.
3. **The fallback path is minimal** — when the stop hook handles commit creation, the message is just
   `"[<who>] Agent changes"` (line 55 of `pr.yml`).
4. **No separation of concerns** — title and body are a single `message` string, split on `\n` by the GitHub plugin.

## Current Flow (How It Works Today)

```
Agent makes changes
    ↓
#pr xprompt invoked with (name, bug_id)
    ↓
Stop hook detects uncommitted changes → blocks agent
    ↓
Agent invokes /sase_git_commit skill
    ↓
Agent writes commit message (tag: short description)
    ↓
sase commit dispatches to CommitWorkflow.run()
    ↓
CommitWorkflow → GitHubPlugin.vcs_create_pull_request()
    ├─ git checkout -b <name>
    ├─ git add / git commit -m <message>
    ├─ git push -u origin <name>
    └─ gh pr create --title <first-line> --body <message>
    ↓
PR is created with commit message as description
```

### Key Files

| File                                                      | Role                                                      |
| --------------------------------------------------------- | --------------------------------------------------------- |
| `src/sase/xprompts/pr.yml`                                | The `#pr` xprompt workflow                                |
| `src/sase/workflows/commit/workflow.py`                   | `CommitWorkflow` orchestrator                             |
| `../sase-github/src/sase_github/plugin.py`                | `GitHubPlugin.vcs_create_pull_request()`                  |
| `src/sase/vcs_provider/plugins/_git_common.py`            | Base git ops (branch, add, commit, push)                  |
| `src/sase/scripts/sase_commit_stop_hook.py`               | Stop hook that forces agent to commit                     |
| `~/.claude/skills/sase_git_commit/SKILL.md`               | Skill prompt that guides how agent writes commit messages |
| `../sase-github/src/sase_github/xprompts/new_pr_desc.yml` | Separate after-the-fact PR desc regeneration workflow     |

## Existing Prior Art: `#new_pr_desc`

The sase-github plugin already has a `#new_pr_desc` workflow (`../sase-github/src/sase_github/xprompts/new_pr_desc.yml`)
that regenerates PR descriptions _after_ creation. It demonstrates the right approach:

1. **get_context** (python step): Gathers changespec description, git diff (first 5000 chars), and commit subjects
2. **generate** (agent step): Asks an LLM to produce a `TITLE:` / `BODY:` with conventional commit format and a
   `## Summary` section
3. **apply** (bash step): Updates the existing PR via `gh pr edit --title ... --body ...`

This works but has a critical limitation: it's a separate workflow you have to remember to run after `#pr` completes.
The description should be generated as part of the `#pr` flow itself.

## Analysis of Available Context for Better Descriptions

At PR creation time, the following context is available (or can be made available):

| Context Source                     | Currently Used?                       | Quality Signal                      |
| ---------------------------------- | ------------------------------------- | ----------------------------------- |
| Commit message                     | Yes (it IS the description)           | Low — terse, git-log oriented       |
| Git diff                           | No                                    | High — shows exactly what changed   |
| ChangeSpec description             | No                                    | High — human-written intent         |
| Plan file (`SASE_PLAN`)            | No (appended to message as path only) | High — detailed implementation plan |
| Bead description                   | No                                    | Medium — task-level context         |
| Agent chat/response history        | No                                    | Medium — shows reasoning            |
| Commit subjects (multi-commit PRs) | No                                    | Medium — chronological narrative    |

## Recommended Solution: Post-Create Description Update Step

### Why Post-Create (not Pre-Create)

The cleanest approach is to **update the PR description after creation** rather than trying to compose it before. Here's
why:

1. **Minimal disruption** — the existing commit flow (`CommitWorkflow` → VCS provider → `gh pr create`) stays unchanged.
   No need to thread a description through the payload or modify the plugin interface.
2. **Full context available** — after the PR exists, we have the PR URL, the diff against the default branch, the
   changespec name, and all commit metadata.
3. **Proven pattern** — `#new_pr_desc` already does this successfully; we just need to inline the pattern into `#pr`.
4. **Idempotent** — `gh pr edit` is safe to call multiple times. If the step fails, the PR still exists with the
   original commit message as a fallback.

### Proposed Changes

#### 1. Add a `describe` step to `pr.yml` (after `create`, before `report`)

```yaml
- name: describe
  hidden: true
  if: "{{ create.success }}"
  python: |
    import os, subprocess, tempfile, json

    # Read commit result for metadata
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR", "")
    result_file = os.path.join(artifacts_dir, "commit_result.json") if artifacts_dir else ""
    if not (result_file and os.path.isfile(result_file)):
        print("error=no commit_result.json")
        raise SystemExit(0)

    with open(result_file) as f:
        cr = json.load(f)

    branch_name = cr.get("name", "")
    commit_message = cr.get("message", "")
    pr_url = cr.get("result", "")

    # Get diff against default branch
    default_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "origin/HEAD"],
        capture_output=True, text=True, check=False
    ).stdout.strip().split("/")[-1] or "master"

    diff_result = subprocess.run(
        ["git", "diff", f"origin/{default_branch}...{branch_name}"],
        capture_output=True, text=True, check=False
    )
    diff = diff_result.stdout[:8000] if diff_result.returncode == 0 else ""

    # Get commit subjects
    log_result = subprocess.run(
        ["git", "log", "--format=%s", f"origin/{default_branch}..{branch_name}"],
        capture_output=True, text=True, check=False
    )
    commits = log_result.stdout.strip() if log_result.returncode == 0 else ""

    # Get plan content if available
    plan_path = os.environ.get("SASE_PLAN", "")
    plan_content = ""
    if plan_path and os.path.isfile(plan_path):
        with open(plan_path) as f:
            plan_content = f.read()[:3000]

    # Get changespec description if available
    cs_desc = ""
    cs_name = cr.get("changespec_name", "")
    if cs_name:
        try:
            from sase.ace.changespec import find_all_changespecs
            for cs in find_all_changespecs():
                if cs.name == cs_name:
                    cs_desc = cs.description or ""
                    break
        except Exception:
            pass

    # Write diff to temp file for the agent
    diff_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".diff", prefix="pr_desc_", delete=False
    )
    diff_file.write(diff)
    diff_file.close()

    print("error=")
    print(f"branch_name={branch_name}")
    print(f"commit_message={commit_message}")
    print(f"pr_url={pr_url}")
    print(f"diff_file={diff_file.name}")
    print(f"commits={commits}")
    print(f"plan_content={plan_content}")
    print(f"cs_desc={cs_desc}")
  output:
    error: line
    branch_name: word
    commit_message: text
    pr_url: line
    diff_file: path
    commits: text
    plan_content: text
    cs_desc: text

- name: generate_description
  if: "{{ create.success and not describe.error }}"
  agent: |
    Generate a PR title and body for the following changes.

    ## Commit Message
    {{ describe.commit_message }}

    ## ChangeSpec Description
    {{ describe.cs_desc }}

    ## Plan Context
    {{ describe.plan_content }}

    ## Commits
    {{ describe.commits }}

    ## Diff
    @{{ describe.diff_file }}

    ## Instructions
    - PR title: Use conventional commit format (e.g., "feat: ...", "fix: ..."), under 72 characters
    - PR body: Write for a human reviewer. Include:
      - `## Summary` — 1-3 bullet points explaining what changed and WHY
      - `## Changes` — brief list of notable implementation details (only if non-obvious)
      - `## Testing` — how to verify the changes (if applicable)
    - Be concise. Don't repeat the diff line-by-line. Focus on intent and impact.

    Output EXACTLY in this format (no extra text):
    TITLE: <your title here>
    BODY:
    <your body here>

- name: apply_description
  hidden: true
  if: "{{ create.success and not describe.error }}"
  bash: |
    RESPONSE="{{ _response }}"
    TITLE=$(echo "$RESPONSE" | grep -m1 '^TITLE: ' | sed 's/^TITLE: //')
    BODY=$(echo "$RESPONSE" | sed -n '/^BODY:$/,$ p' | tail -n +2)

    if [ -n "$TITLE" ] && [ -n "$BODY" ]; then
      gh pr edit "{{ describe.branch_name }}" --title "$TITLE" --body "$BODY" 2>/dev/null \
        && echo "applied=true" || echo "applied=false"
    else
      echo "applied=false"
    fi
  output: { applied: bool }
```

#### 2. Enhance the skill prompt to produce richer commit messages

Even with the post-create description update, improving the commit message helps because it becomes the "seed" context
for the description generation. Update `~/.claude/skills/sase_git_commit/SKILL.md` to encourage multi-line messages for
`create_pull_request` method:

```
## Extra Requirements for PRs

When `$SASE_COMMIT_METHOD` is `create_pull_request`, write a richer commit message:
- First line: conventional commit tag + concise summary (under 72 chars)
- Blank line
- Body: 2-5 sentences explaining the motivation and approach
```

### Alternative Approaches Considered

#### A. Pre-create description generation (agent step before CommitWorkflow)

- Would require the agent to generate a description in a dedicated step, then pass it through the payload
- Problem: at that point the diff isn't finalized (precommit commands like `just fix` may modify files)
- Problem: requires changes to `CommitWorkflow` payload handling and the VCS plugin interface to separate title/body
- More invasive, less robust

#### B. Modify `CommitWorkflow` / `GitHubPlugin` to accept separate title and body

- Add `pr_title` and `pr_body` fields to the payload
- Modify `GitHubPlugin.vcs_create_pull_request()` to use them
- Problem: breaks the VCS abstraction (Google/Hg CLs don't have title/body separation the same way)
- Problem: still doesn't solve where the rich content comes from

#### C. Just improve the commit message prompt (no new steps)

- Enhance `sase_git_commit` skill to produce better messages when `SASE_COMMIT_METHOD=create_pull_request`
- Simplest change but limited: the agent doesn't have structured access to plan files, changespec descriptions, etc.
  during commit message composition
- Could be done as a complement to the recommended approach

#### D. Auto-run `#new_pr_desc` after `#pr` (workflow chaining)

- Add a final step to `pr.yml` that invokes `#new_pr_desc` with the created changespec name
- Problem: `#new_pr_desc` uses an `agent` step which spawns a full LLM call — this is expensive and adds latency
- The recommended approach also uses an agent step but is tighter (inlined context, no changespec lookup needed)

### Recommendation Summary

**Do both:**

1. **Primary**: Add `describe` → `generate_description` → `apply_description` steps to `pr.yml` (the post-create
   approach above). This gives rich, contextual PR descriptions for every PR created via `#pr`.

2. **Complementary**: Enhance the commit skill prompt to produce richer messages for PRs. This improves the seed context
   and provides a reasonable fallback if the description generation step fails.

3. **Optional cleanup**: Consider deprecating or removing `#new_pr_desc` once the inline approach is working, since it
   would be redundant. Or keep it for updating descriptions on PRs not created via `#pr`.

### Cost/Complexity Assessment

- **pr.yml changes**: ~60 lines of new YAML (3 new steps). No changes to Python modules.
- **Skill prompt change**: ~5 lines of markdown.
- **No changes needed to**: `CommitWorkflow`, `GitHubPlugin`, `GitCommon`, VCS hookspec, or any core modules.
- **Risk**: Low. The new steps only run after PR creation succeeds. If they fail, the PR still exists with the original
  commit message. The `gh pr edit` call is idempotent.
