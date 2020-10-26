import hashlib
import shutil
from contextlib import suppress
from os import path
from os.path import dirname
from subprocess import check_call
from typing import Optional, List, Tuple, Type, Callable, Iterable, Any

from betty.event import Event
from betty.fs import DirectoryBackup
from betty.html import HtmlProvider
from betty.plugin import Plugin, NO_CONFIGURATION
from betty.generate import PostStaticGenerateEvent
from betty.site import Site


class Maps(Plugin, HtmlProvider):
    def __init__(self, site: Site):
        self._site = site

    @classmethod
    def for_site(cls, site: Site, configuration: Any = NO_CONFIGURATION):
        return cls(site)

    def subscribes_to(self) -> List[Tuple[Type[Event], Callable]]:
        return [
            (PostStaticGenerateEvent, self._render),
        ]

    @property
    def assets_directory_path(self) -> Optional[str]:
        return '%s/assets' % dirname(__file__)

    async def _render(self, _: PostStaticGenerateEvent) -> None:
        build_directory_path = path.join(self._site.configuration.cache_directory_path, self.name(),
                                         hashlib.md5(self.assets_directory_path.encode()).hexdigest(), 'build')

        async with DirectoryBackup(build_directory_path, 'node_modules'):
            with suppress(FileNotFoundError):
                shutil.rmtree(build_directory_path)
            shutil.copytree(path.join(self.assets_directory_path, 'js'), build_directory_path)
            await self._site.assets.copy2(path.join('public', 'static', 'css', 'variables.scss.j2'), path.join(build_directory_path, 'variables.scss.j2'))
        await self._site.renderer.render_tree(build_directory_path)

        self._site.executor.submit(_do_render, build_directory_path, self._site.configuration.www_directory_path)

    @property
    def css_paths(self) -> Iterable[str]:
        return {
            self._site.static_url_generator.generate('css/maps.css'),
        }

    @property
    def js_paths(self) -> Iterable[str]:
        return {
            self._site.static_url_generator.generate('js/maps.js'),
        }


def _do_render(build_directory_path: str, www_directory_path: str) -> None:
    # Install third-party dependencies.
    check_call(['npm', 'install', '--production'], cwd=build_directory_path)

    # Run Webpack.
    check_call(['npm', 'run', 'webpack'], cwd=build_directory_path)
    output_directory_path = path.join(path.dirname(build_directory_path), 'output')
    shutil.copytree(path.join(output_directory_path, 'images'), path.join(www_directory_path, 'images'))
    shutil.copy2(path.join(output_directory_path, 'maps.css'), path.join(www_directory_path, 'css', 'maps.css'))
    shutil.copy2(path.join(output_directory_path, 'maps.js'), path.join(www_directory_path, 'js', 'maps.js'))
