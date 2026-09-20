"""Run blocking notification-gate reads off Textual's loop and message pump."""

from __future__ import annotations

from collections.abc import Callable


def run_off_loop[T](
    app: object,
    work: Callable[[], T],
    on_done: Callable[[T], None],
    *,
    name: str,
) -> None:
    """Run ``work`` on a thread, then ``on_done(result)`` on the event loop.

    The body is a pump-free task so a slow disk or journal read never blocks key
    events. Without a running loop (narrow unit-test callers) both steps run
    inline. A raising ``work`` is logged by the pump-free task machinery and
    ``on_done`` is skipped.
    """
    import asyncio

    from ...util.pump_tasks import spawn_pump_free_task

    async def _body() -> None:
        result = await asyncio.to_thread(work)
        on_done(result)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        on_done(work())
        return
    spawn_pump_free_task(
        app,
        _body(),
        name=name,
        registry_attr="_pump_free_async_tasks",
    )


__all__ = ["run_off_loop"]
