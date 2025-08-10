import os
from typing import Optional

from promising.errors import NoCurrentPromiseError, NoInheritableParentConfigError, NoParentConfigError
from promising.sentinels import NOT_SET, Sentinel
from promising.utils import get_concrete_value


class PromisingDefaults:
    # TODO Introduce a utility function that reads booleans from env vars and also raises errors if .lower() is not
    #  true or false
    START_SOON = os.getenv("PROMISING_DEFAULT_START_SOON", "true").lower() == "true"
    MAKE_PARENT_WAIT = os.getenv("PROMISING_DEFAULT_MAKE_PARENT_WAIT", "false").lower() == "true"
    # TODO Switch it to RAISE(Default)|WARN|SUPPRESS (Make a utility function that validates the value is in the list
    #  of allowed values ? Or, maybe, use Enum somehow ?)
    WRONG_EVENT_LOOP = os.getenv("PROMISING_DEFAULT_WRONG_EVENT_LOOP", "true").lower() == "true"
    CONFIGS_INHERITABLE = os.getenv("PROMISING_DEFAULT_CONFIGS_INHERITABLE", "true").lower() == "true"


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
                # pylint: disable=import-outside-toplevel,cyclic-import
                from promising.promises import get_current_promise

                self._parent_config = get_current_promise().get_config()
            except NoCurrentPromiseError:
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
            raise NoParentConfigError("No parent PromiseConfig found")
        return self._parent_config

    def get_inheritable_parent_config(self, raise_if_none: bool = True) -> Optional["PromiseConfig"]:
        if raise_if_none and self._inheritable_parent_config is None:
            raise NoInheritableParentConfigError("No inheritable parent PromiseConfig found")
        return self._inheritable_parent_config

    def is_start_soon(self) -> bool:
        return self._start_soon

    def is_make_parent_wait(self) -> bool:
        return self._make_parent_wait

    def is_config_inheritable(self) -> bool:
        return self._config_inheritable

    def get_wrong_event_loop(self) -> bool:  # TODO Will be switched to RAISE(Default)|WARN|SUPPRESS, hence "get"
        return self._wrong_event_loop

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
