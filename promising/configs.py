from typing import Optional

from promising.errors import NoCurrentPromiseError, NoParentConfigError
from promising.sentinels import NOT_SET, Sentinel
from promising.utils import get_bool_env, get_concrete_value


class PromisingDefaults:
    """
    Default configuration values for the Promising library.

    This class defines environment-variable-backed default settings that control
    the behavior of Promise instances when no explicit configuration is provided.
    All defaults can be overridden via environment variables prefixed with 'PROMISING_DEFAULT_'.
    """

    START_SOON = get_bool_env("PROMISING_DEFAULT_START_SOON", True)
    MAKE_PARENT_WAIT = get_bool_env("PROMISING_DEFAULT_MAKE_PARENT_WAIT", False)
    CONFIGS_INHERITABLE = get_bool_env("PROMISING_DEFAULT_CONFIGS_INHERITABLE", True)


class PromiseConfig:
    """
    Configuration object for Promise behavior and inheritance.

    PromiseConfig manages the behavioral settings for Promise instances, including
    execution timing, parent-child relationships, and configuration inheritance.
    Configurations can form hierarchical relationships where child configs inherit
    settings from their parents.
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
        Initialize a new PromiseConfig instance.

        Args:
            parent_config: Parent configuration to inherit from. If NOT_SET, uses current Promise's config.
            start_soon: Whether Promises with this config should start execution immediately.
            make_parent_wait: Whether parent Promises should wait for Promises with this config.
            config_inheritable: Whether this configuration can be inherited by child Promises.

        Raises:
            ValueError: If config_inheritable is False for a root config, or invalid combinations.
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
        Get the parent configuration of this config.

        Args:
            raise_if_none: If True, raises an exception when no parent config exists.

        Returns:
            The parent PromiseConfig, or None if no parent exists and raise_if_none is False.

        Raises:
            NoParentConfigError: If no parent config exists and raise_if_none is True.
        """
        if raise_if_none and self._parent_config is None:
            raise NoParentConfigError("No parent PromiseConfig found")
        return self._parent_config

    def get_inheritable_parent_config(self, raise_if_none: bool = True) -> Optional["PromiseConfig"]:
        """
        Get the nearest inheritable parent configuration.

        Args:
            raise_if_none: If True, raises an exception when no inheritable parent exists.

        Returns:
            The nearest inheritable parent PromiseConfig, or None if none exists and
            raise_if_none is False.

        Raises:
            NoParentConfigError: If no inheritable parent exists and raise_if_none is True.
        """
        if raise_if_none and self._inheritable_parent_config is None:
            raise NoParentConfigError("No inheritable parent PromiseConfig found")
        return self._inheritable_parent_config

    def is_start_soon(self) -> bool:
        """
        Check if Promises with this config should start execution immediately.

        Returns:
            True if Promises should start soon, False otherwise.
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
            True if this config is inheritable, False otherwise.
        """
        return self._config_inheritable

    def find_inheritable_config(self) -> "PromiseConfig":
        """
        Find the nearest inheritable configuration in the parent chain.

        Traverses up the configuration hierarchy to find the first configuration
        that has config_inheritable=True.

        Returns:
            The nearest inheritable PromiseConfig in the parent chain.

        Raises:
            RuntimeError: If no inheritable config is found (should never happen as
                         root configs are always inheritable).
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
