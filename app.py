import io
import os
import uuid
import zipfile
import threading
import subprocess
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory, abort, send_file

app = Flask(__name__)

from local_access import protect_flask
protect_flask(app)

app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024 * 1024  # 20 GB

UPLOAD_FOLDER = Path('uploads')
OUTPUT_FOLDER = Path('output')
UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)

jobs: dict = {}
jobs_lock = threading.Lock()
whisper_models: dict = {}
whisper_lock = threading.Lock()


# ── helpers ──────────────────────────────────────────────────────────────────

def update_job(job_id: str, **kwargs):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(kwargs)


def check_ffmpeg() -> bool:
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_whisper_model(model_size: str):
    with whisper_lock:
        if model_size not in whisper_models:
            import whisper
            whisper_models[model_size] = whisper.load_model(model_size)
        return whisper_models[model_size]


# ── background workers ───────────────────────────────────────────────────────

def convert_audio_job(job_id: str, input_path: Path,
                      output_format: str, original_name: str):
    try:
        update_job(job_id, status='processing', progress=20,
                   status_text='Конвертация аудио...')

        stem = Path(original_name).stem
        output_filename = f"{stem}_{job_id[:8]}.{output_format}"
        output_path = OUTPUT_FOLDER / output_filename

        codec_map = {
            'mp3':  ['-acodec', 'libmp3lame', '-q:a', '2'],
            'wav':  ['-acodec', 'pcm_s16le'],
            'ogg':  ['-acodec', 'libvorbis', '-q:a', '4'],
            'flac': ['-acodec', 'flac'],
            'm4a':  ['-acodec', 'aac', '-b:a', '192k'],
        }
        codec_args = codec_map.get(output_format, ['-acodec', 'libmp3lame', '-q:a', '2'])
        cmd = ['ffmpeg', '-i', str(input_path), '-vn'] + codec_args + [str(output_path), '-y']

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode == 0:
            update_job(job_id, status='done', progress=100,
                       result_filename=output_filename, result_type='audio')
        else:
            err = result.stderr[-500:] if result.stderr else 'FFmpeg error'
            update_job(job_id, status='error', error=err)

    except subprocess.TimeoutExpired:
        update_job(job_id, status='error', error='Превышено время конвертации (10 мин)')
    except Exception as exc:
        update_job(job_id, status='error', error=str(exc))
    finally:
        try:
            os.remove(input_path)
        except Exception:
            pass


def convert_text_job(job_id: str, input_path: Path, language: str,
                     model_size: str, original_name: str):
    temp_wav: Path | None = None
    try:
        update_job(job_id, status='processing', progress=5,
                   status_text='Извлечение аудио...')

        temp_wav = OUTPUT_FOLDER / f"{job_id}_temp.wav"
        cmd = [
            'ffmpeg', '-i', str(input_path),
            '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1',
            str(temp_wav), '-y'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            update_job(job_id, status='error',
                       error='Не удалось извлечь аудио: ' + result.stderr[-300:])
            return

        update_job(job_id, progress=25,
                   status_text=f'Загрузка модели Whisper ({model_size})…')
        model = get_whisper_model(model_size)

        update_job(job_id, progress=45, status_text='Транскрибирование…')
        transcription = model.transcribe(
            str(temp_wav),
            language=language if language != 'auto' else None,
            verbose=False,
        )

        text = transcription['text'].strip()
        stem = Path(original_name).stem
        output_filename = f"{stem}_{job_id[:8]}.txt"
        output_path = OUTPUT_FOLDER / output_filename
        output_path.write_text(text, encoding='utf-8')

        update_job(job_id, status='done', progress=100,
                   result_filename=output_filename,
                   result_type='text',
                   text_preview=text[:800])

    except Exception as exc:
        update_job(job_id, status='error', error=str(exc))
    finally:
        try:
            os.remove(input_path)
        except Exception:
            pass
        if temp_wav:
            try:
                os.remove(temp_wav)
            except Exception:
                pass


# ── routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/convert/audio', methods=['POST'])
def convert_audio():
    if not check_ffmpeg():
        return jsonify({
            'error': 'FFmpeg не найден. Скачайте: https://ffmpeg.org/download.html '
                     'и добавьте в PATH'
        }), 500

    if 'file' not in request.files or not request.files['file'].filename:
        return jsonify({'error': 'Файл не выбран'}), 400

    file = request.files['file']
    output_format = request.form.get('format', 'mp3')
    if output_format not in ('mp3', 'wav', 'ogg', 'flac', 'm4a'):
        output_format = 'mp3'

    job_id = str(uuid.uuid4())
    ext = Path(file.filename).suffix
    input_path = UPLOAD_FOLDER / f"{job_id}{ext}"
    file.save(str(input_path))

    with jobs_lock:
        jobs[job_id] = {'status': 'queued', 'progress': 0, 'status_text': 'В очереди…'}

    threading.Thread(
        target=convert_audio_job,
        args=(job_id, input_path, output_format, file.filename),
        daemon=True,
    ).start()

    return jsonify({'job_id': job_id})


@app.route('/convert/text', methods=['POST'])
def convert_text():
    if not check_ffmpeg():
        return jsonify({'error': 'FFmpeg не найден'}), 500

    try:
        import whisper  # noqa: F401
    except ImportError:
        return jsonify({
            'error': 'Библиотека openai-whisper не установлена. '
                     'Запустите: pip install openai-whisper'
        }), 500

    if 'file' not in request.files or not request.files['file'].filename:
        return jsonify({'error': 'Файл не выбран'}), 400

    file = request.files['file']
    language = request.form.get('language', 'auto')
    model_size = request.form.get('model', 'base')
    if model_size not in ('tiny', 'base', 'small', 'medium', 'large'):
        model_size = 'base'

    job_id = str(uuid.uuid4())
    ext = Path(file.filename).suffix
    input_path = UPLOAD_FOLDER / f"{job_id}{ext}"
    file.save(str(input_path))

    with jobs_lock:
        jobs[job_id] = {'status': 'queued', 'progress': 0, 'status_text': 'В очереди…'}

    threading.Thread(
        target=convert_text_job,
        args=(job_id, input_path, language, model_size, file.filename),
        daemon=True,
    ).start()

    return jsonify({'job_id': job_id})


@app.route('/status/<job_id>')
def get_status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if job is None:
        return jsonify({'status': 'not_found'}), 404
    return jsonify(job)


@app.route('/download/<path:filename>')
def download_file(filename: str):
    safe_name = Path(filename).name
    filepath = OUTPUT_FOLDER / safe_name
    if not filepath.exists():
        abort(404)
    return send_from_directory(OUTPUT_FOLDER.resolve(), safe_name, as_attachment=True)


@app.route('/download-zip', methods=['POST'])
def download_zip():
    data = request.get_json(silent=True) or {}
    filenames: list[str] = data.get('filenames', [])

    if not filenames:
        return jsonify({'error': 'Нет файлов'}), 400

    buf = io.BytesIO()
    added = 0
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for raw in filenames:
            safe = Path(raw).name
            path = OUTPUT_FOLDER / safe
            if path.exists():
                zf.write(path, safe)
                added += 1

    if added == 0:
        return jsonify({'error': 'Файлы не найдены'}), 404

    buf.seek(0)
    return send_file(
        buf,
        mimetype='application/zip',
        as_attachment=True,
        download_name='mediaconverter_results.zip',
    )


@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': 'Файл слишком большой. Максимум — 4 ГБ.'}), 413


@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': f'Внутренняя ошибка сервера: {e}'}), 500


if __name__ == '__main__':
    print('=' * 55)
    print('  MediaConverter zapushchen!')
    print('  Otkroi v brauzere: http://localhost:7832')
    print('=' * 55)
    app.run(debug=False, port=7832, threaded=True)
