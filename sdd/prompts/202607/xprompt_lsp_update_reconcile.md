---
plan: sdd/tales/202607/xprompt_lsp_update_reconcile.md
---
 Can you help me make sure that the sase xprompt LSP server is properly re-compiled and re-installed (if necessary) when the user updates sase (e.g. via the `u` keymap on the "Updates" tab of the "SASE Admin Center" panel)? If not, use your /sase_plan skill to plan the appropriate changes.
 The concern is that we need to make sure that, after an update, the user is able to immediately start using new LSP functionality that was added to the sase-core repo in a commit that was pulled in during the update. 