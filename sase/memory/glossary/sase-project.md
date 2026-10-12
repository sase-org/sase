---
keyword: Sase Project
---

A sase project is a named unit of work registered with SASE. Existing repositories can
be added with `sase project add` or the New Project wizard; the wizard can also create a
repository through the provider. `sase project create` creates a repository and
registers the resulting project. A new VCS macro argument can also create a project:
`#git:<name>` accepts any valid project name, while `#gh:<org>/<repo>` requires an
existing GitHub repository. Its ProjectSpec is `~/.sase/projects/<key>/<key>.sase`,
where the directory key `<key>` is `<name>` for `#git` projects but `gh_<org>__<repo>`
for `#gh` projects (ex: `gh_sase-org__sase`); the user-facing name is the spec's
`PROJECT_NAME:` (ex: `sase`) or, if unset, the key. Projects have exactly two
user-facing states, enabled and disabled; onboarding leaves `PROJECT_STATE:` unset, so
new projects are enabled by default, and only an explicit disable changes that. The
system-managed `home` project remains hidden. Prompts name an existing project with a
[[glossary:project-tag]] (`+<project>`). Directory keys, names, and aliases are unique
across projects and VCS types, compared case-insensitively.
