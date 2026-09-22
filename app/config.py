import os

class Settings:
    WHISPER_MODEL_SIZE: str = os.environ.get("WHISPER_MODEL_SIZE", "base")
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///./data/meetings.db")
    UPLOAD_DIR: str = os.environ.get("UPLOAD_DIR", "./data/uploads")
    ANSWER_SIMILARITY_THRESHOLD: float = float(os.environ.get("ANSWER_SIMILARITY_THRESHOLD", "0.1"))

settings = Settings()