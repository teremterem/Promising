from asyncio import AbstractEventLoop, Future, Task, coroutines
from contextvars import ContextVar
import itertools
import os
from typing import Any, Coroutine, Generic, Optional
from weakref import WeakSet

from promising.errors import NoCurrentPromiseError, NoParentPromiseError
from promising.sentinels import NOT_SET, Sentinel
from promising.typing import T_co


class PromisingDefaults:
    START_SOON = os.getenv("PROMISING_DEFAULT_START_SOON", "true").lower() == "true"
    MAKE_PARENT_WAIT = os.getenv("PROMISING_DEFAULT_MAKE_PARENT_WAIT", "false").lower() == "true"
    CONFIGS_INHERITABLE = os.getenv("PROMISING_DEFAULT_CONFIGS_INHERITABLE", "true").lower() == "true"


_promise_name_counter = itertools.count(1)
# TODO Also maintain UUIDs for promises ?


def get_current_promise(raise_if_none: bool = True) -> Optional["Promise[Any]"]:
    # TODO Do we really need this function ?
    return Promise.get_current(raise_if_none=raise_if_none)


def _get_concrete_value(value: Any | Sentinel, default_value: Any) -> Any:
    if value is NOT_SET:
        return default_value
    return value


class PromiseConfig:
    _parent_config: Optional["PromiseConfig"] = None
    _inheritable_parent_config: Optional["PromiseConfig"] = None

    def __init__(
        self,
        parent_config: Optional["PromiseConfig"] | Sentinel = NOT_SET,
        *,
        start_soon: bool | Sentinel = NOT_SET,
        make_parent_wait: bool | Sentinel = NOT_SET,
        config_inheritable: bool | Sentinel = NOT_SET,
    ) -> None:
        if parent_config is NOT_SET:
            try:
                self._parent_config = get_current_promise().get_config()
            except (NoCurrentPromiseError, NoParentPromiseError):
                pass
        else:
            self._parent_config = parent_config

        if self._parent_config is None:
            # This is a root PromiseConfig
            if config_inheritable is False:
                raise ValueError("Cannot set config_inheritable to False for the root PromiseConfig")

            self._start_soon = _get_concrete_value(start_soon, PromisingDefaults.START_SOON)
            self._make_parent_wait = _get_concrete_value(make_parent_wait, PromisingDefaults.MAKE_PARENT_WAIT)
            self._config_inheritable = True  # Root PromiseConfig is always inheritable
        else:
            # This is NOT a root PromiseConfig
            self._inheritable_parent_config = self._find_inheritable_parent_config()
            self._start_soon = _get_concrete_value(start_soon, self._inheritable_parent_config.is_start_soon())
            self._make_parent_wait = _get_concrete_value(
                make_parent_wait, self._inheritable_parent_config.is_make_parent_wait()
            )
            self._config_inheritable = _get_concrete_value(
                config_inheritable, self._inheritable_parent_config.is_config_inheritable()
            )

    def get_parent_config(self, raise_if_none: bool = True) -> Optional["PromiseConfig"]:
        if raise_if_none and self._parent_config is None:
            # TODO Dedicated error for this case ?
            raise NoParentPromiseError("No parent PromiseConfig found")
        return self._parent_config

    def get_inheritable_parent_config(self, raise_if_none: bool = True) -> Optional["PromiseConfig"]:
        if raise_if_none and self._inheritable_parent_config is None:
            # TODO Dedicated error for this case ?
            raise NoParentPromiseError("No inheritable parent PromiseConfig found")
        return self._inheritable_parent_config

    def is_start_soon(self) -> bool:
        return self._start_soon

    def is_make_parent_wait(self) -> bool:
        return self._make_parent_wait

    def is_config_inheritable(self) -> bool:
        return self._config_inheritable

    def _find_inheritable_parent_config(self) -> "PromiseConfig":
        # pylint: disable=protected-access
        config = self._parent_config
        while config is not None:
            if config._config_inheritable:
                return config
            config = config._parent_config
        raise RuntimeError(
            "No inheritable parent PromiseConfig found (at least the root PromiseConfig should have been inheritable, "
            "but it's not)"
        )


class Promise(Future, Generic[T_co]):
    _current: ContextVar[Optional["Promise[Any]"]] = ContextVar("Promise._current", default=None)

    _task: Optional[Task[T_co]] = None

    def __init__(
        self,
        coro: Optional[Coroutine[Any, Any, T_co]] = None,
        *,
        loop: Optional[AbstractEventLoop] = None,
        name: Optional[str] = None,
        config: Optional[PromiseConfig] = None,
        start_soon: bool | Sentinel = NOT_SET,
        make_parent_wait: bool | Sentinel = NOT_SET,
        config_inheritable: bool | Sentinel = NOT_SET,
        prefill_result: Optional[T_co] | Sentinel = NOT_SET,
        prefill_exception: Optional[BaseException] = None,
    ):
        if coro is not None and not coroutines.iscoroutine(coro):
            raise TypeError(f"Promise must be created with a coroutine. Got {type(coro)}.")
        if coro is not None and (prefill_result is not NOT_SET or prefill_exception is not None):
            raise ValueError("Cannot provide both 'coro' and 'prefill_result' or 'prefill_exception' parameters")
        if prefill_result is not NOT_SET and prefill_exception is not None:
            raise ValueError("Cannot provide both 'prefill_result' and 'prefill_exception' parameters")
        # TODO If config is provided, start_soon, make_parent_wait and config_inheritable should not be provided

        # TODO Does it make sense to set the parent Promise upon creation or should it be done upon "activation" ?
        self._parent = self.get_current(raise_if_none=False)

        self._children: WeakSet[Promise[Any]] = WeakSet()
        if self._parent is not None:
            self._parent._children.add(self)

        # TODO Get the loop from the "parent" Promise if not explicitly provided
        # TODO Disallow passing a loop if it's not the same as the parent's loop ?
        super().__init__(loop=loop)

        if name is None:
            name = f"Promise-{next(_promise_name_counter)}"
        self._name = name

        if config is None:
            self._config = PromiseConfig(
                start_soon=start_soon,
                make_parent_wait=make_parent_wait,
                config_inheritable=config_inheritable,
            )
        else:
            self._config = config

        self._coro = coro
        # TODO handle prefill_result and prefill_exception

        # TODO TODO TODO

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

    def get_config(self) -> PromiseConfig:
        return self._config

    # TODO Supply getters for attributes like _start_soon, _make_parent_wait, _coro, _name, _children
