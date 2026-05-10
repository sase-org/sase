---
plan: sdd/tales/202603/hg_changespec_metadata.md
---
The "ChangeSpec:" field in the agent metadata panel on the "Agents" tab of the `sase ace` TUI is not being populated
still for the hg VCS provider (see the ../retired Mercurial plugin repo), although most of the other fields I want look good and the
GitHub provider's PR creation looks good. See the `sase ace` snapshots below for context. Can you help me diagnose the
root cause of this issue and fix it? Think this through thoroughly and create a plan using your `/sase_plan` skill.

### `sase ace` Snapshot (the `#hg` VCS provider is missing the `ChangeSpec:` field)

```
⭘                                                                                                     sase ace
  CLs (1)  │  Agents (x9)  │  AXE (4)                                                                                                                                                                              ✉ 10
 Agents: 1/9   [view: collapsed]   (auto-refresh in 8s)
┌─────────────────────────────────────────────────┐┌───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ✘ [agent] eval (DONE) (7 steps) @j             ││                                                                                                                                                                   │
│  ✘ [agent] eval_foobar_2 (DONE) (7 steps) @i    ││  AGENT DETAILS                                                                                                                                                    │
│  ✘ [agent] eval_foobar_2 (DONE) (7 steps) @h    ││                                                                                                                                                                   │
│  ✘ [agent] eval (DONE) (4 steps) @g             ││  Project: eval                                                                                                                                                    │
│  ✘ [agent] eval (DONE) (4 steps) @f             ││  Workspace: #100                                                                                                                                                  │
│  ✘ [agent] eval (DONE) (4 steps) @e             ││  Embedded Workflows: hg(name=eval), commit                                                                                                                        │
│  ✘ [agent] eval (DONE) (4 steps) @d             ││  Model: GEMINI(gemini-3-flash-preview)                                                                                                                            │
│  ✘ [agent] eval (DONE) (4 steps) @b             ││  VCS: Mercurial                                                                                                                                                   │
│  ✘ [agent] eval (DONE) (4 steps) @a             ││  PID: 890868                                                                                                                                                      │
│                                                 ││  Name: @j                                                                                                                                                         │
│                                                 ││  Timestamps: BEGIN | 2026-03-25 20:21:52                                                                                                                          │
│                                                 ││              END   | 2026-03-25 20:25:22                                                                                                                          │
│                                                 ││                                                                                                                                                                   │
│                                                 ││  New Commit: http://cl/889496570                                                                                                                                  │
│                                                 ││  Commit Message: Convert foobar field from int to String in SizeSetting model                                                                                     │
│                                                 ││                                                                                                                                                                   │
│                                                 ││  ──────────────────────────────────────────────────                                                                                                               │
│                                                 ││                                                                                                                                                                   │
│                                                 ││  AGENT PROMPT                                                                                                                                                     │
│                                                 ││                                                                                                                                                                   │
│                                                 ││                                                                                                                                                                   │
│                                                 ││  Can you help me convert the new 'foobar' field added by this CL from an integer into a string? Just fix the files that                                           │
│                                                 ││  have already been edited by this file (see the diff file below) and terminate.                                                                                   │
│                                                 ││                                                                                                                                                                   │
│                                                 ││  IMPORTANT: You should make the necessary file changes, but should NOT create a commit, branch, or PR / CL yourself.                                              │
│                                                 ││  Exception: If a post-completion hook instructs you to commit, you MUST follow those instructions and commit. IMPORTANT:                                          │
│                                                 ││  You should make the necessary file changes, but should NOT create/amend a CL.                                                                                    │
│                                                 ││                                                                                                                                                                   │
│                                                 ││  ### Context Files Related to this CL                                                                                                                             │
│                                                 ││                                                                                                                                                                   │
│                                                 ││  - @ : Contains a diff of the changes made by the current CL.                                                                                                     │
│                                                 ││  - @ : Contains the current CL's change description.                                                                                                              │
│                                                 ││                                                                                                                                                                   │
│                                                 ││                                                                                                                                                                   │
│                                                 ││  ──────────────────────────────────────────────────                                                                                                               │
│                                                 ││                                                                                                                                                                   │
│                                                 ││  AGENT CHAT                                                                                                                                                       │
│                                                 ││                                                                                                                                                                   │
│                                                 ││                                                                                                                                                                   │
│                                                 ││  # Chat History - ace-run                                                                                                                                         │
│                                                 ││                                                                                                                                                               ▇▇  │
│                                                 ││  **Timestamp:** 2026-03-25 20:25:22 EDT                                                                                                                           │
│                                                 ││                                                                                                                                                                   │
│                                                 ││  ## Prompt                                                                                                                                                        │
│                                                 ││                                                                                                                                                                   │
│                                                 ││  #hg:eval Can you help me convert the new 'foobar' field added by this CL from an integer into a string? Just fix the                                             │
│                                                 ││  files that have already been edited by this file (see the diff file below) and terminate. #commit                                                                │
│                                                 ││                                                                                                                                                                   │
│                                                 ││  ## Response                                                                                                                                                      │
│                                                 ││                                                                                                                                                                   │
│                                                 ││  I will start by determining the current workspace and identifying any active changelists to locate the 'foobar' field changes.                                   │
│                                                 ││  I will list the modified files and their current differences in this workspace to identify where 'foobar' was added.                                             │
│                                                 ││  I will search for the term 'foobar' in the workspace to locate where the new field was recently added.                                                           │
│                                                 ││  I will examine the last few commits in this workspace to find the 'foobar' field addition.                                                                       │
│                                                 ││  I will export and examine the differences in changeset 97 to identify the files containing the 'foobar' field.                                                   │
│                                                 ││  I will resolve the paths for the identified files and then read the content of `size_setting.dart` to prepare for the type conversion of the `foobar` field.     │
│                                                 ││  I will now read the `size_setting.dart` file to confirm its current contents and plan the `foobar` field update.                                                 │
│                                                 ││  I will check my current changeset ID using `hg id` to confirm if I am on the correct branch for the 'foobar' changes.                                            │
│                                                 ││  I will update my workspace to the latest changeset using `hg update tip` to include the 'foobar' field changes.                                                  │
│                                                 ││                                                                                                                                                                   │
└─────────────────────────────────────────────────┘└─────────────────────────────────────────────────────────────────────── ○ files  ○ thinking ───────────────────────────────────────────────────────────────────────┘
 COPY c chat  p prompt  s snap                                                                                                                                                                                 RUNNING
```

### `sase ace` Snapshot (the agent that ran using the `#gh` VCS provider correctly populates the `ChangeSpec:` field)

```
⭘                                                                                                     sase ace
  CLs (.12)  │  Agents (x12)  │  AXE (6)                                                                                                                                                                   ■ IDLE  ✉ 18
 Agents: 1/12   [view: collapsed]   (auto-refresh in 1s)
┌──────────────────────────────────────────────────┐┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  ✘ [agent] sase (DONE) (9 steps) @d              ││                                                                                                                                                                  │
│  ✘ [agent] sase (PLAN DONE) (6 steps)            ││  AGENT DETAILS                                                                                                                                                   │
│  ⚡ ✘ [agent] sase (PLAN DONE) (6 steps)         ││                                                                                                                                                                  │
│  ✘ [agent] sase (DONE) (5 steps) @c              ││  ChangeSpec: sase_e2e_test_comment_2                                                                                                                             │
│  ✘ [agent] sase (DONE) (5 steps) @a              ││  Workspace: #100                                                                                                                                                 │
│  ⚡ ✘ [agent] sase (DONE) (5 steps) @sase-c.4    ││  Embedded Workflows: gh(gh_ref=sase), pr                                                                                                                         │
│  ⚡ ✘ [agent] sase (DONE) (5 steps) @sase-c.3    ││  Model: CLAUDE(opus)                                                                                                                                             │
│  ⚡ ✘ [agent] sase (DONE) (5 steps) @sase-c.2    ││  VCS: GitHub                                                                                                                                                     │
│  ⚡ ✘ [agent] sase (DONE) (5 steps) @sase-c.1    ││  PID: 14322                                                                                                                                                      │
│  ✘ [agent] sase (DONE) (5 steps) @b              ││  Name: @d                                                                                                                                                        │
│  ✘ [agent] sase (PLAN DONE) (7 steps)            ││  Timestamps: BEGIN | 2026-03-25 20:21:16                                                                                                                         │
│  ✘ [agent] sase (PLAN DONE) (6 steps) @j         ││              END   | 2026-03-25 20:21:51                                                                                                                         │
│                                                  ││                                                                                                                                                                  │
│                                                  ││  Pr Header: chore: Add E2E test comment to pyproject.toml                                                                                                        │
│                                                  ││  Pr Url: https://github.com/sase-org/sase/pull/22                                                                                                                │
│                                                  ││  Commit Message: chore: Add E2E test comment to pyproject.toml                                                                                                   │
│                                                  ││                                                                                                                                                                  │
│                                                  ││  ──────────────────────────────────────────────────                                                                                                              │
│                                                  ││                                                                                                                                                                  │
│                                                  ││  AGENT PROMPT                                                                                                                                                    │
│                                                  ││                                                                                                                                                                  │
│                                                  ││                                                                                                                                                                  │
│                                                  ││  Add a comment to the top of pyproject.toml saying: `# SASE E2E test comment (please delete)`                                                                    │
│                                                  ││                                                                                                                                                                  │
│                                                  ││  IMPORTANT: You should make the necessary file changes, but should NOT create a commit, branch, or PR / CL yourself.                                             │
│                                                  ││  Exception: If a post-completion hook instructs you to commit, you MUST follow those instructions and commit.                                                    │
│                                                  ││                                                                                                                                                                  │
│                                                  ││                                                                                                                                                                  │
│                                                  ││  ──────────────────────────────────────────────────                                                                                                              │
│                                                  ││                                                                                                                                                                  │
│                                                  ││  AGENT CHAT                                                                                                                                                      │
│                                                  ││                                                                                                                                                                  │
│                                                  ││                                                                                                                                                                  │
│                                                  ││  # Chat History - ace-run                                                                                                                                        │
│                                                  ││                                                                                                                                                                  │
│                                                  ││  **Timestamp:** 2026-03-25 20:21:51 EDT                                                                                                                          │
│                                                  ││                                                                                                                                                                  │
│                                                  ││  ## Prompt                                                                                                                                                       │
│                                                  ││                                                                                                                                                                  │
│                                                  ││  #gh:sase Add a comment to the top of pyproject.toml saying: `# SASE E2E test comment (please delete)` #pr                                                       │
│                                                  ││                                                                                                                                                                  │
│                                                  ││  ## Response                                                                                                                                                     │
│                                                  ││                                                                                                                                                                  │
│                                                  ││  Done. Added the comment to the top of `pyproject.toml`.                                                                                                         │
│                                                  ││                                                                                                                                                                  │
│                                                  ││  No in-progress beads. Committing the change now.                                                                                                                │
│                                                  ││                                                                                                                                                                  │
│                                                  ││  Committed and PR created via `sase commit`. The change adds the E2E test comment to the top of `pyproject.toml`.                                                │
│                                                  ││                                                                                                                                                                  │
│                                                  ││                                                                                                                                                                  │
│                                                  ││                                                                                                                                                                  │
│                                                  ││                                                                                                                                                                  │
│                                                  ││                                                                                                                                                                  │
│                                                  ││                                                                                                                                                                  │
│                                                  ││                                                                                                                                                                  │
│                                                  ││                                                                                                                                                                  │
│                                                  ││                                                                                                                                                                  │
│                                                  ││                                                                                                                                                                  │
│                                                  ││                                                                                                                                                                  │
│                                                  ││                                                                                                                                                                  │
└──────────────────────────────────────────────────┘└────────────────────────────────────────────────────────────────────── ● files  ● thinking ───────────────────────────────────────────────────────────────────────┘
 COPY c chat  p prompt  s snap                                                                                                                                                                                 RUNNING
```
