I want to start having a single lumberjack chop handle all right to project spec files. This chop should know about most
of the common projects spec updates that need to happen and handle them on its own when at all possible. If some
external processes need custom rights then they have to request these rights through some sort of API and then the chop
should handle those rights and let the calling process know that the right has been done.

Additional requirements:

- The system must support both **synchronous** and **asynchronous** writes. Synchronous writes are where the caller
  submits a request and waits for the chop to complete the write and return a response. Asynchronous writes are where
  the caller submits a request and then continues with its work (or even terminates) without waiting for the chop to
  complete the write.
- The spec_writer chop must be **completely independent** of all other chops. Other chops that submit write requests
  must have a way to ensure they do not make duplicate requests (e.g., if a chop submits a write request on one tick but
  the spec_writer hasn't processed it yet by the next tick, the chop must not resubmit the same request). Make sure all
  such deduplication cases are handled properly.

This is a large piece of work that should be split up into multiple phases. I'll let you decide how many phases to
create, but keep in mind that each phase will be run by a distinct claude instance.
