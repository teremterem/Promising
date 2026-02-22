import asyncio
import concurrent.futures
from typing import Any


class AsyncioBackedConcurrentFuture(concurrent.futures.Future):
    """
    A thread-safe concurrent.futures.Future backed by an asyncio Future.

    This class provides a bridge between asyncio-based Futures and the
    concurrent.futures interface, allowing asyncio Futures to be used in
    multi-threaded contexts while maintaining proper result/exception
    synchronization.

    Args:
        asyncio_future: The asyncio Future instance that backs this concurrent
            Future.
    """

    def __init__(self, asyncio_future: asyncio.Future[Any]) -> None:
        super().__init__()
        self._asyncio_future = asyncio_future

    def result(self, timeout: float | None = None) -> Any:
        """
        Get the result of the asyncio Future.

        This method blocks until the underlying asyncio Future is done and ensures
        that the asyncio Future's result is properly consumed (asyncio will not issue
        a warning about the asyncio Future not having been awaited for).

        Args:
            timeout: Maximum time to wait for the result in seconds.

        Returns:
            The result value from the asyncio Future.

        Raises:
            concurrent.futures.TimeoutError: If timeout expires before
                completion.
            Exception: Any exception that occurred during asyncio Future execution.
        """
        try:
            # Let's block until the underlying asyncio Future is done (it will
            # set the result/exception on this concurrent Future)
            result = super().result(timeout=timeout)
        finally:
            # Let's also read the result from the asyncio Future directly, so
            # it knows that its result has been consumed and there is no need
            # to issue a warning about the asyncio Future not having been
            # awaited for (which, by this point, would be done already)
            try:
                self._asyncio_future.result()
            except BaseException:  # noqa: BLE001 (blind-except)
                # Suppress the error if any - if there's an error, it should
                # come from super().result(), not from here
                pass
        # For consistency, let's return the result from this concurrent Future,
        # even though it's going to be the same as the result from the asyncio
        # Future
        return result

    def exception(self, timeout: float | None = None) -> BaseException | None:
        """
        Get the exception that occurred during asyncio Future execution, if
        any.

        This method blocks until the underlying asyncio Future is done and
        ensures that the asyncio Future's exception is properly consumed
        (asyncio will not issue a warning about the exception not having
        been retrieved from the asyncio Future).

        Args:
            timeout: Maximum time to wait for completion in seconds.

        Returns:
            The exception that occurred, or None if the asyncio Future
            completed successfully.

        Raises:
            concurrent.futures.TimeoutError: If timeout expires before
                completion.
        """
        try:
            # Let's block until the underlying asyncio Future is done (it will
            # set the result/exception on this concurrent Future)
            exception = super().exception(timeout=timeout)
        finally:
            # Let's also read the exception from the asyncio Future directly,
            # so it knows that its exception has been consumed and there is no
            # need to issue a warning about the exception never being retrieved
            # from the asyncio Future (which, by this point, would be done
            # already)
            try:
                self._asyncio_future.exception()
            except BaseException:  # noqa: BLE001 (blind-except)
                # Suppress the error if any - if there's an error, it should
                # come from super().exception(), not from here
                pass
        # For consistency, let's return the exception from this concurrent
        # Future, even though it's going to be the same as the exception from
        # the asyncio Future
        return exception
