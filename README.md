# Meeting Search Service

A small backend service that transcribes meeting recordings locally with Whisper and lets you ask questions across all uploaded meetings, with answers that cite the source meeting and timestamp.

## Overview

Upload an audio recording via a REST API. The service transcribes it in the background using a local, CPU-only Whisper model, storing timestamped segments. You can then ask a question across all uploaded meetings and get back an answer extracted from the most relevant segment, citing the meeting and timestamp — with corroborating meetings surfaced too, if more than one contains relevant content — or an honest "I couldn't find this" if nothing matches well enough.

## Architecture
POST /meetings → create Meeting (status=processing) → save file under a
unique, id-based path → background task:
Whisper transcribe
→ TranscriptSegment rows
→ status=completed/failed

GET /meetings/{id}/transcript → full ordered transcript for one meeting

POST /ask → TF-IDF over all TranscriptSegments → cosine similarity ranking
→ top match above threshold: extractive answer + citation
+ other_sources (other meetings that also scored above threshold)
→ below threshold: "couldn't find this" (no citation)

- **FastAPI** — REST API framework
- **SQLite + SQLAlchemy** — `Meeting` (id, filename, status, created_at) and `TranscriptSegment` (id, meeting_id, start_time, end_time, text), one meeting → many segments
- **openai-whisper**, CPU-only — local transcription with timestamps, model size configurable
- **FastAPI BackgroundTasks** — async processing without extra infrastructure
- **scikit-learn TF-IDF + cosine similarity** — cross-meeting retrieval
- **Deterministic extractive answer model** — returns the top-scoring segment verbatim with a citation, or a fixed "couldn't find" message below a similarity threshold

## Setup (local, without Docker)

Requires Python 3.11 and `ffmpeg` installed and on PATH (Whisper shells out to it for audio decoding).

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\Activate.ps1
pip install "setuptools<82" wheel
pip install --no-build-isolation openai-whisper==20231117
pip install -r requirements.txt
uvicorn app.main:app --reload
```

> **Why the two-step whisper install:** `openai-whisper`'s packaging predates a setuptools change (v82, Feb 2026) that removed `pkg_resources`, which its legacy `setup.py` still imports. Installing `setuptools<82` and `wheel` first, then installing whisper with `--no-build-isolation`, avoids the isolated build environment picking up a too-new setuptools. See AI_LOG.md for how this was diagnosed.

Visit `http://127.0.0.1:8000/docs` for the interactive API.

## Running with Docker

```bash
docker compose up --build
```

This installs system `ffmpeg` inside the container, applies the same whisper install workaround as above, and mounts `./data` as a volume so the SQLite DB and uploads persist across restarts. A `.dockerignore` excludes `venv/` and `.git/` from the build context — without it, the build context was over 1GB and the first build took nearly an hour; with it, builds are dramatically faster. First build is still slow regardless (Whisper's `torch` dependency is large, ~125MB download plus install); subsequent builds are cached.

Verified end-to-end: built, started, and successfully processed an upload + question through the containerized service.

Once running, the API is available at `http://127.0.0.1:8000`.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/meetings` | Upload an audio file (multipart `file`); returns immediately with `status: processing` |
| `GET` | `/meetings/{id}` | Check a meeting's transcription status |
| `GET` | `/meetings/{id}/transcript` | Full ordered transcript for one meeting (404 if meeting doesn't exist, 409 if not yet completed) |
| `POST` | `/ask` | `{"question": "..."}` → answer with citation and other supporting sources, or "couldn't find" with `citation: null` |

## Example Usage

```bash
curl -X POST http://127.0.0.1:8000/meetings -F "file=@meeting.wav"
# {"id":1,"filename":"meeting.wav","status":"processing"}

curl http://127.0.0.1:8000/meetings/1
# {"id":1,"filename":"meeting.wav","status":"completed"}

curl http://127.0.0.1:8000/meetings/1/transcript
# {"meeting_id":1,"filename":"meeting.wav","segments":[{"start":0.0,"end":2.5,"text":"..."}, ...]}

curl -X POST http://127.0.0.1:8000/ask -H "Content-Type: application/json" \
  -d '{"question":"what did we decide about the launch"}'
# {"answer":"We decided to launch the project next Monday.",
#  "citation":{"meeting_id":1,"filename":"meeting.wav","start":2.56,"end":5.92},
#  "other_sources":[]}
```

## Design Decisions

- **FastAPI + BackgroundTasks over Celery/Redis:** for a single-process, single-machine service with no requirement for retries-across-restarts or distributed workers, `BackgroundTasks` gives the same "accept now, process after" behavior with zero extra infrastructure to configure or explain. Tradeoff: a crash mid-transcription loses that job with no retry, and it doesn't scale across multiple instances.
- **TF-IDF over a vector database:** at this data volume (a handful of meetings, a few dozen segments each), TF-IDF is fast, needs no extra infrastructure, and is fully explainable — a match can always be traced to shared terms. Tradeoff: it's lexical, not semantic, so it won't match a question phrased very differently from the transcript's wording. A vector DB / embeddings would be the natural upgrade at scale.
- **Deterministic extractive answers over an LLM:** the answer is always a verbatim transcript segment, so it structurally cannot hallucinate — "cites the meeting and timestamp" and "says so rather than guess" are guaranteed by design, not by prompting. The tradeoff is fluency: an LLM could paraphrase across multiple segments more naturally, at the cost of a new failure mode this version doesn't have.
- **Similarity threshold for "no answer":** the top TF-IDF cosine score is used as a crude confidence proxy. It's simple and explainable, though not a calibrated confidence measure.
- **Multiple supporting sources, not just a single winner:** `/ask` retrieves the top few candidates and surfaces other meetings that independently score above the threshold as `other_sources`, rather than silently dropping corroborating evidence when more than one meeting discusses the same topic.
- **Uploads stored by database id, not original filename:** early on, uploads were stored on disk using the client-provided filename directly. Uploading two files with the same name (a very realistic scenario — e.g. two meetings both named `standup.wav`) silently overwrote the first file's audio with the second's, while both `Meeting` rows in the database still believed they pointed to distinct, valid recordings. This caused a real, reproduced failure: a background transcription reading a file that had been overwritten mid-read, producing an incorrect or failed transcript with no indication anything was wrong. Fixed by writing each upload to a path derived from the meeting's own database id (assigned before the file is written to disk), while keeping the original filename for display purposes only. See AI_LOG.md.

## What I Left Out & Why

- Frontend, auth/accounts, PostgreSQL, Redis, Celery, Kubernetes, cloud deployment, speaker diarization, real-time streaming, multiple LLM providers, complex monitoring — all explicitly out of scope for a small, well-reasoned backend service per the brief.
- An LLM-backed answer model (e.g. via Ollama) was considered but not built — the deterministic model was prioritized as the safe default given limited time, per the brief's guidance to favor a small thing that works.

## Limitations

- TF-IDF is rebuilt from scratch on every `/ask` call rather than cached — fine at this scale, would not scale to many meetings.
- No retry if the background transcription task crashes the server process.
- The Whisper model cache isn't persisted in the Docker volume, so the container re-downloads model weights on first run after an image rebuild.
- The similarity threshold for "no answer" is a fixed default, not tuned against real meeting data.
- **`WHISPER_MODEL_SIZE` is only read once per server process**, at first model load. The loaded model is cached in a module-level variable for the lifetime of the process (intentional, to avoid reloading a large model on every request), but this means changing the environment variable while the server is already running has no effect until the process restarts. Confirmed directly while testing error handling for bad model-size values — the cached model from an earlier successful load was silently reused instead of re-attempting the load, which initially looked like the error handling wasn't working before the actual cause was identified.

## What I'd Build Next

- Swap TF-IDF for embeddings + a lightweight vector index once meeting volume grows.
- Add the LLM-backed answer model as an opt-in alternative to the extractive default, with the extractive version retained as a safe fallback if the LLM call fails.
- Persist the Whisper model cache as a Docker volume to avoid re-downloading on rebuild.
- Add retry/dead-letter handling for failed background transcriptions.
- Allow explicit model reload (e.g. an admin endpoint) rather than requiring a process restart to pick up a changed `WHISPER_MODEL_SIZE`.