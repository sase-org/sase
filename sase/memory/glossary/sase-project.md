---
keyword: Sase Project
---

A sase project is a named unit of work registered with SASE. A project is created only
when a new VCS xprompt argument resolves to a valid project: `#git:<name>` accepts any
valid project name, while `#gh:<org>/<repo>` requires an existing GitHub repository. Its
ProjectSpec is `~/.sase/projects/<key>/<key>.sase`, where the directory key `<key>` is
`<name>` for `#git` projects but `gh_<org>__<repo>` for `#gh` projects (ex:
`gh_sase-org__sase`); the user-facing name is the spec's `PROJECT_NAME:` (ex: `sase`)
or, if unset, the key. Projects have exactly two user-facing states, enabled and
disabled; missing `PROJECT_STATE:` means enabled, and only an explicit disable changes
that. The system-managed `home` project remains hidden.
