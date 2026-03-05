import contextvars
import functools
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Generic

from promising.promise import Promise, get_active_promise
from promising.sentinels import INHERIT, NOT_SET, Sentinel
from promising.types import DecoratableFunctionType, T_co
from promising.utils import DecoratorSupport, resolve_namespace

# TODO Allow overriding this executor in local promise configurations
# TODO What to do about potential deadlocks if recursive sync promises use up
#  the executor's thread pool (when each such promise waits for its children to
#  complete) ? Is setting `max_workers` to 128 just a provisional workaround,
#  and we need our own mechanism ? Or is it enough to issue a warning / throw
#  an error when the number of nested sync function calls approaches this
#  number ?
_sync_function_executor = ThreadPoolExecutor(max_workers=128)


def function(
    func_or_method: DecoratableFunctionType | None = None,
    *,
    namespace: str | None = None,
    start_soon: bool | Sentinel = NOT_SET,
    children_start_soon: bool | Sentinel = NOT_SET,
    start_soon_default: bool | Sentinel = INHERIT,
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
    ) -> None:
        super().__init__(func_or_method)
        self.namespace = namespace
        self.start_soon = start_soon
        self.children_start_soon = children_start_soon
        self.start_soon_default = start_soon_default

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

        # TODO Develop a convenient and idiomatic (whatever that would mean)
        #  way of serializing/deserializing the arguments and ensuring
        #  immutability

        if self._is_wrapped_async:
            coro = self._wrapped_as_callable(*args, **kwargs)
        else:

            @functools.wraps(self.__wrapped__)
            async def _sync_to_async() -> T_co:
                # Get the event loop from the active promise that is running
                # this async function
                loop = get_active_promise().get_loop()
                # Copy the current context so that ContextVars
                # (in particular Promise._current) are accessible
                # inside the executor thread
                ctx = contextvars.copy_context()
                return await loop.run_in_executor(
                    _sync_function_executor,
                    functools.partial(ctx.run, self._wrapped_as_callable, *args, **kwargs),
                )

            coro = _sync_to_async()

        return Promise[T_co](
            namespace=resolve_namespace(
                provided_explicitly=self.namespace,
                named_object_fallback=self.__wrapped__,
            ),
            coro=coro,
            start_soon=start_soon,
            children_start_soon=children_start_soon,
            start_soon_default=start_soon_default,
        )
