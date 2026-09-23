import shutil
from pathlib import Path
from fastapi import FastAPI, Depends, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import Base, engine, get_db, SessionLocal
from app.config import settings
from app.services.transcription import transcribe_audio
from app.services.answer import generate_answer
from app import models

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


@app.post("/meetings")
def upload_meeting(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    file_path = str(Path(settings.UPLOAD_DIR) / file.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    meeting = models.Meeting(filename=file.filename, status="processing")
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    background_tasks.add_task(process_meeting, meeting.id, file_path)

    return {"id": meeting.id, "filename": meeting.filename, "status": meeting.status}


@app.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        return {"error": "not found"}
    return {"id": meeting.id, "filename": meeting.filename, "status": meeting.status}


class AskRequest(BaseModel):
    question: str


@app.post("/ask")
def ask(request: AskRequest, db: Session = Depends(get_db)):
    return generate_answer(request.question, db)