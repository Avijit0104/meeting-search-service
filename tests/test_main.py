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