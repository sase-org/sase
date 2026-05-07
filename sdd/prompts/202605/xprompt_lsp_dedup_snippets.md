---
plan: sdd/tales/202605/xprompt_lsp_dedup_snippets.md
---
 Can you help me stop returning duplicate xprompts from our new LSP server (see the nvim snapshot below for context)? Let's only show one row in the completion menu for each xprompt. The row should be a snippet and should either expand to `#foo ` (if it has no required args), `#foo:` if it has one required (non-text type) arg, `#foo(<cursor_goes_here>)` (if there are multiple required args), or `#foo::` if there is one required argument of type `text`. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.

```
▎ 1.  sase_ace_prompt_i… ●
 CWD:  ~/projects/github/sase-org/sase
💡1   #gh:sase #bd💡earch_swarm:                                                                                                                                                                                     W 1
               #bd/land_epic                    󰉿 (bead_id: word)
               #bd/land_epic(...) snippet        (bead_id: word)
               #bd/land_epic: snippet            (bead_id: word)
               #bd/land_legend                  󰉿 (bead_id: word)
               #bd/land_legend(...) snippet      (bead_id: word)
               #bd/land_legend: snippet          (bead_id: word)
               #bd/new_epic                     󰉿 (plan_file_path: path, legend_bead_id?: word, changespec?: word, bug_id?: int)
               #bd/new_epic(...) snippet         (plan_file_path: path, legend_bead_id?: word, changespec?: word, bug_id?: int)
               #bd/new_epic: snippet             (plan_file_path: path, legend_bead_id?: word, changespec?: word, bug_id?: int)
               #bd/new_legend                   󰉿 (plan_file_path: path)
               #bd/new_legend(...) snippet       (plan_file_path: path)
               #bd/new_legend: snippet           (plan_file_path: path)
               #bd/next                         󰉿 (prompt?: text)
               #bd/next: snippet                 (prompt?: text)
               #bd/review/plan                  󰉿 (file_base: word)
               #bd/review/plan(...) snippet      (file_base: word)
               #bd/review/plan: snippet          (file_base: word)
               #bd/review/prompt                󰉿 (file_base: word)
               #bd/review/prompt(...) snippet    (file_base: word)
               #bd/review/prompt: snippet        (file_base: word)
               #bd/work_phase_bead              󰉿 (bead_id: word)
               #bd/work_phase_bead(...) snippet  (bead_id: word)
               #bd/work_phase_bead: snippet      (bead_id: word)








































 INSERT   master  ~/Sync/home/tmp/sase/sase_ace_prompt_izoq7t27.md [+]                                                                                                                    markdown  Top    1:13
-- INSERT --
```