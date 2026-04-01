from .config import Settings
from .webhook import create_app

settings = Settings.from_env()
app = create_app(settings)

