# Media Converter

Media Converter turns uploaded video into downloadable audio through a compact local interface. Background jobs keep conversion progress visible, while an optional Whisper integration adds speech transcription.

## Features

- Extract MP3 audio from uploaded video.
- Expose background conversion progress in the web interface.
- Download completed results from the same workflow.
- Provide an optional Whisper transcription path.

## How it works

Flask receives uploads and tracks background jobs. FFmpeg performs the conversion work; Whisper is loaded for speech transcription.

**Stack:** Python · Flask · FFmpeg · Whisper

## Getting started

Use Python 3.12 and a separate virtual environment. Run the following commands from this repository's root in Windows PowerShell.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-local.txt
```

Install FFmpeg and ffprobe on PATH. `requirements-local.txt` covers audio extraction; optional transcription uses the Whisper dependencies in `requirements.txt` and downloads model weights.

### Start the application

Open http://127.0.0.1:7832. Install FFmpeg and ffprobe on PATH. Whisper model downloads are needed only for transcription.

```powershell
python app.py
```

## Example workflow

Upload a short MP4, convert it to MP3, then download and play the audio.

## Testing and limitations

MP4-to-MP3 conversion and the output download route were checked with real media. Optional Whisper transcription was not run.

See [Verification](VERIFICATION.md) for the recorded checks and [Limitations](LIMITATIONS.md) for integration requirements.

## Configuration and security

Keep web services bound to `127.0.0.1`. Hosting this application for multiple users requires authentication and separate storage and resource limits. Configure your own provider credentials when a feature requires them; credentials and personal data are not included. See [Security](SECURITY.md) for local configuration and reporting guidance.
