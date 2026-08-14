import subprocess
import tempfile
import os
import logging

import whisper

logger = logging.getLogger(__name__)

model = whisper.load_model("base")


def capture_and_transcribe(stream_url, chunk_seconds=15):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        proc = subprocess.run(
            [
                    "ffmpeg", "-y",
                    "-fflags", "nobuffer+discardcorrupt",
                    "-flags", "low_delay",
                    "-rtbufsize", "32",
                    "-i", stream_url,
                    "-ss", "2",
                    "-t", str(chunk_seconds),
                    "-ar", "16000",
                    "-ac", "1",
                    "-f", "wav",
                tmp_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=chunk_seconds + 15,
        )

        if proc.returncode != 0:
            logger.warning(
                "FFmpeg exited with code %d for %s: %s",
                proc.returncode,
                stream_url,
                proc.stderr.decode(errors="replace").strip(),
            )
            return None

        whisper_result = model.transcribe(tmp_path)
        text = whisper_result["text"].strip()
        return text or None

    except subprocess.TimeoutExpired:
        logger.error("FFmpeg timed out capturing from %s", stream_url)
        return None
    except FileNotFoundError:
        logger.error(
            "FFmpeg not found. Install FFmpeg and ensure it is on your PATH."
        )
        return None
    except Exception as e:
        logger.error("Transcription failed for %s: %s", stream_url, e, exc_info=True)
        return None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
