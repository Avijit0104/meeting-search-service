from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy.orm import Session
from app import models

def retrieve_relevant_segments(query: str, db: Session, top_k: int = 3) -> list[dict]:
    segments = db.query(models.TranscriptSegment).join(models.Meeting).filter(
        models.Meeting.status == "completed"
    ).all()

    if not segments:
        return []

    texts = [seg.text for seg in segments]
    vectorizer = TfidfVectorizer(stop_words="english")
    tfidf_matrix = vectorizer.fit_transform(texts)
    query_vec = vectorizer.transform([query])

    similarities = cosine_similarity(query_vec, tfidf_matrix)[0]

    ranked = sorted(
        zip(segments, similarities), key=lambda pair: pair[1], reverse=True
    )

    return [
        {
            "meeting_id": seg.meeting_id,
            "filename": seg.meeting.filename,
            "start": seg.start_time,
            "end": seg.end_time,
            "text": seg.text,
            "score": float(score),
        }
        for seg, score in ranked[:top_k]
        if score > 0
    ]
    