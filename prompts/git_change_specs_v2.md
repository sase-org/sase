Can you help me make several improvements to ChangeSpecs and improve support for git / GitHub (which use the #git or #gh
embedded workflows, respectively) projects? Can you split this work up into phases? I'll let you decide how many phases
to use, but keep in mind that each phase will be given to a distinct `claude` instance to complete.

### STATUS Field Value Changes

- The current "Drafted" status value should be renamed to "Ready".
- The current "WIP" status value should be renamed to "Draft".
- We will add a new status value named "WIP" (distinct from the old WIP which is now Draft), which should act like the
  current WIP status with one exception: No HOOKS or MENTORS should be run by `sase axe`. ChangeSpecs with a WIP status
  should use the `__<N>` suffix. This suffix shouldn't be removed until the status is changed to "Ready" (we should run
  the same logic that we do now when transitioning from WIP -> Drafted status).
- You should write a migration script to update all existing ChangeSpecs in the system to use these new status values
  (ex: WIP -> Draft, Drafted -> Ready).

### VCS Embedded Workflow (#git, #gh, and #hg) Changes

- We should stop using the `agent_<N>` style for branch names when using the #gh or #git embedded workflows. Instead, we
  should pre-create a list of 100 random, but human-readable branch names and use those in a round-robin fashion. Also,
  we should stop associating branch names with workspace numbers / workspace directories (i.e. use a new, unused,
  pre-created branch name when the #gh or #git workflows are embedded in a prompt).
- We should always create a ChangeSpec associated with the random branch name if the agent created a commit (it will
  after file changes thanks to our stop hooks). Submitting the ChangeSpec should merge the branch with master (after
  performing any necessary checks, like making sure
- All VCS workflows should be given a new `n` input that accepts an integer, but defaults to `null`. When no value is
  given, we should claim an unused workspace as usual. If `n` is provided, however, we use that workspace number (or the
  primary workspace directory if `n` is `1`). Additionally, we should start outputing the workspace number using an
  `output` field in each of these workflows. This way we can use this in an xprompt YAML workflow to run multiple agents
  in sequence, in the same workspace directory.
- When the `n` input is given, we shouldn't release the workspace directory like we normally do in a post-step. We
  should be able to force a workspace release with a new `release` boolean input that defaults to `false` when `n` is
  given or `true` otherwise (figure out how to make this work). If this is set to `true`, we should release the
  workspace as normal. NOTE: You might need to add a marker to the RUNNING entry (or however you track this) to make
  sure that `sase axe` doesn't release the workspace for you (ex: it might be checking the PID and releasing if the
  agent process is no longer running).

### #commit, #amend, and #propose Embedded Workflow Changes

- We should rename the #cl xprompt (in the sase.yml file in my chezmoi repo) to #cldd (make sure to update ALL
  references, if any, in this codebase and in the chezmoi repo).
- The #commit workflow (see the xprompts/commit.yml file) should be renamed to #cl.
- The #amend workflow should be renamed to #commit.
- We should add a new, optional boolean `wip` input that defaults to `false` to the new #cl workflow. When this is set
  to `true`, the workflow should create a ChangeSpec with a WIP status (instead of Draft).
- We should add support to the #propose workflow for #git and #gh workflows. These should save the diff of the file
  changes made by the agent and create a new ChangeSpec proposal (just like when used with #hg).
- Changing a git/GitHub ChangeSpec STATUS to "Submitted" should merge the branch (when using random branch names--see
  next section for what to do when a PR exists) with master and delete the branch name. Perform this merge in the
  primary workspace directory. Additionally, since we only have 100 random branch names and every ChangeSpec must have a
  unique name, append `__YYmmdd_HHMMSS` (where the timestamp is the time of submission) to the ChangeSpec name when we
  merge and delete the branch.

### The NEW #pr Embedded Workflow

- We should stop creating PRs automatically when using the #gh workflow. Instead, we should add a new #pr embedded
  workflow that creates a PR.
- The #pr workflow should accept a `name` input which should be used in the same way the #cl workflow uses its `name`
  input: as the branch name and ChangeSpec name.
- The PR should have a good title and body, which we will generate using a new #new_pr_desc workflow (invoked by the #pr
  workflow somehow; you figure out how to make that work).
- When the #commit workflow is used on a branch that already has a PR, it should update the PR with the new commit and
  add a bullet to the PR description with the commit message header and a link to the commit in the PR.
- Changing a GitHub ChangeSpec STATUS to "Submitted" should merge the PR (if one exists--I think we can do this by just
  merging the branch to master in the primary workspace directory?) if the project is associated with your GitHub
  account (we will need to add a new sase.yml field for this I think--update the chezmoi repo to configure mine to be
  `bbugyi200`). Otherwise, this should not be allowed and a good error message should be displayed.
