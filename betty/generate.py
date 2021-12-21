import asyncio
import json
import logging
import multiprocessing
import os
import queue

import dill as pickle
from contextlib import suppress
from pathlib import Path
from typing import Any, Sequence, Type, Awaitable

import aiofiles
from babel.core import Locale
from jinja2 import Environment, TemplateNotFound

from betty.json import JSONEncoder
from betty.model import get_entity_type_name, Entity
from betty.model.ancestry import File, Person, Place, Event, Citation, Source, Note
from betty.openapi import build_specification
from betty.app import App
from betty.string import camel_case_to_kebab_case, camel_case_to_snake_case

_GENERATE_ENTITY_TYPES = {File, Person, Place, Event, Citation, Source}


def getLogger() -> logging.Logger:
    return logging.getLogger(__name__)


class Generator:
    async def generate(self) -> None:
        raise NotImplementedError


async def generate(app: App) -> None:
    await asyncio.gather(
        _generate(app),
        app.dispatcher.dispatch(Generator)(),
    )
    os.chmod(app.configuration.output_directory_path, 0o755)
    for directory_path_str, subdirectory_names, file_names in os.walk(app.configuration.output_directory_path):
        directory_path = Path(directory_path_str)
        for subdirectory_name in subdirectory_names:
            os.chmod(directory_path / subdirectory_name, 0o755)
        for file_name in file_names:
            os.chmod(directory_path / file_name, 0o644)
    await app.wait()


class _GenerateProcess:
    def __init__(self, queue: multiprocessing.Queue, pickled_app: bytes):
        self._queue = queue
        self._pickled_app = pickled_app

    @classmethod
    def do(cls, app: App, queue: multiprocessing.Queue) -> Awaitable[None]:
        pickled_app = pickle.dumps(app)
        # @todo Should we pickle the queue here as well, so as not to do that multiple times?
        return asyncio.gather(*[
            app.do_in_process(cls(queue, pickled_app))
            for i in range(0, app.concurrency)
        ])

    def __call__(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(self._generate())

    async def _generate(self) -> None:
        app = pickle.loads(self._pickled_app)
        while True:
            # @todo This gets a single item from the queue at a time, meaning we still block on I/O...
            # @todo Instead, determine the number of entities we are comfortable rendering in parallel
            # @todo Get that many entities from the queue
            # @todo And put those in asyncio.gather()
            # @todo
            try:
                entity_type, entity_id, locale = self._queue.get_nowait()
            except queue.Empty:
                return
            async with app.with_locale(locale):
                if app.configuration.multilingual:
                    www_directory_path = app.configuration.www_directory_path / app.configuration.locales[locale].alias
                else:
                    www_directory_path = app.configuration.www_directory_path
                await _generate_entity(
                    www_directory_path,
                    app.ancestry.entities[entity_type][entity_id],
                    app,
                    locale,
                )


async def _generate(app: App) -> None:
    logger = getLogger()
    await app.assets.copytree(Path('public') / 'static', app.configuration.www_directory_path)
    await app.renderer.render_tree(app.configuration.www_directory_path)
    entity_manager = multiprocessing.Manager()
    generate_queue = entity_manager.Queue()
    for locale_configuration in app.configuration.locales:
        locale = locale_configuration.locale
        async with app.with_locale(locale):
            if app.configuration.multilingual:
                www_directory_path = app.configuration.www_directory_path / locale_configuration.alias
            else:
                www_directory_path = app.configuration.www_directory_path

            # @todo Can we put these prerequisites in the queue as well?
            # Generate the prerequisites.
            await app.assets.copytree(Path('public') / 'localized', www_directory_path)
            await app.renderer.render_tree(www_directory_path)

            # Generate everything that's not an entity but also not a prerequisite for anything else.
            await asyncio.gather(
                *[
                    # Generate listings for specific entity types.
                    _generate_entity_type_list(
                        www_directory_path,
                        entity_type,
                        app.ancestry.entities[entity_type],
                        app,
                    )
                    for entity_type in _GENERATE_ENTITY_TYPES
                ],
                # Notes are special for now, because we don't want HTML pages for them.
                _generate_entity_type_list_json(www_directory_path, Note, app.ancestry.entities[Note], app),
                *[
                    _generate_entity_json(www_directory_path, note, app, locale)
                    for note in app.ancestry.entities[Note]
                ],
                # Generate OpenAPI documentation.
                _generate_openapi(www_directory_path, app)
            )

        for entity_type in _GENERATE_ENTITY_TYPES:
            for entity in app.ancestry.entities[entity_type]:
                generate_queue.put((entity_type, entity.id, locale))

        locale_label = Locale.parse(locale, '-').get_display_name()
        logger.info(f'Generating pages for {len(app.ancestry.entities[File])} files in {locale_label}...')
        logger.info(f'Generating pages for {len(app.ancestry.entities[Person])} people in {locale_label}...')
        logger.info(f'Generating pages for {len(app.ancestry.entities[Place])} places in {locale_label}...')
        logger.info(f'Generating pages for {len(app.ancestry.entities[Event])} events in {locale_label}...')
        logger.info(f'Generating pages for {len(app.ancestry.entities[Citation])} citations in {locale_label}...')
        logger.info(f'Generating pages for {len(app.ancestry.entities[Source])} sources in {locale_label}...')
        logger.info(f'Generating pages for {len(app.ancestry.entities[Note])} notes in {locale_label}...')
        logger.info(f'Generating OpenAPI documentation in {locale_label}...')

    await _GenerateProcess.do(app, generate_queue)


def _create_file(path: Path) -> object:
    path.parent.mkdir(exist_ok=True, parents=True)
    return aiofiles.open(path, 'w', encoding='utf-8')


def _create_html_resource(path: Path) -> object:
    return _create_file(path / 'index.html')


def _create_json_resource(path: Path) -> object:
    return _create_file(path / 'index.json')


async def _generate_entity_type_list(
        www_directory_path: Path,
        entity_type: Type[Entity],
        entities: Sequence[Any],
        app: App,
) -> None:
    await _generate_entity_type_list_html(
        www_directory_path,
        entity_type,
        entities,
        app.jinja2_environment,
    )
    await _generate_entity_type_list_json(
        www_directory_path,
        entity_type,
        entities,
        app,
    )


async def _generate_entity_type_list_html(
        www_directory_path: Path,
        entity_type: Type[Entity],
        entities: Sequence[Any],
        environment: Environment,
) -> None:
    entity_type_name = get_entity_type_name(entity_type)
    entity_type_fs_name = camel_case_to_kebab_case(entity_type_name)
    entity_type_path = www_directory_path / entity_type_fs_name
    with suppress(TemplateNotFound):
        template = environment.get_template(f'page/list-{entity_type_fs_name}.html.j2')
        rendered_html = template.render({
            'page_resource': '/%s/index.html' % entity_type_name,
            'entity_type_name': entity_type_name,
            'entities': entities,
        })
        async with _create_html_resource(entity_type_path) as f:
            await f.write(rendered_html)


async def _generate_entity_type_list_json(
        www_directory_path: Path,
        entity_type: Type[Entity],
        entities: Sequence[Any],
        app: App,
) -> None:
    entity_type_name = get_entity_type_name(entity_type)
    entity_type_fs_name = camel_case_to_kebab_case(entity_type_name)
    entity_type_path = www_directory_path / entity_type_fs_name
    data = {
        '$schema': app.static_url_generator.generate('schema.json#/definitions/%sCollection' % entity_type_name, absolute=True),
        'collection': []
    }
    for entity in entities:
        data['collection'].append(app.localized_url_generator.generate(
            entity, 'application/json', absolute=True))
    rendered_json = json.dumps(data)
    async with _create_json_resource(entity_type_path) as f:
        await f.write(rendered_json)


async def _generate_entity(
        www_directory_path: Path,
        entity: Entity,
        app: App,
        locale: str,
) -> None:
    await _generate_entity_html(www_directory_path, entity, app.jinja2_environment)
    await _generate_entity_json(www_directory_path, entity, app, locale)


async def _generate_entity_html(
        www_directory_path: Path,
        entity: Entity,
        environment: Environment,
) -> None:
    entity_type_name = get_entity_type_name(entity.entity_type())
    entity_type_fs_name = camel_case_to_kebab_case(entity_type_name)
    entity_path = www_directory_path / entity_type_fs_name / entity.id
    rendered_html = environment.get_template(f'page/{entity_type_fs_name}.html.j2').render({
        'page_resource': entity,
        'entity_type_name': entity_type_name,
        _get_entity_type_jinja2_name(entity_type_name): entity,
    })
    async with _create_html_resource(entity_path) as f:
        await f.write(rendered_html)


async def _generate_entity_json(
        www_directory_path: Path,
        entity: Entity,
        app: App,
        locale: str,
) -> None:
    entity_type_name = get_entity_type_name(entity.entity_type())
    entity_type_fs_name = camel_case_to_kebab_case(entity_type_name)
    entity_path = www_directory_path / entity_type_fs_name / entity.id
    rendered_json = json.dumps(entity, cls=JSONEncoder.get_factory(app, locale))
    async with _create_json_resource(entity_path) as f:
        await f.write(rendered_json)


async def _generate_openapi(
        www_directory_path: Path,
        app: App,
) -> None:
    api_directory_path = www_directory_path / 'api'
    api_directory_path.mkdir(exist_ok=True, parents=True)
    rendered_json = json.dumps(build_specification(app))
    async with _create_json_resource(api_directory_path) as f:
        await f.write(rendered_json)


def _get_entity_type_jinja2_name(entity_type_name: str) -> str:
    return camel_case_to_snake_case(entity_type_name).replace('.', '__')
