from typing import Optional

from promising.errors import NoCurrentPromiseError, NoParentConfigError
from promising.sentinels import NOT_SET, Sentinel
from promising.utils import get_bool_env, get_concrete_value


class PromisingDefaults:
    """
    Global defaults for Promise configuration.

    These defaults can be overridden via environment variables:
    - PROMISING_DEFAULT_START_SOON: Whether Promises start execution immediately
    - PROMISING_DEFAULT_MAKE_PARENT_WAIT: Whether parent Promises wait for children
    - PROMISING_DEFAULT_CONFIGS_INHERITABLE: Whether configurations are inherited by children

    Attributes:
        START_SOON: Default value for whether Promises start immediately (default: True).
        MAKE_PARENT_WAIT: Default value for whether parents wait for children (default: False).
        CONFIGS_INHERITABLE: Default value for config inheritance (default: True).
    """

    START_SOON = get_bool_env("PROMISING_DEFAULT_START_SOON", True)
    MAKE_PARENT_WAIT = get_bool_env("PROMISING_DEFAULT_MAKE_PARENT_WAIT", False)
    CONFIGS_INHERITABLE = get_bool_env("PROMISING_DEFAULT_CONFIGS_INHERITABLE", True)


class PromiseConfig:
    """
    Configuration object for controlling Promise behavior.

    PromiseConfig objects form a hierarchy, with child configs inheriting
    settings from their parents when those settings are marked as inheritable.

    Attributes:
        _parent_config: Direct parent configuration.
        _inheritable_parent_config: Nearest inheritable parent configuration.
        _start_soon: Whether the Promise starts execution immediately.
        _make_parent_wait: Whether parent Promises wait for this Promise.
        _config_inheritable: Whether child Promises can inherit this configuration.
    """

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
        """
        Initialize a PromiseConfig.

        Args:
            parent_config: Parent configuration to inherit from. If NOT_SET, uses current Promise's config.
            start_soon: Whether Promise starts immediately. If NOT_SET, inherits from parent or uses default.
            make_parent_wait: Whether parent waits for this Promise. If NOT_SET, inherits from parent or uses default.
            config_inheritable: Whether children can inherit this config. If NOT_SET, inherits from parent or
                uses default.

        Raises:
            ValueError: If config_inheritable is False for a root configuration.
        """
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
            self._config_inheritable = True  # Root PromiseConfig is always inheritable
        else:
            # This is NOT a root PromiseConfig
            self._inheritable_parent_config = self._parent_config.find_inheritable_config()
            self._start_soon = get_concrete_value(start_soon, self._inheritable_parent_config.is_start_soon())
            self._make_parent_wait = get_concrete_value(
                make_parent_wait, self._inheritable_parent_config.is_make_parent_wait()
            )
            self._config_inheritable = get_concrete_value(
                config_inheritable, self._inheritable_parent_config.is_config_inheritable()
            )

    def get_parent_config(self, raise_if_none: bool = True) -> Optional["PromiseConfig"]:
        """
        Get the direct parent configuration.

        Args:
            raise_if_none: If True, raises NoParentConfigError when no parent exists.

        Returns:
            The parent PromiseConfig, or None if this is a root config.

        Raises:
            NoParentConfigError: If raise_if_none is True and no parent exists.
        """
        if raise_if_none and self._parent_config is None:
            raise NoParentConfigError("No parent PromiseConfig found")
        return self._parent_config

    def get_inheritable_parent_config(self, raise_if_none: bool = True) -> Optional["PromiseConfig"]:
        """
        Get the nearest inheritable parent configuration.

        Args:
            raise_if_none: If True, raises NoParentConfigError when no inheritable parent exists.

        Returns:
            The nearest inheritable parent PromiseConfig, or None.

        Raises:
            NoParentConfigError: If raise_if_none is True and no inheritable parent exists.
        """
        if raise_if_none and self._inheritable_parent_config is None:
            raise NoParentConfigError("No inheritable parent PromiseConfig found")
        return self._inheritable_parent_config

    def is_start_soon(self) -> bool:
        """
        Check if Promises with this config should start execution immediately.

        Returns:
            True if Promises should start immediately, False otherwise.
        """
        return self._start_soon

    def is_make_parent_wait(self) -> bool:
        """
        Check if parent Promises should wait for Promises with this config.

        Returns:
            True if parents should wait, False otherwise.
        """
        return self._make_parent_wait

    def is_config_inheritable(self) -> bool:
        """
        Check if this configuration can be inherited by child Promises.

        Returns:
            True if the configuration is inheritable, False otherwise.
        """
        return self._config_inheritable

    def find_inheritable_config(self) -> "PromiseConfig":
        """
        Find the nearest inheritable configuration in the hierarchy.

        Traverses up the configuration hierarchy to find the nearest
        configuration marked as inheritable.

        Returns:
            The nearest inheritable PromiseConfig (could be self).

        Raises:
            RuntimeError: If no inheritable configuration is found (should never happen).
        """
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
