import subprocess
import whisper
import numpy as np
import tempfile
import os

model = whisper.load_model("base")

def capture_and_transcribe(stream_url, chunk_seconds=15):
    """Capture audio from a radio stream and transcribe it."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        # Use ffmpeg to grab a chunk of audio from the stream
        subprocess.run([
            "ffmpeg", "-y",
            "-i", stream_url,
            "-t", str(chunk_seconds),
            "-ar", "16000",
            "-ac", "1",
            "-f", "wav",
            tmp_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Transcribe with Whisper
        result = model.transcribe(tmp_path)
        return result["text"].strip()

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)