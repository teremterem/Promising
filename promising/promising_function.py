import concurrent.futures
import contextvars
import functools
from collections.abc import Callable
from typing import Any, Generic

from promising.promise import Promise, get_active_promise
from promising.sentinels import INHERIT, NOT_SET, Sentinel
from promising.types import DecoratableFunctionType, T_co
from promising.utils import DecoratorSupport, is_func_or_method_async


def function(
    func_or_method: DecoratableFunctionType | Sentinel = NOT_SET,
    *,
    namespace: str | Sentinel = NOT_SET,
    start_soon: bool | Sentinel = NOT_SET,
    children_start_soon: bool | Sentinel = NOT_SET,
    start_soon_default: bool | Sentinel = INHERIT,
    thread_pool: concurrent.futures.ThreadPoolExecutor | Sentinel = INHERIT,
    use_thread_pool: bool = True,
) -> "PromisingFunction[T_co] | Callable[Callable[..., T_co], PromisingFunction[T_co]]":
    """
    A decorator that turns a function into one that returns a ``Promise``
    instead of a plain result.

    When called, a decorated function creates and returns a ``Promise``
    that encapsulates the function's execution. The ``Promise`` can be
    awaited multiple times without re-executing the underlying function.

    Promises automatically form parent-child hierarchies: if a decorated
    function is called during another ``Promise``'s execution, the newly
    created ``Promise`` becomes a child of the active one.

    Both sync and async functions are supported. Sync functions are
    transparently executed in a thread pool so they can participate in
    the async promise machinery.

    Works as a method decorator for instance methods, ``@classmethod``,
    and ``@staticmethod``.

    Decorated functions may return other awaitables or ``Promise`` objects
    (e.g. by calling other decorated functions) instead of concrete values.
    If the return value is an awaitable that is not already a ``Promise``,
    it is automatically wrapped in a child ``Promise`` of the current one,
    inheriting settings (``thread_pool``, ``start_soon_default``, etc.)
    through the standard ``Promise`` inheritance mechanism. When the
    resulting ``Promise`` is awaited (or resolved via ``.sync()``), nested
    awaitables are automatically unpacked recursively until a concrete,
    non-awaitable value is reached. To unpack only one level, use
    ``unpack_once()`` or ``unpack_once_sync()`` instead.

    Inside a decorated function body, the following utilities are
    available:

    - **Consuming other promises from sync functions:** sync decorated
      functions run in a thread pool and can call ``.sync()`` on other
      ``Promise`` objects to block until their result is available.
      Async decorated functions simply ``await`` other promises as usual.
    - **Waiting for child promises:** call
      ``await promising.await_children()`` (or
      ``promising.await_children_sync()`` from sync functions) to wait
      for all child promises spawned during the current function's
      execution. The same methods are available directly on the
      ``Promise`` object as well.
    - **Grouping children:** use ``promising.context`` (as a context
      manager or decorator) to create lightweight grouping nodes in
      the promise hierarchy without creating a full ``Promise``. This
      is useful for overriding settings for a block of code or for
      selectively awaiting a subset of children.

    Args:
        namespace: Optional namespace string for the resulting ``Promise``.
            Defaults to the wrapped function's ``__qualname__``.
        start_soon: Whether the ``Promise`` should start executing
            immediately upon creation. Defaults to ``NOT_SET``, which
            defers to the parent ``Promise``'s configuration.
        children_start_soon: Whether child promises created during this
            ``Promise``'s execution should start executing immediately.
            Defaults to ``NOT_SET``.
        start_soon_default: Default ``start_soon`` value propagated to
            child promises. Defaults to ``INHERIT``, meaning the value
            is inherited from the parent ``Promise``.
        thread_pool: Thread pool executor used to run sync
            promising functions. ``INHERIT`` (default) inherits from
            the parent context, falling back to ``GLOBAL_DEFAULT``
            at the root. ``GLOBAL_DEFAULT`` uses
            ``Defaults.SYNC_THREAD_POOL``. ``ASYNCIO_DEFAULT``
            passes ``None`` to ``run_in_executor``, letting the
            event loop use its own default executor. A concrete
            ``ThreadPoolExecutor`` instance can also be provided.
            Only relevant for sync functions — async functions
            always run on the event loop regardless.
        use_thread_pool: Whether to run the sync function in a thread pool
            executor (default ``True``). When ``False``, the sync function
            runs directly on the event loop thread. This is only relevant
            for sync functions — async functions always run on the event
            loop regardless of this setting. **Warning:** when
            ``use_thread_pool=False``, calling ``sync()`` or
            ``await_children_sync()`` from within the function will raise
            ``SyncUsageError`` because those calls would deadlock the
            event loop.

            Unlike ``thread_pool``, this parameter is intentionally not
            inheritable through the context hierarchy — it must be set
            per-function at decoration or call time. This is by design:
            running sync functions on the event loop thread is
            problematic for CPU-bound workloads (it blocks the loop),
            so the user should make a conscious decision for each
            specific case rather than blanket-disabling thread pools
            for an entire subtree.
    """
    if func_or_method is NOT_SET:
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


class PromisingFunction(DecoratorSupport, Generic[T_co]):
    """Callable wrapper created by ``@promising.function``. See
    :func:`promising.function` for usage details."""

    def __init__(
        self,
        func_or_method: DecoratableFunctionType,
        *,
        namespace: str | Sentinel = NOT_SET,
        start_soon: bool | Sentinel = NOT_SET,
        children_start_soon: bool | Sentinel = NOT_SET,
        start_soon_default: bool | Sentinel = INHERIT,
        thread_pool: concurrent.futures.ThreadPoolExecutor | Sentinel = INHERIT,
        use_thread_pool: bool = True,
    ) -> None:
        super().__init__(func_or_method, namespace=namespace)
        self.start_soon = start_soon
        self.children_start_soon = children_start_soon
        self.start_soon_default = start_soon_default
        self.thread_pool = thread_pool
        self.use_thread_pool = use_thread_pool

        # TODO Make sure to use `get_type_hints()` instead of `__annotations__`
        #  to resolve postponed type hints correctly, when you implement input
        #  params as Promises.
        # TODO Safeguard against the wrapped function accepting keyword
        #  arguments that are reserved to configure the Promise (`start_soon`,
        #  `children_start_soon`, `start_soon_default`):
        #  https://github.com/teremterem/Promising/pull/52#discussion_r2834995579

    def __call__(
        self,
        *args: Any,
        namespace: str | Sentinel | None = None,
        start_soon: bool | Sentinel | None = None,
        children_start_soon: bool | Sentinel | None = None,
        start_soon_default: bool | Sentinel | None = None,
        thread_pool: concurrent.futures.ThreadPoolExecutor | Sentinel | None = None,
        use_thread_pool: bool | None = None,
        **kwargs: Any,
    ) -> Promise[T_co]:
        """
        Call the wrapped function and return a ``Promise`` for its result.

        Creates a ``Promise`` that wraps the function's execution (running
        sync functions in a thread pool automatically).

        The ``namespace``, ``start_soon``, ``children_start_soon``,
        ``start_soon_default``, ``thread_pool``, and ``use_thread_pool``
        parameters can be passed as keyword arguments to override the
        values set on the ``PromisingFunction`` at decoration time. To
        use the decorator-level values, simply omit these keyword
        arguments or pass ``None`` — both are equivalent. Passing
        ``NOT_SET`` explicitly will still override them (``NOT_SET`` is
        itself a valid value with its own semantics in ``Promise``).

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
                  in a thread pool executor. See ``promising.function``
                  for details.

        Returns:
            A ``Promise`` that will resolve to the wrapped function's
            return value.
        """
        if namespace is None:
            namespace = self.namespace
        if start_soon is None:
            start_soon = self.start_soon
        if children_start_soon is None:
            children_start_soon = self.children_start_soon
        if start_soon_default is None:
            start_soon_default = self.start_soon_default
        if thread_pool is None:
            thread_pool = self.thread_pool
        if use_thread_pool is None:
            use_thread_pool = self.use_thread_pool

        # TODO Develop a convenient and idiomatic way (whatever that would
        #  mean) of serializing/deserializing the arguments and ensuring
        #  immutability

        if is_func_or_method_async(self.__wrapped__):
            # The wrapped function is already async, so we can just call it
            # directly
            coro = self._wrapped_as_callable(*args, **kwargs)

        elif use_thread_pool:
            # Run the sync function in a thread pool executor
            @functools.wraps(self.__wrapped__)
            async def _sync_to_async() -> T_co:
                # Get the event loop from the active promise that is running
                # this async wrapper function
                active_promise = get_active_promise()
                loop = active_promise.get_loop()
                executor = active_promise.get_thread_pool_executor()
                # Copy the current context so that ContextVars (in particular
                # Promise._current) are accessible inside the executor thread
                ctx = contextvars.copy_context()
                return await loop.run_in_executor(
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

        return Promise[T_co](
            namespace=namespace,
            awaitable=coro,
            start_soon=start_soon,
            children_start_soon=children_start_soon,
            start_soon_default=start_soon_default,
            thread_pool=thread_pool,
        )
