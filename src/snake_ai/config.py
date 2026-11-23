"""Load shareable settings separately from local credentials."""
import os
from pathlib import Path

from dotenv import dotenv_values

SETTINGS = (
    "AI_PROVIDER", "LOCAL_AI_MODEL_NAME", "OLLAMA_BASE_URL",
    "OPENROUTER_MODEL_NAME", "OPENROUTER_BASE_URL", "AI_TIMEOUT_SECONDS", "AI_LOG_DIR", "GAME_SPEED",
)


def load_configuration(directory=None):
    directory = Path.cwd() if directory is None else Path(directory)
    # Read only non-secret, recognized settings from the shareable file.
    config = dotenv_values(directory / ".config", interpolate=False)
    for key in SETTINGS:
        if config.get(key) is not None:
            os.environ[key] = config[key]
    # A key exported by the caller retains priority over the local secret file.
    secrets = dotenv_values(directory / ".env", interpolate=False)
    if secrets.get("OPENROUTER_API_KEY") is not None:
        os.environ.setdefault("OPENROUTER_API_KEY", secrets["OPENROUTER_API_KEY"])
