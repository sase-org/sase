# SASE Tools (executable scripts)

Any script in this directory that has a suffix of the form `-YYmmdd` (ex: `pyvision-260227`) was vendored into this repo
from my chezmoi dotfile repo (the ../lib/bugyi-260217.sh file was also vendored using `pyvendor`). If you are asked to
modify any of these files, you should instead make the change in the original source file in my dotfiles repo, use your
commit skill (NOT `git commit`) to commit the change in that repo, and then re-vendor it here using `pyvendor`.

## `pyvision-260227`

This linter will fail if any public symbol is unused by other (non-test) files, if any private symbol is used by other
files, or if any private symbol is NOT used in the file it is defined in. This linter should normally be obeye since it
does a good job of preventing unused code from accumulating. With that said, when working an epic (a bead that has been
broken down into phases), it may be necessary to ignore one or more symbols (that will be used by later phases). You can
accomplish this by adding the `--epic-symbol <epic_bead_id>(<symbol_name>)` option to the `pyvision` command in Justfile
for every symbol that needs to be ignored.
