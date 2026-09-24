import os

def _get_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(
            f"Environment variable {name}='{raw}' is not a valid float (expected default: {default})"
        )

class Settings:
    WHISPER_MODEL_SIZE: str = os.environ.get("WHISPER_MODEL_SIZE", "base")
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///./data/meetings.db")
    UPLOAD_DIR: str = os.environ.get("UPLOAD_DIR", "./data/uploads")
    ANSWER_SIMILARITY_THRESHOLD: float = _get_float_env("ANSWER_SIMILARITY_THRESHOLD", 0.1)

settings = Settings()