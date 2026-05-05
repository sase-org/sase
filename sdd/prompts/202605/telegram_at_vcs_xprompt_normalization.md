---
plan: sdd/tales/202605/telegram_at_vcs_xprompt_normalization.md
---
  Can you help me start substituting "@" for ":" an inbound telegram messages before sending them to sase when it appears those "@" symbols are in the middle of and xprompt invocation? For example
```
#gh@sase
```
Should be replaced with 
```
#gh:sase
```
This will allow us to get rid of one of the hacks (see the 'gh_sase' xprompt, for example) that we use for VCS xprompt workflows currently. Think this through thoroughly and create a plan using your `/sase_plan` skill before making any file changes.
 