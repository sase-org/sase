Can you help me dig through the sase plugin integration logic along with the rest of the codebase to confirm that we
have abstracted away ALL logic that might be specific to a certain VCS? If not plan the migration of the appropriate
code to the ../sase-github/ and/or ../retired Mercurial plugin/ repos. Our goal is to be able to implement a gitlab integration, a
facebook integration (using their internal VCS), and more without having to make ANY code changes to sase's core.

This is a large piece of work that should be split into phases. I'll let you decide how many phases to create, but keep
in mind that each phase will be completed by a distinct `claude` instance.
