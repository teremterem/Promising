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
    TODO Finalize this docstring by explaining why we need the
     PromisingFunction wrapper at all. List the advantages it provides:

    - Decorated functions always return Promises.
    - Returned Promises can be awaited any number of times without
      re-executing the function.
    - TODO Should input parameters always be passed as promises as well ?
       All of them ? Only those, that were typed as `Promise` explicitly ?
    - Both, input parameters and results are strictly serializable and are
      serialized/deserialized in transit
    - All these interactions are stored/storable in graph databases, or any
      other kinds of databases or caches that can handle the data structures.
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
    # TODO Explain the idea behind parent-child relationships between Promise
    #  objects with respect to PromisingFunction calls

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
        # NOTE: Allows overriding the start_soon, children_start_soon, and
        # start_soon_default parameters from the PromisingFunction constructor
        # by passing them as keyword arguments to the call() method.
        # TODO Add the above info to a docstring. (Class docstring ? This
        #  method's docstring ?)
        # TODO Mention that the only way NOT to override the parameters is NOT
        #  to pass them into the call() method at all (passing NOT_SET will
        #  still override the parameters from the PromisingFunction
        #  constructor).
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
