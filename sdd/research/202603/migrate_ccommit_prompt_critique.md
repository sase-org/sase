## Prompt Review: Gaps and Design Decisions Needed

Your prompt asks to "integrate all functionality from the `/commit` skill and ccommit scripts into our new unified
commit/propose/pr workflows" but leaves several significant design decisions implicit. An agent executing this would
need to make choices that could easily go wrong.

### 1. Where does the logic land?

`ccommit` is a 530-line bash script. The unified workflow has three layers:

- **Skill instructions** (what the agent does) — `sase_git_commit/SKILL.md`
- **Python workflow** — `CommitWorkflow` dispatching to VCS provider hooks
- **VCS provider** — `_git_common.py`'s `vcs_create_commit` / `vcs_create_proposal` / `vcs_create_pull_request`

The prompt doesn't specify which layer should absorb each piece of `ccommit` functionality. For example, should
`just fmt` be called in the Python VCS provider, or should the skill instructions tell the agent to run it? These are
very different designs.

#### DECISIONS

- We should migrate the `ccommit` script to src/sase/scripts/sase_git_commit in this repo.
- We should also start using this new `sase_git_commit` script to make git commits from `sase commit` (you might need to
  edit the ../sase-github repo for this).

### 2. Feature-by-feature ambiguity

Here are the ccommit features not present in the unified workflow, each needing a decision:

| ccommit feature                           | Present in unified?                      | Decision needed                                            |
| ----------------------------------------- | ---------------------------------------- | ---------------------------------------------------------- |
| `just fmt` + re-stage                     | No (stop hook does it separately)        | Redundant with stop hook? Or add to VCS provider?          |
| Merge/pull from origin/master             | No                                       | Add to VCS provider? Skip for propose/PR? Rebase vs merge? |
| Push retry (pull + re-push)               | No (bare `git push`)                     | Add retry logic?                                           |
| Bead close + sync + note + amend          | Partially (skill says to close manually) | Programmatic in VCS provider, or agent responsibility?     |
| `SASE_PLAN` in commit message + mark done | No                                       | Add to VCS provider? Or to `CommitWorkflow.run()`?         |
| Desktop notifications                     | No                                       | Add? Where?                                                |
| JSON logging (`~/.ccommit.jsonl`)         | No                                       | Add? Or rely on sase's own logging?                        |
| Conventional commit tag validation        | No (agent composes message freely)       | Validate programmatically? Or trust the agent?             |

#### DECISIONS

- `just fmt`: This should be supported via a new `precommit_command` sase.yml config field. You should set
  `precommit_command: "just fix"` in this repo's local sase.yml file (make sure this field is supported in local
  sase.yml files) and set `precommit_command: "sase_hg_fix"` to the ../retired Mercurial plugin repo's default_config.yml file
  (`sase_hg_fix` is a new script that you should create in that repo that wraps `hg fix`, but only runs it if we are in
  an hg repo (make sure this works reliably).
- Merge/pull from origin/master: Add to the VCS providers. Replicate this for git repos, but just
  `hg update <branch_name>` should be sufficient for the ../retired Mercurial plugin repo (hg VCS provider).
- Beads: The bead operations should be performed by `sase commit` (make sure we support repos that do NOT have
  `sdd.version_controlled` set to `true`).
- `SASE_PLAN` in commit message + mark as done: This should be supported for all repos (regardless of VCS provider or
  the `sdd.version_controlled` config field---though this field will control where the plans/ directory lives).
- Desktop notifications: We don't need to suppor tthis.
- JSON logging: This should be supported by the new `sase_git_commit` script.
- Conventional commit tag validation: Let's not worry about this for now.

### 3. What happens to existing artifacts?

The prompt doesn't say:

- **Is `/commit` skill (ccommit-based) deprecated?** If both paths coexist, agents have two ways to commit, which is
  confusing.
- **Is the `ccommit` bash script deleted?** Or kept for manual human use outside of sase workflows?
- **Does the chezmoi-managed `SKILL.md` for `/commit` get updated or removed?**

#### DECISIONS

- Delete the `/commit` skill (and all references to it) and the `ccommit` script as the last phase in your plan.

### 4. Scope across the three methods

ccommit is commit-only. The unified system has `create_commit`, `create_proposal`, and `create_pull_request`. The prompt
says "integrate all functionality" but doesn't clarify which features apply to which methods:

- Merge-with-master makes sense for `create_commit` but probably not `create_pull_request` (which creates a branch).
- Bead handling likely applies to all three, but the amend-to-fold-bead-notes pattern doesn't translate to proposals.
- Push retry applies to commit/push but not proposals in systems where proposals are branch-only.

#### DECISIONS

Use your best judgement on these.

### 5. Missing: the `/commit` skill instruction → `sase_git_commit` convergence

Right now there are **two competing skill definitions**:

- `/commit` — tells the agent to run `ccommit <tag> <message> <files...>`
- `/sase_git_commit` — tells the agent to run `.venv/bin/sase commit '<json>'`

The prompt should specify: after integration, which skill does the agent use? If the answer is `sase_git_commit`, then
its SKILL.md needs to be updated with any ccommit-specific instructions that the agent is responsible for (like
conventional tag selection, bead checking).

#### DECISIONS

- The `/commit` skill gets deleted. Modify the `/sase_git_commit` skill as needed.
- Stop telling the agent to use `.venv/bin/sase commit` (tell it to just use `sase commit`).

### 6. The stop hook interaction

The `sase_commit_stop_hook` detects uncommitted changes and tells the agent to run `/sase_git_commit`. If `/commit` is
being absorbed, should the stop hook's behavior change? Currently it never invokes `/commit`.

#### DECISIONS

No. Instead, the `/sase_git_commit` skill should be updated as needed.

---

### Suggested additions to your prompt

To make this actionable, I'd add decisions on:

1. **Deprecation stance**: "After this work, the `/commit` skill and `ccommit` script should be [deprecated/removed/kept
   for manual use only]."
2. **Layer assignment**: "Programmatic features (fmt, merge, push retry, bead lifecycle) should be implemented in [the
   VCS provider Python code / a new helper module / the skill instructions]."
3. **Method scope**: "Features X, Y, Z apply to all three methods; features A, B apply only to `create_commit`."
4. **What to skip**: Explicitly call out any ccommit features you do NOT want ported (e.g., desktop notifications, JSON
   logging).

Would you like to discuss any of these decisions now?
