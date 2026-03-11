I want to start having a single lumberjack chop handle all right to project spec files. This chop should know about most
of the common projects spec updates that need to happen and handle them on its own when at all possible. If some
external processes need custom rights then they have to request these rights through some sort of API and then the chop
should handle those rights and let the calling process know that the right has been done.

This is a large piece of work that should be split up into multiple phases. I'll let you decide how many phases to
create, but keep in mind that each phase will be run by a distinct claude instance.
