from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
import app.main as main_module

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    main_module.app.dependency_overrides[get_db] = override_get_db
    main_module.SessionLocal = TestingSessionLocal  # redirect background task's DB access too
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(main_module.app)

FAKE_SEGMENTS = [
    {"start": 0.0, "end": 2.5, "text": "This is a test meeting recording."},
    {"start": 2.5, "end": 6.0, "text": "We decided to launch the project next Monday."},
    {"start": 6.0, "end": 9.5, "text": "Action item, John will send the budget report by Friday."},
]


@patch("app.main.transcribe_audio")
def test_upload_returns_processing_or_completed(mock_transcribe):
    mock_transcribe.return_value = FAKE_SEGMENTS
    response = client.post("/meetings", files={"file": ("test.wav", b"fake", "audio/wav")})
    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "test.wav"
    assert data["status"] in ("processing", "completed")


@patch("app.main.transcribe_audio")
def test_mocked_transcription_creates_segments(mock_transcribe):
    mock_transcribe.return_value = FAKE_SEGMENTS
    response = client.post("/meetings", files={"file": ("test.wav", b"fake", "audio/wav")})
    meeting_id = response.json()["id"]

    detail = client.get(f"/meetings/{meeting_id}")
    assert detail.json()["status"] == "completed"

    db = TestingSessionLocal()
    segments = db.query(main_module.models.TranscriptSegment).filter(
        main_module.models.TranscriptSegment.meeting_id == meeting_id
    ).all()
    db.close()
    assert len(segments) == 3


@patch("app.main.transcribe_audio")
def test_retrieval_finds_relevant_segment(mock_transcribe):
    mock_transcribe.return_value = FAKE_SEGMENTS
    client.post("/meetings", files={"file": ("test.wav", b"fake", "audio/wav")})

    from app.services.retrieval import retrieve_relevant_segments
    db = TestingSessionLocal()
    results = retrieve_relevant_segments("what did we decide about launch", db)
    db.close()

    assert len(results) > 0
    assert "launch" in results[0]["text"].lower()


@patch("app.main.transcribe_audio")
def test_ask_returns_answer_with_citation(mock_transcribe):
    mock_transcribe.return_value = FAKE_SEGMENTS
    client.post("/meetings", files={"file": ("test.wav", b"fake", "audio/wav")})

    response = client.post("/ask", json={"question": "what did we decide about the launch"})
    assert response.status_code == 200
    data = response.json()
    assert "launch" in data["answer"].lower()
    assert data["citation"] is not None
    assert data["citation"]["filename"] == "test.wav"


@patch("app.main.transcribe_audio")
def test_ask_returns_no_answer_for_unrelated_question(mock_transcribe):
    mock_transcribe.return_value = FAKE_SEGMENTS
    client.post("/meetings", files={"file": ("test.wav", b"fake", "audio/wav")})

    response = client.post("/ask", json={"question": "what is the weather in paris"})
    assert response.status_code == 200
    data = response.json()
    assert data["citation"] is None
    assert "couldn't find" in data["answer"].lower()


@patch("app.main.transcribe_audio")
def test_transcript_returns_segments_in_order(mock_transcribe):
    mock_transcribe.return_value = FAKE_SEGMENTS
    response = client.post("/meetings", files={"file": ("test.wav", b"fake", "audio/wav")})
    meeting_id = response.json()["id"]

    transcript = client.get(f"/meetings/{meeting_id}/transcript")
    assert transcript.status_code == 200
    data = transcript.json()
    assert data["meeting_id"] == meeting_id
    assert len(data["segments"]) == 3
    # confirm chronological order
    starts = [s["start"] for s in data["segments"]]
    assert starts == sorted(starts)


def test_transcript_404_for_nonexistent_meeting():
    response = client.get("/meetings/99999/transcript")
    assert response.status_code == 404


@patch("app.main.transcribe_audio")
def test_transcript_409_when_not_completed(mock_transcribe):
    # simulate a meeting stuck in "processing" by not letting the background task run fully —
    # easiest way: query the DB right after upload, before checking status
    mock_transcribe.return_value = FAKE_SEGMENTS
    response = client.post("/meetings", files={"file": ("test.wav", b"fake", "audio/wav")})
    meeting_id = response.json()["id"]

    # manually force status back to "processing" to simulate the in-flight state,
    # since TestClient runs background tasks synchronously so it's already "completed" by now
    db = TestingSessionLocal()
    meeting = db.query(main_module.models.Meeting).filter(
        main_module.models.Meeting.id == meeting_id
    ).first()
    meeting.status = "processing"
    db.commit()
    db.close()

    transcript = client.get(f"/meetings/{meeting_id}/transcript")
    assert transcript.status_code == 409



@patch("app.main.transcribe_audio")
def test_other_sources_includes_second_meeting_when_relevant(mock_transcribe):
    # Meeting 1: launch decision
    mock_transcribe.return_value = [
        {"start": 0.0, "end": 3.0, "text": "We decided to launch the product next week."},
    ]
    client.post("/meetings", files={"file": ("meeting1.wav", b"fake", "audio/wav")})

    # Meeting 2: also discusses launch, different meeting
    mock_transcribe.return_value = [
        {"start": 0.0, "end": 3.0, "text": "The launch date was confirmed for next week."},
    ]
    client.post("/meetings", files={"file": ("meeting2.wav", b"fake", "audio/wav")})

    response = client.post("/ask", json={"question": "when is the launch"})
    assert response.status_code == 200
    data = response.json()

    assert data["citation"] is not None
    assert "other_sources" in data
    # both meetings discuss launch — expect the second to show up as a supporting source
    all_filenames = {data["citation"]["filename"]} | {s["filename"] for s in data["other_sources"]}
    assert "meeting1.wav" in all_filenames
    assert "meeting2.wav" in all_filenames


@patch("app.main.transcribe_audio")
def test_other_sources_empty_when_only_one_meeting_matches(mock_transcribe):
    mock_transcribe.return_value = FAKE_SEGMENTS
    client.post("/meetings", files={"file": ("test.wav", b"fake", "audio/wav")})

    response = client.post("/ask", json={"question": "what did we decide about the launch"})
    data = response.json()

    assert data["citation"] is not None
    assert data["other_sources"] == []

@patch("app.main.transcribe_audio")
def test_same_filename_uploaded_twice_does_not_collide(mock_transcribe):
    # First upload: distinct content
    mock_transcribe.return_value = [
        {"start": 0.0, "end": 2.0, "text": "This is the first meeting content."},
    ]
    r1 = client.post("/meetings", files={"file": ("duplicate.wav", b"fake1", "audio/wav")})
    id1 = r1.json()["id"]

    # Second upload, same original filename, different content
    mock_transcribe.return_value = [
        {"start": 0.0, "end": 2.0, "text": "This is the second meeting content."},
    ]
    r2 = client.post("/meetings", files={"file": ("duplicate.wav", b"fake2", "audio/wav")})
    id2 = r2.json()["id"]

    assert id1 != id2

    t1 = client.get(f"/meetings/{id1}/transcript").json()
    t2 = client.get(f"/meetings/{id2}/transcript").json()

    # each meeting must have kept its own distinct content, not the other's
    assert t1["segments"][0]["text"] == "This is the first meeting content."
    assert t2["segments"][0]["text"] == "This is the second meeting content."