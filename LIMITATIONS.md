# Limitations and integration requirements

MP4-to-MP3 conversion and the output download route were checked with real media. Optional Whisper transcription was not run.

Install FFmpeg and ffprobe on PATH. `requirements-local.txt` covers audio extraction; optional transcription uses the Whisper dependencies in `requirements.txt` and downloads model weights.

Keep web services bound to `127.0.0.1`. Hosting this application for multiple users requires authentication and separate storage and resource limits.
