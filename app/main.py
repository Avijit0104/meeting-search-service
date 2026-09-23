import shutil
from pathlib import Path
from fastapi import FastAPI, Depends, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from app.database import Base, engine, get_db, SessionLocal
from app.config import settings
from app.services.transcription import transcribe_audio
from app import models
from app.services.answer import generate_answer

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Meeting Search Service")

Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)


@app.get("/health")
def health():
    return {"status": "ok"}


def process_meeting(meeting_id: int, file_path: str):
    db = SessionLocal()
    try:
        meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
        segments = transcribe_audio(file_path)
        for seg in segments:
            db.add(models.TranscriptSegment(
                meeting_id=meeting_id,
                start_time=seg["start"],
                end_time=seg["end"],
                text=seg["text"],
            ))
        meeting.status = "completed"
        db.commit()
    except Exception:
        meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
        meeting.status = "failed"
        db.commit()
        raise
    finally:
        db.close()


from pydantic import BaseModel

class AskRequest(BaseModel):
    question: str

@app.post("/ask")
def ask(request: AskRequest, db: Session = Depends(get_db)):
    return generate_answer(request.question, db)

@app.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        return {"error": "not found"}
    return {"id": meeting.id, "filename": meeting.filename, "status": meeting.status}


@app.post("/ask")
def ask():
    # stub — real retrieval + answer generation comes in Phase 4/5
    return {"message": "not implemented yet"}