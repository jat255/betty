from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from importlib.metadata import entry_points, EntryPoint
from pathlib import Path
from typing import Type, Set, Optional, Any, List, Dict, TypeVar, Union, Iterable, TYPE_CHECKING, Generic, \
    Iterator, Sequence

try:
    from typing_extensions import Self
except ModuleNotFoundError:
    from typing import Self  # type: ignore

from reactives import reactive, scope
from reactives.factory.type import ReactiveInstance

from betty import fs
from betty.config import ConfigurationT, Configurable
from betty.dispatch import Dispatcher, TargetedDispatcher
from betty.importlib import import_any
from betty.app.extension.requirement import Requirement

if TYPE_CHECKING:
    from betty.app import App
    from betty.builtins import _


class CyclicDependencyError(BaseException):
    def __init__(self, extension_types: Iterable[Type[Extension]]):
        extension_names = ', '.join([extension.name() for extension in extension_types])
        super().__init__(f'The following extensions have cyclic dependencies: {extension_names}')


class Dependencies(Requirement):
    def __init__(self, dependent_type: Type[Extension]):
        self._dependent_type = dependent_type

    @classmethod
    def for_dependent(cls, dependent_type: Type[Extension]) -> Self:  # type: ignore
        return cls(dependent_type)

    def is_met(self) -> bool:
        for dependency_type in self._dependent_type.depends_on():
            try:
                if not dependency_type.enable_requirement().is_met():
                    return False
            except RecursionError:
                raise CyclicDependencyError([dependency_type])
        return True

    def summary(self) -> str:
        return _('{dependent_label} requires {dependency_labels}.').format(
            dependent_label=format_extension_type(self._dependent_type),
            dependency_labels=', '.join(map(format_extension_type, self._dependent_type.depends_on())),
        )


class Dependents(Requirement):
    def __init__(self, dependency: Extension, dependents: Iterable[Extension]):
        self._dependency = dependency
        self._dependents = dependents

    def summary(self) -> str:
        return _('{dependency_label} is required by {dependency_labels}.').format(
            dependency_label=format_extension_type(type(self._dependency)),
            dependent_labels=', '.join(
                map(
                    format_extension_type,
                    map(type, self._dependents),  # type: ignore
                )
            ),
        )

    def is_met(self) -> bool:
        # This class is never instantiated unless there is at least one enabled dependent, which means this requirement
        # is always met.
        return True

    @classmethod
    def for_dependency(cls, dependency: Extension) -> Self:  # type: ignore
        dependents = [
            dependency.app.extensions[extension_type]
            for extension_type
            in discover_extension_types()
            if dependency in extension_type.depends_on() and extension_type in dependency.app.extensions
        ]
        return cls(dependency, dependents)


class Extension:
    """
    Integrate optional functionality with the Betty app.
    """

    def __init__(self, app: App, *args, **kwargs):
        assert type(self) != Extension
        super().__init__(*args, **kwargs)
        self._app = app

    @classmethod
    def name(cls) -> str:
        return '%s.%s' % (cls.__module__, cls.__name__)

    @classmethod
    def depends_on(cls) -> Set[Type[Extension]]:
        return set()

    @classmethod
    def comes_after(cls) -> Set[Type[Extension]]:
        return set()

    @classmethod
    def comes_before(cls) -> Set[Type[Extension]]:
        return set()

    @classmethod
    def enable_requirement(cls) -> Requirement:
        """
        Define the requirement for this extension to be enabled.

        This defaults to the extension's dependencies.
        """
        return Dependencies.for_dependent(cls)

    def disable_requirement(self) -> Requirement:
        """
        Define the requirement for this extension to be disabled.

        This defaults to the extension's dependents.
        """
        return Dependents.for_dependency(self)

    @classmethod
    def assets_directory_path(cls) -> Optional[Path]:
        return None

    @property
    def cache_directory_path(self) -> Path:
        return fs.CACHE_DIRECTORY_PATH / self.name()

    @property
    def app(self) -> App:
        return self._app


ExtensionT = TypeVar('ExtensionT', bound=Extension)


class UserFacingExtension(Extension):
    @classmethod
    def label(cls) -> str:
        raise NotImplementedError

    @classmethod
    def description(cls) -> str:
        raise NotImplementedError


class Theme(UserFacingExtension):
    pass


def format_extension_type(extension_type: Type[Extension]) -> str:
    if isinstance(extension_type, UserFacingExtension):
        return f'{extension_type.label()} ({extension_type.name()})'
    return extension_type.name()


class ConfigurableExtension(Extension, Generic[ConfigurationT], Configurable[ConfigurationT]):
    def __init__(self, *args, **kwargs):
        assert type(self) != ConfigurableExtension
        if 'configuration' not in kwargs or kwargs['configuration'] is None:
            kwargs['configuration'] = self.default_configuration()
        super().__init__(*args, **kwargs)

    @classmethod
    def default_configuration(cls) -> ConfigurationT:
        raise NotImplementedError


@reactive
class Extensions(ReactiveInstance):
    def __getitem__(self, extension_type: Union[Type[ExtensionT], str]) -> ExtensionT:
        raise NotImplementedError

    def __iter__(self) -> Iterator[Iterator[Extension]]:
        raise NotImplementedError

    def flatten(self) -> Iterator[Extension]:
        raise NotImplementedError

    def __contains__(self, extension_type: Union[Type[Extension], str, Any]) -> bool:
        raise NotImplementedError


class ListExtensions(Extensions):
    def __init__(self, extensions: List[List[Extension]]):
        super().__init__()
        self._extensions = extensions

    @scope.register_self
    def __getitem__(self, extension_type: Union[Type[ExtensionT], str]) -> ExtensionT:
        if isinstance(extension_type, str):
            extension_type = import_any(extension_type)
        for extension in self.flatten():
            if type(extension) == extension_type:
                return extension  # type: ignore
        raise KeyError(f'Unknown extension of type "{extension_type}"')

    @scope.register_self
    def __iter__(self) -> Iterator[Iterator[Extension]]:
        # Use a generator so we discourage calling code from storing the result.
        for batch in self._extensions:
            yield (extension for extension in batch)

    def flatten(self) -> Iterator[Extension]:
        for batch in self:
            yield from batch

    @scope.register_self
    def __contains__(self, extension_type: Union[Type[Extension], str]) -> bool:
        if isinstance(extension_type, str):
            try:
                extension_type = import_any(extension_type)
            except ImportError:
                return False
        for extension in self.flatten():
            if type(extension) == extension_type:
                return True
        return False


class ExtensionDispatcher(Dispatcher):
    def __init__(self, extensions: Extensions):
        self._extensions = extensions

    def dispatch(self, target_type: Type) -> TargetedDispatcher:
        target_method_names = [method_name for method_name in dir(target_type) if not method_name.startswith('_')]
        if len(target_method_names) != 1:
            raise ValueError(f"A dispatch's target type must have a single method to dispatch to, but {target_type} has {len(target_method_names)}.")
        target_method_name = target_method_names[0]

        async def _dispatch(*args, **kwargs) -> List[Any]:
            return [
                result
                for target_extension_batch
                in self._extensions
                for result
                in await asyncio.gather(*[
                    getattr(target_extension, target_method_name)(*args, **kwargs)
                    for target_extension in target_extension_batch
                    if isinstance(target_extension, target_type)
                ])
            ]
        return _dispatch


ExtensionTypeGraph = Dict[Type[Extension], Set[Type[Extension]]]


def build_extension_type_graph(extension_types: Iterable[Type[Extension]]) -> ExtensionTypeGraph:
    extension_types_graph: ExtensionTypeGraph = defaultdict(set)
    # Add dependencies to the extension graph.
    for extension_type in extension_types:
        _extend_extension_type_graph(extension_types_graph, extension_type)
    # Now all dependencies have been collected, extend the graph with optional extension orders.
    for extension_type in extension_types:
        for before in extension_type.comes_before():
            if before in extension_types_graph:
                extension_types_graph[before].add(extension_type)
        for after in extension_type.comes_after():
            if after in extension_types_graph:
                extension_types_graph[extension_type].add(after)

    return extension_types_graph


def _extend_extension_type_graph(graph: Dict, extension_type: Type[Extension]) -> None:
    dependencies = extension_type.depends_on()
    # Ensure each extension type appears in the graph, even if they're isolated.
    graph.setdefault(extension_type, set())
    for dependency in dependencies:
        seen_dependency = dependency in graph
        graph[extension_type].add(dependency)
        if not seen_dependency:
            _extend_extension_type_graph(graph, dependency)


def discover_extension_types() -> Set[Type[Extension]]:
    betty_entry_points: Sequence[EntryPoint]
    if (sys.version_info.major, sys.version_info.minor) >= (3, 10):
        betty_entry_points = entry_points(group='betty.extensions')  # type: ignore
    else:
        betty_entry_points = entry_points()['betty.extensions']
    return {import_any(betty_entry_point.value) for betty_entry_point in betty_entry_points}
