---
plan: sdd/tales/202603/fix_pr_bug_tag.md
---
Can you help me figure out when we stopped adding the `BUG=<bug_id>` PR tag to PR descriptions when creating them with
the `#pr` xprompt workflow and fix this? This PR tag should be added with the `#pr` xprompt's `bug_id` input is set. I
just created a PR on another machine and the BUG tag was not added, but the default PR tags (see the ../retired Mercurial plugin
repo's config) were added (so I guess it's possible that these tags overwrote the BUG tag too--check for that). Think
this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
