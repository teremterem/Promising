import concurrent.futures
import contextvars
import functools
from collections.abc import Callable
from typing import Any, Generic

from promising.promise import Promise, get_active_promise
from promising.sentinels import INHERIT, NOT_SET, Sentinel
from promising.types import DecoratableFunctionType, T_co
from promising.utils import DecoratorSupport, resolve_namespace


def function(
    func_or_method: DecoratableFunctionType | None = None,
    *,
    namespace: str | None = None,
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
            # TODO TODO TODO Raise SyncUsageError on the blocking methods of
            #  as_concurrent_future() too
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


class PromisingFunction(DecoratorSupport, Generic[T_co]):
    """Callable wrapper created by ``@promising.function``. See
    :func:`promising.function` for usage details."""

    def __init__(
        self,
        func_or_method: DecoratableFunctionType,
        *,
        namespace: str | None = None,
        start_soon: bool | Sentinel = NOT_SET,
        children_start_soon: bool | Sentinel = NOT_SET,
        start_soon_default: bool | Sentinel = INHERIT,
        thread_pool: concurrent.futures.ThreadPoolExecutor | Sentinel = INHERIT,
        use_thread_pool: bool = True,
    ) -> None:
        super().__init__(func_or_method)
        self.namespace = namespace
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
        **kwargs: Any,
    ) -> Promise[T_co]:
        return self.call(*args, **kwargs)

    def call(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Promise[T_co]:
        """
        Call the wrapped function and return a ``Promise`` for its result.

        This is the core method that ``__call__`` delegates to. It creates
        a ``Promise`` that wraps the function's execution (running sync
        functions in a thread pool automatically).

        The ``start_soon``, ``children_start_soon``, and
        ``start_soon_default`` parameters can be passed as keyword
        arguments to override the values set on the ``PromisingFunction``
        at decoration time. To use the decorator-level values, simply
        omit these keyword arguments — passing ``NOT_SET`` explicitly
        will still override them (``NOT_SET`` is itself a valid value
        with its own semantics in ``Promise``).

        Args:
            *args: Positional arguments forwarded to the wrapped function.
            **kwargs: Keyword arguments forwarded to the wrapped function.
                The following keyword arguments are intercepted and not
                forwarded:

                - **start_soon** — Whether the ``Promise`` should start
                  executing immediately upon creation.
                - **children_start_soon** — Default ``start_soon`` value
                  enforced on child ``Promise`` objects created during
                  this ``Promise``'s execution.
                - **start_soon_default** — Local override for the global
                  ``START_SOON_DEFAULT``.
                - **thread_pool** — Thread pool executor for sync
                  functions. See ``promising.function`` for details.

        Returns:
            A ``Promise`` that will resolve to the wrapped function's
            return value.
        """
        start_soon = kwargs.pop(
            "start_soon",
            self.start_soon,
        )
        children_start_soon = kwargs.pop(
            "children_start_soon",
            self.children_start_soon,
        )
        start_soon_default = kwargs.pop(
            "start_soon_default",
            self.start_soon_default,
        )
        thread_pool = kwargs.pop(
            "thread_pool",
            self.thread_pool,
        )

        # TODO Develop a convenient and idiomatic (whatever that would mean)
        #  way of serializing/deserializing the arguments and ensuring
        #  immutability

        if self._is_wrapped_async:
            coro = self._wrapped_as_callable(*args, **kwargs)
        elif self.use_thread_pool:

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

            @functools.wraps(self.__wrapped__)
            async def _sync_inline() -> T_co:
                return self._wrapped_as_callable(*args, **kwargs)

            coro = _sync_inline()

        return Promise[T_co](
            namespace=resolve_namespace(
                provided_explicitly=self.namespace,
                named_object_fallback=self.__wrapped__,
            ),
            coro=coro,
            start_soon=start_soon,
            children_start_soon=children_start_soon,
            start_soon_default=start_soon_default,
            thread_pool=thread_pool,
        )
