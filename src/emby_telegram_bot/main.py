import logging

from .config import Settings
from .webhook import create_app


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_env()
    app = create_app(settings)
    app.run(host="0.0.0.0", port=8081)


if __name__ == "__main__":
    run()

