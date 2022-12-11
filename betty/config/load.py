from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Type, Dict, Union, Callable, Optional, Any, TypeVar, List

from babel.core import parse_locale

from betty.config.dump import DumpedConfigurationImport, DumpedConfigurationImportU, \
    DumpedConfigurationTypeT, DumpedConfigurationType
from betty.config.error import ConfigurationError, ConfigurationErrorCollection
from betty.locale import bcp_47_to_rfc_1766
from betty.model import EntityTypeError, EntityTypeInvalidError, EntityTypeImportError, Entity, get_entity_type

try:
    from typing_extensions import TypeAlias, TypeGuard
except ModuleNotFoundError:
    from typing import TypeAlias, TypeGuard  # type: ignore

if TYPE_CHECKING:
    from betty.builtins import _


class ConfigurationLoadError(ConfigurationError):
    pass


class ConfigurationValidationError(ConfigurationLoadError):
    pass


class ConfigurationFormatError(ConfigurationLoadError):
    pass


_TYPE_VIOLATION_ERROR_MESSAGE_BUILDERS: Dict[Type[DumpedConfigurationType], Callable[[], str]] = {
    bool: lambda: _('This must be a boolean.'),
    int: lambda: _('This must be an integer.'),
    float: lambda: _('This must be a decimal number.'),
    str: lambda: _('This must be a string.'),
    list: lambda: _('This must be a list.'),
    dict: lambda: _('This must be a key-value mapping.'),
}


T: TypeAlias = TypeVar('T')
U: TypeAlias = TypeVar('U')


ValueAssertionFunction: TypeAlias = Callable[
    [
        T,
        ConfigurationErrorCollection,
    ],
    U,
]


# @todo We stopped distinguishing between callables on different objects
# @todo Instead we just count parameters and pass on the error collection, or not
# @todo
ValueAssertionLoaderMethod: TypeAlias = Callable[
    [
        T,
    ],
    U,
]


ValueAssertion: TypeAlias = Union[
    ValueAssertionFunction,
    ValueAssertionLoaderMethod,
]


KeyAndValueAssertion: TypeAlias = Callable[
    [
        T,
        ConfigurationErrorCollection,
        str,
    ],
    U,
]


Assertion: TypeAlias = Union[
    ValueAssertion,
    KeyAndValueAssertion,
]


class Assertions:
    def __init__(self, *assertions: Assertion):
        self._assertions = assertions

    def __call__(self, configuration: Any, errors: ConfigurationErrorCollection, configuration_key: Optional[str] = None) -> Any:
        for assertion in self._assertions:
            with errors.context() as assertion_errors:
                args = [configuration, assertion_errors]
                if configuration_key and len(inspect.signature(assertion).parameters) > len(args):
                    args.append(configuration_key)
                configuration = assertion(*args)
            if assertion_errors.invalid:
                return


@dataclass(frozen=True)
class Field:
    name: str
    required: bool
    assertions: Optional[Assertions] = None


class Fields:
    def __init__(self, *fields: Field):
        self._fields = fields

    def __iter__(self) -> Iterator[Field]:
        return (field for field in self._fields)


def _assert_type(dumped_configuration: DumpedConfigurationImportU, errors: ConfigurationErrorCollection, configuration_value_required_type: Type[DumpedConfigurationTypeT], configuration_value_disallowed_type: Optional[Type[DumpedConfigurationType]] = None) -> TypeGuard[DumpedConfigurationTypeT]:
    if isinstance(dumped_configuration, configuration_value_required_type) and (not configuration_value_disallowed_type or not isinstance(dumped_configuration, configuration_value_disallowed_type)):
        return True
    errors.append(ConfigurationValidationError(_TYPE_VIOLATION_ERROR_MESSAGE_BUILDERS[configuration_value_required_type]()))
    return False


def assert_bool() -> ValueAssertion[Any, TypeGuard[bool]]:
    def _assertion(dumped_configuration: DumpedConfigurationImport, errors: ConfigurationErrorCollection) -> TypeGuard[bool]:
        return _assert_type(dumped_configuration, errors, bool)
    return _assertion


def assert_int() -> ValueAssertion[Any, TypeGuard[int]]:
    def _assertion(dumped_configuration: DumpedConfigurationImport, errors: ConfigurationErrorCollection) -> TypeGuard[int]:
        return _assert_type(dumped_configuration, errors, int, bool)
    return _assertion


def assert_float() -> ValueAssertion[Any, TypeGuard[float]]:
    def _assertion(dumped_configuration: DumpedConfigurationImport, errors: ConfigurationErrorCollection) -> TypeGuard[float]:
        return _assert_type(dumped_configuration, errors, float)
    return _assertion


def assert_str() -> ValueAssertion[Any, TypeGuard[str]]:
    def _assertion(dumped_configuration: DumpedConfigurationImport, errors: ConfigurationErrorCollection) -> TypeGuard[str]:
        return _assert_type(dumped_configuration, errors, str)
    return _assertion


def assert_list() -> ValueAssertion[Any, TypeGuard[TypeGuard[List]]]:
    def _assertion(dumped_configuration: DumpedConfigurationImport, errors: ConfigurationErrorCollection) -> TypeGuard[List]:
        return _assert_type(dumped_configuration, errors, list)
    return _assertion


def assert_dict() -> ValueAssertion[Any, TypeGuard[Dict]]:
    def _assertion(value: Any, errors: ConfigurationErrorCollection) -> TypeGuard[Dict]:
        return _assert_type(value, errors, dict)
    return _assertion


def assert_sequence(assertions: Assertions) -> ValueAssertion[Any, TypeGuard[List[Any]]]:
    def _assertion(value: Any, errors: ConfigurationErrorCollection) -> TypeGuard[List[Any]]:
        with errors.context() as sequence_errors:
            if assert_list()(value, errors):
                for i, dumped_configuration_item in enumerate(value):
                    with sequence_errors.context(str(i)) as item_errors:
                        assertions(dumped_configuration_item, item_errors)
        return sequence_errors.valid
    return _assertion


def assert_mapping(assertions: Assertions) -> KeyAndValueAssertion[Any, TypeGuard[Dict[str, Any]]]:
    def _assertion(value: Any, errors: ConfigurationErrorCollection) -> TypeGuard[Dict[str, Any]]:
        with errors.context() as mapping_errors:
            if assert_dict()(value, errors):
                for configuration_key, dumped_configuration_item in value.items():
                    with mapping_errors.context(configuration_key) as item_errors:
                        assertions(dumped_configuration_item, item_errors, configuration_key)
        return mapping_errors.valid
    return _assertion


def assert_fields(fields: Fields) -> ValueAssertion[Any, None]:
    def _assertion(value: Any, errors: ConfigurationErrorCollection) -> None:
        if assert_dict()(value, errors):
            for field in fields:
                with errors.context(field.name):
                    if field.name in value:
                        dumped_configuration_item = value[field.name]
                        field.assertions(dumped_configuration_item, errors, field.name)
                    elif field.required:
                        errors.append(ConfigurationValidationError(_('The key "{configuration_key}" is required.').format(
                            configuration_key=field.name,
                        )))
    return _assertion


def assert_field(field: Field) -> ValueAssertion[Any, None]:
    return assert_fields(Fields(field))


def assert_record(fields: Fields) -> ValueAssertion[Any, None]:
    if not fields:
        raise ValueError('One or more fields are required.')

    def _assertion(value: Any, errors: ConfigurationErrorCollection) -> None:
        with errors.context() as record_errors:
            if assert_dict()(value, errors):
                known_configuration_keys = set(map(lambda x: x.name, fields))
                unknown_configuration_keys = set(value.keys()) - known_configuration_keys
                for unknown_configuration_key in unknown_configuration_keys:
                    with errors.context(unknown_configuration_key) as key_errors:
                        key_errors.append(ConfigurationValidationError(_('Unknown key: {unknown_configuration_key}. Did you mean {known_configuration_keys}?').format(
                            unknown_configuration_key=f'"{unknown_configuration_key}"',
                            known_configuration_keys=', '.join(map(lambda x: f'"{x}"', sorted(known_configuration_keys)))
                        )))
                assert_fields(fields)(value, errors)
        return record_errors.valid
    return _assertion


def assert_path() -> ValueAssertion[Any, Optional[Path]]:
    def _assertion(value: Any, errors: ConfigurationErrorCollection) -> Optional[Path]:
        if assert_str()(value, errors):
            return Path(value).expanduser().resolve()
    return _assertion


def assert_directory_path() -> ValueAssertion[Any, Optional[Path]]:
    def _assertion(value: Any, errors: ConfigurationErrorCollection) -> Optional[Path]:
        if directory_path := assert_path()(value, errors):
            if directory_path.is_dir():
                return directory_path
            errors.append(ConfigurationValidationError(_('"{path}" is not a directory.').format(
                path=value,
            )))
    return _assertion


def assert_locale() -> TypeGuard[str]:
    def _assertion(value: Any, errors: ConfigurationErrorCollection) -> TypeGuard[str]:
        if assert_str()(value, errors):
            try:
                parse_locale(
                    bcp_47_to_rfc_1766(
                        value,  # type: ignore
                    ),
                )
                return True
            except ValueError:
                errors.append(ConfigurationValidationError(_('"{locale}" is not a valid IETF BCP 47 language tag.').format(
                    locale=value,
                )))
        return False
    return _assertion


def assert_setattr(instance: Any, attr_name: str) -> ValueAssertion[Any, None]:
    def _assertion(value: Any, errors: ConfigurationErrorCollection) -> None:
        with errors.catch():
            setattr(instance, attr_name, value)
        return value
    return _assertion


def assert_entity_type() -> ValueAssertion[Any, Type[Entity]]:
    def _assertion(value: Any, errors: ConfigurationErrorCollection) -> Type[Entity]:
        if assert_str()(value, errors):
            try:
                return get_entity_type(value)
            except EntityTypeImportError:
                errors.append(ConfigurationValidationError(_('Cannot find and import "{entity_type}".').format(
                    entity_type=str(value),
                )))
            except EntityTypeInvalidError:
                errors.append(ConfigurationValidationError(
                    _('"{entity_type}" is not a valid Betty entity type.').format(
                        entity_type=str(value),
                    )))
            except EntityTypeError:
                errors.append(ConfigurationValidationError(
                    _('Cannot determine the entity type for "{entity_type}". Did you perhaps make a typo, or could it be that the entity type comes from another package that is not yet installed?').format(
                        entity_type=str(value),
                    )))
    return _assertion
