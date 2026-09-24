from sqlalchemy.orm import Session
from app.config import settings
from app.services.retrieval import retrieve_relevant_segments

def generate_answer(query: str, db: Session) -> dict:
    results = retrieve_relevant_segments(query, db, top_k=5)

    strong_results = [r for r in results if r["score"] >= settings.ANSWER_SIMILARITY_THRESHOLD]

    if not strong_results:
        return {
            "answer": "I couldn't find this information in the uploaded meetings.",
            "citation": None,
            "other_sources": [],
        }

    top = strong_results[0]
    primary_citation = {
        "meeting_id": top["meeting_id"],
        "filename": top["filename"],
        "start": top["start"],
        "end": top["end"],
    }

    other_sources = []
    seen_meetings = {top["meeting_id"]}
    for r in strong_results[1:]:
        if r["meeting_id"] not in seen_meetings:
            other_sources.append({
                "meeting_id": r["meeting_id"],
                "filename": r["filename"],
                "start": r["start"],
                "end": r["end"],
                "text": r["text"],
            })
            seen_meetings.add(r["meeting_id"])

    return {
        "answer": top["text"],
        "citation": primary_citation,
        "other_sources": other_sources,
    }