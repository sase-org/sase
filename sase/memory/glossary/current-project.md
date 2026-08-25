---
keyword: Current Project
---

The current project is the one sase project SASE treats as your working context: in
practice, the one you most recently launched an agent on. It is derived, not stored —
the first entry in the shared VCS xprompt MRU store (`~/.sase/vcs_xprompt_mru.json`)
that maps to an enabled project, where a Patch entry yields its owning project.
`sase project set-current` and the ACE Projects tab promote a project without launching;
the working directory never does, and there may be none. It supplies only display and
defaults, namely the ACE top-bar `+<project>` chip and the first-open value of project
filters, so it never overrides an explicit choice, project lifecycle state, or what a
command targets. `sase project current` prints it.
