---
plan: sdd/tales/202603/vcs_aware_tag_disambiguation.md
---
Can you help me add a `#pr_diff` xprompt to the default_config.yml file in the ../sase-github repo (create this file if
it doesn't already exist) that has the "diff_file" xprompt tag? We'll need to start allowing this tag to be on multiple
xprompt of the same priority in order to allow users to install the ../retired Mercurial plugin and ../sase-github plugins on the
same machine. We should be able to do this by prioritizing the xprompt that is defined in the same repo as the VCS
workflow that is embedded in the prompt (ex: use `#cl_diff` if `#hg` was embedded and use `#pr_diff` if `#gh` was
embedded). Think this through thoroughly and create a plan using your `/sase_plan` skill.
