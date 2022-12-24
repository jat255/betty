from betty.app import App, AppConfiguration
from betty.asyncio import sync
from betty.generate import generate
from betty.load import load

from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)


@sync
async def generate_site():
    conf_file = Path(__file__).absolute().parent.parent / 'betty.yml'
    if not conf_file.exists():
        raise FileNotFoundError()
    with App() as app:
        app.project.configuration.read(conf_file)
        await load(app)
        await generate(app)

if __name__ == '__main__':
    generate_site()
