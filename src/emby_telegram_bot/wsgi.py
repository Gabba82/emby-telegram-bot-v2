import logging

from .runtime import create_runtime_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True)

app = create_runtime_app()
