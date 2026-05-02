---
plan: sdd/plans/202604/filter_sase_dir_from_file_history.md
---
We should never store file references (see the plans/202604/ctrlt_file_history_completion.md file for context) that
point to files in a local .sase/ directory. We should, however, store the ~/ file references (if they were preficed with
`@`, then they would have been transformed into .sase/home/ file paths). Can you help me make these changes? Think this
through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
