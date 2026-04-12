# Ephemeral `sase_<N>` Workspace Directories

Sase runs agents (like you) are run from ephemeral workspace directories, which are full clones of the sase repo that
live in the same parent directory as the main repo. These directories are named `sase_<N>` where `<N>` is some integer.
You need to be mindful not to run commands outside of these workspace directories, since they have their own isolated
virtual environments.

**IMPORTANT**: One consequence of this is that you need to run `just install` before running other commands like
`just check` (since it is possible we haven't used this workspace directory in a long time and package dependencies may
have changed).
