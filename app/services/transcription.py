import whisper
from app.config import settings

_model = None

def get_model():
    global _model
    if _model is None:
        _model = whisper.load_model(settings.WHISPER_MODEL_SIZE)
    return _model

def transcribe_audio(file_path: str) -> list[dict]:
    model = get_model()
    result = model.transcribe(file_path)
    return [
        {
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"].strip(),
        }
        for seg in result["segments"]
    ]