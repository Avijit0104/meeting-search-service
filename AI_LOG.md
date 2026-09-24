# AI Usage Log

I used Claude throughout this build as a pair-programmer: working phase by phase against a fixed schedule, writing code in small reviewable chunks, and diagnosing errors from actual terminal output rather than guessing fixes. Below are the most substantial times it got something wrong, and how I worked through them.

## 1. Whisper's `pkg_resources` build failure — first fix didn't work

Early in setup, `pip install openai-whisper` failed with `ModuleNotFoundError: No module named 'pkg_resources'` during the build step. I correctly diagnosed the root cause: setuptools v82.0.0 (Feb 2026) removed `pkg_resources`, and `openai-whisper`'s legacy `setup.py` still imports it.

Claude's first proposed fix was pinning `setuptools<82` via a `PIP_CONSTRAINT` environment variable, reasoning that pip's build-isolation subprocess would inherit it. It didn't — the constraint never reached the isolated build environment in practice, and the same error recurred with a couple of different approaches to setting it.

The actual fix required a different mechanism: pre-installing `setuptools<82` and `wheel` directly into the active environment, then installing `openai-whisper` with `--no-build-isolation` so the build used that environment instead of a fresh isolated one. This worked immediately, and the same sequence was baked directly into the Dockerfile so it wouldn't need rediscovering there — and it didn't recur.

## 2. A real, reproduced data-corruption bug: uploads overwriting each other by filename

Originally, uploaded files were saved to disk using the client-provided filename directly (`data/uploads/<original filename>`). This meant uploading two files with the same name — a realistic scenario, e.g. two different meetings both exported as `standup.wav` — silently overwrote the first file's audio with the second's on disk, while the database still held two separate `Meeting` rows that both believed they pointed to valid, distinct recordings.

This wasn't caught in review — it took deliberately uploading the same filename twice in a row to reproduce. The result was concrete and visible: one meeting ended up with status `"failed"` (its background task tried to read audio that had already been overwritten mid-read), and two other meetings with the same filename had subtly different, partially garbled transcripts of what should have been identical content — clear evidence of the underlying file changing while transcription was in progress. Diagnosed by comparing file sizes and modification timestamps in the uploads directory against the corrupted transcript content.

The fix was to store each upload under a path derived from the meeting's own database id — created first, before the file write — rather than the original filename, while keeping the original filename in the database purely for display. Re-ran the exact same duplicate-upload scenario afterward to confirm both files persisted independently and both transcripts came back complete and identical, then added a regression test that asserts two same-named uploads keep distinct content.

## 3. A test that forgot to mock — caught immediately by running it

While adding validation to reject non-audio uploads, I wrote a test to confirm a `.wav` file with a generic `application/octet-stream` content-type was still accepted. The test itself omitted the `@patch("app.main.transcribe_audio")` decorator that every other test uses, so it exercised real Whisper against fake placeholder bytes (`b"fakebytes"`) and failed with a real `ffmpeg` decode error — not a bug in the application, just a missing mock in the test. Fixed by adding the decorator; the test then passed as intended.

## Other notes

Beyond these, most other AI-assisted moments were straightforward diagnosis-from-error-output (a missing `ffmpeg` on PATH across three different terminal sessions on a machine switch, a `.dockerignore`-less Docker build transferring a 1GB context including `venv/`, a WSL2 backend requiring installation before Docker Desktop would run) rather than the AI being wrong per se — environment friction on an unfamiliar/borrowed machine more than logic errors.