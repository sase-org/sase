---
plan: sdd/plans/202603/fix_duplicate_status_frontmatter.md
---
I keep seeing frontmatter like the followig in plan files:

```
---
status: done
create_time: 2026-03-26 19:21:26
status: done
---
```

I think there has to be somewhere that we are adding the `status: wip` frontmatter field and not checking if it already
exists maybe? Can you help me diagnose the root cause of this issue and fix it? Also, remove the duplicate `status`
field from any plans/ files where it exists. Think this through thoroughly and create a plan using your `/sase_plan`
skill.
