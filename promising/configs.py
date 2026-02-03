from typing import Optional

from promising.errors import NoCurrentPromiseError, NoParentConfigError
from promising.sentinels import NOT_SET, Sentinel
from promising.utils import get_concrete_value


class PromisingDefaults:
    """
    Default configuration values for the Promising library.

    This class defines environment-variable-backed default settings that
    control the behavior of Promise instances when no explicit configuration is
    provided. All defaults can be overridden via environment variables prefixed
    with 'PROMISING_DEFAULT_'.
    """

    START_SOON = True
    MAKE_PARENT_WAIT = False
    CONFIGS_INHERITABLE = True


class PromiseConfig:
    """
    Configuration object for Promise behavior.

    Configurations can form hierarchical relationships where child configs
    inherit settings from their parents.

    Args:
        parent_config: Parent configuration to inherit from. If NOT_SET, uses
            the currently active Promise's config as parent.
        start_soon: Whether Promises with this config should start execution
            immediately. More specifically, they are scheduled to run at the
            next opportunity the asyncio event loop provides. If NOT_SET,
            inherits the value from the nearest "inheritable" parent config.
        make_parent_wait: Whether parent Promises should wait for Promises with
            this config. This is not about dependency waiting - if a Promise
            depends on other Promises, it will always wait for them regardless
            of configuration. This flag is about execution timing/ordering
            only - use it when a parent Promise must NOT finish earlier than
            certain child Promises for sequencing or user experience reasons.
            If NOT_SET, inherits the value from the nearest "inheritable"
            parent config.
        config_inheritable: Whether this configuration can be inherited by
            child Promises.

    Raises:
        ValueError: If config_inheritable is False for a root configuration.
    """

    _parent_config: Optional["PromiseConfig"]
    _inheritable_parent_config: Optional["PromiseConfig"]

    def __init__(
        self,
        parent_config: Optional["PromiseConfig"] | Sentinel = NOT_SET,
        *,
        start_soon: bool | Sentinel = NOT_SET,
        make_parent_wait: bool | Sentinel = NOT_SET,
        config_inheritable: bool | Sentinel = NOT_SET,
    ) -> None:
        self._parent_config = None
        self._inheritable_parent_config = None

        if parent_config is NOT_SET:
            try:
                # pylint: disable=import-outside-toplevel,cyclic-import
                from promising.promises import get_current_promise

                self._parent_config = get_current_promise().get_config()
            except NoCurrentPromiseError:
                pass
        else:
            # TODO Do we really need to maintain _parent_config and
            #  _inheritable_parent_config separately ?
            self._parent_config = parent_config

        if self._parent_config is None:
            # TODO Instead of turning this config into a root config, just
            #  create a static root config object globally and use it as parent
            #  if there is no parent config.

            # This is the root PromiseConfig
            if config_inheritable is False:
                raise ValueError("Cannot set config_inheritable to False for the root PromiseConfig")

            self._start_soon = get_concrete_value(start_soon, PromisingDefaults.START_SOON)
            self._make_parent_wait = get_concrete_value(make_parent_wait, PromisingDefaults.MAKE_PARENT_WAIT)
            # The root PromiseConfig is always inheritable
            self._config_inheritable = True
        else:
            # This is NOT the root PromiseConfig
            self._inheritable_parent_config = self._parent_config.find_inheritable_config()
            self._start_soon = get_concrete_value(start_soon, self._inheritable_parent_config.is_start_soon())
            self._make_parent_wait = get_concrete_value(
                make_parent_wait, self._inheritable_parent_config.is_make_parent_wait()
            )
            # TODO Split it into `config_inheritable` and
            #  `child_configs_inheritable` ? (I don't remember what would be
            #  the use case for this, thought)
            self._config_inheritable = get_concrete_value(config_inheritable, PromisingDefaults.CONFIGS_INHERITABLE)

    def get_parent_config(self, raise_if_none: bool = True) -> Optional["PromiseConfig"]:
        """
        Get the parent config of this config.

        Args:
            raise_if_none: If True, raises NoParentConfigError if no parent
                config exists.

        Returns:
            The parent PromiseConfig, or None if no parent exists and
            raise_if_none is False.

        Raises:
            NoParentConfigError: If no parent config exists and raise_if_none
                is True.
        """
        if raise_if_none and self._parent_config is None:
            raise NoParentConfigError("No parent PromiseConfig found")
        return self._parent_config

    def get_inheritable_parent_config(self, raise_if_none: bool = True) -> Optional["PromiseConfig"]:
        """
        Get the nearest inheritable parent configuration.

        Args:
            raise_if_none: If True, raises NoParentConfigError when no
                inheritable parent exists.

        Returns:
            The nearest inheritable parent PromiseConfig, or None if none
            exists and raise_if_none is False.

        Raises:
            NoParentConfigError: If no inheritable parent exists and
                raise_if_none is True.
        """
        if raise_if_none and self._inheritable_parent_config is None:
            raise NoParentConfigError("No inheritable parent PromiseConfig found")
        return self._inheritable_parent_config

    def is_start_soon(self) -> bool:
        """
        Check if Promises with this config should start execution immediately,
        or more specifically, at the nearest opportunity the asyncio event loop
        provides. If False, the execution will start only when the Promise is
        explicitly awaited.

        Returns:
            True if Promises should start soon, False otherwise.
        """
        return self._start_soon

    def is_make_parent_wait(self) -> bool:
        """
        Check if a parent Promise should wait for a Promise (or Promises) with
        this config to finish.

        Returns:
            True if a parent should wait, False otherwise.
        """
        return self._make_parent_wait

    def is_config_inheritable(self) -> bool:
        """
        Check if this config can be inherited by child Promises.

        Returns:
            True if this config is inheritable, False otherwise.
        """
        return self._config_inheritable

    def find_inheritable_config(self) -> "PromiseConfig":
        """
        Find the nearest inheritable config in the parent chain.

        Traverses up the configuration hierarchy to find the first
        configuration that has config_inheritable=True.

        Returns:
            Either self (if inheritable) or the nearest inheritable
            PromiseConfig in the parent chain.

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
            "No inheritable PromiseConfig found - at least the root "
            "PromiseConfig should be inheritable, but it isn't"
        )
