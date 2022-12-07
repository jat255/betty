from __future__ import annotations

from contextlib import contextmanager
from tempfile import NamedTemporaryFile
from typing import Iterator, Type, Union, Optional, Tuple, Iterable, List, Any, Hashable

import pytest
from reactives.tests import assert_reactor_called, assert_in_scope, assert_scope_empty

from betty.app import App
from betty.config import FileBasedConfiguration, ConfigurationMap, Configuration, DumpedConfigurationExport, \
    DumpedConfigurationImport, ConfigurationSequence, ConfigurationCollection
from betty.config.error import ConfigurationError, ConfigurationErrorCollection
from betty.config.load import ConfigurationFormatError, Loader


def assert_configuration_error(
        actual_error: Union[ConfigurationError, ConfigurationErrorCollection],
        error: Optional[Union[ConfigurationError, Type[ConfigurationError]]] = None,
        error_type: Optional[Type[ConfigurationError]] = None,
        error_message: Optional[str] = None,
        error_contexts: Optional[Tuple[str, ...]] = None,
) -> List[ConfigurationError]:
    actual_errors: Iterable[ConfigurationError]
    if isinstance(actual_error, ConfigurationErrorCollection):
        actual_errors = actual_error.flatten()
    else:
        actual_errors = [actual_error]

    expected_error_type = None
    expected_error_message = None
    expected_error_contexts = None
    if error:
        expected_error_type = type(error)
        expected_error_message = str(error)
        expected_error_contexts = error.contexts
    if error_type:
        expected_error_type = error_type
    if not expected_error_type:
        expected_error_type = ConfigurationError
    if error_message:
        expected_error_message = error_message
    if error_type:
        expected_error_contexts = error_contexts

    errors = [
        actual_error
        for actual_error
        in actual_errors
        if isinstance(actual_error, expected_error_type) or expected_error_message and str(actual_error).startswith(expected_error_message) or expected_error_contexts and expected_error_contexts == actual_error.contexts
    ]
    if errors:
        return errors
    raise AssertionError('Failed raising a configuration error.')


@contextmanager
def raises_configuration_error(*args, **kwargs) -> Iterator[Loader]:
    loader = Loader()
    try:
        with App():
            yield loader
    finally:
        assert_configuration_error(loader.errors, *args, **kwargs)


@contextmanager
def raises_no_configuration_errors(*args, **kwargs) -> Iterator[Loader]:
    loader = Loader()
    try:
        with App():
            yield loader
    finally:
        try:
            errors = assert_configuration_error(loader.errors, *args, **kwargs)
        except AssertionError:
            loader.commit()
            return
        raise AssertionError('Failed not to raise a configuration error') from errors[0]


class TestFileBasedConfiguration:
    def test_configuration_file_path_should_error_unknown_format(self) -> None:
        configuration = FileBasedConfiguration()
        with NamedTemporaryFile(mode='r+', suffix='.abc') as f:
            with pytest.raises(ConfigurationFormatError):
                configuration.configuration_file_path = f.name


class ConfigurationCollectionTestConfiguration(Configuration):
    def __init__(self, configuration_key: Any, configuration_value: int):
        super().__init__()
        self.key = configuration_key
        self.value = configuration_value

    def load(self, dumped_configuration: DumpedConfigurationImport, loader: Loader) -> None:
        raise NotImplementedError

    def dump(self) -> DumpedConfigurationExport:
        raise NotImplementedError


class ConfigurationCollectionTestBase:
    _ConfigurationKeyT: Type[int | Hashable]
    _ConfigurationT: Type[Configuration]
    _CONFIGURATION_KEYS: Tuple[_ConfigurationKeyT, _ConfigurationKeyT, _ConfigurationKeyT, _ConfigurationKeyT]

    def get_sut(self, configurations: _ConfigurationKeyT = None) -> ConfigurationCollection[_ConfigurationKeyT, _ConfigurationT]:
        raise NotImplementedError

    def get_configurations(self) -> Tuple[_ConfigurationT, _ConfigurationT, _ConfigurationT, _ConfigurationT]:
        raise NotImplementedError

    def test_getitem(self) -> None:
        configuration = self.get_configurations()[0]
        sut = self.get_sut([configuration])
        with assert_in_scope(sut):
            assert [configuration] == list(sut)

    def test_delitem(self) -> None:
        configuration = self.get_configurations()[0]
        sut = self.get_sut([configuration])
        with assert_scope_empty():
            with assert_reactor_called(sut):
                del sut[self._CONFIGURATION_KEYS[0]]
        assert [] == list(sut)
        assert [] == list(configuration.react._reactors)

    def test_iter(self) -> None:
        configurations = self.get_configurations()
        sut = self.get_sut([
            configurations[0],
            configurations[1],
        ])
        with assert_in_scope(sut):
            assert [configurations[0], configurations[1]] == list(iter(sut))

    def test_len(self) -> None:
        configurations = self.get_configurations()
        sut = self.get_sut([
            configurations[0],
            configurations[1],
        ])
        with assert_in_scope(sut):
            assert 2 == len(sut)

    def test_eq(self) -> None:
        configurations = self.get_configurations()
        sut = self.get_sut([
            configurations[0],
            configurations[1],
        ])
        other = self.get_sut([
            configurations[0],
            configurations[1],
        ])
        with assert_in_scope(sut):
            assert other == sut

    def test_prepend(self) -> None:
        configurations = self.get_configurations()
        sut = self.get_sut([
            configurations[1],
        ])
        with assert_scope_empty():
            with assert_reactor_called(sut):
                sut.prepend(configurations[0])
        assert [configurations[0], configurations[1]] == list(sut)
        with assert_reactor_called(sut):
            configurations[0].react.trigger()

    def test_append(self) -> None:
        configurations = self.get_configurations()
        sut = self.get_sut([
            configurations[0],
        ])
        with assert_scope_empty():
            with assert_reactor_called(sut):
                sut.append(configurations[1], configurations[2])
        assert [configurations[0], configurations[1], configurations[2]] == list(sut)
        with assert_reactor_called(sut):
            configurations[0].react.trigger()

    def test_insert(self) -> None:
        configurations = self.get_configurations()
        sut = self.get_sut([
            configurations[0],
            configurations[1],
        ])
        with assert_scope_empty():
            with assert_reactor_called(sut):
                sut.insert(1, configurations[2], configurations[3])
        assert [configurations[0], configurations[2], configurations[3], configurations[1]] == list(sut)
        with assert_reactor_called(sut):
            configurations[0].react.trigger()

    def test_move_to_beginning(self) -> None:
        configurations = self.get_configurations()
        sut = self.get_sut(configurations)
        with assert_scope_empty():
            with assert_reactor_called(sut):
                sut.move_to_beginning(self._CONFIGURATION_KEYS[2], self._CONFIGURATION_KEYS[3])
        assert [configurations[2], configurations[3], configurations[0], configurations[1]] == list(sut)

    def test_move_towards_beginning(self) -> None:
        configurations = self.get_configurations()
        sut = self.get_sut(configurations)
        with assert_scope_empty():
            with assert_reactor_called(sut):
                sut.move_towards_beginning(self._CONFIGURATION_KEYS[2], self._CONFIGURATION_KEYS[3])
        assert [configurations[0], configurations[2], configurations[3], configurations[1]] == list(sut)

    def test_move_to_end(self) -> None:
        configurations = self.get_configurations()
        sut = self.get_sut(configurations)
        with assert_scope_empty():
            with assert_reactor_called(sut):
                sut.move_to_end(self._CONFIGURATION_KEYS[0], self._CONFIGURATION_KEYS[1])
        assert [configurations[2], configurations[3], configurations[0], configurations[1]] == list(sut)

    def test_move_towards_end(self) -> None:
        configurations = self.get_configurations()
        sut = self.get_sut(configurations)
        with assert_scope_empty():
            with assert_reactor_called(sut):
                sut.move_towards_end(self._CONFIGURATION_KEYS[0], self._CONFIGURATION_KEYS[1])
        assert [configurations[2], configurations[0], configurations[1], configurations[3]] == list(sut)


class ConfigurationSequenceTestBase(ConfigurationCollectionTestBase):
    _ConfigurationKeyT = int
    _CONFIGURATION_KEYS = (0, 1, 2, 3)

    def test_abstract_methods(self) -> None:
        sut = self.get_sut()
        configuration = sut._default_configuration_item()
        assert isinstance(configuration, Configuration)


class ConfigurationSequenceTestConfigurationSequence(ConfigurationSequence[ConfigurationCollectionTestConfiguration]):
    def _default_configuration_item(self) -> ConfigurationCollectionTestConfiguration:
        return ConfigurationCollectionTestConfiguration('foo', 123)


class TestConfigurationSequence(ConfigurationSequenceTestBase):
    def get_sut(self, configurations: Optional[Iterable[ConfigurationCollectionTestConfiguration]] = None) -> ConfigurationSequenceTestConfigurationSequence:
        return ConfigurationSequenceTestConfigurationSequence(configurations)

    def get_configurations(self) -> Tuple[ConfigurationCollectionTestConfiguration, ConfigurationCollectionTestConfiguration, ConfigurationCollectionTestConfiguration, ConfigurationCollectionTestConfiguration]:
        return (
            ConfigurationCollectionTestConfiguration(self._CONFIGURATION_KEYS[0], 123),
            ConfigurationCollectionTestConfiguration(self._CONFIGURATION_KEYS[1], 456),
            ConfigurationCollectionTestConfiguration(self._CONFIGURATION_KEYS[2], 789),
            ConfigurationCollectionTestConfiguration(self._CONFIGURATION_KEYS[0], 000),
        )


class ConfigurationMapTestBase(ConfigurationCollectionTestBase):
    def test_abstract_methods(self) -> None:
        sut = self.get_sut()
        configuration_key = self._CONFIGURATION_KEYS[0]
        configuration = sut._default_configuration_item(configuration_key)
        assert isinstance(configuration, Configuration)
        assert configuration_key == sut._get_key(configuration)
        dumped_configuration_key = sut._dump_key(configuration_key)
        assert isinstance(dumped_configuration_key, str)
        loaded_configuration_key = sut._load_key(dumped_configuration_key)
        assert configuration_key == loaded_configuration_key


class ConfigurationMapTestConfigurationMap(ConfigurationMap[str, ConfigurationCollectionTestConfiguration]):
    def _get_key(self, configuration: ConfigurationCollectionTestConfiguration) -> str:
        return configuration.key

    def _load_key(self, dumped_configuration_key: str) -> str:
        return dumped_configuration_key

    def _dump_key(self, configuration_key: str) -> str:
        return configuration_key

    def _default_configuration_item(self, configuration_key: str) -> ConfigurationCollectionTestConfiguration:
        return ConfigurationCollectionTestConfiguration('foo', 123)


class TestConfigurationMap(ConfigurationMapTestBase):
    _ConfigurationKeyT = str
    _ConfigurationT = ConfigurationCollectionTestConfiguration
    _CONFIGURATION_KEYS = ('foo', 'bar', 'baz', 'qux')

    def get_sut(self, configurations: Optional[Iterable[ConfigurationCollectionTestConfiguration]] = None) -> ConfigurationMapTestConfigurationMap:
        return ConfigurationMapTestConfigurationMap(configurations)

    def get_configurations(self) -> Tuple[ConfigurationCollectionTestConfiguration, ConfigurationCollectionTestConfiguration, ConfigurationCollectionTestConfiguration, ConfigurationCollectionTestConfiguration]:
        return (
            ConfigurationCollectionTestConfiguration(self._CONFIGURATION_KEYS[0], 123),
            ConfigurationCollectionTestConfiguration(self._CONFIGURATION_KEYS[1], 456),
            ConfigurationCollectionTestConfiguration(self._CONFIGURATION_KEYS[2], 789),
            ConfigurationCollectionTestConfiguration(self._CONFIGURATION_KEYS[3], 000),
        )
