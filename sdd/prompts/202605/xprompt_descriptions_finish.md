---
plan: sdd/tales/202605/xprompt_descriptions_finish.md
---
    Can you help me verify that all the work associated with the bead with ID sase-3w is complete?

Actually read through the source code and the git commits that are associated with that bead's work (they should have
the bead ID in the commit message) and ensure all of the work that the previous agents say is complete, is actually
complete. Also, run `sase bead show` on every child bead and ensure that any notes on those beads have been
addressed.

If not, plan out the remaining work using your /sase_plan skill (make sure to include closing the bead as the
final step of the plan) and complete it. Otherwise, close the bead using the `sase bead close` command. If
available, run the `just pyvision` command AFTER closing the epic bead (some symbols can be ignored while an epic
is open) to make sure we didn't leave any unused code behind.

Finally, find the plan file associated with this work (which should be in the sdd/epics/ directory, in a YYYYMM
subdirectory). If found, a `status` field should be added (or updated if it already exists) to the frontmatter of
the plan file with a value of `done`.

Sibling repos for this project are available in workspace-matched directories:
- core: /home/bryan/.local/state/sase/workspaces/sase-org/sase-core/sase-core_10
- github: /home/bryan/.local/state/sase/workspaces/sase-org/sase-github/sase-github_10
- telegram: /home/bryan/.local/state/sase/workspaces/sase-org/sase-telegram/sase-telegram_10
- nvim: /home/bryan/.local/state/sase/workspaces/sase-org/sase-nvim/sase-nvim_10
- chezmoi: /home/bryan/.local/share/chezmoi
When editing a sibling repo, use its workspace-matched directory, not the primary checkout.


### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (memory/long/external_repos, matched: `chezmoi`, `sase-github`, `sase-telegram`, `sase-nvim`, `sase-core`)