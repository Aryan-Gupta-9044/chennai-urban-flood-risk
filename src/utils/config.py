import json
from functools import lru_cache
from .paths import CONFIG


@lru_cache(maxsize=1)
def load_settings():
    with open(CONFIG / "settings.json", "r", encoding="utf-8") as f:
        return json.load(f)
