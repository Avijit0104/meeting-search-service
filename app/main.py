import shutil
from pathlib import Path
from fastapi import FastAPI, Depends, UploadFile, File, BackgroundTasks, HTTPException
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

AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".mp4"}

def looks_like_audio(file: UploadFile) -> bool:
    if file.content_type and file.content_type.startswith("audio/"):
        return True
    ext = Path(file.filename).suffix.lower()
    return ext in AUDIO_EXTENSIONS

@app.post("/meetings")
def upload_meeting(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    if not looks_like_audio(file):
        raise HTTPException(
            status_code=400,
            detail=f"Doesn't look like an audio file (content-type: {file.content_type}, filename: {file.filename})",
        )

    meeting = models.Meeting(filename=file.filename, status="processing")
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    # store on disk under a name unique to this meeting, independent of the
    # original filename, so two uploads with the same name never collide
    ext = Path(file.filename).suffix
    stored_filename = f"{meeting.id}{ext}"
    file_path = str(Path(settings.UPLOAD_DIR) / stored_filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    background_tasks.add_task(process_meeting, meeting.id, file_path)

    return {"id": meeting.id, "filename": meeting.filename, "status": meeting.status}


@app.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return {"id": meeting.id, "filename": meeting.filename, "status": meeting.status}

class AskRequest(BaseModel):
    question: str


@app.post("/ask")
def ask(request: AskRequest, db: Session = Depends(get_db)):
    return generate_answer(request.question, db)



@app.get("/meetings/{meeting_id}/transcript")
def get_transcript(meeting_id: int, db: Session = Depends(get_db)):
    meeting = db.query(models.Meeting).filter(models.Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    if meeting.status != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Transcript not available yet (status: {meeting.status})",
        )

    segments = (
        db.query(models.TranscriptSegment)
        .filter(models.TranscriptSegment.meeting_id == meeting_id)
        .order_by(models.TranscriptSegment.start_time)
        .all()
    )

    return {
        "meeting_id": meeting.id,
        "filename": meeting.filename,
        "segments": [
            {"start": s.start_time, "end": s.end_time, "text": s.text}
            for s in segments
        ],
    }