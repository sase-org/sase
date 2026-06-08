---
plan: sdd/tales/202606/pyvendor_strip_executable_prefix.md
---
 #fork:3u  The `pyvision` script is vendored into this repo using the `pyvender` script (defined in my chezmoi repo), but `pyvendor` seems to keep the `executable_` prefix when copying the file over to this repo. Can you help me fix that? The `executable_` prefix is specific to scripts in my chezmoi repo. `pyvendor` should know to strip those when copying files from chezmoi repos. Make sure you vendor the script back into this repo (using `pyvendor`) when you're done making your changes. Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the `sase plan`
command (as the skill instructs) before making any file changes.
