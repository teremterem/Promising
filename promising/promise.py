import asyncio
import concurrent.futures
import contextvars
import itertools
from asyncio import AbstractEventLoop, Future, Task, coroutines
from collections.abc import Coroutine, Generator
from contextvars import ContextVar
from typing import Any, Generic
from weakref import WeakSet

from promising.errors import NoCurrentPromiseError, NoParentPromiseError
from promising.sentinels import GLOBAL_DEFAULT, INHERIT, NOT_SET, Sentinel
from promising.types import T_co

_promise_name_counter = itertools.count(1)


def get_current_promise(*, raise_if_none: bool = True) -> "Promise[Any] | None":
    """
    Get the currently active Promise from context.

    Args:
        raise_if_none: If True, raises NoCurrentPromiseError when no active
            Promise is found.

    Returns:
        The currently active Promise instance, or None if no Promise is active
        and raise_if_none is False.

    Raises:
        NoCurrentPromiseError: If no active Promise is found and raise_if_none
            is True.
    """
    return Promise.get_current(raise_if_none=raise_if_none)


class Promise(Future, Generic[T_co]):
    """
    A Promise combines asyncio Future functionality with hierarchical context
    management.

    Promises extend asyncio Futures to provide:
    - Parent-child relationships between asynchronous operations
    - Configuration inheritance from parent Promises
    - Automatic child task management
    - Thread-safe concurrent.futures compatibility

    Parent-child relationships semantics:
    - If the coroutine of a Promise creates other Promise instances during its
      execution, those Promises are attached as children of that Promise.
    - The exact time when a child's execution starts, finishes, or when its
      resolution is triggered does not matter (it may occur outside of the
      parent's execution window); it is still registered as a child of the
      Promise whose coroutine created it.
    - If a parent is explicitly specified at creation time, that explicit
      parent takes precedence.

    Type Parameters:
        T_co: The covariant type of the Promise's result.

    Args:
        coro: The coroutine to execute. If None, the Promise must be prefilled
            with a result or exception.
        loop: The event loop to use. If not provided, inherits from the parent
            Promise. If no parent Promise, uses the current running loop. If
            provided explicitly and a parent Promise exists, must be the same
            event loop as the parent's loop.
        name: Human-readable name for the Promise. If None, generates a unique
            name ("Promise-N", where N is a number).
        parent: Parent Promise instance. If INHERIT, uses the currently
            active Promise as a parent. If None, the Promise has no
            parent.
        start_soon: Whether to start executing the coroutine
            immediately upon creation. NOT_SET (default) defers to
            the parent's children_start_soon_by_default if that is
            enforced (i.e. set to a concrete bool), otherwise falls
            back to everything_starts_soon_by_default. INHERIT copies
            the parent's start_soon directly (or falls back to
            everything_starts_soon_by_default if no parent).
        children_start_soon_by_default: Default start_soon value
            enforced on child Promises that leave start_soon as
            NOT_SET. NOT_SET (default) means no enforcement. INHERIT
            copies the parent's children_start_soon_by_default (or
            falls back to everything_starts_soon_by_default if no
            parent).
        everything_starts_soon_by_default: Local override for the
            global EVERYTHING_STARTS_SOON_BY_DEFAULT. INHERIT
            (default) propagates from the parent (or reads the global
            if no parent). GLOBAL_DEFAULT reads the current global setting
            without inheriting.
        prefill_result: Pre-set result value. Cannot be combined with coro or
            prefill_exception.
        prefill_exception: Pre-set exception. Cannot be combined with coro or
            prefill_result.

    Raises:
        ValueError: If invalid parameter combinations are provided. See
            parameter descriptions above.
        TypeError: If coro is not a coroutine when provided.
    """

    _current: ContextVar["Promise[Any] | None"] = ContextVar("Promise._current", default=None)

    _previous_token: contextvars.Token | None
    _task: Task[T_co] | None

    # TODO [ALMOST READY] Support cancellation of the whole Promise tree
    # TODO Would it make sense to implement this get_state() method which would
    #  return either NOT_STARTED, STARTED, DONE or FAILED sentinels ? (Also,
    #  remember that at the very least, Future already has done() method.)

    def __init__(
        self,
        coro: Coroutine[Any, Any, T_co] | None = None,
        *,
        loop: AbstractEventLoop | None = None,
        name: str | None = None,
        parent: "Promise[Any] | Sentinel | None" = INHERIT,
        start_soon: bool | Sentinel = NOT_SET,
        children_start_soon_by_default: bool | Sentinel = NOT_SET,
        everything_starts_soon_by_default: bool | Sentinel = INHERIT,
        prefill_result: T_co | Sentinel | None = NOT_SET,
        # TODO Use NOT_SET instead of None below as well, for consistency ?
        prefill_exception: BaseException | None = None,
    ) -> None:
        self._previous_token = None
        self._task = None

        if parent is INHERIT:
            self._parent = self.get_current(raise_if_none=False)
        elif parent is None or isinstance(parent, Promise):
            self._parent = parent
        else:
            raise ValueError(
                f"`parent` must be either INHERIT, another Promise or None, but `{type(parent)}` was given instead"
            )

        self._resolve_everything_starts_soon_by_default(everything_starts_soon_by_default)
        self._resolve_start_soon(start_soon)
        self._resolve_children_start_soon_by_default(children_start_soon_by_default)

        if self._parent is not None:
            if loop is None:
                loop = self._parent._loop
            elif loop is not self._parent._loop:
                # TODO Is this actually critical ?
                raise ValueError("Parent and child Promises must share the same event loop")

        self._children: WeakSet[Promise[Any]] = WeakSet()
        if self._parent is not None:
            self._parent._children.add(self)

        self._concurrent_future = _PromiseBackedConcurrentFuture(self)

        super().__init__(loop=loop)

        if name is None:
            name = f"Promise-{next(_promise_name_counter)}"
        self._name = name

        self._coro = coro
        self._finish_initialization(
            prefill_result=prefill_result,
            prefill_exception=prefill_exception,
        )

    def _create_task(self) -> None:
        self._task = self._loop.create_task(self._afulfill(), name=self._name + "-Task")

    def set_result(self, result: T_co) -> None:
        """
        Set the result of the Promise. This method is not intended to be called
        directly by users; it is managed by the Promise's lifecycle.

        Also sets the result on the concurrent.futures.Future for thread
        compatibility (see as_concurrent_future() method).

        Args:
            result: The result value to set.
        """
        super().set_result(result)
        self._concurrent_future.set_result(result)

    def set_exception(self, exception: BaseException) -> None:
        """
        Set an exception on the Promise. This method is not intended to be
        called directly by users; it is managed by the Promise's lifecycle.

        Also sets the exception on the concurrent.futures.Future for thread
        compatibility (see as_concurrent_future() method).

        Args:
            exception: The exception to set.
        """
        super().set_exception(exception)
        self._concurrent_future.set_exception(exception)

    async def _afulfill(self) -> None:
        """
        Execute the Promise's coroutine and manage its lifecycle.

        This method:
        1. Activates the Promise as the current context
        2. Executes the coroutine
        3. Sets the result or exception

        Raises:
            RuntimeError: If the Promise is already done or has no coroutine.
        """
        if self.done():
            # Should not happen
            raise RuntimeError(f"An attempt was made to fulfill a Promise that is already done: {self.get_name()}")
        if self._coro is None:
            # Should not happen
            raise RuntimeError(f"An attempt was made to fulfill a Promise with no coroutine: {self.get_name()}")

        result = NOT_SET
        exception = NOT_SET

        self._activate()
        try:
            result = await self._coro
        except BaseException as exc:  # noqa: BLE001 (blind-except)
            exception = exc
        finally:
            try:
                await self._afinalize()
            finally:
                if exception is not NOT_SET:
                    self.set_exception(exception)
                else:
                    self.set_result(result)

    def __await__(self) -> Generator[Any, None, T_co]:
        """
        If the Promise hasn't started yet, start execution of the coro via
        _afulfill() and run it to completion. If already started via
        start_soon, wait for the existing task to complete.

        Returns:
            A generator for the await protocol that eventually returns the
            result of the Promise.
        """
        if self.done():
            return self.result()

        if self._task is None:
            self._create_task()

        yield from self._task
        return (yield from super().__await__())

    @classmethod
    def get_current(cls, *, raise_if_none: bool = True) -> "Promise[Any] | None":
        """
        Get the currently active Promise from context variables.

        Args:
            raise_if_none: If True, raises an exception when no active Promise
                is found.

        Returns:
            The currently active Promise, or None if none exists and
            raise_if_none is False.

        Raises:
            NoCurrentPromiseError: If no active Promise exists and
                raise_if_none is True.
        """
        current = cls._current.get()
        if raise_if_none and current is None:
            raise NoCurrentPromiseError("No active Promise found")
        return current

    def get_parent(self, *, raise_if_none: bool = True) -> "Promise[Any] | None":
        """
        Get the parent Promise of this Promise.

        Args:
            raise_if_none: If True, raises an exception when no parent exists.

        Returns:
            The parent Promise, or None if no parent exists and raise_if_none
            is False.

        Raises:
            NoParentPromiseError: If no parent exists and raise_if_none is
                True.
        """
        if raise_if_none and self._parent is None:
            raise NoParentPromiseError("No parent Promise found")
        return self._parent

    def get_name(self) -> str:
        """
        Get the human-readable name of this Promise.
        """
        return self._name

    def get_pending_children(self) -> set["Promise[Any]"]:
        """
        Get child Promises that haven't completed yet (provided they are still
        reachable and weren't garbage collected yet).

        Handles potential race conditions when iterating over the WeakSet of
        children by retrying if the set changes during iteration.

        Returns:
            Set of child Promises that are not done.

        Raises:
            RuntimeError: If unable to get a stable view of children after 1000
                attempts.
        """
        # # COPIED FROM asyncio.tasks::all_tasks():
        # Looping over a WeakSet (_all_tasks) isn't safe as it can be updated from another
        # thread while we do so. Therefore we cast it to list prior to filtering. The list
        # cast itself requires iteration, so we repeat it several times ignoring
        # RuntimeErrors (which are not very likely to occur). See issues 34970 and 36607 for
        # details.
        i = 0
        while True:
            try:
                # In `asyncio.tasks` it was `_all_tasks` instead of
                # `self._children`
                children = list(self._children)
            except RuntimeError:
                i += 1
                if i > 1000:  # noqa: PLR2004 (magic-value-comparison)
                    raise
            else:
                return {child for child in children if not child.done()}

    def as_concurrent_future(self) -> concurrent.futures.Future[T_co]:
        """
        Get a thread-safe concurrent.futures.Future view of this Promise.

        This allows the Promise to be used in multi-threaded contexts where
        concurrent.futures.Future objects are expected.

        Returns:
            A concurrent.futures.Future that mirrors this Promise's state.
        """
        return self._concurrent_future

    def _activate(self) -> None:
        """
        Activate this Promise by setting it as the current context.

        Stores the previous context token for later restoration.
        """
        self._previous_token = self._current.set(self)

    async def _afinalize(self) -> None:
        """
        Finalize the Promise execution by restoring context (removing this
        Promise from the context and restoring the previous value for the
        respective context var).
        """
        self._current.reset(self._previous_token)
        self._previous_token = None

    async def await_remaining_children(self, *, return_exceptions: bool = False) -> list[Any]:
        """
        Wait for child Promises to finish.
        """
        # TODO Make it possible to call this method from another thread
        # TODO Ideally, a warning (or an optional exception ?) should be issued
        #  if any of the children are configured with start_soon=False, because
        #  that would make it quite easy to introduce deadlocks.
        return await asyncio.gather(*self.get_pending_children(), return_exceptions=return_exceptions)

    def _resolve_everything_starts_soon_by_default(self, everything_starts_soon_by_default: bool | Sentinel) -> None:
        from promising import should_everything_start_soon_by_default  # noqa: PLC0415 (import-outside-top-level)

        if isinstance(everything_starts_soon_by_default, bool):
            # Concrete value was provided
            self._everything_starts_soon_by_default = everything_starts_soon_by_default
        elif everything_starts_soon_by_default is GLOBAL_DEFAULT:
            # Use the global default
            self._everything_starts_soon_by_default = should_everything_start_soon_by_default()
        elif everything_starts_soon_by_default is INHERIT:
            if self._parent is None:
                # Use the global default
                self._everything_starts_soon_by_default = should_everything_start_soon_by_default()
            else:
                # Inherit from the parent
                self._everything_starts_soon_by_default = self._parent._everything_starts_soon_by_default
        else:
            raise ValueError(
                "`everything_starts_soon_by_default` must be either GLOBAL_DEFAULT, INHERIT or a boolean value, "
                f"but `{type(everything_starts_soon_by_default)}` was given instead"
            )

    def _resolve_start_soon(self, start_soon: bool | Sentinel) -> None:
        if isinstance(start_soon, bool):
            # Concrete value was provided
            self._start_soon = start_soon
        elif start_soon is NOT_SET:
            if self._parent is not None and self._parent._children_start_soon_by_default is not NOT_SET:
                # The parent is enforcing this setting for its children
                self._start_soon = self._parent._children_start_soon_by_default
            else:
                # Use the default
                self._start_soon = self._everything_starts_soon_by_default
        elif start_soon is INHERIT:
            if self._parent is None:
                # Use the default
                self._start_soon = self._everything_starts_soon_by_default
            else:
                # Inherit from the parent
                self._start_soon = self._parent._start_soon
        else:
            raise ValueError(
                "`start_soon` must be either NOT_SET, INHERIT or a boolean value, "
                f"but `{type(start_soon)}` was given instead"
            )

    def _resolve_children_start_soon_by_default(self, children_start_soon_by_default: bool | Sentinel) -> None:
        if isinstance(children_start_soon_by_default, bool) or children_start_soon_by_default is NOT_SET:
            # Apart from the concrete value, we also want to allow
            # `self._children_start_soon_by_default` to stay as NOT_SET, so we
            # can later tell whether it is being enforced on children or not
            # (NOT_SET means "no enforcement").
            self._children_start_soon_by_default = children_start_soon_by_default
        elif children_start_soon_by_default is INHERIT:
            if self._parent is None:
                # Use the default
                self._children_start_soon_by_default = self._everything_starts_soon_by_default
            else:
                # Inherit from the parent
                self._children_start_soon_by_default = self._parent._children_start_soon_by_default
        else:
            raise ValueError(
                "`children_start_soon_by_default` must be either NOT_SET, INHERIT or a boolean value, "
                f"but `{type(children_start_soon_by_default)}` was given instead"
            )

    def _finish_initialization(
        self,
        *,
        prefill_result: T_co | Sentinel | None,
        prefill_exception: BaseException | None,
    ) -> None:
        if self._coro is None:
            if prefill_result is not NOT_SET and prefill_exception is not None:
                raise ValueError("Cannot provide both 'prefill_result' and 'prefill_exception' parameters")

            if prefill_result is not NOT_SET:
                self.set_result(prefill_result)
            elif prefill_exception is not None:
                self.set_exception(prefill_exception)

            else:
                raise ValueError("Cannot create a Promise without a coroutine or prefilled result/exception")
        else:
            if not coroutines.iscoroutine(self._coro):
                raise TypeError(f"Promise must be created with a coroutine. Got {type(self._coro)}.")
            if prefill_result is not NOT_SET or prefill_exception is not None:
                raise ValueError("Cannot provide both 'coro' and 'prefill_result' or 'prefill_exception' parameters")

            if self._start_soon:
                self._create_task()


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
