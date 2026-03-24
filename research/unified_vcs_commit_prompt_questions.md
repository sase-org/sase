## Prompt Review: Gaps, Ambiguities, and Design Decisions Needed

### 1. `sase_commit_stop_hook` already exists — but it's a quality-check hook, not a commit-orchestrator

The current `tools/sase_commit_stop_hook` runs lint/test/format and then tells the agent "you have uncommitted changes,
run `/commit`." Your prompt says it "will need a substantial re-write" to become the thing that dispatches commit
creation. That's a significant role change — from **quality gate** to **commit orchestrator**.

**Decision needed:** Does the rewritten hook keep the quality-check responsibilities (lint, test, fmt) _and_ add commit
orchestration? Or does commit orchestration live elsewhere (e.g., a new hook or a post-step in the workflow)?

### 2. `$SASE_VCS_TYPE` doesn't exist — `$SASE_VCS_PROVIDER` does

The codebase has `SASE_VCS_PROVIDER` (resolves to `"github"`, `"bare_git"`, `"hg"`, etc.). Your prompt introduces
`$SASE_VCS_TYPE` without defining it.

**Decision needed:** Is `$SASE_VCS_TYPE` the same as `$SASE_VCS_PROVIDER`? If not, what's the distinction? (e.g.,
`VCS_PROVIDER=github` vs `VCS_TYPE=git`?)

### 3. The `environment` field is new — scope and lifecycle are undefined

You mention a new `environment` field on xprompts that sets `$SASE_COMMIT_METHOD`. But:

**Decisions needed:**

- Is this a **workflow-level** field or a **step-level** field?
- When are the vars injected — for the entire agent session, or only visible to the stop hook / `sase commit`?
- Can it reference other workflow variables (e.g., Jinja2 templated), or is it static key-value pairs?

### 4. The three built-in xprompts have different `prompt_part` needs per VCS

Currently:

- Google `#commit` and `#propose` inject `#no_cl_ops #cldd` (where `#cldd` provides CL-specific diff/description
  context)
- Google `#cl` injects just `#no_cl_ops`
- GitHub `#pr` injects an empty `prompt_part: ""`

If the built-in xprompts "use the same prompt_part as the Google workflows," that's Google-specific content (`#cldd`
references `cl_changes.diff`, `cl_desc`).

**Decision needed:** What's the VCS-agnostic prompt_part? Is it just the "don't create the commit yourself" instruction?
Does each VCS plugin get to augment it (e.g., Google adds `#cldd` context)?

### 5. The current workflows do _much more_ than prompt + commit — where does that logic go?

The current Google `#cl` workflow: creates branches, checks for name conflicts, generates CL descriptions, runs
`hg addremove`, `hg commit`, `hg fix`, `hg upload`, creates ChangeSpecs, adds hooks.

The current GitHub `#pr` workflow: creates/checks-out branches, pushes to remote, creates ChangeSpecs, runs
`gh pr create`, updates ChangeSpec with PR URL.

Your prompt says the built-in xprompts will NOT do any of this — they just set `$SASE_COMMIT_METHOD` and let
`sase commit` handle it.

**Decisions needed:**

- Does `sase commit` now handle _all_ of this? (Branch creation, ChangeSpec management, VCS-specific upload/fix, PR
  creation, etc.)
- Or do plugins register hooks for each `$SASE_COMMIT_METHOD` value? If so, what's the hook interface? A new pluggy
  hookspec like `vcs_create_pull_request(cwd, ...)` / `vcs_create_proposal(cwd, ...)`?
- How does `sase commit` get the inputs it needs (CL name, bug ID, PR title)? Currently the xprompt workflows collect
  these as `input` fields. If the built-in xprompts are just prompt_parts, who collects the inputs?

### 6. `create_commit` vs `create_proposal` vs `create_pull_request` — semantic mapping is unclear

Currently: | Google concept | GitHub concept | `$SASE_COMMIT_METHOD` | |---|---|---| | `#commit` (amend existing CL) |
??? (no equivalent) | `create_commit` | | `#propose` (proposed entry, reverted) | ??? | `create_proposal` | | `#cl` (new
CL) | `#pr` (new PR) | `create_pull_request` |

**Decisions needed:**

- Is `create_commit` = "amend/add to existing change"? That's what Google's `#commit` does, but `create_commit` sounds
  like creating a _new_ commit.
- What does `create_pull_request` mean for Google? Is `#cl` really "create pull request"? CL creation ≠ PR creation
  semantically.
- Does `create_proposal` have any meaning outside Google? If not, what does a GitHub plugin do when
  `SASE_COMMIT_METHOD=create_proposal`?
- What about bare git repos (no GitHub, no Google)? What do these three methods mean there?

### 7. Removing `sase amend` — what replaces its functionality?

`sase amend` currently supports two modes:

- **Regular amend**: Amend the current CL/branch with a new COMMITS entry
- **`--propose`**: Create a proposed entry, then clean workspace
- **`--accept`**: Accept proposed entries by applying their diffs

**Decision needed:** If `sase amend` is removed, does `sase commit` absorb all three modes? What about `--accept`?
That's a distinct user-facing operation (accepting proposals), not just "committing."

### 8. The hook-instructs-agent flow is underspecified

You say the hook will "instruct the agent to commit the changes using the `sase commit` command." Currently the hook
does this by returning exit code 2 with a message on stderr (Claude Code convention).

**Decisions needed:**

- Does the hook literally tell the agent "run `sase commit`"? Or does it run `sase commit` directly?
- If the hook tells the agent, the agent still needs to know _what arguments_ to pass to `sase commit`. How does the
  agent know the CL name, whether it's a new CL or an amend, etc.?
- The current hook blocks the agent until changes are committed. Is that still the intended flow?

### 9. The `#gcommit` workflow in sase core — what happens to it?

There's already a built-in `src/sase/xprompts/gcommit.yml` that calls `sase_commit_workflow` (a git-specific commit
script). Your prompt doesn't mention it.

**Decision needed:** Does `#gcommit` get replaced by the new `#commit`? Or is it separate?

### 10. Plugin registration for commit methods

You emphasize this must be VCS-agnostic. Currently, `sase commit` calls VCS hooks like `vcs_commit()`, `vcs_amend()`
directly.

**Decision needed:** How do plugins declare which `$SASE_COMMIT_METHOD` values they support? Options:

- New hookspecs (e.g., `vcs_create_pull_request`, `vcs_create_proposal`)
- A single dispatch hook: `vcs_handle_commit_method(method, ...)`
- Entry-point based discovery of method handlers

This is probably the most architecturally significant decision — it determines the plugin contract.
