from sqlalchemy.orm import Session
from app.config import settings
from app.services.retrieval import retrieve_relevant_segments

def generate_answer(query: str, db: Session) -> dict:
    results = retrieve_relevant_segments(query, db, top_k=1)

    if not results or results[0]["score"] < settings.ANSWER_SIMILARITY_THRESHOLD:
        return {
            "answer": "I couldn't find this information in the uploaded meetings.",
            "citation": None,
        }

    top = results[0]
    return {
        "answer": top["text"],
        "citation": {
            "meeting_id": top["meeting_id"],
            "filename": top["filename"],
            "start": top["start"],
            "end": top["end"],
        },
    }