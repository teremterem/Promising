from asyncio import AbstractEventLoop, Future, Task, coroutines
from contextvars import ContextVar
import itertools
from typing import Any, Coroutine, Generic, Optional
from weakref import WeakSet

from promising.configs import PromiseConfig
from promising.errors import NoCurrentPromiseError, NoParentPromiseError
from promising.sentinels import NOT_SET, Sentinel
from promising.types import T_co


_promise_name_counter = itertools.count(1)
# TODO Also maintain UUIDs for promises ?


def get_current_promise(raise_if_none: bool = True) -> Optional["Promise[Any]"]:
    # TODO Do we really need this function ?
    return Promise.get_current(raise_if_none=raise_if_none)


class Promise(Future, Generic[T_co]):
    _current: ContextVar[Optional["Promise[Any]"]] = ContextVar("Promise._current", default=None)

    _task: Optional[Task[T_co]] = None

    def __init__(
        self,
        coro: Optional[Coroutine[Any, Any, T_co]] = None,
        *,
        loop: Optional[AbstractEventLoop] = None,
        name: Optional[str] = None,
        parent: Optional["Promise[Any]"] = None,
        config: Optional[PromiseConfig] = None,
        start_soon: bool | Sentinel = NOT_SET,
        make_parent_wait: bool | Sentinel = NOT_SET,
        wrong_event_loop: bool | Sentinel = NOT_SET,
        config_inheritable: bool | Sentinel = NOT_SET,
        prefill_result: Optional[T_co] | Sentinel = NOT_SET,
        prefill_exception: Optional[BaseException] = None,
    ):
        if coro is not None and (prefill_result is not NOT_SET or prefill_exception is not None):
            raise ValueError("Cannot provide both 'coro' and 'prefill_result' or 'prefill_exception' parameters")
        if coro is not None and not coroutines.iscoroutine(coro):
            raise TypeError(f"Promise must be created with a coroutine. Got {type(coro)}.")
        if prefill_result is not NOT_SET and prefill_exception is not None:
            raise ValueError("Cannot provide both 'prefill_result' and 'prefill_exception' parameters")

        # TODO Does it make sense to set the parent Promise upon creation or should it be done upon "activation" ?
        # TODO What to do about tracing the real way Promise calls are nested ? Maintain _real_parent that is set upon
        #  Promise activation and is not affected by manual choice of a parent or by the loop mismatch ?
        self._parent = parent or self.get_current(raise_if_none=False)
        self._children: WeakSet[Promise[Any]] = WeakSet()

        if self._parent is not None:
            if loop is None:
                loop = self._parent._loop
            elif loop is not self._parent._loop:
                # TODO Issue a warning about the loop mismatch, as long as config.wrong_event_loop is False.
                #  Or, maybe, even raise an error when we switch to wrong_loop_warnings=WARN(default)|RAISE|SUPPRESS.
                #  Also, in all cases make sure to include into the message how to change the handling of
                #  warning/error.
                #  (P.S. You don't have to do all that right here, do it when the config is already available.)

                # There is a mismatch between the loop provided and the loop of the parent Promise - let's not
                # establish the parent-child relationship.
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
            wrong_event_loop=wrong_event_loop,
            config_inheritable=config_inheritable,
        )

        self._coro = coro
        # TODO handle prefill_result and prefill_exception

        # TODO TODO TODO

        # TODO Support cancellation of the whole Promise tree

        # TODO Where to propagate errors raised from the children ?

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
