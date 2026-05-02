---
plan: sdd/tales/202603/project_local_xprompts_in_panels.md
---
When I type the following in the prompt input widget, the xprompt selection panel showed, but none of the xprompts in
the sase repo's local sase.yml file (ex: `#sase/docs`) showed in the panel: `gh:sase #@` We should make sure that, if a
VCS workflow (ex: `#gh:sase`) is embedded in the prompt, that we show ALL xprompts defined in a local sase.yml file in
that repo. Can you help me fix this?

Also, when the `#` keymap is used to show the other xprompt panel, we should show ALL known xprompts from ALL known
projects (you might need to be smart about this so it doesn't slow down that panel's startup--there shouldn't be much
lag between hitting the `#` key and the panel popping up).

Think this through thoroughly and create a plan for it.
