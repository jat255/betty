from __future__ import annotations

from typing import TYPE_CHECKING

from betty.app.extension import ConfigurableExtension, UserFacingExtension

if TYPE_CHECKING:
    from betty.builtins import _
    from betty.gramps.gui import _GrampsGuiWidget

from betty.gramps.config import GrampsConfiguration
from betty.gramps.loader import load_file
from betty.gui import GuiBuilder
from betty.load import Loader


class Gramps(ConfigurableExtension[GrampsConfiguration], UserFacingExtension, Loader, GuiBuilder):
    @classmethod
    def default_configuration(cls) -> GrampsConfiguration:
        return GrampsConfiguration()

    async def load(self) -> None:
        for family_tree in self.configuration.family_trees:
            await load_file(self._app.project.ancestry, family_tree.file_path)

    @classmethod
    def label(cls) -> str:
        return 'Gramps'

    @classmethod
    def description(cls) -> str:
        return _('Load <a href="https://gramps-project.org/">Gramps</a> family trees.')

    def gui_build(self) -> _GrampsGuiWidget:
        from betty.gramps.gui import _GrampsGuiWidget

        return _GrampsGuiWidget(self._app)
