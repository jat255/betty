from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Type, List, cast, Iterable, Tuple, Any
from urllib.parse import urlparse

from babel.core import Locale
from reactives import reactive, scope

from betty.app import Extension, ConfigurableExtension
from betty.config import Configuration, DumpedConfigurationImport, Configurable, FileBasedConfiguration, \
    ConfigurationMapping, DumpedConfigurationExport, DumpedConfigurationDict, ConfigurationSequence, ConfigurationT, \
    ConfigurationErrorCollection
from betty.config.dump import minimize_dict, void_none
from betty.config.load import ConfigurationValidationError, Field, assert_entity_type, assert_dict, Assertions, \
    assert_str, assert_setattr, assert_bool, assert_int, assert_record, Fields, ValueAssertion, \
    assert_field
from betty.locale import bcp_47_to_rfc_1766
from betty.model import Entity, get_entity_type_name, UserFacingEntity
from betty.model.ancestry import Ancestry, Person, Event, Place, Source
from betty.typing import Void

try:
    from typing_extensions import Self, TypeGuard
except ModuleNotFoundError:
    from typing import Self, TypeGuard  # type: ignore

if TYPE_CHECKING:
    from betty.builtins import _


class EntityReference(Configuration):
    def __init__(self, entity_type: Optional[Type[Entity]] = None, entity_id: Optional[str] = None, /, entity_type_is_constrained: bool = False):
        super().__init__()
        self._entity_type = entity_type
        self._entity_id = entity_id
        self._entity_type_is_constrained = entity_type_is_constrained

    @reactive  # type: ignore
    @property
    def entity_type(self) -> Optional[Type[Entity]]:
        return self._entity_type

    @entity_type.setter
    def entity_type(self, entity_type: Optional[Type[Entity]]) -> None:
        if self._entity_type_is_constrained:
            raise AttributeError(f'The entity type cannot be set, as it is already constrained to {self._entity_type}.')
        self._entity_type = entity_type

    @reactive  # type: ignore
    @property
    def entity_id(self) -> Optional[str]:
        return self._entity_id

    @entity_id.setter
    def entity_id(self, entity_id: str) -> None:
        self._entity_id = entity_id

    @entity_id.deleter
    def entity_id(self) -> None:
        self._entity_id = None

    @property
    def entity_type_is_constrained(self) -> bool:
        return self._entity_type_is_constrained

    def update(self, other: Self) -> None:
        self.entity_type = other.entity_type
        self._entity_type_is_constrained = other.entity_type_is_constrained
        self.entity_id = other.entity_id

    @classmethod
    def load(cls, dumped_configuration: DumpedConfigurationImport, errors: ConfigurationErrorCollection) -> Optional[Self]:
        configuration = cls()
        if isinstance(dumped_configuration, dict):
            assert_record(Fields(
                Field('entity_type', True, Assertions(assert_entity_type(), assert_setattr(configuration, 'entity_type'))),
                Field('entity_id', False, Assertions(assert_str(), assert_setattr(configuration, 'entity_id'))),
            ))(dumped_configuration, )
        elif assert_str()(dumped_configuration, errors):
            assert_setattr(configuration, 'entity_id')(dumped_configuration, errors)
        return configuration

    def dump(self) -> DumpedConfigurationExport:
        if self.entity_type_is_constrained:
            return void_none(self.entity_id)

        if self.entity_type is None or self.entity_id is None:
            return Void

        return {
            'entity_type': get_entity_type_name(self._entity_type),
            'entity_id': self._entity_id,
        }

    @scope.register_self
    def __eq__(self, other) -> bool:
        if not isinstance(other, EntityReference):
            return NotImplemented
        return self.entity_type == other.entity_type and self.entity_id == other.entity_id


class EntityReferenceSequence(ConfigurationSequence[EntityReference]):
    def __init__(self, entity_references: Optional[List[EntityReference]] = None, /, entity_type_constraint: Optional[Type[Entity]] = None):
        self._entity_type_constraint = entity_type_constraint
        super().__init__(entity_references)

    @classmethod
    def _item_type(cls) -> Type[ConfigurationT]:
        return EntityReference

    def _on_add(self, entity_reference: EntityReference) -> None:
        super()._on_add(entity_reference)
        if self._entity_type_constraint:
            if entity_reference.entity_type != self._entity_type_constraint or not entity_reference.entity_type_is_constrained:
                raise ConfigurationValidationError(_('The entity reference must be constrained to {entity_type} entities.').format(
                    entity_type=self._entity_type_constraint.entity_type_label() if issubclass(self._entity_type_constraint, UserFacingEntity) else get_entity_type_name(self._entity_type_constraint),
                ))


class ExtensionConfiguration(Configuration):
    def __init__(self, extension_type: Type[Extension], enabled: bool = True, extension_configuration: Optional[Configuration] = None):
        super().__init__()
        self._extension_type = extension_type
        self._enabled = enabled
        if extension_configuration is None and issubclass(extension_type, ConfigurableExtension):
            extension_configuration = extension_type.default_configuration()
        if extension_configuration is not None:
            extension_configuration.react(self)
        self._extension_configuration = extension_configuration

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        if self.extension_type != other.extension_type:
            return False
        if self.enabled != other.enabled:
            return False
        if self.extension_configuration != other.extension_configuration:
            return False
        return True

    @property
    def extension_type(self) -> Type[Extension]:
        return self._extension_type

    @reactive  # type: ignore
    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    @property
    def extension_configuration(self) -> Optional[Configuration]:
        return self._extension_configuration

    def update(self, other: Self) -> None:
        raise NotImplementedError

    @classmethod
    def load(cls, dumped_configuration: DumpedConfigurationImport, errors: ConfigurationErrorCollection) -> Optional[Self]:
        if not assert_field(Field('extension', True)):
            return
        configuration = cls(dumped_configuration['extension'])
        assert_record(Fields(
            Field('enabled', False, Assertions(assert_bool(), assert_setattr(configuration, 'enabled'))),
            Field('configuration', False, Assertions(cls.configuration._assert_extension_configuration())),
        ))(dumped_configuration, errors)
        return configuration

    @classmethod
    def _assert_extension_configuration(cls, extension_type: Type[Extension]) -> ValueAssertion[Any, None]:
        def _assertion(value: Any, errors: ConfigurationErrorCollection) -> None:
            if issubclass(extension_type, ConfigurableExtension):
                cast(ExtensionConfiguration, extension_type).load(value, errors)
                return True
            errors.append(ConfigurationValidationError(_('{extension_type} is not configurable.').format(
                extension_type=extension_type.name(),
            )))
        return _assertion

    def dump(self) -> DumpedConfigurationExport:
        return minimize_dict({
            'extension': self.extension_type,
            'enabled': self.enabled,
            'configuration': self.extension_configuration.dump() if issubclass(self.extension_type, Configurable) and self.extension_configuration else Void,
        }, True)


class ExtensionConfigurationMapping(ConfigurationMapping[Type[Extension], ExtensionConfiguration]):
    def __init__(self, configurations: Optional[Iterable[ExtensionConfiguration]] = None):
        super().__init__(configurations, default_factory=ExtensionConfiguration)

    def _get_key(self, configuration: ExtensionConfiguration) -> Type[Extension]:
        return configuration.extension_type

    @classmethod
    def _load_key(cls, dumped_item: DumpedConfigurationImport, errors: ConfigurationErrorCollection, dumped_key: str) -> DumpedConfigurationImport:
        if assert_dict()(dumped_item, errors):
            dumped_item['extension'] = dumped_key
            return dumped_item

    def _dump_key(self, dumped_item: DumpedConfigurationDict) -> Tuple[DumpedConfigurationExport, str]:
        dumped_key = dumped_item.pop('extension')
        return dumped_item, dumped_key

    def enable(self, *extension_types: Type[Extension]):
        for extension_type in extension_types:
            try:
                self._configurations[extension_type].enabled = True
            except KeyError:
                self.append(ExtensionConfiguration(extension_type, True))

    def disable(self, *extension_types: Type[Extension]):
        for extension_type in extension_types:
            with suppress(KeyError):
                self._configurations[extension_type].enabled = False


class EntityTypeConfiguration(Configuration):
    def __init__(self, entity_type: Type[Entity], generate_html_list: Optional[bool] = None):
        super().__init__()
        self._entity_type = entity_type
        self.generate_html_list = generate_html_list

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        if self.entity_type != other.entity_type:
            return False
        if self.generate_html_list != other.generate_html_list:
            return False
        return True

    @property
    def entity_type(self) -> Type[Entity]:
        return self._entity_type

    @reactive  # type: ignore
    @property
    def generate_html_list(self) -> bool:
        return self._generate_html_list or False

    @generate_html_list.setter
    def generate_html_list(self, generate_html_list: Optional[bool]) -> None:
        if generate_html_list and not issubclass(self._entity_type, UserFacingEntity):
            raise ConfigurationValidationError('Cannot generate HTML pages for entity types that are not user-facing.')
        self._generate_html_list = generate_html_list

    @classmethod
    def load(cls, dumped_configuration: DumpedConfigurationImport, loader: Loader) -> Self:
        # @todo We still have the problem of how to pass on primary keys to loaders. We purposefully extract them as part of the serialization
        # @todo so they can become mapping keys.
        # @todo Perhaps we can come up with a generic solution for that, transforming the key into a dictionary field as part of the parent collection's loading process
        # @todo Items will then become reusable components, able to stand alone (with their primary key inside the dumped config), or as part of a collection,
        # @todo with the primary key outside the dumped config, as a collection key.
        # @todo
        # @todo
        configuration = cls()
        loader.assert_record(dumped_configuration, (
            Field('generate_html_list', False, (loader.assert_bool, loader.assert_setattr(configuration, 'generate_html_list'))),
        ))
        return configuration

    def dump(self) -> DumpedConfigurationExport:
        return minimize_dict({
            'generate_html_list': Void if self._generate_html_list is None else self._generate_html_list,
        }, True)


class EntityTypeConfigurationMapping(ConfigurationMapping[Type[Entity], EntityTypeConfiguration]):
    def _get_key(self, configuration: EntityTypeConfiguration) -> Type[Entity]:
        return configuration.entity_type

    def _load_key(self, dumped_configuration_key: str, errors: ConfigurationErrorCollection) -> Optional[Type[Entity]]:
        return assert_entity_type()(dumped_configuration_key, errors)

    def _dump_key(self, configuration_key: Type[Entity]) -> str:
        return get_entity_type_name(configuration_key)

    @classmethod
    def _item_type(cls) -> Type[EntityTypeConfiguration]:
        return EntityTypeConfiguration


class LocaleConfiguration(Configuration):
    def __init__(self, locale: str, alias: Optional[str] = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._locale = locale
        if alias is not None and '/' in alias:
            raise ConfigurationValidationError(_('Locale aliases must not contain slashes.'))
        self._alias = alias

    def __repr__(self):
        return '<%s.%s(%s, %s)>' % (self.__class__.__module__, self.__class__.__name__, self.locale, self.alias)

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        if self.locale != other.locale:
            return False
        if self.alias != other.alias:
            return False
        return True

    def __hash__(self):
        return hash((self._locale, self._alias))

    @property
    def locale(self) -> str:
        return self._locale

    @reactive
    @property
    def alias(self) -> str:
        if self._alias is None:
            return self.locale
        return self._alias

    @alias.setter
    def alias(self, alias: Optional[str]) -> None:
        self._alias = alias

    def update(self, other: Self) -> None:
        self.alias = other._alias

    @classmethod
    def load(cls, dumped_configuration: DumpedConfigurationImport, errors: ConfigurationErrorCollection) -> Optional[Self]:
        if locale := assert_field(Field('locale', True, Assertions(assert_str()))):
            configuration = cls(cast(str, locale))
            assert_record(Fields(
                Field('locale', True, Assertions()),
                Field('alias', False, Assertions(assert_str(), assert_setattr(configuration, 'alias'))),
            ))(dumped_configuration, errors)
            return configuration

    def dump(self) -> DumpedConfigurationExport:
        return minimize_dict({
            'locale': self.locale,
            'alias': void_none(self._alias)
        })


class LocaleConfigurationMapping(ConfigurationMapping[str, LocaleConfiguration]):
    def __init__(self, configurations: Optional[Iterable[LocaleConfiguration]] = None):
        super().__init__(configurations)
        if len(self) == 0:
            self.append(LocaleConfiguration('en-US'))

    def _get_key(self, locale: LocaleConfiguration) -> str:
        return locale.locale

    # @todo Add a KeyedConfigurationMapping(ConfigurationMapping) that implements _load_key() and _dump_key() and can alter error contexts.
    # @todo However, for generic
    # @todo
    # @todo HOLD THE PRESSES
    # @todo self._get_key()!!! ConfigurationMapping already assumes the key comes from the config. All good here!
    # @todo
    @classmethod
    def _load_key(cls, dumped_item: DumpedConfigurationImport, errors: ConfigurationErrorCollection, dumped_key: str) -> DumpedConfigurationImport:
        if assert_dict()(dumped_item):
            dumped_item['locale'] = dumped_key
        return dumped_item

    def _dump_key(self, dumped_item: DumpedConfigurationExport) -> Tuple[DumpedConfigurationExport, str]:
        locale = dumped_item.pop('locale')
        return dumped_item, locale

    @classmethod
    def _item_type(cls) -> Type[LocaleConfiguration]:
        return LocaleConfiguration

    def _on_remove(self, locale: LocaleConfiguration) -> None:
        if len(self._configurations) <= 1:
            raise ConfigurationValidationError(_('Cannot remove the last remaining locale {locale}').format(
                locale=Locale.parse(bcp_47_to_rfc_1766(locale.locale)).get_display_name()),
            )

    @reactive  # type: ignore
    @property
    def default(self) -> LocaleConfiguration:
        return next(self.values())

    @default.setter
    def default(self, configuration: LocaleConfiguration) -> None:
        # @todo Make sure this locale does not already exist. Then move it to the beginning.
        self._configurations[configuration.locale] = configuration
        self._configurations.move_to_end(configuration.locale, False)
        self.react.trigger()


class ProjectConfiguration(FileBasedConfiguration):
    def __init__(self, base_url: Optional[str] = None):
        super().__init__()
        self._base_url = 'https://example.com' if base_url is None else base_url
        self._root_path = ''
        self._clean_urls = False
        self._content_negotiation = False
        self._title = 'Betty'
        self._author: Optional[str] = None
        self._entity_types = EntityTypeConfigurationMapping([
            EntityTypeConfiguration(Person, True),
            EntityTypeConfiguration(Event, True),
            EntityTypeConfiguration(Place, True),
            EntityTypeConfiguration(Source, True),
        ])
        self._entity_types.react(self)
        self._extensions = ExtensionConfigurationMapping()
        self._extensions.react(self)
        self._debug = False
        self._locales = LocaleConfigurationMapping()
        self._locales.react(self)
        self._lifetime_threshold = 125

    @property
    def project_directory_path(self) -> Path:
        return self.configuration_file_path.parent

    @reactive  # type: ignore
    @property
    def output_directory_path(self) -> Path:
        return self.project_directory_path / 'output'

    @reactive  # type: ignore
    @property
    def assets_directory_path(self) -> Path:
        return self.project_directory_path / 'assets'

    @property
    def www_directory_path(self) -> Path:
        return self.output_directory_path / 'www'

    @reactive  # type: ignore
    @property
    def title(self) -> str:
        return self._title

    @title.setter
    def title(self, title: str) -> None:
        self._title = title

    @reactive  # type: ignore
    @property
    def author(self) -> Optional[str]:
        return self._author

    @author.setter
    def author(self, author: Optional[str]) -> None:
        self._author = author

    @reactive  # type: ignore
    @property
    def base_url(self) -> str:
        return self._base_url

    @base_url.setter
    def base_url(self, base_url: str) -> None:
        base_url_parts = urlparse(base_url)
        if not base_url_parts.scheme:
            raise ConfigurationValidationError(_('The base URL must start with a scheme such as https://, http://, or file://.'))
        if not base_url_parts.netloc:
            raise ConfigurationValidationError(_('The base URL must include a path.'))
        self._base_url = '%s://%s' % (base_url_parts.scheme, base_url_parts.netloc)

    @reactive  # type: ignore
    @property
    def root_path(self) -> str:
        return self._root_path

    @root_path.setter
    def root_path(self, root_path: str) -> None:
        self._root_path = root_path.strip('/')

    @reactive  # type: ignore
    @property
    def content_negotiation(self) -> bool:
        return self._content_negotiation

    @content_negotiation.setter
    def content_negotiation(self, content_negotiation: bool):
        self._content_negotiation = content_negotiation

    @reactive  # type: ignore
    @property
    def clean_urls(self) -> bool:
        return self._clean_urls or self.content_negotiation

    @clean_urls.setter
    def clean_urls(self, clean_urls: bool) -> None:
        self._clean_urls = clean_urls

    @reactive  # type: ignore
    @property
    def locales(self) -> LocaleConfigurationMapping:
        return self._locales

    @property
    def multilingual(self) -> bool:
        return len(self.locales) > 1

    @property
    def entity_types(self) -> EntityTypeConfigurationMapping:
        return self._entity_types

    @property
    def extensions(self) -> ExtensionConfigurationMapping:
        return self._extensions

    @reactive  # type: ignore
    @property
    def debug(self) -> bool:
        return self._debug

    @debug.setter
    def debug(self, debug: bool) -> None:
        self._debug = debug

    @reactive  # type: ignore
    @property
    def lifetime_threshold(self) -> int:
        return self._lifetime_threshold

    @lifetime_threshold.setter
    def lifetime_threshold(self, lifetime_threshold: int) -> None:
        if lifetime_threshold <= 0:
            raise ConfigurationValidationError(_('This must be a positive number.'))
        self._lifetime_threshold = lifetime_threshold

    def update(self, other: Self) -> None:
        self.base_url = other.base_url
        self.title = other.title
        self.author = other.author
        self.root_path = other.root_path
        self.clean_urls = other.clean_urls
        self.content_negotiation = other.content_negotiation
        self.debug = other.debug
        self.lifetime_threshold = other.lifetime_threshold
        self.locales.update(other.locales)
        self.extensions.update(other.extensions)
        self.entity_types.update(other.entity_types)

    @classmethod
    def load(cls, dumped_configuration: DumpedConfigurationImport, errors: ConfigurationErrorCollection) -> Optional[Self]:
        configuration = cls()
        assert_record(Fields(
            Field('base_url', True, Assertions(assert_str(), assert_setattr(configuration, 'base_url'))),
            Field('title', False, Assertions(assert_str(), assert_setattr(configuration, 'title'))),
            Field('author', False, Assertions(assert_str(), assert_setattr(configuration, 'author'))),
            Field('root_path', False, Assertions(assert_str(), assert_setattr(configuration, 'root_path'))),
            Field('clean_urls', False, Assertions(assert_bool(), assert_setattr(configuration, 'clean_urls'))),
            Field('content_negotiation', False, Assertions(assert_bool(), assert_setattr(configuration, 'content_negotiation'))),
            Field('debug', False, Assertions(assert_bool(), assert_setattr(configuration, 'debug'))),
            Field('lifetime_threshold', False, Assertions(assert_int(), assert_setattr(configuration, 'lifetime_threshold'))),
            Field('locales', False, Assertions(configuration._locales.load)),
            Field('extensions', False, Assertions(configuration._extensions.load)),
            Field('entity_types', False, Assertions(configuration._entity_types.load)),
        ))(dumped_configuration, errors)
        return configuration

    def dump(self) -> DumpedConfigurationExport:
        return minimize_dict({
            'base_url': self.base_url,
            'title': self.title,
            'root_path': void_none(self.root_path),
            'clean_urls': void_none(self.clean_urls),
            'author': void_none(self.author),
            'content_negotiation': void_none(self.content_negotiation),
            'debug': void_none(self.debug),
            'lifetime_threshold': void_none(self.lifetime_threshold),
            'locales': self.locales.dump(),
            'extensions': self.extensions.dump(),
            'entity_types': self.entity_types.dump(),
        }, True)


class Project(Configurable[ProjectConfiguration]):
    def __init__(self):
        super().__init__()
        self._configuration = ProjectConfiguration()
        self._ancestry = Ancestry()

    @property
    def ancestry(self) -> Ancestry:
        return self._ancestry
