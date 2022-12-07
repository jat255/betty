from __future__ import annotations

import os
from collections import OrderedDict
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, TypeVar, Generic, Optional, Iterable, List, Union, SupportsIndex, Hashable

from reactives import reactive, scope
from reactives.factory.type import ReactiveInstance

from betty.classtools import Repr, repr_instance
from betty.config.dump import DumpedConfigurationImport, DumpedConfigurationExport, \
    DumpedConfigurationDict, minimize_dict, minimize_list
from betty.config.format import FORMATS_BY_EXTENSION, EXTENSIONS
from betty.config.load import ConfigurationFormatError, Loader, ConfigurationLoadError
from betty.os import PathLike, ChDir

try:
    from typing_extensions import TypeAlias, TypeGuard
except ModuleNotFoundError:
    from typing import TypeAlias, TypeGuard  # type: ignore


@reactive
class Configuration(ReactiveInstance, Repr):
    def load(self, dumped_configuration: DumpedConfigurationImport, loader: Loader) -> None:
        """
        Validate the dumped configuration and prepare to load it into self.

        Implementations MUST:
        - Use the loader to set configuration errors
        - Use the loader to register callbacks that make the actual configuration updates

        Implementations MUST NOT:
        - Raise configuration errors
        - Update their own state as a direct result of this method being called
        """

        raise NotImplementedError

    def dump(self) -> DumpedConfigurationExport:
        """
        Dump this configuration to a portable format.
        """

        raise NotImplementedError


ConfigurationT = TypeVar('ConfigurationT', bound=Configuration)


class FileBasedConfiguration(Configuration):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._project_directory: Optional[TemporaryDirectory] = None
        self._configuration_file_path = None
        self._autowrite = False

    def _assert_configuration_file_path(self) -> None:
        if self.configuration_file_path is None:
            raise ConfigurationLoadError('The configuration must have a configuration file path.')

    @property
    def autowrite(self) -> bool:
        return self._autowrite

    @autowrite.setter
    def autowrite(self, autowrite: bool) -> None:
        if autowrite:
            self._assert_configuration_file_path()
            if not self._autowrite:
                self.react.react_weakref(self.write)
        else:
            self.react.shutdown(self.write)
        self._autowrite = autowrite

    def write(self, configuration_file_path: Optional[PathLike] = None) -> None:
        if configuration_file_path is None:
            self._assert_configuration_file_path()
        else:
            self.configuration_file_path = configuration_file_path

        self._write(self.configuration_file_path)

    def _write(self, configuration_file_path: Path) -> None:
        # Change the working directory to allow absolute paths to be turned relative to the configuration file's directory
        # path.
        with ChDir(configuration_file_path.parent):
            dumped_configuration = FORMATS_BY_EXTENSION[configuration_file_path.suffix[1:]].dump(self.dump())
            try:
                with open(configuration_file_path, mode='w') as f:
                    f.write(dumped_configuration)
            except FileNotFoundError:
                os.makedirs(configuration_file_path.parent)
                self.write()
        self._configuration_file_path = configuration_file_path

    def read(self, configuration_file_path: Optional[PathLike] = None) -> None:
        if configuration_file_path is None:
            self._assert_configuration_file_path()
        else:
            self.configuration_file_path = configuration_file_path

        # Change the working directory to allow relative paths to be resolved against the configuration file's directory
        # path.
        with ChDir(self.configuration_file_path.parent):
            with open(self.configuration_file_path) as f:
                read_configuration = f.read()
            loader = Loader()
            with loader.context('in %s' % self.configuration_file_path.resolve()):
                self.load(FORMATS_BY_EXTENSION[self.configuration_file_path.suffix[1:]].load(read_configuration), loader)
        loader.commit()

    def __del__(self):
        if hasattr(self, '_project_directory') and self._project_directory is not None:
            self._project_directory.cleanup()

    @reactive  # type: ignore
    @property
    def configuration_file_path(self) -> Path:
        if self._configuration_file_path is None:
            if self._project_directory is None:
                self._project_directory = TemporaryDirectory()
            self._write(Path(self._project_directory.name) / f'{type(self).__name__}.json')
        return self._configuration_file_path  # type: ignore

    @configuration_file_path.setter
    def configuration_file_path(self, configuration_file_path: PathLike) -> None:
        configuration_file_path = Path(configuration_file_path)
        if configuration_file_path == self._configuration_file_path:
            return
        if configuration_file_path.suffix[1:] not in EXTENSIONS:
            raise ConfigurationFormatError(f"Unknown file format \"{configuration_file_path.suffix}\". Supported formats are: {', '.join(map(lambda x: f'.{x}', EXTENSIONS))}.")
        self._configuration_file_path = configuration_file_path

    @configuration_file_path.deleter
    def configuration_file_path(self) -> None:
        if self._autowrite:
            raise RuntimeError('Cannot remove the configuration file path while autowrite is enabled.')
        self._configuration_file_path = None


ConfigurationKey: TypeAlias = Union[SupportsIndex, slice, Hashable]
ConfigurationKeyT = TypeVar('ConfigurationKeyT', bound=ConfigurationKey)


class ConfigurationCollection(Configuration, Generic[ConfigurationKeyT, ConfigurationT]):
    _configurations: List[ConfigurationT] | Dict[ConfigurationKeyT, ConfigurationT]

    def __init__(self, configurations: Optional[Iterable[ConfigurationT]] = None):
        super().__init__()
        if configurations is not None:
            self.append(*configurations)

    def __contains__(self, item) -> bool:
        return item in self._configurations

    @scope.register_self
    def __getitem__(self, configuration_key: ConfigurationKeyT) -> ConfigurationT:
        return self._configurations[configuration_key]

    def __delitem__(self, configuration_key: ConfigurationKeyT) -> None:
        self.remove(configuration_key)

    @scope.register_self
    def __iter__(self) -> Iterable[ConfigurationT]:
        raise NotImplementedError

    @scope.register_self
    def __len__(self) -> int:
        return len(self._configurations)

    @scope.register_self
    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self._configurations == other._configurations

    def remove(self, *configuration_keys: ConfigurationKeyT) -> None:
        for configuration_key in configuration_keys:
            with suppress(LookupError):
                self._configurations[configuration_key].react.shutdown(self)
            del self._configurations[configuration_key]
        self.react.trigger()

    def clear(self) -> None:
        self.remove(*self._configurations.keys())

    def prepend(self, *configurations: ConfigurationT) -> None:
        raise NotImplementedError

    def append(self, *configurations: ConfigurationT) -> None:
        raise NotImplementedError

    def insert(self, index: int, *configurations: ConfigurationT) -> None:
        raise NotImplementedError

    def move_to_beginning(self, *configuration_keys: ConfigurationKeyT) -> None:
        raise NotImplementedError

    def move_towards_beginning(self, *configuration_keys: ConfigurationKeyT) -> None:
        raise NotImplementedError

    def move_to_end(self, *configuration_keys: ConfigurationKeyT) -> None:
        raise NotImplementedError

    def move_towards_end(self, *configuration_keys: ConfigurationKeyT) -> None:
        raise NotImplementedError


class ConfigurationSequence(ConfigurationCollection[int, ConfigurationT], Generic[ConfigurationT]):
    def __init__(self, configurations: Optional[Iterable[ConfigurationT]] = None):
        self._configurations: List[ConfigurationT] = []
        super().__init__(configurations)

    @scope.register_self
    def __iter__(self) -> Iterable[ConfigurationT]:
        return (configuration for configuration in self._configurations)

    def __repr__(self):
        return repr_instance(self, configurations=self._configurations)

    def load(self, dumped_configuration: DumpedConfigurationImport, loader: Loader) -> None:
        if loader.assert_list(dumped_configuration):
            loader.on_commit(self.clear)
            loader.assert_sequence(
                dumped_configuration,
                self._load_configuration,  # type: ignore
            )

    def _load_configuration(self, dumped_configuration: DumpedConfigurationImport, loader: Loader) -> TypeGuard[DumpedConfigurationDict[DumpedConfigurationImport]]:
        with loader.context() as errors:
            with loader.catch():
                configuration = self._default_configuration_item()
                configuration.load(dumped_configuration, loader)
                loader.on_commit(lambda: self.append(configuration))
        return errors.valid

    def dump(self) -> DumpedConfigurationExport:
        return minimize_list([
            configuration.dump()
            for configuration in self._configurations
        ])

    def _default_configuration_item(self) -> ConfigurationT:
        raise NotImplementedError

    def prepend(self, *configurations: ConfigurationT) -> None:
        for configuration in configurations:
            self._configurations.insert(0, configuration)
            configuration.react(self)
        self.react.trigger()

    def append(self, *configurations: ConfigurationT) -> None:
        for configuration in configurations:
            self._configurations.append(configuration)
            configuration.react(self)
        self.react.trigger()

    def insert(self, index: int, *configurations: ConfigurationT) -> None:
        for configuration in reversed(configurations):
            self._configurations.insert(index, configuration)
            configuration.react(self)
        self.react.trigger()

    def move_to_beginning(self, *configuration_keys: int) -> None:
        configuration_keys = list(configuration_keys)
        self.move_to_end(
            *configuration_keys,
            *[
                configuration_key
                for configuration_key
                in range(0, len(self._configurations))
                if configuration_key not in configuration_keys
            ]
        )

    def move_towards_beginning(self, *configuration_keys: int) -> None:
        for configuration_key in configuration_keys:
            self._configurations.insert(configuration_key - 1, self._configurations.pop(configuration_key))
        self.react.trigger()

    def move_to_end(self, *configuration_keys: int) -> None:
        configuration_keys = list(configuration_keys)
        for configuration_key in configuration_keys:
            self._configurations.append(self._configurations[configuration_key])
        for configuration_key in reversed(configuration_keys):
            self._configurations.pop(configuration_key)
        self.react.trigger()

    def move_towards_end(self, *configuration_keys: int) -> None:
        for configuration_key in reversed(configuration_keys):
            self._configurations.insert(configuration_key + 1, self._configurations.pop(configuration_key))
        self.react.trigger()


class ConfigurationMap(ConfigurationCollection[ConfigurationKeyT, ConfigurationT], Generic[ConfigurationKeyT, ConfigurationT]):
    def __init__(self, configurations: Optional[Iterable[ConfigurationT]] = None):
        self._configurations: OrderedDict = OrderedDict()
        super().__init__(configurations)

    @scope.register_self
    def __getitem__(self, configuration_key: ConfigurationKeyT) -> ConfigurationT:
        try:
            return super().__getitem__(configuration_key)
        except KeyError:
            item = self._default_configuration_item(configuration_key)
            self.append(item)
            return item

    @scope.register_self
    def __iter__(self) -> Iterable[ConfigurationT]:
        return (configuration for configuration in self._configurations.values())

    def __repr__(self):
        return repr_instance(self, configurations=list(self._configurations.values()))

    def load(self, dumped_configuration: DumpedConfigurationImport, loader: Loader) -> None:
        if loader.assert_dict(dumped_configuration):
            loader.on_commit(self.clear)
            loader.assert_mapping(
                dumped_configuration,
                self._load_configuration,  # type: ignore
            )

    def _load_configuration(self, dumped_configuration: DumpedConfigurationImport, loader: Loader, dumped_configuration_key: str) -> TypeGuard[DumpedConfigurationDict[DumpedConfigurationImport]]:
        with loader.context() as errors:
            with loader.catch():
                configuration_key = self._load_key(dumped_configuration_key)
                configuration = self._default_configuration_item(configuration_key)
                configuration.load(dumped_configuration, loader)
                loader.on_commit(lambda: self.append(configuration))
        return errors.valid

    def dump(self) -> DumpedConfigurationExport:
        return minimize_dict({
            self._dump_key(self._get_key(configuration)): configuration.dump()
            for configuration in self._configurations.values()
        }, self._is_void_empty())

    def _get_key(self, configuration: ConfigurationT) -> ConfigurationKeyT:
        raise NotImplementedError

    def _load_key(self, dumped_configuration_key: str) -> ConfigurationKeyT:
        raise NotImplementedError

    def _dump_key(self, configuration_key: ConfigurationKeyT) -> str:
        raise NotImplementedError

    def _default_configuration_item(self, configuration_key: ConfigurationKeyT) -> ConfigurationT:
        raise NotImplementedError

    def _is_void_empty(self) -> bool:
        return False

    def prepend(self, *configurations: ConfigurationT) -> None:
        for configuration in configurations:
            configuration_key = self._get_key(configuration)
            self._configurations[configuration_key] = configuration
            configuration.react(self)
        self.move_to_beginning(*map(self._get_key, configurations))

    def _append_without_trigger(self, *configurations: ConfigurationT) -> None:
        for configuration in configurations:
            configuration_key = self._get_key(configuration)
            self._configurations[configuration_key] = configuration
            configuration.react(self)
        self._move_to_end_without_trigger(*map(self._get_key, configurations))

    def append(self, *configurations: ConfigurationT) -> None:
        self._append_without_trigger(*configurations)
        self.react.trigger()

    def _insert_without_trigger(self, index: int, *configurations: ConfigurationT) -> None:
        configurations = list(configurations)
        current_configuration_keys = list(self._configurations.keys())
        self._append_without_trigger(*configurations)
        self._move_to_end_without_trigger(
            *current_configuration_keys[0:index],
            *map(self._get_key, configurations),
            *current_configuration_keys[index:]
        )

    def insert(self, index: int, *configurations: ConfigurationT) -> None:
        self._insert_without_trigger(index, *configurations)
        self.react.trigger()

    def move_to_beginning(self, *configuration_keys: ConfigurationKeyT) -> None:
        for configuration_key in reversed(configuration_keys):
            self._configurations.move_to_end(configuration_key, False)
        self.react.trigger()

    def move_towards_beginning(self, *configuration_keys: ConfigurationKeyT) -> None:
        self._move_by_offset(-1, *configuration_keys)

    def _move_to_end_without_trigger(self, *configuration_keys: ConfigurationKeyT) -> None:
        for configuration_key in configuration_keys:
            self._configurations.move_to_end(configuration_key)

    def move_to_end(self, *configuration_keys: ConfigurationKeyT) -> None:
        print(self._configurations)
        self._move_to_end_without_trigger(*configuration_keys)
        print(self._configurations)
        self.react.trigger()

    def move_towards_end(self, *configuration_keys: ConfigurationKeyT) -> None:
        self._move_by_offset(1, *configuration_keys)

    def _move_by_offset(self, offset: int, *configuration_keys: ConfigurationKeyT) -> None:
        current_configuration_keys = list(self._configurations.keys())
        ordered_current_configuration_keys = current_configuration_keys if offset < 0 else list(reversed(current_configuration_keys))
        for configuration_key in ordered_current_configuration_keys:
            if configuration_key in configuration_keys:
                configuration_index = current_configuration_keys.index(configuration_key)
                self._insert_without_trigger(configuration_index + offset, self._configurations.pop(configuration_key))
        self.react.trigger()


class Configurable(Generic[ConfigurationT]):
    def __init__(self, /, configuration: Optional[ConfigurationT] = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._configuration = configuration

    @property
    def configuration(self) -> ConfigurationT:
        if self._configuration is None:
            raise RuntimeError(f'{self} has no configuration. {type(self)}.__init__() must ensure it is set.')
        return self._configuration
