---
plan: sdd/tales/202604/shard_sase_dirs_by_yyyymm.md
---
I suspect that much of the TUI performance issues coming from this machine stem from reading directories that have way
too many top-level (i.e. not nexted in a subdirectory) files in them. Can you help me fix this by having sase start
using sub-directories of the form `YYYYMM/` (ex: 202604/) whereever appropriate (whereever you determine there is
legitimate concern for this)? Make sure you also move the existing files on this machine to their approriate
subdirectory. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file
changes.
