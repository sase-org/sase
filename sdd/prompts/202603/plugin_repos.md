I want to split out the VCS functionality into separate plugin git repos that all live in directories of the form
`~/projects/github/bbugyi200/sase-*/`. These should support scripts (e.g. chops, metahooks, etc.), xprompts, the
existing VCS pluggy hooks, sase.yml default overrides, and any other functionality that YOU think should be configurable
on a per-team / per-company basis. I want you to lead the design here. Make it modern and easy to understand. Other
requirements:

- We should definitely create the sase-github and retired Mercurial plugin directories and move ALL of the appropriate files to those
  directories.
- We should also create a first git commit in those directories after initializing them as git repos. Don't worry about
  pushing them to GitHub (I haven't created the repos yet).
- We will need to configure Github Actions to actually release these Python packages to PyPI. This inclues the existing
  `sase` package. I'm not sure what package names are available. Prefer `sase`, but I could also live with `sase-cli` or
  something like that if `sase` is taken. I'm more confident that `sase-github` and `retired Mercurial plugin` will be available, but
  we can check that as well. We should also create the appropriate GitHub Actions workflow files to build and publish
  the packages when we push new tags.
- End the plan with instructions for the user on how to set up their system the way it was before (I assume I'll need to
  install the new plugin packages?).
- Review the research that we've stored in the sdd/research/202602/ directory (specifically `pluggy_repo_separation.md` and `sase_plugin_specifics.md`) for inspiration.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance.
