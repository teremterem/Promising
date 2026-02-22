class _PromiseBackedConcurrentFuture(concurrent.futures.Future):
    """
    A thread-safe concurrent.futures.Future backed by a Promise.

    This class provides a bridge between asyncio-based Promises and the
    concurrent.futures interface, allowing Promises to be used in
    multi-threaded contexts while maintaining proper result/exception
    synchronization.

    Args:
        promise: The Promise instance that backs this concurrent future.
    """

    def __init__(self, promise: "Promise[Any]") -> None:
        super().__init__()
        self._promise = promise

    def result(self, timeout: float | None = None) -> Any:
        """
        Get the result of the Promise.

        This method blocks until the underlying Promise is done and ensures
        that the Promise's result is properly consumed (asyncio will not issue
        a warning about the Promise not having been awaited for).

        Args:
            timeout: Maximum time to wait for the result in seconds.

        Returns:
            The result value from the Promise.

        Raises:
            concurrent.futures.TimeoutError: If timeout expires before
                completion.
            Exception: Any exception that occurred during Promise execution.
        """
        try:
            # Let's block until the underlying Promise is done (it will set the
            # result/exception on this concurrent Future)
            result = super().result(timeout=timeout)
        finally:
            # Let's also read the result from the Promise directly, so it knows
            # that its result has been consumed and there is no need to issue a
            # warning about the Promise not having been awaited for (which, by
            # this point, would be done already)
            try:
                self._promise.result()
            except BaseException:  # noqa: BLE001 (blind-except)
                # Suppress the error if any - if there's an error, it should
                # come from super().result(), not from here
                pass
        # For consistency, let's return the result from this concurrent Future,
        # even though it's going to be the same as the result from the Promise
        return result

    def exception(self, timeout: float | None = None) -> BaseException | None:
        """
        Get the exception that occurred during Promise execution, if any.

        This method blocks until the underlying Promise is done and ensures
        that the Promise's exception is properly consumed (asyncio will not
        issue a warning about the exception not having been retrieved from the
        Promise).

        Args:
            timeout: Maximum time to wait for completion in seconds.

        Returns:
            The exception that occurred, or None if the Promise completed
            successfully.

        Raises:
            concurrent.futures.TimeoutError: If timeout expires before
                completion.
        """
        try:
            # Let's block until the underlying Promise is done (it will set
            # the result/exception on this concurrent Future)
            exception = super().exception(timeout=timeout)
        finally:
            # Let's also read the exception from the Promise directly, so it
            # knows that its exception has been consumed and there is no need
            # to issue a warning about the exception never being retrieved from
            # the Promise (which, by this point, would be done already)
            try:
                self._promise.exception()
            except BaseException:  # noqa: BLE001 (blind-except)
                # Suppress the error if any - if there's an error, it should
                # come from super().exception(), not from here
                pass
        # For consistency, let's return the exception from this concurrent
        # Future, even though it's going to be the same as the exception from
        # the Promise
        return exception
