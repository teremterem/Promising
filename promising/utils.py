import asyncio

from promising import SyncUsageError


def assert_no_sync_usage_deadlock(*, loop: asyncio.AbstractEventLoop, message: str) -> None:
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop is loop:
        raise SyncUsageError(message)
