---
plan: sdd/plans/202604/enter_accepts_file_completion.md
---
When I hit `<enter>` when the new file completion menu (see recent, related git commits) is shown currently, it launches
an agent. This is incorrect. We should instead expand the currently selected file/directory in the prompt input widget
and dismiss (i.e. make it disappear) the file completion menu. Can you help me fix this? Think this through thoroughly
and create a plan using your `/sase_plan` skill before making any file changes.
