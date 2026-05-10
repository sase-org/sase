---
plan: sdd/tales/202603/branch_naming_reform.md
---
It looks like we are trying to checkout the wrong branch here! I just changed the STATUS field of this ChangeSpec (see
the `sase ace` snapshot below) from "Draft" to "Ready", which removed the `_<N>` suffix. I'm worried we are not handling
branch names / renames appropriately, so here are the rules:

- We should always make sure that branch names and ChangeSpec names are synced. This means that the branch corresponding
  to the `sase_xprompt_snippets` ChangeSpec shown below should also be named `sase_xprompt_snippets`. This also means
  that when the status change caused the `sase_xprompt_snippets_1` ChangeSpec NAME field value to be updated to
  `sase_xprompt_snippets`, the corresponding branch should have ideally been renamed to `sase_xprompt_snippets`.
- The above rule needs to be broken for the GitHub integration, however, since branch names corresponding to PRs cannot
  be renamed without closing the PR. In this case, we will need to save the candidate branch number (the `<N>` from
  above) to disk somewhere and associate it with the ChangeSpec. We should make this VCS-agnostic by allowing a VCS
  provider to subscribe to this functionality.
- NO dashes (`-`) should ever be used in branch names (use underscores instead).

Can you help me diagnose the root cause of this issue, help me fix it, and also redesign the system as necessary to
fulfill the constraints above? This is a large piece of work that should be split into phases. I'll let you decide how
many phases to create, but keep in mind that each phase will be completed by a distinct agent instance (i.e. a distinct
`claude` / `gemini` / `codex` command). Think this through thoroughly and create a plan using your `/sase_plan` skill
before making any file changes.

Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

### Additional Requirements

- Make sure you make this work with the ../retired Mercurial plugin repo, but do NOT change any of the behavior for that VCS
  provider. It's fine if you need to make code changes to that repo, but none of the behavior should change.

### `sase ace` Snapshot

```
⭘                                                                                                                    sase ace
  CLs (1)  │  Agents (2 x2)  │  AXE (6)                                                                                                                                                                                                   ■ IDLE  ✉ 5
 ChangeSpec: 1/1   +14X +16S   (auto-refresh in 1s)                         ┌───────────────────────────────────────────────────────────────────────────────────────────────────────────▌                                                           ─┐
┌──────────────────────────────────────────────────────────────────────────┐│ Search Query » project:sase                                                                               ▌ checkout failed: git checkout failed: error: pathspec      │
│  [R] sase_xprompt_snippets (https://github.com/sase-org/sase/pull/31)    │└───────────────────────────────────────────────────────────────────────────────────────────────────────────▌ 'xprompt-snippets' did not match any file(s) known to git ─┘
│                                                                          │┌───────────────────────────────────────────────────────────────────────────────────────────────────────────▌                                                           ─┐
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││  ╭────────────────────────────────────────────────────────────── ~/.sase/projects/sase/sase.gp:321 ───────────────────────────────────────────────────────────────╮    │
│                                                                          ││  │                                                                                                                                                                │    │
│                                                                          ││  │  RUNNING:                                                                                                                                                      │    │
│                                                                          ││  │    #101 | 2744769 | ace(run)-260328_181441 | sase                                                                                                              │    │
│                                                                          ││  │    #105 |  883042 | ace(run)-260329_133732 | sase                                                                                                              │    │
│                                                                          ││  │    #106 |  969915 | ace(run)-260329_135928 | sase                                                                                                              │    │
│                                                                          ││  │    #102 | 1022543 | ace(run)-260329_141156 | sase                                                                                                              │    │
│                                                                          ││  │                                                                                                                                                                │    │
│                                                                          ││  │                                                                                                                                                                │    │
│                                                                          ││  │  NAME: sase_xprompt_snippets                                                                                                                                   │    │
│                                                                          ││  │  DESCRIPTION:                                                                                                                                                  │    │
│                                                                          ││  │    chore: Add research on integrating xprompt parts as expandable snippets                                                                                     │    │
│                                                                          ││  │  PR: https://github.com/sase-org/sase/pull/31                                                                                                                  │    │
│                                                                          ││  │  STATUS: Ready                                                                                                                                                 │    │
│                                                                          ││  │  COMMITS:                                                                                                                                                      │    │
│                                                                          ││  │    (1) [run] Initial Commit                                                                                                                                    │    │
│                                                                          ││  │        | CHAT: ~/.sase/chats/sase-org-ace_run-260329_133730.md (5m20s)                                                                                         │    │
│                                                                          ││  │        | DIFF: ~/.sase/diffs/sase_xprompt_snippets-260329_134250.diff                                                                                          │    │
│                                                                          ││  │  HOOKS:                                                                                                                                                        │    │
│                                                                          ││  │    just lint  [folded: PASSED: 1]                                                                                                                              │    │
│                                                                          ││  │    just test  [folded: PASSED: 1]                                                                                                                              │    │
│                                                                          ││  │                                                                                                                                                                │    │
│                                                                          ││  ╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯    │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
│                                                                          ││                                                                                                                                                                        │
└──────────────────────────────────────────────────────────────────────────┘└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
 COPY ! +snap  % raw  b bug  c CL#  n name  p spec  s snap                                                                                                                                                                                   RUNNING
```
