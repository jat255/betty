from betty.config import from_file
from betty.asyncio import sync
from betty.generate import generate
from betty.parse import parse
from betty.site import Site
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)

@sync
async def generate_site():
    conf_file = Path(__file__).absolute().parent.parent / 'betty.yml'
    if not conf_file.exists():
        raise FileNotFoundError()
    with open(conf_file) as f:
        configuration = from_file(f)
    async with Site(configuration) as site:
        await parse(site)
        await generate(site)

if __name__ == '__main__':
    generate_site()