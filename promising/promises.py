import asyncio
import contextvars
import itertools
from asyncio import AbstractEventLoop, Future, Task, coroutines
from contextvars import ContextVar
from types import TracebackType
from typing import Any, Coroutine, Generator, Generic, Optional
from weakref import WeakSet

from promising.configs import PromiseConfig
from promising.errors import NoCurrentPromiseError, NoParentPromiseError
from promising.sentinels import NOT_SET, Sentinel
from promising.types import T_co


_promise_name_counter = itertools.count(1)


def get_current_promise(raise_if_none: bool = True) -> Optional["Promise[Any]"]:
    return Promise.get_current(raise_if_none=raise_if_none)


class Promise(Future, Generic[T_co]):
    _current: ContextVar[Optional["Promise[Any]"]] = ContextVar("Promise._current", default=None)
    _previous_token: Optional[contextvars.Token] = None

    _task: Optional[Task[T_co]] = None

    # TODO Support cancellation of the whole Promise tree

    # TODO Expose it as concurrent.Future so it could be accessed from threads outside of the event loop
    #  (e.g. as_concurrent_future() method ?)

    def __init__(
        self,
        coro: Optional[Coroutine[Any, Any, T_co]] = None,
        *,
        loop: Optional[AbstractEventLoop] = None,
        name: Optional[str] = None,
        parent: Optional["Promise[Any]"] | Sentinel = NOT_SET,
        config: Optional[PromiseConfig] = None,
        # TODO Support optional `children_config` too
        start_soon: bool | Sentinel = NOT_SET,
        make_parent_wait: bool | Sentinel = NOT_SET,
        config_inheritable: bool | Sentinel = NOT_SET,
        prefill_result: Optional[T_co] | Sentinel = NOT_SET,
        prefill_exception: Optional[BaseException] = None,
    ):
        # TODO Fix the following linting error:
        # pylint: disable=too-many-branches

        if coro is None and prefill_result is NOT_SET and prefill_exception is None:
            raise ValueError("Cannot create a Promise without a coroutine or prefilled result/exception")
        if coro is not None and (prefill_result is not NOT_SET or prefill_exception is not None):
            raise ValueError("Cannot provide both 'coro' and 'prefill_result' or 'prefill_exception' parameters")
        if coro is not None and not coroutines.iscoroutine(coro):
            raise TypeError(f"Promise must be created with a coroutine. Got {type(coro)}.")
        if prefill_result is not NOT_SET and prefill_exception is not None:
            raise ValueError("Cannot provide both 'prefill_result' and 'prefill_exception' parameters")

        # TODO Does it make sense to set the parent Promise upon creation or should it be done upon "activation" ?
        # TODO What to do about tracing the real way Promise calls are nested ? Maintain _real_parent that is set upon
        #  Promise activation and is not affected by manual choice of a parent or by the loop mismatch ?
        if parent is NOT_SET:
            self._parent = self.get_current(raise_if_none=False)
        else:
            self._parent = parent

        self._children: WeakSet[Promise[Any]] = WeakSet()

        if self._parent is not None:
            if loop is None:
                loop = self._parent._loop
            elif loop is not self._parent._loop:
                # TODO Raise a ValueError instead of setting the parent to None
                self._parent = None

        if self._parent is not None:
            self._parent._children.add(self)

        super().__init__(loop=loop)

        if name is None:
            name = f"Promise-{next(_promise_name_counter)}"
        self._name = name

        self._config = self._init_config(
            config,
            start_soon=start_soon,
            make_parent_wait=make_parent_wait,
            config_inheritable=config_inheritable,
        )

        self._coro = coro
        if self._coro is None:
            if prefill_exception is None:
                self.set_result(prefill_result)
            else:
                self.set_exception(prefill_exception)

        elif self._config.is_start_soon():
            self._task = self._loop.create_task(self._afulfill(), name=self._name + "-Task")

    async def _afulfill(self) -> None:
        # TODO Raise an error if there is no coroutine
        if self.done():
            raise RuntimeError("Promise is already done")  # TODO Come up with a better error message

        try:
            async with self:  # Let's "activate" the Promise for the duration of the coroutine execution
                result = await self._coro
        except BaseException as exc:  # pylint: disable=broad-except
            self.set_exception(exc)
        else:
            self.set_result(result)

    def __await__(self) -> Generator[T_co, None, None]:
        if not self.done():
            if self._task is None:
                yield from self._afulfill().__await__()  # pylint: disable=no-member
            else:
                yield self._task
        return (yield from super().__await__())

    def _init_config(self, config: Optional[PromiseConfig], **kwargs) -> PromiseConfig:
        # TODO If config is provided and any of the kwarg values are not NOT_SET, raise an error

        if config is not None:
            return config

        if self._parent is not None and all(value is NOT_SET for value in kwargs.values()):
            return self._parent.get_config().find_inheritable_config()

        return PromiseConfig(**kwargs)

    @classmethod
    def get_current(cls, *, raise_if_none: bool = True) -> Optional["Promise[Any]"]:
        current = cls._current.get()
        if raise_if_none and current is None:
            raise NoCurrentPromiseError("No current Promise found")
        return current

    def get_parent(self, *, raise_if_none: bool = True) -> Optional["Promise[Any]"]:
        if raise_if_none and self._parent is None:
            raise NoParentPromiseError("No parent Promise found")
        return self._parent

    def is_active(self) -> bool:
        return self._previous_token is not None

    def get_name(self) -> str:
        return self._name

    def get_config(self) -> PromiseConfig:
        return self._config

    def get_pending_children(self) -> set["Promise[Any]"]:
        # TODO Copy the explanation from asyncio.tasks::all_children() here
        i = 0
        while True:
            try:
                children = list(self._children)
            except RuntimeError:
                i += 1
                if i > 1000:
                    raise
            else:
                return {child for child in children if not child.done()}

    def activate(self) -> bool:
        # TODO What's the point of this method being public ? Can it ever be called directly ?
        #  We'll figure it out when we try to base `async with MiniAgents():` on the Promise.
        # TODO Raise an error if the promise is already active
        self._previous_token = self._current.set(self)
        return True

    async def afinalize(self) -> None:
        # TODO What's the point of this method being public ? Can it ever be called directly ?
        #  We'll figure it out when we try to base `async with MiniAgents():` on the Promise.
        # TODO Test what happens if afinalize() is called in the context where no promise is active
        # TODO Test what happens if afinalize() is called in the context of a child promise
        # TODO Test what happens if afinalize() is called in the context where this promise is not present even as a
        #  parent, grandparent, etc.

        # TODO Move this to wait_for_children() public method
        promises_to_await = [
            child for child in self.get_pending_children() if child.get_config().is_make_parent_wait()
        ]
        if promises_to_await:
            # TODO Do errors disappear from stdout/stderr when they are "gathered" like this ? Do they make it to
            #  stdout/stderr only when the whole python process exits ? We should somehow show the errors to the user
            #  as soon as they happen (for all children, not just the ones that make the parent wait).
            await asyncio.gather(*promises_to_await, return_exceptions=True)

        self._current.reset(self._previous_token)
        self._previous_token = None

    async def __aenter__(self) -> "Promise[Any]":
        self.activate()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        # TODO Do anything with errors raised from within the `async with` block ?
        await self.afinalize()
