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
    # TODO Introduce a utility function that reads booleans from env vars and also raises errors if .lower() is not
    #  true or false
    START_SOON = os.getenv("PROMISING_DEFAULT_START_SOON", "true").lower() == "true"
    MAKE_PARENT_WAIT = os.getenv("PROMISING_DEFAULT_MAKE_PARENT_WAIT", "false").lower() == "true"
    # TODO Switch it to RAISE(Default)|WARN|SUPPRESS (Make a utility function that validates the value is in the list
    #  of allowed values ? Or, maybe, use Enum somehow ?)
    WRONG_EVENT_LOOP = os.getenv("PROMISING_DEFAULT_WRONG_EVENT_LOOP", "true").lower() == "true"
    CONFIGS_INHERITABLE = os.getenv("PROMISING_DEFAULT_CONFIGS_INHERITABLE", "true").lower() == "true"


_promise_name_counter = itertools.count(1)
# TODO Also maintain UUIDs for promises ?


def get_current_promise(raise_if_none: bool = True) -> Optional["Promise[Any]"]:
    # TODO Do we really need this function ?
    return Promise.get_current(raise_if_none=raise_if_none)


# TODO Move this function to utils.py
def get_concrete_value(value: Any | Sentinel, default_value: Any) -> Any:
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
        wrong_event_loop: bool | Sentinel = NOT_SET,
        config_inheritable: bool | Sentinel = NOT_SET,
    ) -> None:
        if parent_config is NOT_SET:
            try:
                self._parent_config = get_current_promise().get_config()
            except (NoCurrentPromiseError, NoParentPromiseError):
                pass
        else:
            # TODO Do we really need to maintain _parent_config and _inheritable_parent_config separately ?
            self._parent_config = parent_config

        if self._parent_config is None:
            # This is a root PromiseConfig
            if config_inheritable is False:
                raise ValueError("Cannot set config_inheritable to False for the root PromiseConfig")

            self._start_soon = get_concrete_value(start_soon, PromisingDefaults.START_SOON)
            self._make_parent_wait = get_concrete_value(make_parent_wait, PromisingDefaults.MAKE_PARENT_WAIT)
            self._wrong_event_loop = get_concrete_value(wrong_event_loop, PromisingDefaults.WRONG_EVENT_LOOP)
            self._config_inheritable = True  # Root PromiseConfig is always inheritable
        else:
            # This is NOT a root PromiseConfig
            self._inheritable_parent_config = self._parent_config.find_inheritable_config()
            self._start_soon = get_concrete_value(start_soon, self._inheritable_parent_config.is_start_soon())
            self._make_parent_wait = get_concrete_value(
                make_parent_wait, self._inheritable_parent_config.is_make_parent_wait()
            )
            self._wrong_event_loop = get_concrete_value(
                wrong_event_loop, self._inheritable_parent_config.is_wrong_event_loop()
            )
            self._config_inheritable = get_concrete_value(
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

    def find_inheritable_config(self) -> "PromiseConfig":
        # pylint: disable=protected-access
        config = self
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
