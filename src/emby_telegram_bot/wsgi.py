import logging

from .config import Settings
from .webhook import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True)

settings = Settings.from_env()
app = create_app(settings)
