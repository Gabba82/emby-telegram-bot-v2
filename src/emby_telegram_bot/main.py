import logging

from .runtime import create_runtime_app


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = create_runtime_app()
    app.run(host="0.0.0.0", port=8081)


if __name__ == "__main__":
    run()

