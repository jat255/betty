from pathlib import Path
from typing import Optional, Iterable, Type

from reactives import reactive

from betty.config import Configuration, DumpedConfigurationImport, DumpedConfigurationExport, ConfigurationSequence, \
    ConfigurationT
from betty.config.dump import minimize_dict
from betty.config.load import Loader, Field
from betty.os import PathLike


class FamilyTreeConfiguration(Configuration):
    def __init__(self, file_path: Optional[PathLike] = None):
        super().__init__()
        self.file_path = file_path

    def __eq__(self, other):
        if not isinstance(other, FamilyTreeConfiguration):
            return False
        return self._file_path == other.file_path

    @reactive  # type: ignore
    @property
    def file_path(self) -> Optional[Path]:
        return self._file_path

    @file_path.setter
    def file_path(self, file_path: Optional[PathLike]) -> None:
        self._file_path = Path(file_path) if file_path else None

    def load(self, dumped_configuration: DumpedConfigurationImport, loader: Loader) -> None:
        loader.assert_record(dumped_configuration, {
            'file': Field(
                True,
                loader.assert_path,  # type: ignore
                lambda x: loader.assert_setattr(self, 'file_path', x)
            )
        })

    def dump(self) -> DumpedConfigurationExport:
        return {
            'file': str(self.file_path),
        }


class FamilyTreeConfigurationSequence(ConfigurationSequence[FamilyTreeConfiguration]):
    @classmethod
    def _item_type(cls) -> Type[ConfigurationT]:
        return FamilyTreeConfiguration


class GrampsConfiguration(Configuration):
    def __init__(self, family_trees: Optional[Iterable[FamilyTreeConfiguration]] = None):
        super().__init__()
        self._family_trees = FamilyTreeConfigurationSequence(family_trees)
        self._family_trees.react(self)

    @property
    def family_trees(self) -> FamilyTreeConfigurationSequence:
        return self._family_trees

    def load(self, dumped_configuration: DumpedConfigurationImport, loader: Loader) -> None:
        loader.assert_record(dumped_configuration, {
            'family_trees': Field(
                True,
                self._family_trees.load,  # type: ignore
            ),
        })

    def dump(self) -> DumpedConfigurationExport:
        return minimize_dict({
            'family_trees': self.family_trees.dump(),
        }, True)
