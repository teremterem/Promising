import asyncio
import concurrent.futures
import contextvars
import functools
from collections.abc import Callable
from typing import Any, Generic

from promising.decorator_support import _SETTINGS_AS_DICT_KEY, PromisingDecorator
from promising.errors import DecorationError
from promising.promise import Promise, get_active_promise, wrap_awaitable
from promising.sentinels import INHERIT, UNCHANGED, WHOLE_SUBTREE, Sentinel
from promising.types import DecoratableFunctionType, T_co


def function(
    func_or_method: DecoratableFunctionType | None = None,
    *,
    namespace: str | None = None,
    start_soon: bool | None | Sentinel = None,
    children_start_soon: bool | None | Sentinel = None,
    start_soon_default: bool | Sentinel = INHERIT,
    thread_pool: concurrent.futures.ThreadPoolExecutor | Sentinel = INHERIT,
    use_thread_pool: bool | None = None,
) -> "PromisingFunction[T_co] | Callable[Callable[..., T_co], PromisingFunction[T_co]]":
    """
    A decorator that turns a function into one that returns a ``Promise``
    instead of a plain result.

    When called, a decorated function creates and returns a ``Promise`` that
    encapsulates the function's execution. The ``Promise`` can be awaited
    multiple times without re-executing the underlying function.

    Promises automatically form parent-child hierarchies: if a decorated
    function is called during another ``Promise``'s execution, the newly
    created ``Promise`` becomes a child of the active one.

    Both sync and async functions are supported. Sync functions are
    transparently executed in a thread pool so they can participate in the
    async promise machinery.

    Works as a method decorator for instance methods, ``@classmethod``, and
    ``@staticmethod``.

    Decorated functions may return other awaitables or ``Promise`` objects
    (e.g. by calling other decorated functions) instead of concrete values. If
    the return value is an awaitable that is not already a ``Promise``, it is
    automatically wrapped in a child ``Promise`` of the current one, inheriting
    settings (``thread_pool``, ``start_soon_default``, etc.) through the
    standard ``Promise`` inheritance mechanism. When the resulting ``Promise``
    is awaited (or resolved via ``.sync()``), nested Promises (non-Promise
    awaitables are auto-wrapped into Promises by ``set_result``) are
    automatically unpacked recursively until a concrete, non-Promise value is
    reached. To unpack only one level, use ``unpack_once()`` or
    ``unpack_once_sync()`` instead.

    Inside a decorated function body, the following utilities are available:

    - **Consuming other promises from sync functions:** sync decorated
      functions run in a thread pool and can call ``.sync()`` on other
      ``Promise`` objects to block until their result is available. Async
      decorated functions simply ``await`` other promises as usual.
    - **Waiting for child promises:** call ``await promising.await_children()``
      (or ``promising.await_children_sync()`` from sync functions) to wait for
      all child promises spawned during the current function's execution. The
      same methods are available directly on the ``Promise`` object as well.
    - **Grouping children:** use ``promising.context`` (as a context manager or
      decorator) to create lightweight grouping nodes in the promise hierarchy
      without creating a full ``Promise``. This is useful for overriding
      settings for a block of code or for selectively awaiting a subset of
      children.

    Args:
        namespace: Optional namespace string for the resulting ``Promise``.
            Defaults to the wrapped function's ``__qualname__``.
        start_soon: Whether the ``Promise`` should start executing immediately
            upon creation. Defaults to ``None``, which defers to the parent's
            ``children_start_soon`` if enforced, otherwise falls back to
            ``start_soon_default``. ``INHERIT`` copies the parent's
            ``start_soon`` directly.
        children_start_soon: Whether child promises created during this
            ``Promise``'s execution should start executing immediately.
            Defaults to ``None`` (no enforcement), unlike
            ``PromisingContext`` where it defaults to ``INHERIT``.
            ``INHERIT`` copies the parent's ``children_start_soon`` setting.
        start_soon_default: Default ``start_soon`` value propagated to child
            promises. Defaults to ``INHERIT``, meaning the value is inherited
            from the parent ``Promise``.
        thread_pool: Thread pool executor used to run sync promising functions.
            ``INHERIT`` (default) inherits from the parent context, falling
            back to ``PROMISING_DEFAULT`` at the root. ``PROMISING_DEFAULT``
            uses ``Defaults.PROMISING_THREAD_POOL``. ``ASYNCIO_DEFAULT`` passes
            ``None`` to ``run_in_executor``, letting the event loop use its own
            default executor. A concrete ``ThreadPoolExecutor`` instance can
            also be provided. Only relevant for sync functions — async
            functions always run on the event loop regardless.
        use_thread_pool: Whether to run the sync function in a thread pool
            executor. ``True`` (recommended for most cases) runs the function
            in a thread pool so CPU-heavy workloads don't block the event loop
            thread. ``False`` runs the sync function directly on the event loop
            thread. **Warning:** when ``use_thread_pool=False``, calling
            ``sync()`` or ``await_children_sync()`` from within the function
            will raise ``SyncUsageError`` because those calls would deadlock
            the event loop.

            This parameter is **required** for sync functions — omitting it
            will raise ``DecorationError``. This is by design: the user should
            make a conscious decision about thread pool usage for each specific
            sync function.

            This parameter is **disallowed** for async functions — passing it
            will raise ``DecorationError``. Async functions always run on the
            event loop regardless of this setting.

            Unlike ``thread_pool``, this parameter is intentionally not
            inheritable through the context hierarchy — it must be set
            per-function at decoration time. This is by design: running sync
            functions on the event loop thread is problematic for CPU-bound
            workloads (it blocks the loop), so the user should make a conscious
            decision for each specific case rather than blanket-disabling
            thread pools for an entire subtree.
    """
    if func_or_method is None:
        # The decorator was used with arguments
        def _decorator(f_or_m: Callable[..., T_co]) -> PromisingFunction[T_co]:
            return PromisingFunction[T_co](
                f_or_m,
                namespace=namespace,
                start_soon=start_soon,
                children_start_soon=children_start_soon,
                start_soon_default=start_soon_default,
                thread_pool=thread_pool,
                use_thread_pool=use_thread_pool,
            )

        return _decorator

    # The decorator was used either without arguments or as a direct function
    # call
    return PromisingFunction[T_co](
        func_or_method,
        namespace=namespace,
        start_soon=start_soon,
        children_start_soon=children_start_soon,
        start_soon_default=start_soon_default,
        thread_pool=thread_pool,
        use_thread_pool=use_thread_pool,
    )


class PromisingFunction(PromisingDecorator, Generic[T_co]):
    """Callable wrapper created by ``@promising.function``. See
    :func:`promising.function` for usage details."""

    # A magic marker for `asyncio.iscoroutinefunction()` to always recognize
    # promising functions as coroutine functions (regardless of the logic that
    # exists in `DecoratorSupport._update_wrapper()`, since promising functions
    # always return awaitable Promises, even when they decorate non-async
    # functions)
    _is_coroutine = asyncio.coroutines._is_coroutine

    def __init__(
        self,
        func_or_method: DecoratableFunctionType,
        *,
        namespace: str | None = None,
        start_soon: bool | None | Sentinel = None,
        children_start_soon: bool | None | Sentinel = None,
        start_soon_default: bool | Sentinel = INHERIT,
        thread_pool: concurrent.futures.ThreadPoolExecutor | Sentinel = INHERIT,
        use_thread_pool: bool | None = None,
    ) -> None:
        super().__init__(
            func_or_method,
            namespace=namespace,
            children_start_soon=children_start_soon,
            start_soon_default=start_soon_default,
            thread_pool=thread_pool,
        )
        self.start_soon = start_soon
        self.use_thread_pool = self._validate_use_thread_pool(use_thread_pool)

        # TODO Make sure to use `typing.get_type_hints()` to resolve postponed
        #  type hints correctly, when you implement input params as Promises.
        # TODO Safeguard against the wrapped function accepting keyword
        #  arguments that are reserved to configure the Promise (`start_soon`,
        #  `children_start_soon`, `start_soon_default`):
        #  https://github.com/teremterem/Promising/pull/52#discussion_r2834995579

    def __call__(
        self,
        *args: Any,
        namespace: str | None | Sentinel = UNCHANGED,
        start_soon: bool | None | Sentinel = UNCHANGED,
        children_start_soon: bool | None | Sentinel = UNCHANGED,
        start_soon_default: bool | Sentinel = UNCHANGED,
        thread_pool: concurrent.futures.ThreadPoolExecutor | Sentinel = UNCHANGED,
        use_thread_pool: bool | Sentinel = UNCHANGED,
        **kwargs: Any,
    ) -> Promise[T_co]:
        """
        Call the wrapped function and return a ``Promise`` for its result.

        Creates a ``Promise`` that wraps the function's execution (running
        sync functions in a thread pool automatically).

        The ``namespace``, ``start_soon``, ``children_start_soon``,
        ``start_soon_default``, and ``thread_pool``
        parameters can be passed as keyword arguments to override the
        values set on the ``PromisingFunction`` at decoration time. To
        use the decorator-level values, simply omit these keyword
        arguments or pass ``UNCHANGED`` — both are equivalent. Passing
        None explicitly will still override them (None is
        itself a valid value with its own semantics in ``Promise``).

        For sync functions, ``use_thread_pool`` can also be overridden
        at call time. For async functions, passing ``use_thread_pool``
        at call time will raise ``DecorationError``.

        Args:
            *args: Positional arguments forwarded to the wrapped function.
            **kwargs: Keyword arguments forwarded to the wrapped function.
                The following keyword arguments are intercepted and not
                forwarded:

                - **namespace** — Namespace string for the resulting
                  ``Promise``.
                - **start_soon** — Whether the ``Promise`` should start
                  executing immediately upon creation.
                - **children_start_soon** — Default ``start_soon`` value
                  enforced on child ``Promise`` objects created during
                  this ``Promise``'s execution.
                - **start_soon_default** — Local override for the global
                  ``START_SOON_DEFAULT``.
                - **thread_pool** — Thread pool executor for sync
                  functions. See ``promising.function`` for details.
                - **use_thread_pool** — Whether to run a sync function
                  in a thread pool executor (sync functions only). See
                  ``promising.function`` for details.

        Returns:
            A ``Promise`` that will resolve to the wrapped function's return
            value.
        """
        settings_as_dict = kwargs.pop(_SETTINGS_AS_DICT_KEY, {})

        if start_soon is not UNCHANGED:
            settings_as_dict["start_soon"] = start_soon
        if use_thread_pool is not UNCHANGED:
            settings_as_dict["use_thread_pool"] = self._validate_use_thread_pool(use_thread_pool)

        return super().__call__(
            *args,
            namespace=namespace,
            children_start_soon=children_start_soon,
            start_soon_default=start_soon_default,
            thread_pool=thread_pool,
            **kwargs,
            **{_SETTINGS_AS_DICT_KEY: settings_as_dict},
        )

    def run(
        self,
        *args: Any,
        namespace: str | None | Sentinel = UNCHANGED,
        start_soon: bool | None | Sentinel = UNCHANGED,
        children_start_soon: bool | None | Sentinel = UNCHANGED,
        start_soon_default: bool | Sentinel = UNCHANGED,
        thread_pool: concurrent.futures.ThreadPoolExecutor | Sentinel = UNCHANGED,
        use_thread_pool: bool | Sentinel = UNCHANGED,
        await_children: bool | Sentinel = WHOLE_SUBTREE,
        **kwargs: Any,
    ) -> T_co:
        """
        Top-level entrypoint for running a decorated function
        from non-async code — analogous to ``asyncio.run()``.
        Calls ``asyncio.run()`` on ``protected_run()``, which
        means it creates its own event loop, awaits the result,
        and by default awaits all children recursively.

        This is **not** the same as ``promise.sync()``:
        ``.sync()`` is for consuming a promise's result from
        within a sync promising function that already runs
        inside an event loop (in a thread pool), whereas
        ``.run()`` is for starting the whole promise tree from
        scratch.

        Args:
            *args: Positional arguments forwarded to the
                wrapped function.
            **kwargs: Keyword arguments forwarded to the
                wrapped function.
            namespace: Override for the ``Promise`` namespace.
            start_soon: Override for eager/deferred execution.
            children_start_soon: Override for child execution
                policy.
            start_soon_default: Override for the global
                ``start_soon`` default.
            thread_pool: Override for the thread pool executor.
            use_thread_pool: Override for thread pool usage
                (sync functions only).
            await_children: Whether to await children after the
                promise completes. ``WHOLE_SUBTREE`` (default)
                awaits the entire subtree, ``True`` awaits
                direct children only, ``False`` skips child
                awaiting.

        Returns:
            The fully unpacked result of the ``Promise``.

        Raises:
            RuntimeError: If called from within an already-running event
                loop (e.g., inside another async function).
        """
        return asyncio.run(
            self.protected_run(
                *args,
                namespace=namespace,
                start_soon=start_soon,
                children_start_soon=children_start_soon,
                start_soon_default=start_soon_default,
                thread_pool=thread_pool,
                use_thread_pool=use_thread_pool,
                await_children=await_children,
                **kwargs,
            )
        )

    async def protected_run(
        self,
        *args: Any,
        namespace: str | None | Sentinel = UNCHANGED,
        start_soon: bool | None | Sentinel = UNCHANGED,
        children_start_soon: bool | None | Sentinel = UNCHANGED,
        start_soon_default: bool | Sentinel = UNCHANGED,
        thread_pool: concurrent.futures.ThreadPoolExecutor | Sentinel = UNCHANGED,
        use_thread_pool: bool | Sentinel = UNCHANGED,
        await_children: bool | Sentinel = WHOLE_SUBTREE,
        **kwargs: Any,
    ) -> T_co:
        """
        Returns a **coroutine** (not a ``Promise``), making it
        safe to pass to ``asyncio.run()`` — unlike calling the
        decorated function directly, which would construct a
        ``Promise`` (an ``asyncio.Future`` subclass) before the
        event loop exists and fail.

        Inside, the coroutine calls the decorated function,
        awaits the resulting ``Promise``, and by default recursively
        awaits its children. Used by ``run()`` internally.

        Args:
            *args: Positional arguments forwarded to the
                wrapped function.
            **kwargs: Keyword arguments forwarded to the
                wrapped function.
            namespace: Override for the ``Promise`` namespace.
            start_soon: Override for eager/deferred execution.
            children_start_soon: Override for child execution
                policy.
            start_soon_default: Override for the global
                ``start_soon`` default.
            thread_pool: Override for the thread pool executor.
            use_thread_pool: Override for thread pool usage
                (sync functions only).
            await_children: Whether to await children after the
                promise completes. ``WHOLE_SUBTREE`` (default)
                awaits the entire subtree, ``True`` awaits
                direct children only, ``False`` skips child
                awaiting.

        Returns:
            The fully unpacked result of the ``Promise``.
        """
        if await_children is not WHOLE_SUBTREE and not isinstance(await_children, bool):
            raise ValueError(f"Invalid await_children={await_children!r}; expected WHOLE_SUBTREE, True, or False")

        promise = self(
            *args,
            namespace=namespace,
            start_soon=start_soon,
            children_start_soon=children_start_soon,
            start_soon_default=start_soon_default,
            thread_pool=thread_pool,
            use_thread_pool=use_thread_pool,
            **kwargs,
        )
        try:
            return await promise
        finally:
            # TODO What about await_children's `unpack_promises_fully` ?
            if await_children is WHOLE_SUBTREE:
                await promise.await_children(whole_subtree=True)
            elif await_children:
                await promise.await_children(whole_subtree=False)

    def _call_wrapped(self, *args: Any, settings_as_dict: dict[str, Any], **kwargs: Any) -> Any:
        # TODO Develop a convenient and idiomatic way (whatever that would
        #  mean) of serializing/deserializing the arguments and ensuring
        #  immutability

        if self._is_wrapped_async:
            # The wrapped function is already async, so we can just call it
            # directly
            coro = self._wrapped_as_callable(*args, **kwargs)

        elif settings_as_dict.get("use_thread_pool", self.use_thread_pool):
            # Run the sync function in a thread pool executor
            @functools.wraps(self.__wrapped__)
            async def _sync_to_async() -> T_co:
                # Get the event loop from the active promise that is running
                # this async wrapper function
                active_promise = get_active_promise()
                executor = active_promise.get_thread_pool_executor()
                # Copy the current context so that ContextVars (in particular
                # Promise._current) are accessible inside the executor thread
                ctx = contextvars.copy_context()
                return await active_promise.loop.run_in_executor(
                    executor,
                    functools.partial(ctx.run, self._wrapped_as_callable, *args, **kwargs),
                )

            coro = _sync_to_async()

        else:
            # Run the sync function directly on the event loop thread
            @functools.wraps(self.__wrapped__)
            async def _sync_inline() -> T_co:
                return self._wrapped_as_callable(*args, **kwargs)

            coro = _sync_inline()

        return wrap_awaitable(
            namespace=settings_as_dict.get("namespace", self.namespace),
            awaitable=coro,
            start_soon=settings_as_dict.get("start_soon", self.start_soon),
            children_start_soon=settings_as_dict.get("children_start_soon", self.children_start_soon),
            start_soon_default=settings_as_dict.get("start_soon_default", self.start_soon_default),
            thread_pool=settings_as_dict.get("thread_pool", self.thread_pool),
        )

    def _validate_use_thread_pool(self, use_thread_pool: bool | None) -> bool | None:
        func_name = getattr(self.__wrapped__, "__qualname__", None) or getattr(
            self.__wrapped__, "__name__", repr(self.__wrapped__)
        )
        if self._is_wrapped_async:
            if use_thread_pool is not None:
                raise DecorationError(
                    f"`use_thread_pool` cannot be set for async function "
                    f"'{func_name}' — it is only applicable to sync functions. "
                    f"Async functions always run on the event loop regardless."
                )
        elif use_thread_pool is None:
            raise DecorationError(
                f"Sync function '{func_name}' requires an explicit "
                f"`use_thread_pool` setting. Set `use_thread_pool=True` "
                f"(recommended for most cases, so CPU-heavy workloads "
                f"don't block the event loop thread) or "
                f"`use_thread_pool=False` on the decorator."
            )
        return use_thread_pool
