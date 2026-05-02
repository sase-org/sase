---
plan: sdd/epics/202603/xprompt_tags.md
---
#gh:sase Can you help me add support for "xprompt tags" that mark certain xprompts as special?

- These tags will be supported via a new `tags: <tags>` xprompt field (in YAML or frontmatter), where `<tags>` is a
  comma-separated list of pre-defined (by sase) tag names.
- We should support the following tags:
  - **vcs**: Marks an xprompt as a VCS workflow (ex: `#git`, `#gh`, and `#hg`). NOTE: This should obsolete and replace
    the `wraps_all` field!
  - **crs**: This tag marks an xprompt as the xprompt that we should use when handling reviewer comments. We currently
    use the `#crs` xprompt for this (make sure to add the tag to that xprompt). This functionality can be overridden by
    the user by setting the "handle_review_comments" tag on one (and ONLY one) of their own xprompts; sase should
    respect the following precedence: local xprompts, user xprompts (ex: in ~/xprompts), builtin xprompts (in this
    repo).
  - **fix_hook**: Marks an xprompt as the xprompt we should use to fix HOOKS. We use `#fix_hook` for this currently, so
    that xprompt should be tagged. Users should be able to override this xprompt too (see above bullet).
  - **rollover**: This tag marks an xprompt workflow as one that should be "rolled over" to coder (`.code`) / question
    (`.q`) agents. We currently seem to do this for ALL xprompts, but this is a bug. Some workflows are only meant to be
    embedded in the planner agent.
- Make sure to update all plugin repos accordingly.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance.
