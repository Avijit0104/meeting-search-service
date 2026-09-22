from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from app.database import Base, engine, get_db
from app import models

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Meeting Search Service")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/meetings")
def upload_meeting():
    # stub — real upload + background processing comes in Phase 3/4
    return {"message": "not implemented yet"}

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