---
plan: sdd/epics/202603/unified_vcs_commit.md
---
I'm thinking about getting rid of all commit/propose/cl (for example, see the `#commit` / `#propose` / `#cl` workflows
in the ../retired Mercurial plugin repo or the `#pr` workflow in the ../sase-github repo--which corresponds with the `#cl` workflow,
but for GitHub) in favor of using 3 built-in xprompts (`#commit`, `#propose`, and `#pr`---`#pr` will be used instead of
`#cl`).

- The goal of this change: To unify / standardize the way I commit changes, create new proposals, and create new CLs/PRs
  across all VCS providers.
- These built-in xprompt will have the same `prompt_part` used by the ../retired Mercurial plugin workflows currently, but will NOT
  actually create the commit/proposal/PR.
- Instead, they will set a `$SASE_COMMIT_METHOD` environment variable (supported via a new `environment` field), which
  will be set to either "create_commit", "create_proposal", or "create_pull_request".
- The `sase_commit_stop_hook` hook, which will need a substantial re-write, will then the new `$SASE_VCS_TYPE`
  environment variable (which tells us which VCS workflow was used) to check for file changes, instruct the agent to
  commit the changes using the `sase commit` command.
- The `sase commit` command will need a substantial re-write. It will use the `$SASE_VCS_TYPE` and `$SASE_COMMIT_METHOD`
  environment variables to figure out (This MUST be done in a VCS-agnostic way! Remember that we need to support
  arbitrary new VCS providers in the future without making any code changes to sase's core!) which actions to take.
- This work obsoletes the `sase amend` command, which should be removed.

### Design Decisions / Q&A

I asked another agent to critique this prompt and flesh out the design decisions that I need to make. My answers are
below. The numbers correspond to the section numbers in the sdd/research/202603/unified_vcs_commit_prompt_questions.md file, which
contains the agent's reply:

1. We should move the quality checks to a new `sase_core_stop_hook` stop hook that is configured ONLY for this repo (I
   think you might need a workaround for this for Codex. We've been using the Codex settings.json configuration in the
   chezmoi repo for this I believe.).
2. Let's just use the existing `$SASE_VCS_PROVIDER` for this (I didn't realize we had this).
3. workflow-level; the entire agent session; should support jinja2 so we can use the xprompt's inputs
4. See the "4. NEW VCS-specific xprompt Tags" section below.
5. `sase commit` should handle all of this in a VCS-agnostic way using plugin hooks. How does `sase commit` get the
   inputs that it needs?: `sase commit` will receive most of its arguments via the JSON payload (see the "`sase commit`
   Command Arguments" section below), which will be constructed by the agent. The `sase_commit_stop_hook` will instruct
   the agent what JSON schema to use in its message to the agent. The bug ID should be provided via a new `$SASE_BUG_ID`
   environment variable (set via the new xprompt `environment` field using the `#cl`'s xprompt `bug_id` input).
6. For the `#git` VCS workflow, the `#pr` xprompt should result in us creating a new branch and ChangeSpec and doing
   everything else we can that the other VCS workflows do (one thing we can't do: Create a "PR" or "CL"). The `#commit`
   and `#propose` workflows should both both result in commits being created (with good commit messages) and pushed to
   the current branch.
7. We can remove the `sase amend --accept` functionality without replacing it (I only ever use the TUI to accept
   proposals anyway).
8. We should tell the agent to use its `/sase_<vcs>_commit` skill. You will need to create these new skills for each LLM
   provider (define them all in the chezmoi repo). The current `/commit` skill will be obsoleted by the new
   `/sase_git_commit` skill (the `#git` and `#gh` should be able to share this skill I think---look into how to make
   this work). We should block the agent, but ONLY ONCE (see how the `sase_commit_stop_hook` currently handles this).
9. `#gcommit` gets replaced by the new `#commit`.
10. New hookspecs.

#### 4. NEW VCS-specific xprompt Tags

- Let's add support for the following new VCS-specific (i.e. we will only use an xprompt with this tag if it is defined
  in the same plugin repo as the VCS workflow embedded in the prompt---see how we handle this for the "diff_file"
  xprompt tag) xprompt tags: "append_to_pr", "append_to_commit_and_propose".
- If an xprompt tagged with "append_to_pr" exists for the given VCS (determined by an embedded VCS xprompt workflow),
  then we will append that xprompt to the `#pr` xprompt contents (in the same location we put `#no_cl_ops` and `#cldd`
  in before).
- If an xprompt tagged with "append_to_commit_and_propose" exists for the given VCS (determined by an embedded VCS
  xprompt workflow), then we will append that xprompt to the `#commit` and `#propose` xprompt contents (in the same
  location we put `#no_cl_ops` and `#cldd` in before).
- We should tag the `#no_cl_ops` xprompt in the ../retired Mercurial plugin repo with "append_to_pr". We should also define a new
  `#no_cl_ops_and_cldd` xprompt in this repo that is tagged with "append_to_commit_and_propose" has the following
  contents:
  ```
  #no_cl_ops #cldd
  ```
- We should define a new `#prdd` xprompt in the ../sase-github repo that is tagged with "append_to_commit_and_propose"
  (this xprompt should work like `#cldd`, but using `gh` to fetch the PR description and `git` to create the appropriate
  diff file). I don't think this repo needs an xprompt tagged with "append_to_pr".

#### `sase commit` Command Arguments

- `sase commit` will accept a JSON payload as an argument.
- The required schema of this payload will depned on the `$SASE_COMMIT_METHOD` environment variable value.
- We should be able to override the `$SASE_COMMIT_METHOD` environment variable by using the `sase commit` command's
  `--method=<commit_method>` option.

### YOUR TASK

Can you help me make this change? This is a large piece of work that should be split into phases. I'll let you decide
how many phases to create, but keep in mind that each phase will be completed by a distinct `claude` instance.
